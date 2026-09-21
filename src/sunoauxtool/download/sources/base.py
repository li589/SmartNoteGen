"""下载源适配器基类（R7）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


@dataclass
class FetchedFile:
    """一次取回产出的单个文件。"""

    path: Path
    source: str
    meta: Dict[str, str] = field(default_factory=dict)


class SourceAdapter(ABC):
    """下载源适配器接口：``fetch(query, out_dir) -> [FetchedFile]``。

    query 语义由各源自定义：catcatch = 目录路径；API 源 = 歌曲/任务 ID。
    """

    #: 源标识（--source 取值）
    name: str = ""
    #: 一句话能力说明（CLI help 用）
    description: str = ""

    @abstractmethod
    def fetch(self, query: str, out_dir: Path) -> List[FetchedFile]:
        """执行取回；失败抛 SmartNoteGenError 子类（退出码见 exceptions.py）。"""

    def fetch_or_raise_dir(self, out_dir: Path) -> Path:
        """确保输出目录存在（幂等）。"""
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir


def list_sources() -> List[SourceAdapter]:
    """全部已注册源（新源加到此处一行）。"""
    from sunoauxtool.download.sources.api import API_SOURCE_NAMES, ApiSource
    from sunoauxtool.download.sources.catcatch import CatCatchSource

    sources: List[SourceAdapter] = [CatCatchSource()]
    for name in API_SOURCE_NAMES:
        sources.append(ApiSource(name))
    return sources
