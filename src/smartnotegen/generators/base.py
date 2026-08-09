"""生成器抽象：Generator 接口 + GenerationRequest + SeedContext + 音阶工具。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from music21 import key as keylib

from smartnotegen.models.notes import NoteSequence

# 大/小调音阶半音间隔
_MAJOR_INTERVALS = [0, 2, 4, 5, 7, 9, 11]
_MINOR_INTERVALS = [0, 2, 3, 5, 7, 8, 10]


def resolve_scale_pitch_classes(key: str) -> List[int]:
    """解析调式字符串为升序音级集合（C=0）。

    支持 "C major" / "A minor" / "F# minor" / "Bb major" 等 music21 可解析的调式名。

    Args:
        key: 调式名。

    Returns:
        音级列表，如 C major -> [0, 2, 4, 5, 7, 9, 11]。
    """
    parts = str(key).strip().split()
    if len(parts) == 2:
        k = keylib.Key(parts[0], parts[1])
    else:
        k = keylib.Key(parts[0])
    tonic = k.tonic.pitchClass
    intervals = _MINOR_INTERVALS if k.mode == "minor" else _MAJOR_INTERVALS
    return [(tonic + i) % 12 for i in intervals]


def scale_pitches_in_range(key: str, low: int, high: int) -> List[int]:
    """返回 [low, high] 区间内的全部音阶 MIDI pitch（升序）。"""
    pcs = resolve_scale_pitch_classes(key)
    pitches: List[int] = []
    for p in range(low, high + 1):
        if p % 12 in pcs:
            pitches.append(p)
    return pitches


def chord_tones_in_range(chord_tones: List[int], low: int, high: int) -> List[int]:
    """返回 [low, high] 区间内的全部和弦音 MIDI pitch（升序）。"""
    pitches: List[int] = []
    for p in range(low, high + 1):
        if p % 12 in chord_tones:
            pitches.append(p)
    return pitches


@dataclass
class GenerationRequest:
    """一次生成请求（由 CLI 从配置 + 参数构造）。"""

    chords: str = "C-G-Am-F"
    bpm: int = 120
    key: str = "C major"
    time_signature: str = "4/4"
    bars: int = 8
    style: str = "pop"
    seed: Optional[int] = None
    tracks: List[str] = field(default_factory=lambda: ["chords", "melody", "bass"])
    with_drums: bool = False
    variations: int = 1  # 仅 music21 乐理旋律生成使用（--variations）
    # P2-2 乐理规则（全部默认关闭，不破坏 P0 输出）
    enable_voice_leading: bool = False
    enable_counterpoint: bool = False
    enable_inversion: bool = False
    rhythm_pattern: Optional[str] = None  # 引用 RhythmPatternRegistry 名
    # P2-4 风格参数（CLI 解析 StyleRegistry 后注入；None 时用生成器内置预设）
    style_instruments: Optional[dict] = None
    melody_profile: Optional[dict] = None


class SeedContext:
    """随机种子上下文：进入时统一设置 random / numpy（及已安装的 torch）。

    任何使用随机的生成器都必须通过 SeedContext 保证可复现性。
    P0 不 import torch —— 这里仅当 torch 已安装时才设置，避免引入重型依赖。
    """

    def __init__(self, seed: Optional[int]) -> None:
        self.seed = seed

    def __enter__(self) -> "SeedContext":
        if self.seed is not None:
            import random

            import numpy as np

            random.seed(self.seed)
            # numpy 的随机种子要求 0 <= seed <= 2**32-1；派生种子（seed*1000+i）可能超界，
            # 统一取模保持确定性且互不冲突（1000 < 2**32，批次内无碰撞）。
            np_seed = self.seed % (2**32)
            np.random.seed(np_seed)
            try:
                import torch  # type: ignore

                torch.manual_seed(self.seed)
            except ImportError:
                pass  # P0 环境无 torch，跳过即可
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


class Generator(ABC):
    """生成器抽象接口：generate(request) -> NoteSequence。"""

    @abstractmethod
    def generate(self, request: GenerationRequest) -> NoteSequence:
        """生成一段 NoteSequence。"""
        raise NotImplementedError
