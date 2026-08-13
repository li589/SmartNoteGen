# SmartNoteGen 增量 PRD（P1 + P2）

> 版本：v1.1（增量 PRD）｜ 作者：许清楚（Product Manager）｜ 日期：2025-08-09
> 状态：待架构师评审
> 关联文档：`docs/PRD.md`（v1.0，P0 已交付）、`docs/ai-integration.md`（P1 AI 集成说明）、`docs/architecture.md`

---

## 0. 变更摘要

### 0.1 交付现状（P0 已完成）

- P0 全部交付：CLI（`generate midi/melody`、`render`、`export suno`、`pipeline`、`config`、`batch` 骨架）、`ai` 骨架（延迟导入 + 明确提示，不安装/不 import torch/audiocraft/diffrhythm）。
- 测试 **106 个全绿**（`tests/` 覆盖 CLI、配置、MIDI、生成器、渲染、导出、边界用例）。

### 0.2 新增环境事实（已核实）

| 项 | 路径/事实 |
|---|---|
| FluidSynth | `module\fluidsynth\bin\fluidsynth.exe`（Windows 发行版，含 `libfluidsynth-3.dll`、`SDL3.dll`、`sndfile.dll`） |
| 音色库 A | `module\GeneralUser_GS\ColomboGMGS2_SF2\ColomboGMGS2.sf2` |
| 音色库 B | `module\GeneralUser_GS\GeneralUser-GS\GeneralUser-GS.sf2` |
| 目标 | 让 `render` / `pipeline` 在**本机真跑通**（此前因缺 fluidsynth / SoundFont 只能 mock） |

### 0.3 本增量 PRD 范围

| 编号 | 内容 | 类型 |
|---|---|---|
| M-1 | module 环境接入（默认路径指向 `module/`、路径探测、降级提示） | **新增前置需求（升为 P1 级）** |
| P1-1 | MusicGen 集成（melody conditioning） | P1 细化 |
| P1-2 | DiffRhythm 集成（完整歌曲草稿，spike 前置） | P1 细化 |
| P1-3 | 批量生成/随机化（batch 完整实现） | P1 细化 |
| P2-1 | DSP 参数调优 | P2 细化 |
| P2-2 | 更丰富乐理规则 | P2 细化 |
| P2-3 | 工程化完善 | P2 细化 |
| P2-4 | 预设风格库 | P2 细化 |
| P2-5 | 输出管理 | P2 细化 |

### 0.4 关键原则（延续 v1.0）

1. **本机真跑通优先**：M-1 是 P1-1/P1-2 之前的管线地基，render/pipeline 必须在本机用真实 fluidsynth + SoundFont 跑通，不再依赖 mock。
2. **显存风险显性化**：DiffRhythm 是否可跑 RTX 4060 8GB 须先 spike，GO/NO-GO 均要有明确、可交付的结论。
3. **可复现性**：所有随机化（批量、风格变体）支持 `--seed`。
4. **保持 CLI 心智模型**：延续子命令式扩展，不引入 UI。

---

## 1. M-1 module 环境接入（新增，P1 级前置）

### 1.1 背景与问题

P0 的 `render` 依赖 FluidSynth + SoundFont，但本机此前缺少可执行文件与音色库，测试只能 mock。现用户已补齐本地环境，需将 `module/` 目录正式接入配置体系，让 `render` / `pipeline` 默认即用真实引擎。

### 1.2 User Stories

- **作为本机用户**，我想开箱即用地执行 `smartnotegen render --input demo.mid`，不需要手动指定 fluidsynth 与 sf2 路径，以便快速得到真实 WAV。
- **作为环境不完整的用户**（如换机/CI），我想在缺少 `module/` 时得到**明确、可操作的错误提示**（而非静默 mock 或崩溃），以便知道需要补装什么。
- **作为高级用户**，我想用 CLI 参数或配置文件覆盖默认 SoundFont/fluidsynth 路径，以便使用自己的音色库。
- **作为测试维护者**，我想让路径探测逻辑可注入、可单测，以便在不依赖真实二进制的情况下验证降级分支。

### 1.3 需求细化

| 子项 | 需求 |
|---|---|
| M-1a | **默认路径发现**：`config` 默认配置中，fluidsynth 可执行文件与默认 SoundFont 指向 `module/` 下的实际路径；支持相对项目根目录解析 |
| M-1b | **路径探测**：启动 render/pipeline 时探测 (1) fluidsynth.exe 存在且可执行 (2) SoundFont 文件存在 (3) SF2 可被 fluidsynth 加载（非 0 退出码）；探测结果分级（OK / MISSING / BROKEN） |
| M-1c | **降级提示**：探测失败时给出分级错误信息与修复指引（如“请确认已下载 module/fluidsynth 与 SoundFont，或通过 --soundfont 指定”）；退出码按现有错误码体系扩展，不吞错 |
| M-1d | **可覆盖**：CLI `--soundfont` / `--fluidsynth-path` 优先级高于配置文件；配置文件优先级高于默认值 |
| M-1e | **双音色库策略**：默认 SF2 与备选 SF2 需显式命名与记录（见待确认问题 4），缺失默认库时自动探测备选库 |
| M-1f | **不引入 mock 静默回退**：真实环境可用时必须用真实引擎；只有显式 `--dry-run` 才允许 mock 行为 |

### 1.4 验收标准

- [ ] `smartnotegen render --input <demo.mid>` 在本机（无任何额外参数）产出真实 WAV，文件大小 > 0，时长与 MIDI 设定一致（±0.5s），无爆音/明显失真。
- [ ] `smartnotegen pipeline`（默认配置）端到端跑通：MIDI 生成 → 渲染 → 导出，全程使用真实 fluidsynth，无 mock 日志。
- [ ] 删除/重命名 `module/fluidsynth` 后执行 render，输出明确错误（含缺失路径与修复指引），退出码非 0 且符合错误码表；**不产生静默 mock 产物**。
- [ ] 提供错误 SoundFont 路径（如指向不存在的文件）时，探测给出 BROKEN/MISSING 分级结论与提示。
- [ ] `--soundfont <绝对路径>` 可覆盖默认 SF2 并成功渲染；`--fluidsynth-path` 同理。
- [ ] 路径探测与降级分支有单元测试（覆盖 OK/MISSING/BROKEN 三分支），不依赖真实二进制。
- [ ] 默认配置中 SF2 路径、fluidsynth 路径均以 `module/` 相对路径表达，且 `config --init` 生成的模板可直接使用。

---

## 2. P1 细化需求与验收标准

### 2.1 P1-1 MusicGen 集成（melody conditioning）

**目标**：以本地产出的旋律 WAV 为条件，用 MusicGen 扩编曲/生成器乐伴奏，形成“旋律 → 完整伴奏”的本地预览能力。

**需求细化**

| 子项 | 需求 |
|---|---|
| P1-1a | 模型选型：`facebook/musicgen-medium`（1.5B，fp16，目标 8GB 显存可跑）；提供 `--model-size` 可选 small 作降档 |
| P1-1b | CLI：`smartnotegen ai musicgen --input melody.wav --prompt "upbeat pop" --output out.wav [--duration 20] [--model-size medium] [--seed N]` |
| P1-1c | 实现要点：`audiocraft.models.MusicGen.get_pretrained(...)`；melody conditioning 用 `generate_with_chroma`（以输入旋律为条件，而非纯文本生成） |
| P1-1d | 依赖隔离：torch/audiocraft 仍为延迟导入；未安装时沿用现有“不可用+安装指引”提示（退出码体系内） |
| P1-1e | 资源约束：默认 fp16；推理前检查显存可用性（如 torch.cuda.get_device_properties），不足时明确提示而非 OOM 崩溃 |
| P1-1f | 产物合规：输出 WAV 时长可配置（默认对齐输入旋律，上限 30s），可被后续 export suno 消费 |

**验收标准**

- [ ] `smartnotegen ai musicgen --input melody.wav --prompt "upbeat pop" --output out.wav` 在 8GB 显存本机成功产出伴奏 WAV（默认 medium + fp16），全程无 OOM。
- [ ] 输出时长 ≥ 输入旋律时长（对齐/可配置），默认落在 10–30s 区间；采样率 32kHz（MusicGen 原生）或与导出链对齐（记录实际值）。
- [ ] 输出与输入旋律**有可量化的相关性**：对输入/输出做 chroma 特征提取，相关分 > 阈值（建议 ≥ 0.3，具体阈值待 spike 确认），证明是“以旋律为条件”而非纯文本生成。
- [ ] 记录性能基线：medium fp16 下 20s 输出的峰值显存与推理耗时（写入 CHANGELOG/README），供后续优化参照。
- [ ] `--seed` 可复现：相同输入/参数/seed 产出逐字节一致（或经可接受容差判定一致）。
- [ ] 未安装 AI 依赖时，命令给出明确安装指引（pip 命令），不触发 torch import（沿用 P0 验证方式）。
- [ ] 显存不足场景给出友好提示与降档建议（如 `--model-size small`），不崩溃。

### 2.2 P1-2 DiffRhythm 集成（完整歌曲草稿）

**目标**：生成长度接近完整歌曲的带人声草稿（“旋律/歌词 → 歌曲”本地预览）。**前置：spike 验证 RTX 4060 8GB 可行性**。

**需求细化**

| 子项 | 需求 |
|---|---|
| P1-2a | **spike 先行（T-S1）**：安装 CUDA torch + espeak-ng，权重经 hf-mirror 下载，将 infer 脚本 `decode_audio(..., chunked=False)` 改为 `chunked=True`；记录峰值显存、95s 歌曲推理耗时、主观音质 |
| P1-2b | **GO 分支**：`smartnotegen ai diffrhythm --prompt "slow ballad" [--lyrics ...] [--duration 95]` 产出带人声歌曲草稿 WAV（chunked=True 默认） |
| P1-2c | **NO-GO 分支**：spike 判定不可行时，命令给出明确提示“DiffRhythm 需要 ≥8GB 显存且当前环境不可用”（退出码 6），并输出 spike 证据（峰值显存/失败原因）；T-P1-2 延期但不阻塞其他交付 |
| P1-2d | 依赖隔离：torch/diffrhythm 延迟导入；未安装时沿用现有提示 |
| P1-2e | 产物合规：草稿 WAV 不自动进入 Suno 导出链（含人声，不符合 P0-5 纯器乐规范），文档中明确用途为“本地听感预览” |

**验收标准**

- [ ] **spike 报告产出**：`docs/ai-integration.md` 中 T-S1 表格填齐（峰值显存、95s 推理耗时、主观音质、GO/NO-GO 结论与依据）。
- [ ] **GO 时**：`smartnotegen ai diffrhythm --prompt "..."` 成功产出 ≥60s 带人声 WAV；全程显存峰值 < 8GB（以 nvidia-smi 或 torch 记录为准）；chunked=True 为默认参数，无需用户手动改脚本。
- [ ] **NO-GO 时**：命令输出明确不可用提示与退出码 6；不崩溃、不产生损坏文件；文档说明降级路径。
- [ ] 未安装依赖时给出安装指引（含 espeak-ng 的 Windows 安装说明），不触发 torch import。
- [ ] `--lyrics` 传入歌词时可生成含对应人声的草稿；不传时行为明确（默认空词/哼唱模式或提示）。
- [ ] 草稿产物命名与输出管理（P2-5）兼容，元数据标注 `contains_vocals=true`。

### 2.3 P1-3 批量生成/随机化（batch 完整实现）

**目标**：把 P0 的 batch 骨架补全为完整能力：一次生成 N 个变体，覆盖和弦进行、节奏型、风格、旋律特性等维度，且可复现。

**需求细化**

| 子项 | 需求 |
|---|---|
| P1-3a | CLI：`smartnotegen batch --count N [--seed S] [--chords-choices ...] [--style ...] [--variations] [--render] [--export]`；支持不渲染纯出 MIDI、或链式 render/export |
| P1-3b | 随机化维度：和弦进行变体、节奏型变体、风格/乐器变体、（music21）旋律变奏方式；维度可分别开关 |
| P1-3c | 可复现：`--seed S` 全局种子，同参数 + 同 seed 产出完全一致；默认不传 seed 时用系统熵（日志记录实际 seed 便于回溯） |
| P1-3d | 进度与结果：stdout 输出每项状态（成功/失败/耗时），失败项不中断整体；生成结果清单（文件路径、参数、seed） |
| P1-3e | 与 P2-5 输出管理兼容：批量产物按输出管理规范落盘（见 4.5） |
| P1-3f | 资源保护：默认串行；可选 `--parallel`（并发数可配），失败重试策略明确（如单次重试） |

**验收标准**

- [ ] `smartnotegen batch --count 5 --seed 42` 产出 5 个独立变体（文件命名唯一），其中至少 2 个变体在和弦/节奏/风格维度与其余不同。
- [ ] **可复现性**：`--seed 42` 连续运行两次，产物（MIDI 内容与渲染后 WAV）一致（MIDI 逐字节一致；WAV 经归一化比较一致或提供 hash 校验）。
- [ ] 无 `--seed` 时运行日志记录实际使用的 seed，便于事后复现。
- [ ] 构造 1 个失败项（如非法和弦），整体继续执行，失败项有明确错误日志，成功项不受影响，最终退出码按“全部成功/部分失败/全部失败”区分。
- [ ] `--render` 链式执行时逐项调用真实 render（非 mock），失败项不中断整体。
- [ ] 批量产物清单（参数 + 路径 + seed）可导出为元数据文件（兼容 P2-5）。

---

## 3. P2 细化需求与验收标准

### 3.1 P2-1 DSP 参数调优

**目标**：提升试听质感，让导出片段更接近“可直接上传的成品器乐”。

**需求细化**

| 子项 | 需求 |
|---|---|
| P2-1a | **音量平衡**：多轨归一化（峰值目标 -1 dBFS 默认），轨道间相对音量可调（如 `--track-gain`） |
| P2-1b | **淡入淡出**：可配 `--fade-in/--fade-out`（默认 100ms/300ms，范围 0–5000ms），消除爆音与切边 |
| P2-1c | **轻度 EQ/压缩**：提供可选 `--eq` / `--compressor`（参数化，如低频切、轻压缩 ratio/threshold），默认关或轻度开启需在待确认问题 6 中拍板 |
| P2-1d | **混响控制**：渲染链可选加混响（`--reverb`），但 Suno 导出链默认**无强混响**（延续 P0-5 合规约束），导出时明确禁用 |
| P2-1e | 实现位置：render 输出后、export 前，作为独立处理阶段，可开关、可测试 |

**验收标准**

- [ ] 默认导出片段峰值 ≤ -1 dBFS，无削波（峰值采样数 = 0）。
- [ ] 淡入/淡出生效：片段首/尾 50ms 内能量按预设曲线衰减，肉眼可见包络变化且无爆音。
- [ ] 开启 EQ/压缩后输出仍无失真；参数非法（如 ratio<1、fade 为负）时给出参数校验错误而非静默忽略。
- [ ] `export suno` 产物无混响（或混响可被显式关闭），符合 P0-5 合规约束。
- [ ] 所有 DSP 阶段均有单元测试（构造已知波形验证增益/淡变/削波检测）。

### 3.2 P2-2 更丰富乐理规则

**目标**：让生成旋律/和声更有“人写感”，降低明显乐理错误。

**需求细化**

| 子项 | 需求 |
|---|---|
| P2-2a | **声部进行约束**：避免平行五度/平行八度（检测并修正或提示）；声部交叉检测 |
| P2-2b | **对位**：基础二声部对位规则（协和音程优先、经过音/辅助音约束，至少 1 档严格度可配） |
| P2-2c | **和弦转位**：根据旋律音/声部流畅性自动选择转位（低音声部更平滑），可选开启 |
| P2-2d | **节奏型库扩展**：至少覆盖常见风格节奏型（见 P2-4），支持用户自定义节奏型（如以字符串/JSON 描述） |
| P2-2e | 与现有 music21 旋律生成链集成：规则作用于生成与后处理两阶段 |

**验收标准**

- [ ] 生成的多声部 MIDI 中，平行五度/八度出现次数低于阈值（默认 0 次，可配容忍度）；提供规则检测器单测（构造含平行五度的输入可被检出）。
- [ ] 开启对位模式后，二声部在强拍上的音程满足协和约束（可量化校验：强拍音程在允许集合内）。
- [ ] 开启转位后，低音声部相邻音符平均音程差 ≤ 未开启时的基线（更平滑），且和弦功能不变（根音位置仍正确）。
- [ ] 节奏型库 ≥ 6 种内置型 + 至少 1 种用户自定义方式（文档给出格式示例）。
- [ ] 所有新规则可开关、默认不破坏 P0 已有输出兼容性（既有测试保持全绿）。

### 3.3 P2-3 工程化完善

**目标**：让项目可维护、可分发、可放心升级。

**需求细化**

| 子项 | 需求 |
|---|---|
| P2-3a | **日志分级**：DEBUG/INFO/WARNING/ERROR 分级输出，`--verbose`/`--quiet` 控制级别；关键流程（生成/渲染/导出/AI）有结构化日志 |
| P2-3b | **错误处理**：统一错误码表（沿用现有退出码体系，新增 M-1 与 AI 相关码），CLI 捕获预期异常给出友好信息，未预期异常给出堆栈开关 |
| P2-3c | **单元测试**：新增模块全部补测；既有 106 测试保持全绿；覆盖率目标（建议 ≥ 80%，见待确认问题 9） |
| P2-3d | **依赖锁定**：`requirements/*.txt` 提供锁定版本（含 AI 依赖）；`pyproject.toml` 版本规范化；提供一键安装脚本 |
| P2-3e | **打包脚本**：提供 Windows 打包（PyInstaller 或等价）脚本，产物为可分发 CLI（含 module/ 资源路径说明） |

**验收标准**

- [ ] `--verbose` 输出 DEBUG 级日志，默认输出 INFO 级，`--quiet` 仅输出错误；日志含时间戳、级别、模块名。
- [ ] 错误码表文档化（`docs/` 或 `--help` 可查），M-1/AI 相关错误有独立码；预期错误不打印堆栈（`--debug` 才打印）。
- [ ] 全量测试通过：`pytest` 0 失败；新增模块测试覆盖率 ≥ 目标值（默认 80%）。
- [ ] `requirements/*.txt` 全部锁定版本；`pip install -r requirements/base.txt` 可干净复现环境（在干净 venv 验证）。
- [ ] 打包脚本在干净 Windows 环境可产出可执行文件，执行 `--help` 正常；打包产物含 module/ 资源路径的说明文档。

### 3.4 P2-4 预设风格库

**目标**：内置开箱即用的风格预设，让用户一句 `--style pop` 得到合理参数组合。

**需求细化**

| 子项 | 需求 |
|---|---|
| P2-4a | 预设字段：BPM 范围、乐器/音色（GM Program）、节奏型、旋律特性（音域/音程偏好/变奏强度）、和弦进行偏好、DSP 默认参数（如适用） |
| P2-4b | 首期风格：**流行/摇滚/电子/古典** 4 个基线预设（风格清单以待确认问题 1 结论为准）；每风格至少 1 条 demo 可跑通 |
| P2-4c | 用户扩展：支持自定义风格（以 TOML/JSON 文件注册，`--style <name>` 可引用） |
| P2-4d | 与 P1-3 联动：batch 的 `--style` 从风格库取参，风格可作为随机化维度 |

**验收标准**

- [ ] `smartnotegen generate midi --style pop`（零额外参数）跑通并输出符合流行特征的 MIDI（BPM/乐器/节奏型与预设一致，可断言关键字段）。
- [ ] 4 个内置风格各自有完整字段（BPM/乐器/节奏型/旋律特性），无缺失默认值；文档列出各风格参数表。
- [ ] 自定义风格文件注册后可被 `--style <name>` 引用；风格名非法/缺失时给出明确错误。
- [ ] 风格库与 P1-3 联动：`batch --style pop --count 3` 产出 3 个 pop 参数下的变体。

### 3.5 P2-5 输出管理

**目标**：批量/多日使用后，输出目录依然有序、可追溯。

**需求细化**

| 子项 | 需求 |
|---|---|
| P2-5a | **目录组织**：默认按 `输出根目录/项目名/日期(YYYYMMDD)/` 组织（目录规范以待确认问题 2 结论为准），项目名可 CLI 指定，缺省用“default” |
| P2-5b | **自动命名**：文件命名规则（如 `{style}_{bpm}_{seed}_{seq}.mid/.wav`），同参数重复运行不覆盖（序号递增或时间戳） |
| P2-5c | **元数据清单**：每次生成/渲染/导出在产物旁输出元数据文件（JSON/CSV），记录参数、seed、耗时、依赖版本、输入输出路径 |
| P2-5d | 与 P1-3 兼容：batch 清单复用同一元数据体系 |

**验收标准**

- [ ] 执行 `batch --count 3 --project myproj` 后，产物落在 `<root>/myproj/<YYYYMMDD>/` 下，文件命名唯一且含可读语义（style/bpm/seed/序号）。
- [ ] 同参数重复运行不覆盖旧文件（新文件序号/时间戳递增），旧产物可追溯。
- [ ] 每次运行产出元数据文件，字段完整（参数、seed、耗时、版本、路径），可被程序读取（JSON schema 文档化）。
- [ ] 无项目名时使用默认目录，仍满足命名唯一与元数据要求。
- [ ] 目录/命名规则可通过配置或 CLI 覆盖（`--output-dir`、`--project`）。

---

## 4. 交付顺序与依赖关系（建议）

```
M-1 module 接入（地基，P1 前置）
 ├─ 渲染链真实化：render / pipeline 真跑通
 ├─ P2-1 DSP（依赖真实 WAV 产出）
 ├─ P2-5 输出管理（依赖 M-1 落盘路径）
 │
 ├─ P1-3 batch（依赖 M-1 + P2-5 兼容 + 可复现 seed）
 ├─ P2-4 风格库（依赖 P1-3 风格维度 + P2-2 节奏型）
 │
 ├─ P1-1 MusicGen（依赖 M-1 的旋律 WAV 作为条件输入）
 ├─ P1-2 DiffRhythm（T-S1 spike 先行；独立，不阻塞他人）
 │
 ├─ P2-2 乐理规则（可与生成链并行）
 └─ P2-3 工程化（贯穿全程，随各模块补齐）
```

- **建议首期冲刺**：M-1 + P1-3 + P2-5 + P2-4（不依赖 AI 权重，价值闭环快）。
- **AI 二阶段**：P1-1 与 P1-2（spike 结论后）单独冲刺。
- **P2-2/P2-3** 穿插完成，不设硬前置。

---

## 5. 待确认问题（需主理人/架构师/用户拍板）

| # | 问题 | 影响 | 建议默认 |
|---|---|---|---|
| 1 | **预设风格库首期覆盖哪些风格**？建议流行/摇滚/电子/古典；是否需要国风/爵士/环境等扩展 | P2-4 范围与节奏型库 | 流行/摇滚/电子/古典 4 个，其余列为 P2 扩展 |
| 2 | **输出管理目录规范偏好**：`项目/日期` 还是 `日期/项目`？文件命名是否接受 `{style}_{bpm}_{seed}_{seq}` 风格 | P2-5 目录/命名规则 | `<root>/<project>/<YYYYMMDD>/` + `{style}_{bpm}_{seed}_{seq}` |
| 3 | **DiffRhythm spike 的时间/资源预算确认**：何时执行（是否本冲刺）、允许下载权重体积/时长上限、spike 期间是否可占用 GPU | P1-2 排期与阻塞 | 本冲刺内执行；权重走 hf-mirror；GPU 空闲窗口执行 |
| 4 | **默认 SoundFont 选型**：ColomboGMGS2 还是 GeneralUser-GS？哪个作为默认、哪个备选 | M-1 默认路径与音色质量 | 默认 GeneralUser-GS（更轻量通用），Colombo 备选；待用户试听后定 |
| 5 | **MusicGen 模型规格**：默认 medium（1.5B）还是 small？是否接受首次下载 ~2GB+ 权重 | P1-1 资源与首跑体验 | 默认 medium，`--model-size small` 降档 |
| 6 | **DSP 默认策略**：EQ/压缩默认开启还是显式参数开启？淡入淡出默认值是否可接受 100ms/300ms | P2-1 默认听感 | 淡入淡出默认开；EQ/压缩默认关、显式开启 |
| 7 | **AI 推理 GPU 占用策略**：是否允许占用 GPU（影响其他工作）？是否需要 CPU 低优先级选项 | P1-1/P1-2 使用体验 | 允许 GPU，提供 `--device cpu` 可选 |
| 8 | **批量默认并发与数量**：`batch --count` 默认值？是否默认串行 | P1-3 默认行为 | 默认 count=3、串行；`--parallel` 显式开启 |
| 9 | **测试覆盖率目标**：P2-3 覆盖率阈值（80%？90%？） | P2-3 验收 | ≥ 80% |
| 10 | **打包形态**：P2-3 打包是否需要产出单文件 exe（体积/杀软风险）还是仅提供脚本 | P2-3 范围 | 先提供可复现脚本，exe 列为可选 |

---

## 6. 风险与开放项

- **DiffRhythm 显存风险**：8GB 是硬约束，spike 前不承诺可交付；NO-GO 时降级为明确提示 + 文档，不阻塞其他交付。
- **AI 权重下载**：MusicGen（~2GB+）与 DiffRhythm 权重下载依赖网络，需确认镜像（hf-mirror）与磁盘空间。
- **Windows 原生二进制兼容性**：fluidsynth.exe 依赖 SDL3/sndfile dll，打包分发时需一并说明路径相对性。
- **P2 范围蔓延**：P2-2 乐理规则、P2-4 风格库均为“深度型”需求，建议每项独立验收、增量交付，避免阻塞主线。
