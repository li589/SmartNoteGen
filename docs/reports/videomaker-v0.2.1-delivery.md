# videomaker v0.2.1 交付报告

> 日期：2026-08-23 ｜ 版本：0.2.0 → 0.2.1 ｜ 主题：rawvideo 提速 + Logo 水印 + multi 批量

---

## 交付概要

主理人四项全选，按 Wave 完成：**W4 PIL 性能优化 → W3 Logo 水印 → W2 multi 批量 → W5 文档**。

| Wave | 交付 | 状态 |
|------|------|------|
| W4 | rawvideo 管道（21s → 0.8s） | ✅ 提速 26 倍 |
| W3 | Logo/水印（CLI + 配置 + 双引擎） | ✅ |
| W2 | multi 多平台批量命令 | ✅ |
| W5 | docs/videomaker.md + README + 测试补强 | ✅ |

## 关键突破：rawvideo 管道

**FrameEngine 重构**：从"PNG 帧序列落盘 → ffmpeg 读文件"改为 **PIL 帧 numpy→bytes 直写 ffmpeg stdin**，零中间文件。

| 音频时长 | 优化前（PNG 路径） | 优化后（rawvideo） |
|----------|---------------------|---------------------|
| 3s | 21s | **0.8s** |

### 管道死锁修复（最关键 bug）
ffmpeg 进度日志量大，stderr 不排空会填满缓冲 → `proc.stdin.write()` 阻塞 → 死锁。加 **daemon 线程持续 drain stderr** 解决。

## 新增功能

### Logo 水印（--logo）
- ffmpeg 路径：PIL 缩放+定位 → 临时 PNG → overlay 双输入（`[base][logo]overlay`）
- PIL 路径：alpha_composite 四角合成
- 四角定位 + 透明度 + 尺寸比例，CLI `--logo` / `--logo-pos`

### multi 批量命令
```bash
videomaker multi audio.wav --presets douyin,youtube,instagram,official --style circular_spectrum --logo logo.png
```
一次产出全平台，输出结果表，复用同一次音频分析。

## 规避的三个新版 ffmpeg 坑（固化为经验）

1. **`-loop 1` + `-shortest` 死锁**（2026 版）：改单帧图片输入 + 链尾 `format=yuv420p`
2. **overlay 输入顺序**：`[底图][叠加层]`，反了会把 logo 当底图（输出变 logo 尺寸）
3. **x264 奇数尺寸拒绝**：logo 缩放强制 `//2*2` 偶数（yuv420p 要求）

## 验证证据

| 测试 | 结果 |
|------|------|
| circular 3s rawvideo | 0.8s, 1080x1080, v=Y a=Y |
| logo 水印（ffmpeg 路径） | 右下角红色像素 12694（1080p） |
| logo 水印（PIL 路径） | 红色像素 4770（1080x1080） |
| reactive + title + logo 全组合 | logo红1798 标题白2956 |
| multi 两平台 | 2.1s 全成功 |
| 单元测试 | **33/33 通过** |
| 全量回归 | 全部通过 |

## 交付文件

```
docs/videomaker.md     # 完整使用指南（新增）
README.md              # 增 videomaker 章节
src/videomaker/
  config.py            # + LogoConfig
  cli.py               # + multi 命令、--logo/--logo-pos
  engines/
    ffmpeg_engine.py   # + overlay logo、format 尾、无 -loop
    frame_engine.py    # rawvideo 管道 + stderr 线程 + logo alpha
tests/test_videomaker.py  # 25 → 33 测试（+logo）
```
