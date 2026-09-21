"""和弦估计（R13）：逐窗 chroma × 三和弦模板匹配 → 分段和弦进行。

方法
----
1. 滑窗 chroma（:func:`chromagram`，复用 ``key.chroma_from_mono``）；
2. 每窗与 48 个三和弦模板（12 根音 × maj/min/dim/aug）算**余弦相似度**，取最大；
3. 连续相同标签合并为时间段（静音窗不产出）。

是「和声显著度」的简化版：不做低音独立识别，故**转位不区分**
（C-E-G 与 E-G-C 都判 Cmaj）。需要更细的转位/七和弦请接外部复调转谱。

numpy-only。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from sunoauxtool.analysis.key import NOTE_NAMES, chroma_from_mono

#: 三和弦音程（相对根音的半音）
TRIAD_INTERVALS = {
    "maj": (0, 4, 7),
    "min": (0, 3, 7),
    "dim": (0, 3, 6),
    "aug": (0, 4, 8),
}

#: 默认参与匹配的质量（越多越容易误判，四质量已够用）
DEFAULT_QUALITIES: Tuple[str, ...] = ("maj", "min", "dim", "aug")


def chord_templates(
    qualities: Sequence[str] = DEFAULT_QUALITIES,
) -> Tuple[np.ndarray, List[Tuple[int, str]]]:
    """构造三和弦模板矩阵 ``(n_templates, 12)`` 与 ``[(root_pc, quality)]`` 标签。"""
    rows: List[np.ndarray] = []
    labels: List[Tuple[int, str]] = []
    for root in range(12):
        for q in qualities:
            t = np.zeros(12, dtype=np.float64)
            for iv in TRIAD_INTERVALS[q]:
                t[(root + iv) % 12] = 1.0
            rows.append(t)
            labels.append((root, q))
    return np.array(rows, dtype=np.float64), labels


def chromagram(
    mono: np.ndarray,
    sr: int,
    win_s: float = 0.5,
    hop_s: float = 0.25,
) -> Tuple[np.ndarray, float]:
    """逐窗 chroma：返回 ``(n_windows, 12)`` 与**窗步进秒数**。

    窗长决定时间/频率精度的交换（0.5s 适合和弦级；再短会抓不住低音）。
    """
    mono = np.asarray(mono, dtype=np.float64)
    win = max(1, int(win_s * sr))
    hop = max(1, int(hop_s * sr))
    n = 1 + (len(mono) - win) // hop if len(mono) >= win else 0
    if n <= 0:
        return np.zeros((0, 12), dtype=np.float64), float(hop) / float(sr)
    out = np.zeros((n, 12), dtype=np.float64)
    for i in range(n):
        out[i] = chroma_from_mono(mono[i * hop : i * hop + win], sr)
    return out, float(hop) / float(sr)


@dataclass
class ChordSegment:
    """一段和弦。"""

    start: float
    end: float
    root: str  # 根音名（如 "C"）
    quality: str  # maj / min / dim / aug

    @property
    def label(self) -> str:
        """如 ``"Cmaj"``。"""
        return f"{self.root}{self.quality}"


def estimate_chords(
    mono: np.ndarray,
    sr: int,
    win_s: float = 0.5,
    hop_s: float = 0.25,
    qualities: Sequence[str] = DEFAULT_QUALITIES,
) -> List[ChordSegment]:
    """估计和弦进行（静音窗不产出，故时间段可能不连续）。"""
    chroma, hop_sec = chromagram(mono, sr, win_s=win_s, hop_s=hop_s)
    if chroma.shape[0] == 0:
        return []

    templates, labels = chord_templates(qualities)
    t_norm = templates / np.linalg.norm(templates, axis=1, keepdims=True)

    seq: List[Optional[Tuple[int, str]]] = []
    for i in range(chroma.shape[0]):
        row = chroma[i]
        if row.sum() <= 0:  # 静音
            seq.append(None)
            continue
        c_norm = row / (np.linalg.norm(row) or 1.0)
        best = int(np.argmax(t_norm @ c_norm))
        seq.append(labels[best])

    segments: List[ChordSegment] = []
    start_i = 0
    for i in range(1, len(seq) + 1):
        if i == len(seq) or seq[i] != seq[start_i]:
            label = seq[start_i]
            if label is not None:
                segments.append(
                    ChordSegment(
                        start=start_i * hop_sec,
                        end=i * hop_sec,
                        root=NOTE_NAMES[label[0]],
                        quality=label[1],
                    )
                )
            start_i = i
    return segments


def estimate_chords_file(wav_path: str, **kw) -> List[ChordSegment]:
    """估计 WAV 文件的和弦进行。"""
    from sunoauxtool.analysis.tempo import read_wav_mono

    mono, sr = read_wav_mono(wav_path)
    return estimate_chords(mono, sr, **kw)


__all__ = [
    "TRIAD_INTERVALS",
    "DEFAULT_QUALITIES",
    "ChordSegment",
    "chord_templates",
    "chromagram",
    "estimate_chords",
    "estimate_chords_file",
]
