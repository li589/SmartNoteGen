"""猫抓源（R7）：既有取证 + 解码能力直通为统一 fetch 接口。

行为 = ``downloadhelper batch``：扫描目录，fMP4 解码为 Opus/MP3，
加密密文跳过并汇总报告。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from sunoauxtool.download.exceptions import EncryptedBlobError, SunoError
from sunoauxtool.download.forensics import identify
from sunoauxtool.download.sources.base import FetchedFile, SourceAdapter
from sunoauxtool.download.transcoder import decode_fmp4


class CatCatchSource(SourceAdapter):
    """猫抓缓存目录源（--source catcatch，默认）。"""

    name = "catcatch"
    description = "猫抓缓存目录扫描：fMP4 解码为 Opus/MP3，密文跳过"

    def __init__(self, fmt: str = "both", bitrate: str = "192k", ffmpeg: Optional[str] = None):
        self.fmt = fmt
        self.bitrate = bitrate
        self.ffmpeg = ffmpeg

    def fetch(self, query: str, out_dir: Path) -> List[FetchedFile]:
        """query = 待扫描目录路径。"""
        directory = Path(query)
        if not directory.is_dir():
            from sunoauxtool.exceptions import InputFileError

            raise InputFileError(f"猫抓缓存目录不存在: {directory}", code=3)
        self.fetch_or_raise_dir(out_dir)

        results: List[FetchedFile] = []
        skipped: List[str] = []
        failures: List[str] = []

        for file in sorted(directory.iterdir()):
            if not file.is_file():
                continue
            verdict = identify(str(file))
            if verdict.is_encrypted:
                skipped.append(f"{file.name}  (加密密文, χ²={verdict.chi_square:.0f})")
                continue
            if verdict.kind != "fmp4":
                continue  # 非 fMP4 容器静默跳过（与 batch 行为一致）
            try:
                outputs = decode_fmp4(
                    file, out_dir, fmt=self.fmt, bitrate=self.bitrate, ffmpeg=self.ffmpeg
                )
                results.extend(
                    FetchedFile(path=p, source=self.name, meta={"from": file.name})
                    for p in outputs
                )
            except (SunoError, EncryptedBlobError):
                failures.append(file.name)

        if failures:
            from sunoauxtool.exceptions import BatchPartialError

            raise BatchPartialError(
                f"解码成功 {len(results)} 个、失败 {len(failures)} 个: {', '.join(failures)}",
                code=8,
            )
        return results

    def check(self, query: str) -> str:
        """校验缓存目录存在且可扫描（**不解码**）；目录不存在抛 InputFileError(3)。"""
        directory = Path(query)
        if not directory.is_dir():
            from sunoauxtool.exceptions import InputFileError

            raise InputFileError(f"猫抓缓存目录不存在: {directory}", code=3)
        count = sum(1 for f in directory.iterdir() if f.is_file())
        return f"catcatch: 目录={directory}  可扫描文件 {count} 个（未解码）"

    def report(self, skipped: List[str]) -> str:  # pragma: no cover - 预留报告渲染
        return "\n".join(f"跳过 {s}" for s in skipped)
