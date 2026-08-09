"""自定义异常与错误码定义。

错误码约定（见 docs/architecture-P1P2.md §4.4 错误码表）：
    0 成功
    1 参数错误/通用错误
    2 配置错误
    3 输入文件错误
    4 渲染失败
    5 导出失败
    6 AI 模块不可用
    7 渲染环境不完整（module 缺失/损坏、fluidsynth 不可执行、SF2 不可加载）
    8 批量部分失败
    9 批量全部失败
"""

from __future__ import annotations

from typing import List, Optional, Tuple

#: 错误码表（供 `smartnotegen errors` 子命令与文档使用）
ERROR_CODES: List[Tuple[int, str, str]] = [
    (0, "成功", ""),
    (1, "参数错误/通用错误", "未知子命令、非法参数组合、非法 DSP 参数（ratio<1、fade 越界）"),
    (2, "配置错误", "配置文件缺失/非法、用户显式配置的路径无效"),
    (3, "输入文件错误", ".mid/.wav 不存在或无法解析"),
    (4, "渲染失败", "fluidsynth 进程非零退出（加载后执行失败）"),
    (5, "导出失败", "时长越界、MP3 编码器缺失"),
    (6, "AI 模块不可用", "依赖未装、显存不足、DiffRhythm NO-GO"),
    (7, "渲染环境不完整", "module 缺失/损坏、fluidsynth 不可执行、SF2 不可加载"),
    (8, "批量部分失败", "batch 部分项成功部分失败"),
    (9, "批量全部失败", "batch 全部项失败"),
]


class SmartNoteGenError(Exception):
    """所有 SmartNoteGen 自定义异常的基类。"""

    #: 默认错误码（1 = 参数/通用错误）
    code: int = 1

    def __init__(self, message: str, code: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code

    def __str__(self) -> str:  # pragma: no cover - 简单透传
        return self.message


class ParameterError(SmartNoteGenError):
    """参数错误：非法参数组合、未知参数值、越界时长等。"""

    code = 1


class ConfigError(SmartNoteGenError):
    """配置错误：配置文件不存在/格式非法、SoundFont 路径无效等。"""

    code = 2


class InputFileError(SmartNoteGenError):
    """输入文件错误：.mid/.wav 不存在或无法解析。"""

    code = 3


class RenderError(SmartNoteGenError):
    """渲染失败：fluidsynth 未安装/找不到、渲染进程非零退出。"""

    code = 4


class ExportError(SmartNoteGenError):
    """导出失败：时长不在 10–30s、MP3 编码器缺失等。"""

    code = 5


class AiDependencyError(SmartNoteGenError):
    """AI 模块不可用：P1 依赖未安装、显存不足（DiffRhythm）。"""

    code = 6


class ModuleError(SmartNoteGenError):
    """渲染环境不完整：module 缺失/损坏、fluidsynth 不可执行、SF2 不可加载。

    与 ConfigError(2) 的区分：默认 module 环境（非用户显式配置）缺失/损坏用本异常；
    用户显式配置的路径无效仍用 ConfigError(2)。
    """

    code = 7


class BatchPartialError(SmartNoteGenError):
    """批量部分失败：batch 部分项成功部分失败。"""

    code = 8


class BatchFailedError(SmartNoteGenError):
    """批量全部失败：batch 全部项失败。"""

    code = 9
