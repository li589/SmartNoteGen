# DownloadHelper（sunoauxtool.download，原 Suno-Cat-Catch-Resolve）— 下载/取证/转码

`sunoauxtool.download` 子模块（兼容 API 下载 adapter 于 R7 接入），负责处理 Suno 页面抓取产物：自动识别「能解码的明文」与
「不可解的加密密文」，并把前者转成可播放的 Opus / MP3，供 `sunoauxtool.video` 制作 MV。

## 一、取证结论（2026-09-20 实测）

用「猫抓」(CatCatcher) 抓 Suno 会得到**两类文件，它们是同一首曲子**：

| 抓取方式 | 常见文件名 | 真实身份 | 可解码 |
|---|---|---|---|
| **缓存捕获** | `Suno _ AI Music.mp3` | **fragmented MP4**：`ftyp`+`moov`+N×(moof/mdat)，音频是 **Opus 48kHz 立体声** | ✅ 直接解码 |
| **直接下载页面媒体** | `<uuid>.m4a` | **加密密文**（服务端下发原文） | ❌ 无密钥不可破 |

`.mp3` 那个扩展名是**错的**——它是 MP4 容器，播放器按 MP3 解析才打不开。

### 为什么 `<uuid>.m4a` 破不了

不是工具或方法问题，是**数学结论**。实测（N≈4.9MB）：

| 指标 | fMP4 内 Opus 明文 | `<uuid>.m4a` 密文 |
|---|---|---|
| 熵 | 7.998522 | **7.999962** |
| 卡方 χ² (df=255) | **11820** | **259**（均匀随机均值=255，σ≈22.6）|
| 周期扫描 (K=1..256) | — | 0.4168%，与随机基线 0.3906% 无异 |

- **χ²≈259**：字节分布完美均匀，与真随机不可区分 → 密码学强加密。
  （明文压缩音频 χ² 是它的约 45 倍，因为保留统计结构。）
- **无周期性**：排除「重复密钥 XOR」这类弱加密。
- 结论：属 **AES / ChaCha20 级流加密**，无密钥不可破。

> 熵的差异很小（7.9985 vs 8.0000），**卡方才是可靠判据**——它对样本量不敏感，
> 明文与密文相差约 45 倍。

### 工程结论

**不要试图破解 `<uuid>.m4a`。** 缓存捕获拿到的 fMP4 已经是同一首曲子的
**完整明文副本**，直接解码即可。`decode` / `batch` 遇到密文会明确报错并给出建议，
不会假装成功。

## 二、安装

本包是 `src/` 下的**独立 editable 兄弟包**（与 `smartnotegen` / `videomaker` 并列），
由本目录的 `pyproject.toml` 单独打包；主包 `pyproject.toml` 已 exclude 本目录。

### 命名约定（重要）

连字符不是合法 Python 标识符，故发行名与可导入包名分离：

| 用途 | 名称 |
|---|---|
| 目录 / 发行名 | `Suno-Cat-Catch-Resolve` |
| **可导入包名** | `suno_cat_catch_resolve` |
| 控制台脚本 | `suno-cat-catch-resolve` |

`import` 与 `python -m` 一律用 `suno_cat_catch_resolve`。

### 安装

```bash
随主包安装：`pip install -e .`（downloadhelper 入口兼容保留）
suno-cat-catch-resolve --help                 # 安装后的命令
```

不安装、临时试用（注意 PYTHONPATH 指向**子项目根**，不是 `src`）：

```bash
export PYTHONPATH="D:\New\Music\SmartNoteGen\src\Suno-Cat-Catch-Resolve"   # Git Bash
$env:PYTHONPATH="D:\New\Music\SmartNoteGen\src\Suno-Cat-Catch-Resolve"     # PowerShell
python -m suno_cat_catch_resolve version
```

核心层（`fmp4` / `forensics` / `transcoder`）**零第三方依赖**；只有 `cli.py` 需要 `typer`。

### ffmpeg 定位（四种方式，按优先级）

`find_ffmpeg()` 依次尝试，命中即返回：

| 顺序 | 方式 | 说明 |
|---|---|---|
| 1 | `--ffmpeg-path` / `find_ffmpeg(path=...)` | 显式传参，最高优先级 |
| 2 | 环境变量 `SUNO_FFMPEG` | 值可以是**可执行文件**，也可以是**所在目录**；高于 PATH，用来压过 PATH 上版本不符的 ffmpeg |
| 3 | `PATH` | `shutil.which("ffmpeg")` |
| 4 | 环境变量 `SUNO_FFMPEG_DIRS` | 追加搜索目录，多目录用系统分隔符（Windows `;` / POSIX `:`） |
| 5 | 硬编码本机目录 | 兜底，仅本机有效 |

```bash
export SUNO_FFMPEG="/d/tools/ffmpeg/bin/ffmpeg.exe"        # Git Bash：直接指文件
set SUNO_FFMPEG=D:\tools\ffmpeg\bin                        # ...或指目录（自动找 ffmpeg.exe）
set SUNO_FFMPEG_DIRS=D:\tools\ffmpeg\bin;E:\ffmpeg\bin      # 多目录
```

`SMARTNOTEGEN_FFMPEG` 是同一约定的别名（沿用主包 `DIFFRHYTHM_DIR` 的双写法）。
环境变量写成无效路径时**继续回落**而非直接报错；空串等同未设置。
四处都找不到才抛 `FFmpegNotFoundError`（错误码 20），消息里会列出全部可选修法。

## 三、CLI

```bash
# 取证：判定是明文还是密文
python -m suno_cat_catch_resolve probe "Suno _ AI Music (1).mp3"

# 解码单文件（默认同时出 opus 无损 + mp3 通用）
python -m suno_cat_catch_resolve decode "Suno _ AI Music (1).mp3" -o ./out

# 只出无损 Opus / 只出 MP3
python -m suno_cat_catch_resolve decode "in.mp3" -o ./out --fmt opus
python -m suno_cat_catch_resolve decode "in.mp3" -o ./out --fmt mp3 --bitrate 256k

# 批量：扫描目录，解码所有 fMP4，密文自动跳过并汇总
python -m suno_cat_catch_resolve batch ./downloads -o ./out

python -m suno_cat_catch_resolve version
```

错误码（延续项目分段：smartnotegen 0-9、videomaker 10-14）：

| code | 含义 |
|---|---|
| 20 | ffmpeg 未找到 |
| 21 | 不是可解析的 fragmented MP4 |
| 22 | 输入是加密密文，无密钥不可解码 |
| 23 | 转码失败 |
| 24 | 输出路径不可写 |

## 四、Python API

```python
from suno_cat_catch_resolve import identify, decode_fmp4
from suno_cat_catch_resolve.exceptions import EncryptedBlobError

# 取证
verdict = identify("Suno _ AI Music (1).mp3")
print(verdict.kind)        # 'fmp4' | 'mp3' | 'ogg' | 'encrypted' | ...
print(verdict.breakable)   # True / False
print(verdict.render())    # 多行人类可读报告

# 解码（密文会抛 EncryptedBlobError，不会静默产出垃圾文件）
try:
    paths = decode_fmp4("Suno _ AI Music (1).mp3", out_dir="out", fmt="both")
except EncryptedBlobError as exc:
    print(exc.message)     # 含熵/卡方证据与处置建议
```

底层可单独用：

```python
from suno_cat_catch_resolve.fmp4 import parse_atoms, concatenate_mdat, summarize
from suno_cat_catch_resolve.forensics import entropy, chi_square, periodicity_scan
from suno_cat_catch_resolve.transcoder import remux_opus, to_mp3, probe, find_ffmpeg
```

## 五、已知的坑

1. **Opus 不能直接 `-c copy` 进 `.m4a`/MP4**——ipod 封装器会报
   `Could not find tag for codec opus ... not currently supported in container`。
   无损请用 Ogg `.opus`，或转 MP3/AAC。
2. **别按扩展名判断格式**，一律走 `identify()`：Suno 产物扩展名基本不可信。
3. `batch` 只处理判定为 `fmp4` 的文件，其余静默跳过并计入报告。

## 六、测试

```bash
pip install -e "src/Suno-Cat-Catch-Resolve[dev]"   # 需要 pytest / pytest-cov
cd src/Suno-Cat-Catch-Resolve
python -m pytest --cov --cov-report=term-missing   # 覆盖率门槛 95%（实测 100%）
```

147 例，覆盖 `fmp4` / `forensics` / `transcoder` / `cli` 全部模块（语句覆盖率 100%）：

| 文件 | 重点 |
|---|---|
| `test_fmp4.py` | 原子解析（32/64 位长度、size=0 到 EOF、非 ASCII 类型中断、截断）、mdat 拼接、`summarize` |
| `test_forensics.py` | 熵 / 卡方 / 周期扫描的边界与**判据**、五种容器魔数 + MP3 帧同步、明文/密文/弱加密三条判定分支 |
| `test_transcoder.py` | ffmpeg 定位五级回落（参数 → `SUNO_FFMPEG` → PATH → `SUNO_FFMPEG_DIRS` → 硬编码）、`_sanitize`、异常分级、`decode_fmp4` 全分支；**末尾用真实 ffmpeg 跑端到端** |
| `test_cli.py` | 四个子命令、退出码 2/22/23、batch 汇总报告；**末尾绕开 mock 走真实链路** |

要点：

- **环境相关的用例自带隔离**：`conftest.py` 有 autouse fixture 清空
  `SUNO_FFMPEG` / `SMARTNOTEGEN_FFMPEG` / `SUNO_FFMPEG_DIRS`。
  否则开发机自己设了这些变量，那些「应当回落到 PATH / 应当抛错」的用例
  会静默变成假绿或假红——测试结果不该由运行者的机器环境决定。

- **合成样本优先**：`tests/conftest.py` 用纯 Python 拼 ISO BMFF 原子，
  单元测试不需要 ffmpeg，也不需要任何真实音频文件。
- **密文样本用固定种子**（`random.Random(1234)`）而非 `os.urandom`，
  保证 χ² 稳定落在密文判据区间，测试不会偶发翻转。
- **集成测试缺 ffmpeg 自动 skip**，不会因为环境不全而假红。
- 合成 fMP4 只有合法容器结构、没有可解码音轨，所以凡是需要 ffmpeg 真正
  转码的用例都必须用**现场生成的真 fMP4**，不能用合成样本 —— 否则会「通过得莫名其妙」。

CI 中该子包由独立步骤安装并运行（主包 `packages.find` 已排除它，
其测试不在根 `testpaths` 内，不单独跑就完全不会被收集）。

---

## 下载源统一接口（R7，`sunoaux post fetch`）

```
sunoaux post fetch <query> [--source catcatch|suno-api|haimeng|tianyin] [-o 输出目录]
```

| 源 | query 含义 | 状态 |
|---|---|---|
| `catcatch`（默认） | 猫抓缓存目录路径 | ✅ 全量可用（= `downloadhelper batch` 直通，`--fmt/--bitrate/--ffmpeg-path` 原样透传） |
| `suno-api` | 歌曲/任务 ID | 留位：配置驱动，拿到合法 API 后填配置即用 |
| `haimeng` | 歌曲/任务 ID | 留位（同上） |
| `tianyin` | 歌曲/任务 ID | 留位（同上） |

### API 源接入契约（mock 契约测试已锁定）

1. 配置文件（gitignored，查找顺序后者覆盖前者）：`config/sources.toml` → `~/.sunoauxtool/sources.toml`
2. 配置格式：

   ```toml
   [sources."suno-api"]
   endpoint = "https://你的端点/v1/songs"   # 必填
   token = "..."                            # 可选，Bearer 头
   ```

3. 请求：`GET {endpoint}?id={query}`，头 `Authorization: Bearer {token}`；
4. 响应 JSON：`{"files": [{"url": "...", "name": "..."}, ...]}`；
5. 文件逐个下载到输出目录（`name` 缺省从 URL 推断）。

错误码：**25** = 凭证/端点缺失、**26** = 请求或响应解析失败；猫抓路径沿用 20-24。
**本仓库不做客户端逆向**（同猫抓取证边界：明文可取、密文不碰）——API 源只在
拿到合法授权接口时接入。
