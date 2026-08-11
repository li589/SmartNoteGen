"""预览页生成器测试（P3-A1）+ 音频特征测试（P3-A3）。"""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from smartnotegen.preview import PreviewGenerator, compute_audio_features


# ---------------------------------------------------------------------------
# 音频特征（P3-A3）
# ---------------------------------------------------------------------------

def _write_sine_wav(tmp_path, freq=440.0, duration=1.0, sr=44100):
    """生成正弦波 WAV，返回路径。"""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    audio = 0.5 * np.sin(2 * np.pi * freq * t)
    path = tmp_path / "sine.wav"
    sf.write(str(path), audio, sr)
    return path


def test_compute_audio_features_peak_rms(tmp_path):
    """0.5 振幅正弦波：peak ≈ -6dBFS，rms 合理。"""
    wav = _write_sine_wav(tmp_path)
    feats = compute_audio_features(wav)
    # 0.5 振幅 → 峰值 -6.02 dBFS
    assert feats.peak_db == pytest.approx(-6.0, abs=0.5)
    # RMS 应低于峰值
    assert feats.rms_db < feats.peak_db
    # 频谱中心应接近 440Hz（正弦波单一频率）
    assert feats.spectral_centroid == pytest.approx(440.0, abs=100.0)


def test_compute_audio_features_band_energy(tmp_path):
    """频谱能量分布：低频应占主导（440Hz < 250Hz? 不，440 > 250 属中频）。"""
    wav = _write_sine_wav(tmp_path, freq=440.0)
    feats = compute_audio_features(wav)
    total = sum(feats.band_energy.values())
    assert total == pytest.approx(1.0, abs=0.01)
    # 440Hz 在 250-4000Hz 之间 → 中频占比最高
    assert feats.band_energy["mid"] > feats.band_energy["low"]
    assert feats.band_energy["mid"] > feats.band_energy["high"]


def test_compute_audio_features_stereo(tmp_path):
    """立体声 WAV 应正确混为单声道。"""
    t = np.linspace(0, 1, 44100, endpoint=False)
    audio = np.stack([0.5 * np.sin(2 * np.pi * 440 * t),
                      0.5 * np.sin(2 * np.pi * 440 * t)], axis=1)
    path = tmp_path / "stereo.wav"
    sf.write(str(path), audio, 44100)
    feats = compute_audio_features(path)
    assert feats.peak_db == pytest.approx(-6.0, abs=0.5)


# ---------------------------------------------------------------------------
# 预览页生成（P3-A1）
# ---------------------------------------------------------------------------

def test_generate_for_creates_html(tmp_path):
    """generate_for 产出 preview.html 且含 base64 音频。"""
    wav = _write_sine_wav(tmp_path)
    gen = PreviewGenerator()
    out = tmp_path / "out"
    html_path = gen.generate_for(
        wav,
        {"时长": "1.0s", "风格": "pop"},
        out,
        label="test.wav",
    )
    assert html_path.endswith("preview.html")
    html = open(html_path, encoding="utf-8").read()
    # 含音频 base64
    assert "data:audio/wav;base64," in html
    # 含标签
    assert "test.wav" in html
    # 含元数据
    assert "pop" in html
    # 含波形数据
    assert "waveform" in html


def test_generate_for_waveform_points(tmp_path):
    """波形点数量受 max_waveform_points 限制。"""
    # 生成 10s 音频（远大于 2000 点）
    wav = _write_sine_wav(tmp_path, duration=10.0)
    gen = PreviewGenerator(max_waveform_points=2000)
    audio, _ = gen._load_audio(wav)
    waveform = gen._compute_waveform(audio)
    assert len(waveform) <= 2000


def test_generate_batch_lists_items(tmp_path):
    """批量预览页列出所有变体。"""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    wav1 = _write_sine_wav(tmp_path / "a", freq=440)
    wav2 = _write_sine_wav(tmp_path / "b", freq=880)
    gen = PreviewGenerator()

    items = []
    for i, wav in enumerate([wav1, wav2]):
        audio, sr = gen._load_audio(wav)
        items.append({
            "label": f"variant{i}.wav",
            "audio_base64": gen._audio_to_base64(wav),
            "waveform": gen._compute_waveform(audio),
            "spectrogram": gen._compute_spectrogram(audio, sr),
            "metadata": {"风格": "pop", "BPM": 120 + i},
            "features": {"rms_db": -10.0, "peak_db": -1.0,
                         "spectral_centroid": 440.0, "band_energy": {}},
        })

    out = tmp_path / "out"
    html_path = gen.generate_batch(items, out)
    html = open(html_path, encoding="utf-8").read()
    assert "variant0.wav" in html
    assert "variant1.wav" in html
    assert "2" in html  # 变体数量


def test_spectrogram_empty_for_short_audio(tmp_path):
    """过短音频频谱为空（不崩溃）。"""
    wav = _write_sine_wav(tmp_path, duration=0.005)  # < 512 samples
    gen = PreviewGenerator()
    audio, sr = gen._load_audio(wav)
    spec = gen._compute_spectrogram(audio, sr)
    assert spec == []