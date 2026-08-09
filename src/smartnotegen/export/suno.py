"""Suno 合规导出器：WAV → 10–30s 纯器乐合规片段（wav/mp3）。

合规校验（_validate_compliance）：
- 目标时长 ∈ [10, 30]s（Suno 最佳实践）
- 采样率 / 位深符合 ExportOptions（默认 44.1kHz / 16bit）
- 纯器乐、无强混响：本产品生成物天然满足（无歌词轨、无混响处理），文档说明即可
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from smartnotegen.exceptions import ExportError
from smartnotegen.export import audio as audio_ops

#: Suno 合规时长区间
SUNO_MIN_DURATION = 10
SUNO_MAX_DURATION = 30


@dataclass
class ExportOptions:
    """Suno 导出参数。"""

    duration: int = 25
    format: str = "wav"  # wav | mp3
    sample_rate: int = 44100
    bit_depth: int = 16
    fade_ms: float = 50.0


class Exporter(ABC):
    """导出器抽象接口。"""

    @abstractmethod
    def export(self, wav_path: str, opts: ExportOptions) -> str:
        """将 WAV 导出为合规片段，返回输出路径。"""
        raise NotImplementedError


class SunoExporter(Exporter):
    """Suno 合规导出器。

    合规约束（P0-5）：10–30s 纯器乐、采样率/位深符合 ExportOptions、
    **无强混响**——本导出器不做任何混响处理（Suno 导出链恒禁混响，P2-1d）。
    任何调用方请求带混响导出（opts.reverb=True）都会显式报错而非静默忽略。
    """

    #: Suno 导出链恒禁混响（P2-1d 合规标志）
    REVERB_ALLOWED = False

    def export(
        self,
        wav_path: str,
        opts: ExportOptions,
        output_path: Optional[str | Path] = None,
    ) -> str:
        """导出 Suno 合规片段。

        Args:
            wav_path: 输入 WAV 路径。
            opts: 导出选项（时长/格式/采样率/位深/淡入淡出）。
            output_path: 输出路径；None 时写到输入文件同目录并追加 _suno{duration}s 后缀。

        Returns:
            输出文件绝对路径。

        Raises:
            InputFileError: 输入 WAV 不存在。
            ExportError: 目标时长越界 / MP3 编码器缺失 / 请求混响。
        """
        self._validate_compliance(opts)
        # P0-5 合规约束（P2-1d）：Suno 导出链恒禁混响，显式请求即报错而非静默忽略。
        if getattr(opts, "reverb", False):
            raise ExportError("Suno 导出链恒禁混响（P0-5 合规约束，P2-1d）", code=5)

        audio, sr = audio_ops.read_wav(wav_path)

        # 裁剪/循环至目标时长
        audio = self._trim_duration(audio, sr, opts.duration)
        # 淡入淡出
        audio = self._fade(audio, sr, opts.fade_ms)
        # 重采样
        audio = self._resample(audio, sr, opts.sample_rate)
        # 归一化到 -1 dBFS（无爆音）
        audio = audio_ops.normalize(audio)

        ext = opts.format.lower()
        target = self._resolve_output_path(wav_path, output_path, opts.duration, ext)
        target.parent.mkdir(parents=True, exist_ok=True)

        if ext == "wav":
            audio_ops.write_wav(target, audio, opts.sample_rate, opts.bit_depth)
        elif ext == "mp3":
            mp3_bytes = self._encode_mp3(audio, opts.sample_rate)
            target.write_bytes(mp3_bytes)
        else:
            raise ExportError(f"不支持的导出格式: {opts.format}（可选 wav|mp3）", code=5)
        return str(target)

    # -- 合规校验 ----------------------------------------------------------

    def _validate_compliance(self, opts: ExportOptions) -> None:
        """校验导出选项是否符合 Suno 合规区间。"""
        if not SUNO_MIN_DURATION <= opts.duration <= SUNO_MAX_DURATION:
            raise ExportError(
                f"目标时长 {opts.duration}s 超出 Suno 合规区间 "
                f"[{SUNO_MIN_DURATION}, {SUNO_MAX_DURATION}]s；请使用 --duration 10..30",
                code=5,
            )
        if opts.format not in ("wav", "mp3"):
            raise ExportError(f"不支持的导出格式: {opts.format}（可选 wav|mp3）", code=5)
        if opts.sample_rate not in (8000, 16000, 22050, 24000, 44100, 48000, 96000):
            raise ExportError(f"不支持的采样率: {opts.sample_rate}", code=5)
        if opts.bit_depth not in (8, 16, 24, 32):
            raise ExportError(f"不支持的位深: {opts.bit_depth}", code=5)

    # -- 处理步骤 ----------------------------------------------------------

    def _trim_duration(
        self, audio: np.ndarray, sample_rate: int, seconds: float
    ) -> np.ndarray:
        """裁剪/循环至目标秒数。"""
        return audio_ops.trim_or_loop(audio, sample_rate, seconds)

    def _fade(self, audio: np.ndarray, sample_rate: int, fade_ms: float) -> np.ndarray:
        """线性淡入淡出。"""
        return audio_ops.fade(audio, sample_rate, fade_ms)

    def _resample(self, audio: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
        """重采样。"""
        return audio_ops.resample(audio, sr_from, sr_to)

    def _encode_mp3(self, audio: np.ndarray, sample_rate: int) -> bytes:
        """lameenc 编码 MP3；未安装时抛 ExportError(5)。"""
        try:
            import lameenc  # 延迟导入：仅 --format mp3 时才需要
        except ImportError as exc:
            raise ExportError(
                "未安装 lameenc，无法导出 MP3。请执行: pip install lameenc",
                code=5,
            ) from exc

        pcm = audio_ops.to_pcm16(audio)
        if audio.ndim == 2:
            interleaved = pcm.ravel()  # (n,2) -> 交错 L,R,L,R
        else:
            interleaved = pcm

        encoder = lameenc.Encoder()
        encoder.set_bit_rate(192)
        encoder.set_in_sample_rate(sample_rate)
        encoder.set_channels(1 if audio.ndim == 1 else 2)
        encoder.set_quality(2)
        mp3 = encoder.encode(interleaved.tobytes())
        mp3 += encoder.flush()
        return mp3

    # -- 工具 --------------------------------------------------------------

    @staticmethod
    def _resolve_output_path(
        wav_path: str | Path,
        output_path: Optional[str | Path],
        duration: int,
        ext: str,
    ) -> Path:
        """决定输出路径。"""
        if output_path is not None:
            p = Path(output_path).expanduser().resolve()
            if p.suffix.lower() != f".{ext}":
                p = p.with_suffix(f".{ext}")
            return p
        src = Path(wav_path).expanduser().resolve()
        return src.with_name(f"{src.stem}_suno{duration}s.{ext}")

    @staticmethod
    def describe(path: str | Path) -> dict:
        """读取产物元数据（时长/采样率/位深近似）。"""
        data, sr = audio_ops.read_wav(path)
        n = len(data)
        duration = round(n / sr, 2)
        # WAV 文件头位深探测
        bit_depth: Optional[int] = None
        try:
            import struct

            with Path(path).open("rb") as f:
                fmt = f.read(4)
                if fmt == b"RIFF":
                    f.seek(34)
                    bit_depth = struct.unpack("<H", f.read(2))[0]
        except Exception:
            bit_depth = None
        return {
            "duration_s": duration,
            "sample_rate": sr,
            "bit_depth": bit_depth,
            "channels": 2 if data.ndim == 2 else 1,
        }
