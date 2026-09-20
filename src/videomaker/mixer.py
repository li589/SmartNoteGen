"""多轨混音（v0.3 W3）：多输入对齐 + 增益/声像 + 防削波归一化。

输入形态（mix_tracks / parse_track_spec）：
    单个文件路径            → 单轨
    "file.wav:gain=0.8:pan=-0.3"  → 带参数轨道（冒号分段）
    TrackSpec 列表          → 程序化构造

混音流程：
    1. load_audio 逐轨加载（WAV/MP3/MIDI 混用）
    2. 重采样对齐到目标采样率（线性插值，numpy）
    3. 长度对齐：以最长轨为准，短轨补零（可选 trim_to_shortest）
    4. 逐轨 gain × pan（等功率声像定律）→ 立体声
    5. 求和 → 峰值归一化到 ceiling（防削波，默认 -1 dBFS）
    6. 输出 MixResult（混音立体声 + 逐轨单声道，供分轨可视化）
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
import soundfile as sf

from videomaker.audio_io import AudioLoadResult, load_audio


@dataclass
class TrackSpec:
    """单轨规格。"""
    path: str
    gain: float = 1.0        # 线性增益
    pan: float = 0.0          # -1(左) ~ +1(右)，0 居中
    label: str = ""           # 显示名

    @classmethod
    def parse(cls, spec: str) -> "TrackSpec":
        """解析 "file.wav:gain=0.8:pan=-0.3" 形态。

        Windows 路径含盘符冒号：仅当段中含 '=' 时视为参数段，
        否则视为路径的一部分（首段恒为路径）。
        """
        parts = spec.split(":")
        path = parts[0]
        kwargs = {}
        for seg in parts[1:]:
            if "=" in seg:
                k, _, v = seg.partition("=")
                k = k.strip().lower()
                if k in ("gain", "pan"):
                    try:
                        kwargs[k] = float(v)
                    except ValueError:
                        continue
        return cls(path=path, **kwargs)


def parse_track_specs(items: List[str]) -> List[TrackSpec]:
    """把 CLI 输入列表解析为 TrackSpec（纯路径原样过）。"""
    return [TrackSpec.parse(item) if ":" in item and "=" in item else TrackSpec(path=item)
            for item in items]


@dataclass
class MixResult:
    """混音结果。"""
    mixed: np.ndarray                 # (n, 2) 立体声混音
    sample_rate: int
    track_monos: List[np.ndarray] = field(default_factory=list)  # 逐轨单声道（增益后）
    track_labels: List[str] = field(default_factory=list)
    normalize_gain: float = 1.0       # 归一化应用的增益（诊断用）
    sources: List[str] = field(default_factory=list)

    @property
    def mono(self) -> np.ndarray:
        return self.mixed.mean(axis=1)

    @property
    def duration_s(self) -> float:
        return len(self.mixed) / self.sample_rate


def mix_tracks(
    specs: List[TrackSpec],
    *,
    target_sr: int = 44100,
    normalize_ceiling: float = 0.891,  # -1 dBFS
    trim_to_shortest: bool = False,
    fluidsynth: Optional[str] = None,
    soundfont: Optional[str] = None,
    save_wav: Optional[str] = None,
) -> MixResult:
    """多轨混音。

    Args:
        specs: 轨道规格列表。
        target_sr: 目标采样率。
        normalize_ceiling: 归一化峰值上限（线性幅度；默认 -1 dBFS）。
        trim_to_shortest: True 裁到最短轨；False 补零到最长轨。
        fluidsynth/soundfont: MIDI 渲染资源路径。
        save_wav: 保存混音 WAV 的路径（可选）。

    Returns:
        MixResult。

    Raises:
        AudioReadError: 任一轨道加载失败。
        ValueError: specs 为空。
    """

    if not specs:
        raise ValueError("mix_tracks 需要至少一条轨道")

    # 1. 逐轨加载
    loaded: List[AudioLoadResult] = []
    for spec in specs:
        result = load_audio(
            spec.path,
            fluidsynth=fluidsynth,
            soundfont=soundfont,
        )
        loaded.append(result)

    # 2. 重采样对齐 + 长度对齐
    monos: List[np.ndarray] = []
    labels: List[str] = []
    for spec, result in zip(specs, loaded):
        mono = _to_mono(result.audio)
        mono = _resample(mono, result.sample_rate, target_sr)
        monos.append(mono)
        labels.append(spec.label or result.label or Path(spec.path).stem)

    target_len = min(len(m) for m in monos) if trim_to_shortest else max(len(m) for m in monos)
    monos = [_fit_length(m, target_len) for m in monos]

    # 3. 逐轨增益 + 声像（等功率定律）
    lefts: List[np.ndarray] = []
    rights: List[np.ndarray] = []
    post_gain_monos: List[np.ndarray] = []
    for spec, mono in zip(specs, monos):
        pan = max(-1.0, min(1.0, spec.pan))
        # 等功率声像：pan=-1 → L=1,R=0；pan=0 → L=R=1/√2；pan=+1 → L=0,R=1
        angle = (pan + 1.0) * (math.pi / 4.0)  # 0 ~ π/2
        l_gain = math.cos(angle)
        r_gain = math.sin(angle)
        g = max(0.0, spec.gain)
        lefts.append(mono * (g * l_gain))
        rights.append(mono * (g * r_gain))
        post_gain_monos.append(mono * g)

    left = np.sum(lefts, axis=0) if lefts else np.zeros(target_len)
    right = np.sum(rights, axis=0) if rights else np.zeros(target_len)

    # 4. 防削波归一化（峰值 → ceiling）
    peak = float(max(np.abs(left).max(), np.abs(right).max())) if target_len else 0.0
    norm_gain = 1.0
    if peak > normalize_ceiling and peak > 0:
        norm_gain = normalize_ceiling / peak
        left = left * norm_gain
        right = right * norm_gain
        post_gain_monos = [m * norm_gain for m in post_gain_monos]

    mixed = np.stack([left, right], axis=1).astype(np.float32)

    # 5. 可选保存
    if save_wav:
        out = Path(save_wav)
        out.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out), mixed, target_sr, subtype="PCM_16")

    # 6. 清理 MIDI 临时文件
    from videomaker.audio_io import cleanup_rendered
    for result in loaded:
        cleanup_rendered(result)

    return MixResult(
        mixed=mixed,
        sample_rate=target_sr,
        track_monos=post_gain_monos,
        track_labels=labels,
        normalize_gain=norm_gain,
        sources=[r.source_path for r in loaded],
    )


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _to_mono(audio: np.ndarray) -> np.ndarray:
    if audio.ndim > 1:
        return audio.mean(axis=1)
    return audio


def _resample(mono: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    """线性插值重采样（质量足够用于可视化与预听混音）。"""
    if sr_from == sr_to or len(mono) == 0:
        return mono
    n_out = int(len(mono) * sr_to / sr_from)
    if n_out == 0:
        return np.zeros(0, dtype=mono.dtype)
    x_old = np.linspace(0.0, 1.0, len(mono), endpoint=False)
    x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
    return np.interp(x_new, x_old, mono).astype(np.float32)


def _fit_length(mono: np.ndarray, target: int) -> np.ndarray:
    """补零或裁剪到目标长度。"""
    if len(mono) == target:
        return mono
    if len(mono) > target:
        return mono[:target]
    out = np.zeros(target, dtype=np.float32)
    out[: len(mono)] = mono
    return out
