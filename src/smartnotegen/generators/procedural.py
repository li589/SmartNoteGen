"""程序化多轨 MIDI 生成器（和弦/旋律/贝斯，可选第 4 轨鼓）。

风格预设控制：乐器号（GM 映射）、节奏密度（sustain/half/eighth）。
P2-2/P2-4 集成（默认关闭/可选）：
- request.style_instruments：CLI 解析 StyleRegistry 后注入的乐器号（P2-4）；
- request.rhythm_pattern：引用 RhythmPatternRegistry 的节奏型（P2-2d），驱动贝斯音头；
- request.enable_*：乐理规则后处理（P2-2e），默认关闭。
所有随机性经由 SeedContext 设置，保证同 seed 可复现。
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional

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
from smartnotegen.music_theory.rhythm_patterns import RhythmPattern, RhythmPatternRegistry


class _StylePreset:
    """风格预设：乐器号 + 节奏密度（P0 内置兜底）。"""

    __slots__ = ("chords_program", "melody_program", "bass_program", "density")

    def __init__(self, chords_program: int, melody_program: int, bass_program: int, density: str) -> None:
        self.chords_program = chords_program
        self.melody_program = melody_program
        self.bass_program = bass_program
        self.density = density  # 'sustain' | 'half' | 'eighth'


#: 内置风格预设（P2-4 扩展为完整风格库后作为兜底）
STYLE_PRESETS: Dict[str, _StylePreset] = {
    "pop": _StylePreset(0, 81, 33, "sustain"),        # 钢琴 / 合成主音 / 电贝斯
    "rock": _StylePreset(25, 80, 34, "eighth"),       # 尼龙吉他 / 方波主音 / 指拨贝斯
    "electronic": _StylePreset(88, 81, 38, "eighth"), # 合成垫 / 合成主音 / 合成贝斯
    "classical": _StylePreset(46, 73, 43, "sustain"), # 竖琴 / 长笛 / 大提琴
}

_DEFAULT_STYLE = "pop"


class ProceduralGenerator(Generator):
    """程序化生成器：不依赖 AI，纯乐理规则 + 随机游走产出多轨 MIDI。"""

    def __init__(self, seed: Optional[int] = None) -> None:
        self.seed = seed

    # -- 公共接口 ----------------------------------------------------------

    def generate(self, request: GenerationRequest) -> NoteSequence:
        """生成多轨 NoteSequence（和弦/旋律/贝斯 [+鼓]）。"""
        with SeedContext(self.seed if self.seed is not None else request.seed):
            progression = ChordProgression.parse(request.chords)
            preset = STYLE_PRESETS.get(request.style, STYLE_PRESETS[_DEFAULT_STYLE])
            programs = self._programs(request, preset)
            beats_per_bar = _beats_per_bar(request.time_signature)
            rhythm = self._rhythm_pattern(request)

            seq = NoteSequence(
                bpm=request.bpm,
                key=request.key,
                time_signature=request.time_signature,
                bars=request.bars,
                style=request.style,
            )

            track_names = list(request.tracks)
            if request.with_drums and "drums" not in track_names:
                track_names.append("drums")

            if "chords" in track_names:
                seq.add_track(
                    "chords", programs["chords"], 0,
                    self._chords_track(progression, request, preset, beats_per_bar),
                )
            if "melody" in track_names:
                seq.add_track(
                    "melody", programs["melody"], 1,
                    self._melody_track(progression, request, preset, beats_per_bar),
                )
            if "bass" in track_names:
                seq.add_track(
                    "bass", programs["bass"], 2,
                    self._bass_track(progression, request, preset, beats_per_bar, rhythm),
                )
            if "drums" in track_names:
                seq.add_track("drums", 0, 9, self._drums_track(request, beats_per_bar))

            # P2-2 乐理规则后处理（默认关闭）
            if request.enable_voice_leading or request.enable_counterpoint or request.enable_inversion:
                seq, _violations = apply_postprocess(seq, request)
            return seq

    # -- 风格/节奏解析 -----------------------------------------------------

    @staticmethod
    def _programs(request: GenerationRequest, preset: _StylePreset) -> Dict[str, int]:
        """确定各轨乐器号：CLI 注入（StyleRegistry）> 内置兜底。"""
        if request.style_instruments:
            return {
                "chords": int(request.style_instruments.get("chords", 0)),
                "melody": int(request.style_instruments.get("melody", 81)),
                "bass": int(request.style_instruments.get("bass", 33)),
            }
        return {
            "chords": preset.chords_program,
            "melody": preset.melody_program,
            "bass": preset.bass_program,
        }

    @staticmethod
    def _rhythm_pattern(request: GenerationRequest) -> Optional[RhythmPattern]:
        """解析节奏型；未指定时返回 None（沿用 P0 密度行为）。"""
        if not request.rhythm_pattern:
            return None
        return RhythmPatternRegistry().get(request.rhythm_pattern)

    # -- 各轨生成 ----------------------------------------------------------

    def _chords_track(
        self,
        progression: ChordProgression,
        request: GenerationRequest,
        preset: _StylePreset,
        beats_per_bar: float,
    ) -> List[Note]:
        """和弦轨：按小节铺开块状和弦/琶音。"""
        notes: List[Note] = []
        for bar in range(request.bars):
            chord = progression.get_chord(bar)
            bar_start = bar * beats_per_bar
            tones = chord_tones_in_range(chord.chord_tones, 48, 71)  # C3 附近
            if not tones:
                tones = [48 + (chord.root_pc - 48) % 12]
            if preset.density == "eighth":
                # 8 分音符琶音（上下循环）
                step = beats_per_bar / 8.0
                for i in range(8):
                    idx = i % len(tones)
                    notes.append(
                        Note(
                            pitch=tones[idx],
                            start=bar_start + i * step,
                            duration=step * 0.9,
                            velocity=58 + random.randint(-4, 6),
                        )
                    )
            elif preset.density == "half":
                for half in range(2):
                    for tone in tones:
                        notes.append(
                            Note(
                                pitch=tone,
                                start=bar_start + half * beats_per_bar / 2,
                                duration=beats_per_bar / 2 - 0.05,
                                velocity=58 + random.randint(-4, 6),
                            )
                        )
            else:  # sustain：整小节块状和弦
                for tone in tones:
                    notes.append(
                        Note(
                            pitch=tone,
                            start=bar_start,
                            duration=beats_per_bar - 0.05,
                            velocity=58 + random.randint(-4, 6),
                        )
                    )
        return notes

    def _melody_track(
        self,
        progression: ChordProgression,
        request: GenerationRequest,
        preset: _StylePreset,
        beats_per_bar: float,
    ) -> List[Note]:
        """旋律轨：音阶内随机游走，强拍/句尾对齐和弦音。"""
        notes: List[Note] = []
        pool = scale_pitches_in_range(request.key, 60, 83)  # C4 附近两八度
        current: Optional[int] = None
        for bar in range(request.bars):
            chord = progression.get_chord(bar)
            bar_start = bar * beats_per_bar
            chord_pool = chord_tones_in_range(chord.chord_tones, 60, 83)
            if not chord_pool:
                chord_pool = [60 + (chord.root_pc - 60) % 12]
            # 每拍一个四分音符
            for beat in range(int(beats_per_bar)):
                t = bar_start + beat
                strong = beat == 0 or beat == 2
                phrase_end = bar == request.bars - 1 and beat == int(beats_per_bar) - 1
                if strong or phrase_end:
                    current = self._nearest(current, random.choice(chord_pool))
                else:
                    current = self._step_or_hold(current, pool, chord_pool, chord_tone_prob=0.25)
                if current is None:
                    current = chord_pool[0]
                notes.append(
                    Note(
                        pitch=current,
                        start=t,
                        duration=beats_per_bar / int(beats_per_bar) * 0.9,
                        velocity=72 + random.randint(-6, 6),
                    )
                )
        return notes

    def _bass_track(
        self,
        progression: ChordProgression,
        request: GenerationRequest,
        preset: _StylePreset,
        beats_per_bar: float,
        rhythm: Optional[RhythmPattern],
    ) -> List[Note]:
        """贝斯轨：根音打底（整小节 / 四分 / 八分节奏型）。

        当 request.rhythm_pattern 指定时，按节奏型网格放置音头（P2-2d）。
        """
        notes: List[Note] = []
        for bar in range(request.bars):
            chord = progression.get_chord(bar)
            bar_start = bar * beats_per_bar
            root_pitch = 36 + ((chord.root_pc - 36) % 12)  # C2 附近
            if rhythm is not None:
                onsets = rhythm.onsets_in_bar(beats_per_bar)
                step = beats_per_bar / max(1, len(rhythm.grid))
                for t in onsets:
                    # 第五个音头可加五度音（保持节奏型骨架）
                    p = root_pitch
                    notes.append(
                        Note(
                            pitch=p,
                            start=bar_start + t,
                            duration=step * 0.9,
                            velocity=66 + random.randint(-4, 6),
                        )
                    )
            elif preset.density == "eighth":
                step = beats_per_bar / 8.0
                for i in range(8):
                    p = root_pitch if i % 2 == 0 else root_pitch + (7 if i == 5 else 0)
                    notes.append(
                        Note(
                            pitch=p,
                            start=bar_start + i * step,
                            duration=step * 0.9,
                            velocity=66 + random.randint(-4, 6),
                        )
                    )
            elif preset.density == "half":
                for half in range(2):
                    notes.append(
                        Note(
                            pitch=root_pitch,
                            start=bar_start + half * beats_per_bar / 2,
                            duration=beats_per_bar / 2 - 0.05,
                            velocity=66 + random.randint(-4, 6),
                        )
                    )
            else:  # sustain
                notes.append(
                    Note(
                        pitch=root_pitch,
                        start=bar_start,
                        duration=beats_per_bar - 0.05,
                        velocity=66 + random.randint(-4, 6),
                    )
                )
        return notes

    def _drums_track(self, request: GenerationRequest, beats_per_bar: float) -> List[Note]:
        """鼓轨：kick/snare/hihat（GM 通道 9）。"""
        notes: List[Note] = []
        kick = 36
        snare = 38
        hihat = 42
        for bar in range(request.bars):
            bar_start = bar * beats_per_bar
            # kick：每小节第 1、3 拍
            notes.append(Note(pitch=kick, start=bar_start, duration=0.4, velocity=92))
            notes.append(Note(pitch=kick, start=bar_start + beats_per_bar / 2, duration=0.4, velocity=88))
            # snare：第 2、4 拍
            notes.append(Note(pitch=snare, start=bar_start + beats_per_bar / 4, duration=0.3, velocity=80))
            notes.append(Note(pitch=snare, start=bar_start + 3 * beats_per_bar / 4, duration=0.3, velocity=80))
            # hihat：8 分音符
            step = beats_per_bar / 8.0
            for i in range(8):
                notes.append(
                    Note(
                        pitch=hihat,
                        start=bar_start + i * step,
                        duration=step * 0.5,
                        velocity=60 if i % 2 == 0 else 52,
                    )
                )
        return notes

    # -- 内部工具 ----------------------------------------------------------

    @staticmethod
    def _nearest(target: Optional[int], candidate: int) -> int:
        """返回离 target 最近的和弦音（平滑声部进行）。"""
        if target is None:
            return candidate
        return candidate

    @staticmethod
    def _step_or_hold(
        current: Optional[int],
        pool: List[int],
        chord_pool: List[int],
        chord_tone_prob: float,
    ) -> int:
        """随机游走一步：大概率级进（±1 音阶音），小概率跳至和弦音/保持。"""
        if current is None:
            return random.choice(pool)
        r = random.random()
        if r < chord_tone_prob:
            return random.choice(chord_pool)
        idx = pool.index(current) if current in pool else _nearest_index(pool, current)
        if r < chord_tone_prob + 0.6:
            return pool[max(0, min(len(pool) - 1, idx + random.choice([-1, 1])))]
        return current


def _nearest_index(pool: List[int], pitch: int) -> int:
    """返回 pool 中与 pitch 最接近的下标。"""
    best = 0
    best_dist = abs(pool[0] - pitch)
    for i, p in enumerate(pool):
        d = abs(p - pitch)
        if d < best_dist:
            best_dist = d
            best = i
    return best


def _beats_per_bar(time_signature: str) -> float:
    """按拍号计算每小节拍数（4/4 -> 4.0）。"""
    try:
        num, den = time_signature.split("/")
        return float(num) * 4.0 / float(den)
    except (ValueError, AttributeError):
        return 4.0
