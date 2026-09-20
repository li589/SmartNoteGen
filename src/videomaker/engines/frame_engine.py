"""PIL 逐帧渲染引擎（v0.2.0 W1 + W4 rawvideo 提速）。

职责：
- 调用 analyze() 一次预计算 → 构建 VisualContext
- 注入背景帧（渐变/纯色/图片）
- 逐帧调用 Visualizer.render_frame()（查表渲染，无重计算）
- 文字叠加（PIL ImageDraw，微软雅黑默认）
- rawvideo 管道直写 ffmpeg stdin（零 PNG 中间文件，见 _encode_pipe）
- stderr 用线程持续排空，避免管道缓冲死锁（ffmpeg 大量进度输出）
- 无临时帧目录，故不再需要 _force_remove_tree

适用风格：circular_spectrum / reactive（创意层）
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from videomaker.analysis import analyze
from videomaker.config import Config
from videomaker.exceptions import FFmpegNotFoundError, RenderError
from videomaker.visuals.base import VisualContext, Visualizer


class FrameEngine:
    """PIL 逐帧渲染引擎。"""

    def __init__(self, config: Config) -> None:
        self.config = config

    def render_with_visualizer(
        self,
        visualizer: Visualizer,
        audio_path: str,
        output_path: str,
        *,
        background: Optional[Image.Image] = None,
        font_path: Optional[str] = None,
        title: str = "",
        subtitle: str = "",
        render_scale: float = 0.5,
        analysis=None,
    ) -> str:
        """渲染创意层视频（rawvideo 管道，零 PNG 中间文件）。

        Args:
            visualizer: PIL 创意层 Visualizer 实例。
            audio_path: 音频文件路径（ffmpeg 合成音轨用）。
            output_path: 输出 MP4 路径。
            background: 背景图（PIL Image，已按目标尺寸缩放）；None 用纯色。
            font_path: 字体文件路径；None 时尝试微软雅黑。
            title: 标题文字（空则不绘制）。
            subtitle: 副标题文字。
            render_scale: 临时帧缩放比例（默认 0.5 → 内部用半分辨率渲染，
                管道端 scale 上采样到目标尺寸，避免大帧 PNG 编码瓶颈）。
            analysis: 预计算 AudioAnalysis（v0.3：多轨模式下由调用方传入
                analyze_multitrack 结果；None 时内部 analyze(audio_path)）。

        Returns:
            输出路径。
        """
        cfg = self.config
        w, h, fps = cfg.video.width, cfg.video.height, cfg.video.fps
        rw, rh = int(w * render_scale), int(h * render_scale)

        # 1. 预计算一次（全帧共享；多轨模式外部注入）
        if analysis is None:
            analysis = analyze(audio_path, fps=fps)

        # 2. 背景帧（按渲染分辨率缩放，注入 ctx）
        if background is not None:
            bg = background.resize((rw, rh), Image.LANCZOS).convert("RGB")
            bg_array = np.array(bg)
        else:
            bg_array = np.full((rh, rw, 3), (26, 26, 46), dtype=np.uint8)

        # 3. 构建上下文（用渲染分辨率）
        ctx = VisualContext(width=rw, height=rh, fps=fps, analysis=analysis, background=bg_array)

        # 4. 字体（按渲染分辨率）
        font = self._load_font(font_path, size=int(rh * 0.05))
        sub_font = self._load_font(font_path, size=int(rh * 0.03))

        # 4.5 Logo 预处理（W3：PIL 路径水印）
        logo_img = self._prepare_logo(rw, rh)

        # 5. 逐帧渲染 → rawvideo 管道直写 ffmpeg
        self._encode_pipe(
            visualizer=visualizer,
            ctx=ctx,
            audio_path=audio_path,
            output_path=output_path,
            fps=fps,
            render_w=rw, render_h=rh, target_w=w, target_h=h,
            font=font, sub_font=sub_font, title=title, subtitle=subtitle,
            logo_img=logo_img,
        )

        return output_path

    def _prepare_logo(self, render_w: int, render_h: int) -> Optional[Image.Image]:
        """预处理 logo（PIL 路径）：缩放到渲染分辨率 + 定位。None = 无 logo。"""
        logo_cfg = self.config.logo
        if not logo_cfg.path or not Path(logo_cfg.path).exists():
            return None
        logo = Image.open(logo_cfg.path).convert("RGBA")
        target_w = int(render_w * logo_cfg.scale) // 2 * 2
        ratio = target_w / logo.width
        target_h = int(logo.height * ratio) // 2 * 2
        logo = logo.resize((target_w, target_h), Image.LANCZOS)
        if logo_cfg.opacity < 1.0:
            alpha = logo.getchannel("A").point(lambda a: int(a * logo_cfg.opacity))
            logo.putalpha(alpha)
        return logo

    def _paste_logo(self, img: Image.Image, logo: Image.Image) -> Image.Image:
        """把 logo 粘贴（alpha 合成）到帧的四角位置。"""
        logo_cfg = self.config.logo
        m = logo_cfg.margin
        w, h = img.size
        lw, lh = logo.size
        if logo_cfg.position == "top-left":
            xy = (m, m)
        elif logo_cfg.position == "top-right":
            xy = (w - lw - m, m)
        elif logo_cfg.position == "bottom-left":
            xy = (m, h - lh - m)
        else:
            xy = (w - lw - m, h - lh - m)
        img.paste(logo, xy, logo)  # 第三参数 = alpha mask
        return img

    # -- 文字 ---------------------------------------------------------------

    def _load_font(self, font_path: Optional[str], size: int) -> ImageFont.FreeTypeFont:
        """加载字体：显式路径 → 微软雅黑 → 默认位图字体。"""
        candidates = []
        if font_path:
            candidates.append(font_path)
        candidates.extend([
            r"C:\Windows\Fonts\msyh.ttc",   # 微软雅黑
            r"C:\Windows\Fonts\simhei.ttf",  # 黑体
        ])
        for p in candidates:
            if p and Path(p).exists():
                try:
                    return ImageFont.truetype(p, size)
                except OSError:
                    continue
        return ImageFont.load_default()

    def _draw_title(
        self,
        img: Image.Image,
        frame_idx: int,
        fps: int,
        title: str,
        subtitle: str,
        font: ImageFont.FreeTypeFont,
        sub_font: ImageFont.FreeTypeFont,
    ) -> Image.Image:
        """标题淡入淡出（前 3s：0-1s 淡入，2-3s 淡出）。"""
        t = frame_idx / fps
        if t > 3.0:
            return img
        alpha = min(1.0, t) if t <= 1.0 else max(0.0, 3.0 - t) / 2.0
        if alpha <= 0.01:
            return img

        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        w, h = img.size

        # 标题（居中，上 1/3 处）
        bbox = draw.textbbox((0, 0), title, font=font)
        tw = bbox[2] - bbox[0]
        a = int(255 * alpha)
        draw.text(((w - tw) / 2, h * 0.30), title, font=font, fill=(255, 255, 255, a))

        # 副标题
        if subtitle:
            bbox2 = draw.textbbox((0, 0), subtitle, font=sub_font)
            tw2 = bbox2[2] - bbox2[0]
            draw.text(((w - tw2) / 2, h * 0.30 + (bbox[3] - bbox[1]) + 20), subtitle,
                      font=sub_font, fill=(220, 220, 220, a))

        return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    # -- 编码 ---------------------------------------------------------------

    def _encode_pipe(
        self,
        *,
        visualizer: Visualizer,
        ctx: VisualContext,
        audio_path: str,
        output_path: str,
        fps: int,
        render_w: int,
        render_h: int,
        target_w: int,
        target_h: int,
        font,
        sub_font,
        title: str,
        subtitle: str,
        logo_img: Optional[Image.Image] = None,
    ) -> None:
        """rawvideo 管道：逐帧渲染直写 ffmpeg stdin（零 PNG 中间文件）。

        流程：PIL 帧 (H,W,3) uint8 → tobytes() → proc.stdin → ffmpeg
        （rawvideo 输入 + scale 上采样 + 音频合并 + x264 编码）。
        """
        cfg = self.config
        cmd = [
            cfg.paths.ffmpeg,
            "-y",
            # 视频输入：stdin rawvideo
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{render_w}x{render_h}",
            "-r", str(fps),
            "-i", "-",
            # 音频输入
            "-i", audio_path,
            # 上采样到目标尺寸
            "-filter:v", f"scale={target_w}:{target_h}:flags=lanczos",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "libx264",
            "-preset", cfg.video.preset,
            "-crf", str(cfg.video.crf),
            "-pix_fmt", "yuv420p",
            "-shortest",
            output_path,
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            raise FFmpegNotFoundError()

        # stderr 排空线程：ffmpeg 进度输出量大，不排空会填满缓冲导致写帧死锁
        stderr_chunks: list[bytes] = []
        reader = threading.Thread(
            target=lambda: stderr_chunks.append(proc.stderr.read()),
            daemon=True,
        )
        reader.start()

        try:
            n = ctx.analysis.n_frames
            for i in range(n):
                frame = visualizer.render_frame(ctx, i)
                img = Image.fromarray(frame)
                if title:
                    img = self._draw_title(img, i, fps, title, subtitle, font, sub_font)
                if logo_img is not None:
                    img = self._paste_logo(img, logo_img)
                frame = np.asarray(img)
                # 必须连续内存（PIL 数组可能非连续）
                if not frame.flags["C_CONTIGUOUS"]:
                    frame = np.ascontiguousarray(frame)
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
            proc.wait(timeout=600)
            reader.join(timeout=5)
            if proc.returncode != 0:
                stderr_text = b"".join(stderr_chunks).decode(errors="replace")
                raise RenderError(
                    f"ffmpeg 管道编码失败（exit {proc.returncode}）:\n{stderr_text[-1000:]}"
                )
        except BrokenPipeError:
            # ffmpeg 早退（参数错误等），等待 stderr 线程回传定位
            proc.wait(timeout=30)
            reader.join(timeout=5)
            stderr_text = b"".join(stderr_chunks).decode(errors="replace")
            raise RenderError(f"ffmpeg 管道中断:\n{stderr_text[-1000:]}")
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RenderError("ffmpeg 编码超时（10分钟）")
