"""视频生成器主入口（v0.2.0 W1+W2+W3）。

整合分析、渲染、构图逻辑，提供统一的 video() 函数。
双引擎路由 + 背景/文字链路 + 标题卡。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from videomaker.analysis import analyze, analyze_multitrack
from videomaker.compositor import Compositor
from videomaker.config import Config
from videomaker.output_manager import (
    VideoArtifactMeta,
    VideoOutputManager,
    VideoRunMeta,
)
from videomaker.presets import resolve_preset


@dataclass
class VideoResult:
    """视频生成结果。"""
    output_path: str
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    fps: int = 0
    visual_style: str = ""
    preset: str = ""


def video(
    audio_path: str,
    output_path: Optional[str] = None,
    *,
    config: Optional[Config] = None,
    preset: str = "douyin",
    visual_style: str = "waveform",
    title: str = "",
    subtitle: str = "",
    chords: str = "",
    bpm: int = 0,
    seed: Optional[int] = None,
    style: str = "",
    width: Optional[int] = None,
    height: Optional[int] = None,
    fps: Optional[int] = None,
    score_midi: Optional[str] = None,
    tempo_grid: bool = False,
    notation: str = "staff",
) -> VideoResult:
    """生成音乐视频（双引擎路由；v0.3 支持多轨输入）。

    Args:
        audio_path: 音频文件路径（WAV/MP3/FLAC/OGG/MIDI）。
        output_path: 输出视频路径（None 由 OutputManager 规划）。
        config: 配置对象（None 加载默认）。
        preset: 平台预设（douyin/youtube/instagram/official）。
        visual_style: 视觉效果（waveform/spectrum/circular_spectrum/reactive/
            tracks/waveform_scroll/score）。
        title: 标题文字（前 3s 淡入淡出叠加）。
        subtitle: 副标题文字。
        chords: 和弦进行（元数据记录用）。
        bpm: BPM（元数据记录用）。
        seed: 随机种子（元数据记录用）。
        style: 风格名（元数据记录用）。
        score_midi: score 样式的谱面 MIDI 路径（None 时输入音频本身
            为 .mid 则直接用；否则报 RenderError）。
        tempo_grid: 用测速 BPM 绘制节拍网格并标注 BPM（score 样式）。
        notation: score 样式记谱法（staff=五线谱 / jianpu=简谱）。

    Returns:
        VideoResult 实例。
    """
    # 多轨输入：路径含列表分隔符或传入多文件时走 mix 入口

    # 1. 加载配置
    cfg = config or Config.load()

    # 2. 应用预设 + 显式覆盖
    preset_cfg = resolve_preset(preset)
    cfg.video.width = width or preset_cfg["width"]
    cfg.video.height = height or preset_cfg["height"]
    cfg.video.fps = fps or preset_cfg["fps"]

    # 3. 标题默认值（official 预设且未指定时用文件名）
    if not title and preset == "official":
        title = Path(audio_path).stem

    # 4. 分析音频（元数据用；时长/特征）——支持 MIDI/MP3 多格式
    from videomaker.audio_io import load_audio
    loaded = load_audio(audio_path)
    analysis = analyze(loaded, fps=cfg.video.fps)
    del loaded  # 释放

    # 5. 输出路径规划
    output_mgr = VideoOutputManager(cfg)
    if output_path is None:
        seq = output_mgr.next_seq(style or preset, bpm or 0, seed)
        output_path = str(output_mgr.plan_path(
            style=style or preset,
            bpm=bpm or 0,
            seed=seed,
            seq=seq,
        ))
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    # 6. 渲染（双引擎路由 + 背景 + 文字）
    #    ffmpeg 引擎直接吃音频文件（MIDI 已在临时 WAV，路径见下）
    compositor = Compositor(cfg)
    render_audio = _prepare_render_audio(audio_path, out_p.parent)

    # 6.5 score 样式装配（#14）：谱面数据 + 可选节拍网格
    visualizer_extra: dict = {}
    if visual_style == "score":
        from videomaker.exceptions import RenderError

        midi_src = score_midi
        if midi_src is None:
            from videomaker.audio_io import detect_format
            if detect_format(audio_path) == "midi":
                midi_src = audio_path
        if not midi_src:
            raise RenderError(
                "style=score 需要 MIDI 谱面数据：输入音频非 .mid 时请用 "
                "--score-midi 指定对应的 MIDI 文件"
            )
        from smartnotegen.score import Score

        score_obj = Score.from_midi(midi_src)
        bpm_scroll = None
        beat_times = None
        if tempo_grid:
            from smartnotegen.analysis.tempo import beat_grid, estimate_bpm

            est = estimate_bpm(render_audio)
            beat_times = beat_grid(analysis.duration_s, est.bpm, est.beat_offset)
            bpm_scroll = est.bpm
        visualizer_extra = dict(
            score=score_obj,
            beat_times=beat_times,
            bpm=bpm_scroll,
            notation=notation if notation in ("staff", "jianpu") else "staff",
        )

    result_path = compositor.compose(
        render_audio,
        str(out_p),
        visual_style=visual_style,
        title=title,
        subtitle=subtitle,
        visualizer_extra=visualizer_extra,
    )

    # 7. 元数据落盘
    try:
        import videomaker
        version = videomaker.__version__
    except Exception:
        version = ""
    artifact = VideoArtifactMeta(
        path=str(Path(result_path).resolve()),
        kind="video",
        params={
            "preset": preset,
            "visual_style": visual_style,
            "chords": chords,
            "bpm": bpm,
            "seed": seed,
            "style": style,
            "title": title,
            "score_midi": score_midi,
            "tempo_grid": tempo_grid,
            "notation": notation,
        },
        seed=seed,
        duration_s=analysis.duration_s,
        width=cfg.video.width,
        height=cfg.video.height,
        fps=cfg.video.fps,
        audio_path=str(Path(audio_path).resolve()),
    )
    output_mgr.write_metadata(
        VideoRunMeta(
            command=f"videomaker render {audio_path} --preset {preset} --style {visual_style}",
            seed=seed,
            started_at=datetime.now().isoformat(timespec="seconds"),
            duration_s=analysis.duration_s,
            version=version,
        ),
        [artifact],
    )

    return VideoResult(
        output_path=result_path,
        duration_s=analysis.duration_s,
        width=cfg.video.width,
        height=cfg.video.height,
        fps=cfg.video.fps,
        visual_style=visual_style,
        preset=preset,
    )


# ---------------------------------------------------------------------------
# 多轨入口（v0.3）
# ---------------------------------------------------------------------------

def _prepare_render_audio(audio_path: str, work_dir: Path) -> str:
    """为 ffmpeg 引擎准备可直读的音频文件。

    WAV/MP3/FLAC/OGG 原样返回；MIDI 渲染为临时 WAV（保留至视频生成后，
    由调用方在 finally 清理）。
    """
    from videomaker.audio_io import detect_format

    if detect_format(audio_path) != "midi":
        return audio_path

    from videomaker.audio_io import load_audio
    result = load_audio(audio_path, keep_rendered_wav=True)
    return result.rendered_wav or audio_path


def video_multitrack(
    tracks,
    output_path: Optional[str] = None,
    *,
    config: Optional[Config] = None,
    preset: str = "douyin",
    visual_style: str = "tracks",
    title: str = "",
    subtitle: str = "",
    bpm: int = 0,
    seed: Optional[int] = None,
    style: str = "",
    save_mix_wav: bool = True,
) -> VideoResult:
    """多轨音乐视频（v0.3）：混音 + 分轨可视化。

    Args:
        tracks: 轨道列表。元素为文件路径字符串（可带 ":gain=..:pan=.."），
            或 TrackSpec 实例。支持 WAV/MP3/FLAC/OGG/MIDI 混用。
        output_path: 输出视频路径（None 自动规划）。
        config: 配置。
        preset: 平台预设。
        visual_style: 视觉效果（tracks 为分轨；也可 circular_spectrum 等，
            此时用混音单轨分析）。
        title/subtitle: 标题。
        bpm/seed/style: 元数据。
        save_mix_wav: 保存混音 WAV（与视频同目录，供发布复用）。

    Returns:
        VideoResult。
    """
    from videomaker.mixer import TrackSpec, mix_tracks

    if isinstance(tracks, str):
        tracks = [tracks]
    specs = [t if isinstance(t, TrackSpec) else TrackSpec.parse(t) for t in tracks]
    if len(specs) == 1:
        # 单轨直接走单文件入口
        return video(
            specs[0].path, output_path,
            config=config, preset=preset, visual_style=visual_style,
            title=title, subtitle=subtitle, bpm=bpm, seed=seed, style=style,
        )

    cfg = config or Config.load()
    preset_cfg = resolve_preset(preset)
    cfg.video.width = preset_cfg["width"]
    cfg.video.height = preset_cfg["height"]
    cfg.video.fps = preset_cfg["fps"]

    if not title and preset == "official":
        title = " / ".join(Path(s.path).stem for s in specs[:3])

    # 1. 混音（重采样/对齐/增益/声像/归一化）
    output_mgr = VideoOutputManager(cfg)
    if output_path is None:
        seq = output_mgr.next_seq(style or preset, bpm or 0, seed)
        output_path = str(output_mgr.plan_path(
            style=style or preset, bpm=bpm or 0, seed=seed, seq=seq,
        ))
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    mix_wav_path = out_p.with_suffix(".mix.wav") if save_mix_wav else None
    mix = mix_tracks(specs, target_sr=44100, save_wav=str(mix_wav_path) if mix_wav_path else None)

    # 2. 多轨分析（主轨=混音，track_*=逐轨）
    analysis = analyze_multitrack(mix, fps=cfg.video.fps)

    # 3. 渲染（ffmpeg 引擎吃混音 WAV；PIL 引擎吃注入的 analysis）
    compositor = Compositor(cfg)
    render_audio = str(mix_wav_path) if mix_wav_path else audio_fallback(specs, out_p.parent)
    result_path = compositor.compose(
        render_audio,
        str(out_p),
        visual_style=visual_style,
        title=title,
        subtitle=subtitle,
        analysis=analysis,
    )

    # 4. 元数据
    try:
        import videomaker as _vm
        version = _vm.__version__
    except Exception:
        version = ""
    artifact = VideoArtifactMeta(
        path=str(Path(result_path).resolve()),
        kind="video",
        params={
            "preset": preset,
            "visual_style": visual_style,
            "tracks": [s.path for s in specs],
            "track_gains": [s.gain for s in specs],
            "track_pans": [s.pan for s in specs],
            "title": title,
            "mix_wav": str(mix_wav_path) if mix_wav_path else None,
        },
        seed=seed,
        duration_s=analysis.duration_s,
        width=cfg.video.width,
        height=cfg.video.height,
        fps=cfg.video.fps,
        audio_path=str(mix_wav_path) if mix_wav_path else render_audio,
    )
    output_mgr.write_metadata(
        VideoRunMeta(
            command=f"videomaker multi-track ({len(specs)} tracks) --preset {preset} --style {visual_style}",
            seed=seed,
            started_at=datetime.now().isoformat(timespec="seconds"),
            duration_s=analysis.duration_s,
            version=version,
        ),
        [artifact],
    )

    return VideoResult(
        output_path=result_path,
        duration_s=analysis.duration_s,
        width=cfg.video.width,
        height=cfg.video.height,
        fps=cfg.video.fps,
        visual_style=visual_style,
        preset=preset,
    )


def audio_fallback(specs, work_dir: Path) -> str:
    """无 save_mix_wav 时的兜底音频路径（ffmpeg 引擎需要）。"""
    return specs[0].path
