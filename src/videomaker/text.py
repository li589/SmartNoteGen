"""文字与水印模块。

提供：
- drawtext：ffmpeg drawtext 滤镜封装
- watermark：半透明 logo 叠加
- subtitle：字幕样式控制

复用 SmartNoteGen 的 Config 中的文字配置。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TextParams:
    """文字参数。"""
    text: str
    font: str = ""
    font_size: int = 48
    font_color: str = "white"
    stroke_color: str = "black"
    stroke_width: int = 2
    x: str = "(w-text_w)/2"  # 水平居中
    y: str = "(h-text_h)/2"  # 垂直居中
    box: bool = False
    box_color: str = "black@0.5"
    box_border_width: int = 2


def build_drawtext(params: TextParams) -> str:
    """构建 ffmpeg drawtext 滤镜字符串。"""
    opts = []
    if params.text:
        # 转义特殊字符
        text = params.text.replace("'", "\\'")
        opts.append(f"text='{text}'")
    if params.font:
        opts.append(f"fontfile={params.font}")
    opts.append(f"fontsize={params.font_size}")
    opts.append(f"fontcolor={params.font_color}")
    opts.append(f"borderw={params.stroke_width}")
    opts.append(f"bordercolor={params.stroke_color}")
    opts.append(f"x={params.x}")
    opts.append(f"y={params.y}")
    if params.box:
        opts.append("box=1")
        opts.append(f"boxcolor={params.box_color}")
        opts.append(f"boxborderw={params.box_border_width}")
    return "drawtext=" + ",".join(opts)


def build_watermark(image_path: str, x: str = "10", y: str = "10") -> str:
    """构建水印叠加滤镜字符串。"""
    return f"[0:v][1:v]overlay={x}:{y}[vout]"
