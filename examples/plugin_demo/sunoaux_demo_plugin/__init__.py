"""SunoAuxTool 插件示例（R12）：经 entry point 注册扩展，**无需改核心代码**。

安装::

    pip install -e examples/plugin_demo

安装后立即被核心发现（``sunoauxtool.plugins.discover``）：:

    sunoauxtool transcribe in.wav --backend demo        # 新转谱后端
    sunoaux post fetch <query> --source demo-source     # 新下载源
    sunoaux post fetch <query> --source demo-source --dry-run

卸载即消失（``pip uninstall sunoaux-demo-plugin``）——核心代码零改动。

契约要点
--------
- ``sunoauxtool.transcribe_backends``：注册**类**，需提供
  ``transcribe(src_wav, out_mid=None) -> str``。
- ``sunoauxtool.download_sources``：注册 **``SourceAdapter`` 子类**（核心会实例化，
  故必须是子类，否则 warn 跳过）。

详见 :mod:`sunoauxtool.plugins` 与 ``docs/plugins.md``。
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from sunoauxtool.download.sources.base import FetchedFile, SourceAdapter


class DemoTranscribeBackend:
    """演示转谱后端：委托内置 builtin 管线（证明插件后端确实被调用）。"""

    def transcribe(self, src_wav: str, out_mid: str | None = None) -> str:
        from sunoauxtool.analysis.transcribe import (
            TranscribeOptions,
            transcribe_wav,
            write_transcribed_midi,
        )

        result = transcribe_wav(src_wav, TranscribeOptions())
        out = out_mid or str(Path(src_wav).with_suffix(".demo.mid"))
        return write_transcribed_midi(result, out)


class DemoSource(SourceAdapter):
    """演示下载源：不联网，落一个占位文件（证明插件源被发现并调用）。"""

    name = "demo-source"
    description = "插件示例源（R12）：不联网，产出占位文件"

    def fetch(self, query: str, out_dir: Path) -> List[FetchedFile]:
        self.fetch_or_raise_dir(out_dir)
        target = out_dir / f"{query}.txt"
        target.write_text("demo plugin source\n", encoding="utf-8")
        return [FetchedFile(path=target, source=self.name)]

    def check(self, query: str) -> str:
        return f"demo-source: 插件示例源，query={query}（无需凭证，不联网）"


__all__ = ["DemoTranscribeBackend", "DemoSource"]
