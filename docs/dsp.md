# DSP 功能包（R6）

`post dsp` 提供管道式 DSP 算子链：一次调用、多个算子按序执行。纯 numpy/scipy 实现
（不依赖 ffmpeg/sox），错误码分段：**15 = DSP 处理失败**、**16 = DSP 参数错误**。

## 用法

```bash
sunoaux post dsp <wav> --ops "<算子串>" [-o out.wav] [--bit-depth 16|24]
```

- 输出默认 `<输入主干>_dsp.wav`（同目录）；`--bit-depth 24` 写 PCM_24。
- `concat` 的相对路径按输入文件所在目录解析。
- 未知算子 / 非法参数 → 退出码 16；静音做 loudnorm 等运行期失败 → 退出码 15。

## 算子一览

| 算子 | 语法 | 说明 |
|---|---|---|
| `norm` | `norm [-1]` | 峰值归一化到目标 dBFS（可放大可衰减；静音不缩放） |
| `loudnorm` | `loudnorm [-16]` | **EBU R128 简化版**：K 加权（BS.1770 两阶段 biquad，sr 自适应）+ 400ms/100ms 分块 + 绝对门 -70 LUFS / 相对门 -10 LU → 目标 LUFS |
| `fade-in` / `fade-out` | `fade-in 0.5` | 余弦淡入/淡出（秒）；超出音频长度 → 16 |
| `trim` | `trim 10-25` | 裁剪 [START, END) 秒；区间非法/越界 → 16 |
| `resample` | `resample 32000` | scipy `resample_poly`（polyphase 抗混叠）；采样率相同为 no-op |
| `lowcut` | `lowcut 80` | 一阶高通低频切（复用既有 `filters.highpass`） |
| `compress` | `compress 3 [-14]` | 软拐点压缩：ratio（≥1）+ 阈值 dBFS（默认 -12） |
| `concat` | `concat b.wav [xf=0.5]` | 拼接（可选秒数交叉淡化，等功率余弦）；采样率不一致自动重采样 |

算子串语法：逗号分隔 `name` / `name 主参数` / `name key=value`，
例：`"norm -1, fade-in 0.5, trim 10-25, resample 32000, concat bed.wav xf=0.5"`。

## 架构

```
src/sunoauxtool/dsp/
├── processor.py   # P2-1 管线内链（render→export），增量兼容不动
├── filters.py     # 高通/压缩器（numpy，P2-1 起既有）
├── ops.py         # R6 通用算子框架：parse_ops → 注册表 → apply_ops
└── loudness.py    # EBU R128 简化版积分响度（BS.1770 口径）
```

新算子接入：写 `op_xxx(audio, sr, args) -> (audio, sr)` 纯函数 + 在 `OPS` 注册 +
数值断言单测（对齐 `tests/test_dsp_ops.py` 口径），无其它接线。

## 验证口径（tests/test_dsp_ops.py，23 例）

- `norm`：峰值 == 10^(dB/20)；
- `fade-in`：起点 0 / 终点 1 / 中点 0.5（余弦）；
- `resample`：采样率与时长按比例、440Hz 主频保持；
- `loudnorm`：997Hz 满幅正弦实测 ≈ -3.0 LUFS（理论 -3.70 raw + K 加权 +0.7dB，±0.8）；
  归一后实测 == 目标（±0.3 LU）；
- `concat xf`：总长 = 两段之和 − 交叉淡化；中点 = 等功率混合值。
