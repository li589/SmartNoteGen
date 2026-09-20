# CI 修复与下一步路线图

> 生成：2026-09-20 ｜ 触发：整理并推送 5 个提交后，CI 仍红灯
> 状态：**已完成 —— CI 首次全绿**（run 35502250795）

---

## 一、现状：CI 失败分解（run 35498949334）

`gh run list --limit 10` 显示最近 **4 次运行全部 failure** —— CI 从未绿过，非本次引入。

| 步骤 | 结果 | 说明 |
|---|---|---|
| Set up / Install / **Lint with ruff** | ✅ | 本期修复 videomaker 16 处 lint 后通过 |
| Test with pytest | ❌ | 8 failed / 379 passed / 1 skipped，覆盖率 86.30% |
| Check P0 zero torch import | ⏭ | 因上一步失败被跳过 |

失败用例分三类：

| 类别 | 例数 | 具体用例 | 根因 | 归属 |
|---|---|---|---|---|
| ffmpeg 未找到 | 4 | `test_videomaker.py`×3、`test_videomaker_v03.py`×1 | ubuntu runner 未装 ffmpeg | **本次引入**（测试刚入库才被收集） |
| fluidsynth 不可执行 | 4 | `test_env.py`×3、`test_inspire_diff.py`×1 | CI 上 `module/fluidsynth` 是 Windows `.exe`，Linux 无执行语义 | 历史遗留 |
| 覆盖率不足 | — | — | 86.30% < 门槛 87% | 历史遗留 |

**根因结论**：CI 从未适配项目的**真实引擎依赖**（FluidSynth + SoundFont + ffmpeg）。
本项目「真实渲染优先」（`render`/`pipeline` 默认走真实 fluidsynth），而 `ubuntu-latest`
拿不到 Windows 版 `fluidsynth.exe`；部分测试还硬编码了 Windows 语义（断言 `.exe` 可执行）。

> 红线：**不要为过 CI 而改业务源码**，尤其不要把真实引擎降级成 mock 来凑绿。

---

## 二、三条路线

### 路线 A：让 CI 具备真实依赖（还原度最高）
- CI 增加 `apt-get install -y fluidsynth ffmpeg`，并让 `module/` 探测支持 Linux
  系统路径（`/usr/bin/fluidsynth` + `/usr/share/sounds/sf2/*.sf2`）。
- 代价：改动 `env.py` / `render/fluidsynth.py` 的探测逻辑（有回归风险）；
  SoundFont 需在 CI 侧获取（体积/许可）。
- 收益：CI 真正覆盖渲染链路，红灯语义可信。

### 路线 B：分层标记，CI 只跑核心单测（推荐）
- 给依赖外部引擎的用例加 `@pytest.mark.integration`，CI 跑 `-m "not integration"`。
- 覆盖率门槛按期下调，或对 `integration` 用例单独统计、不计入门槛。
- 代价：CI 不再覆盖真实渲染，需靠本地/手动回归补位。
- 收益：**改动最小、无源码风险**，CI 恢复「绿=可信」的信号价值。

### 路线 C：先只修本次引入的部分
- CI 装 ffmpeg（或给 videomaker 测试加 `skipif` 无 ffmpeg 时跳过）。
- 代价：CI 仍因 fluidsynth + 覆盖率红灯，等于没解决根问题。

**建议：B 打底 + A 逐步补**。先用 B 让 CI 变绿并恢复信号价值，再按需把真实引擎
接入 CI（A），避免长时间红着导致「红灯免疫」。

---

## 三、随附发现项（独立于 CI，待裁定）

| # | 发现 | 位置 | 建议 |
|---|---|---|---|
| 1 | `_interval()` 死代码（定义后零引用） | `src/smartnotegen/generators/procedural.py:483` | 删除，或补用途 |
| 2 | videomaker 版本历史未进主 CHANGELOG | `CHANGELOG.md` vs `reports/` | 补 v0.1→v0.3.0 条目 |
| 3 | venv 内 videomaker 元数据滞后为 0.1.0 | `venv/` | 重装 `pip install -e src/videomaker` |
| 4 | Suno 子包无测试、CI 未安装 | `src/Suno-Cat-Catch-Resolve/` | 补冒烟测试或明确豁免 |
| 5 | `test_generators.py` 三个可复现性测试写 CWD 非 `tmp_path` | `tests/` | 改为 `tmp_path`（历史遗留） |
| 6 | CI 的 node20 弃用告警 | `.github/workflows/ci.yml` | 升 `actions/checkout@v5` / `setup-python@v6` |

---

## 四、建议执行顺序

1. **决策路线**（A / B / C）—— 本文档核心待决项。
2. 按路线改造 CI，推送后确认 `gh run watch` 转绿。
3. 清理发现项 1–3（低风险、可独立提交）。
4. 视精力处理 4–6。

---

## 附：本次已完成（供对照）

- 5 个提交推送至 `origin/main`（`3f76bea..488b2f1`）
- videomaker 源码 + 56 例测试 + 4 份交付报告 + `styles/` 全部入库
- 清理 `src/videomaker` 16 处 lint → **CI lint 步骤由必红转为通过**
- 版本号三处对齐 0.5.4；CHANGELOG `[0.5.4]` 段按实际实现重写
- 验证：`ruff check src/ tests/` 全通过；`pytest` 388 例全通过

---

## 执行结果（路线 A）

### 调研结论（修正了原先对 A 成本的估计）
- **SoundFont 不需要在 CI 侧获取**：`module/GeneralUser_GS/**`（主库 GeneralUser-GS.sf2
  + 备选 ColomboGMGS2.sf2，共 293M）**随版本控制入库**，CI checkout 即有。
- **Windows 版 fluidsynth 同样已入库**：`module/fluidsynth/bin/fluidsynth.exe` + DLL。
  它在 Linux 上「存在但不可执行」——这正是 4 例历史失败的根因。
- 因此 A 的代价远低于预估：**不需要**在 CI 下载音色库或处理许可问题，
  只需（1）apt 装 Linux fluidsynth + ffmpeg，（2）让探测逻辑支持回落。

### 实施
| 改动 | 内容 |
|---|---|
| 新增 `src/smartnotegen/platform_paths.py` | `system_fluidsynth()`：POSIX 查 PATH；**Windows 恒返回 None**（永不回落，既有行为逐字不变） |
| `env.PathResolver` | `resolve_fluidsynth` / `_probe_fluidsynth` 在「文件存在但不可执行」时回落；无回落则维持 ModuleError(7) / RenderError(4) 分级报错 |
| `render.FluidSynthRenderer` | `_resolve_fluidsynth` 的绝对路径与相对路径两条分支同样回落 |
| `.github/workflows/ci.yml` | `apt-get install fluidsynth ffmpeg` + 新增「渲染环境自检」步骤 |
| 测试 | `test_env.py` / `test_render_m1.py` 占位二进制补 `chmod(0o755)`；新增 13 例覆盖回落与分级报错 |

### 与预期的差异
- **发现并修复了一处「改动引入的脆弱性」**：给解析加 `X_OK` 检查后，CI 上所有
  造假 fluidsynth 的测试会走回落分支。已给占位文件补执行位，使单测**自洽、不依赖
  CI 是否安装系统 fluidsynth**。
- **ffmpeg 4 例（本次引入的失败）**：由「测试刚入库才被 CI 收集」造成，
  随 `apt install ffmpeg` 解决；med 级未改测试。
- **覆盖率**：86.71%（本地，修复中）→ **87.22%**（达标）。新增回落代码若不计入测试
  会反向拉低覆盖率（曾跌到 86.71%），故补齐了新增分支的覆盖。

### 实际结果：三次迭代后 CI 全绿

| 提交 | 改动 | CI 结果 |
|---|---|---|
| `3fa27db` | fluidsynth POSIX 回落 + apt 装 fluidsynth/ffmpeg + 测试补 chmod | 8 failed → **1 failed**；覆盖率 86.30% → 86.94% |
| `053eb7a` | SF2 校验加 `-a dummy`（**方向错误，已撤回**） | 仍 1 failed；但自检诊断暴露真根因 |
| `20f4f73` | **LFS 拉取音色库** + SF2 校验改 `file` 驱动 | **全绿**；覆盖率 87.01% |

**真实根因（与最初推测完全不同）**：

1. **Git LFS 未拉取** —— `.gitattributes` 把 `module/**/*.sf2|exe|dll|ogg` 交给 Git LFS，
   而 `actions/checkout` 默认**不拉取 LFS 实体**。CI 上 `.sf2` 是文本指针文件，
   前 4 字节是 `vers`(`0x73726576`) 而非 `RIFF`(`0x46464952`)，fluidsynth 无法识别 →
   合法音色库被判 BROKEN → ModuleError(7) → `test_new_non_tty` 退出码 7。
   修复：`git lfs pull --include="module/GeneralUser_GS/**/*.sf2"`（实测仅 31M）。
2. **Ubuntu 版 fluidsynth 不编译 `dummy` 驱动** —— 实测可用驱动仅
   alsa/file/jack/oss/pipewire/pulseaudio/sdl2，故 `-a dummy` 只会让校验必然失败。
   改用 `file` 驱动（两平台都有，无需平台分支），并以临时目录为 cwd 隔离其产出的
   `fluidsynth.wav`，避免污染工作目录。

**经验教训**：

- 前两轮基于推测改代码，**第二轮方向完全错误**。第三轮改为「先在 CI 加自检步骤
  打印关键事实（文件魔数 / 退出码 / 驱动列表）」，一轮命中根因 —— **取证优于推测**。
- `test_inspire_diff::test_new_non_tty` 全程**未放宽断言**，最终由环境修复自然通过，
  没有用「放宽测试」掩盖真实问题。
- **未调整覆盖率门槛**（87%）：通过补齐新增分支的测试达到，本地 87.24% / CI 87.01%。
- 最终保留的有效修复：`platform_paths.system_fluidsynth()` 的 POSIX 平台回落
  （Windows 恒不触发）。
