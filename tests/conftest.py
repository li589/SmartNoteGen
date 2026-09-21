"""pytest 共享 fixture：临时目录、最小 SoundFont stub、fluidsynth mock。"""

from __future__ import annotations

import random as _random
import struct as _struct
from pathlib import Path

import numpy as np
import pytest

from sunoauxtool.export import audio as audio_ops


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    """将 CWD 切到临时目录，避免读到项目根的 config/default.toml / sunoauxtool.toml。"""
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
    from sunoauxtool.render import fluidsynth as fs_mod

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
    from sunoauxtool import env as env_mod

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
    from sunoauxtool.dsp import processor as dsp_mod

    def fake_process(self, wav_path, opts, out_path):
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(Path(wav_path).read_bytes())
        return str(out.resolve())

    monkeypatch.setattr(dsp_mod.DspProcessor, "process", fake_process)
    return monkeypatch


# ---------------------------------------------------------------------------
# DownloadHelper（原 Suno-Cat-Catch-Resolve）测试支撑
# ---------------------------------------------------------------------------





@pytest.fixture(autouse=True)
def _isolate_ffmpeg_env(monkeypatch):
    """清空 ffmpeg 定位相关环境变量，保证 find_ffmpeg 的用例结果只由用例自己决定。

    若开发机真的设了 SUNO_FFMPEG / SMARTNOTEGEN_FFMPEG / SUNO_FFMPEG_DIRS，
    「应当回落到 PATH / 已知目录 / 抛错」的用例会静默变成假绿或假红。
    环境相关的测试不该被运行者机器的环境左右。
    """
    from sunoauxtool.download import transcoder

    for var in (*transcoder.FFMPEG_ENV_VARS, transcoder.FFMPEG_DIRS_ENV_VAR):
        monkeypatch.delenv(var, raising=False)


def box(atom_type: bytes, payload: bytes) -> bytes:
    """构造一个 32 位长度的 ISO BMFF 原子：4 字节长度 + 4 字节类型 + 载荷。"""
    return _struct.pack(">I", len(payload) + 8) + atom_type + payload


@pytest.fixture
def make_fmp4():
    """返回构造 fragmented MP4 字节串的工厂。"""

    def _make(mdat_payloads=(b"\x11" * 64,), ftyp: bytes = b"isom\x00\x00\x02\x00isomiso2mp41"):
        data = box(b"ftyp", ftyp)
        data += box(b"moov", b"\x00" * 16)
        for payload in mdat_payloads:
            data += box(b"moof", b"\x01" * 12)
            data += box(b"mdat", payload)
        return data

    return _make


@pytest.fixture
def fmp4_bytes(make_fmp4):
    """一份最小的可解析 fMP4。"""
    return make_fmp4()


@pytest.fixture
def fmp4_file(tmp_path, make_fmp4):
    """落盘的 fMP4，故意命名为 .mp3（复刻 Suno 缓存捕获的误标场景）。"""
    p = tmp_path / "Suno _ AI Music.mp3"
    p.write_bytes(make_fmp4())
    return p


@pytest.fixture
def encrypted_bytes():
    """确定性的「密文」样本：均匀随机字节（χ²≈255）。

    用固定种子而非 os.urandom，保证 χ² 在跨平台/跨运行时稳定落在
    密文判据区间（≤360），不会偶发翻转测试结果。
    """
    return _random.Random(1234).randbytes(1_000_000)


@pytest.fixture
def encrypted_file(tmp_path, encrypted_bytes):
    """落盘的密文样本，UUID 命名（复刻猫抓直下的 *.m4a）。"""
    p = tmp_path / "a1b2c3d4-0000-1111-2222-333344445555.m4a"
    p.write_bytes(encrypted_bytes)
    return p
