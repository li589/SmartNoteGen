"""HTML 预览页生成器（P3-A1）+ 音频特征计算（P3-A3）。

核心功能：
1. 从 WAV 文件读取音频 → 降采样波形 → 计算频谱 → 构建自包含 HTML
2. 计算音频特征（RMS/峰值/频谱中心/频段能量）
3. 支持单文件预览和批量预览

所有数据以 base64 内嵌 HTML，无外部依赖，离线可打开。
"""

from __future__ import annotations

import base64
import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, List, Optional

import numpy as np
import soundfile as sf


# ---------------------------------------------------------------------------
# 音频特征（P3-A3）
# ---------------------------------------------------------------------------

@dataclass
class AudioFeatures:
    """音频特征摘要。"""
    rms_db: float = 0.0          # 平均 RMS（dBFS）
    peak_db: float = 0.0         # 峰值（dBFS）
    spectral_centroid: float = 0.0  # 频谱中心（Hz）
    band_energy: dict[str, float] = field(default_factory=lambda: {
        "low": 0.0, "mid": 0.0, "high": 0.0
    })


def compute_audio_features(wav_path: str | Path) -> AudioFeatures:
    """读取 WAV 并计算音频特征。

    Args:
        wav_path: WAV 文件路径。

    Returns:
        AudioFeatures 实例。
    """
    audio, sr = sf.read(str(wav_path))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)  # 立体声混为单声道

    features = AudioFeatures()

    # 峰值（dBFS）
    peak = float(np.max(np.abs(audio)))
    features.peak_db = round(20 * math.log10(peak + 1e-10), 1)

    # RMS（dBFS）
    rms = float(np.sqrt(np.mean(audio ** 2)))
    features.rms_db = round(20 * math.log10(rms + 1e-10), 1)

    # 频谱中心（STFT）
    n_fft = min(2048, len(audio))
    hop_length = n_fft // 4
    if len(audio) > n_fft:
        # 手动计算 STFT
        freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
        n_frames = (len(audio) - n_fft) // hop_length + 1
        centroid_sum = 0.0
        energy_sum = 0.0
        low_energy = 0.0
        mid_energy = 0.0
        high_energy = 0.0
        low_cut = 250
        high_cut = 4000

        for i in range(0, n_frames * hop_length, hop_length):
            frame = audio[i:i + n_fft]
            if len(frame) < n_fft:
                frame = np.pad(frame, (0, n_fft - len(frame)))
            window = np.hanning(n_fft) * frame
            spectrum = np.abs(np.fft.rfft(window))
            spec_energy = spectrum ** 2
            total = float(np.sum(spec_energy))
            if total > 0:
                centroid_sum += float(np.sum(freqs * spec_energy)) / total
                energy_sum += 1.0
                # 频段能量
                for freq, e in zip(freqs, spec_energy):
                    if freq <= low_cut:
                        low_energy += float(e)
                    elif freq <= high_cut:
                        mid_energy += float(e)
                    else:
                        high_energy += float(e)

        if energy_sum > 0:
            features.spectral_centroid = round(centroid_sum / energy_sum, 1)

        total_band = low_energy + mid_energy + high_energy
        if total_band > 0:
            features.band_energy = {
                "low": round(low_energy / total_band, 2),
                "mid": round(mid_energy / total_band, 2),
                "high": round(high_energy / total_band, 2),
            }

    return features


# ---------------------------------------------------------------------------
# 预览页生成器（P3-A1）
# ---------------------------------------------------------------------------

class PreviewGenerator:
    """生成自包含 HTML 预览页。

    单文件模式：pipeline/render 后调用
    批量模式：batch 后调用
    """

    def __init__(self, max_waveform_points: int = 2000) -> None:
        self.max_waveform_points = max_waveform_points

    def generate_for(
        self,
        wav_path: str | Path,
        metadata: dict[str, Any],
        output_dir: str | Path,
        label: str = "",
        score_svg: str = "",
    ) -> str:
        """为单个 WAV 生成预览页。

        Args:
            wav_path: WAV 文件路径。
            metadata: 元数据字典（用于展示）。
            output_dir: 输出目录（preview.html 写入此目录）。
            label: 显示标签，为空时用文件名。
            score_svg: 可选，五线谱 SVG 文本；非空时在卡片内以折叠区**内联**展示
                （内联而非 ``<img src=data:>``：内联 SVG 随容器缩放、可选中文本，
                且深色主题下靠自身白底保证可读）。

        Returns:
            preview.html 的绝对路径。
        """
        wav_path = Path(wav_path)
        audio, sr = self._load_audio(wav_path)
        label = label or wav_path.name

        # 波形数据
        waveform = self._compute_waveform(audio)

        # 频谱数据
        spectrogram = self._compute_spectrogram(audio, sr)

        # 音频 base64
        audio_b64 = self._audio_to_base64(wav_path)

        # 特征
        features = compute_audio_features(wav_path)

        # 构建 HTML
        item = {
            "label": label,
            "audio_base64": audio_b64,
            "waveform": waveform,
            "spectrogram": spectrogram,
            "metadata": dict(metadata),
            "features": asdict(features),
            "score_svg": score_svg or "",
        }

        html = self._build_html([item], is_batch=False)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "preview.html"
        out_path.write_text(html, encoding="utf-8")
        return str(out_path)

    def generate_batch(
        self,
        items: list[dict[str, Any]],
        output_dir: str | Path,
    ) -> str:
        """为批量产物生成预览总览页。

        Args:
            items: 预览项列表，每项含 label/audio_base64/waveform/spectrogram/metadata/features。
            output_dir: 输出目录。

        Returns:
            preview.html 的绝对路径。
        """
        html = self._build_html(items, is_batch=True)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "preview.html"
        out_path.write_text(html, encoding="utf-8")
        return str(out_path)

    # -- 内部方法 ----------------------------------------------------------

    def _load_audio(self, wav_path: Path) -> tuple[np.ndarray, int]:
        """读取 WAV，返回 (audio_array, sample_rate)。"""
        audio, sr = sf.read(str(wav_path))
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        return audio, int(sr)

    def _compute_waveform(self, audio: np.ndarray) -> list[float]:
        """等距降采样，保持包络形状。"""
        n = self.max_waveform_points
        if len(audio) <= n:
            return audio.tolist()
        indices = np.linspace(0, len(audio) - 1, n, dtype=int)
        return audio[indices].tolist()

    def _compute_spectrogram(
        self, audio: np.ndarray, sr: int,
        n_fft: int = 512, hop_length: int = 128,
    ) -> list[list[float]]:
        """STFT → 频谱矩阵 → 降采样 → 归一化。"""
        if len(audio) < n_fft:
            return []

        # 限制帧数（最多 200 帧，避免 HTML 过大）
        n_frames = (len(audio) - n_fft) // hop_length + 1
        max_frames = 200
        if n_frames > max_frames:
            step = n_frames // max_frames
            n_frames = max_frames
        else:
            step = 1

        n_bins = n_fft // 2 + 1
        # 降采样频率轴（保留低频细节）
        max_bins = 64
        bin_step = max(1, n_bins // max_bins)

        spectrogram: list[list[float]] = []
        for i in range(0, n_frames * step * hop_length, step * hop_length):
            if i + n_fft > len(audio):
                break
            frame = audio[i:i + n_fft]
            window = np.hanning(n_fft) * frame
            spectrum = np.abs(np.fft.rfft(window))
            # 降采样
            spec_down = []
            for b in range(0, len(spectrum), bin_step):
                spec_down.append(float(np.mean(spectrum[b:b + bin_step])))
            spectrogram.append(spec_down)

        if not spectrogram:
            return []

        # 归一化到 0-1
        arr = np.array(spectrogram)
        arr_min, arr_max = float(arr.min()), float(arr.max())
        if arr_max - arr_min > 1e-10:
            arr = (arr - arr_min) / (arr_max - arr_min)
        return arr.tolist()

    def _audio_to_base64(self, wav_path: Path) -> str:
        """WAV 文件 → base64 字符串（data URI 格式）。"""
        data = wav_path.read_bytes()
        return base64.b64encode(data).decode("ascii")

    def _build_html(
        self, items: list[dict[str, Any]],
        is_batch: bool = False,
    ) -> str:
        """构建自包含 HTML 字符串。"""
        items_json = json.dumps(items, ensure_ascii=False)
        items_count = len(items)
        title = f"SmartNoteGen 预览 — {items_count} 个变体" if is_batch else "SmartNoteGen 预览"

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #1a1a2e;
    color: #e0e0e0;
    padding: 20px;
  }}
  @media (prefers-color-scheme: light) {{
    body {{ background: #f5f5f5; color: #333; }}
    .card {{ background: #fff; border-color: #ddd; }}
    .meta-label {{ color: #666; }}
    .meta-value {{ color: #222; }}
  }}
  h1 {{ font-size: 1.3em; margin-bottom: 16px; color: #8899cc; }}
  .card {{
    background: #16213e;
    border: 1px solid #2a3a5e;
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 16px;
  }}
  .card-title {{
    font-size: 1em;
    font-weight: 600;
    margin-bottom: 8px;
    color: #aaccff;
    word-break: break-all;
  }}
  canvas {{
    width: 100%;
    height: 120px;
    display: block;
    border-radius: 6px;
    background: #0d1b2a;
    margin-bottom: 8px;
  }}
  canvas.spectrogram {{ height: 80px; }}
  .controls {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 8px 0;
  }}
  button {{
    background: #2a5a9e;
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 6px 16px;
    cursor: pointer;
    font-size: 0.9em;
  }}
  button:hover {{ background: #3a6abe; }}
  button.pause {{ background: #8a2a2a; }}
  button.pause:hover {{ background: #aa3a3a; }}
  .meta-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 4px 12px;
    font-size: 0.85em;
    margin-top: 8px;
  }}
  .meta-label {{ color: #8899aa; }}
  .meta-value {{ color: #ddeeff; }}
  .spectrogram-toggle {{
    background: none;
    border: 1px solid #3a5a8e;
    color: #8899cc;
    font-size: 0.8em;
    padding: 2px 8px;
    cursor: pointer;
    border-radius: 4px;
  }}
  .spectrogram-toggle:hover {{ background: #1a2a4e; }}
  .spectrogram-wrap {{ display: none; }}
  .spectrogram-wrap.visible {{ display: block; }}
  .badge {{
    display: inline-block;
    background: #2a4a6e;
    color: #aaccff;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.8em;
    margin-right: 4px;
  }}
  .score-wrap {{ margin-top: 12px; }}
  .score-wrap > summary {{
    cursor: pointer;
    font-size: 0.85em;
    color: #8899cc;
    padding: 4px 0;
    user-select: none;
  }}
  .score-wrap > summary:hover {{ color: #aaccff; }}
  .score-svg {{
    background: #ffffff;
    border-radius: 6px;
    padding: 10px;
    margin-top: 8px;
    overflow-x: auto;
    border: 1px solid #2a3a5e;
  }}
  /* 内联 SVG 随容器缩放；谱面本身是固定像素画布，不缩会溢出卡片 */
  .score-svg svg {{ max-width: 100%; height: auto; display: block; }}
</style>
</head>
<body>
<h1>{"📊 " + title if is_batch else "🎵 " + title}</h1>
<div id="items"></div>
<script>
const items = {items_json};

function renderWaveform(canvas, data) {{
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const mid = h / 2;
  ctx.strokeStyle = "#4a9eff";
  ctx.lineWidth = 1.5;
  ctx.beginPath();

  const step = Math.max(1, Math.floor(data.length / w));
  for (let x = 0; x < w && x * step < data.length; x++) {{
    const val = data[x * step];
    const y = mid + val * (mid - 4);
    if (x === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }}
  ctx.stroke();

  // 填充
  ctx.strokeStyle = "rgba(74, 158, 255, 0.2)";
  ctx.lineTo(w, mid);
  ctx.lineTo(0, mid);
  ctx.closePath();
  ctx.fillStyle = "rgba(74, 158, 255, 0.08)";
  ctx.fill();
}}

function renderSpectrogram(canvas, data) {{
  if (!data || data.length === 0) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const imgData = ctx.createImageData(w, h);
  const rows = data.length;
  const cols = data[0].length;

  for (let y = 0; y < h; y++) {{
    for (let x = 0; x < w; x++) {{
      const row = Math.floor((y / h) * rows);
      const col = Math.floor((x / w) * cols);
      const v = Math.min(1, Math.max(0, data[Math.min(row, rows-1)][Math.min(col, cols-1)]));
      const idx = (y * w + x) * 4;
      // 热力图：蓝 → 青 → 黄 → 红
      if (v < 0.25) {{
        imgData.data[idx] = 0;
        imgData.data[idx+1] = Math.floor(v * 4 * 255);
        imgData.data[idx+2] = 255;
      }} else if (v < 0.5) {{
        imgData.data[idx] = 0;
        imgData.data[idx+1] = 255;
        imgData.data[idx+2] = Math.floor((1 - (v-0.25)*4) * 255);
      }} else if (v < 0.75) {{
        imgData.data[idx] = Math.floor((v-0.5) * 4 * 255);
        imgData.data[idx+1] = 255;
        imgData.data[idx+2] = 0;
      }} else {{
        imgData.data[idx] = 255;
        imgData.data[idx+1] = Math.floor((1 - (v-0.75)*4) * 255);
        imgData.data[idx+2] = 0;
      }}
      imgData.data[idx+3] = 255;
    }}
  }}
  ctx.putImageData(imgData, 0, 0);
}}

function buildCard(item, idx) {{
  const div = document.createElement("div");
  div.className = "card";

  let html = `<div class="card-title">${{item.label}}</div>`;

  // 波形 Canvas
  html += `<canvas id="wave-${{idx}}" width="800" height="120"></canvas>`;

  // 控制按钮
  html += `<div class="controls">`;
  html += `<button onclick="playAudio('audio-${{idx}}', this)">▶ 播放</button>`;
  html += `<span class="badge">${{item.features.peak_db || 0}} dBFS</span>`;
  html += `<span class="badge">${{item.features.rms_db || 0}} dB RMS</span>`;
  if (item.features.spectral_centroid) {{
    html += `<span class="badge">${{Math.round(item.features.spectral_centroid)}} Hz</span>`;
  }}
  html += `<button class="spectrogram-toggle" onclick="toggleSpectrogram('spec-${{idx}}')">频谱</button>`;
  html += `</div>`;

  // 频谱
  html += `<div class="spectrogram-wrap" id="spec-${{idx}}">`;
  html += `<canvas id="spec-canvas-${{idx}}" class="spectrogram" width="800" height="80"></canvas>`;
  html += `</div>`;

  // 五线谱谱面（可选，内联 SVG）
  if (item.score_svg) {{
    html += `<details class="score-wrap">`;
    html += `<summary>五线谱谱面（点击展开）</summary>`;
    html += `<div class="score-svg">${{item.score_svg}}</div>`;
    html += `</details>`;
  }}

  // 音频
  html += `<audio id="audio-${{idx}}" preload="none" style="display:none"></audio>`;

  // 元数据
  html += `<div class="meta-grid">`;
  const meta = item.metadata || {{}};
  for (const [k, v] of Object.entries(meta)) {{
    html += `<div><span class="meta-label">${{k}}</span> <span class="meta-value">${{v}}</span></div>`;
  }}
  // 频段能量
  const fe = item.features.band_energy || {{}};
  if (fe.low !== undefined) {{
    html += `<div><span class="meta-label">低频</span> <span class="meta-value">${{Math.round(fe.low*100)}}%</span></div>`;
    html += `<div><span class="meta-label">中频</span> <span class="meta-value">${{Math.round(fe.mid*100)}}%</span></div>`;
    html += `<div><span class="meta-label">高频</span> <span class="meta-value">${{Math.round(fe.high*100)}}%</span></div>`;
  }}
  html += `</div>`;

  div.innerHTML = html;
  return div;
}}

function playAudio(audioId, btn) {{
  const audio = document.getElementById(audioId);
  if (!audio.src) {{
    const idx = parseInt(audioId.split("-")[1]);
    audio.src = "data:audio/wav;base64," + items[idx].audio_base64;
  }}
  if (audio.paused) {{
    audio.play();
    btn.textContent = "⏸ 暂停";
    btn.className = "pause";
  }} else {{
    audio.pause();
    btn.textContent = "▶ 播放";
    btn.className = "";
  }}
  audio.onended = () => {{ btn.textContent = "▶ 播放"; btn.className = ""; }};
}}

function toggleSpectrogram(id) {{
  const el = document.getElementById(id);
  el.classList.toggle("visible");
}}

// 渲染
const container = document.getElementById("items");
items.forEach((item, idx) => {{
  container.appendChild(buildCard(item, idx));
  // 绘制波形
  const waveCanvas = document.getElementById("wave-" + idx);
  if (waveCanvas) {{
    requestAnimationFrame(() => renderWaveform(waveCanvas, item.waveform));
  }}
  // 绘制频谱（延迟渲染，等用户点击展开）
  const specCanvas = document.getElementById("spec-canvas-" + idx);
  if (specCanvas) {{
    requestAnimationFrame(() => renderSpectrogram(specCanvas, item.spectrogram));
  }}
}});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# 视频预览：缩略帧 + 时间轴 scrub（R15）
# ---------------------------------------------------------------------------

#: 缩略图/HTML 的输出根目录名（位于 output/ 下，用户裁定：可放 output/ 但须新建目录）
PREVIEW_DIR_NAME = "preview"

_VIDEO_PREVIEW_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>视频预览 __NAME__</title>
<style>
  body { background:#15151f; color:#e8e8f0; font-family:system-ui,"Microsoft YaHei",sans-serif; margin:24px; }
  h1 { font-size:18px; margin-bottom:4px; }
  .meta { color:#9aa; font-size:12px; margin-bottom:12px; }
  video { width:100%; max-width:960px; background:#000; border-radius:8px; }
  .strip { display:flex; gap:8px; flex-wrap:wrap; margin-top:16px; }
  .thumb { background:#1d1d2b; border:2px solid #333; border-radius:6px;
           cursor:pointer; padding:0; overflow:hidden; color:inherit; }
  .thumb:hover { border-color:#00c8ff; }
  .thumb img { display:block; width:160px; height:90px; object-fit:cover; }
  .thumb span { display:block; color:#9aa; font-size:11px; padding:3px 0; }
</style>
</head>
<body>
<h1>__NAME__</h1>
<div class="meta">时长 __DURATION__ s · __NFRAMES__ 个缩略帧（点击缩略图跳转）</div>
__VIDEO__
<div class="strip">
__THUMBS__
</div>
<script>
function seekTo(t) {
  var v = document.getElementById("vp");
  if (!v) return;
  v.currentTime = t;
  var p = v.play();
  if (p && p.catch) { p.catch(function () {}); }
}
</script>
</body>
</html>"""


def _esc(s: str) -> str:
    """最小 HTML 转义（避免文件名/路径破坏标签）。"""
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _default_runner(cmd: List[str]) -> str:
    """默认命令执行器：跑子进程返回 stdout；非 0 退出码抛 RuntimeError。"""
    import subprocess

    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(
            f"命令失败（{res.returncode}）: {' '.join(cmd)}\n{res.stderr}"
        )
    return res.stdout


@dataclass
class PreviewFrame:
    """一个视频缩略帧。"""

    index: int
    time_s: float
    path: Path  # 缩略图绝对路径
    rel_path: str  # 相对 HTML 的引用路径（同目录 -> 仅文件名）


def probe_duration(video_path: str | Path, runner: Optional[Callable] = None) -> float:
    """用 ffprobe 探测视频时长（秒）。

    Args:
        runner: 命令执行器（**注入点**，测试可替换）；None 用子进程。

    Raises:
        RuntimeError: ffprobe 执行失败或输出无法解析为浮点。
    """
    run = runner or _default_runner
    out = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(video_path),
        ]
    )
    try:
        return float(str(out).strip().splitlines()[0])
    except (ValueError, IndexError) as exc:
        raise RuntimeError(
            f"无法解析视频时长: {video_path}（ffprobe 输出: {out!r}）"
        ) from exc


def extract_preview_frames(
    video_path: str | Path,
    out_dir: str | Path,
    duration_s: Optional[float] = None,
    n: int = 6,
    runner: Optional[Callable] = None,
    ffmpeg: str = "ffmpeg",
) -> List[PreviewFrame]:
    """从视频均匀抽取 ``n`` 个缩略帧到 ``out_dir``。

    Args:
        video_path: 视频文件。
        out_dir: 缩略图输出目录（**会创建**）。
        duration_s: 时长（秒）；None 时先用 ffprobe 探测。
        n: 缩略帧数量（须 >= 1）。
        runner: 命令执行器注入点。
        ffmpeg: ffmpeg 可执行文件名/路径。

    Returns:
        按时间升序的 :class:`PreviewFrame` 列表。

    Notes:
        采样点取 ``(i + 0.5) * duration / n``——避开 0 与结尾两处边界
        （首帧常是黑场、末帧易因舍入越界）。
    """
    if n < 1:
        raise ValueError(f"缩略帧数量须 >= 1: {n}")

    video = Path(video_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run = runner or _default_runner

    if duration_s is None:
        duration_s = probe_duration(video, runner=run)
    if duration_s <= 0:
        raise ValueError(f"视频时长须 > 0: {duration_s}")

    stem = video.stem
    frames: List[PreviewFrame] = []
    for i in range(n):
        t = (i + 0.5) * duration_s / n
        name = f"{stem}_t{i:02d}.jpg"
        target = out_dir / name
        run(
            [
                ffmpeg,
                "-y",
                "-ss",
                f"{t:.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(target),
            ]
        )
        frames.append(PreviewFrame(index=i, time_s=t, path=target, rel_path=name))
    return frames


def build_video_preview_html(
    video_name: str,
    frames: List[PreviewFrame],
    duration_s: float,
    video_href: Optional[str] = None,
) -> str:
    """生成视频 scrub 预览 HTML —— **纯函数**：不跑 ffmpeg、不落盘。

    Args:
        video_name: 展示用的视频名。
        frames: 缩略帧列表（``rel_path`` 相对 HTML 所在目录引用）。
        duration_s: 视频时长（秒）。
        video_href: 视频源地址（本地文件传 ``Path.as_uri()``）；None 则只浏览缩略帧。

    Returns:
        自包含 HTML 字符串（无外部依赖，离线可打开）。
    """
    if video_href:
        video_block = (
            f'<video id="vp" src="{_esc(video_href)}" controls '
            'preload="metadata"></video>'
        )
    else:
        video_block = '<div class="meta">（未提供视频源，仅缩略帧浏览）</div>'

    thumbs = "\n".join(
        f'  <button class="thumb" onclick="seekTo({f.time_s:.3f})">'
        f'<img src="{_esc(f.rel_path)}" alt="t={f.time_s:.2f}s">'
        f"<span>{f.time_s:.2f}s</span></button>"
        for f in frames
    )

    return (
        _VIDEO_PREVIEW_TEMPLATE.replace("__NAME__", _esc(video_name))
        .replace("__DURATION__", f"{duration_s:.2f}")
        .replace("__NFRAMES__", str(len(frames)))
        .replace("__VIDEO__", video_block)
        .replace("__THUMBS__", thumbs)
    )


class VideoPreviewGenerator:
    """视频预览生成器（R15）：抽缩略帧 + 写 scrub HTML。

    输出布局（**新建目录，不污染既有 output 子目录**）::

        <output_root>/preview/<视频 stem>/preview.html
        <output_root>/preview/<视频 stem>/<stem>_t00.jpg ...
    """

    def __init__(self, n_frames: int = 6, ffmpeg: str = "ffmpeg") -> None:
        self.n_frames = n_frames
        self.ffmpeg = ffmpeg

    def output_dir_for(
        self, video_path: str | Path, output_root: str | Path | None = None
    ) -> Path:
        """解析并创建该视频的预览输出目录。"""
        if output_root is None:
            from sunoauxtool.config import Config

            output_root = getattr(Config().paths, "output_dir", "output") or "output"
        d = Path(output_root) / PREVIEW_DIR_NAME / Path(video_path).stem
        d.mkdir(parents=True, exist_ok=True)
        return d

    def generate(
        self,
        video_path: str | Path,
        output_root: str | Path | None = None,
        duration_s: Optional[float] = None,
        runner: Optional[Callable] = None,
    ) -> str:
        """生成视频预览页，返回 ``preview.html`` 的绝对路径。"""
        video = Path(video_path)
        out_dir = self.output_dir_for(video, output_root)

        if duration_s is None:
            duration_s = probe_duration(video, runner=runner)

        frames = extract_preview_frames(
            video,
            out_dir,
            duration_s=duration_s,
            n=self.n_frames,
            runner=runner,
            ffmpeg=self.ffmpeg,
        )
        href = video.resolve().as_uri() if video.is_file() else None
        html = build_video_preview_html(video.name, frames, duration_s, video_href=href)
        out_html = out_dir / "preview.html"
        out_html.write_text(html, encoding="utf-8")
        return str(out_html)