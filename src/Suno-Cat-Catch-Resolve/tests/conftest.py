"""pytest 配置：让 tests 在「未安装本包」时也能 import。

本包是 src/ 下的独立 editable 兄弟包，目录名含连字符
（`Suno-Cat-Catch-Resolve`），而可导入包名是 `suno_cat_catch_resolve`。
因此把**子项目根**（不是 repo 的 src/）插进 sys.path。

同时把 pytest 临时根重定向到项目内 —— 与仓库根 conftest.py 同一原因：
沙箱下系统 Temp 不可用，且 tmp_path_retention=all 禁止会话结束后删除。
"""

from __future__ import annotations

import random
import struct
import sys
from pathlib import Path

import pytest

SUBROOT = Path(__file__).resolve().parent.parent
if str(SUBROOT) not in sys.path:
    sys.path.insert(0, str(SUBROOT))


def pytest_configure(config):
    if not config.option.basetemp:
        import time

        base = SUBROOT / ".pytest_tmp" / f"s{int(time.time() * 1000)}"
        base.parent.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(base)


# -- 合成 ISO BMFF 样本 -----------------------------------------------------

def box(atom_type: bytes, payload: bytes) -> bytes:
    """构造一个 32 位长度的原子：4 字节长度 + 4 字节类型 + 载荷。"""
    return struct.pack(">I", len(payload) + 8) + atom_type + payload


@pytest.fixture
def make_fmp4():
    """返回构造 fragmented MP4 字节串的工厂。"""

    def _make(mdat_payloads=(b"\x11" * 64,), ftyp: bytes = b"isom\x00\x00\x02\x00isomiso2mp41"):
        data = box(b"ftyp", ftyp)
        data += box(b"moov", b"\x00" * 16)
        for payload in mdat_payloads:
            data += box(b"moof", b"\x01" * 12)
            data += box(b"mdat", payload)
        return data

    return _make


@pytest.fixture
def fmp4_bytes(make_fmp4):
    """一份最小的可解析 fMP4。"""
    return make_fmp4()


@pytest.fixture
def fmp4_file(tmp_path, make_fmp4):
    """落盘的 fMP4，故意命名为 .mp3（复刻 Suno 缓存捕获的误标场景）。"""
    p = tmp_path / "Suno _ AI Music.mp3"
    p.write_bytes(make_fmp4())
    return p


@pytest.fixture
def encrypted_bytes():
    """确定性的「密文」样本：均匀随机字节（χ²≈255）。

    用固定种子而非 os.urandom，保证 χ² 在跨平台/跨运行时稳定落在
    密文判据区间（≤360），不会偶发翻转测试结果。
    """
    return random.Random(1234).randbytes(1_000_000)


@pytest.fixture
def encrypted_file(tmp_path, encrypted_bytes):
    """落盘的密文样本，UUID 命名（复刻猫抓直下的 *.m4a）。"""
    p = tmp_path / "a1b2c3d4-0000-1111-2222-333344445555.m4a"
    p.write_bytes(encrypted_bytes)
    return p
