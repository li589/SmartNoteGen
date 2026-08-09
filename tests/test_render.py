"""渲染单元测试：mock fluidsynth，不依赖真实 SoundFont/二进制。"""

from __future__ import annotations

import pytest

from smartnotegen.exceptions import ConfigError, InputFileError, RenderError
from smartnotegen.render.fluidsynth import FluidSynthRenderer


def test_render_creates_wav(mock_fluidsynth, fake_midi, fake_soundfont, tmp_path):
    """mock 渲染成功，输出 WAV 存在。"""
    renderer = FluidSynthRenderer()
    out = tmp_path / "out.wav"
    path = renderer.render(str(fake_midi), str(fake_soundfont), str(out))
    assert path == str(out.resolve())
    assert out.is_file()
    assert out.stat().st_size > 0


def test_render_missing_midi(mock_fluidsynth, fake_soundfont, tmp_path):
    """MIDI 不存在 -> InputFileError(3)。"""
    renderer = FluidSynthRenderer()
    with pytest.raises(InputFileError) as exc:
        renderer.render(str(tmp_path / "nope.mid"), str(fake_soundfont), str(tmp_path / "o.wav"))
    assert exc.value.code == 3


def test_render_missing_soundfont(mock_fluidsynth, fake_midi, tmp_path):
    """SoundFont 不存在 -> ConfigError(2)。"""
    renderer = FluidSynthRenderer()
    with pytest.raises(ConfigError) as exc:
        renderer.render(str(fake_midi), str(tmp_path / "nope.sf2"), str(tmp_path / "o.wav"))
    assert exc.value.code == 2


def test_render_fluidsynth_not_found(monkeypatch, fake_midi, fake_soundfont, tmp_path):
    """fluidsynth 未安装/找不到 -> RenderError(4)。"""
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _: None)
    renderer = FluidSynthRenderer(fluidsynth_path=None)
    with pytest.raises(RenderError) as exc:
        renderer.render(str(fake_midi), str(fake_soundfont), str(tmp_path / "o.wav"))
    assert exc.value.code == 4
    assert "fluidsynth" in str(exc.value)


def test_render_subprocess_failure(mock_fluidsynth, fake_midi, fake_soundfont, tmp_path, monkeypatch):
    """渲染进程非零退出 -> RenderError(4)。"""
    from smartnotegen.render import fluidsynth as fs_mod

    class _Fail:
        returncode = 1
        stdout = ""
        stderr = "audio driver error"

    monkeypatch.setattr(fs_mod.subprocess, "run", lambda *a, **k: _Fail())
    renderer = FluidSynthRenderer()
    with pytest.raises(RenderError) as exc:
        renderer.render(str(fake_midi), str(fake_soundfont), str(tmp_path / "o.wav"))
    assert exc.value.code == 4


def test_render_custom_fluidsynth_path(mock_fluidsynth, fake_midi, fake_soundfont, tmp_path, monkeypatch):
    """配置绝对路径的 fluidsynth 可被解析（文件存在）。"""
    from smartnotegen.render import fluidsynth as fs_mod

    binary = tmp_path / "fluidsynth-custom.exe"
    binary.write_bytes(b"mock")
    calls = {}

    def fake_resolve(self):
        return str(binary)

    monkeypatch.setattr(fs_mod.FluidSynthRenderer, "_resolve_fluidsynth", fake_resolve)
    renderer = FluidSynthRenderer(fluidsynth_path=str(binary))
    out = tmp_path / "custom.wav"
    path = renderer.render(str(fake_midi), str(fake_soundfont), str(out))
    assert out.is_file()
