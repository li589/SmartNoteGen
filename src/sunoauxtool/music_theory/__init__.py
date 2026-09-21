"""乐理规则包（P2-2）：声部进行 / 对位 / 转位 / 节奏型库。

全部规则默认关闭（由 GenerationRequest 字段控制），不破坏 P0 输出。
"""

from sunoauxtool.music_theory.counterpoint import CONSONANT_SETS, CounterpointEngine
from sunoauxtool.music_theory.inversion import InversionResolver
from sunoauxtool.music_theory.rhythm_patterns import RhythmPattern, RhythmPatternRegistry
from sunoauxtool.music_theory.voice_leading import Violation, VoiceLeadingChecker

__all__ = [
    "CONSONANT_SETS",
    "CounterpointEngine",
    "InversionResolver",
    "RhythmPattern",
    "RhythmPatternRegistry",
    "Violation",
    "VoiceLeadingChecker",
]
