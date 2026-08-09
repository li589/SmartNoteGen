# SmartNoteGen

本地 AI 音乐生成 CLI：**程序化多轨 MIDI → 渲染 WAV → Suno 合规导出**（10–30s 纯器乐），
供用户上传 **Suno Pro** 合成成品（加人声 / 完整编曲）。

> 技术栈：Python 3.12+ · Typer · music21 · pretty_midi · FluidSynth · numpy/soundfile
> P1 可选：MusicGen / DiffRhythm（AI 扩编曲与歌曲草稿，默认不安装）

---

## 安装

### 1. 准备 venv 并安装依赖

```bash
cd SmartNoteGen
python -m venv venv
venv\Scripts\activate
pip install -r requirements/base.txt      # P0 运行依赖（不含 torch）
pip install -r requirements/dev.txt       # 开发依赖（pytest 等）
pip install -e .                          # 安装 smartnotegen 命令
```

### 2. Windows 外部程序（渲染必需）

| 程序 | 安装方式 |
|---|---|
| **FluidSynth** | 下载 fluidsynth 2.x **win64 二进制**（GitHub releases），将 `bin/` 加入 PATH，或在配置 `[paths] fluidsynth` 指定绝对路径 |
| **SoundFont** | 下载 GeneralUser GS v1.471（约 30MB）或 FluidR3，放入 `assets/soundfonts/`，在配置 `[paths] soundfont` 指定路径 |

> 不装 FluidSynth/SoundFont 时，`generate midi` / `generate melody` 仍可用；`render` / `pipeline` 会以退出码 4 提示安装指引。

### 3. MP3 导出（可选）

```bash
pip install lameenc
```

---

## 快速开始（零参数 demo）

```bash
smartnotegen pipeline
# → 读默认配置（C major / 120bpm / 8 小节 / C-G-Am-F / 3 轨）
# → 生成 MIDI → FluidSynth 渲染 WAV（44.1kHz/16bit）→ 裁剪至 25s + 淡入淡出
# → output/YYYYMMDD/pop_Cmajor_120_8bars_demo_*_suno25s.wav
# → 打印：文件路径 + 元数据（时长/采样率/位深/和弦进行/seed）
```

---

## 子命令一览

| 命令 | 用途 | 示例 |
|---|---|---|
| `generate midi` | 程序化多轨 MIDI（和弦/旋律/贝斯 [+鼓]） | `smartnotegen generate midi --chords C-G-Am-F --bpm 120 --seed 42` |
| `generate melody` | music21 乐理旋律 + 变奏 | `smartnotegen generate melody --key "C major" --chords C-G-Am-F --variations 3` |
| `render` | MIDI → WAV 渲染 | `smartnotegen render --input xxx.mid` |
| `export suno` | Suno 合规导出（10–30s WAV/MP3） | `smartnotegen export suno --input xxx.wav --duration 25` |
| `pipeline` | 一键闭环 generate→render→export | `smartnotegen pipeline`（零参数 demo） |
| `config init` | 生成配置文件模板 | `smartnotegen config init` |
| `config show` | 打印合并后的生效配置 | `smartnotegen config show` |
| `batch` | 批量生成多个变体（P1-3 骨架） | `smartnotegen batch --count 5` |
| `ai musicgen` | MusicGen 扩编曲（P1） | `smartnotegen ai musicgen --input m.wav --prompt "upbeat pop"` |
| `ai diffrhythm` | DiffRhythm 歌曲草稿（P1） | `smartnotegen ai diffrhythm --prompt "slow ballad"` |

完整参数说明见 [docs/usage.md](docs/usage.md)。

---

## 配置

配置合并优先级（低 → 高）：**内置默认值 < `config/default.toml` < 用户配置文件 < CLI 参数**。

```bash
smartnotegen config init            # 生成 smartnotegen.toml（可修改 SoundFont 路径）
smartnotegen config show            # 查看生效配置
smartnotegen --config my.toml generate midi   # 指定配置文件
```

用户配置文件默认查找项目根 `smartnotegen.toml`，也可用 `--config` 显式指定。

---

## 错误码

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 参数错误/通用错误 |
| 2 | 配置错误（配置文件缺失/非法、SoundFont 路径无效） |
| 3 | 输入文件错误（.mid/.wav 不存在或无法解析） |
| 4 | 渲染失败（fluidsynth 未安装/找不到/进程失败） |
| 5 | 导出失败（时长越界 10–30s、MP3 编码器缺失） |
| 6 | AI 模块不可用（P1 依赖未安装） |

---

## P1 AI 集成（可选）

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements/ai.txt
# Windows 另需安装 espeak-ng 并加入 PATH（DiffRhythm 人声合成）
```

详见 [docs/ai-integration.md](docs/ai-integration.md)。

---

## 开发

```bash
pytest            # 运行全部测试（渲染用例使用 mock，无需真实 fluidsynth）
ruff check src    # lint
```
