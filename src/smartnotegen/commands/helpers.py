"""CLI 辅助函数集（从 cli.py 抽离，保持向后兼容）。"""

from __future__ import annotations

import functools
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional

import typer

from smartnotegen import __version__
from smartnotegen.config import Config
from smartnotegen.exceptions import SmartNoteGenError
from smartnotegen.export.suno import ExportOptions
from smartnotegen.generators.base import GenerationRequest
from smartnotegen.logging_setup import get_logger
from smartnotegen.output_manager import ArtifactMeta, OutputManager, RunMeta
from smartnotegen.styles import StyleRegistry

logger = get_logger("cli.helpers")


# -- 全局状态 ---------------------------------------------------------------

#: --debug 时打印未预期异常堆栈（由 main 回调设置）
_DEBUG_ENABLED = False


# -- 错误处理 ---------------------------------------------------------------

def _guard(func: Callable) -> Callable:
    """统一错误处理：SmartNoteGenError -> 退出码；其余 -> 退出码 1。"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except typer.Exit:
            raise
        except SmartNoteGenError as exc:
            if _DEBUG_ENABLED:
                logger.exception("预期错误 [%s]: %s", exc.code, exc)
            else:
                logger.error("错误 [%s]: %s", exc.code, exc)
            typer.echo(f"错误 [{exc.code}]: {exc}", err=True)
            raise typer.Exit(exc.code) from exc
        except Exception as exc:
            if _DEBUG_ENABLED:
                logger.exception("unexpected error")
            else:
                logger.error("unexpected error: %s", exc)
            typer.echo(f"意外错误: {exc}", err=True)
            raise typer.Exit(1) from exc

    return wrapper


def set_debug(enabled: bool) -> None:
    """设置 DEBUG 模式（由 main 回调调用）。"""
    global _DEBUG_ENABLED
    _DEBUG_ENABLED = enabled


# -- 配置加载 ---------------------------------------------------------------

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
    """当 --style 显式提供时，将风格预设注入 request。"""
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
    """按合并优先级构造 GenerationRequest。"""
    merged = cfg.merge_cli(
        chords=chords, bpm=bpm, key=key, time_signature=time_signature,
        bars=bars, style=style, seed=seed, with_drums=with_drums,
        tracks=tracks, voice_leading=voice_leading,
        counterpoint=counterpoint, inversion=inversion, rhythm_pattern=rhythm,
    )
    d = merged.defaults
    request = GenerationRequest(
        chords=d.chords, bpm=d.bpm, key=d.key, time_signature=d.time_signature,
        bars=d.bars, style=d.style, seed=merged.random.seed,
        tracks=list(d.tracks), with_drums=d.with_drums,
        enable_voice_leading=d.voice_leading,
        enable_counterpoint=d.counterpoint,
        enable_inversion=d.inversion, rhythm_pattern=d.rhythm_pattern,
    )
    request = _apply_style_preset(
        request, cfg,
        style_explicit=style is not None,
        bpm_explicit=bpm, chords_explicit=chords, rhythm_explicit=rhythm,
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
        duration=duration, format=format,
        sample_rate=sample_rate, bit_depth=bit_depth, fade_ms=fade_ms,
    )
    e = merged.export
    return ExportOptions(
        duration=e.duration, format=e.format,
        sample_rate=e.sample_rate, bit_depth=e.bit_depth, fade_ms=e.fade_ms,
    )


def _write_single_metadata(
    cfg: Config,
    command: str,
    seed: Optional[int],
    artifacts: List[ArtifactMeta],
    project: Optional[str] = None,
    output_dir: Optional[str | Path] = None,
) -> None:
    """单次生成命令的元数据落盘。"""
    if not cfg.output.metadata:
        return
    om = OutputManager(cfg, project=project, output_dir=output_dir)
    om.write_metadata(
        RunMeta(
            command=command, seed=seed,
            started_at=datetime.now().isoformat(timespec="seconds"),
            duration_s=0.0, version=__version__,
            config_path=str(cfg.config_path) if cfg.config_path else None,
        ),
        artifacts,
    )


# -- 医生诊断 ---------------------------------------------------------------

def _doctor_item(name: str, status: str) -> None:
    """打印一行诊断项。"""
    typer.echo(f"  {name:<12} {status}")


# -- 版本对比 ---------------------------------------------------------------

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


# -- 交互式提示 -------------------------------------------------------------

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


def _config_prompt(label: str, default: str, choices: Optional[list[str]] = None) -> str:
    """配置向导提示输入。"""
    choices_hint = f" ({', '.join(choices)})" if choices else ""
    val = input(f"  {label}{choices_hint} [{default}]: ").strip()
    if not val:
        return default
    if choices and val not in choices:
        typer.echo(f"  ⚠️ 可选值: {', '.join(choices)}，使用默认值 {default}")
        return default
    return val


def _apply_detected_to_config(target: Path, detected: dict[str, str]) -> None:
    """将检测到的路径/参数写入配置文件（就地修改 TOML 文本）。"""
    import re
    content = target.read_text(encoding="utf-8")
    replacements = {
        "soundfont": detected.get("soundfont"),
        "soundfont_backup": detected.get("soundfont_backup"),
        "fluidsynth": detected.get("fluidsynth"),
        "project": detected.get("project"),
        "style": detected.get("style"),
        "bpm": detected.get("bpm"),
    }
    lines = content.splitlines()
    out_lines = []
    for line in lines:
        replaced = False
        for key, val in replacements.items():
            if val is None:
                continue
            pat = rf'^\s*{re.escape(key)}\s*='
            if re.match(pat, line):
                if key in ("bpm",):
                    out_lines.append(f"{key} = {val}")
                else:
                    safe_val = str(val).replace("\\", "\\\\")
                    out_lines.append(f'{key} = "{safe_val}"')
                replaced = True
                break
        if not replaced:
            out_lines.append(line)
    target.write_text("\n".join(out_lines) + "\n", encoding="utf-8")