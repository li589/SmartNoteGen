"""AI 适配器包（P1）。模块顶部零重型 import。"""

from typing import Dict

from sunoauxtool.ai.base import AIGenerator
from sunoauxtool.ai.musicgen import MusicGenAdapter
from sunoauxtool.ai.diffrhythm import DiffRhythmAdapter
from sunoauxtool.ai.basicpitch import BasicPitchAdapter

def discover_ai_backends() -> Dict[str, type]:
    """AI 后端注册表 ``{name: AIGenerator 子类}`` = 内置 + entry point 插件。

    扩展点：``sunoauxtool.ai_backends``（见 :mod:`sunoauxtool.plugins`）。
    ``basic-pitch`` 是**转谱**后端（不走 generate），见
    :func:`sunoauxtool.analysis.discover_transcribe_backends`。
    """
    from sunoauxtool.plugins import discover

    builtins: Dict[str, type] = {
        "musicgen": MusicGenAdapter,
        "diffrhythm": DiffRhythmAdapter,
    }
    return discover("ai_backends", builtins, base=AIGenerator, instantiate=False)


__all__ = [
    "AIGenerator",
    "MusicGenAdapter",
    "DiffRhythmAdapter",
    "BasicPitchAdapter",
    "discover_ai_backends",
]
