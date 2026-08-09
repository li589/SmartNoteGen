# P1 AI 集成说明

> 版本：v0.1.0（P0 阶段占位，P1 里程碑完善）

P0 版本仅提供 AI 适配器骨架（延迟导入 + 明确提示），**不安装、不 import** torch/audiocraft/diffrhythm。

---

## 1. 安装（P1）

```bash
# 1. CUDA 版 torch（RTX 4060 / CUDA 12.1）
pip install torch --index-url https://download.pytorch.org/whl/cu121

# 2. 其余 AI 依赖
pip install -r requirements/ai.txt

# 3. Windows：DiffRhythm 人声合成需要 espeak-ng
#    下载官方 .msi 安装并加入 PATH
```

## 2. MusicGen 适配器（T-P1-1）

- 模型：`facebook/musicgen-medium`（1.5B，fp16，8GB 显存可跑）
- 用法：`smartnotegen ai musicgen --input melody.wav --prompt "upbeat pop" --output out.wav`
- 实现要点：`audiocraft.models.MusicGen.get_pretrained(...)`；melody conditioning 用 `generate_with_chroma`
- 验收：输出伴奏 WAV，且与输入旋律有相关性

## 3. DiffRhythm 适配器（T-P1-2，前置 T-S1 spike）

- 用法：`smartnotegen ai diffrhythm --prompt "slow ballad"`
- 关键修改：infer 脚本 `decode_audio(..., chunked=False)` → `chunked=True`（8GB 显存必需）
- 权重经 hf-mirror.com 下载；Windows 需 espeak-ng
- 显存不足时明确提示（退出码 6）

---

## 4. DiffRhythm 8GB 显存 spike 报告（T-S1）

> 状态：**待执行**（P1 最先执行）

### 执行步骤

1. 安装 CUDA 版 torch（替换官方 requirements.txt 默认 CPU 版）
2. Windows 安装 espeak-ng
3. 权重经 hf-mirror.com 下载
4. 修改 infer 脚本 `decode_audio(..., chunked=False)` → `chunked=True`
5. 记录：峰值显存、95s 歌曲推理耗时、输出音质主观评估

### 结论占位

| 项 | 结果 |
|---|---|
| 峰值显存 | （待填，目标 < 8GB） |
| 95s 歌曲推理耗时 | （待填） |
| 输出音质主观评估 | （待填） |
| 结论 | GO / NO-GO |

**NO-GO 降级方案**：明确提示"DiffRhythm 需要 ≥8GB 显存且当前环境不可用"（退出码 6）；T-P1-2 延期，不影响 P0 交付；MusicGen（T-P1-1）不受影响。

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
