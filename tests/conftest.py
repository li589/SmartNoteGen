"""pytest 共享 fixture：临时目录、最小 SoundFont stub、fluidsynth mock。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from smartnotegen.export import audio as audio_ops


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    """将 CWD 切到临时目录，避免读到项目根的 config/default.toml / smartnotegen.toml。"""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def fake_soundfont(tmp_path):
    """最小 SoundFont stub（仅用于路径存在性校验，不用于真实渲染）。"""
    p = tmp_path / "fake.sf2"
    p.write_bytes(b"RIFF\x00\x00\x00\x00fake-soundfont")
    return p


@pytest.fixture
def fake_midi(tmp_path):
    """最小合法 .mid（空曲目，pretty_midi 可解析）。"""
    import pretty_midi

    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    p = tmp_path / "input.mid"
    pm.write(str(p))
    return p


def make_sine_wav(path: Path, sample_rate: int = 44100, duration: float = 2.0,
                  freq: float = 440.0, amplitude: float = 0.5) -> Path:
    """合成正弦波 WAV（单声道），供导出测试使用。"""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    audio = (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    audio_ops.write_wav(path, audio, sample_rate, bit_depth=16)
    return path


@pytest.fixture
def sine_wav(tmp_path):
    """2 秒 440Hz 正弦波 WAV。"""
    return make_sine_wav(tmp_path / "sine.wav")


@pytest.fixture
def mock_fluidsynth(monkeypatch, tmp_path):
    """mock FluidSynthRenderer：_resolve_fluidsynth 返回假路径，subprocess.run 直接写 WAV。"""
    from smartnotegen.render import fluidsynth as fs_mod

    def fake_resolve(self):
        return "fluidsynth-mock"

    def fake_run(cmd, capture_output=True, text=True, timeout=300):
        # cmd 形如 [bin, '-ni', '-F', out, '-R', sr, '-O', 's16', '-g', g, sf, midi]
        out_idx = cmd.index("-F") + 1
        out_path = Path(cmd[out_idx])
        sr_idx = cmd.index("-R") + 1
        sample_rate = int(cmd[sr_idx])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        t = np.linspace(0, 1.0, sample_rate, endpoint=False)
        audio = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        audio_ops.write_wav(out_path, audio, sample_rate, bit_depth=16)
        return _Result(0, "", "")

    class _Result:
        def __init__(self, returncode, stdout, stderr):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    monkeypatch.setattr(fs_mod.FluidSynthRenderer, "_resolve_fluidsynth", fake_resolve)
    monkeypatch.setattr(fs_mod.subprocess, "run", fake_run)
    return monkeypatch


@pytest.fixture
def mock_path_resolver(monkeypatch, tmp_path):
    """mock PathResolver：ensure_ready 不抛错，resolve_* 返回注入路径（M-1 探测分支测试）。"""
    from smartnotegen import env as env_mod

    fs_bin = tmp_path / "fluidsynth-mock.exe"
    fs_bin.write_bytes(b"mock")
    sf = tmp_path / "mock.sf2"
    sf.write_bytes(b"RIFF\x00\x00\x00\x00mock-soundfont")

    monkeypatch.setattr(env_mod.PathResolver, "ensure_ready", lambda self: None)
    monkeypatch.setattr(env_mod.PathResolver, "resolve_fluidsynth", lambda self: fs_bin)
    monkeypatch.setattr(env_mod.PathResolver, "resolve_soundfont", lambda self: sf)
    return tmp_path


@pytest.fixture
def mock_dsp(monkeypatch):
    """mock DspProcessor.process：直接将输入复制为输出（跳过真实 DSP 处理）。"""
    from smartnotegen.dsp import processor as dsp_mod

    def fake_process(self, wav_path, opts, out_path):
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(Path(wav_path).read_bytes())
        return str(out.resolve())

    monkeypatch.setattr(dsp_mod.DspProcessor, "process", fake_process)
    return monkeypatch
