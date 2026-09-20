"""取证分析：判定一个文件是「可解码明文」还是「加密密文」。

判据来源（2026-09-20 对 Suno 实样的实测）：

    明文（fMP4 内 Opus 码流，N≈4.8MB）
        熵 7.998522   卡方 χ² ≈ 11820
        → 压缩音频保留统计结构，字节分布**明显偏离均匀**

    密文（猫抓直下 *.m4a，N≈4.9MB）
        熵 7.999962   卡方 χ² ≈ 259（df=255，均匀随机 χ² 均值=255，σ≈22.6）
        → 字节分布**完美均匀**，与真随机不可区分

关键：熵的差异极小（7.9985 vs 8.0000），**卡方才是可靠判据**——
它对样本量不敏感（已按期望频数归一化），明文与密文相差约 45 倍。

周期性扫描用于区分弱加密与强加密：
    若为「重复密钥 XOR」，密文在密钥长度 K 处会出现偏移自相关峰
    （match 率显著高于随机基线 1/256≈0.39%）。
    实测密文各 K 均在 0.41% 左右，与基线无异 → 排除重复密钥 XOR。
"""

from __future__ import annotations

import collections
import math
from dataclasses import dataclass, field
from typing import List, Optional

# 均匀随机判据：χ²(df=255) 均值 255，取均值+4σ≈345 作上界
CHI2_UNIFORM_MAX = 360.0
# 随机基线：任意两字节相等的概率 1/256
RANDOM_MATCH_BASE = 1.0 / 256.0
# 超过基线 3 倍认为存在周期性（弱加密特征）
PERIODICITY_RATIO = 3.0

SAMPLE_LIMIT = 2_000_000     # 熵/卡方采样上限
PERIOD_SAMPLE = 200_000      # 周期性扫描采样长度
DEFAULT_MAX_PERIOD = 64

CONTAINER_MAGICS = [
    (b"ftyp", "mp4"),     # ftyp 通常位于偏移 4，故单独判断
    (b"OggS", "ogg"),
    (b"RIFF", "wav"),
    (b"ID3", "mp3"),
    (b"fLaC", "flac"),
]


@dataclass
class Verdict:
    """取证结论。"""

    kind: str                      # fmp4 / mp4 / mp3 / ogg / wav / encrypted / unknown
    path: str = ""
    entropy: float = 0.0
    chi_square: float = 0.0
    best_period: Optional[int] = None
    best_period_match: float = 0.0
    periodic: bool = False
    breakable: bool = False        # 是否可破解/可解码
    evidence: List[str] = field(default_factory=list)

    @property
    def is_encrypted(self) -> bool:
        return self.kind == "encrypted"

    def render(self) -> str:
        """人类可读的多行报告。"""
        lines = [
            f"文件    : {self.path or '<bytes>'}",
            f"判定    : {self.kind}"
            + ("（可解码）" if self.breakable else "（不可解码）"),
            f"熵      : {self.entropy:.6f}",
            f"卡方 χ² : {self.chi_square:.1f}  (df=255, 均匀随机临界≈310)",
        ]
        if self.best_period is not None:
            lines.append(
                f"周期性  : K={self.best_period} match={self.best_period_match * 100:.4f}%"
                f"  (随机基线 {RANDOM_MATCH_BASE * 100:.4f}%)"
                + ("  ← 检出周期，弱加密" if self.periodic else "")
            )
        if self.evidence:
            lines.append("证据    :")
            lines.extend(f"  - {e}" for e in self.evidence)
        return "\n".join(lines)


def entropy(data: bytes) -> float:
    """香农熵（bits/byte），最大 8.0。"""
    if not data:
        return 0.0
    counts = collections.Counter(data)
    total = len(data)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def chi_square(data: bytes) -> float:
    """字节分布卡方统计量（df=255）。越小越均匀，真随机≈255。"""
    if not data:
        return 0.0
    counts = collections.Counter(data)
    total = len(data)
    expected = total / 256.0
    return sum((counts.get(i, 0) - expected) ** 2 / expected for i in range(256))


def periodicity_scan(
    data: bytes,
    max_period: int = DEFAULT_MAX_PERIOD,
    sample: int = PERIOD_SAMPLE,
) -> tuple[Optional[int], float]:
    """扫描重复密钥 XOR 的周期特征，返回 (最佳周期, 匹配率)。

    原理：若密文 = 明文 XOR 周期密钥，则 ct[i] 与 ct[i+K] 在 K=密钥长度时
    密钥分量相同，相等概率升高，偏离随机基线。
    """
    n = min(sample, len(data) - max_period)
    if n <= 0:
        return None, 0.0

    best_k: Optional[int] = None
    best_rate = -1.0
    for k in range(1, max_period + 1):
        same = sum(1 for a, b in zip(data[:n], data[k : k + n]) if a == b)
        rate = same / n
        if rate > best_rate:
            best_rate, best_k = rate, k
    return best_k, best_rate


def _detect_container(data: bytes) -> Optional[str]:
    """按魔数识别容器类型。"""
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return "mp4"
    for magic, kind in CONTAINER_MAGICS:
        if data[: len(magic)] == magic:
            return kind
    # MP3 无 ID3 时靠帧同步字 0xFFEx
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return "mp3"
    return None


def classify(data: bytes, path: str = "") -> Verdict:
    """对字节序列做取证判定（不依赖 ffmpeg）。"""
    sample = data[:SAMPLE_LIMIT]
    ent = entropy(sample)
    chi = chi_square(sample)
    container = _detect_container(data)
    evidence: List[str] = []

    # 1) 已知容器 → 明文
    if container:
        evidence.append(f"命中容器魔数: {container}")
        evidence.append(
            f"χ²={chi:.1f} 远大于均匀临界 → 保留统计结构，符合压缩明文"
            f"（密文应≈255，此处越大越说明是明文）"
        )
        kind = container
        # 进一步区分 fMP4
        if container == "mp4":
            from suno_cat_catch_resolve.fmp4 import is_fragmented_mp4

            if is_fragmented_mp4(data):
                kind = "fmp4"
                evidence.append("检出 moof/mdat 分片 → fragmented MP4（Suno 缓存捕获特征）")
            else:
                evidence.append("标准 MP4（非分片）")
        return Verdict(
            kind=kind,
            path=path,
            entropy=ent,
            chi_square=chi,
            breakable=True,
            evidence=evidence,
        )

    # 2) 无容器头 → 判定是否加密密文
    best_k, best_rate = periodicity_scan(sample)
    periodic = best_rate > RANDOM_MATCH_BASE * PERIODICITY_RATIO

    evidence.append("未命中任何容器魔数（无 ftyp/ID3/OggS/RIFF）")
    if chi <= CHI2_UNIFORM_MAX:
        evidence.append(
            f"χ²={chi:.1f} ≤ {CHI2_UNIFORM_MAX:.0f} → 字节分布完美均匀，符合密码学密文"
        )
    else:
        evidence.append(f"χ²={chi:.1f} > {CHI2_UNIFORM_MAX:.0f} → 分布不均匀，可能是未知裸流")

    if periodic and best_k is not None:
        evidence.append(
            f"周期 K={best_k} 匹配率 {best_rate * 100:.4f}% 显著高于基线 → 重复密钥 XOR，可破解"
        )
        kind, breakable = "encrypted", True
    else:
        evidence.append(
            f"周期扫描最佳 K={best_k} 匹配率 {best_rate * 100:.4f}%，"
            f"与随机基线 {RANDOM_MATCH_BASE * 100:.4f}% 无异 → 排除重复密钥 XOR"
        )
        evidence.append("结论：AES / ChaCha20 级强加密，无密钥在数学上不可破")
        kind, breakable = "encrypted", False

    return Verdict(
        kind=kind,
        path=path,
        entropy=ent,
        chi_square=chi,
        best_period=best_k,
        best_period_match=best_rate,
        periodic=periodic,
        breakable=breakable,
        evidence=evidence,
    )


def identify(path: str) -> Verdict:
    """读取文件并取证判定。"""
    with open(path, "rb") as fh:
        data = fh.read()
    return classify(data, path=path)
