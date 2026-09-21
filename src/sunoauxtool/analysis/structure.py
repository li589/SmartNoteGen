"""音乐结构分段（R13）：自相似矩阵（SSM）+ Foote 新奇度 + 峰值提取。

方法
----
1. 滑窗 chroma（复用 ``chords.chromagram``）→ 特征序列；
2. 余弦相似度自相似矩阵 ``S``（``S[i,j]`` = 第 i 窗与第 j 窗的和声相似程度）；
3. **Foote 棋盘核**（高斯加权的「同块 +1 / 异块 −1」）沿对角线卷积 → 新奇度曲线；
4. 局部极大 + 均值/标准差阈值 + 最小段长约束 → 段落边界。

副歌/主歌的**语义标签不做判定**（那是更高层任务），只输出边界时间轴，
供 ``videomaker --style score`` 的章节切换等下游使用。

numpy-only。注意 SSM 是 O(n²)：默认 0.25s 步进下，5 分钟素材约 1200 窗
（1.4M 元素，可接受）；更长素材请调大 ``hop_s``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np

from sunoauxtool.analysis.chords import chromagram


@dataclass
class SectionSegment:
    """一个结构段（按出现顺序编号）。"""

    index: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def self_similarity(chroma: np.ndarray) -> np.ndarray:
    """余弦相似度自相似矩阵 ``(n, n)``；零向量窗按 0 相似处理。"""
    chroma = np.asarray(chroma, dtype=np.float64)
    norms = np.linalg.norm(chroma, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    z = chroma / norms
    return z @ z.T


def _gauss_window(size: int) -> np.ndarray:
    """半窗高斯 taper（Foote 核用）。"""
    x = np.arange(size, dtype=np.float64)
    return np.exp(-0.5 * ((x - size / 2.0) / (size / 4.0)) ** 2)


def foote_novelty(ssm: np.ndarray, k: int = 8) -> np.ndarray:
    """Foote 棋盘核新奇度曲线（长度 n，越大越像段落边界）。"""
    ssm = np.asarray(ssm, dtype=np.float64)
    n = ssm.shape[0]
    if n == 0:
        return np.zeros(0, dtype=np.float64)

    size = max(2, min(int(k), max(1, n // 2)))
    g2 = np.outer(_gauss_window(size), _gauss_window(size))
    kernel = np.block([[g2, -g2], [-g2, g2]])
    ks = kernel.shape[0]
    half = ks // 2

    novelty = np.zeros(n, dtype=np.float64)
    for t in range(n):
        lo, hi = t - half, t + half
        a0, a1 = max(0, lo), min(n, hi)
        if a1 <= a0:
            continue
        block = np.zeros((ks, ks), dtype=np.float64)
        b0 = a0 - lo
        b1 = b0 + (a1 - a0)
        block[b0:b1, b0:b1] = ssm[a0:a1, a0:a1]
        novelty[t] = float((block * kernel).sum())
    return novelty


def pick_peaks(
    x: np.ndarray, min_distance: int = 4, threshold_scale: float = 1.0
) -> List[int]:
    """局部极大 + ``mean + threshold_scale*std`` 阈值 + 最小间距（保留更强者）。"""
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return []
    thr = x.mean() + threshold_scale * x.std()
    idx: List[int] = []
    for i in range(x.size):
        if x[i] < thr:
            continue
        left = x[i - 1] if i > 0 else -np.inf
        right = x[i + 1] if i + 1 < x.size else -np.inf
        if x[i] < left or x[i] < right:
            continue
        if idx and i - idx[-1] < min_distance:
            if x[i] > x[idx[-1]]:
                idx[-1] = i
            continue
        idx.append(i)
    return idx


def estimate_structure(
    mono: np.ndarray,
    sr: int,
    win_s: float = 0.5,
    hop_s: float = 0.25,
    k: int = 8,
    min_section_s: float = 4.0,
    threshold_scale: float = 1.0,
) -> List[SectionSegment]:
    """估计结构段落边界。

    Args:
        mono / sr: 单声道信号与采样率。
        win_s / hop_s: chroma 窗长与步进（秒）。
        k: Foote 核半宽（窗数）。
        min_section_s: 最小段长（秒），用于抑制过密边界。
        threshold_scale: 峰值阈值（均值 + 该系数 × 标准差）。

    Returns:
        按出现顺序的 :class:`SectionSegment` 列表（至少 1 段）。
    """
    chroma, hop_sec = chromagram(mono, sr, win_s=win_s, hop_s=hop_s)
    n = chroma.shape[0]
    if n < 4:
        return []

    novelty = foote_novelty(self_similarity(chroma), k=k)
    min_dist = max(1, int(min_section_s / hop_sec))
    peaks = pick_peaks(novelty, min_distance=min_dist, threshold_scale=threshold_scale)
    # 落在首尾的峰会产生零长段落，剔除；排序去重保证边界单调
    peaks = sorted({p for p in peaks if 0 < p < n})

    bounds = [0] + peaks + [n]
    return [
        SectionSegment(index=i, start=bounds[i] * hop_sec, end=bounds[i + 1] * hop_sec)
        for i in range(len(bounds) - 1)
    ]


def estimate_structure_file(wav_path: str, **kw) -> List[SectionSegment]:
    """估计 WAV 文件的结构分段。"""
    from sunoauxtool.analysis.tempo import read_wav_mono

    mono, sr = read_wav_mono(wav_path)
    return estimate_structure(mono, sr, **kw)


__all__ = [
    "SectionSegment",
    "self_similarity",
    "foote_novelty",
    "pick_peaks",
    "estimate_structure",
    "estimate_structure_file",
]
