# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 风格。

## [Unreleased]

### 新增
- **`src/Suno-Cat-Catch-Resolve` 子项目 v0.1.0**（`src/` 下独立 editable 兄弟包，与
  `smartnotegen` / `videomaker` 并列）：Suno「猫抓」产物逆向取证与转码。
  - `fmp4.py`：ISO BMFF 原子解析、mdat 分片提取（识别 fragmented MP4）
  - `forensics.py`：熵 / 卡方 χ² / 周期扫描 → 判定明文 or 密文（核心取证层）
  - `transcoder.py`：ffmpeg 封装（Ogg Opus 无损重封装 / MP3 转码 / 探测）
  - `cli.py`：`probe` / `decode` / `batch` / `version`（Typer）
  - `exceptions.py`：错误码 20-24（延续分段：smartnotegen 0-9、videomaker 10-14）
  - 核心层零第三方依赖，仅 CLI 依赖 typer。
- **取证结论入库**：猫抓直下的 `<uuid>.m4a` 为服务端下发的加密密文
  （χ²≈215 完美均匀、无周期性 → AES/ChaCha20 级强加密），无密钥不可破；
  缓存捕获的 fMP4 是同一首曲子的完整明文副本，直接解码即可。

### 配置
- 主 `pyproject.toml` 的 `[tool.setuptools.packages.find]` 新增
  `exclude = ["Suno-Cat-Catch-Resolve*"]`：该目录名含连字符、不是合法包名，
  必须排除，否则主包打包时会收录成非法包名。

### 工程化
- **`src/videomaker/` 与 `reports/`、`styles/` 纳入版本控制**：videomaker 源码（v0.1.0 → v0.3.0
  全部交付）此前只存在于工作区、从未入库；本次连同 `tests/test_videomaker.py`（30 例）与
  `tests/test_videomaker_v03.py`（26 例）、4 份交付报告一并入库。
- **清理 `src/videomaker/` 16 处 lint 问题**：未使用导入（F401 ×13）、空 f-string（F541）、
  歧义变量名 `l`（E741）、死变量 `ring_alpha`（F841）。主包 `packages.find` 会收录
  videomaker，而 CI 的 `ruff check src/` 此前从未扫过它——推送到 main 会直接红灯，故一并修正。

### 修复
- **CI 适配真实引擎依赖（FluidSynth / SoundFont / ffmpeg）**：CI 此前长期红灯
  （`gh run list` 显示最近 4 次运行全部 failure，从未绿过）。根因是 `ubuntu-latest`
  拿不到 Windows 版 `fluidsynth.exe`——捆绑二进制在类 Unix 上「存在但不可执行」，
  渲染环境探测据此判 BROKEN（历史遗留 4 例失败 + 覆盖率 86.30% 不达标）。
  - 新增 `platform_paths.py`：**平台感知回落**。Windows 上恒不触发
    （`IS_WINDOWS` 为真时 `system_fluidsynth()` 返回 None），既有行为逐字不变。
  - `env.PathResolver` 与 `render.FluidSynthRenderer` 两处 fluidsynth 解析，在
    「文件存在但不可执行」时回落到系统 fluidsynth；无回落可用则维持原有分级报错
    （module 路径 → ModuleError(7)，非 module → RenderError(4)），不静默放过坏环境。
  - `ci.yml` 增加 `apt-get install fluidsynth ffmpeg`，并新增「渲染环境自检」步骤
    （校验 fluidsynth/ffmpeg 可用 + SoundFont 存在），让环境问题早暴露。
    SoundFont 与 Windows 二进制本就随版本控制入库（293M），CI 无需额外下载。
- **SF2 可加载性校验不再依赖音频设备**：fluidsynth 加载 SoundFont 时会一并初始化
  音频输出，CI 容器没有声卡，导致合法音色库被误判为 BROKEN（进而抛 ModuleError(7)，
  表现为 `test_inspire_diff::test_new_non_tty` 返回 7）。类 Unix 平台改为显式使用
  `dummy` 哑驱动；Windows 发行版**不含 dummy**（实测可用驱动仅
  dsound/file/wasapi/waveout），故不加参数、行为不变。
  CI 自检步骤同时打印音频驱动列表与 SF2 加载退出码，便于定位此类环境问题。
- **跨平台测试修正**：占位二进制（`b"MZ"`）统一补 `chmod(0o755)`。POSIX 的
  `os.access(X_OK)` 要求真实执行位（Windows 上等价于存在性检查），此前
  `test_env.py` 3 例在 CI 上因此把「存在的假二进制」误判为 BROKEN。

### 测试
- 新增 13 例：`platform_paths` 回落判定（Windows/POSIX/未安装）、env 与 render 两层
  的回落与分级报错分支（ModuleError(7) / RenderError(4)）、PATH 查找路径。
- 本地覆盖率 86.71% → **87.22%**（达标）；`render/fluidsynth.py` 80% → 95%。

### 文档
- `README.md` 新增「Suno-Cat-Catch-Resolve 子项目」一节（含两类产物对照表与命名约定）。
- videomaker 交付报告归档至 `reports/`（v0.1 → v0.3.0 共 4 份）。
- `reports/ci-remediation-plan.md`：CI 修复路线与决策记录。

## [0.5.4] - 2026-09-20（旋律生成增强：动机驱动乐句 + 伴奏织体 + 读回拍速修复）

> 说明：本条目描述的是**实际交付到 main 的实现**。此前 `[0.5.4]` 段落曾以
> 「2 小节乐句 / 休止符呼吸 / 句尾长音」描述一版从未入库的中间稿，
> 与最终代码不符，此处按实际实现重写。

### 增强
- **`procedural._melody_track` 重写为动机驱动**：从「每拍均匀四分音符随机游走」升级为
  可记忆的乐句结构——
  - 4 小节一乐句，乐句内复用同一节奏动机（`MOTIFS`：蹦跳 / 附点 / 流动八分 / 平稳），
    乐句之间轮换，形成律动钩子；
  - 强拍（每小节第 1、3 拍）由两遍规划法落在当前和弦音上，和声清晰、有明确调性；
  - 弱拍用 `_step_toward` 级进（相邻音程 ≤2 半音）趋向下一个强拍目标，杜绝跨八度狂跳；
  - 乐句轮廓在 拱形 / 波浪 / 上行 / 下行 之间轮换，旋律有起伏而非无序游走。
- **真正读取 `melody_profile`**：`register`（解析 `C4-C6` 之类音名区间）控制旋律音域，
  `variation_strength` 控制动机活动度（此前两者均未生效）。
- **`_chords_track` 织体增强**：
  - 新增 `block` 密度模式（`_chords_track_block`）：整小节所有和弦音同时按下；
  - `sustain` 模式改为奇数小节块状和弦 + 偶数小节慢速琶音分解，伴奏不再单调。

### 修复
- **`models/midi.py` 读回拍速错误**：改用 `pretty_midi.get_tempo_changes()` 读取 MIDI 真实
  拍速事件，替代按音符密度猜测的 `estimate_tempo()`——后者会把 120 BPM 的文件猜成 180，
  导致读回后的 beat 时间轴整体缩放。

### 新增
- 自定义风格 `styles/piano-cheerful.toml`（欢快钢琴 solo：C4-C6 明亮音域、variation 0.7），
  与 `styles/starsea.toml`（现代抒情 ballads）、`styles/piano-ballad.toml`（钢琴+弦乐叙事）。
- 内置 `STYLE_PRESETS` 新增 `piano-cheerful`（钢琴主奏 + 块状和弦伴奏）。
- 新增 `_parse_pitch_name_to_midi` / `_step_toward` 工具（音名区间解析 / 级进取音）。

### 测试
- 版本号 `0.5.3` → `0.5.4`（`__init__.py` / `pyproject.toml` / `test_cli.py::test_version` 同步）。
- 全量 388 例测试通过，旋律变更向后兼容（无 `melody_profile` 时退化为级进旋律）。

## [0.5.3] - 2026-08-14（DiffRhythm 仓库路径可命令行配置 + 测试）

### 增强
- **`ai diffrhythm` 新增 `--diffrhythm-dir` 选项**：命令行级指定 DiffRhythm 仓库根目录，优先级高于 `DIFFRHYTHM_DIR` 环境变量与默认 `module/diffrhythm`，无需将仓库放在 `module/` 下（接入适配器既有 `model_dir` 参数）。

### 测试
- `tests/test_ai_diffrhythm.py` 新增 `repo_dir` 优先级参数化单测（`model_dir` > `DIFFRHYTHM_DIR` > 默认 `module/diffrhythm`）。

## [0.5.2] - 2026-08-14（代码重构 + 覆盖率提升 + CI 增强）

### 重构
- **拆分 cli.py**（1410 → 1100 行）：辅助函数抽离到 `commands/helpers.py`（15 个辅助函数）
- 保持向后兼容：`from smartnotegen.cli import app` 仍有效

### 测试增强
- 新增 29 例测试（rhythm_patterns 10 + counterpoint 4 + notes 9 + fluidsynth 3 + export 3）
- 全量 329 测试全绿，覆盖率 **87.41%**（门槛 85% → 87%）
- `.gitignore` 增加 `.coverage` / `coverage.xml`

## [0.5.1] - 2026-08-12（工程化深化）

### 工程化
- **GitHub Actions CI**：push 自动 lint + test + coverage 门禁
- **pyright 类型检查**配置（basic 模式）
- 新增 11 例测试，覆盖率门槛 80% → 85%
- README 补齐 P3 命令

## [0.5.0] - 2026-08-12（P3 三期：Suno 衔接）

### 新增（P3-B2 / P3-B3 / P3-B1）
- **`export suno-pack`**：批量导出 Suno 片段打包（目录 + zip + manifest.json）
- **`export suno-manifest`**：生成 CSV/JSON 上传清单（utf-8-sig，Excel 兼容）
- **Suno API 调研**：官方 API 已开放，推荐方案 B（独立脚本），见 `docs/ai-integration.md` §6

## [0.4.1] - 2026-08-12（打磨完善）

### 修复
- **new 向导参数 bug**：GenerationRequest 使用 merged 配置的 seed，用户输入的 BPM/和弦/小节正确生效
- **灵感库 chords 提取**：_load_metadata 优先取 midi 产物完整参数，chords/bpm/bars 正确入库
- **config init Windows 路径**：TOML 路径反斜杠转义，避免解析失败
- **版本号规范化**：0.1.0 → 0.4.1（与 CHANGELOG 对齐）

### 增强
- **config init 交互式向导**：自动检测 module/ 路径，交互式引导配置；`--yes` 非交互模式
- **doctor 增加配置检查**：检查 config/default.toml + smartnotegen.toml 存在性

### 测试
- 全量 279 测试全绿（新增 8 例）
- 补充 inspire（features 边界/chords/组合筛选/导出）+ preview（base64/自动标签/频谱）测试

## [0.4.0] - 2026-08-12（P3 二期：创作工作台）

### 新增（P3-C1 / P3-C3 / P3-C2）
- **灵感库（SQLite）**：`inspire init/add/list/show/rm/export`，自动从 metadata.json 提取元数据，支持标签 + 评分 + 多维筛选
- **版本对比**：`diff <wav1> <wav2>` 对比时长/RMS/峰值/频谱中心/频段能量 + 参数
- **参数引导**：`new` 交互式向导，非 TTY 自动执行 pipeline

## [0.3.0] - 2026-08-11（P3 一期：创作体验闭环）

### 新增（P3-A1 / P3-A2 / P3-A3 / P3-E3 / P3-E2）
- **HTML 预览页**：pipeline/render/export 后自动产出 preview.html（波形 + 频谱 + 播放器，base64 内嵌，离线可用）
- **play 子命令**：系统默认播放器播放 WAV
- **音频特征摘要**：RMS/峰值/频谱中心/频段能量写入 metadata.json
- **doctor 子命令**：一键环境诊断（Python/fluidsynth/SF2/CUDA/AI 依赖/espeak）
- **config 预览节**：[preview] 配置 + --no-preview

## [0.2.0] - 2025-08-09（P1 二期 AI 冲刺）

### 新增（T-S1 / T-P1-1 / T-P1-2）

- **T-S1 DiffRhythm spike（8GB 显存）**：完成 CUDA torch（2.5.1+cu121）+ espeak-ng 1.52.0 安装与验证、权重经 hf-mirror 下载（约 7.5GB）、`chunked=True` 补丁落地与实测推理；报告归档于 `docs/ai-integration.md` §4（峰值显存 / 95s 耗时 / 音质 / GO-NO-GO）。
- **T-P1-1 MusicGen 适配器完整实现**：`ai musicgen` 支持旋律 WAV 条件扩编曲（`generate_with_chroma`）、默认 medium fp16 / `--model-size small` 降档、显存检查防 OOM（不足提示降档建议）、`--seed` 可复现（实测字节级一致）、输出 32kHz WAV 可被 `export suno` 消费；延迟导入 audiocraft，未装依赖退出码 6 并给出安装指引。**实测修正**：audiocraft 仅 `facebook/musicgen-melody`（1.5B）支持旋律条件，因此 `--model-size medium` 映射到 musicgen-melody；`small`（300M）不支持 chroma，自动降级为纯文本生成。性能基线：20s 输出峰值显存 5530 MiB、chroma 相关 0.706。
- **T-P1-2 DiffRhythm 适配器完整实现**：`ai diffrhythm` 支持风格提示 + `--lyrics` 歌词生成 ≥60s 带人声歌曲草稿（`chunked=True` 默认，自动注入补丁）；`--duration` 支持 95 或 96-285s；`--device cuda|cpu`；显存 <8GB 明确提示（退出码 6）；**草稿不自动进 Suno 导出链**（含人声，仅本地听感预览），元数据标注 `contains_vocals=true`。
- **AI 环境落地**：`requirements/ai.txt` 更新（DiffRhythm 官方不可 pip 安装 → 改为仓库克隆说明 + 运行依赖清单）；espeak-ng Windows 说明（含 `PHONEMIZER_ESPEAK_LIBRARY` DLL 定位）；hf-mirror 权重下载指引。
- **测试**：新增 `tests/test_ai_musicgen.py`（15 例）+ `tests/test_ai_diffrhythm.py`（17 例）+ `tests/test_cli.py` AI 元数据用例（2 例），全部 mock 大模型（不真跑、不依赖 GPU/权重，无 GPU 环境可跑）；既有 207 测试全绿，全量 **241 用例**，覆盖率 **91%**。
- **文档**：`docs/ai-integration.md` spike 报告 + MusicGen 性能基线；`docs/usage.md` ai 子命令参数（`--model-size/--lyrics/--duration/--device`）；README AI 安装指引（含 DiffRhythm 仓库克隆 / espeak-ng / hf-mirror）。

### 说明

- 既有 3 个 P0 环境假设测试（`test_ai_musicgen_exit_6` / `test_ai_diffrhythm_exit_6` / `test_ai_adapters_unavailable_in_p0`）改为 monkeypatch find_spec，保证在"已安装 AI 依赖"的环境（如本机二期环境）与"未安装"环境均稳定通过。
- 覆盖率配置：`pyproject.toml` 不再 omit `src/smartnotegen/ai/*`（AI 模块测试计入覆盖率；AI 适配器顶部零 torch import，推理路径由 mock 测试覆盖）。

## [0.1.0] - 2025-08-09（P1 一期非 AI 冲刺增量）

### 新增（P0 里程碑）

- **CLI 入口**：`smartnotegen` 子命令体系（generate midi / generate melody / render / export suno / pipeline / batch / config / ai），错误码 0–6 映射。
- **程序化 MIDI 生成**：`generate midi` 产出 ≥3 轨（和弦/旋律/贝斯），`--with-drums` 追加第 4 轨鼓；`--seed` 可复现（同 seed 字节级一致）。
- **乐理旋律生成**：`generate melody` 基于 music21 调式/和弦约束生成旋律，支持节奏/装饰音/逆行 3 种变奏；强拍/句尾和弦音对齐率 ≥80%。
- **MIDI→WAV 渲染**：`render` 通过 FluidSynth 渲染 44.1kHz/16bit WAV；fluidsynth 缺失时退出码 4 并给出安装指引。
- **Suno 合规导出**：`export suno` 输出 10–30s 纯器乐 WAV/MP3（裁剪/循环、淡入淡出、重采样、-1dBFS 归一化）；时长越界退出码 5。
- **一键管线**：`pipeline` 零参数闭环 generate→render→export，中间产物自动清理。
- **配置体系**：`config init` / `config show`；四级合并优先级（内置 < default.toml < 用户配置 < CLI）。
- **P1 AI 骨架**：`ai/musicgen.py`、`ai/diffrhythm.py` 延迟导入适配器，P0 环境明确提示安装依赖（退出码 6），不触发任何 torch import。
- **测试**：覆盖 config/chords/generators/midi/render/export/cli 的 pytest 用例（渲染用例使用 mock，不依赖真实 fluidsynth）。

### 一期非 AI 冲刺增量（M-1 / P1-3 / P2-1 / P2-2 / P2-4 / P2-5 / P2-3）

- **M-1 module 环境接入**：`render`/`pipeline` 默认使用 `module/` 下真实 fluidsynth + GeneralUser-GS/ColomboGMGS2 双音色库（主库缺失自动回退备选）；路径三分级探测 OK/MISSING/BROKEN；缺失时明确报错并给出修复指引（退出码 7）；仅 `--dry-run` 允许 mock；`--soundfont`/`--fluidsynth` 可覆盖。
- **P1-3 批量生成完整实现**：`batch --count N [--seed S] [--chords-choices ...] [--style ...] [--variations] [--render] [--export] [--parallel]`；四维度随机化（和弦/节奏/风格/旋律变奏）；seed 派生 `seed*1000+i` 可复现；失败项隔离 + 单次重试；退出码 0/8/9；批次清单写入 metadata.json。
- **P2-5 输出管理**：默认 `<root>/<project>/<YYYYMMDD>/{style}_{bpm}_{seed}_{seq}.{ext}` 命名（跨运行防覆盖）；每次运行产出 metadata.json（参数/seed/耗时/版本/路径）；`[output] layout` 双档（project-date/legacy）保兼容。
- **P2-1 DSP 调优**：render 后、export 前独立 DSP 阶段：峰值归一化 -1dBFS、淡入 100ms/淡出 300ms（0–5000ms 校验）、可选 EQ/压缩（默认关）、Suno 导出链恒禁混响；非法参数显式报错。
- **P2-2 乐理规则**：`music_theory/` 包（平行五度/八度检测、声部交叉、二声部对位、和弦转位、节奏型库 ≥6 内置 + 自定义 JSON/字符串）；全部默认关闭，不破坏 P0 输出。
- **P2-4 预设风格库**：`styles/` 包 + 流行/摇滚/电子/古典 4 基线 TOML（BPM/乐器/节奏型/旋律特性/和弦偏好/DSP 默认）；自定义 TOML/JSON 注册；与 `--style`/batch 联动。
- **P2-3 工程化**：日志分级（`--verbose`/`--quiet`/`--debug`）；`smartnotegen errors` 错误码表（新增 7/8/9）；依赖锁定（requirements/*.txt == 版本）；`scripts/install.bat` 一键安装；`scripts/build_package.ps1` PyInstaller 打包（含 module/ 资源说明）。
- **测试**：新增 env/output_manager/dsp/music_theory/styles/batch/error_codes/logging/render_m1/postprocess 测试；全量 197 用例全绿，覆盖率 ≥88%。

### 说明

- 本机已配置 `module/fluidsynth` 与双 SoundFont，`render` / `pipeline` 开箱即用；删除 `module/` 时报错误码 7 而非静默 mock。
- 版本号保持 0.1.0（`--version` 断言兼容，P2-3 版本规范化延后至测试断言许可后执行）。
