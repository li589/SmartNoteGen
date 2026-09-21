"""乐谱子系统：多轨谱面生成（中间表示 → 排版 → 五线谱 / 简谱 / MusicXML / 位图）。

分层
----
- ``theory``  纯乐理函数：调号、音名拼写、时值分解。
- ``model``   乐谱中间表示：从 MidiDocument / NoteSequence 解析出多轨谱面数据。
- ``layout``  排版引擎：行断开 + 行内定位 + 符干/连杠/加线几何。
- ``drawing`` 共享绘制层：一次记录指令流，分别序列化为 SVG 与 PNG（保证两者几何同源）。
- ``svg``     五线谱 SVG 渲染（零依赖，离线可看）。
- ``jianpu``  简谱（数字谱）文本 / SVG / PNG 渲染。
- ``png``     五线谱位图输出（Pillow，**惰性导入**：不装 Pillow 也能用 SVG）。
- ``musicxml`` MusicXML 4.0 导出（**纯标准库**手写，好处见该模块文档）。

本模块只做「入口聚合」，具体实现分散在上述子模块，避免循环导入。
聚合在这里的名字即公开 API；子模块内的私有辅助（``_`` 前缀）不在此列出。
"""

from __future__ import annotations

from smartnotegen.score.jianpu import (
    JianpuRenderer,
    JpMeasure,
    JpOptions,
    JpRow,
    JpScore,
    JpToken,
    parse_jianpu,
    render_jianpu_png,
    render_jianpu_svg,
    to_jianpu_lines,
    write_jianpu_png,
    write_jianpu_svg,
)
from smartnotegen.score.layout import (
    LayoutOptions,
    LaidCluster,
    LaidMeasure,
    LaidNote,
    LaidStaff,
    ScoreLayout,
    System,
    layout_score,
)
from smartnotegen.score.model import Score, ScoreMeasure, ScoreNote, ScoreTrack
from smartnotegen.score.musicxml import (
    MusicXmlOptions,
    render_musicxml,
    validate_musicxml,
    write_musicxml,
)
from smartnotegen.score.png import render_png, write_png
from smartnotegen.score.svg import (
    SvgOptions,
    SvgTheme,
    render_svg,
    required_indent,
    signature_area_width,
    write_svg,
)

__all__ = [
    "JianpuRenderer",
    "JpMeasure",
    "JpOptions",
    "JpRow",
    "JpScore",
    "JpToken",
    "LayoutOptions",
    "LaidCluster",
    "LaidMeasure",
    "LaidNote",
    "LaidStaff",
    "MusicXmlOptions",
    "Score",
    "ScoreLayout",
    "ScoreMeasure",
    "ScoreNote",
    "ScoreTrack",
    "SvgOptions",
    "SvgTheme",
    "System",
    "layout_score",
    "parse_jianpu",
    "render_jianpu_png",
    "render_jianpu_svg",
    "render_musicxml",
    "render_png",
    "render_svg",
    "required_indent",
    "signature_area_width",
    "to_jianpu_lines",
    "validate_musicxml",
    "write_jianpu_png",
    "write_jianpu_svg",
    "write_musicxml",
    "write_png",
    "write_svg",
]
