"""共享频谱底座：STFT 幅度谱 / onset 强度包络（numpy-only，零 librosa）。

两处消费者：
- ``tempo.py``：onset 包络的自相关 → BPM + 置信度 + 节拍相位
- ``transcribe.py``：幅度谱 → 逐帧音高 salience → 峰值跟踪

设计取舍（都验证过）：
- **帧长/跳长固定常量而非参数自由化**：`tempo` 用 (2048, 512)（时间分辨率优先），
  `transcribe` 用 (4096, 512)（低音区频率分辨率优先，10.8Hz ≈ C3 处 0.6 半音）。
- **onset 包络 = 对数谱差分的半波整流沿频率求和**（librosa 的经典做法的手写等价物）。
  对数压缩（log1p）是关键：直接用线性幅度时，强音的谱差分会淹没弱音的起音。
"""

from __future__ import annotations

import numpy as np

#: tempo 用的 STFT 参数（2048@44.1k ≈ 46ms 窗，512 ≈ 11.6ms 步长）
TEMPO_FRAME = 2048
TEMPO_HOP = 512

#: transcribe 用的 STFT 参数（2048@22.05k ≈ 93ms 窗，256 ≈ 11.6ms 步长）。
#: 窗长是**时间精度与频率精度的交换**：4096 时低音区更准，但音符边界会因
#: 「下一音提前漏进窗尾」系统性提前 ~80ms，1/16 量化必错位；2048 实测边界
#: 误差 ≈ 半个窗长，配合帧中心时间戳可落在 ±20ms 内。
TRANSCRIBE_FRAME = 2048
TRANSCRIBE_HOP = 256


def frame_view(x: np.ndarray, frame: int, hop: int) -> np.ndarray:
    """把一维信号切成 ``(n_frames, frame)`` 矩阵（不足一帧的尾部丢弃）。"""
    n_frames = 1 + (len(x) - frame) // hop if len(x) >= frame else 0
    if n_frames <= 0:
        return np.zeros((0, frame), dtype=x.dtype)
    idx = np.arange(frame)[None, :] + hop * np.arange(n_frames)[:, None]
    return x[idx]


def stft_magnitude(mono: np.ndarray, frame: int, hop: int) -> np.ndarray:
    """STFT 幅度谱，形状 ``(n_frames, frame//2 + 1)``（Hann 窗）。"""
    frames = frame_view(mono, frame, hop)
    if frames.shape[0] == 0:
        return np.zeros((0, frame // 2 + 1), dtype=np.float64)
    win = np.hanning(frame).astype(np.float64)
    return np.abs(np.fft.rfft(frames.astype(np.float64) * win, axis=1))


def onset_strength(mono: np.ndarray, frame: int = TEMPO_FRAME, hop: int = TEMPO_HOP) -> np.ndarray:
    """onset 强度包络（谱通量），长度与帧数对齐（首帧补 0）。

    每帧值 = 相邻帧对数谱差分的半波整流沿频率求和。静音段恒为 0。
    """
    spec = stft_magnitude(mono, frame, hop)
    if spec.shape[0] < 2:
        return np.zeros(spec.shape[0], dtype=np.float64)
    logspec = np.log1p(100.0 * spec)
    diff = np.diff(logspec, axis=0)
    flux = np.maximum(diff, 0.0).sum(axis=1)
    return np.concatenate(([0.0], flux))
