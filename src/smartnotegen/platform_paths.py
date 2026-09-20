"""平台感知的 fluidsynth 回落：类 Unix 平台改用系统安装的 fluidsynth。

背景：仓库捆绑的 fluidsynth 是 **Windows 发行版**
（`module/fluidsynth/bin/fluidsynth.exe` + DLL，随版本控制入库）。
在类 Unix 平台（CI 的 ubuntu-latest、macOS）上该文件**存在但没有执行位**
（PE 格式，且 git 不保留可执行位差异），
此时应回落到系统安装的 fluidsynth（`apt install fluidsynth` / `brew install fluid-synth`）。

设计约束：
- **Windows 上永不触发回落**——`system_fluidsynth()` 恒返回 None，
  既有行为逐字不变（Windows 不存在「.exe 存在但不可执行」这一状态，
  `os.access(path, os.X_OK)` 在 Windows 上近似等价于存在性检查）。
- 仅在调用方**已确认「路径存在但不可执行」**时才查询回落，避免掩盖
  「路径压根不存在」这类真实的配置错误。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional

#: 是否为 Windows 平台。Windows 无 Unix 可执行位语义，
#: 故不能在 Windows 上做「不可执行 -> 回落」，否则会改变既有行为。
IS_WINDOWS = os.name == "nt"


def system_fluidsynth() -> Optional[Path]:
    """返回系统 PATH 上的 fluidsynth 可执行文件；**Windows 上恒为 None**。

    仅在「捆绑的 Windows 二进制在当前平台不可执行」时作为回落候选使用。
    返回 None 表示无回落可用，调用方应维持原有的不可用判定（MISSING/BROKEN）。
    """
    if IS_WINDOWS:
        return None
    found = shutil.which("fluidsynth")
    return Path(found) if found else None
