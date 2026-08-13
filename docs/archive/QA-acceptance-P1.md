# SmartNoteGen 一期（非 AI）独立验收报告 — QA（严过关 / Edward）

> 验收人：QA Engineer（Edward）
> 验收对象：一期非 AI 冲刺（M-1 + P1-3 + P2-1/2/4/5 + P2-3 收口）
> 交付方自述：197 测试全绿、覆盖率 90.94%、本机渲染真跑通过、IS_PASS: YES
> 验收方式：独立复跑（fresh eyes），不盲信自测，全部实测
> 日期：2026-08-09
> 结果：**路由判定 = Engineer（源码需修，2 处缺陷）**；其余验收点全部实测通过

---

# 第 2 轮回归验收（2026-08-09，工程师修复后最终回归）

> 修复对象：缺陷 A（Bb 解析失败）、缺陷 B（--rhythm 被 --style 静默覆盖）
> 交付方自述：207 测试全绿、覆盖率 91%、3 条验收命令实测通过
> 验收方式：独立复跑（fresh eyes），全量测试 + 3 条验收命令 + 原通过项抽查
> 结果：**路由判定 = NoOne（修复有效，无回归）**；验收通过 ✅

## R2-1 全量测试独立复跑

| 项 | 结果 |
|---|---|
| 收集用例数 | **207**（197 + 10：chords +4、batch +2、cli +4） |
| 通过 | **207 / 207**（0 失败） |
| 覆盖率（独立复测） | **91%**（2329 stmts / 208 miss） |

## R2-2 三条验收命令独立复跑

| # | 命令 | 期望 | 实测 | 结论 |
|---|---|---|---|---|
| 1 | `batch --count 6 --seed 1 --style electronic` | 成功 6/失败 0，退出码 0 | 6 项全 ok（seed 1000-1005），退出码 0 | ✅ |
| 2 | `generate midi --style pop --rhythm nonexistent` | 退出码 1 + "未知节奏型" | `错误 [1]: 未知节奏型: 'nonexistent'`，退出码 1 | ✅ |
| 3 | `generate midi --style pop --rhythm funk` vs 默认 pop | 显式值生效，字节不同 | funk md5=4ec0a55b，pop 默认 md5=6cb81a82，**字节不同** | ✅ |

## R2-3 原第 1 轮通过项抽查（防回归）

| 原验收点 | 抽查方式 | 结论 |
|---|---|---|
| render 真跑 | 真跑 WAV：44.1kHz/16bit/stereo、19.1s、峰值 -12.5dBFS、0 削波 | ✅ |
| module 删除→码 7 | 配置指向不存在 fluidsynth → MISSING 分级 + 修复指引 + 退出码 7（零环境风险方式；环境已恢复并复验 render EXIT=0） | ✅ |
| DSP -1dBFS | render WAV 峰值 -12.5dBFS ≤ -1dBFS、0 削波 | ✅ |
| 乐理默认关 | `Config.load().defaults` voice_leading/counterpoint/inversion 均 False | ✅ |
| 输出管理防覆盖 | 同 seed 42 两次生成 → seq_1/seq_2 并存（字节一致、命名递增不覆盖） | ✅ |
| 零 torch | 导入 cli/chords/batch/dsp 后 torch/audiocraft 不在 sys.modules | ✅ |
| 平行五度/八度检测器 | test_music_theory.py 14 例全绿（含 P5/P8/反向不误报） | ✅ |
| batch 失败隔离/退出码 8/9 | test_batch 3 例单独复跑全绿 | ✅ |
| 缺陷 A/B 回归测试 | test_chords(12) + electronic batch(2) + cli rhythm(3) 单独复跑 17 例全绿 | ✅ |

## R2-4 Bb 归一化对其他和弦路径影响验证（QA 独立构造）

- 降号根音全映射正确：Bb(10)、Bb7(10)、Eb(3)、Ab(8)、Db(1)、Gb(6)、Cb(11)、Fb(4)，音级集合均正确 ✅
- 非降号/扩展音路径不受影响：`_normalize_symbol('Cm7b5')` 原样返回（**b5 不被触碰**）、`Gb7b5`→`F#7b5`（仅根音）✅
- 完整池解析：`Dm-Bb-F-C`、`Dm-A#-F-C`、`Dm-Bb-F-C-Gm-C7` 等均正常 ✅
- 注：`B-` 在 music21 中解析为 Bb 语义（root=10）为 **music21 既有行为**，`_normalize_symbol('B-')` 原样返回未被触碰，非本次修复引入的回归（与本修复无关的既有怪癖，不影响默认池/预设路径）。

## R2-5 结论

- 工程师修复声明（207 全绿、91%、3 条命令通过）**经独立复测全部属实**。
- 缺陷 A、缺陷 B 均修复有效，且未引入回归（原通过项抽查全部通过）。
- **智能路由：NoOne（验收通过）**。第 2 轮为最终回归，无遗留源码缺陷。
- 环境已恢复：module/fluidsynth 与 SoundFont 完整；QA 临时产物已清理。

---

## 1. 独立测试结果

### 1.1 全量测试（venv pytest，独立复跑）

| 项 | 结果 |
|---|---|
| 收集用例数 | **197**（与交付方一致） |
| 通过 | **197 / 197**（0 失败） |
| 覆盖率（独立复测） | **91%**（2318 stmts / 216 miss，`--omit=__main__.py,ai/*`） |
| 覆盖率目标 | ≥ 80% ✅ |

> 覆盖率复测方法：沙箱回收站不可用导致 pytest-cov 清理数据文件失败，改用
> `coverage run -m pytest -p no:cov` + `coverage report` 独立测得 91%，与交付方 90.94% 一致。

### 1.2 分文件用例分布（197 = 原 106 + 新增 91）

```
test_batch.py:12  test_chords.py:8   test_cli.py:22   test_config.py:14
test_dsp.py:11    test_env.py:15     test_error_codes.py:5  test_export.py:14
test_generators.py:10  test_logging.py:5  test_midi.py:6   test_music_theory.py:14
test_output_manager.py:8  test_postprocess.py:5  test_qa_edge_cases.py:26
test_render.py:6  test_render_m1.py:8  test_styles.py:8
```

### 1.3 新增边界用例（QA 独立构造，非交付方测试）

QA 在本机真实环境额外构造并验证了以下边界场景（未落入 tests/，仅实测）：

1. `render` 删除 `module/fluidsynth` → 退出码 7 + MISSING 分级 + 修复指引 + **无静默 mock 产物**（已恢复环境）。
2. 伪造 `.sf2`（存在但不可加载）→ BROKEN 分级 + ConfigError(2)（非 module 路径语义正确）。
3. `--soundfont` / `--fluidsynth` 绝对路径覆盖 → 均成功渲染。
4. `render --dry-run` / `pipeline --dry-run` → 零落盘。
5. `batch --count 5 --seed 42` 两次运行 → 5 个 MIDI **逐字节一致**；`--render` 链 WAV 逐字节一致。
6. `batch --render --export` 链式 → 每项产出 midi+wav+suno 三产物 + metadata.json 完整。
7. `batch` 全部失败（非法和弦池）→ 退出码 9；部分失败 → 退出码 8。
8. 平行五度/八度检测器：构造平行五度、平行八度输入可检出；反向进行不误报。
9. `--rhythm` 无 `--style` 时非法名报错 1；**有 `--style` 时被静默覆盖（缺陷，见 §3）**。
10. `pipeline --reverb` → 显式报错 1（未支持，不静默忽略）。
11. `--style pop/rock/electronic/classical` 各跑通；自定义 `jazz.toml` 注册可引用；非法风格名报错 1。
12. `--verbose` 输出 DEBUG、`--quiet` 仅结果、`--debug` 打印堆栈；`errors` 子命令含 7/8/9。
13. 零 torch：导入全部非 AI 模块后 `torch/audiocraft/diffrhythm` 均不在 `sys.modules`；`ai musicgen` 退出码 6。

---

## 2. 验收点逐项实测结论

| # | 验收点 | 结论 | 证据 |
|---|---|---|---|
| 1 | 独立复跑 197 全绿、覆盖率 ≥80% | ✅ | 197/197 通过；91% |
| 2a | `render --input <demo.mid>` 零参数真跑真实 WAV | ✅ | 44.1kHz/16bit 立体声；时长 19.1s（MIDI 16s + 引擎尾音）；峰值 -12.5dBFS ≤ -1dBFS；0 削波 |
| 2b | `pipeline` 默认配置端到端真跑（无 mock 日志） | ✅ | 生成→渲染→DSP→导出全链，产物 `{project}/20260809/{style}_{bpm}_{seed}_{seq}*`，含 metadata.json |
| 2c | 删除 module/fluidsynth → 错误码 7 + MISSING + 无静默 mock（验证后已恢复） | ✅ | 实测退出码 7；无 wav 产物 |
| 2d | 错误 sf2 → BROKEN；--soundfont/--fluidsynth 绝对路径覆盖成功 | ✅ | 伪造 sf2 → BROKEN→ConfigError(2)；两个覆盖均成功 |
| 2e | `--dry-run` 零落盘；`config init` 模板含 module 相对路径 | ✅ | 两者均实测 |
| 3 | batch `--count 5 --seed 42` 复现性、失败隔离、退出码 8/9、链式 | ✅（含 1 项缺陷，见 §3-B） | MIDI/WAV 逐字节一致；非法和弦不中断；0/8/9 正确 |
| 4 | 输出管理 project/date、命名防覆盖、metadata 完整、layout 双档 | ✅ | `<root>/<project>/<YYYYMMDD>/`；`{style}_{bpm}_{seed}_{seq}`；metadata.json 字段齐（schema_version/run/artifacts）；project-date 与 legacy 均验证 |
| 5 | DSP -1dBFS 无削波、淡入淡出生效、非法参数报错、suno 恒禁混响 | ✅ | pipeline WAV 峰值 -12.2dBFS ≤ -1dBFS、0 削波；首/尾 50ms 包络可见；fade 越界/ratio<1 → ParameterError(1)；`--reverb` 显式报错；SunoExporter 有恒禁混响守卫 |
| 6 | 乐理默认关闭（P0 输出不变）；平行五度检测器可检出；节奏型 ≥6 + 自定义 | ✅ | 既有 106 测试全绿（默认关闭未破坏）；检测器实测检出 P5/P8；库 6 种 + from_string/from_json |
| 7 | 风格库 4 基线可跑；自定义注册可引用；非法名报错 | ✅ | 4 风格 CLI 各跑通；jazz.toml 注册后 `--style jazz` 成功；非法名 → StyleError(1) |
| 8 | --verbose/--quiet/--debug 生效；errors 错误码表含 7/8/9；新增模块测试存在 | ✅ | 均实测；分文件用例分布见 §1.2 |
| 9 | 零 torch 保持 | ✅ | `sys.modules` 实测无 torch/audiocraft/diffrhythm；AI 命令退出码 6 |
| 10 | 6 项偏差评估 | ⚠️ 见 §4 | 版本/Config CWD/内置 legacy 合理；batch seed 0 基派生与 test_batch 断言自洽；SF2 判定方式合理 |

---

## 3. 智能路由判定

### 路由：**Engineer（源码需修）** — 2 处缺陷

### 缺陷 A（高影响）：默认和弦池含无法解析的和弦 `Bb`，导致合法 seed 下 batch 随机失败

- **文件/位置**：
  - `src/smartnotegen/batch.py:44` — `DEFAULT_CHORD_POOL` 含 `"Dm-Bb-F-C"`
  - `src/smartnotegen/styles/presets/electronic.toml:7` — `chord_preference` 含 `"Dm-Bb-F-C"`
- **复现**：
  ```bash
  smartnotegen batch --count 6 --seed 1 --style electronic
  # → 成功 1 / 失败 5（失败原因均为 "无法解析和弦符号: 'Bb'"）
  ```
- **根因**：`ChordProgression._parse_single` 用 `music21.harmony.ChordSymbol('Bb')` 解析，`Bb` 在 music21 中抛 `ValueError: Invalid chord abbreviation 'b'`（实测 `A#`/`B-`/`Bb7` 可解析，裸 `Bb` 不可）。默认池与 electronic 预设使用了解析器不支持的符号，属于**数据缺陷**。
- **影响**：非构造场景（默认 `--chords-choices` 或 `--style electronic`）下 batch 会随机失败，违反 P1-3 “合法输入可复现、失败项为构造异常”的预期；对外表现为偶发退出码 8。
- **建议修复**（供工程师参考，不代改）：将 `Dm-Bb-F-C` 改为 `Dm-A#-F-C`（或 `Dm-B--F-C`/`Dm-Bb7-F-C`，均已实测可解析）；更稳妥做法是在 `ChordProgression._parse_single` 对 `Bb` 做归一化（如 `Bb` → `A#`/`B-`），使解析器对常见降号书写健壮。

### 缺陷 B（中影响）：`--rhythm` CLI 参数在 `--style` 存在时被静默覆盖，且掩盖非法节奏型错误

- **文件/位置**：`src/smartnotegen/cli.py:132-133`（`_apply_style_preset`）
  ```python
  if preset.rhythm_pattern:
      request.rhythm_pattern = preset.rhythm_pattern   # ← 无条件覆盖用户 --rhythm
  ```
- **复现**：
  ```bash
  # 期望：报"未知节奏型" 或 使用 funk；实际：静默使用 pop 预设节奏型
  smartnotegen generate midi --style pop --rhythm funk --seed 8          # 成功但实际用 pop
  smartnotegen generate midi --style pop --rhythm nonexistent --seed 8   # 成功（错误被掩盖）
  # 对照：无 --style 时非法名正确报错
  smartnotegen generate midi --rhythm nonexistent --seed 8               # 退出码 1 未知节奏型
  ```
- **根因**：`_apply_style_preset` 对 `bpm`/`chords` 均有 `*_explicit` 保护（`bpm_explicit is None`、`chords_explicit is None`），但 `rhythm_pattern` 没有对应保护，违反“CLI 参数 > 配置 > 风格预设”的合并优先级（architecture §1.1.1）。batch 路径（`batch.py:215`）有 `if opts.rhythm_pattern` 保护，因此**同一参数在 generate/pipeline 与 batch 行为不一致**。
- **影响**：用户显式指定 `--rhythm` 时静默不生效（生成器实际用风格预设节奏型）；非法 `--rhythm` 与 `--style` 组合不报错，掩盖配置错误。
- **建议修复**：为 `_apply_style_preset` 增加 `rhythm_explicit` 参数（与 bpm/chords 一致），仅当用户未显式指定 `--rhythm` 时才用 `preset.rhythm_pattern` 填充。

---

## 4. 6 项偏差评估（验收点 10）

| 偏差 | 评估 | 归属 |
|---|---|---|
| 版本号 0.1.0（未按 P2-3 提升到 0.2.0） | ✅ 合理：CHANGELOG 已注明“版本号保持 0.1.0（--version 断言兼容，规范化延后）”，`test_cli.py::test_version` 断言 0.1.0，一致性成立；非阻塞 | Engineer（文档化即可） |
| `Config.load` 沿用 CWD 查找（未用 ProjectRootResolver 向上探测） | ✅ 合理：`config.py:283-285` 注释说明为避免 pytest 临时目录被误判为项目根；但**存在边界隐患**——在非项目根 CWD 运行时不会加载 `config/default.toml`，退回内置 legacy 路径（实测 `config show` 从其他 CWD 显示内置默认）。建议文档注明“应从项目根运行或显式 `--config`” | 观察项（非阻塞） |
| 内置 paths 保留 legacy（assets/... 与 PATH 查找） | ✅ 合理：`config.py` 注释明确“无 config/default.toml 时行为与 P0 一致”，保证既有测试兼容；module/ 路径由 default.toml 提供 | 确认 |
| batch seed 0 基派生（`seed*1000+i`，i 从 0 起） | ✅ 合理：确定性且文档化（`batch.py:4` 注释、`test_batch.py` 断言 `[42000,42001,42002]`）；架构示例为 1 基（42001..），实现为 0 基（42000..），属实现细节偏差，可复现性不受影响 | 确认（文档同步即可） |
| `test_batch` 断言更新（0 基派生） | ✅ 合理：断言与实现一致，属正确同步 | 确认 |
| SF2 可加载判定（退出码 0 + 无错误文本） | ✅ 合理：Windows fluidsynth 对无法识别文件仍返回 0 但在输出打印错误文本，`env.py:259-280` 以“退出码 0 且无错误文本”判定，`test_env.py` 覆盖；比纯退出码判定更健壮 | 确认 |

---

## 5. 遗留观察清单（非阻塞）

1. **batch metadata `run.duration_s` 为 0.0**：batch 写入 metadata.json 时未填真实耗时（`batch.py:177` 硬编码 0.0），与 pipeline（记录真实值）不一致；不影响 schema 完整性，建议后续补记。
2. **非项目根 CWD 行为**：`Config.load` 仅 CWD 查找，从其他目录运行时默认配置退化为内置 legacy；建议 README/usage 注明运行位置要求（见 §4 第 2 项）。
3. **渲染时长含引擎尾音**：`render` 直接渲染产物约 19.1s（MIDI 16s + fluidsynth 尾音），PRD 验收“±0.5s”在字面上不满足，但 `pipeline` 的 DSP/导出阶段按目标时长裁剪，最终 Suno 产物精确 25s；`render` 子命令本身不做裁剪属设计选择，建议文档说明。
4. **batch 无 `--seed` 时日志记录 seed**：已实现（实测“未指定 --seed，使用系统熵生成全局种子: N”）；但 metadata.json 中 `command` 会以实际 seed 回填，符合 P1-3 验收 3。
5. **`test_qa_edge_cases.py` 26 例为新增边界用例**：覆盖了非法参数/路径/种子等，质量良好，无需处理。
6. **`styles/` 自定义目录**：`config/default.toml [styles] dir="styles"` 相对 CWD 解析；QA 实测在项目根 `styles/` 放 `jazz.toml` 可被 `--style jazz` 引用（验收通过）。

---

## 6. 结论

- 交付方自测声明（197 全绿、覆盖率 ≥90%、本机真跑）**经独立复测属实**。
- 10 项验收点中 **8 项完全通过、2 项有条件通过**（batch 含缺陷 A、`--rhythm` 含缺陷 B）。
- 智能路由：**Engineer** — 2 处源码缺陷（文件 + 行号 + 复现见 §3），修复后建议 QA 回归（第 2 轮）。
- 环境已恢复：`module/fluidsynth` 与双 SoundFont 完整；QA 临时产物已清理。
