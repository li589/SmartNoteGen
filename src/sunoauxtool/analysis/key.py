"""调性估计（R13）：chroma 直方图 × Krumhansl-Schmuckler 剖面相关。

方法
----
1. STFT 幅度谱 → 按频率折算 MIDI 音高 → 累加成 12 维音级直方图（chroma）；
2. 把 chroma 依次旋到 12 个候选主音，分别与大调 / 小调剖面做 **Pearson 相关**；
3. 取相关系数最大者（即 Krumhansl-Schmuckler 判据）为调性。

输入是**音频**（WAV）；若已有音高序列（如转谱 MIDI 结果），可用
:func:`chroma_from_pitches` 直接构造 chroma 再送 :func:`estimate_key_from_chroma`。

numpy-only，与 ``spectral.py`` 共用 STFT 底座。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from sunoauxtool.analysis.spectral import TEMPO_FRAME, TEMPO_HOP, stft_magnitude

#: Krumhansl-Kessler 调性剖面（索引 = 相对主音的半音级 0..11）
KK_MAJOR = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
KK_MINOR = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

#: 低于此频率不计入 chroma（A1 以下多为直流/隆隆声，会污染音级直方图）
_MIN_HZ = 55.0


@dataclass
class KeyEstimate:
    """调性估计结果。"""

    key: str  # 主音名（如 "C"）
    mode: str  # "major" | "minor"
    confidence: float  # Pearson 相关系数 ∈ [-1, 1]；越大越确定
    chroma: np.ndarray  # 归一化后的 12 维音级直方图

    @property
    def label(self) -> str:
        """如 ``"C major"``。"""
        return f"{self.key} {self.mode}"


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson 相关系数；退化（零方差）时返回 0。"""
    da = a - a.mean()
    db = b - b.mean()
    denom = float(np.linalg.norm(da) * np.linalg.norm(db))
    if denom == 0.0:
        return 0.0
    return float(da @ db / denom)


def chroma_from_mono(
    mono: np.ndarray,
    sr: int,
    frame: int = TEMPO_FRAME,
    hop: int = TEMPO_HOP,
) -> np.ndarray:
    """从单声道信号算 12 维音级直方图（已归一化，和为 1；全静音返回全 0）。"""
    spec = stft_magnitude(np.asarray(mono, dtype=np.float64), frame, hop)
    if spec.shape[0] == 0:
        return np.zeros(12, dtype=np.float64)

    n_bins = spec.shape[1]
    freqs = np.arange(n_bins, dtype=np.float64) * (float(sr) / frame)
    valid = freqs >= _MIN_HZ
    if not valid.any():
        return np.zeros(12, dtype=np.float64)

    f_valid = freqs[valid]
    midi = 69.0 + 12.0 * np.log2(f_valid / 440.0)
    pitch_class = np.mod(np.rint(midi), 12).astype(int)

    chroma = np.zeros(12, dtype=np.float64)
    np.add.at(chroma, pitch_class, spec[:, valid].sum(axis=0))
    total = chroma.sum()
    return chroma / total if total > 0 else chroma


def chroma_from_pitches(
    pitches: Sequence[int],
    weights: Optional[Sequence[float]] = None,
) -> np.ndarray:
    """从 MIDI 音高序列构造 chroma（时长/力度可用 weights 加权）。"""
    chroma = np.zeros(12, dtype=np.float64)
    if len(pitches) == 0:
        return chroma
    w = np.ones(len(pitches), dtype=np.float64) if weights is None else np.asarray(
        weights, dtype=np.float64
    )
    pc = np.mod(np.asarray(pitches, dtype=int), 12)
    np.add.at(chroma, pc, w)
    total = chroma.sum()
    return chroma / total if total > 0 else chroma


def estimate_key_from_chroma(chroma: np.ndarray) -> KeyEstimate:
    """对已构造好的 chroma 做 Krumhansl-Schmuckler 判据。"""
    chroma = np.asarray(chroma, dtype=np.float64)
    if chroma.sum() <= 0:
        return KeyEstimate("C", "major", 0.0, chroma)

    best_score = -2.0
    best_shift = 0
    best_mode = "major"
    for shift in range(12):
        rotated = np.roll(chroma, -shift)  # 把候选主音旋到索引 0
        for mode, profile in (("major", KK_MAJOR), ("minor", KK_MINOR)):
            score = _pearson(rotated, profile)
            if score > best_score:
                best_score, best_shift, best_mode = score, shift, mode
    return KeyEstimate(NOTE_NAMES[best_shift], best_mode, float(best_score), chroma)


def estimate_key(mono: np.ndarray, sr: int) -> KeyEstimate:
    """估计单声道信号的调性。"""
    return estimate_key_from_chroma(chroma_from_mono(mono, sr))


def estimate_key_file(wav_path: str) -> KeyEstimate:
    """估计 WAV 文件的调性。"""
    from sunoauxtool.analysis.tempo import read_wav_mono

    mono, sr = read_wav_mono(wav_path)
    return estimate_key(mono, sr)


__all__ = [
    "KK_MAJOR",
    "KK_MINOR",
    "NOTE_NAMES",
    "KeyEstimate",
    "chroma_from_mono",
    "chroma_from_pitches",
    "estimate_key",
    "estimate_key_from_chroma",
    "estimate_key_file",
]
