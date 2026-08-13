# SmartNoteGen P3 一期产品需求文档（PRD）

> 版本：v1.0 ｜ 作者：许清楚（Product Manager） ｜ 日期：2026-08-11
> 状态：待评审
> 上游输入：`docs/research-P3.md`（P3 深度研究）、`docs/PRD.md`（P0 v1.0）、`docs/PRD-P1P2.md`（P1+P2 v1.1）
> 范围：P3 一期 — 创作体验闭环（方向 A + 方向 E）

---

## 0. 变更摘要

### 0.1 交付现状（v0.2.0 已发布）

P0 + P1 + P2 全部交付，形成完整「程序化 MIDI 生成 → 渲染 WAV → Suno 合规导出 → 可选 AI 扩编曲」管线。全量 241 测试全绿，覆盖率 91%，v0.2.0 Release 已发布到 GitHub。

### 0.2 新增环境事实

| 项 | 确认 |
|---|---|
| 主理人确认可做 UI（网页形式） | 当前纯 CLI 产出文件，下一步可自动生成 HTML 预览页 |
| 项目源代码 6018 行，测试 3268 行 | 增量开发，不破坏既有测试 |
| Python 3.12，无前端依赖 | 预览页为自包含 HTML（无 node/npm 需求） |

### 0.3 本增量 PRD 范围

| 编号 | 内容 | 类型 |
|---|---|---|
| P3-A1 | **HTML 预览页**：pipeline/render/batch 后自动产出 preview.html，内嵌波形 + 频谱 + 播放器 | 新增 |
| P3-A2 | **play 子命令**：调用系统默认播放器试听 WAV | 新增 |
| P3-A3 | **音频特征摘要**：RMS/峰值/频谱分布写入 metadata.json | 新增 |
| P3-E3 | **doctor 子命令**：一键环境健康检查（fluidsynth/SF2/AI/显存/依赖） | 新增 |
| P3-E2 | **config init 交互式向导**：逐步引导用户配置 SoundFont/fluidsynth 路径 | 改进 |

### 0.4 关键原则

1. **纯增量**：所有新增以新文件 + 新子命令实现，不修改既有接口签名
2. **无新重型依赖**：HTML 预览页为自包含文件（numpy/soundfile 已存在），无 node/npm
3. **保持 CLI 心智模型**：预览页是"产物"而非"交互 UI"，doctor 是诊断工具
4. **241 测试全绿基线**：不破坏既有测试

---

## 1. P3-A1 HTML 预览页

### 1.1 背景与问题

当前产出物是"文件列表"，用户需要手动打开 WAV 文件才能知道效果。批量生成后更是难以快速判断哪个变体好。

### 1.2 User Stories

- **作为创作者**，我想在生成后立即看到一个**带波形和播放器的网页**，以便快速判断这个片段是否可用。
- **作为批量创作者**，我想在 batch 产出后得到一个**预览总览页**，列出所有变体的波形/参数/特征，方便对比挑选。
- **作为本地用户**，我想在浏览器中打开这个 HTML 即可播放，不需要安装任何额外软件。

### 1.3 需求细化

| 子项 | 需求 |
|---|---|
| P3-A1a | **单文件预览**：`pipeline`/`render`/`export suno` 后，在产物同目录产出 `preview.html` |
| P3-A1b | **批量预览**：`batch` 后产出 `preview.html`，列出所有变体的波形缩略图 + 参数 + 播放按钮 |
| P3-A1c | **预览内容**：波形图（waveform）+ 频谱图（spectrogram）+ 内嵌 `<audio>` 播放器 + 元数据（时长/采样率/风格/seed/BPM） |
| P3-A1d | **自包含**：单 HTML 文件，所有数据以 base64 内嵌，无外部依赖，离线可打开 |
| P3-A1e | **主题**：跟随系统暗色/亮色模式（prefers-color-scheme），深色背景为主 |

### 1.4 技术方案

**实现位置**：新增 `src/smartnotegen/preview.py`

```python
class PreviewGenerator:
    """生成自包含 HTML 预览页。"""
    def generate_for(self, wav_path: str, metadata: dict, output_dir: str) -> str
    def generate_batch(self, artifacts: list[ArtifactMeta], output_dir: str) -> str
```

**波形数据**：numpy 读取 WAV → 降采样到 ~2000 点（等距采样，保持包络）→ JSON base64 内嵌
**频谱图**：短时傅里叶变换（STFT）→ 频谱矩阵 → 降采样 → base64
**HTML 模板**：硬编码字符串模板（无外部文件），包含：
- Canvas 2D 绘制波形（蓝色/青色波形，深色背景）
- Canvas 2D 绘制频谱（热力图）
- `<audio>` 标签播放
- 元数据展示区

**依赖**：全部使用已有依赖（numpy + soundfile），无新包。

### 1.5 验收标准

- [ ] `smartnotegen pipeline --duration 10` 后，产物目录下存在 `preview.html`，浏览器打开可看到波形 + 播放按钮 + 元数据
- [ ] `smartnotegen batch --count 3` 后，产物目录下 `preview.html` 列出 3 个变体的波形缩略图 + 参数 + 播放按钮
- [ ] 预览页离线可打开（无网络请求），暗色主题
- [ ] 波形图肉眼可见包络变化（非平直线），播放功能正常
- [ ] 全量测试保持全绿，新增 `test_preview.py` 覆盖

---

## 2. P3-A2 play 子命令

### 2.1 背景与问题

用户生成 WAV 后需要手动找到文件双击打开，操作路径长。

### 2.2 User Stories

- **作为创作者**，我想在终端直接输入 `smartnotegen play <file.wav>` 立即听到声音，不需要打开文件管理器。

### 2.3 需求细化

| 子项 | 需求 |
|---|---|
| P3-A2a | `smartnotegen play <wav_path>` 调用系统默认播放器播放 |
| P3-A2b | Windows 上使用 `os.startfile` 或 `start` 命令 |
| P3-A2c | 文件不存在时给出明确错误（退出码 3） |
| P3-A2d | 支持 `--device` 参数（可选，默认为系统默认） |

### 2.4 验收标准

- [ ] `smartnotegen play output/xxx.wav` 打开系统默认播放器播放
- [ ] 不存在的路径给出错误码 3 + 友好提示
- [ ] 非 WAV 文件给出警告但仍尝试播放

---

## 3. P3-A3 音频特征摘要

### 3.1 背景与问题

当前 metadata.json 不含音频特征，用户无法通过数值快速判断片段差异。

### 3.2 需求细化

| 子项 | 需求 |
|---|---|
| P3-A3a | metadata.json 的 `artifacts[].params` 中增加音频特征字段 |
| P3-A3b | 特征字段：`rms_db`（平均 RMS）、`peak_db`（峰值）、`spectral_centroid`（频谱中心）、`band_energy`（低频/中频/高频能量占比） |
| P3-A3c | 仅在 WAV 产出时计算（MIDI 不计算） |
| P3-A3d | 计算开销小（对 <30s 音频应在 100ms 内完成） |

### 3.3 验收标准

- [ ] `pipeline` 后 metadata.json 中 WAV 产物包含 `rms_db`/`peak_db`/`spectral_centroid`/`band_energy` 字段
- [ ] 数值合理（-1dBFS 归一化后 peak_db ≈ -1.0）
- [ ] 计算耗时 < 100ms（30s 音频）

---

## 4. P3-E3 doctor 子命令

### 4.1 背景与问题

用户遇到问题（渲染失败、AI 不可用）时，需要手动排查环境，缺少一键诊断工具。

### 4.2 User Stories

- **作为新用户**，我想运行 `smartnotegen doctor` 一键检查所有依赖，告诉我哪些 OK、哪些需要修复。
- **作为遇到错误的用户**，我想在遇到问题后先跑 `doctor` 看看环境是否完整，再决定是否反馈。

### 4.3 需求细化

| 子项 | 需求 |
|---|---|
| P3-E3a | 检测项：Python 版本、fluidsynth（路径 + 可执行）、SoundFont（主库 + 备选）、AI 依赖（torch/audiocraft/diffrhythm）、显存（CUDA 可用 + 总量）、espeak-ng、项目完整性（pyproject.toml/module 目录） |
| P3-E3b | 每项输出：✅/❌ + 状态 + 修复指引 |
| P3-E3c | 退出码：全部 OK → 0；有警告 → 1；有错误 → 2 |
| P3-E3d | 复用现有 `PathResolver`/`ProbeStatus` 组件 |

### 4.4 验收标准

- [ ] `smartnotegen doctor` 输出完整诊断报告（含 Python/fluidsynth/SF2/AI/显存/espeak）
- [ ] 全部正常时退出码 0
- [ ] 复用现有 env.py 探测逻辑，不重复实现
- [ ] 新增 `test_doctor.py` 覆盖

---

## 5. P3-E2 config init 交互式向导

### 5.1 背景与问题

`config init` 当前只是生成模板文件，用户仍需手动编辑路径。

### 5.2 需求细化

| 子项 | 需求 |
|---|---|
| P3-E2a | `config init` 改为交互式：自动检测 module/ 下 fluidsynth/SF2，引导用户确认或手动指定 |
| P3-E2b | 保持 `--path` 参数指定输出位置 |
| P3-E2c | 非交互模式（`--yes` 或非 TTY）直接使用默认值生成 |
| P3-E2d | 检测结果引用 PathResolver 复用 |

### 5.3 验收标准

- [ ] `config init` 在 TTY 下交互式引导用户配置路径
- [ ] `config init --yes` 非交互式生成默认配置
- [ ] 检测到 module/ 路径时自动填入推荐值
- [ ] 既有 `config init` 测试保持全绿

---

## 6. 交付顺序与依赖关系

```
P3-A1  HTML 预览页（核心，最优先）
  ├─ 依赖：soundfile + numpy（已有）
  └─ 产出：preview.py + preview.html 模板

P3-A3  音频特征摘要（P3-A1 的附带功能）
  └─ 依赖：P3-A1 的音频分析逻辑

P3-A2  play 子命令（独立，可并行）
  └─ 依赖：无

P3-E3  doctor 子命令（独立，可并行）
  └─ 依赖：env.py 已有 PathResolver

P3-E2  config init 向导（可后续）
  └─ 依赖：P3-E3 的探测逻辑
```

**建议实现顺序**：A1 → A3 → A2/E3（并行）→ E2（最后）

---

## 7. 待确认问题

| # | 问题 | 建议默认 | 影响 |
|---|---|---|---|
| 1 | HTML 预览页是否需要频谱图（STFT 计算开销） | 要，但作为可选区域（默认折叠，点击展开） | 预览页复杂度 |
| 2 | 预览页是否加入 AI 分析建议（如"这个片段能量偏低"） | 暂不加，P3 二期再议 | 范围控制 |
| 3 | play 是否支持批量播放（`play --batch`） | 暂不支持，只支持单文件 | 范围控制 |
| 4 | doctor 是否要检查网络连通性（如 hf-mirror） | 不加，网络检查不稳定且耗时 | 可靠性 |
| 5 | config wizard 是否需要选择 SoundFont 音色（A/B 切换） | 要，自动检测后让用户选择默认或备选 | 用户体验 |

---

## 8. 风险与开放项

| 风险 | 等级 | 缓解 |
|---|---|---|
| HTML 预览页文件体积（base64 音频） | 低 | 30s WAV 约 1.7MB，base64 后约 2.3MB，现代浏览器可接受 |
| STFT 频谱计算耗时 | 低 | 30s 音频 STFT 约 50ms，可接受 |
| 预览页浏览器兼容性 | 低 | 仅使用 Canvas 2D + Audio API，主流浏览器均支持 |
| doctor 误报 | 低 | 复用 PathResolver 已验证的分级逻辑 |