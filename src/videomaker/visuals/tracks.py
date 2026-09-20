"""分轨可视化（v0.3 W4）+ 滚动波形（W5）。

- TracksVisualizer：多轨垂直排列，每轨独立频谱条 + 轨名标签，
  轨道颜色按 HSL 色环均匀分布。需 analyze_multitrack() 产出 track_* 数据。
- WaveformScrollVisualizer：播放头居中，波形随时间从右向左流动。
"""

from __future__ import annotations

import colorsys
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from videomaker.visuals.base import VisualContext, Visualizer


def _parse_color(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    if len(h) == 6:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (74, 158, 255)


def _track_color(i: int, n: int, base: tuple) -> tuple:
    """轨道色：基于主色做色相偏移，均匀区分。"""
    if n <= 1:
        return base
    h, light, s = colorsys.rgb_to_hls(base[0] / 255, base[1] / 255, base[2] / 255)
    h = (h + i / n) % 1.0
    r, g, b = colorsys.hls_to_rgb(h, light, s)
    return (int(r * 255), int(g * 255), int(b * 255))


class TracksVisualizer(Visualizer):
    """分轨频谱可视化（v0.3 W4）。

    布局：轨道垂直均分画布；每轨画水平频谱条（从左向右）+ 轨名。
    数据源：ctx.analysis.track_spectrograms / track_rms。
    """

    def render_frame(self, ctx: VisualContext, frame_idx: int) -> np.ndarray:
        analysis = ctx.analysis
        if ctx.background is not None:
            img = Image.fromarray(ctx.background.copy())
        else:
            img = Image.new("RGB", (ctx.width, ctx.height), color=(26, 26, 46))
        draw = ImageDraw.Draw(img)

        tracks = analysis.track_spectrograms
        n_tracks = len(tracks)
        if n_tracks == 0:
            return np.array(img)

        idx = min(frame_idx, analysis.n_frames - 1)
        base_color = _parse_color(self.config.visual.color)

        # 布局参数
        pad_top = int(ctx.height * 0.06)
        pad_bottom = int(ctx.height * 0.04)
        pad_x = int(ctx.width * 0.06)
        label_h = 18 if ctx.width < 800 else 28
        lane_h = max(20, (ctx.height - pad_top - pad_bottom) // n_tracks)
        lane_inner = max(10, lane_h - label_h - 4)

        # 标签字体
        font = self._small_font(ctx.width)

        for t in range(n_tracks):
            spec = tracks[t]
            if spec.size == 0:
                continue
            n_bins = spec.shape[1]
            y0 = pad_top + t * lane_h
            color = _track_color(t, n_tracks, base_color)

            # 轨名
            label = analysis.track_labels[t] if t < len(analysis.track_labels) else f"Track {t+1}"
            if font is not None:
                draw.text((pad_x, y0), label, font=font, fill=(200, 205, 215))

            # 频谱条（从底部向上）
            bar_y_bottom = y0 + label_h + lane_inner
            bar_area_w = ctx.width - pad_x * 2
            bar_w = max(1, bar_area_w // n_bins)
            for b in range(n_bins):
                val = float(spec[idx, b]) if idx < spec.shape[0] else 0.0
                bar_h = int(val * lane_inner)
                if bar_h > 0:
                    x = pad_x + b * bar_w
                    c = tuple(min(255, int(v * (0.6 + val * 0.4))) for v in color)
                    draw.rectangle(
                        [x, bar_y_bottom - bar_h, x + bar_w - 1, bar_y_bottom],
                        fill=c,
                    )

            # 分隔线
            if t < n_tracks - 1:
                sep_y = pad_top + (t + 1) * lane_h - 2
                draw.line([(pad_x, sep_y), (ctx.width - pad_x, sep_y)],
                          fill=(50, 55, 75), width=1)

        return np.array(img)

    def _small_font(self, width: int) -> Optional[ImageFont.FreeTypeFont]:
        size = 14 if width < 800 else 22
        for p in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]:
            try:
                from pathlib import Path as _P
                if _P(p).exists():
                    return ImageFont.truetype(p, size)
            except OSError:
                continue
        return None

    def get_style_name(self) -> str:
        return "tracks"


class WaveformScrollVisualizer(Visualizer):
    """滚动波形（v0.3 W5）：播放头居中，波形随时间流动。

    用预计算 waveform 查表 + 窗口切片，无逐帧重计算。
    """

    WINDOW_S = 6.0  # 窗口时长（秒）

    def render_frame(self, ctx: VisualContext, frame_idx: int) -> np.ndarray:
        analysis = ctx.analysis
        if ctx.background is not None:
            img = Image.fromarray(ctx.background.copy())
        else:
            img = Image.new("RGB", (ctx.width, ctx.height), color=(26, 26, 46))
        draw = ImageDraw.Draw(img)

        t = frame_idx / max(1, ctx.fps)
        wave = analysis.waveform
        if wave.size == 0:
            return np.array(img)

        # 波形数组覆盖全曲 [0, duration]，映射到窗口 [t - W/2, t + W/2]
        duration = analysis.duration_s
        win = min(self.WINDOW_S, duration)
        half = win / 2.0
        t_start = max(0.0, min(t - half, duration - win))
        t_end = t_start + win

        # 窗口内采样
        x_old = np.linspace(0.0, 1.0, len(wave), endpoint=False) * duration
        x_new = np.linspace(t_start, t_end, ctx.width, endpoint=False)
        window = np.interp(x_new, x_old, wave)

        mid_y = ctx.height // 2
        amp = mid_y - int(ctx.height * 0.08)
        color = _parse_color(self.config.visual.color)
        lw = 2 if ctx.width < 800 else 3

        # 波形折线
        pts = []
        for x in range(0, ctx.width, 2):
            y = int(mid_y + window[x] * amp)
            pts.append((x, y))
        if len(pts) > 1:
            draw.line(pts, fill=color, width=lw)

        # 已播放部分填充（低透明度）
        if t > t_start:
            played_x = int((t - t_start) / win * ctx.width)
            played_x = max(0, min(played_x, ctx.width))
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            od.rectangle([0, mid_y - amp, played_x, mid_y + amp],
                         fill=(color[0], color[1], color[2], 36))
            img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
            draw = ImageDraw.Draw(img)

        # 播放头（垂直线）
        head_x = int((t - t_start) / win * ctx.width)
        head_x = max(0, min(head_x, ctx.width - 1))
        draw.line([(head_x, mid_y - amp - 20), (head_x, mid_y + amp + 20)],
                  fill=(255, 255, 255), width=2)

        # 中线
        draw.line([(0, mid_y), (ctx.width, mid_y)], fill=(60, 65, 85), width=1)

        return np.array(img)

    def get_style_name(self) -> str:
        return "waveform_scroll"
