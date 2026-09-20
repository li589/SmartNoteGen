"""音频分析：预计算一次，全帧共享（v0.2.0 W1）。

设计原则：
- analyze() 只调用一次，产出 AudioAnalysis（频谱矩阵 / RMS 包络 / 波形 / onset）
- 所有 Visualizer.render_frame() 只读 AudioAnalysis 查表，不做重计算
- 复用 smartnotegen.preview 的 compute_audio_features，保证与预览页口径一致

性能基准（10s 音频 @44.1kHz, 30fps）：
- STFT 全量 ≈ 50ms；RMS 包络 ≈ 10ms；总分析 < 100ms
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
import soundfile as sf

from smartnotegen.preview import AudioFeatures, compute_audio_features


@dataclass
class AudioAnalysis:
    """预计算的音频分析结果（只读，所有 Visualizer 共享）。"""

    duration_s: float = 0.0
    sample_rate: int = 44100
    fps: int = 30
    n_frames: int = 0                     # 视频总帧数

    # 全局特征（复用 SNG preview）
    features: Optional[AudioFeatures] = None

    # 预计算数组（按视频帧对齐）
    waveform: np.ndarray = field(default_factory=lambda: np.zeros(0))       # (n_wave_points,)
    spectrogram: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))  # (n_frames, n_bins)
    rms_envelope: np.ndarray = field(default_factory=lambda: np.zeros(0))   # (n_frames,) 归一化 0-1
    onsets: List[float] = field(default_factory=list)                        # onset 时间戳（秒）

    # 多轨（v0.3 W4）：分轨可视化用
    track_spectrograms: List[np.ndarray] = field(default_factory=list)      # 每轨 (n_frames, n_bins)
    track_rms: List[np.ndarray] = field(default_factory=list)               # 每轨 (n_frames,)
    track_labels: List[str] = field(default_factory=list)

    # SNG 元数据（如有）
    bpm: Optional[int] = None
    chords: str = ""


def analyze(
    audio_path: str | Path,
    *,
    fps: int = 30,
    n_bins: int = 64,
    n_wave_points: int = 2000,
    onset_threshold: float = 1.5,
) -> AudioAnalysis:
    """分析音频文件（预计算一次）。

    Args:
        audio_path: 音频文件路径（WAV/MP3，soundfile 支持的格式）。
        fps: 视频帧率（频谱矩阵与 RMS 包络按此对齐）。
        n_bins: 频谱频率 bin 数（下采样后的频段数）。
        n_wave_points: 波形降采样点数。
        onset_threshold: onset 检测灵敏度（能量跳变倍数）。

    Returns:
        AudioAnalysis 实例。

    Raises:
        AudioReadError: 文件不存在或无法解析。
    """
    from videomaker.exceptions import AudioReadError

    # v0.3：支持 AudioLoadResult 或路径（多格式：WAV/MP3/MIDI…）
    if hasattr(audio_path, "audio"):
        audio = audio_path.mono
        sr = int(audio_path.sample_rate)
        features = compute_audio_features_from_array(audio, sr)
        path = None
    else:
        path = Path(audio_path)
        if not path.exists():
            raise AudioReadError(str(path), "文件不存在")
        try:
            audio, sr = sf.read(str(path))
        except Exception as exc:
            raise AudioReadError(str(path), str(exc)) from exc
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        sr = int(sr)
        try:
            features = compute_audio_features(path)
        except Exception:
            features = AudioFeatures()

    duration_s = len(audio) / sr
    n_frames = max(1, int(duration_s * fps))

    # -- 1. 波形降采样（等距采样，保持包络） -------------------------------
    if len(audio) <= n_wave_points:
        waveform = audio.copy()
    else:
        indices = np.linspace(0, len(audio) - 1, n_wave_points, dtype=int)
        waveform = audio[indices]

    # -- 2. STFT 频谱矩阵（一次计算 → 按视频帧重采样） ----------------------
    spectrogram = _compute_spectrogram(audio, sr, n_bins, n_frames)

    # -- 3. RMS 包络（按视频帧对齐，归一化 0-1） ----------------------------
    rms_envelope = _compute_rms_envelope(audio, sr, n_frames)

    # -- 4. onset 检测（能量跳变） ------------------------------------------
    onsets = _detect_onsets(audio, sr, onset_threshold)

    return AudioAnalysis(
        duration_s=duration_s,
        sample_rate=sr,
        fps=fps,
        n_frames=n_frames,
        features=features,
        waveform=waveform,
        spectrogram=spectrogram,
        rms_envelope=rms_envelope,
        onsets=onsets,
    )


def analyze_multitrack(
    mix,
    *,
    fps: int = 30,
    n_bins: int = 64,
    n_wave_points: int = 2000,
    onset_threshold: float = 1.5,
) -> AudioAnalysis:
    """多轨分析（v0.3 W4）：混音主分析 + 逐轨频谱/RMS。

    Args:
        mix: MixResult（videomaker.mixer），含 mixed 立体声与 track_monos。
        fps: 视频帧率。
        n_bins: 频谱 bin 数。
        n_wave_points: 波形降采样点数。
        onset_threshold: onset 灵敏度。

    Returns:
        AudioAnalysis（主轨 = 混音；track_* 字段填充逐轨数据）。
    """
    audio = mix.mono if hasattr(mix, "mono") else mix.mixed.mean(axis=1)
    sr = mix.sample_rate
    duration_s = len(audio) / sr
    n_frames = max(1, int(duration_s * fps))

    if len(audio) <= n_wave_points:
        waveform = audio.copy()
    else:
        indices = np.linspace(0, len(audio) - 1, n_wave_points, dtype=int)
        waveform = audio[indices]

    spectrogram = _compute_spectrogram(audio, sr, n_bins, n_frames)
    rms_envelope = _compute_rms_envelope(audio, sr, n_frames)
    onsets = _detect_onsets(audio, sr, onset_threshold)

    try:
        features = compute_audio_features_from_array(audio, sr)
    except Exception:
        features = AudioFeatures()

    # 逐轨（独立归一化，保证每轨视觉可辨）
    track_specs: List[np.ndarray] = []
    track_rms: List[np.ndarray] = []
    for mono in mix.track_monos:
        spec = _compute_spectrogram(mono, sr, n_bins, n_frames)
        vmax = float(spec.max())
        if vmax > 1e-10:
            spec = spec / vmax
        track_specs.append(spec)
        rms = _compute_rms_envelope(mono, sr, n_frames)
        track_rms.append(rms)

    return AudioAnalysis(
        duration_s=duration_s,
        sample_rate=sr,
        fps=fps,
        n_frames=n_frames,
        features=features,
        waveform=waveform,
        spectrogram=spectrogram,
        rms_envelope=rms_envelope,
        onsets=onsets,
        track_spectrograms=track_specs,
        track_rms=track_rms,
        track_labels=list(mix.track_labels),
    )


def compute_audio_features_from_array(audio: np.ndarray, sr: int) -> AudioFeatures:
    """从内存数组计算 AudioFeatures（避免临时落盘）。

    与 smartnotegen.preview.compute_audio_features 同口径。
    """
    import math as _math

    f = AudioFeatures()
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    f.peak_db = round(20 * _math.log10(peak + 1e-10), 1)
    rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
    f.rms_db = round(20 * _math.log10(rms + 1e-10), 1)

    n_fft = min(2048, len(audio))
    if len(audio) > n_fft and n_fft > 0:
        hop = n_fft // 4
        freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
        n_frames_i = (len(audio) - n_fft) // hop + 1
        centroid_sum = 0.0
        energy_sum = 0.0
        low_e = mid_e = high_e = 0.0
        for i in range(0, n_frames_i * hop, hop):
            frame = audio[i:i + n_fft]
            if len(frame) < n_fft:
                frame = np.pad(frame, (0, n_fft - len(frame)))
            spectrum = np.abs(np.fft.rfft(np.hanning(n_fft) * frame)) ** 2
            total = float(np.sum(spectrum))
            if total > 0:
                centroid_sum += float(np.sum(freqs * spectrum)) / total
                energy_sum += 1.0
                low_e += float(np.sum(spectrum[freqs <= 250]))
                mid_e += float(np.sum(spectrum[(freqs > 250) & (freqs <= 4000)]))
                high_e += float(np.sum(spectrum[freqs > 4000]))
        if energy_sum > 0:
            f.spectral_centroid = round(centroid_sum / energy_sum, 1)
        tot = low_e + mid_e + high_e
        if tot > 0:
            f.band_energy = {
                "low": round(low_e / tot, 2),
                "mid": round(mid_e / tot, 2),
                "high": round(high_e / tot, 2),
            }
    return f


# ---------------------------------------------------------------------------
# 内部计算函数
# ---------------------------------------------------------------------------

def _compute_spectrogram(
    audio: np.ndarray,
    sr: int,
    n_bins: int,
    n_frames: int,
    n_fft: int = 2048,
) -> np.ndarray:
    """一次 STFT → (n_frames, n_bins) 频谱矩阵（归一化 0-1）。

    对数频率轴下采样到 n_bins（保留低频细节，音乐可视化常用）。
    """
    if len(audio) < n_fft:
        return np.zeros((n_frames, n_bins))

    hop = n_fft // 4
    window = np.hanning(n_fft)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    n_spec_bins = len(freqs)

    # 全量 STFT
    n_stft_frames = (len(audio) - n_fft) // hop + 1
    spectra = np.zeros((n_stft_frames, n_spec_bins))
    for i in range(n_stft_frames):
        seg = audio[i * hop:i * hop + n_fft] * window
        spectra[i] = np.abs(np.fft.rfft(seg))

    # 对数频率轴下采样到 n_bins
    bin_edges = np.logspace(0, math.log10(n_spec_bins), n_bins + 1)
    bin_edges = np.clip(bin_edges.astype(int), 0, n_spec_bins)
    down = np.zeros((n_stft_frames, n_bins))
    for b in range(n_bins):
        lo, hi = bin_edges[b], bin_edges[b + 1]
        if hi > lo:
            down[:, b] = spectra[:, lo:hi].max(axis=1)

    # 时间轴重采样到视频帧数
    if n_stft_frames == 1:
        frame_spec = np.tile(down, (n_frames, 1))
    else:
        x_old = np.linspace(0, 1, n_stft_frames)
        x_new = np.linspace(0, 1, n_frames)
        frame_spec = np.zeros((n_frames, n_bins))
        for b in range(n_bins):
            frame_spec[:, b] = np.interp(x_new, x_old, down[:, b])

    # 归一化 0-1
    vmax = float(frame_spec.max())
    if vmax > 1e-10:
        frame_spec = frame_spec / vmax

    return frame_spec


def _compute_rms_envelope(audio: np.ndarray, sr: int, n_frames: int) -> np.ndarray:
    """按视频帧计算 RMS 包络（归一化 0-1）。"""
    envelope = np.zeros(n_frames)
    for i in range(n_frames):
        start = int(i * sr / n_frames * (len(audio) / sr) / 1.0)
        start = int(i * len(audio) / n_frames)
        end = int((i + 1) * len(audio) / n_frames)
        seg = audio[start:end]
        if len(seg) > 0:
            envelope[i] = float(np.sqrt(np.mean(seg ** 2)))

    emax = float(envelope.max())
    if emax > 1e-10:
        envelope = envelope / emax
    return envelope


def _detect_onsets(
    audio: np.ndarray,
    sr: int,
    threshold: float,
    frame_ms: int = 50,
) -> List[float]:
    """简单 onset 检测：短帧能量跳变（> threshold 倍视为 onset）。"""
    frame_len = int(sr * frame_ms / 1000)
    if frame_len <= 0 or len(audio) < frame_len * 2:
        return []

    onsets: List[float] = []
    prev_energy = 0.0
    for i in range(0, len(audio) - frame_len + 1, frame_len):
        seg = audio[i:i + frame_len]
        energy = float(np.sum(seg ** 2))
        if prev_energy > 0 and energy > prev_energy * threshold:
            onsets.append(i / sr)
        prev_energy = energy
    return onsets
