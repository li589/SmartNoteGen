"""混响（R14）：合成 IR + FFT 卷积 + wet/dry 混合。

设计取舍
--------
- **IR 不入库**：真实脉冲响应（教堂/大厅）体积大且涉版权，故默认用
  **确定性合成**的指数衰减噪声 IR（同 seed 同结果，便于单测复现）。
- **L1 归一化 IR**：``sum|ir| = 1`` 使卷积成为收缩映射
  （输出峰值 ≤ 输入峰值），从数学上排除爆音——不需要事后 limiter。
- **numpy-only**：自己写 FFT 卷积，不引 scipy（与 ``filters.py`` 同风格）。
- 输出**截断到输入长度**（混响作为 insert 效果，不改变时长），
  便于在算子链中与其它算子串联。

合规边界
--------
本模块只被 **standalone 后处理**（``sunoaux post dsp --ops "reverb ..."``）使用。
``export suno`` 链与 ``pipeline``（经 ``DspProcessor``）**恒不带混响**——
Suno 合规要求无混响，见 ``dsp/processor.py`` 与 ``docs/dsp.md``。
"""

from __future__ import annotations

import numpy as np

#: 默认 IR 时长（秒）
DEFAULT_SECONDS = 1.2
#: 默认 wet 混合比
DEFAULT_WET = 0.3
#: IR 末端衰减到 e^-DECAY_RATIO（越大衰减越快）
DECAY_RATIO = 6.0


def synthesize_ir(
    sr: int,
    seconds: float = DEFAULT_SECONDS,
    decay_ratio: float = DECAY_RATIO,
    seed: int = 42,
) -> np.ndarray:
    """合成指数衰减噪声 IR（确定性）。

    Args:
        sr: 采样率。
        seconds: IR 时长（秒）。
        decay_ratio: 末端衰减到 ``exp(-decay_ratio)``。
        seed: 随机种子（固定 → 结果可复现）。

    Returns:
        一维 float64 IR，满足 ``sum(|ir|) == 1``。
    """
    n = max(1, int(round(sr * seconds)))
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(n)
    t = np.arange(n, dtype=np.float64) / float(sr)
    env = np.exp(-t * float(decay_ratio) / float(seconds))
    ir = noise * env
    l1 = float(np.abs(ir).sum())
    if l1 > 0:
        ir = ir / l1
    return ir.astype(np.float64)


def fft_convolve(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    """FFT 卷积（numpy 实现），返回长度 = ``len(x)``（尾部截断）。"""
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return np.zeros(0, dtype=np.float64)
    n_full = x.shape[0] + h.shape[0] - 1
    nfft = 1 << int(n_full - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(h, nfft), nfft)
    return y[: x.shape[0]]


def apply_reverb(
    audio: np.ndarray,
    sr: int,
    wet: float = DEFAULT_WET,
    seconds: float = DEFAULT_SECONDS,
    seed: int = 42,
) -> np.ndarray:
    """对音频加混响（wet/dry 混合），返回 float32。

    Args:
        audio: ``(n,)`` 单声道或 ``(n, ch)`` 多声道。
        sr: 采样率。
        wet: 湿声比例 ∈ [0, 1]；0 = 干声直通，1 = 纯湿声。
        seconds: IR 时长（秒）。
        seed: IR 合成种子。
    """
    dry = np.asarray(audio, dtype=np.float64)
    if dry.size == 0:
        return np.asarray(audio, dtype=np.float32)

    ir = synthesize_ir(sr, seconds=seconds, seed=seed)

    if dry.ndim == 1:
        out = (1.0 - wet) * dry + wet * fft_convolve(dry, ir)
    else:
        # 逐声道处理：IR 是单声道，不能整块广播
        out = np.empty_like(dry)
        for ch in range(dry.shape[1]):
            out[:, ch] = (1.0 - wet) * dry[:, ch] + wet * fft_convolve(dry[:, ch], ir)
    return out.astype(np.float32)


__all__ = [
    "DEFAULT_SECONDS",
    "DEFAULT_WET",
    "DECAY_RATIO",
    "synthesize_ir",
    "fft_convolve",
    "apply_reverb",
]
