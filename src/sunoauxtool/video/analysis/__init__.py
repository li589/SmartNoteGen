"""音视频分析模块（v0.2.0 预计算架构 + v0.3 多轨）。

核心能力：
- analyze() 一次预计算：频谱矩阵 / RMS 包络 / 波形 / onset
- analyze_multitrack()：混音主分析 + 逐轨频谱/RMS（分轨可视化用）
- AudioAnalysis 只读共享，所有 Visualizer 查表渲染
- 复用 SmartNoteGen 的 preview 模块保证口径一致
"""

from .audio_analysis import (
    AudioAnalysis,
    analyze,
    analyze_multitrack,
    compute_audio_features_from_array,
)

__all__ = [
    "analyze",
    "analyze_multitrack",
    "AudioAnalysis",
    "compute_audio_features_from_array",
]
