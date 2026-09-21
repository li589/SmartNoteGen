"""音频分析（#13）：测速（tempo）与 WAV→MIDI 转谱（transcribe）。

设计约束
--------
- **numpy-only**：只依赖 base.txt 里已有的 numpy + soundfile，不引入 librosa。
  STFT / onset 包络 / 自相关全部手写（`spectral.py` 是共享底座）。
- 内置转谱定位为「单旋律 / 主导声部」：STFT 谐波和 salience + 峰值跟踪 + 按拍量化。
  多音轨复调转谱是研究级问题，留给可选的 basic-pitch 后端（`ai/basicpitch.py`，
  延迟导入，依赖走 requirements/ai.txt 可选装）——与 ai/musicgen.py 同一适配器模式。
"""

from sunoauxtool.analysis.tempo import TempoEstimate, beat_grid, estimate_bpm
from sunoauxtool.analysis.transcribe import (
    TranscribeOptions,
    TranscribeResult,
    transcribe_wav,
)

__all__ = [
    "TempoEstimate",
    "beat_grid",
    "estimate_bpm",
    "TranscribeOptions",
    "TranscribeResult",
    "transcribe_wav",
]
