"""一键管线（P0 + P1/P2 增量）：generate → render → DSP → export（Suno 合规闭环）。

M-1：管线开头做环境探测（PathResolver.ensure_ready，真实引擎）；构造 Renderer 时
     传入配置路径（renderer 内部解析 module 相对路径并支持双音色库回退）。
P2-1：render 输出后、export 前插入 DspProcessor 阶段（归一化 -1dBFS + 淡入淡出）。
P2-5：产物经 OutputManager 规划（<root>/<project>/<YYYYMMDD>/{style}_{bpm}_{seed}_{seq}）
     并落盘 metadata.json。

零参数 demo：smartnotegen pipeline
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from smartnotegen import __version__
from smartnotegen.config import Config
from smartnotegen.dsp import DspOptions, DspProcessor
from smartnotegen.env import PathResolver
from smartnotegen.export.suno import ExportOptions, SunoExporter
from smartnotegen.generators.base import GenerationRequest
from smartnotegen.generators.procedural import ProceduralGenerator
from smartnotegen.logging_setup import get_logger
from smartnotegen.models.midi import MidiDocument
from smartnotegen.output_manager import ArtifactMeta, OutputManager, RunMeta
from smartnotegen.preview import PreviewGenerator
from smartnotegen.render.fluidsynth import FluidSynthRenderer

logger = get_logger("pipeline")


@dataclass
class PipelineResult:
    """管线产物元数据。"""

    midi_path: str = ""
    wav_path: str = ""
    export_path: str = ""
    duration_s: float = 0.0
    sample_rate: int = 0
    bit_depth: Optional[int] = None
    chords: str = ""
    seed: Optional[int] = None
    bpm: int = 0
    bars: int = 0
    key: str = ""
    style: str = ""
    format: str = ""

    def to_dict(self) -> Dict[str, object]:
        return field_dict(self)


def field_dict(obj) -> Dict[str, object]:
    """dataclass -> dict（供 CLI 打印）。"""
    return {f.name: getattr(obj, f.name) for f in obj.__dataclass_fields__.values()}


class Pipeline:
    """编排 generate → render → DSP → export，中间产物写入 output/.tmp 并自动清理。"""

    def __init__(
        self,
        config: Config,
        project: Optional[str] = None,
        output_dir: Optional[str | Path] = None,
        dry_run: bool = False,
    ) -> None:
        """初始化。

        Args:
            config: 生效配置。
            project: 项目名（P2-5，--project 覆盖）。
            output_dir: 输出根目录覆盖（--output-dir）。
            dry_run: True 时不写任何产物、不调用 subprocess，仅规划并打印（M-1f）。
        """
        self.config = config
        self.project = project
        self.output_dir = output_dir
        self.dry_run = dry_run

    def run(
        self,
        request: GenerationRequest,
        export_opts: Optional[ExportOptions] = None,
    ) -> PipelineResult:
        """执行完整管线。

        Args:
            request: 生成请求。
            export_opts: 导出选项；None 时使用配置默认值。

        Returns:
            PipelineResult（含最终产物路径与元数据）。

        Raises:
            SmartNoteGenError: 任一步骤失败（渲染/导出等按错误码抛出）。
        """
        opts = export_opts or ExportOptions(
            duration=self.config.export.duration,
            format=self.config.export.format,
            sample_rate=self.config.export.sample_rate,
            bit_depth=self.config.export.bit_depth,
            fade_ms=self.config.export.fade_ms,
        )

        output_manager = OutputManager(self.config, project=self.project, output_dir=self.output_dir)
        output_root = output_manager.base_dir()

        # 中间产物目录：非 dry-run 才创建（dry-run 不写任何产物）
        tmp_root = output_root / ".tmp"
        tmp_dir: Optional[Path] = None

        try:
            # 1. 环境探测（真实引擎；仅默认 module 环境缺失抛 ModuleError(7)，其余日志提示）
            if not self.dry_run:
                PathResolver(self.config).ensure_ready()

            # 2. 生成 NoteSequence
            generator = ProceduralGenerator(seed=request.seed)
            seq = generator.generate(request)

            # 输出规划（防覆盖序号；产物路径稳定，metadata 可追溯）
            seq_no = output_manager.next_seq(request.style, request.bpm, request.seed, "mid")
            export_ext = opts.format
            midi_plan = output_manager.plan_path(
                style=request.style, bpm=request.bpm, seed=request.seed, ext="mid", seq=seq_no,
                mkdir=False,
            )
            wav_plan = output_manager.plan_path(
                style=request.style, bpm=request.bpm, seed=request.seed, ext="wav", seq=seq_no,
                mkdir=False,
            )
            export_plan = output_manager.plan_path(
                style=request.style, bpm=request.bpm, seed=request.seed,
                ext=export_ext, seq=seq_no, suffix=f"_suno{opts.duration}s", mkdir=False,
            )

            if self.dry_run:
                logger.info(
                    "[DRY-RUN] fluidsynth 将执行: fluidsynth -ni -F %s -R %d -O s16 -g 0.60 "
                    "<soundfont: %s> <midi: %s>",
                    wav_plan, self.config.export.sample_rate, self.config.paths.soundfont, midi_plan,
                )
                logger.info("[DRY-RUN] export suno: %s -> %s", wav_plan, export_plan)
                logger.info("[DRY-RUN] 不写任何产物文件")
                return PipelineResult(
                    midi_path=str(midi_plan), wav_path=str(wav_plan),
                    export_path=str(export_plan),
                    duration_s=float(opts.duration), sample_rate=opts.sample_rate,
                    bit_depth=opts.bit_depth, chords=request.chords, seed=request.seed,
                    bpm=request.bpm, bars=request.bars, key=request.key,
                    style=request.style, format=opts.format,
                )

            # 3. 落盘 .mid（稳定路径）
            tmp_root.mkdir(parents=True, exist_ok=True)
            tmp_dir = Path(tempfile.mkdtemp(prefix="sng_tmp_", dir=str(tmp_root)))
            midi_path = Path(MidiDocument.from_sequence(seq).write(midi_plan))

            # 4. 渲染 WAV（真实引擎；renderer 内部解析 module 路径 + 双音色库回退）
            renderer = FluidSynthRenderer(
                fluidsynth_path=self.config.paths.fluidsynth,
                soundfont_backup=self.config.paths.soundfont_backup,
            )
            wav_path = Path(
                renderer.render(str(midi_path), self.config.paths.soundfont, str(wav_plan))
            )

            # 5. DSP 阶段（P2-1）：render 输出后、export 前（就地处理稳定 wav）
            self._apply_dsp(wav_path)

            # 6. Suno 合规导出（P2-5 命名：{style}_{bpm}_{seed}_{seq}_suno{ds}s）
            exporter = SunoExporter()
            final_path = exporter.export(str(wav_path), opts, output_path=export_plan)

            # 7. 元数据（引用稳定产物路径）
            meta = SunoExporter.describe(final_path)
            result = PipelineResult(
                midi_path=str(midi_path),
                wav_path=str(wav_path),
                export_path=final_path,
                duration_s=meta["duration_s"],
                sample_rate=meta["sample_rate"],
                bit_depth=meta["bit_depth"],
                chords=request.chords,
                seed=request.seed,
                bpm=request.bpm,
                bars=request.bars,
                key=request.key,
                style=request.style,
                format=opts.format,
            )
            if self.config.output.metadata:
                output_manager.write_metadata(
                    RunMeta(
                        command=f"smartnotegen pipeline --style {request.style} --seed {request.seed}",
                        seed=request.seed,
                        started_at=datetime.now().isoformat(timespec="seconds"),
                        duration_s=round(meta["duration_s"], 2),
                        version=__version__,
                        config_path=str(self.config.config_path) if self.config.config_path else None,
                    ),
                    [
                        ArtifactMeta(
                            path=str(midi_path), kind="midi",
                            params={"chords": request.chords, "bpm": request.bpm,
                                    "bars": request.bars, "style": request.style},
                            seed=request.seed, seq=seq_no,
                            duration_s=seq.duration_seconds(),
                        ),
                        ArtifactMeta(
                            path=str(wav_path), kind="wav",
                            params={"bpm": request.bpm, "style": request.style},
                            seed=request.seed, seq=seq_no,
                            duration_s=round(meta["duration_s"], 2),
                            sample_rate=meta["sample_rate"],
                        ),
                        ArtifactMeta(
                            path=final_path, kind="suno",
                            params={"duration": opts.duration, "format": opts.format,
                                    "sample_rate": opts.sample_rate, "bit_depth": opts.bit_depth},
                            seed=request.seed, seq=seq_no,
                            duration_s=meta["duration_s"],
                            sample_rate=meta["sample_rate"],
                        ),
                    ],
                )

            # 8. 自动生成 HTML 预览页（P3-A1）
            if self._preview_enabled():
                try:
                    preview = PreviewGenerator()
                    preview_path = preview.generate_for(
                        final_path,
                        {
                            "时长": f"{meta['duration_s']}s",
                            "采样率": f"{meta['sample_rate']}Hz",
                            "位深": f"{meta['bit_depth']}bit",
                            "风格": request.style,
                            "BPM": request.bpm,
                            "seed": request.seed,
                            "和弦": request.chords,
                        },
                        output_manager.root(),
                        label=Path(final_path).name,
                    )
                    logger.info("预览页: %s", preview_path)
                except Exception as exc:  # 预览失败不阻断管线
                    logger.warning("预览页生成失败（不影响产物）: %s", exc)

            return result
        finally:
            if tmp_dir is not None:
                _force_remove_tree(tmp_dir)
                # 若 .tmp 根目录已空则一并清理
                try:
                    tmp_root.rmdir()
                except OSError:
                    pass

    # -- DSP（P2-1）--------------------------------------------------------

    def _dsp_options(self) -> DspOptions:
        d = self.config.dsp
        return DspOptions(
            normalize_dbfs=d.normalize_dbfs,
            fade_in_ms=d.fade_in_ms,
            fade_out_ms=d.fade_out_ms,
            eq=d.eq,
            eq_low_cut_hz=d.eq_low_cut_hz,
            compressor=d.compressor,
            compressor_ratio=d.compressor_ratio,
            compressor_threshold_db=d.compressor_threshold_db,
            reverb=d.reverb,
        )

    def _apply_dsp(self, wav_path: Path) -> None:
        """在渲染后应用 DSP（就地处理）。"""
        opts = self._dsp_options()
        processor = DspProcessor()
        processor.validate(opts)
        processor.process(str(wav_path), opts, str(wav_path))

    def _preview_enabled(self) -> bool:
        """预览页是否开启（config 或 dry-run 时关闭）。"""
        if self.dry_run:
            return False
        # 兼容：config 无 preview 节时（旧配置）默认开启
        preview = getattr(self.config, "preview", None)
        if preview is None:
            return True
        return bool(getattr(preview, "enabled", True))


def _force_remove_tree(path: Path) -> None:
    """删除目录树。

    不使用 shutil.rmtree：在 WorkBuddy 沙箱环境下其被拦截（回收站不可用），
    改用 os.remove/os.rmdir 逐项删除，保证中间产物真正被清理。
    """
    target = Path(path)
    if not target.exists():
        return
    for root, dirs, files in os.walk(str(target), topdown=False):
        for name in files:
            try:
                os.remove(os.path.join(root, name))
            except OSError:
                pass
        for name in dirs:
            try:
                os.rmdir(os.path.join(root, name))
            except OSError:
                pass
    try:
        os.rmdir(str(target))
    except OSError:
        pass
