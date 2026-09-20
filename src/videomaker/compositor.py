"""构图器（Compositor）：图层合成 + 双引擎路由（v0.2.0 W1+W2）。

路由规则：
- waveform / spectrum          → FFmpegEngine（原生滤镜，快）
- circular_spectrum / reactive → FrameEngine（PIL 创意层，灵活）

背景链路（W2 修复）：
- _render_background() 产出 PIL Image → 显式注入两引擎
- ffmpeg 路径：落盘 PNG → filter_complex overlay 双输入
- PIL 路径：直接注入 VisualContext.background
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw

from videomaker.config import Config
from videomaker.engines.ffmpeg_engine import FFmpegEngine
from videomaker.engines.frame_engine import FrameEngine
from videomaker.visuals import create_visualizer


# 走 ffmpeg 原生引擎的风格（其余走 PIL 创意层）
FFMPEG_STYLES = {"waveform", "spectrum"}


@dataclass
class Layer:
    """单个图层定义。"""
    type: str  # background | visual | text | watermark
    config: Any
    z_order: int = 0  # 叠放顺序（越大越上）


class Compositor:
    """图层合成器（双引擎路由）。"""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.ffmpeg_engine = FFmpegEngine(config)
        self.frame_engine = FrameEngine(config)

    def compose(
        self,
        audio_path: str,
        output_path: str,
        *,
        visual_style: str = "waveform",
        width: Optional[int] = None,
        height: Optional[int] = None,
        fps: Optional[int] = None,
        title: str = "",
        subtitle: str = "",
        analysis=None,
    ) -> str:
        """合成视频（双引擎路由）。

        Args:
            audio_path: 音频文件路径。
            output_path: 输出视频路径。
            visual_style: 视觉效果风格。
            width: 宽度覆盖。
            height: 高度覆盖。
            fps: 帧率覆盖。
            title: 标题文字（叠加在视频前 3s，淡入淡出）。
            subtitle: 副标题文字。
            analysis: 预计算 AudioAnalysis（v0.3 多轨模式注入；None 内部分析）。

        Returns:
            输出路径。
        """
        cfg = self.config
        w = width or cfg.video.width
        h = height or cfg.video.height
        fps_rate = fps or cfg.video.fps

        # 背景帧（W2：显式产出并注入引擎）
        background = self._render_background(w, h, cfg.background)

        # 双引擎路由（W1）
        if visual_style in FFMPEG_STYLES:
            return self.ffmpeg_engine.render(
                audio_path,
                output_path,
                visual_style=visual_style,
                background=background,
                title=title,
                subtitle=subtitle,
                width=w,
                height=h,
                fps=fps_rate,
            )
        else:
            visualizer = create_visualizer(visual_style, cfg)
            return self.frame_engine.render_with_visualizer(
                visualizer,
                audio_path,
                output_path,
                background=background,
                title=title,
                subtitle=subtitle,
                analysis=analysis,
            )

    # -- 背景（W2） -----------------------------------------------------------

    def _render_background(
        self,
        width: int,
        height: int,
        bg_config: Any,
    ) -> Image.Image:
        """渲染背景帧（PIL Image，按目标尺寸）。

        支持：solid 纯色 / gradient 渐变 / image 图片。
        """
        bg_type = getattr(bg_config, "type", "gradient")
        if bg_type == "solid":
            color = getattr(bg_config, "solid_color", "#1a1a2e").lstrip("#")
            return Image.new("RGB", (width, height), color=color)
        if bg_type == "image":
            img_path = getattr(bg_config, "image", "")
            if img_path and Path(img_path).exists():
                img = Image.open(img_path).convert("RGB")
                return img.resize((width, height), Image.LANCZOS)
        # 默认渐变（gradient 或 image 缺失时回退）
        start = getattr(bg_config, "gradient_start", "#1a1a2e")
        end = getattr(bg_config, "gradient_end", "#16213e")
        return self._render_gradient(width, height, start, end)

    def _render_gradient(
        self,
        width: int,
        height: int,
        start_color: str,
        end_color: str,
    ) -> Image.Image:
        """渲染垂直渐变背景。"""
        img = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(img)

        def parse_color(hex_color: str) -> tuple:
            h = hex_color.lstrip("#")
            if len(h) == 6:
                return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
            return (26, 26, 46)

        start = parse_color(start_color)
        end = parse_color(end_color)
        for y in range(height):
            ratio = y / max(1, height - 1)
            r = int(start[0] * (1 - ratio) + end[0] * ratio)
            g = int(start[1] * (1 - ratio) + end[1] * ratio)
            b = int(start[2] * (1 - ratio) + end[2] * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))
        return img
