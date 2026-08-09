"""日志初始化（分级、格式）。

级别控制（P2-3）：
    --debug   -> DEBUG（含未预期异常堆栈）
    --verbose -> DEBUG
    默认      -> INFO
    --quiet   -> ERROR
"""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def setup_logging(
    verbose: bool = False,
    quiet: bool = False,
    debug: bool = False,
) -> logging.Logger:
    """初始化根 logger。

    Args:
        verbose: True 时输出 DEBUG 级日志。
        quiet: True 时仅输出 ERROR 级日志。
        debug: True 时输出 DEBUG 级日志（并允许打印堆栈）。

    Returns:
        根 logger。
    """
    if debug:
        level = logging.DEBUG
    elif quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT))

    root = logging.getLogger("smartnotegen")
    root.setLevel(level)
    # 避免重复添加 handler（如 pytest 多次调用）
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.propagate = False
    return root


def get_logger(name: str) -> logging.Logger:
    """获取带 smartnotegen 前缀的子 logger。"""
    return logging.getLogger(f"smartnotegen.{name}")
