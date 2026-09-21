"""P1 AI 适配器抽象接口。

隔离原则（架构 §5.1）：
- 本包所有重型 import 均发生在函数体内（延迟导入），模块顶部零 torch/audiocraft/diffrhythm
- AIGenerator 只暴露 generate(source_wav, prompt) -> str（输入输出均为文件路径）
- P0 管线完全不感知 AI 内部实现
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class AIGenerator(ABC):
    """AI 生成器抽象接口（P1）。

    generate 输入/输出均为音频文件路径字符串。
    """

    @abstractmethod
    def generate(self, source_wav: str, prompt: str, **kw) -> str:
        """基于输入音频与提示词生成新音频，返回输出文件路径。"""
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        """当前环境是否可用（依赖已安装 / 显存满足）。"""
        raise NotImplementedError
