"""节拍脉冲可视化原语（v0.2.0 W1：查表渲染，走 PIL 创意层）。

- ReactiveVisualizer：节拍/能量驱动的脉冲动画
- 数据来自预计算 AudioAnalysis.rms_envelope + onsets（一次计算，全帧共享）
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from videomaker.visuals.base import VisualContext, Visualizer


def _parse_color(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    if len(h) == 6:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (74, 158, 255)


class ReactiveVisualizer(Visualizer):
    """节拍脉冲可视化（创意层）。

    画面构成：
    - 背景：ctx.background（引擎注入）或深色纯色
    - 中心脉冲圆：半径 + 颜色随 RMS 包络变化
    - 冲击环：onset 后 0.3s 内扩散的圆环
    """

    DECAY_S = 0.3  # onset 冲击环衰减时长（秒）

    def render_frame(self, ctx: VisualContext, frame_idx: int) -> np.ndarray:
        analysis = ctx.analysis
        if ctx.background is not None:
            img = Image.fromarray(ctx.background.copy())
        else:
            img = Image.new("RGB", (ctx.width, ctx.height), color=(26, 26, 46))
        draw = ImageDraw.Draw(img)

        idx = min(frame_idx, analysis.n_frames - 1)
        rms = float(analysis.rms_envelope[idx]) if analysis.rms_envelope.size else 0.0
        t = idx / max(1, ctx.fps)

        cx, cy = ctx.width // 2, ctx.height // 2
        min_dim = min(cx, cy)
        base_color = _parse_color(self.config.visual.color)

        # 中心脉冲圆（能量 → 半径 + 颜色偏移）
        radius = int(min_dim * (0.15 + rms * 0.25))
        r = min(255, int(base_color[0] + rms * (255 - base_color[0])))
        g = int(base_color[1] * (1.0 - rms * 0.5))
        b = int(base_color[2] * (1.0 - rms * 0.5))
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            fill=(r, g, b),
        )

        # onset 冲击环：最近一次 onset 后 DECAY_S 内扩散
        recent_onset = None
        for onset_t in analysis.onsets:
            if onset_t <= t and t - onset_t <= self.DECAY_S:
                recent_onset = onset_t  # 取最近的
        if recent_onset is not None:
            age = t - recent_onset
            progress = age / self.DECAY_S  # 0 → 1
            ring_r = int(radius + progress * min_dim * 0.5)
            ring_c = (min(255, base_color[0] + 80), base_color[1], base_color[2])
            # PIL 无 alpha 直线，用宽度渐减模拟衰减
            width = max(1, int(6 * (1.0 - progress)))
            draw.ellipse(
                [cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
                outline=ring_c,
                width=width,
            )

        return np.array(img)

    def get_style_name(self) -> str:
        return "reactive"
