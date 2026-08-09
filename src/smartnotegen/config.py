"""配置体系：Config dataclass + load / merge_cli / write_template。

配置合并优先级（低 -> 高）：
    内置默认值 < config/default.toml < 用户配置文件（--config 指定，或项目根 smartnotegen.toml）
    < CLI 参数（merge_cli）

所有路径统一使用 pathlib.Path；输出路径由 cli.py 统一解析为绝对路径。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import tomli_w

from smartnotegen.exceptions import ConfigError

# ---------------------------------------------------------------------------
# 内置默认值（代码内的最终兜底）
#
# 兼容性说明：内置默认 soundfont/fluidsynth 保持 P0 的 legacy 表达
# （assets/... 与 PATH 查找），而 config/default.toml 提供 module/ 相对路径
# （M-1a）。这样在无 config/default.toml 的环境（如测试临时目录）行为与 P0 一致，
# 从项目根运行时则读取 config/default.toml 使用真实 module 路径。
# ---------------------------------------------------------------------------

DEFAULT_PATHS = {
    "module_dir": "module",
    "soundfont": "assets/soundfonts/GeneralUser_GS_v1.471.sf2",
    "fluidsynth": "fluidsynth",
    "soundfont_backup": "module/GeneralUser_GS/ColomboGMGS2_SF2/ColomboGMGS2.sf2",
    "output_dir": "output",
}

DEFAULT_DEFAULTS = {
    "bpm": 120,
    "key": "C major",
    "time_signature": "4/4",
    "bars": 8,
    "chords": "C-G-Am-F",
    "style": "pop",
    "tracks": ["chords", "melody", "bass"],
    "with_drums": False,
    # P2-2 乐理规则（全部默认关闭，不破坏 P0 输出）
    "voice_leading": False,
    "counterpoint": False,
    "inversion": False,
    "rhythm_pattern": None,
}

DEFAULT_EXPORT = {
    "format": "wav",
    "sample_rate": 44100,
    "bit_depth": 16,
    "duration": 25,
    "fade_ms": 50,
}

DEFAULT_RANDOM = {"seed": None}

DEFAULT_OUTPUT = {
    "layout": "project-date",  # project-date | legacy
    "project": "default",
    "naming": "{style}_{bpm}_{seed}_{seq}",
    "metadata": True,
}

DEFAULT_DSP = {
    "normalize_dbfs": -1.0,
    "fade_in_ms": 100.0,
    "fade_out_ms": 300.0,
    "eq": False,
    "eq_low_cut_hz": 30.0,
    "compressor": False,
    "compressor_ratio": 2.0,
    "compressor_threshold_db": -12.0,
    "reverb": False,
}

DEFAULT_STYLES = {
    "dir": "styles",
    "search_paths": [],
}

DEFAULT_AI = {
    "device": "cuda",
    "model_size": "medium",
    "diffrhythm_chunked": True,
}


# ---------------------------------------------------------------------------
# 子配置 dataclass
# ---------------------------------------------------------------------------

@dataclass
class PathsConfig:
    """路径相关配置。"""

    module_dir: str = DEFAULT_PATHS["module_dir"]
    soundfont: str = DEFAULT_PATHS["soundfont"]
    fluidsynth: str = DEFAULT_PATHS["fluidsynth"]
    soundfont_backup: str = DEFAULT_PATHS["soundfont_backup"]
    output_dir: str = DEFAULT_PATHS["output_dir"]


@dataclass
class DefaultsConfig:
    """生成默认参数（含 P2-2 乐理规则开关，默认关闭）。"""

    bpm: int = DEFAULT_DEFAULTS["bpm"]
    key: str = DEFAULT_DEFAULTS["key"]
    time_signature: str = DEFAULT_DEFAULTS["time_signature"]
    bars: int = DEFAULT_DEFAULTS["bars"]
    chords: str = DEFAULT_DEFAULTS["chords"]
    style: str = DEFAULT_DEFAULTS["style"]
    tracks: list[str] = field(default_factory=lambda: list(DEFAULT_DEFAULTS["tracks"]))
    with_drums: bool = DEFAULT_DEFAULTS["with_drums"]
    voice_leading: bool = DEFAULT_DEFAULTS["voice_leading"]
    counterpoint: bool = DEFAULT_DEFAULTS["counterpoint"]
    inversion: bool = DEFAULT_DEFAULTS["inversion"]
    rhythm_pattern: Optional[str] = DEFAULT_DEFAULTS["rhythm_pattern"]


@dataclass
class ExportConfig:
    """Suno 合规导出参数。"""

    format: str = DEFAULT_EXPORT["format"]
    sample_rate: int = DEFAULT_EXPORT["sample_rate"]
    bit_depth: int = DEFAULT_EXPORT["bit_depth"]
    duration: int = DEFAULT_EXPORT["duration"]
    fade_ms: int = DEFAULT_EXPORT["fade_ms"]


@dataclass
class RandomConfig:
    """随机性配置。seed=None 表示不固定。"""

    seed: Optional[int] = DEFAULT_RANDOM["seed"]


@dataclass
class OutputConfig:
    """输出管理（P2-5）：目录布局、项目名、命名模板、元数据开关。"""

    layout: str = DEFAULT_OUTPUT["layout"]
    project: str = DEFAULT_OUTPUT["project"]
    naming: str = DEFAULT_OUTPUT["naming"]
    metadata: bool = DEFAULT_OUTPUT["metadata"]


@dataclass
class DspConfig:
    """DSP 参数（P2-1）。默认：归一化 -1dBFS、淡入淡出 100/300ms、EQ/压缩/混响关。"""

    normalize_dbfs: float = DEFAULT_DSP["normalize_dbfs"]
    fade_in_ms: float = DEFAULT_DSP["fade_in_ms"]
    fade_out_ms: float = DEFAULT_DSP["fade_out_ms"]
    eq: bool = DEFAULT_DSP["eq"]
    eq_low_cut_hz: float = DEFAULT_DSP["eq_low_cut_hz"]
    compressor: bool = DEFAULT_DSP["compressor"]
    compressor_ratio: float = DEFAULT_DSP["compressor_ratio"]
    compressor_threshold_db: float = DEFAULT_DSP["compressor_threshold_db"]
    reverb: bool = DEFAULT_DSP["reverb"]


@dataclass
class StylesConfig:
    """自定义风格注册（P2-4）。"""

    dir: str = DEFAULT_STYLES["dir"]
    search_paths: list[str] = field(default_factory=lambda: list(DEFAULT_STYLES["search_paths"]))


@dataclass
class AiConfig:
    """AI 参数（P1-1/P1-2，二期实现）。"""

    device: str = DEFAULT_AI["device"]
    model_size: str = DEFAULT_AI["model_size"]
    diffrhythm_chunked: bool = DEFAULT_AI["diffrhythm_chunked"]


# ---------------------------------------------------------------------------
# 顶层 Config
# ---------------------------------------------------------------------------

#: CLI 覆盖参数 -> (section, field) 映射。merge_cli 使用。
_CLI_OVERRIDE_MAP: dict[str, tuple[str, str]] = {
    # defaults
    "bpm": ("defaults", "bpm"),
    "key": ("defaults", "key"),
    "time_signature": ("defaults", "time_signature"),
    "bars": ("defaults", "bars"),
    "chords": ("defaults", "chords"),
    "style": ("defaults", "style"),
    "tracks": ("defaults", "tracks"),
    "with_drums": ("defaults", "with_drums"),
    "voice_leading": ("defaults", "voice_leading"),
    "counterpoint": ("defaults", "counterpoint"),
    "inversion": ("defaults", "inversion"),
    "rhythm_pattern": ("defaults", "rhythm_pattern"),
    # paths
    "module_dir": ("paths", "module_dir"),
    "soundfont": ("paths", "soundfont"),
    "fluidsynth": ("paths", "fluidsynth"),
    "soundfont_backup": ("paths", "soundfont_backup"),
    "output_dir": ("paths", "output_dir"),
    # export
    "format": ("export", "format"),
    "sample_rate": ("export", "sample_rate"),
    "bit_depth": ("export", "bit_depth"),
    "duration": ("export", "duration"),
    "fade_ms": ("export", "fade_ms"),
    # random
    "seed": ("random", "seed"),
    # output (P2-5)
    "layout": ("output", "layout"),
    "project": ("output", "project"),
    "naming": ("output", "naming"),
    "metadata": ("output", "metadata"),
    # dsp (P2-1)
    "normalize_dbfs": ("dsp", "normalize_dbfs"),
    "fade_in_ms": ("dsp", "fade_in_ms"),
    "fade_out_ms": ("dsp", "fade_out_ms"),
    "eq": ("dsp", "eq"),
    "eq_low_cut_hz": ("dsp", "eq_low_cut_hz"),
    "compressor": ("dsp", "compressor"),
    "compressor_ratio": ("dsp", "compressor_ratio"),
    "compressor_threshold_db": ("dsp", "compressor_threshold_db"),
    "reverb": ("dsp", "reverb"),
    # styles (P2-4)
    "styles_dir": ("styles", "dir"),
    "styles_search_paths": ("styles", "search_paths"),
    # ai (P1-1/P1-2)
    "device": ("ai", "device"),
    "model_size": ("ai", "model_size"),
    "diffrhythm_chunked": ("ai", "diffrhythm_chunked"),
}

#: 合法 section 集合（_merge_dict 校验用）
_VALID_SECTIONS = {"paths", "defaults", "export", "random", "output", "dsp", "styles", "ai"}


@dataclass
class Config:
    """合并后的生效配置。由 CLI 加载后逐层传递给各模块。"""

    paths: PathsConfig = field(default_factory=PathsConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    export: ExportConfig = field(default_factory=ExportConfig)
    random: RandomConfig = field(default_factory=RandomConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    dsp: DspConfig = field(default_factory=DspConfig)
    styles: StylesConfig = field(default_factory=StylesConfig)
    ai: AiConfig = field(default_factory=AiConfig)
    #: 最终生效的用户配置文件路径（可能为空）
    config_path: Optional[Path] = None

    # -- 加载 -------------------------------------------------------------

    @classmethod
    def load(cls, path: Optional[str | Path] = None) -> "Config":
        """加载配置：内置默认 < config/default.toml < 用户配置文件。

        Args:
            path: 用户显式指定的配置文件（--config）。为 None 时按约定查找
                项目根下的 smartnotegen.toml。

        Returns:
            合并后的 Config 实例。

        Raises:
            ConfigError: 显式指定文件不存在或 TOML 解析失败。
        """
        cfg = cls()  # 内置默认

        # 第 1 层：config/default.toml（若存在）
        # 兼容性说明：沿用 P0 的 CWD 查找（而非 ProjectRootResolver 向上探测），
        # 保证 pytest 临时目录（位于项目根 .pytest_tmp 下）不会被误判为项目根。
        default_template = Path.cwd() / "config" / "default.toml"
        if default_template.is_file():
            cfg = cfg._merge_dict(_load_toml(default_template), source="config/default.toml")

        # 第 2 层：用户配置文件
        user_cfg_path: Optional[Path] = None
        if path is not None:
            user_cfg_path = Path(path).expanduser().resolve()
            if not user_cfg_path.is_file():
                raise ConfigError(f"配置文件不存在: {user_cfg_path}", code=2)
        else:
            candidate = Path.cwd() / "smartnotegen.toml"
            if candidate.is_file():
                user_cfg_path = candidate

        if user_cfg_path is not None:
            cfg = cfg._merge_dict(_load_toml(user_cfg_path), source=str(user_cfg_path))
            cfg.config_path = user_cfg_path

        cfg._validate()
        return cfg

    # -- CLI 覆盖 ---------------------------------------------------------

    def merge_cli(self, **overrides: Any) -> "Config":
        """按 CLI 参数覆盖配置，返回新实例（不修改自身）。

        Args:
            **overrides: 扁平化键值，如 merge_cli(bpm=140, soundfont="x.sf2")。

        Raises:
            ConfigError: 出现未知键或类型非法。
        """
        merged: dict[str, dict[str, Any]] = self.to_dict()
        for key, value in overrides.items():
            if value is None:
                continue  # 未提供的 CLI 参数保持原值
            if key not in _CLI_OVERRIDE_MAP:
                raise ConfigError(f"未知配置键: {key}", code=2)
            section, field_name = _CLI_OVERRIDE_MAP[key]
            merged.setdefault(section, {})[field_name] = value
        cfg = Config.from_dict(merged)
        cfg.config_path = self.config_path
        cfg._validate()
        return cfg

    # -- 模板写回 ---------------------------------------------------------

    def write_template(self, path: str | Path) -> str:
        """将当前配置写为带注释的 TOML 模板（config init 使用）。

        Args:
            path: 目标路径。

        Returns:
            写入的绝对路径字符串。
        """
        target = Path(path).expanduser().resolve()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as f:
                tomli_w.dump(self.to_dict(), f)
        except OSError as exc:  # pragma: no cover - 文件系统错误
            raise ConfigError(f"写入配置文件失败: {target} ({exc})", code=2) from exc
        return str(target)

    # -- 校验 -------------------------------------------------------------

    def _validate(self) -> None:
        """基本合法性校验（类型 + 取值范围）。"""
        d = self.defaults
        if not (1 <= d.bpm <= 400):
            raise ConfigError(f"bpm 超出合理范围 (1-400): {d.bpm}", code=2)
        if not (1 <= d.bars <= 64):
            raise ConfigError(f"bars 超出合理范围 (1-64): {d.bars}", code=2)
        e = self.export
        if e.sample_rate not in (8000, 16000, 22050, 24000, 44100, 48000, 96000):
            raise ConfigError(f"不支持的采样率: {e.sample_rate}", code=2)
        if e.bit_depth not in (8, 16, 24, 32):
            raise ConfigError(f"不支持的位深: {e.bit_depth}", code=2)
        if e.format not in ("wav", "mp3"):
            raise ConfigError(f"不支持的导出格式: {e.format}（可选 wav|mp3）", code=2)
        if self.output.layout not in ("project-date", "legacy"):
            raise ConfigError(f"不支持的输出布局: {self.output.layout}（可选 project-date|legacy）", code=2)
        if self.ai.device not in ("cuda", "cpu"):
            raise ConfigError(f"不支持的 AI 设备: {self.ai.device}（可选 cuda|cpu）", code=2)
        if self.ai.model_size not in ("medium", "small"):
            raise ConfigError(f"不支持的模型规格: {self.ai.model_size}（可选 medium|small）", code=2)
        # 注意：export.duration 的 [10,30] 合规校验由 SunoExporter 负责（错误码 5），
        # 不在配置层校验，以保证 `export suno --duration 35` 退出码为 5。

    # -- 序列化 -----------------------------------------------------------

    def to_dict(self) -> dict[str, dict[str, Any]]:
        """转为嵌套 dict（与 TOML schema 一致）。

        注意：TOML 无 null 类型，seed=None 时省略该键（读回时视为 None）。
        """
        d = {
            "paths": {
                "module_dir": self.paths.module_dir,
                "soundfont": self.paths.soundfont,
                "fluidsynth": self.paths.fluidsynth,
                "soundfont_backup": self.paths.soundfont_backup,
                "output_dir": self.paths.output_dir,
            },
            "defaults": {
                "bpm": self.defaults.bpm,
                "key": self.defaults.key,
                "time_signature": self.defaults.time_signature,
                "bars": self.defaults.bars,
                "chords": self.defaults.chords,
                "style": self.defaults.style,
                "tracks": list(self.defaults.tracks),
                "with_drums": self.defaults.with_drums,
                "voice_leading": self.defaults.voice_leading,
                "counterpoint": self.defaults.counterpoint,
                "inversion": self.defaults.inversion,
            },
            "export": {
                "format": self.export.format,
                "sample_rate": self.export.sample_rate,
                "bit_depth": self.export.bit_depth,
                "duration": self.export.duration,
                "fade_ms": self.export.fade_ms,
            },
            "random": {"seed": self.random.seed},
            "output": {
                "layout": self.output.layout,
                "project": self.output.project,
                "naming": self.output.naming,
                "metadata": self.output.metadata,
            },
            "dsp": {
                "normalize_dbfs": self.dsp.normalize_dbfs,
                "fade_in_ms": self.dsp.fade_in_ms,
                "fade_out_ms": self.dsp.fade_out_ms,
                "eq": self.dsp.eq,
                "eq_low_cut_hz": self.dsp.eq_low_cut_hz,
                "compressor": self.dsp.compressor,
                "compressor_ratio": self.dsp.compressor_ratio,
                "compressor_threshold_db": self.dsp.compressor_threshold_db,
                "reverb": self.dsp.reverb,
            },
            "styles": {
                "dir": self.styles.dir,
                "search_paths": list(self.styles.search_paths),
            },
            "ai": {
                "device": self.ai.device,
                "model_size": self.ai.model_size,
                "diffrhythm_chunked": self.ai.diffrhythm_chunked,
            },
        }
        if self.random.seed is None:
            d["random"].pop("seed", None)
        if self.defaults.rhythm_pattern is None:
            d["defaults"].pop("rhythm_pattern", None)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, dict[str, Any]]) -> "Config":
        """从嵌套 dict 构造 Config。"""
        paths_data = data.get("paths", {})
        defaults_data = data.get("defaults", {})
        export_data = data.get("export", {})
        random_data = data.get("random", {})
        output_data = data.get("output", {})
        dsp_data = data.get("dsp", {})
        styles_data = data.get("styles", {})
        ai_data = data.get("ai", {})

        paths = PathsConfig(
            module_dir=str(paths_data.get("module_dir", DEFAULT_PATHS["module_dir"])),
            soundfont=str(paths_data.get("soundfont", DEFAULT_PATHS["soundfont"])),
            fluidsynth=str(paths_data.get("fluidsynth", DEFAULT_PATHS["fluidsynth"])),
            soundfont_backup=str(
                paths_data.get("soundfont_backup", DEFAULT_PATHS["soundfont_backup"])
            ),
            output_dir=str(paths_data.get("output_dir", DEFAULT_PATHS["output_dir"])),
        )
        defaults = DefaultsConfig(
            bpm=int(defaults_data.get("bpm", DEFAULT_DEFAULTS["bpm"])),
            key=str(defaults_data.get("key", DEFAULT_DEFAULTS["key"])),
            time_signature=str(
                defaults_data.get("time_signature", DEFAULT_DEFAULTS["time_signature"])
            ),
            bars=int(defaults_data.get("bars", DEFAULT_DEFAULTS["bars"])),
            chords=str(defaults_data.get("chords", DEFAULT_DEFAULTS["chords"])),
            style=str(defaults_data.get("style", DEFAULT_DEFAULTS["style"])),
            tracks=[str(t) for t in defaults_data.get("tracks", DEFAULT_DEFAULTS["tracks"])],
            with_drums=bool(defaults_data.get("with_drums", DEFAULT_DEFAULTS["with_drums"])),
            voice_leading=bool(
                defaults_data.get("voice_leading", DEFAULT_DEFAULTS["voice_leading"])
            ),
            counterpoint=bool(defaults_data.get("counterpoint", DEFAULT_DEFAULTS["counterpoint"])),
            inversion=bool(defaults_data.get("inversion", DEFAULT_DEFAULTS["inversion"])),
            rhythm_pattern=(
                str(defaults_data["rhythm_pattern"])
                if defaults_data.get("rhythm_pattern") is not None
                else DEFAULT_DEFAULTS["rhythm_pattern"]
            ),
        )
        export = ExportConfig(
            format=str(export_data.get("format", DEFAULT_EXPORT["format"])),
            sample_rate=int(export_data.get("sample_rate", DEFAULT_EXPORT["sample_rate"])),
            bit_depth=int(export_data.get("bit_depth", DEFAULT_EXPORT["bit_depth"])),
            duration=int(export_data.get("duration", DEFAULT_EXPORT["duration"])),
            fade_ms=int(export_data.get("fade_ms", DEFAULT_EXPORT["fade_ms"])),
        )
        seed = random_data.get("seed", DEFAULT_RANDOM["seed"])
        random_cfg = RandomConfig(seed=None if seed is None else int(seed))
        output = OutputConfig(
            layout=str(output_data.get("layout", DEFAULT_OUTPUT["layout"])),
            project=str(output_data.get("project", DEFAULT_OUTPUT["project"])),
            naming=str(output_data.get("naming", DEFAULT_OUTPUT["naming"])),
            metadata=bool(output_data.get("metadata", DEFAULT_OUTPUT["metadata"])),
        )
        dsp = DspConfig(
            normalize_dbfs=float(dsp_data.get("normalize_dbfs", DEFAULT_DSP["normalize_dbfs"])),
            fade_in_ms=float(dsp_data.get("fade_in_ms", DEFAULT_DSP["fade_in_ms"])),
            fade_out_ms=float(dsp_data.get("fade_out_ms", DEFAULT_DSP["fade_out_ms"])),
            eq=bool(dsp_data.get("eq", DEFAULT_DSP["eq"])),
            eq_low_cut_hz=float(dsp_data.get("eq_low_cut_hz", DEFAULT_DSP["eq_low_cut_hz"])),
            compressor=bool(dsp_data.get("compressor", DEFAULT_DSP["compressor"])),
            compressor_ratio=float(
                dsp_data.get("compressor_ratio", DEFAULT_DSP["compressor_ratio"])
            ),
            compressor_threshold_db=float(
                dsp_data.get("compressor_threshold_db", DEFAULT_DSP["compressor_threshold_db"])
            ),
            reverb=bool(dsp_data.get("reverb", DEFAULT_DSP["reverb"])),
        )
        styles = StylesConfig(
            dir=str(styles_data.get("dir", DEFAULT_STYLES["dir"])),
            search_paths=[
                str(p) for p in styles_data.get("search_paths", DEFAULT_STYLES["search_paths"])
            ],
        )
        ai = AiConfig(
            device=str(ai_data.get("device", DEFAULT_AI["device"])),
            model_size=str(ai_data.get("model_size", DEFAULT_AI["model_size"])),
            diffrhythm_chunked=bool(
                ai_data.get("diffrhythm_chunked", DEFAULT_AI["diffrhythm_chunked"])
            ),
        )
        return cls(
            paths=paths,
            defaults=defaults,
            export=export,
            random=random_cfg,
            output=output,
            dsp=dsp,
            styles=styles,
            ai=ai,
        )

    def _merge_dict(self, data: dict[str, Any], source: str) -> "Config":
        """用单个 TOML dict 覆盖当前配置（保持其余字段不变）。"""
        unknown_sections = set(data.keys()) - _VALID_SECTIONS
        if unknown_sections:
            raise ConfigError(
                f"配置文件 [{source}] 含未知 section: {sorted(unknown_sections)}", code=2
            )
        merged = self.to_dict()
        for section, values in data.items():
            if not isinstance(values, dict):
                raise ConfigError(
                    f"配置文件 [{source}] 的 [{section}] 段格式非法（应为表）", code=2
                )
            merged.setdefault(section, {}).update(values)
        cfg = Config.from_dict(merged)
        cfg.config_path = self.config_path
        return cfg


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _load_toml(path: Path) -> dict[str, Any]:
    """读取 TOML 文件；失败时抛 ConfigError。"""
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"配置文件 TOML 解析失败: {path} ({exc})", code=2) from exc
    except OSError as exc:
        raise ConfigError(f"读取配置文件失败: {path} ({exc})", code=2) from exc


def build_output_path(
    output_dir: str | Path,
    style: str,
    key: str,
    bpm: int,
    bars: int,
    seed: Optional[int],
    ext: str,
    timestamp: Optional[str] = None,
    variant: Optional[int] = None,
    extra_suffix: Optional[str] = None,
) -> Path:
    """按架构 §7.3 命名规范构造输出路径（P0 legacy 命名，P2-5 兼容保留）。

    格式：output/{YYYYMMDD}/{style}_{key_nospace}_{bpm}_{bars}bars_{seed}_{ts}[_suno{ds}s][_v{n}].{ext}
    - seed 为 None 时使用 "demo"
    - 批量变体追加 _v{n}

    Args:
        output_dir: 输出根目录。
        style: 风格，如 "pop"。
        key: 调式，如 "C major"（空格会被移除）。
        bpm: 速度。
        bars: 小节数。
        seed: 随机种子（None -> demo）。
        ext: 扩展名（不含点），如 "mid" / "wav" / "mp3"。
        timestamp: HHMMSS 时间戳；None 时自动取当前时间。
        variant: 批量变体序号（P1-3）。
        extra_suffix: 附加后缀（如 "_suno25s"），追加在时间戳之后、扩展名之前。

    Returns:
        完整输出路径。
    """
    from datetime import datetime

    base = Path(output_dir).expanduser()
    date_dir = base / datetime.now().strftime("%Y%m%d")
    key_nospace = str(key).replace(" ", "")
    seed_str = "demo" if seed is None else str(seed)
    ts = timestamp or datetime.now().strftime("%H%M%S")
    stem = f"{style}_{key_nospace}_{bpm}_{bars}bars_{seed_str}_{ts}"
    if extra_suffix:
        stem = f"{stem}{extra_suffix}"
    if variant is not None:
        stem = f"{stem}_v{variant}"
    return date_dir / f"{stem}.{ext}"
