"""基础二声部对位（P2-2b）：强拍音程协和约束。

协和音程允许集合按严格度（1..3）分级：
    strictness 1: 同度/三度/五度/六度/八度（{0,3,4,7,8,9,12}）
    strictness 2: 去掉六度（{0,3,4,7,8,12}）
    strictness 3: 仅同度/三度/五度/八度（{0,3,4,7,12}）

enforce 对「最低轨 + 最高轨」在强拍（第 1、3 拍）上将非协和音程的上方声部
就近调整为协和音程（保持旋律轮廓与音阶内）。
"""

from __future__ import annotations

from typing import Set

from smartnotegen.exceptions import ParameterError
from smartnotegen.models.notes import Note, NoteSequence

#: 各严格度对应的协和音程集合（音级差，取模 12）
CONSONANT_SETS: dict[int, Set[int]] = {
    1: {0, 3, 4, 7, 8, 9, 12},
    2: {0, 3, 4, 7, 8, 12},
    3: {0, 3, 4, 7, 12},
}

#: 强拍（4/4 内第 1、3 拍）
STRONG_BEATS = (0, 2)


def _quantized_pitch_map(notes, step: float = 1.0) -> dict[float, int]:
    result: dict[float, int] = {}
    for n in notes:
        beat = round(n.start / step) * step
        result.setdefault(beat, n.pitch)
    return result


class CounterpointEngine:
    """二声部对位引擎。"""

    def __init__(self, strictness: int = 1) -> None:
        """初始化。

        Args:
            strictness: 严格度 1..3（1 最宽松，3 最严格）。
        """
        if strictness not in CONSONANT_SETS:
            raise ParameterError(f"strictness 必须为 1-3: {strictness}", code=1)
        self.strictness = strictness

    def enforce(self, seq: NoteSequence) -> NoteSequence:
        """对双声部（最低轨 + 最高轨）做强拍协和约束。

        仅调整上方声部在强拍上的音符；默认关闭（由 GenerationRequest 控制）。
        """
        tracks = [t for t in seq.tracks if t.channel != 9]
        if len(tracks) < 2:
            return seq
        lower = min(tracks, key=lambda t: min((n.pitch for n in t.notes), default=60))
        upper = max(tracks, key=lambda t: max((n.pitch for n in t.notes), default=60))
        if lower is upper:
            return seq
        allowed = CONSONANT_SETS[self.strictness]
        map_low = _quantized_pitch_map(lower.notes)

        adjusted: list[Note] = []
        for n in upper.notes:
            beat = round(n.start)
            if beat % 4 in STRONG_BEATS and beat in map_low:
                interval_class = abs(n.pitch - map_low[beat]) % 12
                if interval_class not in allowed:
                    adjusted.append(
                        Note(
                            pitch=self._nearest_consonant(
                                n.pitch, map_low[beat], allowed
                            ),
                            start=n.start,
                            duration=n.duration,
                            velocity=n.velocity,
                        )
                    )
                else:
                    adjusted.append(n)
            else:
                adjusted.append(n)
        upper.notes = adjusted
        return seq

    @staticmethod
    def _nearest_consonant(pitch: int, bass: int, allowed: Set[int]) -> int:
        """就近寻找与 bass 构成协和音程的 pitch（±搜索 12 个半音）。"""
        for step in range(0, 13):
            for sign in (1, -1):
                candidate = pitch + sign * step
                if not 0 <= candidate <= 127:
                    continue
                if abs(candidate - bass) % 12 in allowed:
                    return candidate
        return pitch
