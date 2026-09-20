# videomaker v0.3.0 交付报告

> 日期：2026-08-28/29 ｜ 版本：0.2.1 → 0.3.0
> 主题：**多格式输入 + 多轨混音 + 分轨可视化**（并补上 v0.2 推迟的滚动波形）

---

## 交付概要

| Wave | 任务 | 状态 |
|------|------|------|
| W1 | 环境核查（MP3/SoundFont/fluidsynth） | ✅ |
| W2 | 多格式输入（WAV/MP3/FLAC/OGG/MIDI→WAV） | ✅ |
| W3 | 多轨混音（重采样对齐/增益/声像/归一化） | ✅ |
| W4 | 分轨可视化（tracks 样式） | ✅ |
| W5 | 滚动波形（waveform_scroll 样式） | ✅ |
| W6 | 测试补强 + 文档更新 | ✅ |

## 核心能力

### 多格式输入

| 格式 | 处理 |
|---|---|
| WAV / FLAC / OGG | soundfile 直读 |
| **MP3** | soundfile 0.14 **原生支持**（无需外部转换） |
| **MIDI** | 复用 SNG `FluidSynthRenderer` → 临时 WAV（module/ 真实引擎 + SoundFont） |

MIDI 渲染资源（module/ 默认布局，可覆盖）：
- `module/fluidsynth/bin/fluidsynth.exe`
- `module/GeneralUser_GS/GeneralUser-GS/GeneralUser-GS.sf2`（备用 ColomboGMGS2）

### 多轨混音

```bash
videomaker render drums.wav "bass.mid:gain=0.8:pan=-0.3" melody.mp3 -p douyin -s tracks
```

流程：逐轨加载 → 重采样统一 44.1k → 长度对齐（默认到最长轨）→
**等功率声像定律** + 轨道增益 → **峰值归一化 -1 dBFS**（防削波）

**双产物**：`xxx.mp4`（视频）+ `xxx.mix.wav`（混音，可直接纯音频发布）

### 分轨可视化（`--style tracks`）

- 垂直排列每轨频谱，HSL 色环区分轨道颜色
- **逐轨独立归一化**（弱轨也清晰可见）
- 顶部显示轨名

### 滚动波形（`--style waveform_scroll`）

播放头居中，预计算波形查表 + 6s 滑动窗口；已播放区半透明填充 + 白色播放头线。

## 新增/修改文件

```
src/videomaker/
  audio_io.py          # 新增：多格式加载（WAV/MP3/MIDI→WAV）
  mixer.py             # 新增：多轨混音（TrackSpec/mix_tracks）
  visuals/tracks.py    # 新增：TracksVisualizer + WaveformScrollVisualizer
  analysis/audio_analysis.py  # 加 analyze_multitrack（逐轨频谱/RMS）
  videomaker.py        # 加 video_multitrack 入口
  cli.py               # render 支持多文件（自动多轨模式）
  visuals/__init__.py  # 注册表加 tracks/waveform_scroll
  engines/frame_engine.py  # 支持外部注入 analysis
  compositor.py        # 透传 analysis
tests/test_videomaker_v03.py  # 新增 23 测试
docs/videomaker.md     # 多格式/多轨/分轨章节
README.md              # videomaker 章节更新
```

## 验证证据

| 测试 | 结果 |
|------|------|
| MIDI 单轨 → 视频 | 19.1s / 1920×1080 ✅ |
| MIDI 双轨混音 | 1080×1920，双轨画面（上 std=38.9 / 下 std=41.6）✅ |
| 终极组合（WAV+MIDI 混音 + 分轨 + logo + 标题 + official） | 1080×1350，logo 红 4770 px，混音 WAV 同产 ✅ |
| 滚动波形 | 帧间差异 9.7（波形流动）✅ |
| MP3 加载 | soundfile 原生，19.1s / 44.1k ✅ |
| **测试** | v0.3 23 例 + v0.2 33 例 = **56 例全通过**；全量回归无失败 |

## 修复的 2 个问题

1. **`video_multitrack` 缺 import**（`analyze_multitrack` NameError）→ 补导入
2. **分轨帧差异测试失败** → 排查确认为**测试数据特性**（恒定正弦频谱恒定，
   帧间必然相同），非渲染器 bug → 改用 AM（调幅）信号验证

## 已知限制

- Windows 绝对路径含盘符（`C:\music\a.wav`）不支持 `:gain=` 冒号参数语法
  （冒号被解析切分）；请用相对路径或程序化 `TrackSpec(path=...)`
- MIDI 渲染耗时与音频时长正相关（19s MIDI ≈ 20s 渲染），长曲需耐心
- `tracks` 样式建议不超过 6 轨（轨道高度过低影响可读性）
