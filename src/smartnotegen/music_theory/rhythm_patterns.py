"""节奏型库（P2-2d）：内置 ≥6 种 + 用户自定义（字符串/JSON）。

网格约定：每个元素表示一个时间片（4/4 一拍半 8 分音符网格为 8 格），
1 = 有音头，0 = 无音头。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from smartnotegen.exceptions import InputFileError, ParameterError


@dataclass(frozen=True)
class RhythmPattern:
    """节奏型：半拍网格 0/1 序列。"""

    name: str
    grid: Tuple[int, ...]
    style_tags: Tuple[str, ...] = ()

    @property
    def density(self) -> str:
        """按网格密度推导节奏密度（sustain/half/eighth）。"""
        if not self.grid:
            return "sustain"
        onsets = sum(1 for g in self.grid if g)
        ratio = onsets / len(self.grid)
        if ratio >= 0.6:
            return "eighth"
        if ratio >= 0.35:
            return "half"
        return "sustain"

    def onsets_in_bar(self, beats_per_bar: float) -> List[float]:
        """返回一小节内的音头时刻（拍）。"""
        n = max(1, len(self.grid))
        step = beats_per_bar / n
        return [i * step for i, g in enumerate(self.grid) if g]


class RhythmPatternRegistry:
    """节奏型注册表：内置 + 用户扩展。"""

    #: 内置节奏型（≥6 种）
    BUILTIN: List[RhythmPattern] = [
        RhythmPattern("pop", (1, 0, 1, 0, 1, 1, 0, 0), ("pop",)),
        RhythmPattern("rock", (1, 0, 0, 1, 1, 0, 0, 1), ("rock",)),
        RhythmPattern("electronic", (1, 1, 1, 0, 1, 1, 1, 0), ("electronic",)),
        RhythmPattern("classical", (1, 0, 0, 0, 1, 0, 0, 0), ("classical",)),
        RhythmPattern("waltz", (1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0), ("waltz", "classical")),
        RhythmPattern("funk", (1, 0, 1, 1, 0, 1, 1, 0), ("funk", "pop")),
    ]

    def __init__(self, extra_patterns: Optional[Sequence[RhythmPattern]] = None) -> None:
        """初始化；extra_patterns 可注入自定义节奏型（测试/运行时扩展）。"""
        self._patterns: dict[str, RhythmPattern] = {
            p.name: p for p in list(self.BUILTIN) + list(extra_patterns or [])
        }

    def names(self) -> List[str]:
        """全部节奏型名（含自定义）。"""
        return list(self._patterns.keys())

    def get(self, name: str) -> RhythmPattern:
        """按名获取节奏型；未知 -> ParameterError(1)。"""
        if name not in self._patterns:
            raise ParameterError(
                f"未知节奏型: {name!r}（内置: {', '.join(self.names())}）", code=1
            )
        return self._patterns[name]

    @classmethod
    def from_string(cls, spec: str) -> RhythmPattern:
        """从 0/1 字符串构造自定义节奏型，如 "10010010"（8 半拍网格）。"""
        grid = tuple(1 if c == "1" else 0 for c in str(spec).strip() if c in "01")
        if not grid:
            raise ParameterError(f"非法节奏型字符串: {spec!r}（形如 '10010010'）", code=1)
        return RhythmPattern(name="custom", grid=grid, style_tags=("custom",))

    @classmethod
    def from_json(cls, path: str | Path) -> RhythmPattern:
        """从 JSON 文件注册自定义节奏型。

        JSON 格式：{"name": "mygroove", "grid": [1,0,1,0,1,1,0,0], "style_tags": ["pop"]}
        """
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise InputFileError(f"节奏型 JSON 不存在: {p}", code=3)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ParameterError(f"解析节奏型 JSON 失败: {p} ({exc})", code=1) from exc
        name = str(data.get("name", p.stem))
        grid = tuple(int(x) for x in data.get("grid", []))
        if not grid or any(g not in (0, 1) for g in grid):
            raise ParameterError(
                f"节奏型 JSON 的 grid 非法（应为 0/1 数组）: {data.get('grid')}", code=1
            )
        tags = tuple(str(t) for t in data.get("style_tags", []))
        return RhythmPattern(name=name, grid=grid, style_tags=tags)
