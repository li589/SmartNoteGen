"""共享绘制层：一次记录绘制指令，分别序列化为 SVG 与位图（PNG）。

为什么要有这一层
----------------
SVG 与 PNG 必须是**同一份几何的两个序列化器**。若各自实现一套绘图逻辑，两者必然漂移
（改好了 SVG 忘了 PNG），而 PNG 又无法用文本断言来验证——漂移会静默留在产物里。
所以这里把「画什么」（``Canvas`` 记录的指令流）与「怎么输出」（``to_svg`` / ``to_png``）
彻底分开：五线谱与简谱渲染器都只往 ``Canvas`` 里画，输出格式由调用方挑。

两个序列化器
------------
- ``to_svg``：纯字符串拼装，零依赖，字节级可断言（测试就靠它）。
- ``to_png``：Pillow 光栅化。**惰性导入**——不装 Pillow 也能用 SVG（P0 环境不被拖累）。
  Pillow 的 ``ImageDraw`` 没有抗锯齿，故走**超采样**（先按 ``scale`` 倍画，再 LANCZOS 缩回）。

坐标系与 SVG 一致：页面坐标，y 向下为正，原点在左上角。
"""

from __future__ import annotations

import math
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

__all__ = [
    "Canvas",
    "Op",
    "parse_color",
    "to_png",
    "to_svg",
]


# ---------------------------------------------------------------------------
# 指令流
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Op:
    """一条绘制指令。``data`` 的字段含义按 ``kind`` 解释（见各 ``Canvas`` 方法）。"""

    kind: str
    data: Tuple[Any, ...]


class Canvas:
    """绘制指令累积器。

    不产生任何输出格式的字符串，只记录结构化指令；坐标保持浮点原值，
    格式化交给序列化器（否则 PNG 拿不到精度）。
    """

    def __init__(self) -> None:
        self._frames: List[List[Op]] = [[]]

    # -- 基本图元 --------------------------------------------------------

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float, color: str) -> None:
        """直线（方头，避免小节线出头）。"""
        self._emit(Op("line", (x1, y1, x2, y2, width, color)))

    def rect(self, x: float, y: float, w: float, h: float, fill: str) -> None:
        """实心矩形。"""
        self._emit(Op("rect", (x, y, w, h, fill)))

    def path(
        self, d: str, fill: str, stroke: Optional[str] = None,
        stroke_width: float = 0.0, transform: Optional[str] = None,
    ) -> None:
        """路径。``fill`` 传 ``"none"`` 表示只描边（与 SVG 语义一致）。"""
        self._emit(Op("path", (d, fill, stroke, stroke_width, transform)))

    def ellipse(
        self, cx: float, cy: float, rx: float, ry: float, rotate: float,
        fill: str, stroke: Optional[str] = None, stroke_width: float = 0.0,
    ) -> None:
        """旋转椭圆（符头）。"""
        self._emit(Op("ellipse", (cx, cy, rx, ry, rotate, fill, stroke, stroke_width)))

    def circle(self, cx: float, cy: float, r: float, fill: str) -> None:
        """实心圆。"""
        self._emit(Op("circle", (cx, cy, r, fill)))

    def text(
        self, x: float, y: float, content: str, size: float, color: str, family: str,
        anchor: str = "start", weight: str = "normal", style: str = "normal",
    ) -> None:
        """文本。``(x, y)`` 是**基线**起点（与 SVG 一致），``anchor`` 同 SVG 取值。"""
        self._emit(Op("text", (x, y, content, size, color, family, anchor, weight, style)))

    # -- 变换组 ----------------------------------------------------------

    @contextmanager
    def group(self, transform: str) -> Iterator["Canvas"]:
        """变换组：块内指令被包进 ``<g transform=...>``，PNG 侧则整体施加同一变换。

        用上下文管理器而不是「传一段已渲染好的标记」，是为了让指令流保持结构化——
        否则 PNG 侧拿到的是一坨 SVG 字符串，等于又得解析回来。
        """
        frame: List[Op] = []
        self._frames.append(frame)
        try:
            yield self
        finally:
            self._frames.pop()
            self._emit(Op("group", (transform, tuple(frame))))

    # -- 读取 ------------------------------------------------------------

    def _emit(self, op: Op) -> None:
        self._frames[-1].append(op)

    @property
    def ops(self) -> Tuple[Op, ...]:
        """顶层指令序列。"""
        return tuple(self._frames[0])

    def __len__(self) -> int:
        """顶层指令条数（不含组内子指令）。"""
        return len(self._frames[0])


# ---------------------------------------------------------------------------
# SVG 序列化
# ---------------------------------------------------------------------------


def _xml_escape(content: str) -> str:
    """转义 XML 敏感字符。"""
    return content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _op_to_svg(op: Op) -> str:
    """把一条指令序列化为 SVG 标记（单行，便于测试做行级断言）。"""
    if op.kind == "line":
        x1, y1, x2, y2, width, color = op.data
        return (
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="{color}" stroke-width="{width:.3f}"/>'
        )
    if op.kind == "rect":
        x, y, w, h, fill = op.data
        return f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" fill="{fill}"/>'
    if op.kind == "circle":
        cx, cy, r, fill = op.data
        return f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.3f}" fill="{fill}"/>'
    if op.kind == "ellipse":
        cx, cy, rx, ry, rotate, fill, stroke, stroke_width = op.data
        extra = f' stroke="{stroke}" stroke-width="{stroke_width:.3f}"' if stroke else ""
        return (
            f'<ellipse cx="0" cy="0" rx="{rx:.3f}" ry="{ry:.3f}" fill="{fill}"{extra} '
            f'transform="translate({cx:.2f},{cy:.2f}) rotate({rotate:.1f})"/>'
        )
    if op.kind == "path":
        d, fill, stroke, stroke_width, transform = op.data
        extra = ""
        if stroke:
            extra = (
                f' stroke="{stroke}" stroke-width="{stroke_width:.3f}"'
                ' stroke-linecap="round" stroke-linejoin="round"'
            )
        if transform:
            extra += f' transform="{transform}"'
        return f'<path d="{d}" fill="{fill}"{extra}/>'
    if op.kind == "text":
        x, y, content, size, color, family, anchor, weight, style = op.data
        return (
            f'<text x="{x:.2f}" y="{y:.2f}" font-family="{family}" font-size="{size:.2f}" '
            f'fill="{color}" text-anchor="{anchor}" font-weight="{weight}" '
            f'font-style="{style}">{_xml_escape(content)}</text>'
        )
    if op.kind == "group":
        transform, children = op.data
        return f'<g transform="{transform}">{"".join(_op_to_svg(c) for c in children)}</g>'
    raise ValueError(f"未知绘制指令: {op.kind}")  # pragma: no cover - 内部枚举封闭


def to_svg(
    ops: Sequence[Op], width: float, height: float, background: str,
    *, extra_defs: str = "",
) -> str:
    """把指令流序列化为完整 SVG 文档。

    Args:
        ops: ``Canvas.ops``。
        width: 页面宽（像素，即用户单位）。
        height: 页面高。
        background: 底色（如 ``"#ffffff"``）。
        extra_defs: 追加在根元素内的原始标记（如 ``<style>``），留给上层扩展。

    Returns:
        完整 SVG 文本。
    """
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.1f} {height:.1f}" '
        f'width="{width:.1f}" height="{height:.1f}">'
    )
    body = [_op_to_svg(op) for op in ops]
    return "\n".join(
        [head, f'<rect width="{width:.1f}" height="{height:.1f}" fill="{background}"/>',
         *([extra_defs] if extra_defs else []), *body, "</svg>"]
    )


# ---------------------------------------------------------------------------
# 位图序列化（Pillow，惰性导入）
# ---------------------------------------------------------------------------

#: SVG 路径指令：命令字母 + 随后的数字串
_PATH_CMD_RE = re.compile(r"([MLCQZmlcqz])([^MLCQZmlcqz]*)")
_NUMBER_RE = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")
_TRANSFORM_RE = re.compile(r"(translate|scale)\s*\(([^)]*)\)")

#: 正文字体候选（按平台与优先级）。可用环境变量 ``SMARTNOTEGEN_SCORE_FONT`` 覆盖。
_FONT_CANDIDATES: Tuple[str, ...] = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
)
_FONT_CANDIDATES_BOLD: Tuple[str, ...] = (
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)


def parse_color(value: str) -> Optional[Tuple[int, int, int]]:
    """把 ``#rrggbb`` / ``none`` 解析为 RGB 三元组（``none`` 返回 None）。"""
    if not value or value == "none":
        return None
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:  # pragma: no cover - 主题常量只有 #rrggbb
        raise ValueError(f"无法解析颜色: {value}")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _parse_transform(transform: Optional[str]) -> Tuple[float, float, float, float]:
    """把 ``translate(x,y) scale(s)`` 解析为 ``(sx, sy, tx, ty)``（缺省恒等）。"""
    sx = sy = 1.0
    tx = ty = 0.0
    if not transform:
        return sx, sy, tx, ty
    for name, raw in _TRANSFORM_RE.findall(transform):
        values = [float(v) for v in _NUMBER_RE.findall(raw)]
        if name == "translate":
            tx += values[0] if values else 0.0
            ty += values[1] if len(values) > 1 else 0.0
        else:
            sx *= values[0] if values else 1.0
            sy *= values[1] if len(values) > 1 else values[0] if values else 1.0
    return sx, sy, tx, ty


def _flatten_path(d: str, transform: Optional[str]) -> List[Tuple[List[Tuple[float, float]], bool]]:
    """把 SVG 路径数据展平为若干「折线 + 是否闭合」。

    只支持本项目字形用到的 ``M / L / C / Q / Z``（含隐式重复坐标）。
    贝塞尔按弦长自适应细分，避免大曲线上出现可见折角。
    """
    sx, sy, tx, ty = _parse_transform(transform)

    def apply(px: float, py: float) -> Tuple[float, float]:
        return px * sx + tx, py * sy + ty

    subpaths: List[Tuple[List[Tuple[float, float]], bool]] = []
    points: List[Tuple[float, float]] = []
    closed = False
    start: Optional[Tuple[float, float]] = None
    cursor = (0.0, 0.0)

    def flush() -> None:
        nonlocal points, closed
        if len(points) >= 2:
            subpaths.append((points, closed))
        points, closed = [], False

    for cmd, raw in _PATH_CMD_RE.findall(d):
        upper = cmd.upper()
        values = [float(v) for v in _NUMBER_RE.findall(raw)]
        if upper == "Z":
            closed = True
            flush()
            if start is not None:
                cursor = start
            continue
        if upper == "M":
            flush()
            if len(values) >= 2:
                cursor = (values[0], values[1])
                start = cursor
                points = [apply(*cursor)]
            for i in range(2, len(values) - 1, 2):
                cursor = (values[i], values[i + 1])
                points.append(apply(*cursor))
            continue
        if upper == "L":
            for i in range(0, len(values) - 1, 2):
                cursor = (values[i], values[i + 1])
                points.append(apply(*cursor))
            continue
        if upper == "C":
            for i in range(0, len(values) - 5, 6):
                p1 = apply(values[i], values[i + 1])
                p2 = apply(values[i + 2], values[i + 3])
                end = apply(values[i + 4], values[i + 5])
                points.extend(_flatten_cubic(apply(*cursor), p1, p2, end))
                cursor = (values[i + 4], values[i + 5])
            continue
        if upper == "Q":
            for i in range(0, len(values) - 3, 4):
                ctrl = apply(values[i], values[i + 1])
                end = apply(values[i + 2], values[i + 3])
                points.extend(_flatten_quadratic(apply(*cursor), ctrl, end))
                cursor = (values[i + 2], values[i + 3])
    flush()
    return subpaths


def _segments_for(p0: Tuple[float, float], p3: Tuple[float, float]) -> int:
    """按两端点距离决定细分段数（约每 2 像素一段）。"""
    span = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
    return max(6, min(48, int(span / 2) + 1))


def _flatten_cubic(
    p0: Tuple[float, float], p1: Tuple[float, float],
    p2: Tuple[float, float], p3: Tuple[float, float],
) -> List[Tuple[float, float]]:
    """三次贝塞尔 -> 折线（不含起点）。"""
    count = _segments_for(p0, p3)
    out = []
    for i in range(1, count + 1):
        t = i / count
        u = 1.0 - t
        out.append((
            u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
            u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
        ))
    return out


def _flatten_quadratic(
    p0: Tuple[float, float], ctrl: Tuple[float, float], p1: Tuple[float, float]
) -> List[Tuple[float, float]]:
    """二次贝塞尔 -> 折线（不含起点）。"""
    count = _segments_for(p0, p1)
    out = []
    for i in range(1, count + 1):
        t = i / count
        u = 1.0 - t
        out.append((
            u * u * p0[0] + 2 * u * t * ctrl[0] + t * t * p1[0],
            u * u * p0[1] + 2 * u * t * ctrl[1] + t * t * p1[1],
        ))
    return out


def _ellipse_points(
    cx: float, cy: float, rx: float, ry: float, rotate_deg: float, count: int = 72
) -> List[Tuple[float, float]]:
    """旋转椭圆 -> 多边形顶点。"""
    theta = math.radians(rotate_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    out = []
    for i in range(count):
        phi = 2.0 * math.pi * i / count
        px, py = rx * math.cos(phi), ry * math.sin(phi)
        out.append((cx + px * cos_t - py * sin_t, cy + px * sin_t + py * cos_t))
    return out


_FONT_CACHE: Dict[Tuple[str, bool, int], Any] = {}


def _font_path(bold: bool) -> Optional[str]:
    """挑一个可用的字体文件。"""
    import os

    override = os.environ.get("SMARTNOTEGEN_SCORE_FONT")
    if override and os.path.exists(override):
        return override
    for candidate in (_FONT_CANDIDATES_BOLD if bold else _FONT_CANDIDATES):
        if os.path.exists(candidate):
            return candidate
    return None


def _load_font(size: float, bold: bool) -> Any:
    """加载并缓存字体；找不到字体文件时退化为 Pillow 内置位图字体。"""
    from PIL import ImageFont

    key = (str(_font_path(bold)), bold, int(round(size)))
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    path = key[0]
    font = None
    if path and path != "None":
        try:
            font = ImageFont.truetype(path, int(round(size)))
        except OSError:  # pragma: no cover - 字体文件损坏
            font = None
    if font is None:
        try:
            font = ImageFont.load_default(int(round(size)))
        except TypeError:  # pragma: no cover - Pillow < 10 无 size 参数
            font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def to_png(
    ops: Sequence[Op], width: float, height: float, background: str,
    *, scale: float = 2.0,
) -> bytes:
    """把指令流光栅化为 PNG 字节。

    实现要点：``ImageDraw`` 不做抗锯齿，故先按 ``scale`` 倍超采样绘制、
    再用 LANCZOS 缩回目标尺寸（默认 2 倍，等价于 2×2 SSAA）。

    Args:
        ops: ``Canvas.ops``。
        width: 目标宽（像素）。
        height: 目标高。
        background: 底色。
        scale: 超采样倍数，须 > 0。

    Returns:
        PNG 文件字节。

    Raises:
        ImportError: 未安装 Pillow。
    """
    if scale <= 0:
        raise ValueError(f"scale 必须为正数: {scale}")
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover - 仅在未装 Pillow 的环境触发
        raise ImportError(
            "PNG 输出需要 Pillow：pip install pillow（或改用 SVG / MusicXML，二者零依赖）"
        ) from exc

    factor = max(1, int(round(scale)))
    out_w = max(1, int(round(width)))
    out_h = max(1, int(round(height)))
    canvas = Image.new("RGB", (out_w * factor, out_h * factor), parse_color(background) or (255, 255, 255))
    drawer = ImageDraw.Draw(canvas)

    for op in ops:
        _draw_op(drawer, op, factor)

    if factor > 1:
        canvas = canvas.resize((out_w, out_h), Image.LANCZOS)

    import io

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _draw_op(drawer: Any, op: Op, factor: int) -> None:
    """把一条指令画进 Pillow 画布（``factor`` 为超采样倍数）。"""
    f = float(factor)
    if op.kind == "group":
        transform, children = op.data
        # 组变换在本项目里恒为 translate ∓ scale 的组合，逐个坐标换算即可，
        # 无需借助离屏图层（子元素都为同色系、无半透明叠加）。
        sx, sy, tx, ty = _parse_transform(transform)
        for child in children:
            _draw_op_transformed(drawer, child, factor, sx, sy, tx, ty)
        return
    if op.kind == "line":
        x1, y1, x2, y2, width, color = op.data
        drawer.line(
            [(x1 * f, y1 * f), (x2 * f, y2 * f)],
            fill=parse_color(color), width=max(1, int(round(width * f))),
        )
        return
    if op.kind == "rect":
        x, y, w, h, fill = op.data
        drawer.rectangle([x * f, y * f, (x + w) * f, (y + h) * f], fill=parse_color(fill))
        return
    if op.kind == "circle":
        cx, cy, r, fill = op.data
        drawer.ellipse(
            [(cx - r) * f, (cy - r) * f, (cx + r) * f, (cy + r) * f], fill=parse_color(fill)
        )
        return
    if op.kind == "ellipse":
        cx, cy, rx, ry, rotate, fill, stroke, stroke_width = op.data
        points = [(px * f, py * f) for px, py in _ellipse_points(cx, cy, rx, ry, rotate)]
        drawer.polygon(points, fill=parse_color(fill), outline=parse_color(stroke) if stroke else None)
        if stroke:
            drawer.line(
                points + [points[0]], fill=parse_color(stroke),
                width=max(1, int(round(stroke_width * f))), joint="curve",
            )
        return
    if op.kind == "path":
        d, fill, stroke, stroke_width, transform = op.data
        width_px = max(1, int(round(stroke_width * f)))
        # ``_flatten_path`` **已**把 ``transform`` 施加到每个点上（含贝塞尔控制点），
        # 这里只需再乘超采样倍数。若在此处又乘一遍 sx/tx，几何会被变换两次 ——
        # 谱号/变音字形就会画到页外，而 PNG 看不见，正是本层要防的漂移。
        for points, closed in _flatten_path(d, transform):
            scaled = [(x * f, y * f) for x, y in points]
            if parse_color(fill) is not None:
                drawer.polygon(scaled, fill=parse_color(fill))
            if stroke:
                outline = scaled + [scaled[0]] if closed else scaled
                drawer.line(outline, fill=parse_color(stroke), width=width_px, joint="curve")
                # SVG 侧描边是圆头圆角：折线拐点补圆点补齐端帽
                radius = width_px / 2.0
                for px, py in scaled:
                    drawer.ellipse(
                        [px - radius, py - radius, px + radius, py + radius],
                        fill=parse_color(stroke),
                    )
        return
    if op.kind == "text":
        x, y, content, size, color, _family, anchor, weight, _style = op.data
        bold = weight == "bold"
        font = _load_font(size * f, bold)
        # SVG 的 (x, y) 是基线；Pillow 需显式指定 "baseline 对齐 + 水平锚点"
        pillow_anchor = {"start": "ls", "middle": "ms", "end": "rs"}.get(anchor, "ls")
        kwargs: Dict[str, Any] = {}
        if bold and not _font_path(True):
            # 只有常规字重字体时，用同色描边做「合成加粗」
            kwargs["stroke_width"] = max(1, int(round(0.035 * size * f)))
            kwargs["stroke_fill"] = parse_color(color)
        drawer.text(
            (x * f, y * f), content, font=font, fill=parse_color(color),
            anchor=pillow_anchor, **kwargs,
        )
        return
    raise ValueError(f"未知绘制指令: {op.kind}")  # pragma: no cover - 内部枚举封闭


def _draw_op_transformed(
    drawer: Any, op: Op, factor: int, sx: float, sy: float, tx: float, ty: float
) -> None:
    """把组变换叠加进子指令的坐标后再绘制（组内不嵌套组）。"""
    data = op.data
    if op.kind == "line":
        x1, y1, x2, y2, width, color = data
        scaled = max(1, int(round(width * factor * (sx + sy) / 2.0)))
        drawer.line(
            [((x1 * sx + tx) * factor, (y1 * sy + ty) * factor),
             ((x2 * sx + tx) * factor, (y2 * sy + ty) * factor)],
            fill=parse_color(color), width=scaled,
        )
        return
    if op.kind == "circle":
        cx, cy, r, fill = data
        x, y = (cx * sx + tx) * factor, (cy * sy + ty) * factor
        radius = r * ((sx + sy) / 2.0) * factor
        drawer.ellipse([x - radius, y - radius, x + radius, y + radius], fill=parse_color(fill))
        return
    if op.kind == "path":
        inner = _parse_transform(data[4])
        _draw_op(
            drawer,
            Op("path", (
                data[0], data[1], data[2], data[3] * ((sx + sy) / 2.0),
                f"translate({tx:.6f},{ty:.6f}) scale({inner[0] * sx:.6f},{inner[1] * sy:.6f})",
            )),
            factor,
        )
        return
    if op.kind == "rect":
        x, y, w, h, fill = data
        _draw_op(
            drawer,
            Op("rect", ((x * sx + tx), (y * sy + ty), w * sx, h * sy, fill)),
            factor,
        )
        return
    if op.kind == "ellipse":
        cx, cy, rx, ry, rotate, fill, stroke, stroke_width = data
        _draw_op(
            drawer,
            Op("ellipse", (
                cx * sx + tx, cy * sy + ty, rx * sx, ry * sy, rotate,
                fill, stroke, stroke_width * ((sx + sy) / 2.0),
            )),
            factor,
        )
        return
    if op.kind == "text":
        x, y, content, size, color, family, anchor, weight, style = data
        _draw_op(
            drawer,
            Op("text", (x * sx + tx, y * sy + ty, content, size * ((sx + sy) / 2.0),
                        color, family, anchor, weight, style)),
            factor,
        )
        return
    raise ValueError(f"组变换不支持该指令: {op.kind}")  # pragma: no cover - 内部枚举封闭
