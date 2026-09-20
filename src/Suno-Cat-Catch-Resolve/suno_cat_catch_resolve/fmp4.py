"""MP4 / fragmented MP4 原子解析。

ISO BMFF 结构：每个原子 = 4 字节大端长度 + 4 字节类型 + 载荷。
特例：长度=1 表示后续 8 字节是 64 位真实长度（头部 16 字节）；
      长度=0 表示原子延伸到文件末尾。

Suno 缓存捕获产物是 fMP4：
    ftyp + moov + N × (moof + mdat)
其中 mdat 载荷拼起来就是原始 Opus 帧数据（明文）。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterator, List

FTYP_MAGICS = (b"ftyp",)
FRAGMENT_ATOMS = (b"moof", b"mdat")


@dataclass
class Atom:
    """一个 ISO BMFF 原子。"""

    type: str
    offset: int
    size: int          # 原子总长度（含头部）
    header_size: int   # 8 或 16

    @property
    def payload_offset(self) -> int:
        return self.offset + self.header_size

    @property
    def payload_size(self) -> int:
        return max(0, self.size - self.header_size)


def parse_atoms(data: bytes) -> List[Atom]:
    """顺序解析顶层原子。遇到非法结构即停止（不抛异常，返回已解析部分）。"""
    atoms: List[Atom] = []
    offset = 0
    total = len(data)

    while offset + 8 <= total:
        (size,) = struct.unpack(">I", data[offset : offset + 4])
        atype = data[offset + 4 : offset + 8]
        header_size = 8

        if size == 1:
            if offset + 16 > total:
                break
            (size,) = struct.unpack(">Q", data[offset + 8 : offset + 16])
            header_size = 16
        elif size == 0:
            size = total - offset

        # 类型必须是可打印 ASCII，否则认为结构已损坏/不是 MP4
        if not all(0x20 <= b <= 0x7E for b in atype):
            break

        atoms.append(Atom(atype.decode("latin1"), offset, size, header_size))

        if size < 8:
            break
        offset += size

    return atoms


def is_fragmented_mp4(data: bytes) -> bool:
    """是否是可解析的 fragmented MP4（含 ftyp 且至少一组 moof/mdat）。"""
    atoms = parse_atoms(data)
    types = {a.type for a in atoms}
    return "ftyp" in types and "moof" in types and "mdat" in types


def iter_mdat(data: bytes) -> Iterator[bytes]:
    """按出现顺序产出每个 mdat 原子的载荷（不含头部）。"""
    for atom in parse_atoms(data):
        if atom.type == "mdat":
            yield data[atom.payload_offset : atom.payload_offset + atom.payload_size]


def concatenate_mdat(data: bytes) -> bytes:
    """把所有 mdat 载荷拼接成完整的原始音频码流。"""
    return b"".join(iter_mdat(data))


def summarize(data: bytes) -> dict:
    """返回结构摘要，便于诊断输出。"""
    atoms = parse_atoms(data)
    types = [a.type for a in atoms]
    mdat_total = sum(a.payload_size for a in atoms if a.type == "mdat")
    return {
        "atom_count": len(atoms),
        "atom_types": sorted(set(types)),
        "moof_count": types.count("moof"),
        "mdat_count": types.count("mdat"),
        "mdat_total_bytes": mdat_total,
        "container_overhead_bytes": len(data) - mdat_total,
    }
