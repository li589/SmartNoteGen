"""渲染引擎模块（v0.2.0）。

双引擎架构：
1. FFmpegEngine：原生 ffmpeg 滤镜（showwaves/showspectrum/overlay/drawtext）
   - waveform / spectrum 风格
   - 快、稳、零额外依赖
2. FrameEngine：PIL 逐帧渲染 + ffmpeg 编码
   - circular_spectrum / reactive 风格（创意层）
   - 预计算分析一次，全帧共享

路由决策在 Compositor（FFMPEG_STYLES 集合）。
"""

from .ffmpeg_engine import FFmpegEngine
from .frame_engine import FrameEngine

__all__ = [
    "FFmpegEngine",
    "FrameEngine",
]
