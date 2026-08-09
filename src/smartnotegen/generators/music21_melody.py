"""music21 乐理驱动旋律生成 + 变奏。

- 调式解析：music21 Scale / Key
- 约束：旋律音符全部落在调式音阶内；小节强拍（第 1、3 拍）与句尾目标音对齐和弦音
- 变奏：rhythm（节奏变奏）/ ornament（装饰音变奏）/ retrograde（逆行变奏）
"""

from __future__ import annotations

import random
from typing import List, Optional

from music21 import key as keylib
from music21 import pitch as m21_pitch

from smartnotegen.generators.base import (
    GenerationRequest,
    Generator,
    SeedContext,
    chord_tones_in_range,
    scale_pitches_in_range,
)
from smartnotegen.models.chords import ChordProgression
from smartnotegen.models.notes import Note, NoteSequence
from smartnotegen.music_theory.postprocess import apply_postprocess

#: 变奏方式（按序循环使用）
VARIATION_KINDS: List[str] = ["rhythm", "ornament", "retrograde"]


def _beats_per_bar(time_signature: str) -> float:
    """按拍号计算每小节拍数（4/4 -> 4.0）。"""
    try:
        num, den = time_signature.split("/")
        return float(num) * 4.0 / float(den)
    except (ValueError, AttributeError):
        return 4.0


class Music21MelodyGenerator(Generator):
    """基于 music21 的乐理旋律生成器。

    产出 NoteSequence：主旋律轨 + N 个变奏轨（各自成轨，同文件多轨）。
    """

    def __init__(self, seed: Optional[int] = None) -> None:
        self.seed = seed

    # -- 公共接口 ----------------------------------------------------------

    def generate(self, request: GenerationRequest) -> NoteSequence:
        """生成主旋律 + 变奏（同文件多轨）。"""
        with SeedContext(self.seed if self.seed is not None else request.seed):
            progression = ChordProgression.parse(request.chords)
            scale = self._resolve_scale(request.key)

            main_notes = self._compose_melody(request, progression, scale)
            main_notes = self._align_to_chord_tones(main_notes, progression, request)

            seq = NoteSequence(
                bpm=request.bpm,
                key=request.key,
                time_signature=request.time_signature,
                bars=request.bars,
                style=request.style,
            )
            seq.add_track("melody", 73, 1, main_notes)  # 长笛音色

            n_variations = max(0, request.variations)
            kinds = [VARIATION_KINDS[i % len(VARIATION_KINDS)] for i in range(n_variations)]
            for kind in kinds:
                var_notes = self._variation(main_notes, kind, request.key)
                seq.add_track(f"melody_var_{kind}", 81, 1, var_notes)  # 合成主音

            # P2-2 乐理规则后处理（默认关闭，不破坏 P0 输出）
            if request.enable_voice_leading or request.enable_counterpoint or request.enable_inversion:
                seq, _violations = apply_postprocess(seq, request)
            return seq

    # -- 调式解析 ----------------------------------------------------------

    def _resolve_scale(self, key: str):
        """解析调式字符串为 music21 Scale 对象。"""
        parts = str(key).strip().split()
        if len(parts) == 2:
            k = keylib.Key(parts[0], parts[1])
        else:
            k = keylib.Key(parts[0])
        return k.getScale()

    def _pitch_pool(self, scale, key: str, low: int, high: int) -> List[int]:
        """用 music21 Scale 取 [low, high] 区间内全部音阶 MIDI pitch。

        失败时降级为按音级计算（保证不因 music21 边界行为失败）。
        """
        try:
            ps = scale.getPitches(m21_pitch.Pitch(low), m21_pitch.Pitch(high))
            return sorted({p.midi for p in ps})
        except Exception:
            return scale_pitches_in_range(key, low, high)

    # -- 旋律创作 ----------------------------------------------------------

    def _compose_melody(
        self,
        request: GenerationRequest,
        progression: ChordProgression,
        scale,
    ) -> List[Note]:
        """创作主旋律：强拍/句尾 = 和弦音，其余 = 音阶内级进随机游走。"""
        pool = self._pitch_pool(scale, request.key, 60, 83)
        if not pool:
            pool = scale_pitches_in_range(request.key, 60, 83)
        beats_per_bar = _beats_per_bar(request.time_signature)
        n_beats = max(1, int(round(beats_per_bar)))

        notes: List[Note] = []
        current: Optional[int] = None
        for bar in range(request.bars):
            chord = progression.get_chord(bar)
            bar_start = bar * beats_per_bar
            chord_pool = chord_tones_in_range(chord.chord_tones, 60, 83)
            if not chord_pool:
                chord_pool = [60 + ((chord.root_pc - 60) % 12)]

            for beat in range(n_beats):
                t = bar_start + beat
                strong = beat == 0 or beat == 2
                phrase_end = bar == request.bars - 1 and beat == n_beats - 1
                if strong or phrase_end:
                    current = self._nearest_chord_tone(current, chord_pool)
                else:
                    r = random.random()
                    if r < 0.7:
                        current = self._step(current, pool)
                    elif r < 0.9:
                        current = random.choice(chord_pool)
                    # else：保持 current（同音重复）
                if current is None:
                    current = chord_pool[0]
                notes.append(
                    Note(
                        pitch=current,
                        start=t,
                        duration=beats_per_bar / n_beats * 0.9,
                        velocity=74 + random.randint(-6, 6),
                    )
                )
        return notes

    def _align_to_chord_tones(
        self,
        notes: List[Note],
        progression: ChordProgression,
        request: GenerationRequest,
    ) -> List[Note]:
        """对齐后处理：确保强拍/句尾音符为和弦音（防御性保证，≥80% 目标）。"""
        beats_per_bar = _beats_per_bar(request.time_signature)
        out: List[Note] = []
        for bar in range(request.bars):
            chord = progression.get_chord(bar)
            chord_pool = chord_tones_in_range(chord.chord_tones, 60, 83)
            if not chord_pool:
                chord_pool = [60 + ((chord.root_pc - 60) % 12)]
            bar_notes = [n for n in notes if bar * beats_per_bar <= n.start < (bar + 1) * beats_per_bar]
            for n in bar_notes:
                beat = int(round(n.start - bar * beats_per_bar))
                strong = beat == 0 or beat == 2
                phrase_end = bar == request.bars - 1 and n is bar_notes[-1]
                if strong or phrase_end:
                    out.append(Note(pitch=self._nearest_chord_tone(n.pitch, chord_pool), start=n.start, duration=n.duration, velocity=n.velocity))
                else:
                    out.append(n)
        return out

    # -- 变奏 --------------------------------------------------------------

    def _variation(self, notes: List[Note], kind: str, key: str) -> List[Note]:
        """生成变奏（节奏/装饰音/逆行）。"""
        if kind == "rhythm":
            # 节奏变奏：每拍拆为两个 8 分音符
            out: List[Note] = []
            for n in notes:
                eighth = n.duration / 2.0
                out.append(Note(n.pitch, n.start, eighth * 0.9, n.velocity))
                out.append(Note(n.pitch, n.start + eighth, eighth * 0.9, n.velocity))
            return out
        if kind == "ornament":
            # 装饰音变奏：在每个主音前插入上方邻音（音阶内）
            pool = scale_pitches_in_range(key, 60, 83)
            out = []
            for n in notes:
                neighbor = self._upper_neighbor(n.pitch, pool)
                if neighbor is not None:
                    out.append(Note(neighbor, max(0.0, n.start - 0.25), 0.25, 58))
                out.append(Note(n.pitch, n.start, n.duration, n.velocity))
            return out
        if kind == "retrograde":
            # 逆行变奏：保持节奏，倒序音高
            pitches = [n.pitch for n in notes][::-1]
            return [
                Note(p, n.start, n.duration, n.velocity)
                for p, n in zip(pitches, notes)
            ]
        raise ValueError(f"未知变奏方式: {kind}")

    # -- 内部工具 ----------------------------------------------------------

    @staticmethod
    def _nearest_chord_tone(current: Optional[int], chord_pool: List[int]) -> int:
        """选一个和弦音；若已有当前音则选最近的（平滑声部进行）。"""
        if current is None:
            return chord_pool[0]
        return min(chord_pool, key=lambda p: abs(p - current))

    @staticmethod
    def _step(current: Optional[int], pool: List[int]) -> int:
        """音阶内级进（±1 音阶音）。"""
        if current is None:
            return pool[0]
        idx = pool.index(current) if current in pool else 0
        return pool[max(0, min(len(pool) - 1, idx + random.choice([-1, 1])))]

    @staticmethod
    def _upper_neighbor(pitch: int, pool: List[int]) -> Optional[int]:
        """取音阶内上方邻音；到顶则取下方邻音。"""
        if pitch in pool:
            idx = pool.index(pitch)
            if idx + 1 < len(pool):
                return pool[idx + 1]
            if idx > 0:
                return pool[idx - 1]
        return None
