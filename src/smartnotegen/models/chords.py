"""和弦模型：Chord / ChordProgression（解析 "C-G-Am-F"）。

统一入口 ChordProgression.parse，内部用 music21 解析根音与和弦音级，
程序化生成与乐理旋律生成共用，保证两套生成器对同一和弦进行理解一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from music21 import chord as m21_chord
from music21 import harmony

from smartnotegen.exceptions import ParameterError

#: 降号根音 → 等音升号拼写（music21 对裸降号和弦名解析缺陷的兼容映射）。
#: music21 的 ChordSymbol 无法解析裸降号根音（"Bb" 抛 "Invalid chord abbreviation 'b'"），
#: 且对 "Bb7" 会误解析为 B7（根音 B）。按等音映射为升号拼写后，
#: 既保证可解析，又保证和弦音级正确（Bb→A#、Eb→D#、Ab→G# 等音级集合完全一致）。
_FLAT_ROOT_TO_SHARP: dict[str, str] = {
    "Cb": "B",
    "Db": "C#",
    "Eb": "D#",
    "Fb": "E",
    "Gb": "F#",
    "Ab": "G#",
    "Bb": "A#",
}


@dataclass
class Chord:
    """单个和弦。

    Attributes:
        symbol: 原始和弦符号，如 "C" / "Am" / "G7"。
        root_pc: 根音音级（0-11，C=0）。
        chord_tones: 和弦音音级（升序、去重），如 C 大调 [0, 4, 7]。
        beats: 持续拍数。
    """

    symbol: str
    root_pc: int
    chord_tones: List[int]
    beats: float = 4.0

    def contains(self, pitch_class: int) -> bool:
        """判断某音级是否为和弦音。"""
        return pitch_class % 12 in self.chord_tones


@dataclass
class ChordProgression:
    """和弦进行：按小节索引取和弦。

    Attributes:
        chords: 和弦列表。
        beats_per_chord: 每个和弦的持续拍数（默认 4 拍 = 1 小节 4/4）。
    """

    chords: List[Chord] = field(default_factory=list)
    beats_per_chord: float = 4.0

    @classmethod
    def parse(cls, text: str, beats_per_chord: float = 4.0) -> "ChordProgression":
        """解析 "C-G-Am-F" 风格的和弦进行字符串。

        支持大/小/属七等 music21 ChordSymbol 可解析的符号：
            C、Am、G7、F、Dm、Em、Bdim、Am7、Cmaj7、Csus4、Cadd9 等。

        Args:
            text: 以 "-" 分隔的和弦符号。
            beats_per_chord: 每个和弦持续拍数。

        Returns:
            ChordProgression 实例。

        Raises:
            ParameterError: 字符串为空或包含无法解析的和弦。
        """
        if not text or not str(text).strip():
            raise ParameterError("和弦进行不能为空，例如 --chords 'C-G-Am-F'", code=1)

        parts = [p.strip() for p in str(text).split("-") if p.strip()]
        if not parts:
            raise ParameterError(f"无法解析和弦进行: {text!r}", code=1)

        chords: List[Chord] = []
        for part in parts:
            chords.append(cls._parse_single(part, beats_per_chord))
        return cls(chords=chords, beats_per_chord=beats_per_chord)

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """将降号根音的和弦名归一化为等音升号拼写（仅处理根音音名）。

        仅替换根音位置的降号（如 ``Bb7`` 的 ``Bb`` → ``A#``），不触碰
        和弦性质/扩展音中的 b（如 ``Cm7b5`` 的 ``b5`` 保持原样）。
        无降号根音时原样返回。
        """
        if not symbol:
            return symbol
        s = str(symbol).strip()
        # 根音 token：音名 + 可选升降号（如 "B"、"Bb"、"C#"、"B-"）
        root = s[:2] if len(s) >= 2 and s[1] in "#b-" else s[:1]
        mapped = _FLAT_ROOT_TO_SHARP.get(root)
        if mapped is None:
            return s
        return mapped + s[len(root):]

    @staticmethod
    def _parse_single(symbol: str, beats: float) -> Chord:
        """解析单个和弦符号为 Chord。"""
        try:
            cs = harmony.ChordSymbol(ChordProgression._normalize_symbol(symbol))
            root = cs.root()
            if root is None:
                raise ParameterError(
                    f"无法确定和弦根音: {symbol!r}（支持 C/Am/G7 等和弦符号）", code=1
                )
            # pitchClasses 返回升序去重的音级集合
            tones = sorted(set(cs.pitchClasses))
            root_pc = root.pitchClass
        except (m21_chord.ChordException, ValueError, KeyError) as exc:
            raise ParameterError(
                f"无法解析和弦符号: {symbol!r}（支持 C/Am/G7 等，示例 'C-G-Am-F'）", code=1
            ) from exc
        if not tones:
            raise ParameterError(f"和弦音为空: {symbol!r}", code=1)
        return Chord(symbol=symbol, root_pc=root_pc, chord_tones=tones, beats=beats)

    def get_chord(self, bar_index: int) -> Chord:
        """按小节索引取和弦（循环使用直至覆盖全部小节）。"""
        if not self.chords:
            raise ParameterError("和弦进行为空", code=1)
        return self.chords[bar_index % len(self.chords)]

    def __len__(self) -> int:
        return len(self.chords)

    def __iter__(self):
        return iter(self.chords)
