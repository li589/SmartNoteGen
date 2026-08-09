"""预设风格库（P2-4）：StylePreset + StyleRegistry。

内置 4 基线：流行/摇滚/电子/古典（TOML 位于 styles/presets/）。
自定义注册：`styles/<name>.toml|json`（[styles] dir / search_paths 或 --style-file）。

字段（完整无缺失默认值）：
    name / bpm_range / instruments(轨道->GM Program) / rhythm_pattern(引用 RhythmPatternRegistry)
    / melody_profile / chord_preference / dsp_defaults
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from smartnotegen.exceptions import ParameterError
from smartnotegen.logging_setup import get_logger

logger = get_logger("styles")


class StyleError(ParameterError):
    """风格错误：未知风格/非法风格文件（错误码 1）。"""


@dataclass
class StylePreset:
    """一个风格预设。"""

    name: str
    bpm_range: Tuple[int, int] = (100, 128)
    instruments: Dict[str, int] = field(default_factory=dict)
    rhythm_pattern: str = ""
    melody_profile: Dict = field(default_factory=dict)
    chord_preference: List[str] = field(default_factory=list)
    dsp_defaults: Dict = field(default_factory=dict)

    def validate(self) -> None:
        """字段完整性校验：非法字段抛 StyleError(1)。"""
        if not self.name or not str(self.name).strip():
            raise StyleError("风格 name 不能为空", code=1)
        lo, hi = self.bpm_range
        if not (20 <= lo <= hi <= 300):
            raise StyleError(f"风格 {self.name} 的 bpm_range 非法: {(lo, hi)}", code=1)
        for track, program in self.instruments.items():
            if not (0 <= int(program) <= 127):
                raise StyleError(
                    f"风格 {self.name} 的乐器号非法（{track}={program}，应为 0-127）", code=1
                )
        if not self.rhythm_pattern:
            raise StyleError(f"风格 {self.name} 缺少 rhythm_pattern 字段", code=1)


class StyleRegistry:
    """风格注册表：内置 + 自定义。"""

    BUILTIN_NAMES: Tuple[str, ...] = ("pop", "rock", "electronic", "classical")

    def __init__(self, extra_dirs: Optional[List[Path]] = None) -> None:
        """初始化并加载内置 + 扩展目录风格。

        Args:
            extra_dirs: 自定义风格目录列表（*.toml / *.json）。
        """
        self._extra_dirs = [Path(d) for d in (extra_dirs or [])]
        self._presets: Dict[str, StylePreset] = {}
        self._load_builtin()
        self._load_extra()

    @staticmethod
    def _builtin_dir() -> Path:
        return Path(__file__).resolve().parent / "presets"

    def _load_builtin(self) -> None:
        d = self._builtin_dir()
        for name in self.BUILTIN_NAMES:
            p = d / f"{name}.toml"
            if p.is_file():
                preset = self._parse(p)
                self._presets[preset.name] = preset

    def _load_extra(self) -> None:
        for d in self._extra_dirs:
            if not Path(d).is_dir():
                continue
            for p in sorted(Path(d).glob("*.toml")) + sorted(Path(d).glob("*.json")):
                try:
                    preset = self._parse(p)
                    self._presets[preset.name] = preset
                except StyleError as exc:
                    logger.warning("跳过非法风格文件 %s: %s", p, exc)

    def _parse(self, path: str | Path) -> StylePreset:
        """解析 TOML/JSON 风格文件。"""
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise StyleError(f"风格文件不存在: {p}", code=1)
        try:
            if p.suffix.lower() == ".json":
                data = json.loads(p.read_text(encoding="utf-8"))
            else:
                with p.open("rb") as f:
                    data = tomllib.load(f)
        except Exception as exc:
            raise StyleError(f"解析风格文件失败: {p} ({exc})", code=1) from exc
        if not isinstance(data, dict):
            raise StyleError(f"风格文件格式非法（应为表/对象）: {p}", code=1)
        preset = StylePreset(
            name=str(data.get("name", p.stem)),
            bpm_range=tuple(int(x) for x in data.get("bpm_range", [100, 128])),
            instruments={
                str(k): int(v) for k, v in data.get("instruments", {}).items()
            },
            rhythm_pattern=str(data.get("rhythm_pattern", "")),
            melody_profile=dict(data.get("melody_profile", {})),
            chord_preference=[str(c) for c in data.get("chord_preference", [])],
            dsp_defaults=dict(data.get("dsp_defaults", {})),
        )
        preset.validate()
        return preset

    def get(self, name: str) -> StylePreset:
        """按名获取风格；未知 -> StyleError(1)。"""
        if name not in self._presets:
            raise StyleError(
                f"未知风格: {name!r}（内置: {', '.join(self.BUILTIN_NAMES)}；"
                f"可通过 styles/ 目录注册自定义风格）",
                code=1,
            )
        return self._presets[name]

    def load_all(self) -> Dict[str, StylePreset]:
        """返回全部已加载风格（副本）。"""
        return dict(self._presets)

    def register(self, path: str | Path) -> StylePreset:
        """注册单个自定义风格文件（TOML/JSON）。"""
        preset = self._parse(path)
        self._presets[preset.name] = preset
        return preset
