"""位图（PNG）输出：把五线谱渲染器的绘制指令流光栅化。

设计
----
本模块**不重复实现任何排版逻辑**：它只做两件事 —— 让五线谱渲染器产生指令流
（``ScoreSvgRenderer.draw()``），再交给 ``drawing.to_png`` 光栅化。
因此 SVG 与 PNG 的几何永远是同一份，不存在「改了 SVG 忘了 PNG」的漂移。

依赖
----
Pillow（``requirements/base.txt`` 已声明）。**惰性导入**：只有真正调用 PNG 时才 import，
故不装 Pillow 的环境照常可用 SVG / 简谱文本。缺依赖时抛出带安装指引的 ``ImportError``。

分辨率
------
``scale`` 是**内部超采样倍数**（默认 2.0），**不改变输出像素尺寸**：输出恒为
``(page_width, page_height)`` 取整后的像素，只是先按 ``scale`` 倍放大绘制再 LANCZOS
缩回，等效 ``scale × scale`` 抗锯齿（``ImageDraw`` 自身不做 AA）。调大它换来更干净的
边缘，而不是更大的图。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from sunoauxtool.score.drawing import to_png
from sunoauxtool.score.layout import ScoreLayout
from sunoauxtool.score.svg import ScoreSvgRenderer, SvgOptions

__all__ = [
    "render_png",
    "write_png",
]


def render_png(
    layout: ScoreLayout, options: Optional[SvgOptions] = None, *, scale: float = 2.0
) -> bytes:
    """把五线谱排版结果渲染为 PNG 字节。

    Args:
        layout: ``layout_score()`` 的产物。
        options: 与 SVG 完全相同的渲染选项（主题、标题、开关）。
        scale: 超采样倍数，须 > 0（默认 2.0）。

    Returns:
        PNG 文件字节。

    Raises:
        ImportError: 未安装 Pillow。
        ValueError: ``scale`` 非正。
    """
    opts = options or SvgOptions()
    renderer = ScoreSvgRenderer(layout, opts)
    canvas = renderer.draw()
    return to_png(
        canvas.ops, layout.page_width, layout.page_height, opts.theme.paper, scale=scale
    )


def write_png(
    layout: ScoreLayout, path: str | Path,
    options: Optional[SvgOptions] = None, *, scale: float = 2.0,
) -> str:
    """渲染并落盘 ``.png``，返回绝对路径。"""
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(render_png(layout, options, scale=scale))
    return str(target)
