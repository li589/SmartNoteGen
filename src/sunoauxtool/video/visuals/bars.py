"""频率柱状条视觉层（R15）。

经典频谱柱状条：底部对齐的竖直条 + **峰值保持帽**（每帧按固定系数衰减）。

与既有风格互补——``circular_spectrum`` 是极坐标、``waveform_scroll`` 是横向滚动、
``tracks`` 是分轨，本层是**最常见也最易读**的「柱子」形态，且完全由
``ctx.analysis.spectrogram`` 驱动：numpy + PIL 实现，可被像素探针验证。

经 ``sunoauxtool.plugins`` 的 ``video_visuals`` 扩展点注册，风格名 ``bars``。
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from sunoauxtool.video.visuals.base import VisualContext, Visualizer

_BG = (26, 26, 46)
_DEFAULT_BARS = 48
#: 峰值帽每帧衰减系数（越小掉得越快）
_PEAK_DECAY = 0.90


def _parse_color(hex_color: str) -> tuple:
    """``"#00c8ff"`` -> ``(0, 200, 255)``；非法输入回落默认青色。"""
    s = (hex_color or "").lstrip("#")
    if len(s) == 6:
        try:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except ValueError:
            pass
    return (0, 200, 255)


class BarsVisualizer(Visualizer):
    """频率柱状条（R15）：底部对齐 + 峰值保持帽。

    Args:
        config: 生效配置（``config.visual.color`` 决定条色）。
        bars: 柱子数量（默认 48，最小 4）。
    """

    def __init__(self, config, bars: int = _DEFAULT_BARS) -> None:
        super().__init__(config)
        self.bars = max(4, int(bars))
        self._peaks = np.zeros(self.bars, dtype=np.float64)

    def _heights(self, ctx: VisualContext, frame_idx: int) -> np.ndarray:
        """当前帧的柱高序列（0-1，按峰值归一）。"""
        analysis = ctx.analysis
        spec = np.zeros(0, dtype=np.float64)
        if analysis.spectrogram.size and frame_idx < analysis.spectrogram.shape[0]:
            spec = np.asarray(analysis.spectrogram[frame_idx], dtype=np.float64)

        if spec.size == 0:
            return np.zeros(self.bars, dtype=np.float64)

        # 线性分桶降采样到 self.bars（取每桶最大值，保留峰感）
        edges = np.linspace(0, spec.size, self.bars + 1).astype(int)
        buckets = np.array(
            [
                spec[edges[i] : max(edges[i + 1], edges[i] + 1)].max()
                for i in range(self.bars)
            ],
            dtype=np.float64,
        )
        peak = float(buckets.max())
        return buckets / peak if peak > 0 else buckets

    def render_frame(self, ctx: VisualContext, frame_idx: int) -> np.ndarray:
        if ctx.background is not None:
            img = Image.fromarray(ctx.background.copy())
        else:
            img = Image.new("RGB", (ctx.width, ctx.height), color=_BG)
        draw = ImageDraw.Draw(img)

        heights = self._heights(ctx, frame_idx)
        self._peaks = np.maximum(self._peaks * _PEAK_DECAY, heights)

        color = _parse_color(getattr(self.config.visual, "color", "#00c8ff"))
        w, h = ctx.width, ctx.height
        n = self.bars
        slot = w / float(n)
        bar_w = max(1, int(slot * 0.72))
        baseline = h - int(h * 0.08)  # 底部留白
        span = max(1, baseline)

        for i in range(n):
            x0 = int(i * slot + (slot - bar_w) / 2.0)
            x1 = max(x0 + 1, x0 + bar_w)
            bh = int(heights[i] * span)
            if bh > 0:
                draw.rectangle([x0, baseline - bh, x1 - 1, baseline - 1], fill=color)
            # 峰值帽（白色细线，随衰减缓慢下落）
            ph = int(self._peaks[i] * span)
            py = min(baseline - 1, max(0, baseline - ph))
            draw.line([(x0, py), (x1 - 1, py)], fill=(255, 255, 255), width=1)

        return np.asarray(img, dtype=np.uint8)

    def get_style_name(self) -> str:
        return "bars"


__all__ = ["BarsVisualizer", "_parse_color"]
