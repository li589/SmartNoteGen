"""suno CLI：Suno 逆向取证与转码入口。

子命令：
  probe   对文件做取证判定（明文 / 加密密文 / 容器类型）
  decode  解码单个 fMP4（缓存捕获的 *.mp3）为 Opus / MP3
  batch   批量扫描目录：解码所有 fMP4，密文自动跳过并报告
  version 打印版本
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from suno_cat_catch_resolve import __version__
from suno_cat_catch_resolve.exceptions import EncryptedBlobError, SunoError
from suno_cat_catch_resolve.forensics import identify
from suno_cat_catch_resolve.transcoder import decode_fmp4, find_ffmpeg, probe as ffprobe_info

app = typer.Typer(
    help="Suno 逆向与转码：识别猫抓产物、解码 fMP4、判定加密密文",
    add_completion=False,
)


@app.command()
def probe(
    file: Path = typer.Argument(..., help="待取证的文件路径"),
    ffmpeg: Optional[str] = typer.Option(None, "--ffmpeg-path", help="ffmpeg 绝对路径"),
) -> None:
    """对文件做取证判定并打印报告。"""
    verdict = identify(str(file))
    typer.echo(verdict.render())

    if not verdict.is_encrypted:
        try:
            info = ffprobe_info(file, ffmpeg)
        except SunoError as exc:
            typer.echo(f"\n[ffprobe 不可用] {exc.message}")
            return
        typer.echo("\n媒体信息:")
        for key in (
            "codec_name",
            "codec_type",
            "sample_rate",
            "channels",
            "format_name",
            "duration",
            "bit_rate",
        ):
            if key in info:
                typer.echo(f"  {key:12s}: {info[key]}")


@app.command()
def decode(
    file: Path = typer.Argument(..., help="输入文件（fMP4，常被误标为 .mp3）"),
    out: Path = typer.Option(Path("."), "-o", "--out", help="输出目录"),
    fmt: str = typer.Option("both", "--fmt", help="输出格式: opus | mp3 | both"),
    stem: Optional[str] = typer.Option(None, "--stem", help="输出文件名主干"),
    bitrate: str = typer.Option("192k", "--bitrate", help="MP3 码率"),
    ffmpeg: Optional[str] = typer.Option(None, "--ffmpeg-path", help="ffmpeg 绝对路径"),
) -> None:
    """解码 fMP4 为可播放的 Opus / MP3。"""
    if fmt not in ("opus", "mp3", "both"):
        typer.echo("错误: --fmt 只能是 opus / mp3 / both", err=True)
        raise typer.Exit(code=2)

    try:
        outputs = decode_fmp4(file, out, fmt=fmt, stem=stem, bitrate=bitrate, ffmpeg=ffmpeg)
    except EncryptedBlobError as exc:
        typer.echo(exc.message, err=True)
        raise typer.Exit(code=exc.code or 22) from None
    except SunoError as exc:
        typer.echo(f"错误[{exc.code}]: {exc.message}", err=True)
        raise typer.Exit(code=exc.code or 1) from None

    for path in outputs:
        typer.echo(f"已生成: {path}")


@app.command()
def batch(
    directory: Path = typer.Argument(..., help="待扫描的目录"),
    out: Optional[Path] = typer.Option(None, "-o", "--out", help="输出目录，默认原目录"),
    fmt: str = typer.Option("both", "--fmt", help="输出格式: opus | mp3 | both"),
    bitrate: str = typer.Option("192k", "--bitrate", help="MP3 码率"),
    ffmpeg: Optional[str] = typer.Option(None, "--ffmpeg-path", help="ffmpeg 绝对路径"),
) -> None:
    """批量扫描目录：解码所有 fMP4，加密密文跳过并汇总报告。"""
    target_out = out or directory
    decoded: list[Path] = []
    skipped: list[str] = []
    errors: list[str] = []

    for file in sorted(directory.iterdir()):
        if not file.is_file():
            continue
        verdict = identify(str(file))
        if verdict.is_encrypted:
            skipped.append(f"{file.name}  (加密密文, χ²={verdict.chi_square:.0f})")
            continue
        if verdict.kind != "fmp4":
            continue
        try:
            decoded.extend(decode_fmp4(file, target_out, fmt=fmt, bitrate=bitrate, ffmpeg=ffmpeg))
        except SunoError as exc:
            errors.append(f"{file.name}: {exc.message}")

    typer.echo(f"解码成功 {len(decoded)} 个文件:")
    for path in decoded:
        typer.echo(f"  + {path}")
    if skipped:
        typer.echo(f"\n跳过 {len(skipped)} 个加密密文（无密钥不可解，建议改用缓存捕获产物）:")
        for item in skipped:
            typer.echo(f"  - {item}")
    if errors:
        typer.echo(f"\n失败 {len(errors)} 个:")
        for item in errors:
            typer.echo(f"  ! {item}")


@app.command()
def version() -> None:
    """打印版本与 ffmpeg 位置。"""
    typer.echo(f"suno-cat-catch-resolve {__version__}")
    try:
        typer.echo(f"ffmpeg: {find_ffmpeg()}")
    except SunoError:
        typer.echo("ffmpeg: 未找到")


if __name__ == "__main__":
    app()
