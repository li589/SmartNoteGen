"""兼容别名包：videomaker 已并入 sunoauxtool.video（2026-09，v0.7.0）。

本 shim 只做名字转发：`import videomaker` 等价于 `import sunoauxtool.video`。
将于 1-2 个版本后移除，请迁移到 `from sunoauxtool.video import ...`。
"""

import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "videomaker 已并入 sunoauxtool.video；本兼容别名将于 1-2 个版本后移除。",
    DeprecationWarning,
    stacklevel=2,
)

_mod = _importlib.import_module("sunoauxtool.video")
_sys.modules["videomaker"] = _mod
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
