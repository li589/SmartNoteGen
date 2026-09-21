# SunoAuxTool 下一环节（Phase 4）集成与扩展设计规划

> 状态基线：v1.0.0（R0–R8 全部完成，2026-09-21 已发布 tag）。
> 本规划基于 2026-09-21 对仓库真实状态的调研（占位/桩代码、已验证未入库模块、扩展点、覆盖率、路线图），
> 旨在定义 R8 之后的下一环节：**集成固化（Integration）** 与 **扩展（Extension）** 两条主线。
> 本文为设计规划，不含实现；执行前需逐条确认范围。
>
> **执行状态（2026-09-22 更新）：R9–R15 已全部完成并推送，本文自此转为「历史设计记录」，
> 不再作为待办清单使用。**

| 编号 | 内容 | 版本 | commit |
|---|---|---|---|
| R9 | VASR / AudioSR 真入库 + 补丁进管控 + 专属测试 | 1.1.0 | `94fa8e3` |
| R10 | 一致性清理（死代码 + 过时注释 + 文档对齐） | 1.1.0 | `94fa8e3` |
| R11 | Download API 源凭证接入 + `fetch --dry-run` 自检 | 1.1.0 | `e08f844` |
| R12 | 统一插件 / 扩展架构（entry-point 自动发现） | 1.2.0 | `e08f844` |
| R13 | 分析子系统扩展（调性 / 和弦 / 结构） | 1.2.0 | `e08f844` |
| R14 | DSP 混响补全（Suno 合规边界内） | 1.3.0 | `e08f844` |
| R15 | 视频扩展（`bars`）+ 测试补强 + 视频 scrub 预览 | 1.3.0 | `e08f844` + `5a5a367` |

> 完成后状态：版本 **v1.3.0**；全量测试通过，覆盖率 **88.21%**（门槛 87%）；
> Phase 4 收官，后续方向另立规划。

---

## 0. 调研结论（当前状态基线）

| 维度 | 现状 | 证据 |
|---|---|---|
| 未完成功能 | 极少且集中：`--reverb` 显式 `ParameterError`；`CatCatchSource.report` 预留 `# pragma: no cover`；死代码 `_not_implemented` / `_interval()` | `dsp/processor.py:69-74`、`download/sources/catcatch.py:71-72`、`aggregate.py:138-140`、`ci-remediation-plan.md:62` |
| 集成缺口（最大） | VASR/AudioSR 已实跑验证但未真入库；源码 gitignored；本地长音频补丁脱离版本控制；`ai/audiosr.py` 无专属测试 | `.gitignore:62`、`requirements/vasr.txt`、`src/sunoauxtool/ai/audiosr.py` |
| 扩展架构缺口 | 无 `importlib` 动态加载 / entry-point 发现；AI 后端、渲染引擎、下载源、转谱后端均半手动接线 | `ai/__init__.py`、`render/fluidsynth.py:30`、`download/sources/base.py:41-49`、`cli.py:1023-1044`、`video/visuals/__init__.py:41-49` |
| 路线图 | 止于 R8，无 R9+/Phase 4 | `docs/reports/refactor-sunoauxtool-plan.md`（R0–R8 ✅）、`CHANGELOG.md` 顶部 `[1.0.0]` |
| 覆盖率 | 统一口径 `source=["sunoauxtool"]`、`fail_under=87`；基线 87.53%；videomaker 已并入统一口径（无单独 `--cov`） | `pyproject.toml:52-59`、CI `ci.yml` |
| 文档/注释过时 | `aggregate.py:13`「R6 交付占位」、`cli.py:1337`「P1 骨架」、`CHANGELOG.md:24`、`tests/test_aggregate_cli.py:7/:256` 与已实现状态矛盾 | 见各文件行号 |

**结论**：核心能力已闭环，下一环节重点不是「补功能」，而是 **(A) 把已验证但未真正纳入版本控制与 CI 的能力固化**，**(B) 引入可插拔扩展架构并为分析/DSP/视频补能力**。

---

## 1. 总览与原则

- **两条主线**
  - **Track A 集成固化（v1.1）**：VASR 真入库 + 补丁进管控 + 专属测试；一致性清理；Download API 源凭证接入（按需）。
  - **Track B 扩展架构（v1.2）**：统一插件/扩展架构（entry-point 发现）；分析子系统扩展（调性/和弦/结构）。
  - **Track C 能力补全（v1.3）**：DSP 混响补全；视频/谱面扩展与测试补强。
- **不变原则**（继承自 R0–R8）
  - 核心层不得反向依赖 CLI 层；`sunoaux` 薄转发层只 import 不被 import。
  - 兼容 shim（`smartnotegen`/`videomaker`/`downloadhelper` 入口、异常基类 `SmartNoteGenError`）保留 ≥1 版本。
  - P0 路径零 `torch` import；AI 依赖延迟导入（`find_spec` 门控，退出码 6）。
  - 覆盖率门槛 **不下调**（87%）；新增模块必须配测试，不得稀释基线。

---

## 2. Track A — 集成固化（v1.1 目标）

### R9  VASR / AudioSR 真入库 + 补丁进管控 + 专属测试

**目标**：让「音质提升」能力在重克隆/CI 复现时可稳定复现，且长音频补丁受版本控制。

**现状（证据）**
- 源码 `src/versatile_audio_super_resolution/` 是上游 fork @ `d312fba`，**自带内嵌 `.git`**，被 `.gitignore:62` 整体忽略，`pyproject.toml:41` 打包 `exclude`、`pyproject.toml:65` ruff `extend-exclude`。
- `requirements/vasr.txt` 记录源码采用「目录模式」（默认路径或 `AUDIOSR_DIR`），适配器延迟导入、退出码 6。
- `src/sunoauxtool/ai/audiosr.py` 适配器已完整实现（`resolve_audiosr_dir` / `is_available` / `enhance` 长音频 15s 分块 2s 重叠交叉淡化）。
- **缺口**：本地 `[SunoAuxTool patch R5]`（`audiosr/pipeline.py::super_resolution_long_audio` 末块<overlap 时 fade 切片越界 + overlap-add 广播失败修复）只存在于 gitignored 源码内，不在仓库管控；重克隆上游不重打 → 长音频末块<2s 必崩。
- `tests/` 无 `test_ai_audiosr.py`，仅经 `test_aggregate_cli.py` 的 mock + 依赖不可用断言间接覆盖。

**设计**
1. **源码仍 gitignored（不污染主仓）**，但补丁纳入管控：
   - 新增 `patches/vasr_super_resolution_long_audio.patch`：统一 diff，头部注释记录上游 commit `d312fba`、原文件行号、修复语义。
   - 新增 `scripts/setup_vasr.py`：定位/克隆上游 → 若 `AUDIOSR_DIR` 为空则克隆到 `src/versatile_audio_super_resolution` → 应用补丁 → 回显权重缓存位置（`~/.cache/huggingface`）。CI 中作为「可选装」步骤（不阻塞主 CI）。
2. **放宽上游 `setup.py` 三处死 pin**（R5 已实测可放开）：`numpy<=1.23.5` / `librosa==0.9.2` / `transformers==4.30.2` → 放宽为兼容区间；`diffusers` 死依赖移除；`gradio` 仅 `app.py` 用，改为可选。
3. **删内嵌 `.git` + ruff 153 处**：执行 R5 计划「入库三步」中剩余两步；ruff 真修或保持 `extend-exclude`（不阻塞，但需在 `requirements/vasr.txt` 标注）。
4. **torch 未来断点**：仓内 13 处 `torch.load` 补 `weights_only=False` 并加 `# TODO(torch>=2.6)` 注释（当前 2.5.1 无影响）。
5. **新增 `tests/test_ai_audiosr.py`**：用临时 fake 目录 + 假模型路径验证 `resolve_audiosr_dir` / `_load_model` / `enhance` 分块与重叠逻辑（不拉真实 2.6GB 权重）；依赖不可用路径仍断言退出码 6。

**关键文件**：`src/sunoauxtool/ai/audiosr.py`、`requirements/vasr.txt`、`scripts/setup_vasr.py`（新）、`patches/`（新）、`tests/test_ai_audiosr.py`（新）、`.gitignore`、`pyproject.toml`。

**风险**：主 venv torch `2.5.1+cu121` 与上游要求 `2.0.1+cu118` 冲突 → 维持 R5 结论「主 venv 直调 + 薄适配器」，不建独立 venv；仅当 CI 跑 VASR 用例时需专用镜像。

**验收**：重克隆后 `scripts/setup_vasr.py` 一次成功；长音频（>2s 末块）超分不崩；`tests/test_ai_audiosr.py` 绿；主 CI 仍不依赖 VASR。

---

### R10  一致性清理（死代码 + 过时注释 + 文档对齐）

**目标**：消除与已实现状态矛盾的「占位」表述与死代码，降低维护噪声。

**范围（含）**
- 删除 `aggregate.py:138-140` `_not_implemented`（全仓零调用，死代码）。
- 删除 `generators/procedural.py` `_interval()`（零引用，死代码）。
- 修正过时注释：`aggregate.py:13`「R6 交付占位」→「R6 已交付」；`cli.py:1337`「P1 骨架；二期完整实现」→「已完整实现」；`tests/test_aggregate_cli.py:7/:256` 占位说明同步。
- 对齐 `CHANGELOG.md:24` 自相矛盾的「post dsp 为 R6 交付占位」表述。

**范围（不含）**：不重写业务逻辑；不动兼容 shim。

**验收**：`ruff check src/` 干净；`grep -rn "占位\|尚未实现\|P1 骨架" src/ docs/` 无与现状矛盾项。

---

### R11  Download API 源真实接入（按需 / 凭证驱动）

**目标**：让 `suno-api` / `haimeng` / `tianyin` 三类 API 源在拿到合法端点与凭证后可真实取回。

**现状（证据）**：`download/sources/api.py` 通用 `ApiSource` 已接线，契约明确（`GET {endpoint}?id=` + `Bearer` + `{"files":[{url,name}]}`）；`base.py:41-49` `list_sources()` 硬编码注册；凭证缺失→`SourceCredentialError(25)`、请求失败→`SourceRequestError(26)` 已具备；配置 `config/sources.toml` / `~/.sunoauxtool/sources.toml` 均 gitignored。

**设计**
1. **文档化 `sources.toml` schema**（写入 `docs/downloadhelper.md`）：`[suno-api]` / `[haimeng]` / `[tianyin]` 各含 `endpoint` / `token`。
2. **协议分化**：若三源契约不同，各写 `ApiSource` 子类覆盖 `_list_files` / `_download`；当前三者共用同一通用契约，可暂不分化。
3. **凭证自检**：`fetch --source X --dry-run` 仅校验凭证可用性并报 `SourceCredentialError(25)`，便于用户侧排错。
4. 本仓不存任何凭证；真实端点由用户侧提供。

**验收**：用户提供 endpoint+token 后 `fetch --source haimeng <id>` 跑通一条；缺凭证时干净报 25。

---

## 3. Track B — 扩展架构（v1.2 目标）

### R12  统一插件 / 扩展架构（entry-point 自动发现）

**目标**：引入可插拔扩展机制，使第三方包可通过 `importlib.metadata` entry points 注册 AI 后端 / 渲染引擎 / 下载源 / 转谱后端 / 视频视觉层，无需改核心代码。

**现状（证据）**：现有扩展点——`StyleRegistry`（`styles/registry.py:57-143`，配置驱动，最成熟）、`RhythmPatternRegistry`（`music_theory/rhythm_patterns.py:45`）、`video/visuals/__init__.py:41-49`（硬编码 dict）、`ai/__init__.py` + `cli.py`（手动 import+注册）、`render/fluidsynth.py:30`（单实现，无注册表）、`transcribe --backend` if/elif（`cli.py:1023-1044`）、`download/sources/base.py` `list_sources()` 手动。

**设计**
1. **每个扩展点 = ABC + `discover()`**：`discover()` 合并 builtins（硬编码注册，保持兼容）与 `importlib.metadata.entry_points(group="sunoauxtool.<point>")`。
   - groups：`sunoauxtool.ai_backends` / `render_engines` / `download_sources` / `transcribe_backends` / `video_visuals`。
2. **替换现有手写注册**：`list_sources()` → `discover_sources()`；`video/visuals` 硬编码 dict → `discover_visuals()`；`transcribe` if/elif → `discover_transcribe_backends()`；`ai/__init__.py` 仅注册 builtins，第三方经 entry point。
3. **隔离 loading 失败**：单个 entry point 导入/注册异常只 `warnings.warn` 并跳过，不拖垮内置能力。
4. **保持约束**：builtins 仍硬编码，entry points 追加；`sunoaux` 薄转发层不变；AI 后端延迟导入（P0 路径零 torch）。

**关键文件**：`src/sunoauxtool/{ai,render,download,analysis,video}/` 各加 `*_registry.py` 或扩展现有；`pyproject.toml` 增加示例 `entry-points` 段（仅注释示范）；`aggregate.py` / `cli.py` 改用 `discover()`。

**风险**：entry point 加载失败隔离不当会拖垮 CLI；需严格 try/except + 告警而非抛错。

**验收**：写一个示例外部包（或本仓 `examples/plugin_demo`）经 entry point 注册一个新 transcribe 后端并能被 `transcribe --backend demo` 发现；内置 shim 行为不变；CI 加「插件发现不崩」冒烟测试。

---

### R13  分析子系统扩展（调性 / 和弦 / 结构）

**目标**：在现有 `analysis/`（numpy-only，tempo + 单旋律转谱）基础上，新增调性估计、和弦识别、结构分段，统一暴露为 `analyze` 命令，反哺「前期」风格预设与「后期」分段视频。

**现状（证据）**：`src/sunoauxtool/analysis/` 已落地 `tempo.py` / `transcribe.py` / `spectral.py`（numpy-only，无 librosa）；`transcribe` 内置后端仅适合单旋律，复调走 basic-pitch。

**设计**
1. **`analysis/key.py`**：Krumhansl-Schmuckler 调性剖面（基于 chroma 直方图），输入 WAV 或 MIDI；输出 `(key, mode, confidence)`。
2. **`analysis/chords.py`**：从转谱 MIDI 或 harmonic salience 估计和弦（根音+质量），复用 `transcribe` 的谐波 salience 底座；输出分段和弦进行。
3. **`analysis/structure.py`**：基于自相似矩阵的副歌/主歌分段（lag 自相关或 novelty 曲线），输出段落边界时间轴。
4. **CLI**：`analyze <wav> [--key] [--chords] [--structure] [--json out.json]`；全部 numpy-only，与 `tempo`/`transcribe` 共用 `spectral` 底座。
5. **反哺**：`key`/`chords` 结果可写入 `StyleRegistry` 候选、`structure` 段边界供 `videomaker --style score` 的章节切换使用。

**验收**：合成素材上 key 估计误差 ≤1 半音、和弦进行可还原；`tests/test_analysis_*.py` 新增；覆盖率不稀释。

---

## 4. Track C — 能力补全（v1.3 目标）

### R14  DSP 混响补全

**目标**：实现 `DspProcessor` 当前显式 `ParameterError` 的 `--reverb`。

**现状（证据）**：`dsp/processor.py:69-74` `--reverb` 抛 `ParameterError(1)`，注释「本增量未实现；Suno 导出链恒禁混响」。

**设计**
1. **`dsp/ops.py` 加 `reverb` 卷积算子**：IR 来源 = `config` 指定路径或内置合成 IR（短指数衰减脉冲）；支持 `wet/dry` 混合。
2. **明确边界**：仅 `post dsp` standalone 后处理路径可用；`export suno` 链与 `pipeline`（Suno 合规）**不接** reverb（维持「无混响」合规约束）。
3. IR 资源不入库（小体积可内置合成，避免 LFS）。

**验收**：`post dsp --ops "reverb 0.3"` 输出可闻混响且不爆音；`export suno` 路径不受影响；`test_dsp_ops.py` 补 reverb 分支。

---

### R15  视频 / 谱面扩展与测试补强

**目标**：扩展音乐视频视觉层、实时预览，并补强 `video/*` 当前薄/零覆盖子模块。

**现状（证据）**：`video/visuals/`、`video/engines/`、`video/analysis/audio_analysis.py`、`video/mixer.py`、`video/compositor.py`、`video/text.py`、`video/config.py` 多无独立测试；`preview.py` 已有音频预览（HTML），未延伸至视频 scrub。

**设计**
1. **更多视觉层**：在 `discover_visuals()`（R12）注册表中加 1–2 个新风格（如 `lyric_karaoke`、`stem_separate`）。
2. **实时预览**：`preview.py` 扩展支持视频产物缩略帧 + 时间轴 scrub（复用现有 HTML 模板）。
3. **测试补强**：为 `video/visuals`、`video/mixer`、`video/compositor` 加单元/像素探针测试（沿用 `raster-output-visual-verify` 方法论）。

**验收**：新视觉层经 `video render --style <new>` 产出；`video/*` 覆盖率显著提升；像素探针不溢出。

---

## 5. 不做什么（显式 non-goals）

- 不逆向海绵音乐 / 网易天音客户端加密（同重构计划「不做清单」）。
- 不在本期重写既有业务逻辑；R10 仅删死代码与改注释。
- 不把 VASR 权重（~2.6GB）或任何大模型权重入库（LFS 配额约束）。
- 不下调覆盖率门槛（87%）。
- 不建 VASR 独立 venv（维持 R5「主 venv 直调 + 薄适配器」结论）。

---

## 6. 风险与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| VASR torch 版本冲突（2.5.1 vs 上游 2.0.1） | 主 venv 直调可能不稳 | 维持薄适配器 + 延迟导入；CI 跑 VASR 用例用专用镜像 |
| 插件架构加载失败拖垮 CLI | 一个坏插件致全局不可用 | entry point 加载严格 try/except + 告警跳过（R12） |
| 新增模块稀释覆盖率 | CI 红 | 每个新模块配测试，AI/audiosr 必须专属测试（R9） |
| 长音频补丁丢失 | 末块<2s 超分必崩 | 补丁进 `patches/` 管控 + `scripts/setup_vasr.py` 自动应用（R9） |

---

## 7. 建议执行序列

```
R10 一致性清理（快速、低风险、立即可做）
  → R9  VASR 真入库 + 补丁进管控 + 专属测试
  → R11 Download API 源凭证接入（按需，依赖用户侧 endpoint+token）
  → R12 统一插件/扩展架构（架构地基，解锁后续扩展）
  → R13 分析子系统扩展（调性/和弦/结构）
  → R14 DSP 混响补全
  → R15 视频/谱面扩展与测试补强
```

**版本映射**：R10+R9+R11 → **v1.1.0**；R12+R13 → **v1.2.0**；R14+R15 → **v1.3.0**。

**首推起点**：R10（清理，1 个短 PR）+ R9（集成固化，价值最高且当前最脆弱）。两者不互相依赖，可并行推进。
