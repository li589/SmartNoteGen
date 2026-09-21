"""滚动谱面可视化（#14）。

ScoreVisualizer：由 sunoauxtool 的 score 排版数据（``Score`` 模型）驱动，
FrameEngine 逐帧渲染横向滚动谱面：

- 播放头固定居中，谱面随时间从右向左流动
- staff 模式：五线谱（符头 + 加线，谱号按轨道自动判定沿用）
- jianpu 模式：简谱数字（1-7 + 升号 + 八度点）
- 当前正响的音高亮（主色 + 白描边），其余音用弱化色
- 可选节拍网格（beat_times 来自 ``sunoauxtool.analysis.tempo`` 测速）
  + BPM 标注

设计约束：
- 预计算一次（init 时拍→秒换算 + 分轨排序），逐帧只做窗口内查表绘制
- 不复用 score.layout（那是整页断行排版，不适合横向无限滚动），
  只消费 ``Score``/``ScoreTrack``/``ScoreNote`` 的音高与拍位数据，
  几何在可视化侧自绘（与 preview 内嵌 SVG 的简化谱一致的风格取舍）
"""

from __future__ import annotations

from bisect import bisect_left
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from sunoauxtool.video.visuals.base import VisualContext, Visualizer
from sunoauxtool.video.visuals.tracks import _parse_color

# 五线谱线位的自然音级号（C0=0 记法：dia = octave*7 + step, C=0..B=6）
_STAFF_LINES = {
    "treble": [30, 32, 34, 36, 38],  # E4 G4 B4 D5 F5
    "bass": [18, 20, 22, 24, 26],    # G2 B2 D3 F3 A3
}
_STEPS = "CDEFGAB"
_PC_TO_STEP = {0: 0, 2: 1, 4: 2, 5: 3, 7: 4, 9: 5, 11: 6}

# C4（中央 C，MIDI 60）的自然音级号
_DIA_C4 = 28


def _dia_of_pitch(pitch: int) -> int:
    """MIDI 音高 → 自然音级号（黑键落到**下方**自然音线位，变音记号另行表达）。

    dia = (MIDI 八度 - 1) * 7 + 自然音步进，C4(60) → 28。
    """
    octave, pc = divmod(pitch, 12)
    if pc in _PC_TO_STEP:
        step = _PC_TO_STEP[pc]
    else:  # 黑键 → 下方自然音（C#→C 线、F#→F 线）
        step = _PC_TO_STEP[pc - 1]
    return (octave - 1) * 7 + step


def _tonic_dia(key: str) -> int:
    """调式主音的自然音级号（如 "C major" → 28, "A minor" → 33）。"""
    token = (key or "C").strip().split()[0].upper()
    base = _STEPS.find(token[0]) if token else 0
    if base < 0:
        base = 0
    offset = base
    if "#" in token:
        offset = base + 1
    elif "B" in token[1:] or "b" in token:
        pass  # 降号按自然音近似（简化谱不区分拼写）
    return _DIA_C4 + offset


class _Span:
    """预换算的音符时间跨度（秒）。"""
    __slots__ = ("start", "end", "pitch", "measure_start_beat")

    def __init__(self, start: float, dur: float, pitch: int, measure_start_beat: float) -> None:
        self.start = start
        self.end = start + dur
        self.pitch = pitch
        self.measure_start_beat = measure_start_beat


class ScoreVisualizer(Visualizer):
    """滚动谱面（#14）：播放头居中，当前音高亮。

    Args:
        config: 生效配置。
        score: ``sunoauxtool.score.Score``（None 时渲染提示帧）。
        beat_times: 节拍时间网格（秒，来自测速 ``beat_grid``）；None 不画网格。
        bpm: 滚动时间轴的 BPM（None 用 score.bpm，再退 120）。
        notation: "staff"（五线谱）| "jianpu"（简谱数字）。
    """

    WINDOW_S = 6.0  # 可见窗口时长（秒）

    def __init__(
        self,
        config,
        score=None,
        beat_times: Optional[np.ndarray] = None,
        bpm: Optional[float] = None,
        notation: str = "staff",
    ) -> None:
        super().__init__(config)
        self.score = score
        self.beat_times = np.asarray(beat_times) if beat_times is not None else None
        self.notation = notation if notation in ("staff", "jianpu") else "staff"
        self.bpm = float(bpm) if bpm and bpm > 0 else float(getattr(score, "bpm", 0) or 120)
        self.sec_per_beat = 60.0 / self.bpm

        # -- 预计算：分轨音符跨度（秒）+ 排序，供逐帧窗口切片 ----------------
        self.lanes: List[List[_Span]] = []
        self.lane_labels: List[str] = []
        self.lane_clefs: List[str] = []
        self.lane_dia_range: List[int] = []  # 音域跨度（自然音级数，+2 余量）
        bar_beats = self._beats_per_measure()
        if score is not None:
            for tr in score.tracks:
                spans = []
                dias = []
                for n in tr.notes:
                    if getattr(n, "is_rest", False):
                        continue
                    start = float(n.start) * self.sec_per_beat
                    dur = max(float(n.duration), 0.05) * self.sec_per_beat
                    mb = float(n.start) - (float(n.start) % bar_beats)
                    spans.append(_Span(start, dur, int(n.pitch), mb))
                    dias.append(_dia_of_pitch(int(n.pitch)))
                if not spans:
                    continue
                spans.sort(key=lambda s: s.start)
                self.lanes.append(spans)
                self.lane_labels.append(tr.name or "track")
                self.lane_clefs.append(getattr(tr, "clef", "treble") or "treble")
                self.lane_dia_range.append((max(dias) - min(dias) + 2) if dias else 2)

        # 分轨加线判定用线位
        self._lines_per_lane = [
            _STAFF_LINES.get(c, _STAFF_LINES["treble"]) for c in self.lane_clefs
        ]

    # -- Visualizer ---------------------------------------------------------

    def render_frame(self, ctx: VisualContext, frame_idx: int) -> np.ndarray:
        if ctx.background is not None:
            img = Image.fromarray(ctx.background.copy())
        else:
            img = Image.new("RGB", (ctx.width, ctx.height), color=(26, 26, 46))
        draw = ImageDraw.Draw(img)

        if self.score is None or not self.lanes:
            self._draw_hint(img, draw, ctx)
            return np.array(img)

        color = _parse_color(self.config.visual.color)
        t = frame_idx / max(1, ctx.fps)
        win = max(0.5, min(self.WINDOW_S, self._total_s()))
        half = win / 2.0
        t_start = max(0.0, min(t - half, max(0.0, self._total_s() - win)))
        # 播放头固定居中（窗口左端被 0 截断时头位右移）
        head_x = int((t - t_start) / win * ctx.width)

        # 布局：头部（标题+BPM） / 轨道行 / 底部节拍尺
        pad_top = int(ctx.height * 0.10)
        pad_bottom = int(ctx.height * 0.08) if self.beat_times is not None else int(ctx.height * 0.03)
        lane_h = max(24, (ctx.height - pad_top - pad_bottom) // len(self.lanes))

        self._draw_header(draw, ctx, color)
        for i, spans in enumerate(self.lanes):
            y0 = pad_top + i * lane_h
            self._draw_lane(draw, ctx, i, spans, y0, lane_h, t, t_start, win, color)

        if self.beat_times is not None and len(self.beat_times):
            self._draw_beat_ruler(draw, ctx, t_start, win, color)

        # 播放头（最后画，压在最上层）
        draw.line([(head_x, pad_top - 6), (head_x, ctx.height - pad_bottom + 6)],
                  fill=(255, 255, 255), width=2)
        draw.polygon(
            [(head_x - 5, pad_top - 6), (head_x + 5, pad_top - 6), (head_x, pad_top + 4)],
            fill=(255, 255, 255),
        )
        return np.array(img)

    def get_style_name(self) -> str:
        return "score"

    # -- 布局辅助 -----------------------------------------------------------

    def _total_s(self) -> float:
        return max((s.end for lane in self.lanes for s in lane), default=1.0)

    def _beats_per_measure(self) -> float:
        ts = str(getattr(self.score, "time_signature", "4/4") or "4/4")
        try:
            num = float(ts.split("/")[0])
            return num if num > 0 else 4.0
        except (ValueError, IndexError):
            return 4.0

    def _font(self, size: int) -> Optional[ImageFont.FreeTypeFont]:
        from pathlib import Path as _P
        for p in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]:
            try:
                if _P(p).exists():
                    return ImageFont.truetype(p, size)
            except OSError:
                continue
        return None

    # -- 绘制 ---------------------------------------------------------------

    def _draw_hint(self, img: Image.Image, draw: ImageDraw.Draw, ctx: VisualContext) -> None:
        """无谱面数据时的提示帧。"""
        font = self._font(max(14, ctx.height // 20))
        msg = "score 样式需要 MIDI 谱面数据（--score-midi <path>，或直接输入 .mid）"
        if font is not None:
            bbox = draw.textbbox((0, 0), msg, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text(((ctx.width - tw) / 2, (ctx.height - th) / 2), msg,
                      font=font, fill=(160, 165, 180))

    def _draw_header(self, draw: ImageDraw.Draw, ctx: VisualContext, color: Tuple[int, int, int]) -> None:
        font = self._font(max(14, int(ctx.height * 0.03)))
        if font is None:
            return
        title = getattr(self.score, "title", "") or ""
        if title:
            draw.text((int(ctx.width * 0.03), int(ctx.height * 0.015)), title,
                      font=font, fill=(210, 214, 224))
        bpm_text = f"{self.bpm:.1f} BPM" if self.beat_times is not None else f"{self.bpm:g} BPM"
        bbox = draw.textbbox((0, 0), bpm_text, font=font)
        draw.text((ctx.width - (bbox[2] - bbox[0]) - int(ctx.width * 0.03), int(ctx.height * 0.015)),
                  bpm_text, font=font, fill=color)

    def _draw_lane(
        self,
        draw: ImageDraw.Draw,
        ctx: VisualContext,
        lane_idx: int,
        spans: List[_Span],
        y0: int,
        lane_h: int,
        t: float,
        t_start: float,
        win: float,
        color: Tuple[int, int, int],
    ) -> None:
        label_font = self._font(max(10, lane_h // 5))
        if self.notation == "jianpu":
            self._draw_jianpu_lane(draw, ctx, lane_idx, spans, y0, lane_h, t, t_start, win, color)
        else:
            self._draw_staff_lane(draw, ctx, lane_idx, spans, y0, lane_h, t, t_start, win, color)

        # 轨道名（左上角固定）
        if label_font is not None and lane_idx < len(self.lane_labels):
            draw.text((int(ctx.width * 0.01), y0 + 2), self.lane_labels[lane_idx],
                      font=label_font, fill=(140, 145, 160))

    def _window_indices(self, spans: List[_Span], t_start: float, win: float) -> Tuple[int, int]:
        """按窗口 [t_start, t_start+win] 切片（starts 已排序，bisect 查表）。"""
        lo = bisect_left(spans, t_start - 8.0, key=lambda s: s.start)  # 左边多留 8s 兼容长音
        hi = bisect_left(spans, t_start + win, key=lambda s: s.start)
        return lo, max(lo, hi + 1)  # hi 后一个可能跨进窗口（长音起点在窗外）

    def _x_of(self, time_s: float, t_start: float, win: float, width: int) -> int:
        return int((time_s - t_start) / win * width)

    def _draw_staff_lane(
        self,
        draw: ImageDraw.Draw,
        ctx: VisualContext,
        lane_idx: int,
        spans: List[_Span],
        y0: int,
        lane_h: int,
        t: float,
        t_start: float,
        win: float,
        color: Tuple[int, int, int],
    ) -> None:
        lines = self._lines_per_lane[lane_idx]
        mid_dia = lines[len(lines) // 2]
        # 半线距：默认 lane_h/12；宽音域轨道按跨度收缩，防止符头纵向溢出行。
        # 中线取行中心（上下对称），保证音域两端各有 ≥0.44*lane_h 的余量。
        half_gap = min(
            lane_h / 12.0,
            lane_h * 0.44 / max(1.0, self.lane_dia_range[lane_idx] / 2.0),
        )
        line_gap = half_gap * 2.0
        cy = y0 + lane_h // 2  # 中线 y（行中心）

        # 五线
        for k in range(5):
            y = int(cy - (2 - k) * line_gap)
            draw.line([(0, y), (ctx.width, y)], fill=(88, 94, 116), width=1)

        # 小节线（按轨道第一个音所在小节栅格推）
        bar_beats = self._beats_per_measure()
        beat_s = self.sec_per_beat
        m_beat = spans[0].measure_start_beat
        while m_beat * beat_s < t_start + win:
            x = self._x_of(m_beat * beat_s, t_start, win, ctx.width)
            if x >= 0:
                draw.line([(x, int(cy - 2 * line_gap)), (x, int(cy + 2 * line_gap))],
                          fill=(95, 100, 120), width=1)
            m_beat += bar_beats

        # 音符
        lo, hi = self._window_indices(spans, t_start, win)
        r = max(3, int(line_gap * 0.62))
        for s in spans[lo:hi]:
            x = self._x_of(s.start, t_start, win, ctx.width)
            if x < -r * 2 or x > ctx.width + r * 2:
                continue
            dia = _dia_of_pitch(s.pitch)
            y = int(cy - (dia - mid_dia) * half_gap)
            active = s.start <= t < s.end
            if active:
                fill = color
                outline = (255, 255, 255)
            else:
                fill = (color[0] // 3 + 60, color[1] // 3 + 60, color[2] // 3 + 70)
                outline = None
            # 加线（仅当符头在五线外且处于线位奇偶匹配处）
            top_dia, bottom_dia = lines[-1], lines[0]
            ld = dia
            if ld > top_dia or ld < bottom_dia:
                edge = top_dia if ld > top_dia else bottom_dia
                step_dir = 1 if ld > top_dia else -1
                d = edge + step_dir
                while (step_dir > 0 and d <= ld) or (step_dir < 0 and d >= ld):
                    if d % 2 == lines[0] % 2:  # 线位与五线同奇偶
                        ly = int(cy - (d - mid_dia) * half_gap)
                        draw.line([(x - int(r * 1.4), ly), (x + int(r * 1.4), ly)],
                                  fill=(88, 94, 116), width=1)
                    d += step_dir
            draw.ellipse([x - r, y - int(r * 0.78), x + r, y + int(r * 0.78)],
                         fill=fill, outline=outline, width=2 if active else 0)

    def _draw_jianpu_lane(
        self,
        draw: ImageDraw.Draw,
        ctx: VisualContext,
        lane_idx: int,
        spans: List[_Span],
        y0: int,
        lane_h: int,
        t: float,
        t_start: float,
        win: float,
        color: Tuple[int, int, int],
    ) -> None:
        # 弱基线 + 小节线（简谱无五线）
        base_y = y0 + lane_h // 2
        draw.line([(0, base_y + lane_h // 4), (ctx.width, base_y + lane_h // 4)],
                  fill=(55, 60, 80), width=1)
        bar_beats = self._beats_per_measure()
        m_beat = spans[0].measure_start_beat
        while m_beat * self.sec_per_beat < t_start + win:
            x = self._x_of(m_beat * self.sec_per_beat, t_start, win, ctx.width)
            if x >= 0:
                draw.line([(x, y0 + 4), (x, y0 + lane_h - 4)], fill=(95, 100, 120), width=1)
            m_beat += bar_beats

        tonic = _tonic_dia(getattr(self.score, "key", "C major"))
        # 字号：随行高缩放，但设绝对上限——否则高分辨率多轨时数字过宽，
        # 密集音符处横向糊成一片
        font = self._font(max(11, min(int(lane_h * 0.30), 56)))
        lo, hi = self._window_indices(spans, t_start, win)

        # 同时值分组（和弦 → 同 x 纵向堆叠，避免数字完全重叠）
        groups: List[List[_Span]] = []
        for s in spans[lo:hi]:
            if groups and abs(s.start - groups[-1][0].start) < 0.02:
                groups[-1].append(s)
            else:
                groups.append([s])
        th = 20  # 兜底字高（font 为 None 时不画，仅占位）
        for g in groups:
            x = self._x_of(g[0].start, t_start, win, ctx.width)
            if x < -30 or x > ctx.width + 30:
                continue
            m = len(g)
            for k, s in enumerate(g):
                dia = _dia_of_pitch(s.pitch)
                rel = dia - tonic
                degree_idx = rel % 7
                oct_diff = (rel - degree_idx) // 7
                token = str(degree_idx + 1)
                # 变音：实际 pitch class 与该自然音级差半音 → 加 #
                natural_pc = {0: 0, 1: 2, 2: 4, 3: 5, 4: 7, 5: 9, 6: 11}[dia % 7]
                if (s.pitch % 12) != natural_pc:
                    token = "#" + token
                active = s.start <= t < s.end
                fill = color if active else (color[0] // 3 + 60, color[1] // 3 + 60, color[2] // 3 + 70)
                if font is None:
                    continue
                bbox = draw.textbbox((0, 0), token, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                # 和弦成员纵向堆叠（单音居中）
                y_center = base_y - th // 2 + (k - (m - 1) / 2.0) * (th + 8)
                y_text = int(y_center)
                draw.text((x - tw // 2, y_text), token, font=font, fill=fill)
                # 八度点：仅单音绘制（堆叠时点会与相邻成员混淆）
                if m == 1:
                    if oct_diff > 0:
                        for d_i in range(min(oct_diff, 3)):
                            draw.ellipse([x - 2, y_text - 10 - d_i * 6, x + 2,
                                          y_text - 6 - d_i * 6], fill=fill)
                    elif oct_diff < 0:
                        for d_i in range(min(-oct_diff, 3)):
                            draw.ellipse([x - 2, y_text + th + 4 + d_i * 6, x + 2,
                                          y_text + th + 8 + d_i * 6], fill=fill)

    def _draw_beat_ruler(
        self,
        draw: ImageDraw.Draw,
        ctx: VisualContext,
        t_start: float,
        win: float,
        color: Tuple[int, int, int],
    ) -> None:
        """底部节拍尺：每拍一刻度，每小节首拍加粗。"""
        beats = self.beat_times
        bar_beats = self._beats_per_measure()
        # beat_times 与 offset 对齐：强拍 = 与首拍同余 bar_beats
        y_ruler = ctx.height - max(8, int(ctx.height * 0.03))
        for i, bt in enumerate(beats):
            x = self._x_of(float(bt), t_start, win, ctx.width)
            if x < 0 or x >= ctx.width:
                continue
            strong = (i % int(bar_beats)) == 0 if bar_beats >= 1 else False
            if strong:
                draw.line([(x, y_ruler - 10), (x, y_ruler)], fill=color, width=3)
            else:
                draw.line([(x, y_ruler - 5), (x, y_ruler)], fill=(120, 126, 146), width=1)
