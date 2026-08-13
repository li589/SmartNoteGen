# SmartNoteGen P3 二期产品需求文档（PRD）

> 版本：v1.0 ｜ 作者：许清楚（Product Manager） ｜ 日期：2026-08-12
> 状态：待评审
> 上游输入：`docs/research-P3.md`（P3 深度研究）、`docs/PRD-P3.md`（P3 一期 v1.0）
> 范围：P3 二期 — 创作工作台（方向 C：灵感库 + 版本对比 + 参数引导）

---

## 0. 变更摘要

### 0.1 交付现状（v0.3.0 已发布）

P3 一期已交付：HTML 预览页、play 子命令、音频特征、doctor 诊断、config 预览节。全量 251 测试全绿。

### 0.2 本增量 PRD 范围

| 编号 | 内容 | 类型 |
|---|---|---|
| P3-C1 | **灵感库**：把好的生成结果存入可检索库，支持按风格/和弦/seed/日期检索 | 新增 |
| P3-C3 | **版本对比**：同一 seed 不同参数迭代时，自动对比版本差异 | 新增 |
| P3-C2 | **参数引导 wizard**：`new` 子命令交互式引导用户逐步生成，降低新手门槛 | 新增 |

### 0.3 关键原则

1. **纯增量**：以新文件 + 新子命令实现，不修改既有接口签名
2. **轻量存储**：灵感库使用 SQLite（Python 内置，零依赖）
3. **保持 CLI 心智模型**：wizard 是交互式引导，灵感库是文件管理工具
4. **251 测试全绿基线**：不破坏既有测试

---

## 1. P3-C1 灵感库

### 1.1 背景与问题

用户生成大量变体后，好动机散落在各个目录中，无法快速检索和复用。当前 metadata.json 记录了每次运行，但没有跨运行的索引。

### 1.2 User Stories

- **作为创作者**，我想把满意的生成结果标记为"灵感"并存入库，方便以后检索。
- **作为批量创作者**，我想按风格/和弦/日期/BPM 筛选历史灵感，快速找到合适的动机。
- **作为迭代创作者**，我想从灵感库中引用一个灵感作为新生成的基础（seed + 参数复用）。

### 1.3 需求细化

| 子项 | 需求 |
|---|---|
| P3-C1a | **灵感库初始化**：`inspire init` 在项目根创建 `smartnotegen.db`（SQLite） |
| P3-C1b | **添加灵感**：`inspire add <wav_path>` 将指定 WAV 加入灵感库，自动提取元数据（来自 metadata.json 或 WAV 同目录元数据） |
| P3-C1c | **添加参数**：`--tags "upbeat,pop"` 用户自定义标签；`--rating 1-5` 评分 |
| P3-C1d | **列出灵感**：`inspire list` 列出所有灵感，支持 `--style`/`--tag`/`--seed`/`--date` 筛选 |
| P3-C1e | **查看详情**：`inspire show <id>` 显示灵感详情（路径/参数/特征/标签/评分） |
| P3-C1f | **删除灵感**：`inspire rm <id>` 删除灵感（仅从库中移除，不删文件） |
| P3-C1g | **导出灵感**：`inspire export <id> --output <dir>` 复制灵感文件到指定目录 |
| P3-C1h | **自动集成**：`pipeline`/`batch` 后自动提示"是否保存为灵感"（可选，默认不自动保存） |

### 1.4 技术方案

**存储**：SQLite（Python 内置 `sqlite3`，零依赖）

**Schema**：
```sql
CREATE TABLE inspirations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,              -- WAV 文件绝对路径
    kind TEXT DEFAULT 'suno',        -- suno | draft | wav
    style TEXT,                      -- 风格
    bpm INTEGER,                     -- BPM
    seed INTEGER,                    -- 随机种子
    chords TEXT,                      -- 和弦进行
    duration_s REAL,                 -- 时长
    sample_rate INTEGER,             -- 采样率
    rms_db REAL,                     -- 音频特征
    peak_db REAL,
    spectral_centroid REAL,
    tags TEXT,                       -- 逗号分隔的用户标签
    rating INTEGER,                  -- 1-5 评分
    created_at TEXT,                 -- 添加时间 ISO 8601
    params_json TEXT                 -- 完整参数 JSON（从 metadata 提取）
);
```

**实现位置**：新增 `src/smartnotegen/inspire.py`

```python
class InspirationDB:
    def __init__(self, db_path: Optional[str] = None) -> None
    def init_db(self) -> None
    def add(self, wav_path: str, metadata: dict, tags: str = "",
            rating: Optional[int] = None) -> int  # 返回 id
    def list(self, style: Optional[str] = None, tag: Optional[str] = None,
             seed: Optional[int] = None, date: Optional[str] = None,
             limit: int = 50) -> list[dict]
    def get(self, id: int) -> Optional[dict]
    def delete(self, id: int) -> bool
    def export_files(self, id: int, output_dir: str) -> list[str]
```

### 1.5 验收标准

- [ ] `inspire init` 创建 `smartnotegen.db`，表结构正确
- [ ] `inspire add <wav>` 从 metadata.json 自动提取元数据并入库，返回 id
- [ ] `inspire add --tags "upbeat,pop" --rating 4` 保存标签和评分
- [ ] `inspire list` 列出所有灵感，按日期降序
- [ ] `inspire list --style pop --tag upbeat` 筛选正确
- [ ] `inspire show <id>` 显示完整详情
- [ ] `inspire rm <id>` 从库中移除（文件不删）
- [ ] `inspire export <id> --output <dir>` 复制文件到目标目录
- [ ] 全量测试保持全绿，新增 `test_inspire.py` 覆盖

---

## 2. P3-C3 版本对比

### 2.1 背景与问题

用户迭代创作时（同 seed 不同参数），难以对比两个版本的差异，只能靠耳朵听。

### 2.2 User Stories

- **作为迭代创作者**，我想对比两个 WAV 文件的音频特征差异（RMS/峰值/频谱），以便量化评估哪个版本更好。
- **作为参数调优者**，我想对比两个版本的参数差异（BPM/和弦/风格/seed），快速知道改了哪些参数。

### 2.3 需求细化

| 子项 | 需求 |
|---|---|
| P3-C3a | `diff <wav1> <wav2>` 对比两个 WAV 的音频特征差异 |
| P3-C3b | 对比项：时长差、RMS 差、峰值差、频谱中心差、频段能量差 |
| P3-C3c | 参数对比：如果有 metadata.json 同目录，提取参数 diff |
| P3-C3d | 输出格式：表格形式，一目了然 |

### 2.4 验收标准

- [ ] `smartnotegen diff a.wav b.wav` 输出特征对比表
- [ ] 包含时长/RMS/峰值/频谱中心/频段能量
- [ ] 同目录有 metadata.json 时自动提取参数对比
- [ ] 文件不存在时退出码 3

---

## 3. P3-C2 参数引导 wizard

### 3.1 背景与问题

新用户面对 `--chords/--bpm/--key/--bars/--style/--seed` 等参数感到困惑，不知道从哪开始。

### 3.2 User Stories

- **作为新用户**，我想运行一个交互式向导，一步步输入（或选择默认值）来生成第一段音乐，不需要记参数名。
- **作为快速创作者**，我想在向导中快速试听（先 dry-run 预览），满意再执行。

### 3.3 需求细化

| 子项 | 需求 |
|---|---|
| P3-C2a | `new` 子命令启动交互式向导 |
| P3-C2b | 步骤：选择风格 → 调整 BPM → 选择和弦 → 调整时长 → 确认执行 |
| P3-C2c | 每步显示推荐默认值，用户直接回车使用默认 |
| P3-C2d | 非 TTY 时自动使用默认值执行（与 `pipeline` 等价） |
| P3-C2e | 完成后自动打开预览页（调用浏览器） |

### 3.4 验收标准

- [ ] `smartnotegen new` 在 TTY 下交互式引导用户
- [ ] 非 TTY 时自动执行 `pipeline` 等价行为
- [ ] 完成后提示预览页路径

---

## 4. 交付顺序

```
P3-C1 灵感库（核心，最优先）
  ├─ init/add/list/show/rm/export
  └─ 测试：test_inspire.py

P3-C3 版本对比（独立，可并行）
  └─ diff 子命令 + 测试

P3-C2 参数引导 wizard（可后续）
  └─ new 子命令 + 测试
```

**建议实现顺序**：C1 → C3 → C2

---

## 5. 风险与开放项

| 风险 | 等级 | 缓解 |
|---|---|---|
| SQLite 并发写入冲突 | 低 | 单用户 CLI，无并发问题 |
| 灵感库文件路径漂移（移动文件后失效） | 中 | 路径为绝对路径，移动后需 re-add；文档说明 |
| wizard 交互式体验（Windows 终端兼容性） | 低 | 使用 `input()` 兼容所有终端 |