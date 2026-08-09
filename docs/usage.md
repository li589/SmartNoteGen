# SmartNoteGen 使用指南

> 版本：v0.1.0（P0）｜ 配套文档：docs/PRD.md、docs/architecture.md、docs/task-plan.md

---

## 1. 全局参数

```bash
smartnotegen [--config PATH] [--verbose] [--version] <子命令>
```

| 参数 | 说明 |
|---|---|
| `--config PATH` / `-c` | 指定配置文件（默认查找项目根 `smartnotegen.toml`） |
| `--verbose` | DEBUG 级日志 |
| `--version` | 打印版本号 |

配置合并优先级（低→高）：内置默认值 < `config/default.toml` < 用户配置文件 < CLI 参数。

---

## 2. 子命令详解

### 2.1 `generate midi` — 程序化多轨 MIDI

```bash
smartnotegen generate midi [--chords CHORDS] [--bpm N] [--key KEY] [--time-signature TS]
                           [--bars N] [--style STYLE] [--seed N] [--with-drums]
                           [--track NAME ...] [--output PATH]
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--chords` | `C-G-Am-F` | 和弦进行，`-` 分隔；支持 C/Am/G7/Am7/Cmaj7/Csus4 等 |
| `--bpm` | 120 | 速度 |
| `--key` | `C major` | 调式（music21 可解析，如 `A minor`、`F# minor`） |
| `--time-signature` | `4/4` | 拍号 |
| `--bars` | 8 | 小节数 |
| `--style` | `pop` | 风格：`pop` / `rock` / `electronic` / `classical` |
| `--seed` | 配置值 | 随机种子（可复现） |
| `--with-drums` | false | 追加第 4 轨鼓（通道 9） |
| `--track` | chords melody bass | 轨道名，可多次指定 |
| `--output` | 自动命名 | 输出 .mid 路径 |

**示例：**
```bash
smartnotegen generate midi --chords "C-G-Am-F" --bpm 120 --bars 8 --seed 42
smartnotegen generate midi --chords "G-D-Em-C" --style rock --with-drums --seed 7
```

**可复现性：** 相同参数 + 相同 `--seed` → 字节级一致的 .mid。

### 2.2 `generate melody` — music21 乐理旋律 + 变奏

```bash
smartnotegen generate melody [--key KEY] [--chords CHORDS] [--variations N] [--seed N] ...
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--variations` | 1 | 变奏数量；kinds = `rhythm`（节奏）/ `ornament`（装饰音）/ `retrograde`（逆行），按序循环 |
| 其余 | 同 `generate midi` | — |

输出 1 个主旋律轨 + N 个变奏轨（同文件多轨）。强拍（第 1、3 拍）与句尾目标音对齐和弦音 ≥80%，全部音符在调式音阶内。

**示例：**
```bash
smartnotegen generate melody --key "C major" --chords C-G-Am-F --variations 3 --seed 5
```

### 2.3 `render` — MIDI → WAV

```bash
smartnotegen render --input xxx.mid [--soundfont PATH] [--fluidsynth PATH] [--output PATH]
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--input` | 必填 | 输入 .mid |
| `--soundfont` | 配置值 | .sf2 路径 |
| `--fluidsynth` | 配置值 | fluidsynth 可执行文件（PATH 名或绝对路径） |
| `--output` | 输入同名 `_rendered.wav` | 输出 .wav |

输出 44.1kHz / 16bit WAV。fluidsynth 缺失 → 退出码 4；SoundFont 缺失 → 退出码 2。

### 2.4 `export suno` — Suno 合规导出

```bash
smartnotegen export suno --input xxx.wav [--duration 10..30] [--format wav|mp3]
                         [--sample-rate N] [--bit-depth N] [--fade-ms N] [--output PATH]
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--duration` | 25 | 目标时长，**必须在 10–30s**（越界 → 退出码 5） |
| `--format` | `wav` | `wav` / `mp3`（mp3 需 lameenc） |
| `--sample-rate` | 44100 | 输出采样率 |
| `--bit-depth` | 16 | 输出位深 |
| `--fade-ms` | 50 | 淡入淡出毫秒数 |

处理链：合规校验 → 裁剪/循环至目标时长 → 淡入淡出 → 重采样 → -1dBFS 归一化 → 写出。
输入不足目标时长时自动循环补齐。

### 2.5 `pipeline` — 一键闭环

```bash
smartnotegen pipeline [--chords ...] [--bpm ...] [--key ...] [--bars ...]
                      [--style ...] [--seed ...] [--with-drums]
                      [--duration 10..30] [--format wav|mp3]
```

零参数即跑通 demo 管线：generate → render → export，中间产物自动清理，
最终输出 `output/YYYYMMDD/{style}_{key}_{bpm}_{bars}bars_{seed}_{ts}_suno{duration}s.{ext}`。

### 2.6 `config init` / `config show`

```bash
smartnotegen config init [--path smartnotegen.toml]   # 生成配置文件模板
smartnotegen config show                              # 打印合并后的生效配置
```

### 2.7 `batch`（P1-3 骨架）

```bash
smartnotegen batch --count 5 --seed 42
```

P0 版本提示"批量生成属于 P1-3 里程碑"（退出码 1）。

### 2.8 `ai musicgen` / `ai diffrhythm`（P1 骨架）

```bash
smartnotegen ai musicgen --input melody.wav --prompt "upbeat pop"
smartnotegen ai diffrhythm --prompt "slow ballad"
```

P0 环境未安装 P1 依赖 → 明确提示安装 `requirements/ai.txt`（含 CUDA 版 torch），退出码 6。

---

## 3. 配置文件详解

```toml
[paths]
soundfont = "assets/soundfonts/GeneralUser_GS_v1.471.sf2"  # SoundFont 路径
fluidsynth = "fluidsynth"                                   # fluidsynth 可执行名/绝对路径
output_dir = "output"                                       # 输出目录

[defaults]
bpm = 120
key = "C major"
time_signature = "4/4"
bars = 8
chords = "C-G-Am-F"
style = "pop"
tracks = ["chords", "melody", "bass"]
with_drums = false

[export]
format = "wav"
sample_rate = 44100
bit_depth = 16
duration = 25
fade_ms = 50

[random]
seed = null
```

---

## 4. 错误码与排查

| 退出码 | 含义 | 排查 |
|---|---|---|
| 0 | 成功 | — |
| 1 | 参数/通用错误 | 检查和弦符号、参数组合 |
| 2 | 配置错误 | `config show` 查看生效配置；检查 SoundFont 路径 |
| 3 | 输入文件错误 | 确认 .mid/.wav 存在且可解析 |
| 4 | 渲染失败 | 安装 fluidsynth（README 指引）并配置路径 |
| 5 | 导出失败 | 时长需在 10–30s；mp3 需 `pip install lameenc` |
| 6 | AI 不可用 | `pip install -r requirements/ai.txt`（含 CUDA torch） |
