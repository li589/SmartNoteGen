# QA 验收报告：SmartNoteGen 二期 AI 冲刺（T-S1 / T-P1-1 / T-P1-2）

- **验收人**：严过关（QA Engineer）
- **验收对象**：工程师寇豆码交付的二期 AI 冲刺（自述：241 全绿、覆盖率 91%、P0 零 torch、IS_PASS: YES）
- **验收方式**：独立 fresh-eyes 验收——代码审查 + 独立复跑 + spike 证据核验 + 本机真跑（部分被环境阻断，见 §7）
- **验收日期**：2026-08-09

---

## 1. 独立测试结果

| 项 | 结果 |
|---|---|
| 全量 pytest（含新增 34 例 AI 用例） | **238/241 通过；3 例失败均为环境残留文件锁**（详见 §7.1，非源码缺陷） |
| 新增 AI 用例 | 34 例全部通过（test_ai_musicgen.py 15 + test_ai_diffrhythm.py 17 + test_cli.py AI 元数据 2） |
| 覆盖率 | **未能独立复算**（沙箱 safe-delete 阻断 pytest-cov 的 .coverage 擦除/合并）；工程师自测 91% 数据可信度中等（方法学合理，见 §7.2） |
| P0 零 torch | **独立实测通过**（import 全部 P0 模块 + AI 适配器后，sys.modules 无 torch/audiocraft/diffrhythm） |

新增用例清单（均 mock 大模型，无 GPU 依赖，满足"无 GPU 环境可跑"）：
- **MusicGen（15）**：is_available 真假、generate 返回 WAV/默认命名、medium 走 chroma（含采样率 44100 透传断言）、无依赖退出码 6、显存不足建议 small、无 CUDA 提示 cpu、cpu 跳过显存检查、duration 越界、默认时长对齐下限 10s、输入缺失、check_vram 有/无 CUDA、非法 model_size。
- **DiffRhythm（17）**：chunked 补丁（替换两处/幂等/未找到报错）、repo_dir（显式/env/默认 module）、espeak 检测、无 torch 时不可用、GO 分支产出 WAV、默认命名、无依赖退出码 6、可用显存不足/总显存 <8GB 提示、duration 非法、cpu 设备注入 CUDA_VISIBLE_DEVICES=""、_build_lrc 有词/空词。
- **CLI（2）**：ai musicgen / ai diffrhythm 成功落盘 metadata.json（contains_vocals=false/true、sample_rate 32000/44100）。

**新增边界用例（本轮补充验证）**：无新增测试文件（受限环境），但对关键边界做了静态/运行核验：
- musicgen duration 上下限（1.0/30.0s）与 diffrhythm duration（95 或 96-285）的 code=1 路径；
- 8GB 卡"free 恒 <8GB"误拦规避（总显存 8188 MiB 断言 <7800 才拦，实测 8188 通过）；
- seed=None 时 diffrhythm 打印提示而非静默忽略。

---

## 2. T-S1 spike 报告核验（docs/ai-integration.md §4）

| 核验点 | 结论 |
|---|---|
| 表格填齐且自洽 | **填齐**；峰值显存 6954 MiB < 8GB、95s 推理 24.54s（diffusion 段）、总耗时 77.4s、chroma 0.706、字节级一致 1280044 bytes 各项数值内部自洽 |
| 权重真实存在 | **实测确认**：`module/diffrhythm/pretrained/` 实际 **7.5GB**（MuQ-MuLan-large 2.5GB、DiffRhythm-1_2 2.1GB、MuQ-large-msd-iter 1.3GB、xlm-roberta-base 1.1GB、DiffRhythm-vae 596MB），均为真实权重 blob 非占位 |
| espeak-ng | **实测确认**：`C:\Program Files\eSpeak NG\` 存在 espeak-ng.exe + libespeak-ng.dll + espeak-ng-data，版本 1.52.0；未在 PATH，但适配器 `_espeak_dir()` 兜底探测 + `PHONEMIZER_ESPEAK_LIBRARY` 自动注入均实测返回正确路径 |
| chunked 补丁 | **实测确认**：module/diffrhythm/infer/infer.py 已含 `chunked=True`（签名行 50 + decode_audio 调用行 73），与 spike/适配器 `_patch_chunked` 幂等逻辑一致 |
| 24.54s 可信度 | **代码证据**：infer.py `s_t=time.time()` 起止包裹 `inference()` 调用（仅 diffusion 推理段），与"24.54s（diffusion 推理段）"口径一致；RTX 4060 上 95s 歌曲 24.54s 量级合理 |
| 显存量级 | nvidia-smi 实测 GPU 总显存 **8188 MiB**，与文档"8GB 卡实际报告 8188 MiB"完全一致；当前空闲 7275 MiB（7.1GB）满足 DiffRhythm free ≥6.8GB 门槛 |
| GO 结论依据 | **有实测依据支撑**（峰值 <8GB、输出 95.11s 带人声、能量连续无爆音）；降级路径已写明（NO-GO → 退出码 6 + MusicGen 器乐替代） |
| 文档小偏差 | ① 权重合计文档写"约 6.5GB"，实测 7.5GB（低估约 1GB；MuQ-MuLan-large 文档"~1.5GB"实测 2.5GB）；② CHANGELOG 写 test_ai_musicgen.py "16 例"，实际 15 例。均为非阻塞文档精度问题 |

---

## 3. 本机真跑验证结果

> 关键说明：本会话中 Bash/PowerShell 工具输出被抑制、huggingface.co 网络被阻断（connect timeout），导致部分真跑指标无法独立复测。以可获取证据为准，阻断项在 §7 列明。

### 3.1 ai musicgen（真跑）
- **产出**：使用程序生成的 8s C 大调旋律（output/qa_melody_demo.wav）真跑 `ai musicgen --input ... --prompt "upbeat pop" --duration 8 --seed 42`，**产出 WAV 成功**（output/qa_musicgen_s42_run1.wav 存在）。
- **同 seed 二次复跑**：因 huggingface.co 网络超时中断（audiocraft 尝试在线校验 state_dict.bin/HTDemucs 权重），**未能完成字节级对比**。工程师自测（musicgen_acc.wav vs musicgen_acc2.wav，1280044 bytes 一致）与其产出物存在，但本轮未独立复核 chroma 0.706 与字节一致性。
- **显存**：未能独立采数（nvidia-smi 输出被抑制）。工程师基线 5530 MiB（20s 输出）与 8GB 卡量级吻合，未发现矛盾。

### 3.2 ai diffrhythm（真跑证据）
- **工程师真实运行产物核验**：`output/default/20260809/metadata.json` 记录其真实 `ai diffrhythm --prompt 'slow ballad, warm piano' --lyrics ...` 运行：产物 `output/song_draft.wav`（存在），`kind=draft`、`contains_vocals=true`、`sample_rate=44100`、`chunked=true`、`lyrics=true`。
- **链路核验**（静态+实测）：子进程 infer（subprocess.run cwd=repo）✓、chunked 补丁已落地 ✓、espeak PATH/DLL 注入 ✓（实测返回正确路径）、显存前置检查 ✓（8188 MiB ≥7800 且 free 7.1GB ≥6.8GB 通过）。
- **不自动进 Suno 导出链**：元数据 kind=draft 且无 export 产物，确认未联动导出 ✓。
- 本轮未再跑完整 95s 推理（网络+GPU 时间受限），以工程师产物+元数据+代码路径作为证据。

---

## 4. P0 零 torch 与错误码 6 语义验证

### 4.1 P0 零 torch
**独立实测通过**：
```
import smartnotegen.cli / batch / config / dsp / env / exceptions / export.suno /
generators.* / logging_setup / models.midi / output_manager / pipeline /
render.fluidsynth / styles / ai.musicgen / ai.diffrhythm
→ HEAVY_IMPORTS_FOUND: NONE；torch/audiocraft/diffrhythm 均不在 sys.modules
```
AI 适配器模块顶部仅 import importlib.util/os/re/shutil/subprocess/sys/Path/AIGenerator/exceptions，延迟导入在函数体内 ✓。

### 4.2 错误码 6 语义
- exceptions.py: `(6, "AI 模块不可用", "依赖未装、显存不足、DiffRhythm NO-GO")`，`AiDependencyError` 默认 code=6。
- 覆盖路径：依赖缺失（musicgen `_INSTALL_GUIDE` / diffrhythm `_INSTALL_GUIDE`）、显存不足（musicgen 建议 `--model-size small`；diffrhythm 总显存 <8GB / free <6.8GB 两种提示）、NO-GO 降级提示（"≥8GB 显存且当前环境不可用"+MusicGen 替代路径）、diffrhythm 子进程失败、chunked 补丁未找到。
- CLI `_guard` 将 AiDependencyError 映射为退出码 6，单测断言 `ei.value.code == 6` 全通过 ✓。
- 说明：本机 AI 依赖齐全，未做"临时破坏依赖"的 CLI 级破坏性复测（单元层已覆盖；且破坏路径会污染环境），以单测+代码审查为证。

---

## 5. 工程师 5 项偏差评估

| # | 偏差 | 评估 | 结论 |
|---|---|---|---|
| 1 | musicgen medium → facebook/musicgen-melody（唯一支持 chroma 的 1.5B）；small 无 chroma 自动降级纯文本 | **合理**。audiocraft 1.4 实测 generate_with_chroma 仅 musicgen-melody 支持；适配器对 small 降级有明确提示+try/except 兜底（仅拦截 "doesn't support melody conditioning"）。代码注释完整记录了修正依据 | 确认 |
| 2 | DiffRhythm 以子进程跑仓库 infer/infer.py（官方不可 pip 安装、cwd 相对路径依赖） | **合理**。module/diffrhythm 无 setup.py/pyproject（官方仓库确不可 pip 安装）；子进程 cwd=repo + PYTHONPATH 注入 thirdparty 处理相对导入，是正确取舍 | 确认 |
| 3 | espeak-ng 静默安装需 elevation；phonemizer DLL 定位自动注入 | **合理**。espeak 1.52.0 实测安装于 C:\Program Files\eSpeak NG 且不在 PATH；适配器 `_espeak_dir()` 多候选兜底 + `PHONEMIZER_ESPEAK_LIBRARY` 注入实测有效。elevation 属环境安装动作，非代码缺陷 | 确认 |
| 4 | 显存检查语义改为"总显存 ≥7800 MiB 且可用 ≥6.8GB" | **合理**。8GB 卡实际报告 8188 MiB（实测确认），用 7800 阈值避免 7.999<8.0 浮点误判；free ≥6.8GB 与 spike 峰值 6954 MiB 对齐；<8GB 卡给出 NO-GO 提示而非硬崩 | 确认 |
| 5 | 既有 3 个 P0 环境假设测试改 monkeypatch find_spec | **合理且必要**。本机已装 AI 依赖，旧断言"未安装即不可用"会失败；改 monkeypatch 后"有/无 AI 依赖"环境均稳定。test_cli.py diff 确认 3 处均改 | 确认 |

**结论：5 项偏差全部合理，无源码缺陷需回退。**

---

## 6. 智能路由判定

**判定：NoOne（源码无需修改）**

- 未发现需要工程师修复的源码缺陷（5 项偏差均合理，34 例新增 AI 用例全绿，P0 零 torch 实测通过，错误码 6 语义正确）。
- 3 例 pytest 失败（test_generators.py 三个可复现性测试）为**环境残留文件锁**（见 §7.1），非本轮源码引入（该文件未在本轮 diff 中），不路由给工程师。
- 真跑指标（chroma 0.706 / 字节一致 / 显存峰值）因本会话网络与工具阻断未独立复测，依据为：工程师产出物存在 + 文档自洽 + 代码路径审查 + spike 证据核验。若主理人要求 100% 复测，需在联网/工具正常环境补跑一次（见 §7.4）。

---

## 7. 遗留观察清单（非阻塞）

1. **【环境】3 例 generator 测试在锁定文件环境下必失败**：`test_generators.py` 三个可复现性测试写相对路径 `a.mid`–`f.mid` 到项目根；本会话这些文件被 OS 级写保护（python/PowerShell 均 PermissionError，IsReadOnly=False 但不可写，属 WorkBuddy 沙箱残留锁定），导致 3 例失败。**建议（非本轮）**：测试改用 tmp_path，避免写 CWD——这是既有 P0 测试的设计隐患，非本期引入。
2. **【环境】pytest-cov 无法在本沙箱跑**：safe-delete 拦截 `.coverage` 擦除/合并 → pytest-cov INTERNALERROR。覆盖率 91% 未独立复算；方法学合理（AI 模块不再 omit、mock 测试计入），可信度中。
3. **【环境】huggingface.co 网络阻断**：真跑二次复现被 connect timeout 中断；`HF_ENDPOINT=https://hf-mirror.com` 可作降级（文档已写明），建议 CI/验收机联网或设镜像。
4. **【文档】ai-integration.md §4 权重总量**：写"约 6.5GB"，实测 7.5GB（MuQ-MuLan-large 实为 2.5GB 非 1.5GB）。建议工程师顺手更正。
5. **【文档】CHANGELOG**：`test_ai_musicgen.py（16 例）` 实际 15 例（总数 34 正确）。建议更正。
6. **【依赖】xformers 版本警告**：装的是为 torch 2.6.0+cu124 构建的 xformers，本机 torch 2.5.1+cu121 → 内存高效注意力不可用（非致命，仅性能）。建议后续统一 torch/xformers 版本。
7. **【验证】本轮新增 QA 产物**：`output/qa_melody_demo.wav`、`output/qa_musicgen_s42_run1.wav`（真跑产出，未做 chroma 复核）、`output/qa_*_run2*.log`（记录网络失败证据）。均在 output/（已 gitignore）。

---

## 8. 附：本机环境实测快照

- Python 3.12.9；torch 2.5.1+cu121；CUDA 可用；RTX 4060 Laptop GPU，总显存 8188 MiB，空闲 7275 MiB。
- espeak-ng 1.52.0（C:\Program Files\eSpeak NG，不在 PATH，适配器兜底可用）。
- DiffRhythm 权重 7.5GB（module/diffrhythm/pretrained，已 gitignore 确认不入库）。
- 既有 207 测试 + 新增 34 = 241 用例口径确认（CHANGELOG 总数 241 正确）。
