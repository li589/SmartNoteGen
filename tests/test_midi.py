"""MIDI 文档单元测试：NoteSequence -> .mid 落盘 -> pretty_midi 回读。"""

from __future__ import annotations

import pretty_midi
import pytest

from smartnotegen.generators.base import GenerationRequest
from smartnotegen.generators.procedural import ProceduralGenerator
from smartnotegen.models.midi import MidiDocument
from smartnotegen.models.notes import Note, NoteSequence


def test_write_and_load_roundtrip(tmp_path):
    """写盘后 MidiDocument.load 可解析全部音符。"""
    seq = ProceduralGenerator(seed=42).generate(GenerationRequest(seed=42, bars=4))
    midi_path = MidiDocument.from_sequence(seq).write(tmp_path / "out.mid")

    loaded = MidiDocument.load(midi_path)
    assert len(loaded.tracks) == len(seq.tracks)
    for orig, back in zip(seq.tracks, loaded.tracks):
        assert len(back.notes) == len(orig.notes)
        # 音符数量级一致；音高集合一致（pretty_midi 保留全部音符）
        assert {n.pitch for n in back.notes} == {n.pitch for n in orig.notes}


def test_pretty_midi_opens_file(tmp_path):
    """pretty_midi 可直接打开生成的 .mid。"""
    seq = ProceduralGenerator(seed=1).generate(GenerationRequest(seed=1, bars=2))
    midi_path = MidiDocument.from_sequence(seq).write(tmp_path / "pm.mid")
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    total_notes = sum(len(inst.notes) for inst in pm.instruments)
    assert total_notes == len(seq.notes)


def test_program_mapping_preserved(tmp_path):
    """轨道乐器号（GM 映射）在写盘后保持。"""
    seq = ProceduralGenerator(seed=1).generate(GenerationRequest(seed=1))
    midi_path = MidiDocument.from_sequence(seq).write(tmp_path / "prog.mid")
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    programs = {inst.program for inst in pm.instruments}
    assert programs == {0, 81, 33}


def test_drums_on_channel_9(tmp_path):
    """鼓轨 is_drum=True（pretty_midi 映射到通道 9）。"""
    seq = ProceduralGenerator(seed=1).generate(GenerationRequest(seed=1, with_drums=True))
    midi_path = MidiDocument.from_sequence(seq).write(tmp_path / "drums.mid")
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    drum_instruments = [i for i in pm.instruments if i.is_drum]
    assert len(drum_instruments) == 1
    assert drum_instruments[0].notes  # 有鼓音符


def test_beat_to_second_conversion():
    """领域层拍 -> pretty_midi 秒换算：120bpm 下 4 拍 = 2 秒。"""
    ns = NoteSequence(bpm=120, bars=1)
    ns.add_track("test", 0, 0, [Note(pitch=60, start=4.0, duration=1.0)])
    pm = MidiDocument.from_sequence(ns).to_pretty_midi()
    note = pm.instruments[0].notes[0]
    assert note.start == pytest.approx(2.0, abs=1e-6)
    assert note.end == pytest.approx(2.5, abs=1e-6)


def test_load_missing_file(tmp_path):
    """加载不存在的 .mid -> InputFileError(3)。"""
    from smartnotegen.exceptions import InputFileError

    with pytest.raises(InputFileError) as exc:
        MidiDocument.load(tmp_path / "missing.mid")
    assert exc.value.code == 3
