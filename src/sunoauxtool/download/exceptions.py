"""Suno-Cat-Catch-Resolve 异常与错误码。

延续 SmartNoteGen 的错误码分段风格：
    sunoauxtool            0-9
    sunoauxtool.video              10-14
    Suno-Cat-Catch-Resolve  20-24
"""

from __future__ import annotations

from typing import Optional


class SunoError(Exception):
    """Suno-Cat-Catch-Resolve 基础异常。"""

    def __init__(self, message: str, code: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class FFmpegNotFoundError(SunoError):
    def __init__(self) -> None:
        super().__init__(
            "ffmpeg 未找到。按以下顺序任选一种修法：\n"
            "  1. 设置环境变量 SUNO_FFMPEG=<ffmpeg 可执行文件或其所在目录>\n"
            "  2. 把 ffmpeg 加入 PATH\n"
            "  3. 设置 SUNO_FFMPEG_DIRS=<目录1;目录2>（多目录用系统分隔符）\n"
            "  4. 传参 --ffmpeg-path / find_ffmpeg(path=...) 指定绝对路径",
            code=20,
        )


class NotFragmentedMP4Error(SunoError):
    def __init__(self, path: str, detail: Optional[str] = None) -> None:
        msg = f"不是可解析的 fragmented MP4: {path}"
        if detail:
            msg += f" ({detail})"
        super().__init__(msg, code=21)


class EncryptedBlobError(SunoError):
    """输入经取证判定为加密密文，无密钥不可解码。"""

    def __init__(self, path: str, entropy: float, chi_square: float) -> None:
        super().__init__(
            f"输入是加密密文，无密钥不可解码: {path}\n"
            f"  证据: 熵={entropy:.6f}（明文压缩音频约 7.99，密文逼近 8.0）\n"
            f"        卡方 χ²={chi_square:.1f}（df=255，均匀随机临界≈310，"
            f"越小越均匀）\n"
            f"  结论: 字节分布完美均匀且无周期性 → 排除重复密钥 XOR，"
            f"属 AES/ChaCha20 级强加密。\n"
            f"  建议: 改用「缓存捕获」得到的 fMP4（*.mp3 误标）文件，"
            f"它是同一首曲子的明文副本。",
            code=22,
        )


class TranscodeError(SunoError):
    def __init__(self, msg: str, exit_code: Optional[int] = None) -> None:
        super().__init__(msg, code=23)
        self.exit_code = exit_code


class OutputWriteError(SunoError):
    def __init__(self, path: str) -> None:
        super().__init__(f"输出路径不可写: {path}", code=24)
