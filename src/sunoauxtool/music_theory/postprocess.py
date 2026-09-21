"""生成后处理集成入口（P2-2e）：规则作用于生成链后处理阶段。

全部规则默认关闭；由 GenerationRequest 的 enable_* 字段控制。
"""

from __future__ import annotations

from typing import List, Tuple

from sunoauxtool.generators.base import GenerationRequest
from sunoauxtool.models.notes import NoteSequence
from sunoauxtool.music_theory.counterpoint import CounterpointEngine
from sunoauxtool.music_theory.inversion import InversionResolver
from sunoauxtool.music_theory.voice_leading import Violation, VoiceLeadingChecker


def apply_postprocess(
    seq: NoteSequence,
    request: GenerationRequest,
) -> Tuple[NoteSequence, List[Violation]]:
    """按 request 开关应用乐理规则后处理。

    Args:
        seq: 生成器产出的 NoteSequence（就地修改）。
        request: 生成请求（enable_voice_leading / enable_counterpoint / enable_inversion）。

    Returns:
        (处理后的 NoteSequence, 检测到的违规列表)。
    """
    violations: List[Violation] = []
    checker = VoiceLeadingChecker()
    if request.enable_voice_leading:
        violations.extend(checker.detect_parallel_fifths_octaves(seq))
        violations.extend(checker.detect_crossing(seq))
        seq = checker.correct_or_report(seq)
    if request.enable_counterpoint:
        seq = CounterpointEngine(strictness=1).enforce(seq)
    if request.enable_inversion:
        seq = InversionResolver().resolve(seq)
    return seq, violations
