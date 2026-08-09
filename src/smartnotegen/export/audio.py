"""音频底层处理：soundfile/numpy 实现裁剪/循环、淡入淡出、重采样、位深转换、归一化。

约定：音频数组为 float32，取值 [-1, 1]；单声道 shape (n,)，立体声 shape (n, 2)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np
import soundfile as sf

from smartnotegen.exceptions import InputFileError

#: 位深 -> libsndfile subtype
_SUBTYPES = {8: "PCM_U8", 16: "PCM_16", 24: "PCM_24", 32: "PCM_32"}

#: -1 dBFS 峰值（Suno 合规：无爆音）
PEAK_DBFS = -1.0
PEAK_ABS = float(10 ** (PEAK_DBFS / 20.0))  # ≈ 0.891


def read_wav(path: str | Path) -> Tuple[np.ndarray, int]:
    """读取 WAV -> (float32 数组, 采样率)。"""
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise InputFileError(f"WAV 文件不存在: {p}", code=3)
    try:
        data, sr = sf.read(str(p), dtype="float32", always_2d=False)
    except Exception as exc:
        raise InputFileError(f"无法解析 WAV 文件: {p} ({exc})", code=3) from exc
    return data, int(sr)


def write_wav(
    path: str | Path,
    audio: np.ndarray,
    sample_rate: int,
    bit_depth: int = 16,
) -> str:
    """写 WAV（按位深选择 subtype）。"""
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    subtype = _SUBTYPES.get(bit_depth)
    if subtype is None:
        raise ValueError(f"不支持的位深: {bit_depth}")
    # 防止写入前爆音（防御性裁剪）
    audio = np.clip(audio, -1.0, 1.0)
    sf.write(str(p), audio.astype(np.float32), sample_rate, subtype=subtype)
    return str(p)


def trim_or_loop(audio: np.ndarray, sample_rate: int, target_seconds: float) -> np.ndarray:
    """裁剪至目标时长；输入不足时循环拼接补齐。"""
    target_n = int(round(target_seconds * sample_rate))
    n = len(audio)
    if n <= 0:
        raise ValueError("音频为空，无法导出")
    if n >= target_n:
        return audio[:target_n]
    # 循环补齐
    if audio.ndim == 2:
        repeats = (target_n + n - 1) // n
        tiled = np.tile(audio, (repeats, 1))
    else:
        repeats = (target_n + n - 1) // n
        tiled = np.tile(audio, repeats)
    return tiled[:target_n]


def fade(audio: np.ndarray, sample_rate: int, fade_ms: float) -> np.ndarray:
    """线性淡入淡出（首尾各 fade_ms 毫秒）。"""
    n_fade = int(round(sample_rate * fade_ms / 1000.0))
    if n_fade <= 1 or n_fade * 2 >= len(audio):
        return audio
    out = np.array(audio, dtype=np.float32, copy=True)
    fade_in = np.linspace(0.0, 1.0, n_fade, dtype=np.float32)
    fade_out = np.linspace(1.0, 0.0, n_fade, dtype=np.float32)
    if out.ndim == 2:
        out[:n_fade, :] *= fade_in[:, None]
        out[-n_fade:, :] *= fade_out[:, None]
    else:
        out[:n_fade] *= fade_in
        out[-n_fade:] *= fade_out
    return out


def fade_in_out(
    audio: np.ndarray,
    sample_rate: int,
    fade_in_ms: float,
    fade_out_ms: float,
) -> np.ndarray:
    """独立淡入/淡出毫秒数（P2-1 使用）；0ms 表示不淡变。"""
    out = np.array(audio, dtype=np.float32, copy=True)
    n_in = int(round(sample_rate * fade_in_ms / 1000.0))
    n_out = int(round(sample_rate * fade_out_ms / 1000.0))
    if 1 < n_in < len(out):
        ramp_in = np.linspace(0.0, 1.0, n_in, dtype=np.float32)
        if out.ndim == 2:
            out[:n_in, :] *= ramp_in[:, None]
        else:
            out[:n_in] *= ramp_in
    if 1 < n_out < len(out):
        ramp_out = np.linspace(1.0, 0.0, n_out, dtype=np.float32)
        if out.ndim == 2:
            out[-n_out:, :] *= ramp_out[:, None]
        else:
            out[-n_out:] *= ramp_out
    return out


def resample(audio: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    """线性插值重采样（numpy 实现，无 scipy 依赖）。"""
    if sr_from == sr_to:
        return np.array(audio, dtype=np.float32, copy=False)
    n_in = len(audio)
    n_out = max(1, int(round(n_in * sr_to / sr_from)))
    x_old = np.linspace(0.0, 1.0, n_in, endpoint=False)
    x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
    if audio.ndim == 2:
        cols = [
            np.interp(x_new, x_old, audio[:, c]).astype(np.float32)
            for c in range(audio.shape[1])
        ]
        return np.column_stack(cols)
    return np.interp(x_new, x_old, audio).astype(np.float32)


def normalize(audio: np.ndarray, peak_abs: float = PEAK_ABS) -> np.ndarray:
    """归一化到峰值 peak_abs（默认 -1 dBFS），保证无爆音。"""
    if audio.size == 0:
        return audio
    max_abs = float(np.max(np.abs(audio)))
    if max_abs <= 1e-9 or max_abs <= peak_abs:
        return np.array(audio, dtype=np.float32, copy=False)
    return (audio * (peak_abs / max_abs)).astype(np.float32)


def to_pcm16(audio: np.ndarray) -> np.ndarray:
    """float [-1,1] -> int16 PCM（用于 MP3 编码）。"""
    return (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
