"""WAV→MIDI 转谱（内置后端）：STFT 谐波 salience + 峰值跟踪 + 按拍量化。

定位（务必记住）
--------
内置后端是「**单旋律 / 主导声部**」转谱器，不是复调转谱：
- 逐帧在 [A0, C8] 半音网格上算谐波 salience（f0 + ½·2f0 + ¼·3f0，再扣除八度鬼影），
  取最大者为该帧音高——天然**单声部**。
- 复调（多音同时）交给可选的 basic-pitch 后端（``ai/basicpitch.py``，#13 预留），
  依赖走 requirements/ai.txt 可选装、延迟导入，P0 环境零感知。

流水线
--------
STFT(2048/256) → 逐帧谐波 salience argmax → 音高轨 →
同音高 run 内按 salience 低谷切段（重复音的重音必然伴随能量凹谷）→
合并跨小间隙的同音 run → 滤短段 →
秒 → 拍（用测速结果或显式 bpm）→ 量化到 grid → NoteSequence → MidiDocument 落盘。

两个关键时间约定（都实测校准过）：
- **时间戳取帧中心** ``(f + 0.5) × hop / sr``：音符边界会让新音高提前约半个窗长
  被「看见」，取帧起点会系统性提前 ~80ms；帧中心实测 ±20ms。
- **窗长 2048**：4096 频率分辨率更好但时间上漏得更早，1/16 量化必错位。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from sunoauxtool.analysis.spectral import (
    TRANSCRIBE_FRAME,
    TRANSCRIBE_HOP,
    stft_magnitude,
)
from sunoauxtool.analysis.tempo import estimate_bpm, read_wav_mono
from sunoauxtool.exceptions import ParameterError
from sunoauxtool.models.midi import MidiDocument
from sunoauxtool.models.notes import Note, NoteSequence

#: 转谱音域（A0..C8，钢琴范围）
PITCH_LOW = 21
PITCH_HIGH = 108

#: 量化网格预设（拍为单位；四分音符 = 1 拍）
GRID_CHOICES = {"1/4": 1.0, "1/8": 0.5, "1/16": 0.25, "1/32": 0.125}

#: 音高轨逐帧有效门槛（相对全谱最大 salience；低于视为无声帧）
_VOICED_RATIO = 0.08

#: 八度鬼影扣除系数：S[p] -= coef × S[p+12]
_OCTAVE_SUBTRACT = 0.4

#: 谐波权重（f0、2f0、3f0）
_HARMONIC_WEIGHTS = (1.0, 0.5, 0.25)

#: 同音 run 内部切分重复音的凹谷比率：局部极小须低于两侧平台（±5 帧）最大值的该比例。
#: 实测依据： butt-joint 重复音在 93ms 窗下 salience 只从 13.2 谷到 8.4（64%）——
#: 绝对低谷判据（如 <35% 中位数）永远抓不到；「相对两侧平台塌了 30%」才可用。
#: 0.7 对颤音（谷差通常 <15%）安全。
_DIP_RATIO = 0.7


@dataclass
class TranscribeOptions:
    """转谱选项。

    Attributes:
        bpm: 显式 BPM（``None`` = 自动测速后取整）。
        grid: 量化网格（拍）。字符串支持 ``1/4``/``1/8``/``1/16``/``1/32`` 或浮点串。
        min_note_ms: 音符最短时长（毫秒），更短的段丢弃。
        merge_gap_ms: 同音高 run 之间小于该间隙（毫秒）则合并。
        program: GM 乐器号（0-127）。
        track_name: 输出轨道名。
    """

    bpm: Optional[float] = None
    grid: str = "1/16"
    min_note_ms: float = 60.0
    merge_gap_ms: float = 40.0
    program: int = 0
    track_name: str = "transcribed"

    def __post_init__(self) -> None:
        if self.bpm is not None and not 20.0 <= self.bpm <= 400.0:
            raise ParameterError(f"bpm 超出范围 (20-400): {self.bpm}", code=1)
        self.grid_beats = parse_grid(self.grid)
        if not 0 <= self.program <= 127:
            raise ParameterError(f"program 超出 GM 范围 (0-127): {self.program}", code=1)
        if self.min_note_ms <= 0 or self.merge_gap_ms < 0:
            raise ParameterError(
                f"min_note_ms 必须为正且 merge_gap_ms 非负: "
                f"{self.min_note_ms}/{self.merge_gap_ms}",
                code=1,
            )


def parse_grid(spec: str) -> float:
    """解析量化网格：``1/16`` → 0.25 拍；也接受浮点串（如 ``0.25``）。

    Raises:
        ParameterError: 无法解析或非正。
    """
    text = (spec or "").strip()
    if not text:
        raise ParameterError("grid 不能为空（可用 1/4、1/8、1/16、1/32 或拍数浮点）", code=1)
    if text in GRID_CHOICES:
        return GRID_CHOICES[text]
    try:
        if "/" in text:
            num, den = text.split("/", 1)
            value = float(num) / float(den)
        else:
            value = float(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise ParameterError(f"无法解析量化网格: {spec!r}", code=1) from exc
    if value <= 0 or value > 4.0:
        raise ParameterError(f"量化网格须在 (0, 4] 拍内: {spec!r} -> {value}", code=1)
    return value


@dataclass
class TranscribeResult:
    """转谱结果。

    Attributes:
        seq: 量化后的 :class:`NoteSequence`（单轨）。
        detected_bpm: 自动测速得到的 BPM（显式传入 bpm 时与其相同）。
        confidence: 测速置信度（0~1）。
        beat_offset: 测速给出的第一拍位置（秒）。
        note_count: 转出的音符数。
        pitch_range: (最低, 最高) MIDI 音号。
        segments: 调试明细，每段 ``(pitch, start_s, end_s, q_start_beat, q_dur_beats)``。
    """

    seq: NoteSequence
    detected_bpm: float
    confidence: float
    beat_offset: float
    note_count: int
    pitch_range: Tuple[int, int]
    segments: List[Tuple[int, float, float, float, float]] = field(default_factory=list)


def _pitch_salience(spec: np.ndarray, freq_res: float) -> np.ndarray:
    """逐帧、逐半音的谐波 salience 矩阵，形状 ``(n_frames, PITCH_HIGH+1)``（低段置 -inf）。

    S[p] = w1·E(f0) + w2·E(2f0) + w3·E(3f0)（E 取目标频率 ±1 bin 的最大幅度，
    幅度开方压缩动态），随后 S[p] -= 0.4·S[p+12] 抑制「谐波在八度上冒充基频」的鬼影。
    """
    n_pitches = PITCH_HIGH + 1
    n_frames, n_bins = spec.shape
    sal = np.zeros((n_frames, n_pitches), dtype=np.float64)
    bin_cache: dict[float, int] = {}
    for harmonic, weight in zip((1, 2, 3), _HARMONIC_WEIGHTS):
        for p in range(PITCH_LOW, n_pitches):
            freq = 440.0 * 2.0 ** ((p - 69) / 12.0) * harmonic
            key = round(freq, 4)
            b = bin_cache.get(key)
            if b is None:
                b = min(max(int(round(freq / freq_res)), 1), n_bins - 1)
                bin_cache[key] = b
            lo, hi = max(1, b - 1), min(n_bins, b + 2)
            sal[:, p] += weight * spec[:, lo:hi].max(axis=1)
    sal = np.sqrt(sal)
    tail = sal[:, n_pitches - 12:].copy()
    sal[:, : n_pitches - 12] = np.maximum(
        sal[:, : n_pitches - 12] - _OCTAVE_SUBTRACT * sal[:, 12:], 0.0
    )
    sal[:, n_pitches - 12:] = tail
    sal[:, :PITCH_LOW] = -np.inf
    return sal


def _track_pitch(sal: np.ndarray) -> np.ndarray:
    """逐帧 argmax 出音高轨；低于门槛的帧记 -1（无声）。"""
    best = sal.max(axis=1)
    pitch = sal.argmax(axis=1).astype(int)
    global_max = float(best.max())
    if global_max <= 0:
        return np.full(len(sal), -1, dtype=int)
    pitch[best < _VOICED_RATIO * global_max] = -1
    return pitch


def _split_run_at_dips(sal_run: np.ndarray, dip_ratio: float) -> List[int]:
    """在同音 run 的 salience 曲线里找「相对凹谷」切点（重复音的重音边界）。

    切点 = 局部极小，且其值 < dip_ratio × max(左侧平台, 右侧平台)（各取 ±5 帧
    邻域的最大值）。返回切点帧号列表（run 内局部下标，切点归左段末尾）。

    为什么用相对凹谷而不是绝对低谷：93ms 窗对首尾相接的重复音永远有重叠，
    salience 谷不到中位数的 35%（实测 64%），绝对判据抓不到；而「塌到两侧
    平台的 70% 以下」只出现在真正的重新起音（颤音谷差通常 <15%，不会误切）。
    真正的 legato 重复音（无任何重音）任何方法都分不开，这是内置后端的边界。
    """
    n = len(sal_run)
    if n < 7:
        return []
    cuts: List[int] = []
    for i in range(2, n - 2):
        v = float(sal_run[i])
        if v > sal_run[i - 1] or v > sal_run[i + 1]:
            continue  # 需要局部极小（允许平台）
        left = float(sal_run[max(0, i - 5) : i].max())
        right = float(sal_run[i + 1 : min(n, i + 6)].max())
        if left > 0 and v < dip_ratio * max(left, right):
            cuts.append(i)
    return cuts


def _extract_segments(
    pitch_track: np.ndarray,
    sal: np.ndarray,
    hop: int,
    sr: int,
    min_note_s: float,
    merge_gap_s: float,
) -> List[Tuple[int, int, int]]:
    """音高轨 → 段列表 ``(pitch, start_frame, end_frame)``（end 为排他边界）。

    顺序（语义不能乱）：
    1. 压缩同音高连续帧为 run（-1 无声帧天然断开 run）；
    2. 同音高相邻 run 的无声间隙 ≤ merge_gap_s 则合并；
    3. run 内部按 salience 凹谷切分重复音（**切完不再合并**，否则白切）；
    4. 短于 min_note_s 的段丢弃。
    """
    runs: List[Tuple[int, int, int]] = []
    cur_p, cur_s = -1, 0
    for i, p in enumerate(pitch_track):
        if p != cur_p:
            if cur_p >= 0:
                runs.append((cur_p, cur_s, i))
            cur_p, cur_s = int(p), i
    if cur_p >= 0:
        runs.append((cur_p, cur_s, len(pitch_track)))

    merged: List[List[int]] = []
    for p, s, e in runs:
        if merged and merged[-1][0] == p and (s - merged[-1][2]) * hop / sr <= merge_gap_s:
            merged[-1][2] = e
        else:
            merged.append([p, s, e])

    segments: List[Tuple[int, int, int]] = []
    for p, s, e in merged:
        cuts = _split_run_at_dips(sal[s:e, p], _DIP_RATIO)
        bounds = [s] + [s + c + 1 for c in cuts] + [e]
        for a, b in zip(bounds, bounds[1:]):
            if b > a:
                segments.append((p, a, b))
    return [(p, s, e) for p, s, e in segments if (e - s) * hop / sr >= min_note_s]


def _velocity_for(spec: np.ndarray, freq_res: float, pitch: int, s: int, e: int) -> int:
    """用段内基频 bin 的平均幅度归一到力度（相对全谱最大幅度的开方映射）。"""
    freq = 440.0 * 2.0 ** ((pitch - 69) / 12.0)
    b = min(max(int(round(freq / freq_res)), 1), spec.shape[1] - 1)
    lo, hi = max(1, b - 1), min(spec.shape[1], b + 2)
    energy = float(spec[s:e, lo:hi].max(axis=1).mean())
    global_max = float(spec[:, 1:].max()) or 1.0
    return int(np.clip(round(36 + 84 * np.sqrt(energy / global_max)), 1, 127))


def transcribe_wav(
    wav_path: str | Path,
    options: Optional[TranscribeOptions] = None,
) -> TranscribeResult:
    """把音频转成单轨 MIDI（NoteSequence）。

    Args:
        wav_path: 输入音频路径。
        options: 转谱选项；None 用默认（自动测速 + 1/16 量化）。

    Returns:
        :class:`TranscribeResult`（含量化后的 NoteSequence 与调试明细）。

    Raises:
        InputFileError: 文件不存在/无法解析（退出码 3）。
        ParameterError: 选项非法 / 音频过短 / 近静音（退出码 1）。
    """
    opts = options or TranscribeOptions()

    tempo = estimate_bpm(wav_path)
    detected_bpm = tempo.bpm
    used_bpm = float(opts.bpm) if opts.bpm is not None else detected_bpm

    mono, sr = read_wav_mono(wav_path)
    spec = stft_magnitude(mono, TRANSCRIBE_FRAME, TRANSCRIBE_HOP)
    if spec.shape[0] < 2:
        raise ParameterError(f"音频过短（{tempo.duration:.2f}s），帧数不足以转谱", code=1)
    freq_res = sr / TRANSCRIBE_FRAME

    sal = _pitch_salience(spec, freq_res)
    pitch_track = _track_pitch(sal)
    segments = _extract_segments(
        pitch_track,
        sal,
        TRANSCRIBE_HOP,
        sr,
        min_note_s=opts.min_note_ms / 1000.0,
        merge_gap_s=opts.merge_gap_ms / 1000.0,
    )

    def frame_seconds(f: float) -> float:
        """帧号 → 秒（STFT 惯例：时间戳取帧中心，理由见模块文档）。"""
        return (f + 0.5) * TRANSCRIBE_HOP / sr

    grid = opts.grid_beats
    beats_per_second = used_bpm / 60.0
    notes: List[Note] = []
    detail: List[Tuple[int, float, float, float, float]] = []
    for p, s, e in segments:
        start_s = frame_seconds(s)
        end_s = frame_seconds(e)
        start_b = start_s * beats_per_second
        end_b = end_s * beats_per_second
        start_q = max(0.0, round(start_b / grid) * grid)
        end_q = max(start_q + grid, round(end_b / grid) * grid)
        notes.append(
            Note(
                pitch=int(p),
                start=round(start_q, 6),
                duration=round(end_q - start_q, 6),
                velocity=_velocity_for(spec, freq_res, int(p), s, e),
            )
        )
        detail.append((int(p), start_s, end_s, start_q, end_q - start_q))

    last_end_beat = max((d[2] for d in detail), default=0.0) * beats_per_second
    seq = NoteSequence(
        bpm=int(round(used_bpm)),
        key="C major",
        time_signature="4/4",
        bars=max(1, int(np.ceil(last_end_beat / 4))),
        style="transcribed",
    )
    seq.add_track(opts.track_name, opts.program, 0, notes)

    pitches = [n.pitch for n in notes]
    return TranscribeResult(
        seq=seq,
        detected_bpm=detected_bpm,
        confidence=tempo.confidence,
        beat_offset=tempo.beat_offset,
        note_count=len(notes),
        pitch_range=(min(pitches), max(pitches)) if pitches else (0, 0),
        segments=detail,
    )


def write_transcribed_midi(
    result: TranscribeResult,
    output_path: str | Path,
) -> str:
    """把转谱结果落盘为 .mid，返回绝对路径。"""
    return MidiDocument.from_sequence(result.seq).write(output_path)
