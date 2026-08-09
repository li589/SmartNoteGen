"""MIDI 文件模型：MidiTrack / MidiDocument（pretty_midi 封装）。

- MidiTrack：领域层轨道（name / program / channel / notes）。
- MidiDocument：整首曲目，from_sequence 将 NoteSequence 落盘为标准 .mid。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import pretty_midi

from smartnotegen.models.notes import Note, NoteSequence


@dataclass
class MidiTrack:
    """一条 MIDI 轨道。

    Attributes:
        name: 轨道名。
        program: GM 乐器号（0-127；鼓轨通常为 0，配合 is_drum）。
        channel: MIDI 通道（0-15；鼓轨约定 9）。
        notes: 音符列表。
        is_drum: 是否为鼓轨（写入时映射到通道 9）。
    """

    name: str
    program: int
    channel: int
    notes: List[Note] = field(default_factory=list)
    is_drum: bool = False


@dataclass
class MidiDocument:
    """整首 MIDI 曲目（对应一个 .mid 文件）。"""

    tracks: List[MidiTrack] = field(default_factory=list)
    bpm: int = 120
    ticks_per_beat: int = 480

    @classmethod
    def from_sequence(cls, seq: NoteSequence) -> "MidiDocument":
        """从领域层 NoteSequence 构建 MidiDocument。

        Args:
            seq: 生成器产出的 NoteSequence。

        Returns:
            MidiDocument 实例。
        """
        doc = cls(bpm=seq.bpm)
        for t in seq.tracks:
            doc.tracks.append(
                MidiTrack(
                    name=t.name,
                    program=t.program,
                    channel=t.channel,
                    notes=list(t.notes),
                    is_drum=(t.channel == 9),
                )
            )
        return doc

    def to_pretty_midi(self) -> pretty_midi.PrettyMIDI:
        """转换为 pretty_midi.PrettyMIDI（音符时长按 bpm 换算为秒）。"""
        pm = pretty_midi.PrettyMIDI(initial_tempo=float(self.bpm))
        beat_duration = 60.0 / self.bpm

        for track in self.tracks:
            inst = pretty_midi.Instrument(
                program=track.program,
                is_drum=track.is_drum,
                name=track.name,
            )
            for note in track.notes:
                start_sec = note.start * beat_duration
                end_sec = (note.start + note.duration) * beat_duration
                pm_note = pretty_midi.Note(
                    velocity=note.velocity,
                    pitch=note.pitch,
                    start=start_sec,
                    end=end_sec,
                )
                inst.notes.append(pm_note)
            pm.instruments.append(inst)
        return pm

    def write(self, path: str | Path) -> str:
        """写入 .mid 文件。

        Args:
            path: 输出路径。

        Returns:
            写入的绝对路径字符串。
        """
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        pm = self.to_pretty_midi()
        pm.write(str(target))
        return str(target)

    @classmethod
    def load(cls, path: str | Path) -> "MidiDocument":
        """从 .mid 文件读取（pretty_midi 打开解析）。"""
        from smartnotegen.exceptions import InputFileError

        target = Path(path).expanduser().resolve()
        if not target.is_file():
            raise InputFileError(f"MIDI 文件不存在: {target}", code=3)
        try:
            pm = pretty_midi.PrettyMIDI(str(target))
        except Exception as exc:
            raise InputFileError(f"无法解析 MIDI 文件: {target} ({exc})", code=3) from exc

        bpm = int(pm.estimate_tempo()) if pm.estimate_tempo() else 120
        doc = cls(bpm=bpm)
        for inst in pm.instruments:
            notes = [
                Note(
                    pitch=int(n.pitch),
                    start=round(n.start * bpm / 60.0, 6),
                    duration=round((n.end - n.start) * bpm / 60.0, 6),
                    velocity=int(n.velocity),
                )
                for n in inst.notes
            ]
            doc.tracks.append(
                MidiTrack(
                    name=inst.name or "track",
                    program=inst.program,
                    channel=9 if inst.is_drum else 0,
                    notes=notes,
                    is_drum=inst.is_drum,
                )
            )
        return doc
