"""DSP 处理器（P2-1）：归一化 -1dBFS、淡入淡出、可选 EQ/压缩、恒禁混响。

阶段位置：render 输出后、export 前（pipeline / batch --render 链中插入）。
所有 DSP 阶段可开关、可单测；非法参数显式报错（ParameterError，错误码 1）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from smartnotegen.dsp import filters
from smartnotegen.exceptions import ParameterError
from smartnotegen.export import audio as audio_ops

#: 淡入淡出允许范围（毫秒）
FADE_MIN_MS = 0.0
FADE_MAX_MS = 5000.0


@dataclass
class DspOptions:
    """DSP 参数。默认：归一化 -1dBFS、淡入 100ms/淡出 300ms、EQ/压缩/混响关。"""

    normalize_dbfs: float = -1.0
    fade_in_ms: float = 100.0
    fade_out_ms: float = 300.0
    eq: bool = False
    eq_low_cut_hz: float = 30.0
    compressor: bool = False
    compressor_ratio: float = 2.0
    compressor_threshold_db: float = -12.0
    reverb: bool = False


class DspProcessor:
    """独立 DSP 阶段：read -> normalize -> fade_in/out -> [EQ] -> [compressor] -> write。"""

    def validate(self, opts: DspOptions) -> None:
        """参数合法性校验；非法参数显式抛 ParameterError（而非静默忽略）。"""
        if not FADE_MIN_MS <= opts.fade_in_ms <= FADE_MAX_MS:
            raise ParameterError(
                f"fade_in_ms 必须在 [{FADE_MIN_MS:.0f}, {FADE_MAX_MS:.0f}]ms 区间: {opts.fade_in_ms}",
                code=1,
            )
        if not FADE_MIN_MS <= opts.fade_out_ms <= FADE_MAX_MS:
            raise ParameterError(
                f"fade_out_ms 必须在 [{FADE_MIN_MS:.0f}, {FADE_MAX_MS:.0f}]ms 区间: {opts.fade_out_ms}",
                code=1,
            )
        if opts.normalize_dbfs > 0.0:
            raise ParameterError(
                f"normalize_dbfs 必须 <= 0（dBFS 峰值目标）: {opts.normalize_dbfs}", code=1
            )
        if opts.compressor and opts.compressor_ratio < 1.0:
            raise ParameterError(
                f"compressor_ratio 必须 >= 1（压缩比不能小于 1）: {opts.compressor_ratio}", code=1
            )
        if opts.eq and opts.eq_low_cut_hz <= 0.0:
            raise ParameterError(f"eq_low_cut_hz 必须 > 0: {opts.eq_low_cut_hz}", code=1)

    def process(self, wav_path: str | Path, opts: DspOptions, out_path: str | Path) -> str:
        """处理单个 WAV 文件，返回输出路径。

        Raises:
            ParameterError: 参数非法，或请求了未支持的混响（--reverb）。
        """
        self.validate(opts)
        if opts.reverb:
            raise ParameterError(
                "--reverb 暂未支持（本增量未实现 fluidsynth 混响参数化；"
                "且 Suno 导出链恒禁混响，P0-5 合规约束）",
                code=1,
            )

        audio, sr = audio_ops.read_wav(wav_path)

        # 1. 归一化到峰值目标（默认 -1 dBFS）
        peak_abs = float(10 ** (opts.normalize_dbfs / 20.0))
        audio = audio_ops.normalize(audio, peak_abs=peak_abs)

        # 2. 淡入淡出（首尾独立毫秒数）
        audio = audio_ops.fade_in_out(audio, sr, opts.fade_in_ms, opts.fade_out_ms)

        # 3. 可选 EQ（低频切）
        if opts.eq:
            audio = filters.highpass(audio, sr, opts.eq_low_cut_hz)

        # 4. 可选压缩器（软拐点）
        if opts.compressor:
            audio = filters.compressor(audio, opts.compressor_ratio, opts.compressor_threshold_db)

        # 写盘（16bit PCM，与渲染链一致）
        target = Path(out_path).expanduser().resolve()
        if target.suffix.lower() != ".wav":
            target = target.with_suffix(".wav")
        return audio_ops.write_wav(target, audio, sr, bit_depth=16)
