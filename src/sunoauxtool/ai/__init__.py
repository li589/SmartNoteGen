"""AI 适配器包（P1）。模块顶部零重型 import。"""

from sunoauxtool.ai.base import AIGenerator
from sunoauxtool.ai.musicgen import MusicGenAdapter
from sunoauxtool.ai.diffrhythm import DiffRhythmAdapter
from sunoauxtool.ai.basicpitch import BasicPitchAdapter

__all__ = ["AIGenerator", "MusicGenAdapter", "DiffRhythmAdapter", "BasicPitchAdapter"]
