"""兼容别名包：smartnotegen 已更名为 sunoauxtool（2026-09，v0.7.0）。

本 shim 只做名字转发：`import smartnotegen` 等价于 `import sunoauxtool`，
子模块同理（sys.modules 别名，子模块查找沿用 sunoauxtool 的 __path__）。
将于 1-2 个版本后移除，请迁移到 `import sunoauxtool`。
"""

import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "smartnotegen 已更名为 sunoauxtool；本兼容别名将于 1-2 个版本后移除。",
    DeprecationWarning,
    stacklevel=2,
)

_mod = _importlib.import_module("sunoauxtool")
_sys.modules["smartnotegen"] = _mod
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
