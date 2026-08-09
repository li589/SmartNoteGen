"""输出管理（P2-5）：目录组织、自动命名、防覆盖、元数据 JSON。

新路径引擎（默认 layout=project-date）：
    <root>/<project>/<YYYYMMDD>/{style}_{bpm}_{seed}_{seq}.{ext}
示例：
    output/myproj/20250809/pop_120_42_1.mid
    output/myproj/20250809/pop_120_42_1.wav
    output/myproj/20250809/pop_120_42_1_suno25s.wav
    output/myproj/20250809/metadata.json

- seq 为批次内序号；跨运行防覆盖：next_seq 扫描目录内同 {style}_{bpm}_{seed}_* 文件取 max+1。
- seed 为 None 时文件名用 "demo"（与 P0 兼容）。
- [output] layout=legacy 时回退 P0 旧格式 output/YYYYMMDD/（build_output_path 原样保留）。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from smartnotegen.config import Config


@dataclass
class ArtifactMeta:
    """单个产物的元数据（写入 metadata.json 的 artifacts 数组）。"""

    path: str
    kind: str  # "midi" | "wav" | "suno" | "draft" | "metadata"
    params: Dict[str, Any] = field(default_factory=dict)
    seed: Optional[int] = None
    seq: int = 1
    duration_s: float = 0.0
    sample_rate: Optional[int] = None
    contains_vocals: bool = False


@dataclass
class RunMeta:
    """一次运行的元数据（写入 metadata.json 的 run 对象）。"""

    command: str
    seed: Optional[int] = None
    started_at: str = ""
    duration_s: float = 0.0
    version: str = ""
    config_path: Optional[str] = None


class OutputManager:
    """输出路径规划与元数据落盘。"""

    def __init__(
        self,
        config: Config,
        project: Optional[str] = None,
        output_dir: Optional[str | Path] = None,
    ) -> None:
        """初始化。

        Args:
            config: 生效配置（[output] 节 + paths.output_dir）。
            project: 项目名；None 时用配置 [output] project。
            output_dir: 输出根目录覆盖（--output-dir）；None 时用配置 paths.output_dir。
        """
        self.config = config
        self.project = project or config.output.project
        self.output_dir_override = output_dir

    # -- 目录 --------------------------------------------------------------

    def base_dir(self) -> Path:
        """输出根目录（绝对路径）。"""
        value = self.output_dir_override or self.config.paths.output_dir
        p = Path(value).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
        return p.resolve()

    def root(self) -> Path:
        """本次运行的产物目录。

        project-date: <root>/<project>/<YYYYMMDD>/
        legacy:       <root>/<YYYYMMDD>/
        """
        base = self.base_dir()
        today = datetime.now().strftime("%Y%m%d")
        if self.config.output.layout == "legacy":
            return base / today
        return base / self.project / today

    # -- 命名 --------------------------------------------------------------

    def _naming(self, style: str, bpm: int, seed: Optional[int], seq: int, suffix: str) -> str:
        """按命名模板生成文件名主干（不含扩展名）。"""
        seed_str = "demo" if seed is None else str(seed)
        template = self.config.output.naming
        try:
            stem = template.format(style=style, bpm=bpm, seed=seed_str, seq=seq)
        except (KeyError, ValueError, IndexError):
            # 模板非法时回退默认命名，不阻断生成
            stem = f"{style}_{bpm}_{seed_str}_{seq}"
        return f"{stem}{suffix}"

    def plan_path(
        self,
        *,
        style: str,
        bpm: int,
        seed: Optional[int],
        ext: str,
        seq: int,
        suffix: str = "",
        mkdir: bool = True,
    ) -> Path:
        """规划产物路径。

        Args:
            style: 风格名。
            bpm: 速度。
            seed: 随机种子（None -> demo）。
            ext: 扩展名（不含点）。
            seq: 批次内序号。
            suffix: 附加后缀（如 "_suno25s"），追加在 seq 之后、扩展名之前。
            mkdir: 是否自动创建目录（dry-run 时传 False 不落盘）。
        """
        root = self.root()
        if mkdir:
            root.mkdir(parents=True, exist_ok=True)
        name = self._naming(style, bpm, seed, seq, suffix)
        return root / f"{name}.{ext}"

    def next_seq(self, style: str, bpm: int, seed: Optional[int], ext: str) -> int:
        """防覆盖：扫描目录内同 {style}_{bpm}_{seed}_* 文件，返回下一个 seq（max+1）。"""
        root = self.root()
        if not root.is_dir():
            return 1
        seed_str = "demo" if seed is None else str(seed)
        prefix = re.escape(f"{style}_{bpm}_{seed_str}_")
        pat = re.compile(prefix + r"(\d+)(?:_.*)?\.", re.IGNORECASE)
        max_seq = 0
        for f in root.iterdir():
            if f.is_file() and f.suffix.lower() == f".{ext}":
                m = pat.match(f.name)
                if m:
                    max_seq = max(max_seq, int(m.group(1)))
        return max_seq + 1

    # -- 元数据 ------------------------------------------------------------

    def write_metadata(
        self,
        run: RunMeta,
        artifacts: List[ArtifactMeta],
    ) -> Path:
        """输出 metadata.json（schema_version 1.0）。"""
        root = self.root()
        root.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": "1.0",
            "run": asdict(run),
            "artifacts": [asdict(a) for a in artifacts],
        }
        target = root / "metadata.json"
        target.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False), encoding="utf-8"
        )
        return target
