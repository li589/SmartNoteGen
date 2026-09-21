"""videomaker CLI：Typer 应用入口。

子命令：
  render     生成视频（v0.3 支持多文件多轨混音）
  multi      一个音频一次产出多平台视频
  presets    列出/切换预设
  config     初始化/显示配置
  version    打印版本
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer

app = typer.Typer(
    help="SmartNoteGen 音乐视频 / 音频可视化生成器",
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="打印版本并退出"),
) -> None:
    if version:
        import videomaker
        typer.echo(f"videomaker {videomaker.__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(app.get_help(ctx))


# ---------------------------------------------------------------------------
# render 子命令
# ---------------------------------------------------------------------------

@app.command()
def render(
    audio: List[str] = typer.Argument(..., help="输入音频（WAV/MP3/FLAC/OGG/MIDI）；多个文件 = 多轨混音，支持 :gain=..:pan=.. 参数"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出视频路径"),
    preset: str = typer.Option("douyin", "--preset", "-p", help="平台预设（douyin/youtube/instagram/official）"),
    style: str = typer.Option("waveform", "--style", "-s", help="视觉效果风格（waveform/spectrum/circular_spectrum/reactive/tracks/waveform_scroll/score）"),
    width: Optional[int] = typer.Option(None, "--width", help="视频宽度"),
    height: Optional[int] = typer.Option(None, "--height", help="视频高度"),
    fps: Optional[int] = typer.Option(None, "--fps", help="帧率"),
    title: str = typer.Option("", "--title", "-t", help="标题文字"),
    subtitle: str = typer.Option("", "--subtitle", help="副标题文字"),
    font_size: int = typer.Option(48, "--font-size", help="字体大小"),
    logo: Optional[str] = typer.Option(None, "--logo", help="Logo 水印 PNG 路径"),
    logo_pos: str = typer.Option("bottom-right", "--logo-pos", help="水印位置（top-left/top-right/bottom-left/bottom-right）"),
    score_midi: Optional[str] = typer.Option(None, "--score-midi", help="score 样式的谱面 MIDI 路径（输入为 .mid 时可省略）"),
    tempo_grid: bool = typer.Option(False, "--tempo-grid", help="用测速 BPM 绘制节拍网格并标注 BPM（score 样式）"),
    notation: str = typer.Option("staff", "--notation", help="score 样式记谱法（staff=五线谱 / jianpu=简谱）"),
) -> None:
    """生成音乐视频。

    支持多格式（WAV/MP3/FLAC/OGG/MIDI，MIDI 自动 FluidSynth 渲染）。
    传入多个文件时自动进入多轨混音模式（建议配合 --style tracks）。
    """
    # 导入主逻辑
    from videomaker.videomaker import video, video_multitrack
    from videomaker.config import Config

    # 构建配置
    cfg = Config.load()
    if title:
        cfg.text.title = title
    if subtitle:
        cfg.text.subtitle = subtitle
    if font_size:
        cfg.text.font_size = font_size
    if logo:
        cfg.logo.path = logo
        cfg.logo.position = logo_pos

    # 多轨模式：>1 个输入
    if len(audio) > 1:
        result = video_multitrack(
            list(audio),
            output_path=output,
            config=cfg,
            preset=preset,
            visual_style=style if style not in ("waveform", "spectrum") else "tracks",
            title=title,
            subtitle=subtitle,
        )
        typer.echo(f"✅ 多轨视频已生成: {result.output_path}")
        typer.echo(f"   时长: {result.duration_s:.1f}s | 分辨率: {result.width}x{result.height} | 帧率: {result.fps}fps")
        typer.echo(f"   混音 WAV: {Path(result.output_path).with_suffix('.mix.wav')}")
        return

    # 执行渲染（双引擎路由 + 背景 + 文字）
    result = video(
        audio_path=audio[0],
        output_path=output,
        config=cfg,
        preset=preset,
        visual_style=style,
        title=title,
        subtitle=subtitle,
        width=width,
        height=height,
        fps=fps,
        score_midi=score_midi,
        tempo_grid=tempo_grid,
        notation=notation,
    )

    typer.echo(f"✅ 视频已生成: {result.output_path}")
    typer.echo(f"   时长: {result.duration_s:.1f}s | 分辨率: {result.width}x{result.height} | 帧率: {result.fps}fps")


# ---------------------------------------------------------------------------
# multi 子命令：一个音频一次产出多平台视频
# ---------------------------------------------------------------------------

@app.command()
def multi(
    audio: str = typer.Argument(..., help="输入音频文件路径"),
    presets_str: str = typer.Option(
        "douyin,youtube,instagram,official",
        "--presets",
        help="逗号分隔的平台预设列表",
    ),
    style: str = typer.Option("waveform", "--style", "-s", help="视觉效果风格"),
    title: str = typer.Option("", "--title", "-t", help="标题文字"),
    logo: Optional[str] = typer.Option(None, "--logo", help="Logo 水印 PNG 路径"),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", "-o", help="输出目录"),
) -> None:
    """一个音频一次产出多个平台视频（发布场景核心闭环）。"""
    from videomaker.videomaker import video
    from videomaker.config import Config
    from videomaker.presets import list_presets
    import time as _time

    names = [p.strip() for p in presets_str.split(",") if p.strip()]
    valid = set(list_presets())
    unknown = [p for p in names if p not in valid]
    if unknown:
        typer.echo(f"❌ 未知预设: {unknown}（可用: {sorted(valid)}）")
        raise typer.Exit(code=1)

    cfg = Config.load()
    if title:
        cfg.text.title = title
    if logo:
        cfg.logo.path = logo

    results = []
    total_start = _time.time()
    for name in names:
        start = _time.time()
        try:
            r = video(
                audio_path=audio,
                config=cfg,
                preset=name,
                visual_style=style,
                title=title,
            )
            dt = _time.time() - start
            results.append((name, r.output_path, f"{dt:.1f}s", "✅"))
        except Exception as exc:
            results.append((name, str(exc), "-", "❌"))

    total = _time.time() - total_start
    typer.echo(f"\n多平台渲染完成（总耗时 {total:.1f}s）:")
    typer.echo(f"{'平台':<12} {'结果':<4} {'耗时':<7} 输出")
    for name, output, dt, status in results:
        typer.echo(f"{name:<12} {status:<4} {dt:<7} {output}")

@app.command()
def presets(
    name: Optional[str] = typer.Option(None, "--name", "-n", help="显示指定预设详情"),
) -> None:
    """列出或查看平台预设。"""
    from videomaker.presets import list_presets, get_preset

    if name:
        preset = get_preset(name)
        typer.echo(f"预设: {name}")
        for k, v in preset.items():
            typer.echo(f"  {k}: {v}")
    else:
        typer.echo("可用预设:")
        for p in list_presets():
            typer.echo(f"  - {p}")


# ---------------------------------------------------------------------------
# config 子命令
# ---------------------------------------------------------------------------

@app.command()
def config(
    action: str = typer.Argument("show", help="操作（show/init）"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="配置文件路径"),
) -> None:
    """管理配置文件。"""
    from videomaker.config import Config

    if action == "init":
        target = path or "videomaker.toml"
        cfg = Config()
        cfg.write_template(target)
        typer.echo(f"✅ 配置文件已生成: {target}")
    elif action == "show":
        cfg = Config.load(path)
        typer.echo(f"当前配置:\n{cfg}")
    else:
        typer.echo(f"未知操作: {action}")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# version 子命令
# ---------------------------------------------------------------------------

@app.command()
def version() -> None:
    """打印版本信息。"""
    import videomaker
    typer.echo(f"videomaker {videomaker.__version__}")


if __name__ == "__main__":
    app()
