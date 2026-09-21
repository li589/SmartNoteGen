# SunoAuxTool 项目重构计划（v1.1，决策已拍板，执行中）

> 2026-09-21 · 现基线：main @ `955208f`（已推送），主包 0.6.0 / videomaker 0.4.0 /
> Cat-Catch 0.1.0，根套件 1046 例 / 92.28%，Suno 子包 75 例 / 100%，CI 全绿。
>
> **决策记录（2026-09-21 拍板）**
> - Q1 包名迁移：**迁移 + shim 兼容**（`sunoauxtool` 为正名，`smartnotegen` 留 shim ≥1 版）
> - Q2 顶层 CLI：**`sunoaux`**（pre/post 子命令组）
> - Q3 DSP 栈：numpy/scipy 为主、ffmpeg 滤镜兜底（计划默认，未异议）
> - Q4 VASR 入库：**清理后整目录入库**（153 处 ruff 修掉后进 src/，受 CI 全扫约束）
> - Q5 仓库名：随 R1 立即改

---

## 1. 定位重述

**SunoAuxTool**：Suno / 海绵音乐 / 网易天音等 AI 音乐工具的**前期 + 后期处理工具箱**。

| 阶段 | 能力 | 现有资产 | 缺口 |
|---|---|---|---|
| 前期·旋律/MID 生成 | 和弦/旋律/贝斯/鼓程序化生成、动机乐句 | `smartnotegen` procedural（generate midi/melody） | ✅ 已有 |
| 前期·谱面产出 | 五线谱/简谱 SVG/PNG、MusicXML | `score` 子系统 6 格式（#9–#12） | ✅ 已有 |
| 前期·MIDI↔WAV | MIDI→WAV（FluidSynth）、WAV→MIDI（转谱） | render + analysis.transcribe / basicpitch（#13） | ✅ 已有（复调后端未实测） |
| 后期·下载/转码 | 猫抓取证提取、ffmpeg 转码；API 下载 | Suno-Cat-Catch-Resolve（probe/decode/batch） | ⚠️ API 侧无（Suno/海绵/天音 adapter 待建） |
| 后期·DSP | 响度归一/EQ/压缩/淡入淡出/裁剪拼接/重采样 | — | ❌ 全新功能 |
| 后期·音乐视频 | 多轨混音 + 7 种视觉（含滚动谱面） | videomaker 0.4.0 | ✅ 已有 |
| 后期·音质提升/分离修复 | 音频超分、人声/伴奏分离修复 | `src/versatile_audio_super_resolution/`（**未入库**） | ⚠️ 待摸底接入 |

---

## 2. 现状盘点与约束

**资产**
- `src/smartnotegen/`：核心单包（~40 模块），import 引用遍布 tests/ 与两子包
- `src/videomaker/`、`src/Suno-Cat-Catch-Resolve/`：独立 editable 子包（pyproject 各自版本对齐守卫）
- `src/versatile_audio_super_resolution/`：用户目录，未入库，**153 处 ruff 问题**，依赖未知（疑重）
- `module/`：fluidsynth / SoundFont / AI 模型仓库（**Git LFS 管理**，CI 依赖 `git lfs pull`）
- CI：钉 `ubuntu-24.04`，ruff `src/` 全扫 + 两套 pytest + 零 torch 断言

**改名波及面（务必按此估工作量）**
1. GitHub 仓库名 `li589/SmartNoteGen` → `SunoAuxTool`（gh 可改，旧 URL 自动重定向但应更新 remote）
2. 本地目录 `D:\New\Music\SmartNoteGen` → `D:\New\Music\SunoAuxTool`（venv 绝对路径、IDE 配置全失效，需重建/重装）
3. Python 包名 `smartnotegen` → 新名：**全仓 500+ 处 import**（src/tests/两子包）+ pyproject + LFS 路径无关但 workflow/文档全动
4. `module/` 内 AI 仓库路径被 `DIFFRHYTHM_DIR` 等引用；`.sf2`/`.exe` LFS 路径不动

---

## 3. 分阶段执行计划

### Phase R0 — 摸底与决策（✅ 2026-09-21 完成）
- ✅ **VASR 摸底结论**：
  - 上游 `haoheliu/versatile_audio_super_resolution`（AudioSR），本地克隆 @ `d312fba`，
    **自带内嵌 `.git`**；体量 49M 纯代码（权重不在仓内，走 huggingface 下载）
  - 入口：`inference.py`（`from audiosr import build_model, super_resolution`）；
    MIT 许可（LICENSE 文本为模板头，R5 时核对全文）
  - **依赖与主包 AI 栈冲突**：torch==2.0.1+cu118 固定（主包 AI 用 2.5.1+cu121）、
    transformers==4.30.2 固定、diffusers git 版、gradio/librosa/matplotlib/pyloudnorm
  - **入库执行修正**（Q4 决策落地细节）：
    1. 删除内嵌 `.git`（头部注释记录 fork 基线：URL + commit d312fba + 日期），
       否则 git 嵌入仓库无法整目录入库
    2. ruff 153 处逐项真修（决策已定）；上游派生文件加统一头注释，便于未来对照上游
    3. **运行环境隔离**：torch 版本互斥 → VASR 推理走独立 venv（`requirements/vasr.txt`
       + 适配器以子进程或独立解释器调用），不进主 venv；CI 零 torch 断言扩展到 audiosr
- ✅ API 调研定性：海绵音乐/网易天音无官方公开下载 API，R7 只做 adapter 留位 +
  mock 契约测试，不逆向客户端加密（同猫抓结论边界）
- ✅ 决策三项拍板（见文首决策记录）

### Phase R1 — 仓库改名（✅ 2026-09-21 完成，除目录改名）
- ✅ `gh repo rename SunoAuxTool`（`li589/SmartNoteGen` → `li589/SunoAuxTool`，
  旧 URL 自动重定向）+ `git remote set-url`
- ✅ 核查：README/workflows/docs **零仓库 URL 硬编码**，无需文件改动
- ⏳ **本地目录改名 `D:\New\Music\SmartNoteGen` → `SunoAuxTool`**：推迟到 R8 收口后
  一次性做（改名会使本会话工作区与 venv 绝对路径失效；需重建 venv + editable ×3 重装）

### Phase R2 — 品牌与文档层
- [ ] README 重写定位（前期/后期能力矩阵）
- [ ] docs/ 各文件标题与定位语；CHANGELOG 加条目
- [ ] CLI 欢迎语/`--help` 描述更新
- 验收：`grep -ri smartnotegen docs/ README.md` 只剩包名类引用

### Phase R3 — 顶层聚合 CLI（后期能力的统一入口）
- [ ] 新增顶层 Typer 入口（名字待定，见 §4-Q2），子命令组映射现有能力：
  - `pre`：`melody` / `midi` / `score` / `render` / `transcribe`（→ 现 generate/score/render/transcribe）
  - `post`：`fetch`（猫抓）/ `convert`（转码）/ `dsp`（R6）/ `video`（→ videomaker render）/ `enhance`（→ VASR，R5）
- [ ] 实现为**薄转发层**：只做参数映射与错误码统一，不复制业务逻辑（核心层不得反向依赖 CLI 层的既定铁律延续）
- [ ] 旧入口 `smartnotegen` / `videomaker` 保留（兼容期 ≥1 个版本）
- 验收：每个新子命令有 2+ 例端到端测试（mock 引擎），旧入口测试零改动通过

### Phase R4 — Python 包名迁移（手术最大，可选/可延后）
- [ ] `smartnotegen` → `sunoauxtool`（或 `sat.core`）：机械替换 import + pyproject + 守卫测试
- [ ] 保留 `smartnotegen` 兼容 shim 包一个版本（`from sunoauxtool import *` + deprecation warning）
- [ ] videomaker / Cat-Catch 的跨包 import 同步
- 验收：根套件与子包套件全绿；`pip install -e .` 后新旧 import 均可用

### Phase R5 — VASR 接入（音质提升/分离修复）
- ✅ **兼容性验证（2026-09-21 实测，改写原方案）**：AudioSR 在主 venv 现代栈下
  **直接可用，无版本冲突**——torch 2.5.1+cu121 / numpy 2.5.1 / transformers 4.49 /
  librosa 0.10.2 全部通过：`import audiosr` ✓ → `build_model` ✓（2.6GB 权重下载 +
  torch.load + 258.2M 参数加载）→ `super_resolution` 端到端 ✓（8s@12kHz → 10.24s@48kHz，
  DDIM 50 步 42.2s GPU）。上游 main = 本地 HEAD（d312fba），无更新可拉。
  - setup.py 的 `torch>=1.13.0` 本就开放；**真正过时的是三个钉死**：
    `numpy<=1.23.5` / `librosa==0.9.2` / `transformers==4.30.2`（实测均可放开）；
    `diffusers` git 依赖为**死依赖**（代码零引用，直接删）
  - **唯一未来断点**：torch ≥2.6 将 `torch.load` 默认 `weights_only=True`——
    仓内 13 处 `torch.load` 需补参数；停在 2.5.1 无影响（留 TODO 注释）
  - timm 弃用警告（`timm.models.layers`）小修
  - **R5 方案简化**：原「独立 venv 推理」前提不成立 → 主 venv 直调；入库 =
    删嵌套 `.git`（记 fork 基线）+ ruff 153 处清理 + 重写 requirements +
    薄适配器（延迟导入 + `is_available()` + 退出码 6）
- [ ] 入库三步执行（见 R0 结论 + 上述修正）
- [ ] CLI：`post enhance <wav>`（超分，`--model basic|speech`）；分离修复能力
      以 AudioSR 实际功能为界（超分/高频重建，非人声分离——人声分离另行选型）
- [ ] 真实推理路径已验证 ✓（2026-09-21，对照 basicpitch「未验证」教训已闭环）
- 验收：适配器单测（mock 权重路径）+ 真实样本回归脚本

### Phase R6 — DSP 功能包（全新，先规格后实现）
- [ ] 规格文档：响度归一（EBU R128 简化版）、淡入淡出、重采样、裁剪/拼接/交叉淡化、
      简单 EQ/压缩（numpy/scipy 实现，ffmpeg 滤镜兜底二选一——摸底后定）
- [ ] CLI：`post dsp <wav> --ops "norm,fade-in 0.5,trim 10-25"`（管道式操作串）
- [ ] 错误码延续分段（建议 15+ 段给 DSP）
- 验收：每算子单元测试（数值断言）+ 1 条真实音频听感样本

### Phase R7 — API 下载适配器
- [ ] `post fetch` 统一接口：`--source catcatch|suno-api|haimeng|tianyin`
- [ ] 猫抓路径 = 现 Cat-Catch 能力直通；API 侧 adapter 模式留位（凭证走 gitignored 配置，文档脱敏）
- 验收：猫抓路径回归通过；API adapter 有契约测试（mock HTTP）

### Phase R8 — 收口发布
- [ ] 版本 1.0.0（定位成 Tool 后语义化大版本）或 0.7.0（保守）；CHANGELOG、docs 全量校对
- [ ] CI 全绿 + 推送 + tag

---

## 4. 决策点（需拍板后才动 R1 之后的对应阶段）

| # | 问题 | 选项与建议 |
|---|---|---|
| Q1 | **Python 包名迁移深度** | A. 只改 repo/品牌，包名保留 `smartnotegen`（省 ~500 处改动，风险最低）；B. 迁移到 `sunoauxtool` + shim 兼容（彻底，R4 手术）。**建议 B，但排在 R3 之后做，且允许单独砍掉** |
| Q2 | **顶层聚合 CLI 名** | `sunoaux`（短，推荐）/ `sunotool` / `sat` |
| Q3 | **DSP 实现栈** | A. numpy/scipy 自实现（可控、可测，推荐为主）；B. ffmpeg 滤镜直通（快但难单测）。建议 A 为主、B 兜底 |
| Q4 | **VASR 入库策略** | A. 清理后整目录入库（受 CI ruff 全扫约束）；B. 移入 `module/`（LFS/ignore 区，像 AI 仓库一样可选装）+ 仓库内只留薄适配器。**建议 B**（与 basicpitch/musicgen 同构） |
| Q5 | GitHub 仓库名即改还是发布时改 | 建议 R1 立即改（越早越好，重定向自动生效） |

## 5. 风险表

| 风险 | 缓解 |
|---|---|
| 目录改名导致 venv/IDE/计划任务路径失效 | R1 前记录可迁移项清单；venv 可直接重建（editable ×3 重装） |
| R4 import 迁移漏改 | 全仓 `grep -r "smartnotegen"` 清单驱动 + shim 包兜底 + 全量回归 |
| VASR 依赖过重拖垮主包安装 | 适配器延迟导入 + 可选装（requirements/vasr.txt），CI 零 torch 断言扩展 |
| 海绵/天音接口非官方，随时失效 | adapter 隔离 + 契约测试 + 失败只告警不阻塞主流程 |
| 改名期文档/元数据漂移 | 版本对齐守卫已覆盖三包；新增「发行名 vs 仓库名」断言 |

## 6. 不做清单（本期明确排除）
- 不逆向海绵音乐/网易天音客户端加密（同猫抓结论边界：明文可取、密文不碰）
- 不动 `output/`（用户产出目录）、`Suno-Cat-Catch-Resolve/out/`
- 不在重构期顺手重写业务逻辑——重构与功能分阶段各自提交
