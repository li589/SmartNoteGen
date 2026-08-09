"""pytest 根 conftest：保证 src/ 布局下 smartnotegen 可导入（无需先 pip install -e .）。"""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def pytest_configure(config):
    """将 pytest 临时根目录重定向到项目内（避免沙箱拒绝系统 Temp 目录）。

    使用每会话唯一的 basetemp + tmp_path_retention=all：pytest 不会在会话结束后
    尝试删除临时目录（沙箱下回收站不可用会导致 safe-delete 失败）。
    """
    if not config.option.basetemp:
        import time

        base = Path(__file__).resolve().parent / ".pytest_tmp" / f"s{int(time.time() * 1000)}"
        base.parent.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(base)
