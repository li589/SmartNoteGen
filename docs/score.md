# score — 乐谱生成使用指南

> SmartNoteGen 乐谱子系统：从 **MIDI** 生成 **五线谱 / 简谱 / MusicXML**。
> 纯本地、离线；五线谱 SVG 与简谱 SVG **零依赖**（浏览器直接看），位图输出需 Pillow。

---

## 快速开始

```bash
# 从 MIDI 出五线谱 SVG（默认格式）
smartnotegen score song.mid

# 一次性出全部 6 种格式
smartnotegen score song.mid --format all -o ./score

# 简谱纯文本（等宽字符，可直接打印）
smartnotegen score song.mid --format jianpu-txt

# 深色主题 + 自定义标题 / 调式 / 署名
smartnotegen score song.mid --theme dark --title "夜曲" --key "a minor" --composer "我"

# 把已有的 MIDI 补出谱面
smartnotegen score output/20260921/pop_Cmajor_120_8bars_42.mid -f svg,png,musicxml
```

---

## 输出格式

`--format` 接受逗号分隔的多个格式，也接受别名。`all` = 全部 6 种。

| 格式名 | 说明 | 文件名后缀 | 可用别名 |
|---|---|---|---|
| `svg` | 五线谱矢量图（零依赖） | `.svg` | — |
| `png` | 五线谱位图（需 Pillow） | `.png` | — |
| `jianpu` | 简谱 SVG | `.jianpu.svg` | `jianpu-svg` / `np` / `number` |
| `jianpu-png` | 简谱位图（需 Pillow） | `.jianpu.png` | — |
| `jianpu-txt` | 简谱纯文本（等宽，可直接打印） | `.jianpu.txt` | `txt` / `text` |
| `musicxml` | MusicXML 4.0（MuseScore / Dorico / Finale 可导入） | `.musicxml` | `xml` / `music-xml` |

```bash
smartnotegen score song.mid --list-formats   # 打印可用格式与主题，不渲染
```

---

## score 参数

| 参数 | 说明 |
|---|---|
| `midi`（位置参数） | 输入 `.mid` 路径 |
| `-f, --format` | 输出格式（逗号分隔），默认 `svg` |
| `-o, --output-dir` | 输出目录，默认与输入 MIDI 同目录 |
| `--key` | 记谱调式，如 `'C major'` / `'a minor'`（默认沿用 MIDI 的调） |
| `--time-signature` | 拍号，如 `'4/4'`（默认 4/4） |
| `--title` | 标题（默认取文件名） |
| `--composer` | 作曲者署名 |
| `--bars` | 小节数（默认按最后一个音推算） |
| `--clef` | 谱号覆盖，格式 `'轨道名=treble\|bass'`（可多次） |
| `--theme` | 配色：`light`（白纸黑墨，乐谱惯例）/ `dark`（深纸浅墨） |
| `--scale` | 位图超采样倍数，越大边缘越干净（默认 2.0） |
| `--page-width` | 页面宽度（像素；五线谱与简谱共用） |
| `--space` | 五线谱谱线间距（简谱忽略） |
| `--no-title` / `--no-tempo` | 不渲染标题区 / 速度记号 |
| `--no-measure-numbers` | 不渲染小节号 |
| `--no-ties` | 不渲染延音线 / 连音弧 |

---

## 与生成链路集成

不必先生成 MIDI 再单独跑 `score`——两个上游命令都能顺带产出谱面：

```bash
# generate：产出 MIDI 的同时在同目录、同主干旁出谱面
smartnotegen generate midi --chords C-G-Am-F --bpm 120 --score --score-format svg,png

# pipeline：一键闭环，并把五线谱内嵌进 HTML 预览页
smartnotegen pipeline --score --score-format all --score-theme dark

# 记谱调式可与生成调式不同（例如生成用 C major，记谱用 a minor）
smartnotegen generate midi --score --score-key "a minor"
```

两个命令共用的选项：`--score`、`--score-format`、`--score-theme`、`--score-key`。
`pipeline --score` 的谱面会同时内嵌进预览页（`render_svg` 的 SVG 文本直接写入 HTML）。

---

## Python API

```python
from smartnotegen.models.notes import NoteSequence      # 你的音符数据
from smartnotegen.score import Score, layout_score, render_svg, SvgOptions
from smartnotegen.score_export import (
    ScoreExportOptions,
    export_score,
    score_from_sequence,
    score_svg_text,
)

# 1) 从 NoteSequence 构建乐谱（可覆盖记谱调式）
score = score_from_sequence(seq, title="夜曲", key="a minor")

# 2) 一次性按多格式落盘（返回 {格式名: 绝对路径}）
opts = ScoreExportOptions(formats=("svg", "jianpu-txt", "musicxml"), theme="dark")
written = export_score(score, output_dir="out", stem="yequ", options=opts)

# 3) 只取 SVG 文本（供网页内嵌，不落盘）
svg_text = score_svg_text(score, opts)

# 底层：中间表示 → 排版 → 渲染
layout = layout_score(score)              # ScoreLayout
svg = render_svg(layout, SvgOptions())    # 或 write_svg(layout, "out/x.svg")
```

`score/__init__.py` 聚合了公开 API；各格式的渲染器也可单独导入：

```python
from smartnotegen.score import (
    Score, ScoreTrack, ScoreMeasure, ScoreNote,   # 中间表示
    layout_score, LayoutOptions,                  # 排版
    render_svg, write_svg, SvgOptions, SvgTheme,  # 五线谱
    parse_jianpu, to_jianpu_lines, write_jianpu_svg,  # 简谱
    render_musicxml, write_musicxml, validate_musicxml,  # MusicXML
    render_png, write_png,                        # 位图（惰性导入 Pillow）
)
```

---

## 输出与命名

产物与输入 MIDI **同主干**，仅追加格式后缀（见上表）：

```
输入: pop_Cmajor_120_8bars_42.mid      --format all
输出: pop_Cmajor_120_8bars_42.svg           五线谱 SVG
      pop_Cmajor_120_8bars_42.png           五线谱 PNG
      pop_Cmajor_120_8bars_42.jianpu.svg    简谱 SVG
      pop_Cmajor_120_8bars_42.jianpu.png    简谱 PNG
      pop_Cmajor_120_8bars_42.jianpu.txt    简谱文本
      pop_Cmajor_120_8bars_42.musicxml      MusicXML
```

---

## 分层架构

```
score/
├── theory.py    纯乐理函数：调号、音名拼写、时值分解
├── model.py     乐谱中间表示：MidiDocument / NoteSequence → 多轨谱面数据
├── layout.py    排版引擎：行断开 + 行内定位 + 符干/连杠/加线几何
├── drawing.py   共享绘制层：一次记录指令流，分别序列化为 SVG 与 PNG（几何同源）
├── svg.py       五线谱 SVG 渲染（零依赖）
├── jianpu.py    简谱（数字谱）文本 / SVG / PNG
├── png.py       五线谱位图（Pillow 惰性导入，不装也能用 SVG）
└── musicxml.py  MusicXML 4.0 导出（纯标准库手写）
```

顶层 `score_export.py` 是**格式归一化 + 统一落盘**服务，供 `score` 子命令、
`pipeline --score`、`generate --score` 三处共用，避免各抄一遍逐渐漂移。
它放在顶层（与 `preview.py` 同层）而非 `commands/`：`pipeline` 要用它，
而 `pipeline` 属核心编排层，不应反向依赖 CLI 层。

**设计要点**：五线谱与简谱共享同一套绘制指令流（`drawing.py`），
所以 SVG 与 PNG 的几何**同源**，不会出现"矢量对得上、位图偏一点"的漂移。

---

## 错误处理

| 情形 | 表现 |
|---|---|
| 未知格式名 / 非法主题 | `错误 [1]`（`ParameterError`），提示可用取值 |
| 非法 `--clef` 写法（缺 `=`、谱号名非法、重复指定谱表） | `错误 [1]`（`ParameterError`） |
| 请求位图但未装 Pillow | 转成带安装指引的 `ParameterError`，**不冒成意外错误**：<br>`…需要 Pillow。请 pip install Pillow，或改用 --format svg` |
| 页面宽度 / 谱线间距 / 超采样倍数非正 | 构造选项时即报错（`ParameterError`），避免写了一半才失败 |

```bash
pip install Pillow          # 需要 PNG / jianpu-png 时才装
```

---

## 故障排除

| 现象 | 原因与处理 |
|---|---|
| 只出了 SVG，没出 PNG | 未装 Pillow；装后重试，或用 `--format svg` 保持零依赖 |
| 谱面调式与预期不符 | 默认沿用 MIDI 的调；用 `--key`（`score`）或 `--score-key`（generate/pipeline）覆盖 |
| 音符挤在一行 / 太稀疏 | 调 `--page-width`（页面宽度）或 `--space`（谱线间距） |
| 轨道谱号不对 | 用 `--clef '轨道名=treble\|bass'` 显式指定（可多次） |
| 标题 / 小节号不想要 | `--no-title`、`--no-measure-numbers` 等开关关闭 |

---

## 相关文档

- [usage.md](usage.md) — smartnotegen 全命令参数
- [features.md](features.md) — 三组件全量功能清单
- [videomaker.md](videomaker.md) — 谱面产出后做成音乐视频
