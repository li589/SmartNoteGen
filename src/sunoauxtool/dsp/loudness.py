"""EBU R128 简化版积分响度（ITU-R BS.1770 口径，R6）。

纯 numpy/scipy 实现（无 pyloudnorm 依赖）：
- K 加权 = stage1 高架滤波（+4dB，高频补偿）+ stage2 RLB 高通（38Hz）
  —— biquad 系数按 ITU 标准在 48kHz 给定，任意 sr 经 bilinear 公式缩放
  （与 pyloudnorm 的 ``ITU-R BS.1770`` 滤波器同口径）；
- 分块 400ms、步进 100ms（75% 重叠）；
- 门控：绝对门 -70 LUFS + 相对门（块均值 -10 LU）；
- 积分响度 LUFS = -0.691 + 10*log10(门控块能量和 / 块数)。
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

#: ITU-R BS.1770 stage1（高架 shelving）@48kHz 原始系数（b/a）
_STAGE1_48K = {
    "b": [1.53512485958697, -2.69169618940638, 1.19839281085285],
    "a": [1.0, -1.69065929318241, 0.73248077421585],
}
#: ITU-R BS.1770 stage2（RLB 高通）@48kHz 原始系数
_STAGE2_48K = {
    "b": [1.0, -2.0, 1.0],
    "a": [1.0, -1.99004745483398, 0.99007225036621],
}
#: 48kHz 双线性参考
_REF_SR = 48000.0


def _scale_stage(
    b: list[float], a: list[float], sr: float
) -> tuple[np.ndarray, np.ndarray]:
    """把 48kHz 基准的 biquad 系数缩放到任意采样率（pyloudnorm 同款公式）。

    原理：对 s 域零极点做带宽缩放（p = p * sr / 48000）后重做 bilinear，
    等价于对多项式根做幂次缩放。
    """
    sr_k = sr / _REF_SR
    b = np.asarray(b, dtype=np.float64)
    a = np.asarray(a, dtype=np.float64)
    b_scale = sr_k ** (len(b) - 1 - np.arange(len(b)))
    a_scale = sr_k ** (len(a) - 1 - np.arange(len(a)))
    return b * b_scale, a * a_scale


def k_weight(audio: np.ndarray, sr: int) -> np.ndarray:
    """K 加权滤波（单声道 (N,) 或多声道 (N, ch)）。"""
    b1, a1 = _scale_stage(_STAGE1_48K["b"], _STAGE1_48K["a"], sr)
    b2, a2 = _scale_stage(_STAGE2_48K["b"], _STAGE2_48K["a"], sr)
    x = np.atleast_2d(audio.T).T.astype(np.float64)  # (N,) -> (N, 1)
    x = lfilter(b1, a1, x, axis=0)
    x = lfilter(b2, a2, x, axis=0)
    return x


def integrated_lufs(audio: np.ndarray, sr: int) -> float:
    """门控积分响度（LUFS）。

    Raises:
        ValueError: 输入为数字静音（无能量块，无法定义响度）。
    """
    x = k_weight(audio, sr)
    if x.ndim == 1:
        x = x[:, np.newaxis]

    block = int(0.4 * sr)  # 400ms
    step = int(0.1 * sr)  # 100ms
    n_blocks = 1 + (x.shape[0] - block) // step if x.shape[0] >= block else 0
    if n_blocks <= 0:
        raise ValueError("音频短于单个 400ms 测量块")

    # 每块能量 = 各声道均方之和（ITU：z_j = Σ_channels mean-square）
    block_energy = np.empty(n_blocks, dtype=np.float64)
    for i in range(n_blocks):
        seg = x[i * step : i * step + block]
        block_energy[i] = float(np.sum(np.mean(seg**2, axis=0)))

    def _lufs(e: float) -> float:
        return -0.691 + 10.0 * np.log10(max(e, 1e-24))

    # 绝对门 -70 LUFS
    loud = np.array([_lufs(e) for e in block_energy])
    keep = loud > -70.0
    if not np.any(keep):
        raise ValueError("全静音输入（无块高于绝对门 -70 LUFS）")

    # 相对门：过绝对门块的响度均值 -10 LU
    gated_mean = float(np.mean(loud[keep]))
    keep &= loud > gated_mean - 10.0
    if not np.any(keep):
        raise ValueError("无块高于相对门")

    # ITU 公式：门控块能量的**均值**（不是求和！sum 会让结果随块数漂移）
    return float(_lufs(float(np.mean(block_energy[keep]))))


def gain_to_target_lufs(audio: np.ndarray, sr: int, target_lufs: float) -> np.ndarray:
    """返回把 audio 归一到 target_lufs 所需的增益系数（浮点倍数）。"""
    lufs = integrated_lufs(audio, sr)
    return float(10 ** ((target_lufs - lufs) / 20.0))
