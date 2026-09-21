"""sunoauxtool.video 异常与错误码。

延续 SmartNoteGen 的错误码风格（0-9），新增：
  10 = ffmpeg 不可用
  11 = 分辨率/比例不支持
  12 = 输入音频缺失或无法读取
  13 = 渲染失败（ffmpeg 进程非零退出）
  14 = 输出路径不可写
"""

from __future__ import annotations

from typing import Optional


class VideoMakerError(Exception):
    """sunoauxtool.video 基础异常。"""

    def __init__(self, message: str, code: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class FFmpegNotFoundError(VideoMakerError):
    def __init__(self) -> None:
        super().__init__(
            "ffmpeg 未找到。请确保 ffmpeg 已安装并加入 PATH，"
            "或通过 --ffmpeg-path 指定绝对路径。",
            code=10,
        )


class ResolutionError(VideoMakerError):
    def __init__(self, msg: str) -> None:
        super().__init__(msg, code=11)


class AudioReadError(VideoMakerError):
    def __init__(self, path: str, cause: Optional[str] = None) -> None:
        detail = f"无法读取音频文件: {path}"
        if cause:
            detail += f" ({cause})"
        super().__init__(detail, code=12)


class RenderError(VideoMakerError):
    def __init__(self, msg: str, exit_code: Optional[int] = None) -> None:
        super().__init__(msg, code=13)
        self.exit_code = exit_code


class OutputWriteError(VideoMakerError):
    def __init__(self, path: str) -> None:
        super().__init__(f"输出路径不可写: {path}", code=14)
