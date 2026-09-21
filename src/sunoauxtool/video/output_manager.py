"""输出管理模块。

复用 SmartNoteGen 的 OutputManager 范式，为视频产物提供：
- 目录组织（project-date layout）
- 防覆盖命名
- metadata.json 落盘
- 产物路径规划
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sunoauxtool.video.config import Config
from sunoauxtool.video.exceptions import OutputWriteError


@dataclass
class VideoArtifactMeta:
    """视频产物元数据。"""
    path: str
    kind: str = "video"
    params: Dict[str, Any] = field(default_factory=dict)
    seed: Optional[int] = None
    seq: int = 1
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    fps: int = 0
    audio_path: str = ""


@dataclass
class VideoRunMeta:
    """一次运行的元数据。"""
    command: str
    seed: Optional[int] = None
    started_at: str = ""
    duration_s: float = 0.0
    version: str = ""
    config_path: Optional[str] = None


class VideoOutputManager:
    """视频输出路径规划与元数据落盘。"""

    def __init__(
        self,
        config: Config,
        project: Optional[str] = None,
        output_dir: Optional[str | Path] = None,
    ) -> None:
        self.config = config
        self.project = project or config.output.project
        self.output_dir_override = output_dir

    def base_dir(self) -> Path:
        """输出根目录（绝对路径）。"""
        value = self.output_dir_override or self.config.paths.output_dir
        p = Path(value).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
        return p.resolve()

    def root(self) -> Path:
        """本次运行的产物目录。"""
        base = self.base_dir()
        today = datetime.now().strftime("%Y%m%d")
        if self.config.output.layout == "legacy":
            return base / today
        return base / self.project / today / "video"

    def _naming(
        self,
        style: str,
        bpm: int,
        seed: Optional[int],
        seq: int,
        suffix: str = "",
    ) -> str:
        """按命名模板生成文件名主干。"""
        seed_str = "demo" if seed is None else str(seed)
        template = self.config.output.naming
        try:
            stem = template.format(style=style, bpm=bpm, seed=seed_str, seq=seq)
        except (KeyError, ValueError, IndexError):
            stem = f"{style}_{bpm}_{seed_str}_{seq}"
        return f"{stem}{suffix}"

    def plan_path(
        self,
        *,
        style: str,
        bpm: int,
        seed: Optional[int],
        seq: int,
        suffix: str = "",
        mkdir: bool = True,
    ) -> Path:
        """规划视频产物路径。"""
        root = self.root()
        if mkdir:
            root.mkdir(parents=True, exist_ok=True)
        name = self._naming(style, bpm, seed, seq, suffix)
        return root / f"{name}.mp4"

    def next_seq(self, style: str, bpm: int, seed: Optional[int]) -> int:
        """防覆盖：扫描同风格同名文件，返回下一个序号。"""
        root = self.root()
        if not root.is_dir():
            return 1
        seed_str = "demo" if seed is None else str(seed)
        prefix = re.escape(f"{style}_{bpm}_{seed_str}_")
        pat = re.compile(prefix + r"(\d+)(?:_.*)?\.mp4", re.IGNORECASE)
        max_seq = 0
        for f in root.iterdir():
            if f.is_file() and f.suffix.lower() == ".mp4":
                m = pat.match(f.name)
                if m:
                    max_seq = max(max_seq, int(m.group(1)))
        return max_seq + 1

    def write_metadata(
        self,
        run: VideoRunMeta,
        artifacts: List[VideoArtifactMeta],
    ) -> Path:
        """输出 metadata.json。"""
        root = self.root()
        root.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": "1.0",
            "run": asdict(run),
            "artifacts": [asdict(a) for a in artifacts],
        }
        target = root / "metadata.json"
        try:
            target.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False),
                encoding="utf-8",
            )
        except OSError as e:
            raise OutputWriteError(str(target)) from e
        return target
