"""Visualizer 抽象接口（v0.2.0 W1）。

契约：
- __init__(config)：构造时接收 Config，不接收音频数据
- render_frame(ctx, frame_idx)：只读 ctx.analysis 查表渲染，禁止重计算
- 返回 RGB 帧 (H, W, 3) uint8

创意层实现（PIL 逐帧渲染，走 FrameEngine）：
- waveform / spectrum → ffmpeg 原生引擎（不在本模块）
- circular_spectrum / reactive → 本模块实现（见 spectrum.py / reactive.py）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np

from sunoauxtool.video.analysis import AudioAnalysis
from sunoauxtool.video.config import Config


@dataclass
class VisualContext:
    """渲染上下文（一次构建，全帧共享）。"""
    width: int
    height: int
    fps: int
    analysis: AudioAnalysis
    background: Optional[np.ndarray] = None  # 背景帧 (H, W, 3) uint8，由引擎注入


class Visualizer(ABC):
    """创意层可视化抽象基类（PIL 路径）。"""

    def __init__(self, config: Config) -> None:
        self.config = config

    @abstractmethod
    def render_frame(self, ctx: VisualContext, frame_idx: int) -> np.ndarray:
        """渲染单帧。

        Args:
            ctx: 渲染上下文（含预计算 analysis 与背景帧）。
            frame_idx: 当前帧索引 [0, analysis.n_frames)。

        Returns:
            RGB 帧 (H, W, 3) uint8。
        """
        ...

    @abstractmethod
    def get_style_name(self) -> str:
        """返回视觉效果名称。"""
        ...
