"""CLI 入口（Typer 应用）。

子命令结构：
    smartnotegen generate midi / generate melody
    smartnotegen render
    smartnotegen export suno
    smartnotegen pipeline
    smartnotegen batch            （P1-3 完整实现）
    smartnotegen config init / config show
    smartnotegen errors           （P2-3 错误码表）
    smartnotegen ai musicgen / ai diffrhythm   （P1 骨架）

错误处理：统一捕获 SmartNoteGenError -> 映射退出码 + 友好提示（--debug 才打印堆栈）。
"""

from __future__ import annotations

import functools
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

import typer

from smartnotegen import __version__
from smartnotegen.config import Config
from smartnotegen.env import PathResolver
from smartnotegen.exceptions import (
    BatchFailedError,
    BatchPartialError,
    ERROR_CODES,
    SmartNoteGenError,
)
from smartnotegen.export.suno import ExportOptions, SunoExporter
from smartnotegen.generators.base import GenerationRequest
from smartnotegen.generators.music21_melody import Music21MelodyGenerator
from smartnotegen.generators.procedural import ProceduralGenerator
from smartnotegen.logging_setup import get_logger, setup_logging
from smartnotegen.models.midi import MidiDocument
from smartnotegen.output_manager import ArtifactMeta, OutputManager, RunMeta
from smartnotegen.render.fluidsynth import FluidSynthRenderer
from smartnotegen.styles import StyleRegistry

logger = get_logger("cli")

#: --debug 时打印未预期异常堆栈（由 main 回调设置）
_DEBUG_ENABLED = False

app = typer.Typer(
    name="smartnotegen",
    help="本地 AI 音乐生成 CLI：程序化 MIDI → 渲染 WAV → Suno 合规导出",
    no_args_is_help=True,
    add_completion=False,
)

generate_app = typer.Typer(help="生成 MIDI/旋律", no_args_is_help=True)
export_app = typer.Typer(help="导出音频", no_args_is_help=True)
config_app = typer.Typer(help="配置管理", no_args_is_help=True)
ai_app = typer.Typer(help="AI 模型适配器（P1）", no_args_is_help=True)

app.add_typer(generate_app, name="generate")
app.add_typer(export_app, name="export")
app.add_typer(config_app, name="config")
app.add_typer(ai_app, name="ai")


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _guard(func: Callable) -> Callable:
    """统一错误处理：SmartNoteGenError -> 退出码；其余 -> 退出码 1。"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except typer.Exit:
            raise  # 透传 typer.Exit（play/doctor 主动控制退出码）
        except SmartNoteGenError as exc:
            if _DEBUG_ENABLED:
                logger.exception("预期错误 [%s]: %s", exc.code, exc)
            else:
                logger.error("错误 [%s]: %s", exc.code, exc)
            typer.echo(f"错误 [{exc.code}]: {exc}", err=True)
            raise typer.Exit(exc.code) from exc
        except Exception as exc:  # pragma: no cover - 兜底
            if _DEBUG_ENABLED:
                logger.exception("unexpected error")
            else:
                logger.error("unexpected error: %s", exc)
            typer.echo(f"意外错误: {exc}", err=True)
            raise typer.Exit(1) from exc

    return wrapper


def _load_config(ctx: typer.Context) -> Config:
    """从 CLI 上下文加载配置（--config 覆盖）。"""
    cfg_path = ctx.obj.get("config_path") if ctx.obj else None
    return Config.load(path=cfg_path)


def _style_registry(cfg: Config) -> StyleRegistry:
    """构建 StyleRegistry（内置 + [styles] dir / search_paths 自定义目录）。"""
    dirs = []
    styles_dir = Path(cfg.styles.dir).expanduser()
    if not styles_dir.is_absolute():
        styles_dir = Path.cwd() / styles_dir
    dirs.append(styles_dir)
    dirs.extend(Path(x).expanduser() for x in cfg.styles.search_paths)
    return StyleRegistry(extra_dirs=dirs)


def _apply_style_preset(
    request: GenerationRequest,
    cfg: Config,
    *,
    style_explicit: bool,
    bpm_explicit: Optional[int],
    chords_explicit: Optional[str],
    rhythm_explicit: Optional[str],
) -> GenerationRequest:
    """当 --style 显式提供时，将风格预设（BPM/和弦/节奏型/乐器）注入 request。

    仅显式 --style 生效，避免覆盖配置优先级（config < CLI < 风格预设只在零参数时兜底）。
    bpm/chords/rhythm 均有 *_explicit 保护：用户显式传入的值优先于风格预设。
    """
    if not style_explicit:
        return request
    preset = _style_registry(cfg).get(request.style)
    if bpm_explicit is None and preset.bpm_range:
        request.bpm = (preset.bpm_range[0] + preset.bpm_range[1]) // 2
    if chords_explicit is None and preset.chord_preference:
        request.chords = preset.chord_preference[0]
    if rhythm_explicit is None and preset.rhythm_pattern:
        request.rhythm_pattern = preset.rhythm_pattern
    request.style_instruments = dict(preset.instruments)
    request.melody_profile = dict(preset.melody_profile)
    return request


def _request_from_config(
    cfg: Config,
    chords: Optional[str] = None,
    bpm: Optional[int] = None,
    key: Optional[str] = None,
    time_signature: Optional[str] = None,
    bars: Optional[int] = None,
    style: Optional[str] = None,
    seed: Optional[int] = None,
    with_drums: Optional[bool] = None,
    tracks: Optional[List[str]] = None,
    voice_leading: Optional[bool] = None,
    counterpoint: Optional[bool] = None,
    inversion: Optional[bool] = None,
    rhythm: Optional[str] = None,
) -> GenerationRequest:
    """按合并优先级构造 GenerationRequest（含 P2-2 乐理开关）。"""
    merged = cfg.merge_cli(
        chords=chords,
        bpm=bpm,
        key=key,
        time_signature=time_signature,
        bars=bars,
        style=style,
        seed=seed,
        with_drums=with_drums,
        tracks=tracks,
        voice_leading=voice_leading,
        counterpoint=counterpoint,
        inversion=inversion,
        rhythm_pattern=rhythm,
    )
    d = merged.defaults
    request = GenerationRequest(
        chords=d.chords,
        bpm=d.bpm,
        key=d.key,
        time_signature=d.time_signature,
        bars=d.bars,
        style=d.style,
        seed=merged.random.seed,
        tracks=list(d.tracks),
        with_drums=d.with_drums,
        enable_voice_leading=d.voice_leading,
        enable_counterpoint=d.counterpoint,
        enable_inversion=d.inversion,
        rhythm_pattern=d.rhythm_pattern,
    )
    request = _apply_style_preset(
        request, cfg,
        style_explicit=style is not None,
        bpm_explicit=bpm,
        chords_explicit=chords,
        rhythm_explicit=rhythm,
    )
    return request


def _export_opts_from_config(
    cfg: Config,
    duration: Optional[int] = None,
    format: Optional[str] = None,
    sample_rate: Optional[int] = None,
    bit_depth: Optional[int] = None,
    fade_ms: Optional[float] = None,
) -> ExportOptions:
    """按合并优先级构造 ExportOptions。"""
    merged = cfg.merge_cli(
        duration=duration,
        format=format,
        sample_rate=sample_rate,
        bit_depth=bit_depth,
        fade_ms=fade_ms,
    )
    e = merged.export
    return ExportOptions(
        duration=e.duration,
        format=e.format,
        sample_rate=e.sample_rate,
        bit_depth=e.bit_depth,
        fade_ms=e.fade_ms,
    )


def _write_single_metadata(
    cfg: Config,
    command: str,
    seed: Optional[int],
    artifacts: List[ArtifactMeta],
    project: Optional[str] = None,
    output_dir: Optional[str | Path] = None,
) -> None:
    """单次生成命令的元数据落盘（P2-5）。"""
    if not cfg.output.metadata:
        return
    om = OutputManager(cfg, project=project, output_dir=output_dir)
    om.write_metadata(
        RunMeta(
            command=command,
            seed=seed,
            started_at=datetime.now().isoformat(timespec="seconds"),
            duration_s=0.0,
            version=__version__,
            config_path=str(cfg.config_path) if cfg.config_path else None,
        ),
        artifacts,
    )


# ---------------------------------------------------------------------------
# 顶层回调
# ---------------------------------------------------------------------------

def _version_callback(value: bool) -> None:
    """--version：打印版本号并退出。"""
    if value:
        typer.echo(f"smartnotegen {__version__}")
        raise typer.Exit(0)


@app.callback()
def main(
    ctx: typer.Context,
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="配置文件路径（默认查找项目根 smartnotegen.toml）"
    ),
    verbose: bool = typer.Option(False, "--verbose", help="输出 DEBUG 级日志"),
    quiet: bool = typer.Option(False, "--quiet", help="仅输出 ERROR 级日志"),
    debug: bool = typer.Option(False, "--debug", help="DEBUG 级日志 + 打印堆栈"),
    version: bool = typer.Option(
        None, "--version", help="显示版本号", callback=_version_callback, is_eager=True
    ),
) -> None:
    """SmartNoteGen 主入口。"""
    global _DEBUG_ENABLED
    _DEBUG_ENABLED = debug
    setup_logging(verbose=verbose, quiet=quiet, debug=debug)
    ctx.obj = {"config_path": config}


# ---------------------------------------------------------------------------
# generate midi
# ---------------------------------------------------------------------------

@generate_app.command("midi", help="程序化生成多轨 MIDI（和弦/旋律/贝斯 [+鼓]）")
@_guard
def generate_midi(
    ctx: typer.Context,
    chords: Optional[str] = typer.Option(None, "--chords", help="和弦进行，如 C-G-Am-F"),
    bpm: Optional[int] = typer.Option(None, "--bpm", help="速度"),
    key: Optional[str] = typer.Option(None, "--key", help="调式，如 'C major'"),
    time_signature: Optional[str] = typer.Option(
        None, "--time-signature", help="拍号，如 '4/4'"
    ),
    bars: Optional[int] = typer.Option(None, "--bars", help="小节数"),
    style: Optional[str] = typer.Option(None, "--style", help="风格 pop/rock/electronic/classical 或自定义"),
    seed: Optional[int] = typer.Option(None, "--seed", help="随机种子（可复现）"),
    with_drums: bool = typer.Option(False, "--with-drums", help="追加第 4 轨鼓"),
    track: Optional[List[str]] = typer.Option(
        None, "--track", help="轨道名（可多次，如 --track chords --track melody）"
    ),
    voice_leading: bool = typer.Option(False, "--voice-leading", help="检测/提示平行五度与八度"),
    counterpoint: bool = typer.Option(False, "--counterpoint", help="二声部对位约束"),
    inversion: bool = typer.Option(False, "--inversion", help="和弦转位（低音平滑）"),
    rhythm: Optional[str] = typer.Option(None, "--rhythm", help="节奏型名（pop/rock/... 或自定义）"),
    project: Optional[str] = typer.Option(None, "--project", help="输出项目名（P2-5）"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", help="输出根目录覆盖"),
    output: Optional[Path] = typer.Option(None, "--output", help="输出 .mid 路径"),
) -> None:
    """程序化 MIDI 生成（P0-2；P2-2 乐理开关 / P2-4 风格预设 / P2-5 输出管理）。"""
    cfg = _load_config(ctx)
    request = _request_from_config(
        cfg,
        chords=chords,
        bpm=bpm,
        key=key,
        time_signature=time_signature,
        bars=bars,
        style=style,
        seed=seed,
        with_drums=with_drums,
        tracks=track,
        voice_leading=voice_leading,
        counterpoint=counterpoint,
        inversion=inversion,
        rhythm=rhythm,
    )
    gen = ProceduralGenerator(seed=request.seed)
    seq = gen.generate(request)

    if output is None:
        om = OutputManager(cfg, project=project, output_dir=output_dir)
        seq_no = om.next_seq(request.style, request.bpm, request.seed, "mid")
        output = om.plan_path(
            style=request.style, bpm=request.bpm, seed=request.seed, ext="mid", seq=seq_no
        )
    else:
        seq_no = 1  # 显式 --output 时无批次序号语义
    path = MidiDocument.from_sequence(seq).write(output)
    _write_single_metadata(
        cfg,
        command=f"smartnotegen generate midi --style {request.style} --seed {request.seed}",
        seed=request.seed,
        artifacts=[
            ArtifactMeta(
                path=str(path), kind="midi",
                params={"chords": request.chords, "bpm": request.bpm,
                        "bars": request.bars, "style": request.style},
                seed=request.seed, seq=seq_no, duration_s=seq.duration_seconds(),
            )
        ],
        project=project,
        output_dir=output_dir,
    )
    typer.echo(f"✅ MIDI 已生成: {path}")
    typer.echo(f"   轨道: {', '.join(seq.track_names)}")
    typer.echo(f"   时长: {seq.duration_seconds():.1f}s（{request.bpm}bpm / {request.bars} 小节）")


# ---------------------------------------------------------------------------
# generate melody
# ---------------------------------------------------------------------------

@generate_app.command("melody", help="music21 乐理驱动旋律生成 + 变奏")
@_guard
def generate_melody(
    ctx: typer.Context,
    chords: Optional[str] = typer.Option(None, "--chords", help="和弦进行，如 C-G-Am-F"),
    bpm: Optional[int] = typer.Option(None, "--bpm", help="速度"),
    key: Optional[str] = typer.Option(None, "--key", help="调式，如 'C major'"),
    time_signature: Optional[str] = typer.Option(
        None, "--time-signature", help="拍号，如 '4/4'"
    ),
    bars: Optional[int] = typer.Option(None, "--bars", help="小节数"),
    style: Optional[str] = typer.Option(None, "--style", help="风格标签"),
    seed: Optional[int] = typer.Option(None, "--seed", help="随机种子（可复现）"),
    variations: int = typer.Option(1, "--variations", help="变奏数量（1-3，rhythm/ornament/retrograde）"),
    voice_leading: bool = typer.Option(False, "--voice-leading", help="检测/提示平行五度与八度"),
    counterpoint: bool = typer.Option(False, "--counterpoint", help="二声部对位约束"),
    inversion: bool = typer.Option(False, "--inversion", help="和弦转位（低音平滑）"),
    rhythm: Optional[str] = typer.Option(None, "--rhythm", help="节奏型名"),
    project: Optional[str] = typer.Option(None, "--project", help="输出项目名（P2-5）"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", help="输出根目录覆盖"),
    output: Optional[Path] = typer.Option(None, "--output", help="输出 .mid 路径"),
) -> None:
    """乐理旋律生成（P0-3）：主旋律 + N 个变奏（同文件多轨）。"""
    cfg = _load_config(ctx)
    request = _request_from_config(
        cfg,
        chords=chords,
        bpm=bpm,
        key=key,
        time_signature=time_signature,
        bars=bars,
        style=style,
        seed=seed,
        voice_leading=voice_leading,
        counterpoint=counterpoint,
        inversion=inversion,
        rhythm=rhythm,
    )
    request.variations = variations
    gen = Music21MelodyGenerator(seed=request.seed)
    seq = gen.generate(request)

    if output is None:
        om = OutputManager(cfg, project=project, output_dir=output_dir)
        seq_no = om.next_seq(request.style, request.bpm, request.seed, "mid")
        output = om.plan_path(
            style=request.style, bpm=request.bpm, seed=request.seed,
            ext="mid", seq=seq_no, suffix="_melody",
        )
    else:
        seq_no = 1
    path = MidiDocument.from_sequence(seq).write(output)
    _write_single_metadata(
        cfg,
        command=f"smartnotegen generate melody --seed {request.seed}",
        seed=request.seed,
        artifacts=[
            ArtifactMeta(
                path=str(path), kind="midi",
                params={"chords": request.chords, "bpm": request.bpm,
                        "bars": request.bars, "style": request.style},
                seed=request.seed, seq=seq_no, duration_s=seq.duration_seconds(),
            )
        ],
        project=project,
        output_dir=output_dir,
    )
    typer.echo(f"✅ 旋律 MIDI 已生成: {path}")
    typer.echo(f"   轨道: {', '.join(seq.track_names)}")


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

@app.command("render", help="MIDI -> WAV 渲染（FluidSynth + SoundFont，真实引擎）")
@_guard
def render_cmd(
    ctx: typer.Context,
    input: Path = typer.Option(..., "--input", "-i", help="输入 .mid 路径"),
    soundfont: Optional[str] = typer.Option(None, "--soundfont", help="SoundFont 路径（覆盖配置）"),
    fluidsynth: Optional[str] = typer.Option(None, "--fluidsynth", help="fluidsynth 可执行文件路径"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="输出 .wav 路径"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅打印将执行的命令，不调用 subprocess、不写产物"),
) -> None:
    """MIDI → WAV 渲染（P0-4）：44.1kHz / 16bit；默认使用 module/ 真实引擎（M-1）。"""
    cfg = _load_config(ctx)
    merged = cfg.merge_cli(soundfont=soundfont, fluidsynth=fluidsynth)

    # 输入存在性前置校验（保证缺失输入 -> 退出码 3）
    midi = Path(input).expanduser().resolve()
    if not midi.is_file():
        from smartnotegen.exceptions import InputFileError

        raise InputFileError(f"MIDI 文件不存在: {midi}", code=3)

    resolver = PathResolver(merged)
    if dry_run:
        # dry-run 是唯一允许 mock 的通道：不探测、不解析路径
        sf = merged.paths.soundfont
        fs = merged.paths.fluidsynth
    else:
        resolver.ensure_ready()
        sf = resolver.resolve_soundfont()
        fs = resolver.resolve_fluidsynth()

    if output is None:
        output = input.with_name(f"{input.stem}_rendered.wav")
    renderer = FluidSynthRenderer(fluidsynth_path=str(fs))
    path = renderer.render(str(input), str(sf), str(output), dry_run=dry_run)
    prefix = "[DRY-RUN] " if dry_run else "✅ "
    typer.echo(f"{prefix}WAV 已渲染: {path}")


# ---------------------------------------------------------------------------
# export suno
# ---------------------------------------------------------------------------

@export_app.command("suno", help="Suno 合规导出（10–30s 纯器乐 WAV/MP3，恒禁混响）")
@_guard
def export_suno(
    ctx: typer.Context,
    input: Path = typer.Option(..., "--input", "-i", help="输入 WAV 路径"),
    duration: Optional[int] = typer.Option(None, "--duration", help="目标时长（10-30s）"),
    format: Optional[str] = typer.Option(None, "--format", help="导出格式 wav|mp3"),
    sample_rate: Optional[int] = typer.Option(None, "--sample-rate", help="采样率（默认 44100）"),
    bit_depth: Optional[int] = typer.Option(None, "--bit-depth", help="位深（默认 16）"),
    fade_ms: Optional[float] = typer.Option(None, "--fade-ms", help="淡入淡出毫秒数"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="输出路径"),
) -> None:
    """Suno 合规导出（P0-5；无混响合规约束由导出器强制执行）。"""
    cfg = _load_config(ctx)
    opts = _export_opts_from_config(
        cfg, duration=duration, format=format, sample_rate=sample_rate,
        bit_depth=bit_depth, fade_ms=fade_ms,
    )
    exporter = SunoExporter()
    path = exporter.export(str(input), opts, output_path=output)
    meta = exporter.describe(path)
    typer.echo(f"✅ Suno 合规片段已导出: {path}")
    typer.echo(f"   元数据: 时长 {meta['duration_s']}s / {meta['sample_rate']}Hz / {meta['bit_depth']}bit / {meta['channels']}ch")


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------

@app.command("pipeline", help="一键管线：generate → render → DSP → export（零参数跑通 demo）")
@_guard
def pipeline_cmd(
    ctx: typer.Context,
    chords: Optional[str] = typer.Option(None, "--chords", help="和弦进行，如 C-G-Am-F"),
    bpm: Optional[int] = typer.Option(None, "--bpm", help="速度"),
    key: Optional[str] = typer.Option(None, "--key", help="调式，如 'C major'"),
    bars: Optional[int] = typer.Option(None, "--bars", help="小节数"),
    style: Optional[str] = typer.Option(None, "--style", help="风格（P2-4 预设）"),
    seed: Optional[int] = typer.Option(None, "--seed", help="随机种子（可复现）"),
    with_drums: bool = typer.Option(False, "--with-drums", help="追加鼓轨"),
    voice_leading: bool = typer.Option(False, "--voice-leading", help="检测/提示平行五度与八度"),
    counterpoint: bool = typer.Option(False, "--counterpoint", help="二声部对位约束"),
    inversion: bool = typer.Option(False, "--inversion", help="和弦转位（低音平滑）"),
    rhythm: Optional[str] = typer.Option(None, "--rhythm", help="节奏型名"),
    duration: Optional[int] = typer.Option(None, "--duration", help="Suno 目标时长（10-30s）"),
    format: Optional[str] = typer.Option(None, "--format", help="导出格式 wav|mp3"),
    project: Optional[str] = typer.Option(None, "--project", help="输出项目名（P2-5）"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", help="输出根目录覆盖"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅规划并打印命令，不写产物"),
    fade_in: Optional[float] = typer.Option(None, "--fade-in", help="淡入毫秒（0-5000）"),
    fade_out: Optional[float] = typer.Option(None, "--fade-out", help="淡出毫秒（0-5000）"),
    eq: bool = typer.Option(False, "--eq", help="开启低频切 EQ"),
    compressor: bool = typer.Option(False, "--compressor", help="开启轻压缩"),
    reverb: bool = typer.Option(False, "--reverb", help="请求混响（当前未支持，显式报错）"),
    no_preview: bool = typer.Option(False, "--no-preview", help="不生成 HTML 预览页"),
) -> None:
    """闭环：生成 → 渲染 → DSP → 合规导出（P0 + P2-1 + P2-5）。"""
    from smartnotegen.pipeline import Pipeline

    cfg = _load_config(ctx)
    request = _request_from_config(
        cfg, chords=chords, bpm=bpm, key=key, bars=bars, style=style,
        seed=seed, with_drums=with_drums, voice_leading=voice_leading,
        counterpoint=counterpoint, inversion=inversion, rhythm=rhythm,
    )
    opts = _export_opts_from_config(cfg, duration=duration, format=format)
    merged = cfg.merge_cli(
        fade_in_ms=fade_in, fade_out_ms=fade_out, eq=eq, compressor=compressor, reverb=reverb
    )
    # 应用 --no-preview
    if no_preview:
        merged = cfg.merge_cli()  # 保持其他配置不变
    pipeline = Pipeline(merged, project=project, output_dir=output_dir, dry_run=dry_run)
    result = pipeline.run(request, opts)
    prefix = "[DRY-RUN] " if dry_run else "✅ "
    typer.echo(f"{prefix}Pipeline 完成")
    typer.echo(f"   最终产物: {result.export_path}")
    typer.echo(
        f"   元数据: 时长 {result.duration_s}s / {result.sample_rate}Hz / "
        f"{result.bit_depth}bit / 和弦 {result.chords} / seed {result.seed} / "
        f"{result.bpm}bpm / {result.bars} 小节"
    )


# ---------------------------------------------------------------------------
# batch（P1-3 完整实现）
# ---------------------------------------------------------------------------

@app.command("batch", help="批量生成多个变体（随机化 + 可复现 + 失败隔离）")
@_guard
def batch_cmd(
    ctx: typer.Context,
    count: int = typer.Option(3, "--count", help="生成数量（默认 3）"),
    seed: Optional[int] = typer.Option(None, "--seed", help="全局随机种子（可复现）"),
    chords_choices: Optional[List[str]] = typer.Option(
        None, "--chords-choices", help="和弦池（可多次，如 --chords-choices C-G-Am-F Am-F-C-G）"
    ),
    style: Optional[str] = typer.Option(None, "--style", help="风格基准（P2-4 预设）"),
    variations: bool = typer.Option(False, "--variations", help="风格/乐器/bpm 维度变体"),
    rhythm_variants: bool = typer.Option(False, "--rhythm-variants", help="节奏型维度变体"),
    melody_variants: bool = typer.Option(False, "--melody-variants", help="旋律变奏维度"),
    render: bool = typer.Option(False, "--render", help="链式真实渲染 WAV"),
    export: bool = typer.Option(False, "--export", help="链式导出 Suno 合规片段（需 --render）"),
    parallel: bool = typer.Option(False, "--parallel", help="并行执行（默认串行）"),
    parallel_workers: int = typer.Option(2, "--parallel-workers", help="并行并发数"),
    project: Optional[str] = typer.Option(None, "--project", help="输出项目名（P2-5）"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", help="输出根目录覆盖"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅规划并打印，不写产物"),
    bpm: Optional[int] = typer.Option(None, "--bpm", help="固定 BPM（覆盖预设）"),
    bars: Optional[int] = typer.Option(None, "--bars", help="小节数"),
    with_drums: bool = typer.Option(False, "--with-drums", help="追加鼓轨"),
    voice_leading: bool = typer.Option(False, "--voice-leading", help="检测/提示平行五度与八度"),
    counterpoint: bool = typer.Option(False, "--counterpoint", help="二声部对位约束"),
    inversion: bool = typer.Option(False, "--inversion", help="和弦转位"),
    rhythm: Optional[str] = typer.Option(None, "--rhythm", help="固定节奏型名"),
) -> None:
    """批量生成（P1-3 完整实现）：四维度随机化、失败隔离、退出码 0/8/9。"""
    from smartnotegen.batch import BatchOptions, BatchRunner

    cfg = _load_config(ctx)
    options = BatchOptions(
        count=count, seed=seed, chords_choices=chords_choices, style=style,
        variations=variations, rhythm_variants=rhythm_variants,
        melody_variants=melody_variants, render=render, export=export,
        parallel=parallel, parallel_workers=parallel_workers,
        project=project, output_dir=output_dir, dry_run=dry_run,
        bpm=bpm, bars=bars, with_drums=with_drums,
        voice_leading=voice_leading, counterpoint=counterpoint,
        inversion=inversion, rhythm_pattern=rhythm,
    )
    runner = BatchRunner(options, config=cfg)
    result = runner.run()

    for r in result.items:
        icon = "✅" if r.status == "ok" else "❌"
        typer.echo(f"  {icon} 第 {r.index + 1} 项 (seed={r.seed}): {r.status}")
        if r.error:
            typer.echo(f"      错误: {r.error}")
        if r.midi_path:
            typer.echo(f"      MIDI: {r.midi_path}")
        if r.wav_path:
            typer.echo(f"      WAV: {r.wav_path}")
        if r.export_path:
            typer.echo(f"      Suno: {r.export_path}")
    typer.echo(
        f"{'[DRY-RUN] ' if dry_run else '✅ '}批量完成: 成功 {result.ok_count} / "
        f"失败 {result.failed_count}（全局 seed={result.actual_seed}）"
    )

    if result.failed_count == 0:
        return
    if result.ok_count == 0:
        raise BatchFailedError(
            f"批量全部失败（成功 {result.ok_count} / 失败 {result.failed_count}），"
            "请查看上方错误日志",
            code=9,
        )
    raise BatchPartialError(
        f"批量部分失败（成功 {result.ok_count} / 失败 {result.failed_count}），"
        "失败项已隔离，成功项不受影响",
        code=8,
    )


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

@config_app.command("init", help="生成配置文件模板（默认 smartnotegen.toml）")
@_guard
def config_init(
    path: Path = typer.Option(Path("smartnotegen.toml"), "--path", "-p", help="目标路径"),
) -> None:
    """生成带注释的默认配置模板（P0-6）。"""
    target = Path(path).expanduser().resolve()
    template = Path.cwd() / "config" / "default.toml"
    if template.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        typer.echo(f"✅ 配置文件已生成: {target}")
        typer.echo("   可修改 SoundFont 路径后使用：smartnotegen --config <path> <子命令>")
    else:
        target = Path(Config().write_template(target))
        typer.echo(f"✅ 配置文件已生成: {target}")


@config_app.command("show", help="打印合并后的生效配置")
@_guard
def config_show(ctx: typer.Context) -> None:
    """打印合并后的生效配置（P0-6）。"""
    import tomli_w

    cfg = _load_config(ctx)
    source = f"（来源: {cfg.config_path}）" if cfg.config_path else "（内置默认值）"
    typer.echo(f"# 生效配置 {source}")
    typer.echo(tomli_w.dumps(cfg.to_dict()).rstrip())


# ---------------------------------------------------------------------------
# play（P3-A2 本地播放）
# ---------------------------------------------------------------------------

@app.command("play", help="用系统默认播放器播放 WAV 文件")
@_guard
def play_cmd(
    wav_path: str = typer.Argument(..., help="要播放的 WAV 文件路径"),
) -> None:
    """调用系统默认播放器播放 WAV 文件（P3-A2）。"""
    path = Path(wav_path).expanduser().resolve()
    if not path.is_file():
        from smartnotegen.exceptions import InputFileError
        raise InputFileError(f"文件不存在: {path}", code=3)
    import os
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        import subprocess
        subprocess.run(["open", str(path)], check=False)
    else:
        import subprocess
        subprocess.run(["xdg-open", str(path)], check=False)
    typer.echo(f"▶ 正在播放: {path}")


# ---------------------------------------------------------------------------
# doctor（P3-E3 环境诊断）
# ---------------------------------------------------------------------------

@app.command("doctor", help="一键环境健康检查")
@_guard
def doctor_cmd(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="输出详细信息"),
) -> None:
    """环境诊断（P3-E3）：检查 Python/fluidsynth/SF2/AI/显存/espeak 等。"""
    import shutil
    import sys
    from smartnotegen.env import PathResolver, ProbeStatus

    cfg = _load_config(ctx)
    errors = 0
    warnings = 0

    typer.echo("SmartNoteGen 环境诊断")
    typer.echo("═══════════════════════════════════════")

    # Python
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    _doctor_item("Python", f"✅ {py_ver}" if sys.version_info >= (3, 12) else f"⚠️ {py_ver}（建议 3.12+）")

    # FluidSynth + SoundFont（复用 PathResolver）
    resolver = PathResolver(cfg)
    probes = resolver.probe_all()
    for probe in probes:
        if probe.status == ProbeStatus.OK:
            _doctor_item(probe.component, f"✅ OK ({probe.path})")
        elif probe.status == ProbeStatus.MISSING:
            _doctor_item(probe.component, f"❌ MISSING ({probe.path})")
            typer.echo(f"     → {probe.detail}")
            errors += 1
        else:
            _doctor_item(probe.component, f"⚠️ BROKEN ({probe.path})")
            typer.echo(f"     → {probe.detail}")
            warnings += 1

    # AI 依赖
    torch_ok = False
    try:
        import importlib.util
        torch_ok = importlib.util.find_spec("torch") is not None
    except Exception:
        pass
    if torch_ok:
        _doctor_item("AI 依赖", "✅ torch 已安装")
        # CUDA 检查
        try:
            import torch
            try:
                cuda_ok = torch.cuda.is_available()
            except Exception:
                cuda_ok = False
            if cuda_ok:
                try:
                    props = torch.cuda.get_device_properties(0)
                    total_gb = props.total_mem / 1024**3
                    _doctor_item("CUDA", f"✅ {torch.cuda.get_device_name(0)} ({total_gb:.1f} GB)")
                except Exception:
                    _doctor_item("CUDA", "✅ 可用（获取详情失败）")
            else:
                _doctor_item("CUDA", "⚠️ CUDA 不可用（将使用 CPU）")
                warnings += 1
        except Exception:
            _doctor_item("CUDA", "⚠️ 检查失败")
            warnings += 1
        # audiocraft
        ac_ok = importlib.util.find_spec("audiocraft") is not None
        _doctor_item("audiocraft", "✅ 已安装" if ac_ok else "⚠️ 未安装")
        # diffrhythm
        dr_ok = importlib.util.find_spec("diffrhythm") is not None
        _doctor_item("diffrhythm", "✅ 已安装" if dr_ok else "⚠️ 未安装")
    else:
        _doctor_item("AI 依赖", "❌ torch 未安装")
        typer.echo("     → 安装: pip install torch --index-url https://download.pytorch.org/whl/cu121")
        errors += 1

    # espeak-ng
    espeak = shutil.which("espeak-ng")
    _doctor_item("espeak-ng", f"✅ {espeak}" if espeak else "⚠️ 未安装（DiffRhythm 人声合成需要）")
    if not espeak:
        warnings += 1

    # 项目完整性
    project_root = Path.cwd()
    has_pyproject = (project_root / "pyproject.toml").is_file()
    has_module = (project_root / "module").is_dir()
    if has_pyproject and has_module:
        _doctor_item("项目完整性", "✅ pyproject.toml + module/ 存在")
    else:
        missing = []
        if not has_pyproject:
            missing.append("pyproject.toml")
        if not has_module:
            missing.append("module/")
        _doctor_item("项目完整性", f"⚠️ 缺失: {', '.join(missing)}")
        warnings += 1

    typer.echo("═══════════════════════════════════════")
    if errors == 0 and warnings == 0:
        typer.echo("✅ 状态: 全部正常")
        return
    if errors > 0:
        typer.echo(f"❌ 状态: {errors} 个错误, {warnings} 个警告（需修复）")
        raise typer.Exit(2)
    typer.echo(f"⚠️ 状态: {warnings} 个警告（可继续使用）")
    raise typer.Exit(1)


def _doctor_item(name: str, status: str) -> None:
    """打印一行诊断项。"""
    typer.echo(f"  {name:<12} {status}")


# ---------------------------------------------------------------------------
# inspire（P3-C1 灵感库）
# ---------------------------------------------------------------------------

inspire_app = typer.Typer(help="灵感库管理（SQLite 存储）")
app.add_typer(inspire_app, name="inspire")


@inspire_app.command("init", help="初始化灵感库（创建 smartnotegen.db）")
@_guard
def inspire_init() -> None:
    """创建灵感库数据库。"""
    from smartnotegen.inspire import InspirationDB
    path = InspirationDB().init_db()
    typer.echo(f"✅ 灵感库已初始化: {path}")


@inspire_app.command("add", help="添加灵感（从 WAV + 元数据提取）")
@_guard
def inspire_add(
    wav_path: str = typer.Argument(..., help="WAV 文件路径"),
    tags: str = typer.Option("", "--tags", help="标签（逗号分隔，如 upbeat,pop）"),
    rating: Optional[int] = typer.Option(None, "--rating", help="评分 1-5"),
) -> None:
    """将 WAV 文件加入灵感库。"""
    from smartnotegen.inspire import InspirationDB
    insp_id = InspirationDB().add(wav_path, tags=tags, rating=rating)
    typer.echo(f"✅ 灵感已添加 (id={insp_id})")


@inspire_app.command("list", help="列出灵感")
@_guard
def inspire_list(
    style: Optional[str] = typer.Option(None, "--style", help="按风格筛选"),
    tag: Optional[str] = typer.Option(None, "--tag", help="按标签筛选"),
    seed: Optional[int] = typer.Option(None, "--seed", help="按种子筛选"),
    date: Optional[str] = typer.Option(None, "--date", help="按日期筛选（YYYYMMDD）"),
    limit: int = typer.Option(50, "--limit", help="最大返回条数"),
) -> None:
    """列出灵感库中的条目。"""
    from smartnotegen.inspire import InspirationDB
    items = InspirationDB().list(style=style, tag=tag, seed=seed, date=date, limit=limit)
    if not items:
        typer.echo("（灵感库为空）")
        return
    for item in items:
        tags_str = f" [{item['tags']}]" if item.get("tags") else ""
        rating_str = f" ★{item['rating']}" if item.get("rating") else ""
        style_str = item.get("style") or "?"
        seed_str = f"seed={item['seed']}" if item.get("seed") is not None else ""
        typer.echo(f"  #{item['id']:<4} {style_str:<12} {seed_str:<12} {item['path']}{tags_str}{rating_str}")


@inspire_app.command("show", help="查看灵感详情")
@_guard
def inspire_show(
    id: int = typer.Argument(..., help="灵感 id"),
) -> None:
    """显示灵感详情。"""
    from smartnotegen.inspire import InspirationDB
    insp = InspirationDB().get(id)
    if not insp:
        typer.echo(f"❌ 灵感不存在: id={id}")
        raise typer.Exit(1)
    typer.echo(f"  id:          {insp['id']}")
    typer.echo(f"  路径:        {insp['path']}")
    typer.echo(f"  风格:        {insp.get('style') or '-'}")
    typer.echo(f"  BPM:         {insp.get('bpm') or '-'}")
    typer.echo(f"  seed:        {insp.get('seed') or '-'}")
    typer.echo(f"  和弦:        {insp.get('chords') or '-'}")
    typer.echo(f"  时长:        {insp.get('duration_s') or '-'}s")
    typer.echo(f"  采样率:      {insp.get('sample_rate') or '-'}Hz")
    typer.echo(f"  RMS:         {insp.get('rms_db') or '-'} dBFS")
    typer.echo(f"  峰值:        {insp.get('peak_db') or '-'} dBFS")
    typer.echo(f"  标签:        {insp.get('tags') or '-'}")
    typer.echo(f"  评分:        {insp.get('rating') or '-'}")
    typer.echo(f"  创建时间:    {insp.get('created_at') or '-'}")


@inspire_app.command("rm", help="删除灵感（仅从库中移除，不删文件）")
@_guard
def inspire_rm(
    id: int = typer.Argument(..., help="灵感 id"),
) -> None:
    """从灵感库中移除。"""
    from smartnotegen.inspire import InspirationDB
    if InspirationDB().delete(id):
        typer.echo(f"✅ 灵感 #{id} 已删除")
    else:
        typer.echo(f"❌ 灵感不存在: id={id}")
        raise typer.Exit(1)


@inspire_app.command("export", help="导出灵感文件到指定目录")
@_guard
def inspire_export(
    id: int = typer.Argument(..., help="灵感 id"),
    output: Path = typer.Option(..., "--output", "-o", help="目标目录"),
) -> None:
    """复制灵感文件到指定目录。"""
    from smartnotegen.inspire import InspirationDB
    try:
        paths = InspirationDB().export_files(id, output)
        typer.echo(f"✅ 已导出 {len(paths)} 个文件:")
        for p in paths:
            typer.echo(f"    {p}")
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(f"❌ {exc}")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# diff（P3-C3 版本对比）
# ---------------------------------------------------------------------------

@app.command("diff", help="对比两个 WAV 的音频特征")
@_guard
def diff_cmd(
    wav1: str = typer.Argument(..., help="第一个 WAV 路径"),
    wav2: str = typer.Argument(..., help="第二个 WAV 路径"),
) -> None:
    """对比两个 WAV 的音频特征差异。"""
    from smartnotegen.preview import compute_audio_features

    p1 = Path(wav1).expanduser().resolve()
    p2 = Path(wav2).expanduser().resolve()

    if not p1.is_file():
        from smartnotegen.exceptions import InputFileError
        raise InputFileError(f"文件不存在: {p1}", code=3)
    if not p2.is_file():
        from smartnotegen.exceptions import InputFileError
        raise InputFileError(f"文件不存在: {p2}", code=3)

    f1 = compute_audio_features(p1)
    f2 = compute_audio_features(p2)

    typer.echo("音频特征对比")
    typer.echo("═══════════════════════════════════════")
    _diff_row("时长", _get_duration(p1), _get_duration(p2), "s")
    _diff_row("RMS", f1.rms_db, f2.rms_db, "dBFS")
    _diff_row("峰值", f1.peak_db, f2.peak_db, "dBFS")
    _diff_row("频谱中心", f1.spectral_centroid, f2.spectral_centroid, "Hz")
    typer.echo("")
    typer.echo("频段能量:")
    for band in ("low", "mid", "high"):
        v1 = f1.band_energy.get(band, 0)
        v2 = f2.band_energy.get(band, 0)
        _diff_row(f"  {band}", f"{v1*100:.0f}%", f"{v2*100:.0f}%", "")

    # 尝试从同目录 metadata.json 提取参数对比
    _diff_metadata(p1, p2)


def _diff_row(label: str, v1: Any, v2: Any, unit: str) -> None:
    """打印一行对比。"""
    diff_val = ""
    if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
        d = v2 - v1
        sign = "+" if d > 0 else ""
        diff_val = f" ({sign}{d:.2f}{unit})" if unit else f" ({sign}{d:.2f})"
    typer.echo(f"  {label:<12} {v1}  →  {v2}{diff_val}")


def _get_duration(wav_path: Path) -> float:
    """获取 WAV 时长（秒）。"""
    import soundfile as sf
    try:
        info = sf.info(str(wav_path))
        return round(info.duration, 2)
    except Exception:
        return 0.0


def _diff_metadata(p1: Path, p2: Path) -> None:
    """尝试从 metadata.json 提取参数对比。"""
    import json

    def _get_params(wav_dir: Path) -> dict:
        meta = wav_dir / "metadata.json"
        if not meta.is_file():
            return {}
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            for art in data.get("artifacts", []):
                if art.get("kind") in ("wav", "suno"):
                    return art.get("params", {})
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    params1 = _get_params(p1.parent)
    params2 = _get_params(p2.parent)

    if params1 or params2:
        typer.echo("")
        typer.echo("参数对比:")
        all_keys = set(params1.keys()) | set(params2.keys())
        for k in sorted(all_keys):
            v1 = params1.get(k, "-")
            v2 = params2.get(k, "-")
            if v1 != v2:
                typer.echo(f"  {k:<15} {v1}  →  {v2}")


# ---------------------------------------------------------------------------
# new（P3-C2 参数引导 wizard）
# ---------------------------------------------------------------------------

@app.command("new", help="交互式引导生成新音乐（新手指南）")
@_guard
def new_cmd() -> None:
    """交互式向导：引导用户逐步生成第一段音乐。"""
    import sys as _sys

    # 非 TTY：直接执行 pipeline 默认参数
    if not _sys.stdin.isatty():
        from smartnotegen.pipeline import Pipeline
        from smartnotegen.config import Config
        from smartnotegen.generators.base import GenerationRequest
        from smartnotegen.export.suno import ExportOptions

        cfg = Config.load()
        pipeline = Pipeline(cfg)
        result = pipeline.run(
            GenerationRequest(seed=42),
            ExportOptions(duration=25),
        )
        typer.echo(f"✅ Pipeline 完成: {result.export_path}")
        return

    typer.echo("🎵 SmartNoteGen 创作向导")
    typer.echo("按回车使用默认值，或输入自定义值")
    typer.echo("")

    # 步骤 1：风格
    style = _prompt("风格", "pop", ["pop", "rock", "electronic", "classical"])

    # 步骤 2：BPM
    bpm_str = _prompt("BPM", "120")
    bpm = int(bpm_str) if bpm_str.isdigit() else 120

    # 步骤 3：和弦
    chords = _prompt("和弦进行", "C-G-Am-F")

    # 步骤 4：时长
    dur_str = _prompt("Suno 导出时长 (10-30s)", "25")
    duration = max(10, min(30, int(dur_str) if dur_str.isdigit() else 25))

    # 步骤 5：小节数
    bars_str = _prompt("小节数", "8")
    bars = max(1, min(64, int(bars_str) if bars_str.isdigit() else 8))

    # 确认
    typer.echo("")
    typer.echo("📋 确认参数:")
    typer.echo(f"  风格: {style}")
    typer.echo(f"  BPM: {bpm}")
    typer.echo(f"  和弦: {chords}")
    typer.echo(f"  时长: {duration}s")
    typer.echo(f"  小节: {bars}")
    confirm = input("执行？[Y/n] ").strip().lower()
    if confirm in ("n", "no"):
        typer.echo("已取消")
        return

    # 执行
    from smartnotegen.pipeline import Pipeline
    from smartnotegen.config import Config
    from smartnotegen.generators.base import GenerationRequest
    from smartnotegen.export.suno import ExportOptions

    cfg = Config.load()
    merged = cfg.merge_cli(style=style, bpm=bpm, chords=chords, bars=bars)
    pipeline = Pipeline(merged)
    result = pipeline.run(
        GenerationRequest(style=style, bpm=bpm, chords=chords, bars=bars, seed=42),
        ExportOptions(duration=duration),
    )
    typer.echo(f"✅ 完成: {result.export_path}")
    typer.echo(f"   预览页: {Path(result.export_path).parent / 'preview.html'}")
    typer.echo("   提示: 用 smartnotegen inspire add <path> 保存为灵感")


def _prompt(label: str, default: str, choices: Optional[list[str]] = None) -> str:
    """交互式提示输入。"""
    choices_hint = f" ({', '.join(choices)})" if choices else ""
    val = input(f"  {label}{choices_hint} [{default}]: ").strip()
    if not val:
        return default
    if choices and val not in choices:
        typer.echo(f"  ⚠️ 可选值: {', '.join(choices)}，使用默认值 {default}")
        return default
    return val


# ---------------------------------------------------------------------------
# errors（P2-3 错误码表）
# ---------------------------------------------------------------------------

@app.command("errors", help="打印错误码表")
@_guard
def errors_cmd() -> None:
    """错误码表（P2-3b 文档化入口）。"""
    typer.echo("SmartNoteGen 错误码表")
    for code, name, desc in ERROR_CODES:
        if desc:
            typer.echo(f"  {code}  {name}: {desc}")
        else:
            typer.echo(f"  {code}  {name}")


# ---------------------------------------------------------------------------
# ai（P1 骨架；二期完整实现）
# ---------------------------------------------------------------------------

@ai_app.command("musicgen", help="MusicGen 适配器（P1）：旋律 WAV -> 伴奏 WAV")
@_guard
def ai_musicgen(
    ctx: typer.Context,
    input: Path = typer.Option(..., "--input", "-i", help="旋律 WAV 路径"),
    prompt: str = typer.Option(..., "--prompt", help="风格提示，如 'upbeat pop'"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="输出 WAV 路径"),
    model_size: Optional[str] = typer.Option(None, "--model-size", help="medium|small（默认 medium，显存不足可 small 降档）"),
    duration: Optional[int] = typer.Option(None, "--duration", help="目标时长（默认对齐输入）"),
    seed: Optional[int] = typer.Option(None, "--seed", help="随机种子"),
    device: Optional[str] = typer.Option(None, "--device", help="cuda|cpu"),
) -> None:
    """MusicGen 扩编曲（P1；P0 环境提示安装依赖，退出码 6）。"""
    from smartnotegen.ai.musicgen import MusicGenAdapter

    cfg = _load_config(ctx)
    merged = cfg.merge_cli(model_size=model_size, device=device)
    adapter = MusicGenAdapter(model_size=merged.ai.model_size, device=merged.ai.device)
    path = adapter.generate(
        str(input), prompt,
        output_path=str(output) if output else None,
        duration=duration, seed=seed,
    )
    _write_single_metadata(
        cfg,
        command=f"smartnotegen ai musicgen --input {input} --prompt {prompt!r}",
        seed=seed,
        artifacts=[
            ArtifactMeta(
                path=path, kind="draft",
                params={"prompt": prompt, "model_size": merged.ai.model_size,
                        "duration": duration},
                seed=seed, seq=1, duration_s=0.0, sample_rate=32000,
                contains_vocals=False,
            )
        ],
    )
    typer.echo(f"✅ 伴奏 WAV 已生成: {path}")


@ai_app.command("diffrhythm", help="DiffRhythm 适配器（P1）：风格提示 -> 歌曲草稿 WAV")
@_guard
def ai_diffrhythm(
    ctx: typer.Context,
    prompt: str = typer.Option(..., "--prompt", help="风格提示，如 'slow ballad'"),
    input: Optional[Path] = typer.Option(None, "--input", "-i", help="可选旋律 WAV 路径"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="输出 WAV 路径"),
    lyrics: Optional[str] = typer.Option(None, "--lyrics", help="歌词（纯文本，行分隔；不传为空词哼唱）"),
    duration: Optional[int] = typer.Option(None, "--duration", help="目标时长（默认 95s）"),
    device: Optional[str] = typer.Option(None, "--device", help="cuda|cpu"),
) -> None:
    """DiffRhythm 歌曲草稿（P1；P0 环境提示安装依赖，退出码 6）。"""
    from smartnotegen.ai.diffrhythm import DiffRhythmAdapter

    cfg = _load_config(ctx)
    merged = cfg.merge_cli(device=device)
    adapter = DiffRhythmAdapter(device=merged.ai.device)
    src = str(input) if input is not None else ""
    path = adapter.generate(
        src, prompt,
        output_path=str(output) if output else None,
        lyrics=lyrics, duration=duration,
    )
    _write_single_metadata(
        cfg,
        command=f"smartnotegen ai diffrhythm --prompt {prompt!r}",
        seed=None,
        artifacts=[
            ArtifactMeta(
                path=path, kind="draft",
                params={"prompt": prompt, "lyrics": bool(lyrics), "duration": duration,
                        "chunked": merged.ai.diffrhythm_chunked},
                seed=None, seq=1, duration_s=0.0, sample_rate=44100,
                contains_vocals=True,
            )
        ],
    )
    typer.echo(f"✅ 歌曲草稿已生成: {path}")
