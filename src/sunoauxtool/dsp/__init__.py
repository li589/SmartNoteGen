"""DSP（P2-1 管线内链 + R6 通用算子层）。

- ``DspProcessor``：pipeline 内部处理链（render 后 export 前，增量兼容不动）。
- ``ops``：R6 通用算子框架（管道式 ops 串，``sunoaux post dsp --ops``）。
- ``loudness``：EBU R128 简化版积分响度（loudnorm 算子的底层）。
"""

from sunoauxtool.dsp.processor import DspOptions, DspProcessor

__all__ = ["DspOptions", "DspProcessor"]
