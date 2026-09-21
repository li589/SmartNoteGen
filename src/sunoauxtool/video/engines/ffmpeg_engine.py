"""FFmpeg 原生渲染引擎（v0.2.0 W1+W2+W3）。

能力：
- showwaves / showspectrum：波形、频谱（原生滤镜，快）
- 背景叠加：PIL Image → 临时 PNG → filter_complex overlay 双输入
- 文字叠加：drawtext（微软雅黑，淡入淡出 alpha 表达式）

已验证语法（ffmpeg N-125328 / 2026 dev build）：
- 音频绑定：[0:a]showwaves=s=WxH:scale=lin[viz]
- 背景叠加：[1:v][viz]overlay=0:0[v]
- 中文文字：drawtext=fontfile='C\\:/Windows/Fonts/msyh.ttc':text='...':...
  （Windows 盘符冒号必须转义为 \\:）
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

from PIL import Image

from sunoauxtool.video.config import Config
from sunoauxtool.video.exceptions import FFmpegNotFoundError, RenderError


def _escape_drawtext(text: str) -> str:
    """转义 drawtext 文本（单引号、冒号、分号、反斜杠）。"""
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace(";", "\\;")
    text = text.replace("'", "\\'")
    return text


def _escape_fontfile(path: str) -> str:
    """Windows 字体路径转义（C:\\ → C\\:）。"""
    return path.replace("\\", "/").replace(":", "\\:")


class FFmpegEngine:
    """FFmpeg 原生渲染引擎。"""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._ffmpeg_path = self._resolve_ffmpeg()

    def _resolve_ffmpeg(self) -> str:
        """解析 ffmpeg 可执行文件路径。"""
        path = self.config.paths.ffmpeg or "ffmpeg"
        try:
            result = subprocess.run([path, "-version"], capture_output=True, timeout=5)
            if result.returncode != 0:
                raise FFmpegNotFoundError()
        except FileNotFoundError:
            raise FFmpegNotFoundError()
        return path

    # -- 滤镜构建 -----------------------------------------------------------

    def build_showwaves_filter(self, width: int, height: int, scale: str = "lin") -> str:
        """showwaves 滤镜（新版语法）。"""
        return f"showwaves=s={width}x{height}:scale={scale}"

    def build_showspectrum_filter(
        self, width: int, height: int, mode: str = "combined", scale: str = "log",
    ) -> str:
        """showspectrum 滤镜（新版语法）。"""
        return f"showspectrum=s={width}x{height}:mode={mode}:scale={scale}"

    def _build_drawtext_chain(
        self,
        title: str,
        subtitle: str,
        height: int,
    ) -> str:
        """构建标题/副标题 drawtext 链（前 3s 淡入淡出）。

        alpha 表达式：0-1s 淡入，2-3s 淡出：
        alpha='if(lt(t,1),t,if(lt(t,2),1,(3-t)/2))'
        """
        chain_parts: List[str] = []
        title_size = int(height * 0.05)
        sub_size = int(height * 0.03)
        alpha_expr = "if(lt(t\\,1)\\,t\\,if(lt(t\\,2)\\,1\\,(3-t)/2))"

        font = self._find_font()
        if not font:
            return ""

        if title:
            t = _escape_drawtext(title)
            chain_parts.append(
                f"drawtext=fontfile='{_escape_fontfile(font)}':text='{t}'"
                f":fontsize={title_size}:fontcolor=white"
                f":x=(w-text_w)/2:y=h*0.30:alpha='{alpha_expr}'"
            )
        if subtitle:
            t = _escape_drawtext(subtitle)
            chain_parts.append(
                f"drawtext=fontfile='{_escape_fontfile(font)}':text='{t}'"
                f":fontsize={sub_size}:fontcolor=white@0.85"
                f":x=(w-text_w)/2:y=h*0.30+{title_size}+30:alpha='{alpha_expr}'"
            )
        return ",".join(chain_parts)

    def _find_font(self) -> Optional[str]:
        """查找可用中文字体（微软雅黑 → 黑体）。"""
        for p in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]:
            if Path(p).exists():
                return p
        return None

    def _prepare_logo(
        self,
        width: int,
        height: int,
        output_path: str,
    ) -> Optional[tuple]:
        """预处理 logo：缩放 + 定位 + 落盘临时 PNG。

        Returns:
            (logo_png_path, (x, y)) 或 None（未配置 logo）。
        """
        logo_cfg = self.config.logo
        if not logo_cfg.path or not Path(logo_cfg.path).exists():
            return None

        logo = Image.open(logo_cfg.path).convert("RGBA")
        # 按比例缩放（宽度 = 视频宽 × scale）；强制偶数尺寸（yuv420p 要求）
        target_w = int(width * logo_cfg.scale) // 2 * 2
        ratio = target_w / logo.width
        target_h = int(logo.height * ratio) // 2 * 2
        logo = logo.resize((target_w, target_h), Image.LANCZOS)

        # 透明度
        if logo_cfg.opacity < 1.0:
            alpha = logo.getchannel("A").point(lambda a: int(a * logo_cfg.opacity))
            logo.putalpha(alpha)

        # 定位
        m = logo_cfg.margin
        if logo_cfg.position == "top-left":
            xy = (m, m)
        elif logo_cfg.position == "top-right":
            xy = (width - target_w - m, m)
        elif logo_cfg.position == "bottom-left":
            xy = (m, height - target_h - m)
        else:  # bottom-right
            xy = (width - target_w - m, height - target_h - m)

        tmp_logo = str(Path(output_path).parent / ".tmp_logo.png")
        logo.save(tmp_logo, "PNG")
        return tmp_logo, xy

    # -- 渲染 -----------------------------------------------------------------

    def render(
        self,
        audio_path: str,
        output_path: str,
        *,
        visual_style: str = "waveform",
        background: Optional[Image.Image] = None,
        title: str = "",
        subtitle: str = "",
        width: Optional[int] = None,
        height: Optional[int] = None,
        fps: Optional[int] = None,
        crf: Optional[int] = None,
        preset: Optional[str] = None,
    ) -> str:
        """渲染视频（waveform / spectrum 原生滤镜 + 背景叠加 + 文字）。

        Args:
            audio_path: 音频文件路径。
            output_path: 输出视频路径。
            visual_style: waveform | spectrum。
            background: 背景图（PIL Image）；None 则不加背景。
            title: 标题文字（前 3s 淡入淡出）。
            subtitle: 副标题文字。
            width: 宽度。
            height: 高度。
            fps: 帧率。
            crf: 质量参数。
            preset: 编码预设。

        Returns:
            输出路径。
        """
        cfg = self.config
        w = width or cfg.video.width
        h = height or cfg.video.height
        fps_rate = fps or cfg.video.fps
        crf_val = crf or cfg.video.crf
        preset_val = preset or cfg.video.preset

        # 1. 可视化滤镜
        if visual_style == "spectrum":
            viz = self.build_showspectrum_filter(w, h)
        else:
            viz = self.build_showwaves_filter(w, h)

        # 2. 文字链
        text_chain = self._build_drawtext_chain(title, subtitle, h)

        # 3. 背景临时 PNG（W2）+ Logo 预处理（W3）
        bg_path: Optional[str] = None
        logo_path: Optional[str] = None
        tmp_files: List[Path] = []
        if background is not None:
            bg_path = str(Path(output_path).parent / ".tmp_bg.png")
            background.save(bg_path, "PNG")
            tmp_files.append(Path(bg_path))
        logo_overlay = self._prepare_logo(w, h, output_path)
        if logo_overlay is not None:
            logo_path, logo_xy = logo_overlay
            tmp_files.append(Path(logo_path))

        # 4. 组装 filter_complex（分步：可视化 → 背景overlay → logo overlay → 文字）
        try:
            parts: List[str] = []
            inputs: List[str] = ["-i", audio_path]

            # 视频链起点
            if bg_path:
                # [0:a]showwaves[viz];[1:v]scale[vbg];[vbg][viz]overlay=[base]
                parts.append(f"[0:a]{viz}[viz]")
                parts.append(f"[1:v]scale={w}:{h}:flags=lanczos,setsar=1[vbg]")
                parts.append("[vbg][viz]overlay=0:0[base]")
                inputs += ["-i", bg_path]  # 单帧图片（不用 -loop，避免新版 ffmpeg 死锁）
            else:
                parts.append(f"[0:a]{viz}[base]")

            # Logo overlay（注意：overlay 第一个输入是底图，第二个是叠加层 logo）
            last_label = "base"
            if logo_path:
                logo_idx = 1 if not bg_path else 2
                parts.append(
                    f"[{last_label}][{logo_idx}:v]overlay={logo_xy[0]}:{logo_xy[1]}[withlogo]"
                )
                last_label = "withlogo"
                inputs += ["-i", logo_path]  # 单帧图片（不用 -loop）

            # 文字（最后叠加；链尾强制 format=yuv420p，解决 overlay/drawtext 后格式协商失败）
            if text_chain:
                parts.append(f"[{last_label}]{text_chain},format=yuv420p[v]")
            else:
                parts.append(f"[{last_label}]format=yuv420p[v]")

            fc = ";".join(parts)
            cmd = [
                self._ffmpeg_path,
                "-y",
                *inputs,
                "-filter_complex", fc,
                "-map", "[v]",
                "-map", "0:a:0",
                "-c:v", "libx264",
                "-preset", preset_val,
                "-crf", str(crf_val),
                "-pix_fmt", "yuv420p",
                "-r", str(fps_rate),
                "-shortest",
                output_path,
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                raise RenderError(
                    f"ffmpeg 渲染失败（exit code {result.returncode}）:\n{result.stderr[-1000:]}",
                    exit_code=result.returncode,
                )
        except subprocess.TimeoutExpired:
            raise RenderError("ffmpeg 渲染超时（10分钟）")
        finally:
            for f in tmp_files:
                try:
                    f.unlink()
                except OSError:
                    pass

        return output_path
