"""视觉效果原语模块（v0.2.0 W1 + v0.3 W4/W5）。

双引擎架构下的分工：
- waveform / spectrum    → ffmpeg 原生引擎（showwaves / showspectrum，快）
- circular_spectrum      → PIL 创意层（CircularSpectrumVisualizer）
- reactive               → PIL 创意层（ReactiveVisualizer）
- tracks                 → PIL 创意层（TracksVisualizer，v0.3 分轨）
- waveform_scroll        → PIL 创意层（WaveformScrollVisualizer，v0.3 滚动波形）
- score                  → PIL 创意层（ScoreVisualizer，#14 滚动谱面）
- bars                   → PIL 创意层（BarsVisualizer，R15 频率柱状条 + 峰值保持帽）

通过 create_visualizer(style, config, **extra) 工厂获取 PIL 路径实例。
"""

from typing import Dict

from sunoauxtool.video.config import Config

from .bars import BarsVisualizer
from .base import VisualContext, Visualizer
from .reactive import ReactiveVisualizer
from .score import ScoreVisualizer
from .spectrum import CircularSpectrumVisualizer
from .tracks import TracksVisualizer, WaveformScrollVisualizer


def discover_visuals() -> Dict[str, type]:
    """PIL 创意层风格注册表 ``{style: Visualizer 子类}``。

    = 内置硬编码 + entry point 插件（扩展点 ``sunoauxtool.video_visuals``，
    见 :mod:`sunoauxtool.plugins`）。

    注册表保留**类本身**而非实例——工厂需按当次 config / extra 实例化，
    因此 ``instantiate=False``。
    """
    from sunoauxtool.plugins import discover

    builtins: Dict[str, type] = {
        "bars": BarsVisualizer,
        "circular_spectrum": CircularSpectrumVisualizer,
        "reactive": ReactiveVisualizer,
        "score": ScoreVisualizer,
        "tracks": TracksVisualizer,
        "tracks_visual": TracksVisualizer,  # 别名
        "waveform_scroll": WaveformScrollVisualizer,
    }
    return discover("video_visuals", builtins, base=Visualizer, instantiate=False)


def create_visualizer(style: str, config: Config, **extra) -> Visualizer:
    """工厂函数：实例化 PIL 创意层 Visualizer。

    Args:
        style: 视觉效果风格（bars / circular_spectrum / reactive / tracks /
            waveform_scroll / score，或插件注册的新风格）。
        config: 生效配置。
        **extra: 透传给 Visualizer 构造器的额外参数
            （score 样式用：score / beat_times / bpm / notation）。

    Returns:
        Visualizer 实例。

    Raises:
        ValueError: style 不在 PIL 创意层注册表中（waveform/spectrum 走 ffmpeg 引擎）。
    """
    registry = discover_visuals()
    cls = registry.get(style.lower())
    if cls is None:
        raise ValueError(
            f"未知 PIL 创意层风格: {style}（可用: {sorted(registry.keys())}；"
            f"waveform/spectrum 走 ffmpeg 原生引擎）"
        )
    return cls(config, **extra)


__all__ = [
    "Visualizer",
    "VisualContext",
    "BarsVisualizer",
    "CircularSpectrumVisualizer",
    "ReactiveVisualizer",
    "ScoreVisualizer",
    "TracksVisualizer",
    "WaveformScrollVisualizer",
    "create_visualizer",
    "discover_visuals",
]
