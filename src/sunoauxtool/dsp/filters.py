"""DSP 滤波器实现（P2-1）：EQ 高通 + 压缩器（纯 numpy，无 scipy 依赖）。"""

from __future__ import annotations

import numpy as np


def highpass(
    audio: np.ndarray,
    sample_rate: int,
    cutoff_hz: float,
) -> np.ndarray:
    """一阶高通滤波器（单极点 IIR），用于低频切。

    传递函数：y[n] = alpha * (y[n-1] + x[n] - x[n-1])，alpha = 1 / (1 + 2πfc/fs)。
    对直流分量有完全抑制效果。
    """
    alpha = 1.0 / (1.0 + 2.0 * np.pi * float(cutoff_hz) / float(sample_rate))
    out = np.zeros_like(audio, dtype=np.float32)

    def _apply_one(x: np.ndarray, o: np.ndarray) -> None:
        prev_y = 0.0
        prev_x = 0.0
        for i in range(len(x)):
            xi = float(x[i])
            yi = alpha * (prev_y + xi - prev_x)
            prev_y = yi
            prev_x = xi
            o[i] = yi

    if audio.ndim == 2:
        for c in range(audio.shape[1]):
            _apply_one(audio[:, c], out[:, c])
    else:
        _apply_one(audio, out)
    return out


def compressor(
    audio: np.ndarray,
    ratio: float,
    threshold_db: float,
) -> np.ndarray:
    """软拐点压缩器：超过阈值的部分按 ratio 压缩。

    超过阈值部分：output_level = threshold + (level - threshold) / ratio。
    ratio 必须 >= 1（由 DspProcessor.validate 保证）。
    """
    threshold_lin = float(10 ** (float(threshold_db) / 20.0))
    level = np.abs(audio)
    over = level > threshold_lin
    gain = np.ones_like(level, dtype=np.float32)
    if np.any(over):
        gain[over] = (
            (threshold_lin + (level[over] - threshold_lin) / float(ratio)) / level[over]
        ).astype(np.float32)
    return (audio * gain).astype(np.float32)
