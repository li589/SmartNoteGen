"""频谱可视化原语（v0.2.0 W1：查表渲染，走 PIL 创意层）。

- CircularSpectrumVisualizer：圆形频谱（中心圆 + 放射状频谱条）
- 频谱数据来自预计算 AudioAnalysis.spectrogram（一次 STFT，全帧共享）
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from videomaker.config import Config
from videomaker.visuals.base import VisualContext, Visualizer


def _parse_color(hex_color: str) -> tuple:
    """'#4a9eff' → (74, 158, 255)。"""
    h = hex_color.lstrip("#")
    if len(h) == 6:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (74, 158, 255)  # 默认蓝


class CircularSpectrumVisualizer(Visualizer):
    """圆形频谱可视化（创意层）。

    画面构成：
    - 背景：ctx.background（引擎注入）或深色纯色
    - 中心圆：半径随 RMS 包络脉动
    - 放射频谱条：64 bin 频谱沿圆周放射，长度随能量
    """

    def render_frame(self, ctx: VisualContext, frame_idx: int) -> np.ndarray:
        analysis = ctx.analysis
        if ctx.background is not None:
            img = Image.fromarray(ctx.background.copy())
        else:
            img = Image.new("RGB", (ctx.width, ctx.height), color=(26, 26, 46))
        draw = ImageDraw.Draw(img)

        idx = min(frame_idx, analysis.n_frames - 1)
        spec = analysis.spectrogram[idx] if analysis.spectrogram.size else np.zeros(64)
        rms = float(analysis.rms_envelope[idx]) if analysis.rms_envelope.size else 0.0

        cx, cy = ctx.width // 2, ctx.height // 2
        min_dim = min(cx, cy)
        base_radius = int(min_dim * 0.35)
        max_bar = int(min_dim * 0.30)
        color = _parse_color(self.config.visual.color)
        n_bars = len(spec)

        # 放射频谱条
        for i in range(n_bars):
            angle = 2.0 * np.pi * i / n_bars - np.pi / 2.0
            val = float(spec[i])
            r_out = base_radius + int(val * max_bar)
            x1 = cx + int(base_radius * np.cos(angle))
            y1 = cy + int(base_radius * np.sin(angle))
            x2 = cx + int(r_out * np.cos(angle))
            y2 = cy + int(r_out * np.sin(angle))
            # 能量越高颜色越亮
            c = tuple(min(255, int(v * (0.6 + val * 0.4))) for v in color)
            draw.line([(x1, y1), (x2, y2)], fill=c, width=3)

        # 中心圆（随 RMS 脉动）
        pulse = int(min_dim * 0.08 * (1.0 + rms * 0.8))
        draw.ellipse(
            [cx - pulse, cy - pulse, cx + pulse, cy + pulse],
            fill=color,
        )

        return np.array(img)

    def get_style_name(self) -> str:
        return "circular_spectrum"
