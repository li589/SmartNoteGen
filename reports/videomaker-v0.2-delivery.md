# videomaker v0.2.0 交付报告

> 日期：2026-08-23 ｜ 版本：0.1.0 → 0.2.0 ｜ 主题：创意层激活

---

## 1. 交付概要

v0.1.0 审计发现 **PIL 创意层是 100% 死代码**（用户请求 circular_spectrum/reactive 实际回退到 ffmpeg 普通波形）。v0.2.0 核心使命：让创意层真正跑起来，补齐背景/文字链路。

| Wave | 任务 | 状态 |
|------|------|------|
| W1 | 创意层激活（预计算 + 双引擎路由） | ✅ |
| W2 | 背景叠加链路打通 | ✅ |
| W3 | 文字叠加 + 标题卡（微软雅黑） | ✅ |
| W5 | 测试补强 + 端到端验证 | ✅ |

（W4 滚动波形按主理人决策推迟至 v0.3）

## 2. 架构变化

### 双引擎路由（Compositor）

| style | 引擎 | 理由 |
|-------|------|------|
| waveform | ffmpeg 原生（showwaves） | 原生滚动、最快 |
| spectrum | ffmpeg 原生（showspectrum） | 原生频谱瀑布 |
| circular_spectrum | **PIL FrameEngine** | ffmpeg 无此滤镜 |
| reactive | **PIL FrameEngine** | 需要 RMS/onset 驱动 |

### 预计算架构（性能核心）

```
analyze(audio) 一次 → AudioAnalysis（频谱矩阵 + RMS包络 + 波形 + onset）
    ↓ 注入
VisualContext（全帧共享）→ render_frame(ctx, i) 查表渲染（~5ms/帧）
```

修复前每帧重算全量 STFT（300 帧 × O(n)），修复后只算一次。

### 关键修复清单

1. **创意层断链**：删除占位黑帧类，工厂 `create_visualizer()` 注册真实实现
2. **背景传递**：统一产出 PIL Image → ffmpeg 落盘 PNG 走 overlay 双输入；PIL 直接注入 ctx
3. **ImageDraw import**：补齐（原 gradient 路径必崩 NameError）
4. **沙箱兼容**：临时帧清理 `shutil.rmtree` → `_force_remove_tree`
5. **性能**：PIL 半分辨率渲染（render_scale=0.5）+ ffmpeg lanczos 上采样
6. **drawtext 中文**：微软雅黑 + Windows 盘符冒号转义（`C\:/Windows/Fonts/msyh.ttc`）

## 3. 验证证据

### 端到端冒烟（3s 音频，4 风格 × 4 平台对角组合）

| 组合 | 耗时 | 分辨率 | 视频流 | 音频流 |
|------|------|--------|--------|--------|
| waveform/douyin | 1.3s | 1080×1920 | ✅ | ✅ |
| spectrum/youtube | 1.0s | 1920×1080 | ✅ | ✅ |
| circular_spectrum/instagram | 21s | 1080×1080 | ✅ | ✅ |
| reactive/official | 22s | 1080×1350 | ✅ | ✅ |

### 画面内容验证（防止"假成功"）

- 圆形频谱帧中心亮度 126（有中心圆 + 放射条结构，非波形）
- 标题验证：1.5s 帧白色文字像素 1004-12264，2.5s 帧 0（淡入淡出生效）
- PIL 路径与 ffmpeg 路径标题均验证通过

### 测试

- `tests/test_videomaker.py`：**25/25 通过**（analysis/工厂/渲染/路由/预设/配置）
- 全量回归：**280 测试无失败**

## 4. 已知限制

1. **PIL 路径渲染耗时**：10s 音频约 60-130s（受机器负载影响，本机后台进程多）。
   半分辨率优化已生效（3s 音频 21s），如需更快可调 `render_scale=0.33` 或降 fps
2. **标题卡**：当前为"前 3s 淡入淡出叠加"，非独立 intro 片段（与音频同步，不占额外时长）
3. **滚动波形**（PIL 路径）：按决策推迟至 v0.3

## 5. 下一步建议（v0.3 候选）

1. 滚动波形（PIL 播放位置窗口）
2. 多段拼接（intro 片段 + 正文 + outro）
3. 批量渲染命令（一次吃 SNG batch 产物 → 多平台视频）
4. Logo/水印角标
