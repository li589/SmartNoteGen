# P1 AI 集成说明

> 版本：v0.2.0（P1 二期 AI 冲刺更新）

P0/P1-非AI 环境仅提供 AI 适配器骨架（延迟导入 + 明确提示），**不安装、不 import** torch/audiocraft/diffrhythm。
二期（T-S1 / T-P1-1 / T-P1-2）在本机（RTX 4060 Laptop 8GB）完成 spike 与适配器完整实现。

---

## 1. 安装（P1）

```bash
# 1. CUDA 版 torch + torchaudio（RTX 4060 / CUDA 12.1；务必用 cu121 索引避免装回 CPU 版）
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
#    实测本机版本：torch==2.5.1+cu121 + torchaudio==2.5.1+cu121（cp312）

# 2. 其余 AI 依赖
pip install -r requirements/ai.txt

# 3. DiffRhythm 仓库（官方不可 pip 安装，需手动克隆到 module/diffrhythm 或设置 DIFFRHYTHM_DIR）
git clone https://github.com/ASLP-lab/DiffRhythm.git module/diffrhythm

# 4. Windows：DiffRhythm 人声合成需要 espeak-ng
#    下载官方 .msi 安装（实测 1.52.0 安装到 C:\Program Files\eSpeak NG\）并加入 PATH；
#    phonemizer 还需设置 PHONEMIZER_ESPEAK_LIBRARY=C:\Program Files\eSpeak NG\libespeak-ng.dll
#    （适配器已自动处理该环境变量）

# 5. 权重下载较慢时使用国内镜像
set HF_ENDPOINT=https://hf-mirror.com
```

## 2. MusicGen 适配器（T-P1-1 已实现）

- 模型：`facebook/musicgen-medium`（1.5B，fp16，8GB 显存可跑）；`--model-size small` 降档
- 用法：`smartnotegen ai musicgen --input melody.wav --prompt "upbeat pop" --output out.wav [--duration 20] [--model-size medium|small] [--seed N] [--device cuda|cpu]`
- 实现要点：`audiocraft.models.MusicGen.get_pretrained(...)`（延迟导入）；melody conditioning 用 `generate_with_chroma`；fp16；`--seed` 可复现（torch.manual_seed + cuda.manual_seed_all）；显存不足给出降档建议（退出码 6）
- 输出：32kHz WAV（`export suno` 可消费，导出链内部重采样到 44.1kHz）
- 性能基线：见 §4 表格

## 3. DiffRhythm 适配器（T-P1-2，前置 T-S1 spike）

- 用法：`smartnotegen ai diffrhythm --prompt "slow ballad" [--lyrics "歌词"] [--duration 95] [--device cuda|cpu]`
- 关键修改：适配器自动将 infer 脚本 `decode_audio(..., chunked=False)` 与 `inference(..., chunked=False)` 改为 `chunked=True`（8GB 显存必需，幂等补丁，用户无需改脚本）
- DiffRhythm 官方仓库**不可 pip 安装**（无 setup.py），适配器以子进程方式运行 `infer/infer.py`（仓库存在 cwd 相对路径依赖），通过 `DIFFRHYTHM_DIR` 环境变量或默认 `module/diffrhythm` 定位
- 权重经 hf-mirror.com 下载（实测本机下载到 `module/diffrhythm/pretrained/`，约 7.5GB）
- Windows 需 espeak-ng（实测 1.52.0）；`--lyrics` 传入时生成含对应人声草稿；不传为空词/哼唱
- 显存 <8GB 时明确提示不可用（退出码 6）
- **草稿（含人声）不自动进 Suno 导出链**（CLI 不提供联动），用途为"本地听感预览"

---

## 4. DiffRhythm 8GB 显存 spike 报告（T-S1）

> 状态：**已完成**（本机 RTX 4060 Laptop 8GB 实测）

### 执行步骤

1. 安装 CUDA 版 torch（替换官方 requirements.txt 默认 CPU 版）
   - 实测命令：`pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121`
   - 版本：torch==2.5.1+cu121 / torchaudio==2.5.1+cu121（Python 3.12）
2. Windows 安装 espeak-ng
   - 实测：下载 `espeak-ng.msi`（1.52.0，12.7MB），静默安装到 `C:\Program Files\eSpeak NG\`
   - 注意：phonemizer 通过 DLL 定位，需 `PHONEMIZER_ESPEAK_LIBRARY=C:\Program Files\eSpeak NG\libespeak-ng.dll`（适配器自动注入）
3. 权重经 hf-mirror.com 下载
   - 实测：设置 `HF_ENDPOINT=https://hf-mirror.com` 后 `hf_hub_download` 可用；MuQ-MuLan-large（2.5GB）+ DiffRhythm-1_2（2.1GB）+ MuQ-large-msd-iter（1.3GB）+ xlm-roberta-base（1.1GB）+ DiffRhythm-vae（596MB），合计约 7.5GB
4. 修改 infer 脚本 `decode_audio(..., chunked=False)` → `chunked=True`（`_patch_chunked` 幂等补丁）
5. 记录：峰值显存、95s 歌曲推理耗时、输出音质主观评估

### 结论

| 项 | 结果 |
|---|---|
| 峰值显存 | **6954 MiB（约 6.8GB，< 8GB）**，nvidia-smi 0.5s 采样 |
| 95s 歌曲推理耗时 | **24.54s**（diffusion 推理段，infer.py 计时）；含模型加载/G2P/MuQ 的总耗时 77.4s（首次运行） |
| 输出音质主观评估 | **GO**：95.11s 立体声 44.1kHz/16bit，RMS -14.6 dBFS（峰值 1.0），10s 分段能量连续（0.13–0.22），频谱低频 42% / 中频 58% / 高频 1%，温暖抒情听感与 "slow ballad, warm piano" 提示一致，无明显爆音/截断 |
| 结论 | **GO**（chunked=True 下 8GB 显存可完整推理 95s 带人声歌曲） |
| 风险项 | ① espeak-ng 需 .msi 安装 + `PHONEMIZER_ESPEAK_LIBRARY` DLL 定位（适配器已自动注入）；② 权重 ~7.5GB 依赖 hf-mirror 下载；③ 官方仓库不可 pip 安装（需 clone 到 module/diffrhythm 或 DIFFRHYTHM_DIR）；④ DiffRhythm 官方依赖与 torch cu121/numpy 2.x 有版本冲突，需按 requirements/ai.txt 注释处理 |
| 降级路径 | NO-GO 时：`ai diffrhythm` 明确提示退出码 6 + 使用 MusicGen 生成器乐伴奏（本 spike 判定 GO，未触发） |

**NO-GO 降级方案**：明确提示"DiffRhythm 需要 ≥8GB 显存且当前环境不可用"（退出码 6）；T-P1-2 延期，不影响 P0 交付；MusicGen（T-P1-1）不受影响。

### MusicGen 性能基线（P1-1 验收 4）

| 项 | 结果 |
|---|---|
| 模型 | facebook/musicgen-melody（1.5B，fp16；`--model-size medium` 映射） |
| 输出时长 | 20s（示例） |
| 峰值显存 | **5530 MiB（5.4GB，< 8GB）**，nvidia-smi 0.3s 采样 |
| 推理耗时 | 首次约 136–201s（含模型/依赖加载）；二次运行约 50–70s（20s 输出） |
| 采样率 | 32000 |
| 旋律相关性 | **chroma 相关 0.706**（阈值 ≥0.3；376 帧对齐，median 0.734） |
| `--seed` 复现 | **字节级一致**（1280044 bytes，同 seed 两次运行） |
| 模型映射修正 | audiocraft 仅 `facebook/musicgen-melody`（1.5B）支持 `generate_with_chroma`；`musicgen-medium` 同为 1.5B 但不支持旋律条件。因此 `--model-size medium` 映射到 musicgen-melody；`--model-size small` 映射到 musicgen-small（300M，不支持 chroma，自动降级为纯文本生成） |

---

## 5. P0 环境验证

```bash
# P0 环境（仅 base.txt）下：
smartnotegen ai musicgen --input m.wav --prompt "upbeat pop"
# → 错误 [6]: MusicGen 不可用：未安装 P1 依赖...
#   请先安装: pip install torch --index-url https://download.pytorch.org/whl/cu121
#   然后: pip install -r requirements/ai.txt

# 验证未触发 torch import：
python -c "import sys; import smartnotegen.cli; assert 'torch' not in sys.modules"
```

---

## 6. Suno API 调研（P3-B1）

> 调研日期：2026-08-12 | 调研人：吴八哥

### 结论：Suno 官方 API 已开放

Suno 提供了完整的 REST API，支持歌曲生成、扩展、翻唱、添加人声/伴奏等能力。

### 关键信息

| 项 | 内容 |
|---|---|
| 基础 URL | `https://studio-api.suno.ai/api/` |
| 认证方式 | Bearer Token（在 Suno Dashboard → Settings → API Keys 获取） |
| 生成端点 | `POST /generate/v2/` |
| 轮询状态 | `GET /feed/?ids=...` |
| 模型版本 | `chirp-v3-5`（默认）、`chirp-v4` |
| 价格 | Free 5次/天，Pro 500次/天，Premier 不限量 |
| 每次生成 | 2 个变体，消耗 10 credits |
| 代码示例 | Python SDK 见 neural-audio-theory 文档 |

### 可选集成方案

| 方案 | 复杂度 | 说明 |
|---|---|---|
| **A. 直接集成** | 中 | 在 SmartNoteGen 中新增 `ai suno` 子命令，调用 Suno API 上传本地产出片段，作为 Melody Lock 输入 |
| **B. 独立脚本** | 低 | 提供独立的 Python 脚本（`scripts/suno_upload.py`），用户自行配置 API Key 后调用 |
| **C. 保持现状** | 无 | 用户手动上传，SmartNoteGen 只负责打包 + 清单辅助 |

### 推荐

**方案 B（独立脚本）** 作为 P3-B1 的落地方式，因为：
- Suno API 需要用户自行申请 API Key，集成到 CLI 会增加认证复杂度
- 独立脚本更灵活，用户可按需修改
- 不增加 SmartNoteGen 核心代码的依赖
