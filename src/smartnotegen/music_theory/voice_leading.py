"""声部进行约束（P2-2a）：平行五度/八度检测 + 声部交叉检测。

检测器可单测（构造含平行五度的输入可被检出）；correct_or_report 采用
「检测 + 提示（report）」策略，不静默改动音符（生成链默认关闭）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from smartnotegen.logging_setup import get_logger
from smartnotegen.models.notes import NoteSequence

logger = get_logger("music_theory.voice_leading")


@dataclass
class Violation:
    """一次声部进行违规。"""

    kind: str            # "parallel_fifth_or_octave" | "voice_crossing"
    track_a: str
    track_b: str
    beat: float
    detail: str


def _quantized_pitch_map(notes, step: float = 1.0) -> dict[float, int]:
    """将音符按拍量化：每个时间片取第一个音高。"""
    result: dict[float, int] = {}
    for n in notes:
        beat = round(n.start / step) * step
        result.setdefault(beat, n.pitch)
    return result


class VoiceLeadingChecker:
    """平行五度/八度与声部交叉检测器。"""

    #: 需检测的平行音程（P5=7 个半音；P8=12 个半音，取模后为 0 且距离非 0）
    PARALLEL_INTERVAL_CLASSES = (7, 0)

    def detect_parallel_fifths_octaves(self, seq: NoteSequence) -> List[Violation]:
        """检测相邻两轨同向进行且连续两次音程为 P5/P8。

        判定规则：两轨在连续两个时间片上均同时发声，且
        (1) 两个时间片的音程都是 P5 或 P8（取模音级）；
        (2) 两轨移动方向相同（同向进行）。
        """
        violations: List[Violation] = []
        tracks = [t for t in seq.tracks if t.channel != 9]  # 排除鼓轨
        for i in range(len(tracks)):
            for j in range(i + 1, len(tracks)):
                ta, tb = tracks[i], tracks[j]
                map_a = _quantized_pitch_map(ta.notes)
                map_b = _quantized_pitch_map(tb.notes)
                beats = sorted(set(map_a) & set(map_b))
                prev_cons = False
                prev_pa: int | None = None
                prev_pb: int | None = None
                for beat in beats:
                    pa, pb = map_a[beat], map_b[beat]
                    dist = pb - pa
                    interval_class = abs(dist) % 12
                    is_cons = (
                        interval_class in self.PARALLEL_INTERVAL_CLASSES and dist != 0
                    )
                    dir_same = False
                    if prev_pa is not None and prev_pb is not None:
                        dir_same = (pa - prev_pa) * (pb - prev_pb) > 0
                    if is_cons and prev_cons and dir_same:
                        kind = "平行八度" if interval_class == 0 else "平行五度"
                        violations.append(
                            Violation(
                                "parallel_fifth_or_octave",
                                ta.name,
                                tb.name,
                                beat,
                                f"{kind}: {ta.name} 与 {tb.name} 在拍 {beat:.0f} 同向进行至 "
                                f"音程 {dist} 个半音",
                            )
                        )
                    prev_cons = is_cons
                    prev_pa, prev_pb = pa, pb
        return violations

    def detect_crossing(self, seq: NoteSequence) -> List[Violation]:
        """检测声部交叉：低音域声部在同一拍高于高音域声部。"""
        violations: List[Violation] = []
        tracks = [t for t in seq.tracks if t.channel != 9]
        for i in range(len(tracks)):
            for j in range(i + 1, len(tracks)):
                ta, tb = tracks[i], tracks[j]
                avg_a = sum(n.pitch for n in ta.notes) / len(ta.notes) if ta.notes else 0.0
                avg_b = sum(n.pitch for n in tb.notes) / len(tb.notes) if tb.notes else 0.0
                lower, upper = (ta, tb) if avg_a <= avg_b else (tb, ta)
                map_low = _quantized_pitch_map(lower.notes)
                map_up = _quantized_pitch_map(upper.notes)
                for beat in sorted(set(map_low) & set(map_up)):
                    if map_low[beat] > map_up[beat]:
                        violations.append(
                            Violation(
                                "voice_crossing",
                                lower.name,
                                upper.name,
                                beat,
                                f"声部交叉: {lower.name}({map_low[beat]}) > {upper.name}({map_up[beat]})"
                                f" 于拍 {beat:.0f}",
                            )
                        )
        return violations

    def correct_or_report(
        self, seq: NoteSequence, tolerance: int = 0
    ) -> NoteSequence:
        """检测并提示（report 模式）：违规数超过容忍度时输出警告。

        生成链默认关闭本规则；开启时以提示为主，不静默改动音符。
        """
        violations = self.detect_parallel_fifths_octaves(seq)
        if len(violations) > tolerance:
            logger.warning(
                "检测到 %d 处平行五度/八度（容忍度 %d）: %s",
                len(violations),
                tolerance,
                "; ".join(v.detail for v in violations[:5]),
            )
        crossings = self.detect_crossing(seq)
        if crossings:
            logger.warning("检测到 %d 处声部交叉: %s", len(crossings), crossings[0].detail)
        return seq
