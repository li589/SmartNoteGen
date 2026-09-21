"""下载源适配器（R7）：统一 ``post fetch --source`` 入口。

边界（继承重构计划「不做清单」）：
- **猫抓路径** = 既有能力直通（目录扫描 + 取证判定 + fMP4 解码转码）；
- **API 路径**（suno-api / haimeng / tianyin）= adapter 留位：凭证/端点全部走
  gitignored 配置（``config/sources.toml`` 或 ``~/.sunoauxtool/sources.toml``），
  本仓库不做客户端逆向、不内置任何真实端点——拿到合法 API 时填配置即可用；
- 错误码：25 = 凭证缺失、26 = 请求失败；猫抓路径沿用 20-24。
"""

from sunoauxtool.download.sources.base import FetchedFile, SourceAdapter, list_sources
from sunoauxtool.download.sources.catcatch import CatCatchSource
from sunoauxtool.download.sources.api import ApiSource

__all__ = [
    "FetchedFile",
    "SourceAdapter",
    "CatCatchSource",
    "ApiSource",
    "list_sources",
]
