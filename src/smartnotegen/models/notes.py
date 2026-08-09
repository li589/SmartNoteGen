"""领域数据模型：Note / NoteSequence。

时间单位约定（架构 §7.1）：领域层一切时长以「拍（beat）」计，渲染/导出层才转为「秒」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

# 常用 MIDI 音名（pitch -> name），C4 = 60
_PITCH_NAMES: List[str] = [
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
]


def pitch_to_name(pitch: int) -> str:
    """将 MIDI pitch 转为音名（如 60 -> 'C4'）。"""
    name = _PITCH_NAMES[pitch % 12]
    octave = pitch // 12 - 1
    return f"{name}{octave}"


@dataclass
class Note:
    """一个音符（时长以拍计）。"""

    pitch: int          # MIDI pitch，C4 = 60
    start: float        # 起始拍（相对整首曲子）
    duration: float     # 持续拍数
    velocity: int = 64  # 力度 0-127

    @property
    def name(self) -> str:
        """音名，如 'C4'。"""
        return pitch_to_name(self.pitch)

    def __post_init__(self) -> None:
        if not 0 <= self.pitch <= 127:
            raise ValueError(f"pitch 超出 MIDI 范围 (0-127): {self.pitch}")
        if self.duration <= 0:
            raise ValueError(f"duration 必须为正: {self.duration}")


@dataclass
class _Track:
    """NoteSequence 内部使用的轨道容器（避免与 models/midi.py 的 MidiTrack 混淆）。"""

    name: str
    program: int
    channel: int
    notes: List[Note] = field(default_factory=list)


@dataclass
class NoteSequence:
    """领域层唯一通行证：生成器产出 NoteSequence，MidiDocument.from_sequence 负责落盘。

    Attributes:
        bpm: 每分钟拍数。
        key: 调式，如 "C major"。
        time_signature: 拍号，如 "4/4"。
        bars: 小节数（仅在此层出现）。
        style: 风格标签。
        tracks: 轨道列表（每轨为 _Track）。
    """

    bpm: int = 120
    key: str = "C major"
    time_signature: str = "4/4"
    bars: int = 8
    style: str = "pop"
    tracks: List[_Track] = field(default_factory=list)

    def add_track(self, name: str, program: int, channel: int, notes: List[Note]) -> None:
        """新增一条轨道。

        Args:
            name: 轨道名（如 "chords" / "melody" / "bass" / "drums"）。
            program: GM 乐器号（0-127；鼓轨可传 0，channel=9 表示鼓）。
            channel: MIDI 通道（0-15；鼓轨约定 9）。
            notes: 该轨音符列表。
        """
        if not 0 <= program <= 127:
            raise ValueError(f"program 超出 GM 范围 (0-127): {program}")
        if not 0 <= channel <= 15:
            raise ValueError(f"channel 超出 MIDI 范围 (0-15): {channel}")
        self.tracks.append(_Track(name=name, program=program, channel=channel, notes=list(notes)))

    @property
    def track_names(self) -> List[str]:
        """轨道名列表。"""
        return [t.name for t in self.tracks]

    @property
    def notes(self) -> List[Note]:
        """全部音符（跨轨打平），便于统计/校验。"""
        return [n for t in self.tracks for n in t.notes]

    def total_beats(self) -> float:
        """按拍号计算的整曲拍数（bars * 每小节拍数）。"""
        numerator, denominator = _parse_time_signature(self.time_signature)
        return float(self.bars * numerator * 4.0 / denominator)

    def duration_seconds(self) -> float:
        """整曲时长（秒），按 bpm 换算。"""
        return self.total_beats() * 60.0 / self.bpm


def _parse_time_signature(ts: str) -> tuple[int, int]:
    """解析 "4/4" -> (4, 4)。"""
    try:
        num, den = ts.split("/")
        return int(num), int(den)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"非法拍号: {ts!r}（期望形如 '4/4'）") from exc
