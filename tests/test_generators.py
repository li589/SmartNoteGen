"""生成器单元测试：程序化多轨 MIDI + music21 乐理旋律。

断言：
- 音符 pitch 均在指定调式音阶内
- 强拍/句尾目标音与和弦音对齐率 >= 80%
- 相同 seed 输出字节级一致；不同 seed 结果不同
"""

from __future__ import annotations

from pathlib import Path

import pytest

from smartnotegen.generators.base import (
    GenerationRequest,
    resolve_scale_pitch_classes,
)
from smartnotegen.generators.music21_melody import Music21MelodyGenerator
from smartnotegen.generators.procedural import ProceduralGenerator
from smartnotegen.models.chords import ChordProgression
from smartnotegen.models.midi import MidiDocument


def _write_midi(seq, path: Path) -> Path:
    p = Path(MidiDocument.from_sequence(seq).write(path))
    return p


# ---------------------------------------------------------------------------
# 程序化 MIDI 生成
# ---------------------------------------------------------------------------

def test_procedural_three_tracks():
    """默认 3 轨：chords/melody/bass，乐器号与 pop 预设一致。"""
    gen = ProceduralGenerator(seed=1)
    seq = gen.generate(GenerationRequest(seed=1))
    assert seq.track_names == ["chords", "melody", "bass"]
    programs = {t.name: t.program for t in seq.tracks}
    assert programs["chords"] == 0   # 钢琴
    assert programs["melody"] == 81  # 合成主音
    assert programs["bass"] == 33    # 电贝斯
    assert seq.duration_seconds() == pytest.approx(8 * (60 / 120) * 4, abs=0.01)


def test_procedural_with_drums():
    """with_drums=True -> 第 4 轨鼓，channel 9。"""
    gen = ProceduralGenerator(seed=1)
    seq = gen.generate(GenerationRequest(seed=1, with_drums=True))
    assert len(seq.tracks) == 4
    drums = seq.tracks[-1]
    assert drums.name == "drums"
    assert drums.channel == 9
    assert all(36 <= n.pitch <= 42 for n in drums.notes)


def test_procedural_reproducible_same_seed():
    """相同 seed -> .mid 字节级一致。"""
    req = GenerationRequest(seed=42, chords="C-G-Am-F", bars=8)
    a = _write_midi(ProceduralGenerator(seed=42).generate(req), Path("a.mid"))
    b = _write_midi(ProceduralGenerator(seed=42).generate(req), Path("b.mid"))
    assert a.read_bytes() == b.read_bytes()


def test_procedural_different_seed_differs():
    """不同 seed -> 结果不同。"""
    req = GenerationRequest(seed=1, bars=8)
    a = _write_midi(ProceduralGenerator(seed=1).generate(req), Path("c.mid"))
    b = _write_midi(ProceduralGenerator(seed=2).generate(req), Path("d.mid"))
    assert a.read_bytes() != b.read_bytes()


def test_procedural_notes_in_scale():
    """旋律/和弦/贝斯音符均在调式音阶内。"""
    gen = ProceduralGenerator(seed=7)
    seq = gen.generate(GenerationRequest(seed=7, key="C major", chords="C-G-Am-F"))
    scale_pcs = set(resolve_scale_pitch_classes("C major"))
    for n in seq.notes:
        assert n.pitch % 12 in scale_pcs


# ---------------------------------------------------------------------------
# music21 乐理旋律生成
# ---------------------------------------------------------------------------

def test_melody_notes_in_scale():
    """music21 旋律音符全部落在调式音阶内。"""
    gen = Music21MelodyGenerator(seed=3)
    seq = gen.generate(GenerationRequest(seed=3, key="C major", chords="C-G-Am-F", bars=8))
    scale_pcs = set(resolve_scale_pitch_classes("C major"))
    melody_notes = [t.notes for t in seq.tracks if t.name == "melody"][0]
    for n in melody_notes:
        assert n.pitch % 12 in scale_pcs, f"pitch {n.pitch} 不在 C major 音阶内"


def test_melody_chord_tone_alignment():
    """强拍（第 1、3 拍）与句尾目标音对齐和弦音 >= 80%。"""
    gen = Music21MelodyGenerator(seed=3)
    request = GenerationRequest(seed=3, key="C major", chords="C-G-Am-F", bars=8)
    seq = gen.generate(request)
    prog = ChordProgression.parse(request.chords)
    melody_notes = [t.notes for t in seq.tracks if t.name == "melody"][0]

    checked = 0
    aligned = 0
    for i, n in enumerate(melody_notes):
        bar = int(n.start // 4)
        beat = round(n.start % 4)
        chord = prog.get_chord(bar)
        phrase_end = i == len(melody_notes) - 1
        if beat in (0, 2) or phrase_end:
            checked += 1
            if n.pitch % 12 in chord.chord_tones:
                aligned += 1
    assert checked > 0
    ratio = aligned / checked
    assert ratio >= 0.8, f"对齐率 {ratio:.2%} < 80%"


def test_melody_variations_produced():
    """--variations 3 -> 主旋律 + 3 个变奏轨。"""
    gen = Music21MelodyGenerator(seed=5)
    seq = gen.generate(GenerationRequest(seed=5, chords="C-G-Am-F", bars=8, variations=3))
    assert len(seq.tracks) == 4
    names = seq.track_names
    assert names[0] == "melody"
    assert any("var_rhythm" in n for n in names)
    assert any("var_ornament" in n for n in names)
    assert any("var_retrograde" in n for n in names)


def test_melody_variations_distinguishable():
    """变奏与主旋律音符序列不同（可辨识）。"""
    gen = Music21MelodyGenerator(seed=5)
    seq = gen.generate(GenerationRequest(seed=5, chords="C-G-Am-F", bars=8, variations=3))
    main = seq.tracks[0].notes
    for t in seq.tracks[1:]:
        assert [n.pitch for n in t.notes] != [n.pitch for n in main]


def test_melody_reproducible_same_seed():
    """music21 旋律同 seed -> 字节级一致。"""
    req = GenerationRequest(seed=9, chords="C-G-Am-F", bars=8, variations=2)
    a = _write_midi(Music21MelodyGenerator(seed=9).generate(req), Path("e.mid"))
    b = _write_midi(Music21MelodyGenerator(seed=9).generate(req), Path("f.mid"))
    assert a.read_bytes() == b.read_bytes()
