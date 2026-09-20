"""ffmpeg 封装：fMP4 解码、Opus 重封装、MP3 转码、媒体探测。

注意（实测坑）：
    Opus 码流**不能**直接 `-c copy` 封装进 .m4a/MP4——ipod 封装器会报
    "Could not find tag for codec opus ... not currently supported in container"。
    正确做法：
        无损 → Ogg Opus (`.opus`)   : ffmpeg -i IN -c copy out.opus
        兼容 → MP3                  : ffmpeg -i IN -c:a libmp3lame -b:a 192k out.mp3
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Union

from suno_cat_catch_resolve.exceptions import (
    EncryptedBlobError,
    FFmpegNotFoundError,
    NotFragmentedMP4Error,
    OutputWriteError,
    TranscodeError,
)
from suno_cat_catch_resolve.forensics import classify
from suno_cat_catch_resolve.fmp4 import is_fragmented_mp4

PathLike = Union[str, Path]

# 本机已知安装位置（找不到时依次尝试）
KNOWN_FFMPEG_DIRS = [
    r"D:\myPrograms\FFmpge\ffmpeg-master-latest-win64-gpl\bin",
    r"C:\Program Files\ffmpeg\bin",
    r"C:\ffmpeg\bin",
]


def find_ffmpeg(path: Optional[PathLike] = None) -> Path:
    """定位 ffmpeg 可执行文件。

    顺序：显式参数 > PATH > 已知安装目录。
    """
    if path:
        candidate = Path(path)
        if candidate.is_file():
            return candidate
        raise FFmpegNotFoundError()

    which = shutil.which("ffmpeg")
    if which:
        return Path(which)

    for directory in KNOWN_FFMPEG_DIRS:
        for name in ("ffmpeg.exe", "ffmpeg"):
            candidate = Path(directory) / name
            if candidate.is_file():
                return candidate

    raise FFmpegNotFoundError()


def _find_ffprobe(ffmpeg: Path) -> Path:
    """由 ffmpeg 路径推导同目录的 ffprobe。"""
    sibling = ffmpeg.with_name("ffprobe.exe" if ffmpeg.name.endswith(".exe") else "ffprobe")
    if sibling.is_file():
        return sibling
    which = shutil.which("ffprobe")
    if which:
        return Path(which)
    raise FFmpegNotFoundError()


def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def probe(src: PathLike, ffmpeg: Optional[PathLike] = None) -> Dict[str, str]:
    """用 ffprobe 读取媒体信息，返回 key=value 字典。"""
    ff = find_ffmpeg(ffmpeg)
    fp = _find_ffprobe(ff)
    proc = _run(
        [
            str(fp),
            "-v", "error",
            "-show_entries",
            "format=format_name,duration,bit_rate:stream=codec_name,codec_type,sample_rate,channels",
            "-of", "default=noprint_wrappers=1",
            str(src),
        ]
    )
    if proc.returncode != 0:
        raise TranscodeError(f"ffprobe 失败: {proc.stderr.strip()}", proc.returncode)

    info: Dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            info.setdefault(key.strip(), value.strip())
    return info


def _sanitize(stem: str) -> str:
    """把 'Suno _ AI Music (1)' 规整为 'Suno_AI_Music_1'。"""
    cleaned = re.sub(r"[()\[\]{}]", "", stem)
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned or "track"


def _ensure_outdir(out_dir: PathLike) -> Path:
    out = Path(out_dir)
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputWriteError(str(out)) from exc
    return out


def remux_opus(
    src: PathLike,
    dst: PathLike,
    ffmpeg: Optional[PathLike] = None,
) -> Path:
    """无损重封装为 Ogg Opus（-c copy，不重编码）。"""
    ff = find_ffmpeg(ffmpeg)
    dst = Path(dst)
    _ensure_outdir(dst.parent)
    proc = _run([str(ff), "-y", "-i", str(src), "-c", "copy", str(dst)])
    if proc.returncode != 0:
        raise TranscodeError(f"Opus 重封装失败: {proc.stderr.strip()[-500:]}", proc.returncode)
    return dst


def to_mp3(
    src: PathLike,
    dst: PathLike,
    bitrate: str = "192k",
    ffmpeg: Optional[PathLike] = None,
) -> Path:
    """转码为 MP3（libmp3lame），最大兼容性。"""
    ff = find_ffmpeg(ffmpeg)
    dst = Path(dst)
    _ensure_outdir(dst.parent)
    proc = _run(
        [str(ff), "-y", "-i", str(src), "-c:a", "libmp3lame", "-b:a", bitrate, str(dst)]
    )
    if proc.returncode != 0:
        raise TranscodeError(f"MP3 转码失败: {proc.stderr.strip()[-500:]}", proc.returncode)
    return dst


def decode_fmp4(
    src: PathLike,
    out_dir: PathLike = ".",
    fmt: str = "both",
    stem: Optional[str] = None,
    bitrate: str = "192k",
    ffmpeg: Optional[PathLike] = None,
) -> List[Path]:
    """解码 Suno 缓存捕获的 fMP4（常被误标为 .mp3）。

    Args:
        src:     输入文件（fMP4，扩展名可能是 .mp3）
        out_dir: 输出目录
        fmt:     "opus" | "mp3" | "both"
        stem:    输出文件名主干，默认由输入名安全化得到
        bitrate: MP3 码率
        ffmpeg:  ffmpeg 绝对路径，默认自动查找

    Returns:
        生成的输出文件路径列表

    Raises:
        EncryptedBlobError:      输入是加密密文（应改用缓存捕获的 fMP4）
        NotFragmentedMP4Error:   输入不是 fMP4
        FFmpegNotFoundError / TranscodeError
    """
    src = Path(src)
    with open(src, "rb") as fh:
        data = fh.read()

    verdict = classify(data, path=str(src))
    if verdict.is_encrypted and not verdict.breakable:
        raise EncryptedBlobError(str(src), verdict.entropy, verdict.chi_square)
    if not is_fragmented_mp4(data):
        raise NotFragmentedMP4Error(str(src), f"判定类型={verdict.kind}")

    base = stem or _sanitize(src.stem)
    out = _ensure_outdir(out_dir)
    results: List[Path] = []

    if fmt in ("opus", "both"):
        results.append(remux_opus(src, out / f"{base}_decoded.opus", ffmpeg))
    if fmt in ("mp3", "both"):
        results.append(to_mp3(src, out / f"{base}_decoded.mp3", bitrate, ffmpeg))

    return results
