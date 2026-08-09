# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 风格。

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
