"""视觉效果原语模块（v0.2.0 W1 + v0.3 W4/W5）。

双引擎架构下的分工：
- waveform / spectrum    → ffmpeg 原生引擎（showwaves / showspectrum，快）
- circular_spectrum      → PIL 创意层（CircularSpectrumVisualizer）
- reactive               → PIL 创意层（ReactiveVisualizer）
- tracks                 → PIL 创意层（TracksVisualizer，v0.3 分轨）
- waveform_scroll        → PIL 创意层（WaveformScrollVisualizer，v0.3 滚动波形）

通过 create_visualizer(style, config) 工厂获取 PIL 路径实例。
"""

from typing import Dict

from videomaker.config import Config

from .base import VisualContext, Visualizer
from .reactive import ReactiveVisualizer
from .spectrum import CircularSpectrumVisualizer
from .tracks import TracksVisualizer, WaveformScrollVisualizer


def create_visualizer(style: str, config: Config) -> Visualizer:
    """工厂函数：实例化 PIL 创意层 Visualizer。

    Args:
        style: 视觉效果风格（circular_spectrum / reactive / tracks / waveform_scroll）。
        config: 生效配置。

    Returns:
        Visualizer 实例。

    Raises:
        ValueError: style 不在 PIL 创意层注册表中（waveform/spectrum 走 ffmpeg 引擎）。
    """
    registry: Dict[str, type] = {
        "circular_spectrum": CircularSpectrumVisualizer,
        "reactive": ReactiveVisualizer,
        "tracks": TracksVisualizer,
        "tracks_visual": TracksVisualizer,  # 别名
        "waveform_scroll": WaveformScrollVisualizer,
    }
    cls = registry.get(style.lower())
    if cls is None:
        raise ValueError(
            f"未知 PIL 创意层风格: {style}（可用: {sorted(registry.keys())}；"
            f"waveform/spectrum 走 ffmpeg 原生引擎）"
        )
    return cls(config)


__all__ = [
    "Visualizer",
    "VisualContext",
    "CircularSpectrumVisualizer",
    "ReactiveVisualizer",
    "TracksVisualizer",
    "WaveformScrollVisualizer",
    "create_visualizer",
]
