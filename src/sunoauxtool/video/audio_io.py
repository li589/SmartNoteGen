"""多格式音频输入（v0.3 W2）：WAV / MP3 / MIDI 统一加载。

设计：
- WAV/MP3/FLAC/OGG：soundfile 直读（0.14 原生支持 MP3）
- MIDI：复用 SNG FluidSynthRenderer 渲染为 WAV（module 真实引擎），
  SoundFont/fluidsynth 路径默认取 module/ 布局，可显式覆盖
- 统一返回 AudioLoadResult（单声道分析用 + 原始声道数保留）
- 所有加载都会重采样/对齐由上层 mixer 处理，这里只负责"读出来"

路径解析顺序（fluidsynth/soundfont）：
    显式参数 > module/ 默认布局 > PATH
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from sunoauxtool.video.exceptions import AudioReadError


# module/ 默认布局（与 SNG M-1 一致）
DEFAULT_FLUIDSYNTH = "module/fluidsynth/bin/fluidsynth.exe"
DEFAULT_SOUNDFONT = "module/GeneralUser_GS/GeneralUser-GS/GeneralUser-GS.sf2"
SOUNDFONT_BACKUP = "module/GeneralUser_GS/ColomboGMGS2_SF2/ColomboGMGS2.sf2"

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".mid", ".midi"}


@dataclass
class AudioLoadResult:
    """单轨加载结果。"""

    audio: np.ndarray            # (n,) 单声道 或 (n, 2) 立体声
    sample_rate: int
    source_path: str
    source_format: str           # wav / mp3 / midi / ...
    rendered_wav: Optional[str] = None  # MIDI 渲染产生的临时 WAV 路径（供复用/清理）
    label: str = ""              # 显示名（默认文件名 stem）
    channels: int = 1

    @property
    def mono(self) -> np.ndarray:
        """单声道视图（立体声取均值）。"""
        if self.audio.ndim > 1:
            return self.audio.mean(axis=1)
        return self.audio

    @property
    def duration_s(self) -> float:
        return len(self.audio) / self.sample_rate


def detect_format(path: str | Path) -> str:
    """根据扩展名判断格式。"""
    ext = Path(path).suffix.lower()
    if ext in {".mid", ".midi"}:
        return "midi"
    return ext.lstrip(".")


def is_supported(path: str | Path) -> bool:
    """是否为支持的输入格式。"""
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def load_audio(
    path: str | Path,
    *,
    fluidsynth: Optional[str] = None,
    soundfont: Optional[str] = None,
    keep_rendered_wav: bool = False,
) -> AudioLoadResult:
    """加载单个音频文件（WAV/MP3/FLAC/OGG/MIDI）。

    Args:
        path: 输入文件路径。
        fluidsynth: fluidsynth 可执行路径（MIDI 用；默认 module 布局）。
        soundfont: SoundFont 路径（MIDI 用；默认 module 布局）。
        keep_rendered_wav: True 时保留 MIDI 渲染的临时 WAV（复用/调试）。

    Returns:
        AudioLoadResult。

    Raises:
        AudioReadError: 文件不存在 / 格式不支持 / 读取或渲染失败。
    """
    p = Path(path).expanduser()
    if not p.is_file():
        raise AudioReadError(str(p), "文件不存在")

    fmt = detect_format(p)
    if fmt not in {wav_mp3 for wav_mp3 in ("wav", "mp3", "flac", "ogg")} and fmt != "midi":
        raise AudioReadError(str(p), f"不支持的格式 .{p.suffix}（支持: {sorted(SUPPORTED_EXTENSIONS)}）")

    if fmt == "midi":
        return _load_midi(p, fluidsynth, soundfont, keep_rendered_wav)

    try:
        audio, sr = sf.read(str(p), always_2d=False)
    except Exception as exc:
        raise AudioReadError(str(p), f"读取失败: {exc}") from exc

    channels = 1 if audio.ndim == 1 else audio.shape[1]
    return AudioLoadResult(
        audio=audio,
        sample_rate=int(sr),
        source_path=str(p.resolve()),
        source_format=fmt,
        label=p.stem,
        channels=channels,
    )


def _load_midi(
    midi_path: Path,
    fluidsynth: Optional[str],
    soundfont: Optional[str],
    keep_rendered_wav: bool,
) -> AudioLoadResult:
    """MIDI → WAV（SNG FluidSynthRenderer）→ AudioLoadResult。"""
    try:
        from sunoauxtool.render.fluidsynth import FluidSynthRenderer
    except ImportError as exc:
        raise AudioReadError(str(midi_path), "MIDI 支持需要 sunoauxtool（未安装）") from exc

    fs_path = fluidsynth or _resolve_default(DEFAULT_FLUIDSYNTH)
    sf_path = soundfont or _resolve_default(DEFAULT_SOUNDFONT)
    backup = _resolve_default(SOUNDFONT_BACKUP, required=False)

    renderer = FluidSynthRenderer(
        fluidsynth_path=fs_path,
        soundfont_backup=backup,
    )

    # 渲染到临时位置（与源文件同目录，便于清理）
    out_wav = midi_path.parent / f".{midi_path.stem}_rendered.wav"
    try:
        renderer.render(str(midi_path), sf_path, str(out_wav))
    except Exception as exc:
        raise AudioReadError(str(midi_path), f"MIDI 渲染失败: {exc}") from exc

    try:
        audio, sr = sf.read(str(out_wav), always_2d=False)
    except Exception as exc:
        raise AudioReadError(str(midi_path), f"渲染产物读取失败: {exc}") from exc

    channels = 1 if audio.ndim == 1 else audio.shape[1]
    return AudioLoadResult(
        audio=audio,
        sample_rate=int(sr),
        source_path=str(midi_path.resolve()),
        source_format="midi",
        rendered_wav=str(out_wav) if keep_rendered_wav else None,
        label=midi_path.stem,
        channels=channels,
    )


def _resolve_default(rel_path: str, required: bool = True) -> Optional[str]:
    """解析 module 相对路径（按 CWD）；不存在且 required 时返回原值（让渲染器报详细错误）。"""
    p = Path(rel_path)
    if p.exists():
        return rel_path
    if not required:
        return None
    return rel_path


def cleanup_rendered(result: AudioLoadResult) -> None:
    """清理 MIDI 渲染的临时 WAV（keep_rendered_wav=False 时由调用方调用）。"""
    if result.rendered_wav is None:
        wav = Path(result.source_path).parent / f".{Path(result.source_path).stem}_rendered.wav"
        if wav.exists():
            try:
                wav.unlink()
            except OSError:
                pass
