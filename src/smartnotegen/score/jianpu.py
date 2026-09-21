"""简谱（数字谱）渲染：文本 / SVG / PNG 三种输出。

简谱与五线谱的本质差别
----------------------
五线谱要画「音高在谱表上的位置」，简谱只画「相对主音的第几级 + 高低八度点」，
所以简谱**不需要排版引擎与谱表几何**，直接从 ``Score`` 生成记号序列即可。
本模块因此不依赖 ``layout``，只依赖 ``model``（数据）与 ``theory``（乐理）。

记谱规则（本实现遵守的口径）
---------------------------
- **音级**：相对 ``1`` 的第 1..7 级；非本调音用 ``♯``/``♭`` 前缀标出（复用五线谱的矢量字形）。
  ``1`` 取调式主音，**小调取关系大调主音**（故小调主音记作 ``6``）——简谱惯例。
- **八度**：数字**上方**的点表示高八度、**下方**的点表示低八度，可叠加；文本模式用 ``'`` / ``,``。
- **时值**：一拍为「单位时值」（``beat_unit`` 决定，4/4 即四分音符）。
  - 整数拍：数字后跟 ``拍数-1`` 条延音横线（``5 - -`` 即三拍）；
  - 半拍及更短：数字下加下划线（1 条 = 八分，2 条 = 十六分…）；
  - 附点：数字后加点（半拍以下的附点值，或 1.5 拍这类带小数的一拍以上值）。
- **跨小节的长音**：延续片段若恰好是整数拍，写成横线（``5 - - | -``），
  这是简谱的固定写法，**不画弧**；若延续片段不足一拍（或带小数），
  必须重新写数字并用弧线（``⌒``）与前一记号相连。
- **休止符**：写 ``0``，时值记号规则与音符相同。
- **多声部**：``track.voices`` 有几层就排几行，各行的数字**按列对齐**。

输出
----
- ``to_jianpu_lines()``：等宽文本，适合 CLI 直接打印。
- ``render_jianpu_svg()`` / ``render_jianpu_png()``：带标题、速度、调号声明的谱页。
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from smartnotegen.score.drawing import Canvas, to_png, to_svg
from smartnotegen.score.model import Score
from smartnotegen.score.svg import (
    ACCIDENTAL_DY,
    ACCIDENTAL_STROKES,
    SvgTheme,
    draw_tempo_mark,
    tempo_mark_width,
)
from smartnotegen.score.theory import (
    BEAMS,
    beat_unit,
    duration_components,
    normalize_key,
    prefer_flats,
    relative_major,
    spell_pitch,
)

__all__ = [
    "JianpuRenderer",
    "JpMeasure",
    "JpOptions",
    "JpRow",
    "JpScore",
    "JpToken",
    "parse_jianpu",
    "render_jianpu_png",
    "render_jianpu_svg",
    "to_jianpu_lines",
    "write_jianpu_png",
    "write_jianpu_svg",
]

_EPS = 1e-6

#: 音名首字母 -> 半音数（用于从调名求出主音的 MIDI 值）
_LETTER_SEMITONE: Dict[str, int] = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

#: 与五线谱相同的正文字体栈
DEFAULT_FONT = "Georgia, 'Times New Roman', 'Songti SC', serif"

#: 表头各行相对页顶的偏移（单位：字号）。首系统从 ``header_height`` 起排。
TITLE_BASELINE = 1.6
COMPOSER_BASELINE = 3.1
KEY_BASELINE = 5.0
SUMMARY_BASELINE = 6.0        # 仅窄页折行时使用
HEADER_DESCENDER = 0.8        # 末行基线之下还需的余量
HEADER_TEXT_RATIO = 0.92      # 调号/速度文字相对字号的占比
SUMMARY_RATIO = 0.78          # 右侧摘要相对字号的占比


def _text_em(content: str) -> float:
    """文本宽度的粗略估算（单位：字号）：全角/CJK 记 1.0，其余记 0.55。

    只用来判断「同一行放不放得下」，不追求度量精度 —— 目标是消除表头左右两块相撞，
    不像素级对齐，因此刻意不引入字体度量依赖（PNG 侧本来也拿不到一致的度量）。
    """
    return sum(1.0 if ord(ch) > 0x2E80 else 0.55 for ch in content)


# ---------------------------------------------------------------------------
# 记号模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JpToken:
    """简谱里的一个横向占位：数字（含休止符）或延音横线。"""

    kind: str                     # "note"（含休止符）或 "dash"
    degree: int = 0               # 1..7；休止符为 0；dash 无意义
    accidental: int = 0           # -1 降 / 0 无 / +1 升
    octave: int = 0               # >0 上方点个数，<0 下方点个数
    underscores: int = 0          # 下划线数量（1=八分，2=十六分…）
    dots: int = 0                 # 附点数量
    #: 与**下一个非横线记号**之间画弧（同音被写着两个数字时的连音线）。
    #: 只标在数字上；中间夹的延音横线属于同一音的时值延伸，弧线要跨过去。
    slur_to_next: bool = False

    @property
    def is_rest(self) -> bool:
        """是否休止符。"""
        return self.kind == "note" and self.degree == 0


@dataclass
class JpMeasure:
    """一行简谱里的一个小节。"""

    index: int
    tokens: List[JpToken] = field(default_factory=list)


@dataclass
class JpRow:
    """一行简谱（一个轨的一个声部）。"""

    track_index: int
    voice: int
    name: str
    measures: List[JpMeasure] = field(default_factory=list)


@dataclass
class JpScore:
    """整份简谱：若干行 + 表头信息。"""

    score: Score
    rows: List[JpRow] = field(default_factory=list)
    #: ``1 =`` 后面的调名。**小调时为关系大调**（小调按简谱惯例记作 la 为主音）。
    tonic: str = "C"
    mode: str = "major"
    #: 原始小调主音（仅 ``mode == "minor"`` 时有值，供表头括注「以 6 为主音」）。
    minor_tonic: str = ""
    flats: bool = False

    @property
    def beat_unit(self) -> float:
        """单位时值对应的拍数（4/4 为 1.0，6/8 为 0.5）。"""
        return beat_unit(self.score.time_signature)


# ---------------------------------------------------------------------------
# 选项
# ---------------------------------------------------------------------------


@dataclass
class JpOptions:
    """简谱排版参数（单位：像素）。"""

    page_width: float = 1240.0
    margin: float = 52.0
    note_size: float = 22.0
    slot: float = 30.0                  # 单个记号的横向步进
    measure_pad: float = 15.0           # 小节内两侧留白
    row_gap: float = 26.0               # 同系统内行距附加量
    system_gap: float = 34.0            # 系统间距
    header_gap: float = 14.0            # 表头末行到首系统之间的空隙
    max_slots_per_line: int = 32
    show_title: bool = True
    show_tempo: bool = True
    show_track_names: bool = True
    font_family: str = DEFAULT_FONT
    theme: SvgTheme = field(default_factory=SvgTheme)

    @property
    def row_height(self) -> float:
        """一行简谱的纵向占位（含八度点与下划线余量）。"""
        return self.note_size * 2.30 + self.row_gap


# ---------------------------------------------------------------------------
# Score -> 记号序列
# ---------------------------------------------------------------------------


def _tonic_pitch(tonic: str, octave: int = 4) -> int:
    """把调名主音（如 ``"Bb"``）换算为基准八度的 MIDI 值。"""
    letter = tonic[0].upper()
    rest = tonic[1:].lower()
    accidental = rest.count("#") + rest.count("♯") - rest.count("b") - rest.count("♭")
    return 12 * (octave + 1) + _LETTER_SEMITONE[letter] + accidental


def _dash() -> JpToken:
    """一条延音横线。"""
    return JpToken(kind="dash")


def _component_tokens(note_type: str, dots: int, value: float) -> List[JpToken]:
    """把一个时值分量转成记号（1 个数字 + 若干横线）。"""
    if value >= 1.0 - _EPS:
        whole = int(math.floor(value + 1e-9))
        frac = value - whole
        # 一拍及以上的附点值，简谱用横线表达整拍、用点表达那半个拍
        return [JpToken(kind="note", dots=1 if abs(frac - 0.5) < _EPS else 0)] + [
            _dash() for _ in range(max(0, whole - 1))
        ]
    return [JpToken(kind="note", underscores=BEAMS.get(note_type, 0), dots=dots)]


def _fragment_tokens(duration: float, *, continuation: bool) -> List[JpToken]:
    """把一个音符片段展开为记号序列。

    Args:
        duration: 片段时值（拍）。
        continuation: 该片段是否为前一音在小节线的延续（``tie_from_prev``）。

    Returns:
        记号序列。整数拍的延续片段退化为纯横线（简谱惯例）；其余按时值分量展开。
    """
    if continuation and abs(duration - round(duration)) < _EPS and duration >= 1.0 - _EPS:
        return [_dash() for _ in range(int(round(duration)))]
    tokens: List[JpToken] = []
    components = duration_components(duration)
    if not components:  # pragma: no cover - model 层已过滤非正时值
        return [_dash()]
    for index, (note_type, dots, value) in enumerate(components):
        part = _component_tokens(note_type, dots, value)
        # 同一音符被拆成多个分量时（如 2.5 拍 = 二分 + 八分），分量之间要画弧。
        # 弧标在**该分量的数字**上（而不是末尾的横线），由渲染层跨过横线连到下一分量。
        if index < len(components) - 1:
            part[0] = _replace(part[0], slur_to_next=True)
        tokens.extend(part)
    return tokens


def _replace(token: JpToken, **changes: object) -> JpToken:
    """``dataclasses.replace`` 的轻量包装（保持 frozen 语义）。"""
    return dataclasses.replace(token, **changes)  # type: ignore[arg-type]


def _degree_of(pitch: int, tonic_diatonic: int, flats: bool) -> Tuple[int, int, int]:
    """MIDI 音高 -> ``(音级 1..7, 八度偏移, 变音记号)``（相对调式主音）。"""
    _letter, diatonic, accidental = spell_pitch(pitch, flats)
    octave, index = divmod(diatonic - tonic_diatonic, 7)
    return index + 1, octave, accidental


def _voice_measures(
    track, voice: int, *, bars: int, tonic_diatonic: int, flats: bool
) -> List[JpMeasure]:
    """把某轨某声部的全部音符转成按小节分组的记号。

    必须**整行一起**处理（而不是逐小节）：跨小节的延续片段在下一小节里，
    只看得见本小节就无从判断「延续端是否重写了数字」，也就画不出连音线。
    """
    ordered = sorted(
        (n for n in track.notes if n.voice == voice), key=lambda n: (n.start, n.measure)
    )
    buckets: Dict[int, List[JpToken]] = {index: [] for index in range(1, bars + 1)}

    for position, note in enumerate(ordered):
        part = _fragment_tokens(note.duration, continuation=note.tie_from_prev)
        if note.is_rest:
            part = [_replace(tok, degree=0, accidental=0, octave=0) for tok in part]
        else:
            degree, octave, accidental = _degree_of(note.pitch, tonic_diatonic, flats)
            part = [
                _replace(tok, degree=degree, octave=octave, accidental=accidental)
                for tok in part
            ]
        # 本片后面还有延续端，且延续端**重写了数字**时才需要连音线；
        # 若延续端恰为整数拍（写成纯横线），简谱惯例不加弧。
        if part and not note.is_rest and note.tie_to_next and position + 1 < len(ordered):
            following = ordered[position + 1]
            rewrite = not (
                abs(following.duration - round(following.duration)) < _EPS
                and following.duration >= 1.0 - _EPS
            )
            if rewrite:
                part[0] = _replace(part[0], slur_to_next=True)
        bucket = buckets.get(note.measure)
        if bucket is not None:
            bucket.extend(part)

    return [JpMeasure(index=index, tokens=buckets[index]) for index in sorted(buckets)]


def parse_jianpu(score: Score, *, track_indices: Optional[Iterable[int]] = None) -> JpScore:
    """把 ``Score`` 解析为简谱记号结构。

    Args:
        score: 已装配的乐谱（``Score.from_sequence`` 等入口产出）。
        track_indices: 只渲染指定轨；None 表示全部。

    Returns:
        ``JpScore``；各行的小节数与 ``score.bars`` 一致。
    """
    key_tonic, mode = normalize_key(score.key)
    flats = prefer_flats(score.key)
    minor_tonic = ""
    tonic = key_tonic
    if mode == "minor":
        # 简谱记小调用关系大调作 1，主音落在 6 上；否则 ``1 = A`` 与「以 6 为主音」自相矛盾
        minor_tonic = key_tonic
        tonic = relative_major(key_tonic)
    tonic_diatonic = spell_pitch(_tonic_pitch(tonic), flats)[1]

    wanted = set(track_indices) if track_indices is not None else None
    rows: List[JpRow] = []
    for index, track in enumerate(score.tracks):
        if wanted is not None and index not in wanted:
            continue
        for voice in range(max(1, track.voices)):
            rows.append(
                JpRow(
                    track_index=index,
                    voice=voice,
                    name=track.name,
                    measures=_voice_measures(
                        track, voice,
                        bars=score.bars,
                        tonic_diatonic=tonic_diatonic,
                        flats=flats,
                    ),
                )
            )

    return JpScore(
        score=score, rows=rows, tonic=tonic, mode=mode,
        minor_tonic=minor_tonic, flats=flats,
    )


# ---------------------------------------------------------------------------
# 文本输出
# ---------------------------------------------------------------------------


def _token_text(token: JpToken) -> str:
    """单个记号的 ASCII 写法。``^`` 表示与下一个数字相连（连音线起点）。"""
    if token.kind == "dash":
        return "-"
    if token.degree == 0:
        body = "0"
    else:
        mark = {-1: "b", 1: "#"}.get(token.accidental, "")
        body = f"{mark}{token.degree}"
    body += "." * token.dots
    body += "'" * token.octave if token.octave > 0 else "," * (-token.octave)
    body += "_" * token.underscores
    if token.slur_to_next:
        body += "^"
    return body


def _cell_width(jp: JpScore) -> int:
    """文本模式下的记号定宽（取全谱最长记号，使各行小节能对齐）。"""
    longest = 1
    for row in jp.rows:
        for measure in row.measures:
            for token in measure.tokens:
                longest = max(longest, len(_token_text(token)))
    return longest


def to_jianpu_lines(
    source: Score | JpScore, options: Optional[JpOptions] = None
) -> List[str]:
    """渲染为等宽文本（适合 CLI 直接打印 / 存档）。

    记号写法：``#``/``b`` 前缀表变音；``'`` / ``,`` 表高低八度（可叠加）；
    ``.`` 附点；``_`` 下划线（八分起）；``-`` 延音横线；``^`` 与后一记号同音相连。
    小节之间用 ``|`` 分隔，曲末为 ``||``。

    Args:
        source: ``Score`` 或 ``parse_jianpu`` 的结果。
        options: 选项（文本模式只用到表头开关与行宽）。

    Returns:
        文本行列表。
    """
    opts = options or JpOptions()
    jp = source if isinstance(source, JpScore) else parse_jianpu(source)
    score = jp.score

    lines: List[str] = []
    head = f"1 = {jp.tonic}"
    if opts.show_tempo:
        head += f"   ♩ = {score.bpm}"
    head += f"   {score.time_signature}   {score.bars} 小节"
    if jp.mode == "minor":
        head += f"（{jp.minor_tonic or jp.tonic} 小调，以 6 为主音）"
    if opts.show_title and score.title:
        lines.append(score.title.center(max(len(head), 48)))
    lines.append(head)
    lines.append("")

    if not jp.rows:
        lines.append("（无音符）")
        return lines

    cell = _cell_width(jp)
    for row in jp.rows:
        prefix = ""
        if opts.show_track_names:
            label = row.name + (f".{row.voice}" if row.voice else "")
            prefix = f"{label:<14}"
        for offset, chunk in enumerate(_wrap_text_row(row, opts, cell)):
            lines.append(f"{prefix}{chunk}" if offset == 0 else " " * len(prefix) + chunk)
    return lines


def _wrap_text_row(row: JpRow, opts: JpOptions, cell: int) -> List[str]:
    """把一行简谱按行宽切成若干文本块（每小节以 ``|`` 收尾）。"""
    chunks: List[str] = []
    current = ""
    used = 0
    for measure in row.measures:
        if current and used + len(measure.tokens) > opts.max_slots_per_line:
            chunks.append(current.rstrip())
            current, used = "", 0
        cells = " ".join(f"{_token_text(t):<{cell}}" for t in measure.tokens)
        current += f"| {cells} "
        used += len(measure.tokens)
    if current:
        chunks.append(current.rstrip() + " |")
    return chunks or ["||"]


# ---------------------------------------------------------------------------
# SVG 渲染
# ---------------------------------------------------------------------------


class JianpuRenderer:
    """把 ``JpScore`` 画到画布（与五线谱共用绘制层，故 SVG / PNG 天然同源）。"""

    def __init__(self, jp: JpScore, options: Optional[JpOptions] = None) -> None:
        """初始化。

        Args:
            jp: ``parse_jianpu`` 的产物。
            options: 排版与主题选项。
        """
        self.jp = jp
        self.opts = options or JpOptions()
        self.theme = self.opts.theme
        self.canvas = Canvas()
        self.measure_widths: List[float] = []
        self.systems: List[List[int]] = []
        #: 每个系统的左右边界（x），跨系统连音线要用它画出/入两段
        self.system_span: List[Tuple[float, float]] = []
        #: row_offset -> system_index -> {(小节, 列): 记号中心 x}
        self._positions: List[Dict[int, Dict[Tuple[int, int], float]]] = []
        #: row_offset -> system_index -> 该行的基线 y
        self._baselines: List[Dict[int, float]] = []
        # 先排一次版：``page_height`` 依赖断行结果，若等到 ``draw()`` 才排，
        # 外部先读 ``page_height`` 会拿到偏小的值（页高少了系统间距）。
        self.plan()

    # -- 布局 ------------------------------------------------------------

    def _measure_slots(self) -> List[int]:
        """每个小节的列数（取各行最大值，保证行间按列对齐）。"""
        total = self.jp.score.bars
        out = []
        for index in range(total):
            columns = 1
            for row in self.jp.rows:
                if index < len(row.measures):
                    columns = max(columns, len(row.measures[index].tokens))
            out.append(columns)
        return out

    def _measure_width(self, slots: int) -> float:
        """小节宽度（含两侧留白）。"""
        return slots * self.opts.slot + 2 * self.opts.measure_pad

    def plan(self) -> Tuple[List[int], List[List[int]]]:
        """排出每小节宽度与断行方案。"""
        widths = [self._measure_width(s) for s in self._measure_slots()]
        self.measure_widths = widths
        available = self.opts.page_width - 2 * self.opts.margin
        systems: List[List[int]] = []
        current: List[int] = []
        used = 0.0
        for index, width in enumerate(widths):
            if current and used + width > available:
                systems.append(current)
                current, used = [], 0.0
            current.append(index)
            used += width
        if current or not systems:
            systems.append(current)
        self.systems = systems
        return widths, systems

    @property
    def page_height(self) -> float:
        """页面高度：表头 + 各系统。"""
        row_count = max(1, len(self.jp.rows))
        if not self.systems:
            return self.header_height() + self.opts.row_height * row_count
        height = self.header_height()
        for _system in self.systems:
            height += self.opts.row_height * row_count + self.opts.system_gap
        return height

    def summary_text(self) -> str:
        """表头右侧的摘要：轨名 + 拍号 + 小节数。"""
        score = self.jp.score
        summary = f"{score.time_signature}  ·  {score.bars} 小节"
        if not (self.opts.show_track_names and self.jp.rows):
            return summary
        names: List[str] = []
        for row in self.jp.rows:
            label = row.name + (f".{row.voice}" if row.voice else "")
            if label not in names:
                names.append(label)
        return "·".join(names) + "  |  " + summary

    def header_left_end_x(self) -> float:
        """「1 = C + 速度记号 + = 120」这条线画到多右。

        占位与相撞判断共用这一处公式，避免「判断按一种排法、实际画时按另一种」而漂移。
        """
        opts = self.opts
        size = opts.note_size
        end = opts.margin + _text_em(f"1 = {self.jp.tonic}") * HEADER_TEXT_RATIO * size
        if not opts.show_tempo:
            return end
        mark_right = end + 1.4 * size + tempo_mark_width(HEADER_TEXT_RATIO * size)
        return mark_right + 0.24 * size + _text_em(f"= {self.jp.score.bpm}") * HEADER_TEXT_RATIO * size

    def summary_stacked(self) -> bool:
        """摘要是否必须折到下一行（窄页时左侧速度记号会把同一行占满）。"""
        opts = self.opts
        needed = _text_em(self.summary_text()) * SUMMARY_RATIO * opts.note_size
        return (
            self.header_left_end_x() + 0.9 * opts.note_size + needed
            > opts.page_width - opts.margin
        )

    def header_height(self) -> float:
        """表头高度 = 页顶留白 + 各行基线跨度 + 末行下沿余量 + 到首系统的空隙。

        必须按**内容**算，不能写死：写死时表头文字会落进首系统的行间
        （``1 = C`` 挤在旋律行与低音行之间），窄页折行后更会压到谱面上。
        """
        lines = SUMMARY_BASELINE if self.summary_stacked() else KEY_BASELINE
        return (
            self.opts.margin
            + (lines + HEADER_DESCENDER) * self.opts.note_size
            + self.opts.header_gap
        )

    # -- 绘制 ------------------------------------------------------------

    def draw(self) -> Canvas:
        """绘制整页并返回画布（可重复调用，每次都从空画布开始）。"""
        self.canvas = Canvas()
        self.plan()
        self._header()
        row_count = max(1, len(self.jp.rows))
        y = self.header_height()

        self._positions = [
            {index: {} for index in range(len(self.systems))} for _ in self.jp.rows
        ]
        self._baselines = [
            {index: {} for index in range(len(self.systems))} for _ in self.jp.rows
        ]
        self.system_span = [
            (self.opts.margin,
             self.opts.margin + sum(self.measure_widths[m] for m in measures))
            for measures in self.systems
        ]

        for system_index, measures in enumerate(self.systems):
            is_last = system_index == len(self.systems) - 1
            for row_offset, row in enumerate(self.jp.rows):
                baseline = y + row_offset * self.opts.row_height + self.opts.note_size
                self._baselines[row_offset][system_index] = baseline
                self._draw_row(row, measures, baseline, system_index, row_offset)
            self._system_barlines(y, row_count, measures, final=is_last)
            y += self.opts.row_height * row_count + self.opts.system_gap

        # 连音线放在最后画：它可能跨越小节甚至系统，需要先知道全部记号的落点
        for row_offset, row in enumerate(self.jp.rows):
            self._draw_row_slurs(row, row_offset)
        return self.canvas

    def _header(self) -> None:
        """标题、署名与调号/速度/拍号声明。

        调号与速度在**首系统之上**（不是塞进首系统的行间）；窄页放不下右侧摘要时，
        摘要自动折到下一行，表头高度也随之增高。
        """
        opts = self.opts
        score = self.jp.score
        size = opts.note_size
        ink = self.theme.ink
        if opts.show_title and score.title:
            self.canvas.text(
                opts.page_width / 2.0, opts.margin + TITLE_BASELINE * size, score.title,
                1.55 * size, ink, opts.font_family, anchor="middle", weight="bold",
            )
        if score.composer:
            self.canvas.text(
                opts.page_width - opts.margin, opts.margin + COMPOSER_BASELINE * size,
                score.composer, 0.78 * size, ink, opts.font_family,
                anchor="end", style="italic",
            )
        y = opts.margin + KEY_BASELINE * size
        key_text = f"1 = {self.jp.tonic}"
        self.canvas.text(
            opts.margin, y, key_text, HEADER_TEXT_RATIO * size, ink,
            opts.font_family, weight="bold",
        )
        if opts.show_tempo:
            mark_right = draw_tempo_mark(
                self.canvas,
                opts.margin + _text_em(key_text) * HEADER_TEXT_RATIO * size + 1.4 * size,
                y, HEADER_TEXT_RATIO * size, self.theme.accent,
            )
            self.canvas.text(
                mark_right + 0.24 * size, y, f"= {score.bpm}",
                HEADER_TEXT_RATIO * size, self.theme.accent, opts.font_family, weight="bold",
            )
        summary = self.summary_text()
        self.canvas.text(
            opts.page_width - opts.margin,
            opts.margin + (SUMMARY_BASELINE if self.summary_stacked() else KEY_BASELINE) * size,
            summary, SUMMARY_RATIO * size, self.theme.faint, opts.font_family, anchor="end",
        )

    def _system_barlines(
        self, y: float, row_count: int, measures: Sequence[int], *, final: bool
    ) -> None:
        """画本系统的全部小节线；``final`` 时在末小节右界画终止双竖线。

        每次画的是**小节右边界**，故每小节的竖线同时也充当下一小节的左边界 ——
        与五线谱「只画边界、不画左右各一遍」的策略一致。
        """
        opts = self.opts
        size = opts.note_size
        x = opts.margin
        for measure_index in measures:
            x += self.measure_widths[measure_index]
            self._draw_barline(x, y, row_count, width=size * 0.085)
        if final and measures:
            self._draw_barline(x - size * 0.34, y, row_count, width=size * 0.22)

    def _draw_barline(self, x: float, y: float, row_count: int, *, width: float) -> None:
        """在 ``x`` 处为每一行画一条竖线。"""
        size = self.opts.note_size
        for row_offset in range(row_count):
            top = y + row_offset * self.opts.row_height
            self.canvas.line(x, top, x, top + size * 1.55, width, self.theme.ink)

    def _draw_row(
        self, row: JpRow, measures: Sequence[int], baseline: float,
        system_index: int, row_offset: int,
    ) -> None:
        """画一行：逐小节逐记号定位，并记录每个记号的落点供连音线使用。"""
        opts = self.opts
        x = opts.margin
        slots = self._positions[row_offset][system_index]
        for measure_index in measures:
            width = self.measure_widths[measure_index]
            if measure_index < len(row.measures):
                tokens = row.measures[measure_index].tokens
                for column, token in enumerate(tokens):
                    cx = x + opts.measure_pad + (column + 0.5) * opts.slot
                    self._draw_token(token, cx, baseline)
                    slots[(measure_index, column)] = cx
            x += width

    def _draw_token(self, token: JpToken, cx: float, baseline: float) -> None:
        """画一个记号：数字/横线 + 变音记号 + 附点 + 八度点 + 下划线。"""
        opts = self.opts
        size = opts.note_size
        ink = self.theme.ink
        if token.kind == "dash":
            half = size * 0.36
            self.canvas.line(
                cx - half, baseline - size * 0.30, cx + half, baseline - size * 0.30,
                size * 0.10, ink,
            )
            return

        self.canvas.text(
            cx, baseline, str(token.degree), size, ink, opts.font_family,
            anchor="middle", weight="bold",
        )
        if token.accidental:
            self._draw_accidental(cx - size * 0.52, baseline - size * 0.32, token.accidental, size)
        for index in range(token.dots):
            self.canvas.circle(
                cx + size * (0.44 + 0.26 * index), baseline - size * 0.22, size * 0.06, ink
            )
        for index in range(abs(token.octave)):
            # 八度点要「看得出是点」：半径取数字笔画量级，并让中心离开字顶 / 字底
            # （太小又与数字相切时，视觉上会读成数字的衬线而不是八度记号）
            step = size * (0.98 + 0.30 * index)
            y = baseline - step if token.octave > 0 else baseline + step * 0.72
            self.canvas.circle(cx, y, size * 0.085, ink)
        for index in range(token.underscores):
            y = baseline + size * (0.26 + 0.15 * index)
            half = size * 0.30
            self.canvas.line(
                cx - half, y, cx + half, y, size * 0.085, ink
            )

    def _draw_accidental(self, x: float, y: float, kind: int, size: float) -> None:
        """复用五线谱的矢量变音字形（保证两套谱面字形一致）。"""
        strokes = ACCIDENTAL_STROKES.get(kind)
        if not strokes:  # pragma: no cover - 拼写层只产出 -1/0/1
            return
        scale = size * 0.30
        dy = ACCIDENTAL_DY.get(kind, 0.0) * scale
        with self.canvas.group(f"translate({x:.2f},{y + dy:.2f}) scale({scale:.4f})"):
            for d, width in strokes:
                if width is None:
                    self.canvas.path(d, self.theme.ink)
                else:
                    self.canvas.path(d, "none", stroke=self.theme.ink, stroke_width=width)

    def _draw_row_slurs(self, row: JpRow, row_offset: int) -> None:
        """画整行的连音线。

        起点是带 ``slur_to_next`` 的**数字**，终点是其后第一个非横线记号 ——
        中间的延音横线属于同一个音，弧线要跨过去（``2 - 2̲`` 连的是两个 2）。
        两端不在同一系统时，按刻版惯例画出、入两段。
        """
        # 注意：本渲染器内部一律用「0 基小节位置」（与 ``plan()`` / ``measure_widths`` 一致），
        # 不是 ``JpMeasure.index``（1 基）。两者混用会静默连错小节。
        flat: List[Tuple[int, int, JpToken]] = [
            (position, column, token)
            for position, measure in enumerate(row.measures)
            for column, token in enumerate(measure.tokens)
        ]
        size = self.opts.note_size
        for index, (measure_position, column, token) in enumerate(flat):
            if not token.slur_to_next or token.kind == "dash":
                continue
            target = next(
                (flat[later] for later in range(index + 1, len(flat))
                 if flat[later][2].kind != "dash"),
                None,
            )
            if target is None:
                continue  # 曲末悬空：模型层已清 flag，这里只做兜底
            source_slot = self._slot(row_offset, measure_position, column)
            target_slot = self._slot(row_offset, target[0], target[1])
            if source_slot is None or target_slot is None:
                continue
            (sx, source_system), (tx, target_system) = source_slot, target_slot
            if source_system == target_system:
                self._arc(
                    sx + size * 0.28, tx - size * 0.28,
                    self._baselines[row_offset][source_system],
                )
                continue
            self._arc(
                sx + size * 0.28, self.system_span[source_system][1],
                self._baselines[row_offset][source_system],
            )
            self._arc(
                self.system_span[target_system][0], tx - size * 0.28,
                self._baselines[row_offset][target_system],
            )

    def _slot(
        self, row_offset: int, measure_index: int, column: int
    ) -> Optional[Tuple[float, int]]:
        """查某记号画在哪：``(中心 x, 所属系统)``；不在任何系统里则为 None。"""
        for system_index, slots in self._positions[row_offset].items():
            found = slots.get((measure_index, column))
            if found is not None:
                return found, system_index
        return None

    def _arc(self, x1: float, x2: float, baseline: float) -> None:
        """一段连音弧；跨距太短（不足 0.3 字号）则省略，避免墨点。"""
        size = self.opts.note_size
        if x2 - x1 < size * 0.3:  # pragma: no cover - 相邻槽位步进远大于此
            return
        y = baseline - size * 1.28
        self.canvas.path(
            f"M {x1:.2f},{y:.2f} Q {(x1 + x2) / 2:.2f},{y - size * 0.34:.2f} {x2:.2f},{y:.2f}",
            "none", stroke=self.theme.ink, stroke_width=size * 0.055,
        )


# ---------------------------------------------------------------------------
# 公开入口
# ---------------------------------------------------------------------------


def render_jianpu_svg(source: Score | JpScore, options: Optional[JpOptions] = None) -> str:
    """渲染简谱为 SVG 文档字符串。"""
    jp = source if isinstance(source, JpScore) else parse_jianpu(source)
    opts = options or JpOptions()
    renderer = JianpuRenderer(jp, opts)
    canvas = renderer.draw()
    return to_svg(canvas.ops, opts.page_width, renderer.page_height, opts.theme.paper)


def write_jianpu_svg(
    source: Score | JpScore, path: str | Path, options: Optional[JpOptions] = None
) -> str:
    """渲染并落盘 ``.svg``，返回绝对路径。"""
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_jianpu_svg(source, options), encoding="utf-8")
    return str(target)


def render_jianpu_png(
    source: Score | JpScore, options: Optional[JpOptions] = None, *, scale: float = 2.0
) -> bytes:
    """渲染简谱为 PNG 字节（需要 Pillow）。"""
    jp = source if isinstance(source, JpScore) else parse_jianpu(source)
    opts = options or JpOptions()
    renderer = JianpuRenderer(jp, opts)
    canvas = renderer.draw()
    return to_png(
        canvas.ops, opts.page_width, renderer.page_height, opts.theme.paper, scale=scale
    )


def write_jianpu_png(
    source: Score | JpScore, path: str | Path,
    options: Optional[JpOptions] = None, *, scale: float = 2.0,
) -> str:
    """渲染并落盘 ``.png``，返回绝对路径。"""
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(render_jianpu_png(source, options, scale=scale))
    return str(target)
