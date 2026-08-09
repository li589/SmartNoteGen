"""AI 适配器包（P1）。模块顶部零重型 import。"""

from smartnotegen.ai.base import AIGenerator
from smartnotegen.ai.musicgen import MusicGenAdapter
from smartnotegen.ai.diffrhythm import DiffRhythmAdapter

__all__ = ["AIGenerator", "MusicGenAdapter", "DiffRhythmAdapter"]
