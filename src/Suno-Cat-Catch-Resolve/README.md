# suno — Suno 逆向取证与转码

`SmartNoteGen` 子包，负责处理 Suno 页面抓取产物：自动识别「能解码的明文」与
「不可解的加密密文」，并把前者转成可播放的 Opus / MP3，供 `videomaker` 制作 MV。

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
pip install -e src/Suno-Cat-Catch-Resolve     # 独立安装（同 venv）
suno-cat-catch-resolve --help                 # 安装后的命令
```

不安装、临时试用（注意 PYTHONPATH 指向**子项目根**，不是 `src`）：

```bash
export PYTHONPATH="D:\New\Music\SmartNoteGen\src\Suno-Cat-Catch-Resolve"   # Git Bash
$env:PYTHONPATH="D:\New\Music\SmartNoteGen\src\Suno-Cat-Catch-Resolve"     # PowerShell
python -m suno_cat_catch_resolve version
```

核心层（`fmp4` / `forensics` / `transcoder`）**零第三方依赖**；只有 `cli.py` 需要 `typer`。
另需 ffmpeg（自动查找 PATH，或 `--ffmpeg-path` 指定）。

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
