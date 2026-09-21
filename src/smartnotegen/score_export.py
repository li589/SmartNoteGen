"""乐谱导出服务：格式归一化 + 统一落盘。

为什么独立成模块
----------------
``score`` 子命令、``pipeline --score``、``generate --score`` 三处都要「把一份 Score
按若干格式落到同目录」，且都要处理同一批选项（主题、页面宽度、渲染开关）。写在
``cli.py`` 里会让三处各抄一遍并逐渐漂移；集中在这里，行为只有一份。

放在顶层（与 ``preview.py`` 同层）而不是 ``commands/`` 下：``pipeline`` 要用它，
而 ``pipeline`` 属核心编排层，不应反向依赖 CLI 层。

错误约定
--------
- 未知格式 / 非法参数 → ``ParameterError``（错误码 1）。
- PNG 需要 Pillow：缺依赖时把 ``ImportError`` 转成带安装指引的 ``ParameterError``，
  不让它冒成「意外错误」——这是可预期的环境缺失，不是缺陷。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from smartnotegen.exceptions import ParameterError
from smartnotegen.score import (
    JpOptions,
    LayoutOptions,
    MusicXmlOptions,
    Score,
    SvgOptions,
    SvgTheme,
    layout_score,
    render_jianpu_svg,
    render_svg,
    to_jianpu_lines,
    write_jianpu_png,
    write_jianpu_svg,
    write_musicxml,
    write_png,
    write_svg,
)
from smartnotegen.score.theory import normalize_key

#: 规范格式名 -> 中文说明（也用作 ``score --help`` 的格式清单）
SCORE_FORMATS: Dict[str, str] = {
    "svg": "五线谱矢量图（零依赖，浏览器可直接看）",
    "png": "五线谱位图（需要 Pillow）",
    "jianpu": "简谱 SVG",
    "jianpu-png": "简谱位图（需要 Pillow）",
    "jianpu-txt": "简谱纯文本（等宽字符，可直接打印）",
    "musicxml": "MusicXML 4.0（MuseScore / Dorico / Finale 可导入）",
}

#: 用户可能写的别名 -> 规范格式名元组
FORMAT_ALIASES: Dict[str, Sequence[str]] = {
    "all": tuple(SCORE_FORMATS),
    "xml": ("musicxml",),
    "music-xml": ("musicxml",),
    "txt": ("jianpu-txt",),
    "text": ("jianpu-txt",),
    "jianpu-svg": ("jianpu",),
    "np": ("jianpu",),
    "number": ("jianpu",),
}

#: 规范格式名 -> 文件名后缀（``stem`` 之后追加）
FORMAT_SUFFIX: Dict[str, str] = {
    "svg": ".svg",
    "png": ".png",
    "jianpu": ".jianpu.svg",
    "jianpu-png": ".jianpu.png",
    "jianpu-txt": ".jianpu.txt",
    "musicxml": ".musicxml",
}

#: 主题名 -> 说明
THEMES: Dict[str, str] = {"light": "白纸黑墨（乐谱惯例）", "dark": "深纸浅墨（深色界面内嵌）"}


def format_help() -> str:
    """格式清单（供 CLI 帮助文本与错误提示复用）。"""
    items = "，".join(f"{name}（{desc}）" for name, desc in SCORE_FORMATS.items())
    return f"可用格式：{items}；也可写 all（全部）"


def normalize_formats(spec: str | Iterable[str]) -> List[str]:
    """把用户写法归一化为规范格式名列表（去重、保序）。

    Args:
        spec: ``"svg,png"`` / ``"all"`` / ``["svg", "xml"]`` 等。

    Returns:
        规范格式名列表，如 ``["svg", "png", "musicxml"]``。

    Raises:
        ParameterError: 未知格式名或结果为空。
    """
    if isinstance(spec, str):
        raw = [part.strip() for part in spec.replace(";", ",").split(",")]
    else:
        raw = [str(part).strip() for part in spec]

    out: List[str] = []
    for token in raw:
        key = token.lower()
        if not key:
            continue
        if key in FORMAT_ALIASES:
            names: Sequence[str] = FORMAT_ALIASES[key]
        elif key in SCORE_FORMATS:
            names = (key,)
        else:
            raise ParameterError(f"未知谱面格式: {token!r}。{format_help()}")
        for name in names:
            if name not in out:
                out.append(name)
    if not out:
        raise ParameterError(f"未指定任何谱面格式。{format_help()}")
    return out


def _theme_for(name: str) -> SvgTheme:
    """主题名 -> ``SvgTheme``。"""
    key = (name or "light").strip().lower()
    if key not in THEMES:
        raise ParameterError(f"未知主题: {name!r}（可用：{'、'.join(THEMES)}）")
    return SvgTheme.dark() if key == "dark" else SvgTheme()


@dataclass
class ScoreExportOptions:
    """谱面导出选项（三处调用方共用）。"""

    formats: Sequence[str] = ("svg",)
    theme: str = "light"
    scale: float = 2.0
    page_width: Optional[float] = None
    space: Optional[float] = None
    show_title: bool = True
    show_tempo: bool = True
    show_measure_numbers: bool = True
    show_ties: bool = True
    #: 已归一化的格式（构造时填充；调用方不必自己调 normalize_formats）
    resolved: List[str] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.resolved = normalize_formats(self.formats)
        if self.scale <= 0:
            raise ParameterError(f"位图超采样倍数必须为正，实为 {self.scale}")
        if self.page_width is not None and self.page_width <= 0:
            raise ParameterError(f"页面宽度必须为正，实为 {self.page_width}")
        if self.space is not None and self.space <= 0:
            raise ParameterError(f"谱线间距必须为正，实为 {self.space}")
        _theme_for(self.theme)  # 提前校验，避免写了一半才报错

    # -- 选项构造 ---------------------------------------------------------

    def layout_options(self) -> LayoutOptions:
        """五线谱排版选项。"""
        opts = LayoutOptions()
        if self.page_width is not None:
            opts.page_width = float(self.page_width)
        if self.space is not None:
            opts.space = float(self.space)
        return opts

    def svg_options(self) -> SvgOptions:
        """五线谱渲染选项。"""
        return SvgOptions(
            theme=_theme_for(self.theme),
            show_title=self.show_title,
            show_tempo=self.show_tempo,
            show_measure_numbers=self.show_measure_numbers,
            show_ties=self.show_ties,
        )

    def jianpu_options(self) -> JpOptions:
        """简谱排版选项（只有页面宽度与主题共享，谱线间距对简谱无意义）。"""
        opts = JpOptions(theme=_theme_for(self.theme))
        opts.show_title = self.show_title
        opts.show_tempo = self.show_tempo
        if self.page_width is not None:
            opts.page_width = float(self.page_width)
        return opts

    def musicxml_options(self) -> MusicXmlOptions:
        """MusicXML 导出选项（标题与速度记号跟随同一组开关）。"""
        return MusicXmlOptions(
            include_metadata=self.show_title,
            include_tempo=self.show_tempo,
        )


def export_score(
    score: Score,
    output_dir: str | Path,
    stem: str,
    options: Optional[ScoreExportOptions] = None,
) -> Dict[str, str]:
    """把谱面按选项落到 ``<output_dir>/<stem><suffix>``。

    Args:
        score: 已装配的乐谱。
        output_dir: 输出目录（不存在则创建）。
        stem: 文件名主干（不含扩展名）。
        options: 导出选项；None 用默认（仅 SVG）。

    Returns:
        ``{规范格式名: 绝对路径}``，顺序与 ``options.resolved`` 一致。

    Raises:
        ParameterError: 选项非法或未安装 Pillow 而请求了位图格式。
    """
    opts = options or ScoreExportOptions()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    layout = layout_score(score, opts.layout_options())
    svg_opts = opts.svg_options()
    jp_opts = opts.jianpu_options()

    written: Dict[str, str] = {}
    for name in opts.resolved:
        target = out_dir / f"{stem}{FORMAT_SUFFIX[name]}"
        if name == "svg":
            written[name] = write_svg(layout, target, svg_opts)
        elif name == "png":
            written[name] = _png_guarded(
                lambda: write_png(layout, target, svg_opts, scale=opts.scale), "五线谱位图", "svg"
            )
        elif name == "jianpu":
            written[name] = write_jianpu_svg(score, target, jp_opts)
        elif name == "jianpu-png":
            written[name] = _png_guarded(
                lambda: write_jianpu_png(score, target, jp_opts, scale=opts.scale),
                "简谱位图",
                "jianpu",
            )
        elif name == "jianpu-txt":
            text = "\n".join(to_jianpu_lines(score, jp_opts)) + "\n"
            target.write_text(text, encoding="utf-8")
            written[name] = str(target.expanduser().resolve())
        elif name == "musicxml":
            written[name] = write_musicxml(score, target, opts.musicxml_options())
        else:  # pragma: no cover - normalize_formats 已拦下未知名
            raise ParameterError(f"未知谱面格式: {name!r}")
    return written


def score_svg_text(score: Score, options: Optional[ScoreExportOptions] = None) -> str:
    """只取五线谱 SVG 文本（供预览页内嵌，不落盘）。"""
    opts = options or ScoreExportOptions()
    layout = layout_score(score, opts.layout_options())
    return render_svg(layout, opts.svg_options())


def score_from_sequence(seq, *, title: str = "Untitled", key: Optional[str] = None) -> Score:
    """从 ``NoteSequence`` 构建 ``Score``，可选覆盖记谱调式。

    为什么需要这层包装：``Score.from_sequence`` 不接受 ``key``（它沿用 ``seq.key``），
    而 CLI 允许 ``--score-key`` 覆盖。调式归一化交给 ``theory.normalize_key``，
    非法写法在这里转成 ``ParameterError``，不让 ``ValueError`` 冒成「意外错误」。

    Args:
        seq: ``models.notes.NoteSequence``。
        title: 标题（通常取 MIDI 文件名主干）。
        key: 记谱调式覆盖；None 沿用 ``seq.key``。

    Returns:
        ``Score`` 实例。

    Raises:
        ParameterError: ``key`` 无法解析。
    """
    score = Score.from_sequence(seq, title=title)
    if key:
        try:
            tonic, mode = normalize_key(key)
        except ValueError as exc:
            raise ParameterError(f"非法调式: {key!r}（{exc}）") from exc
        score.key = f"{tonic} {mode}"
    return score


def score_jianpu_svg_text(score: Score, options: Optional[ScoreExportOptions] = None) -> str:
    """只取简谱 SVG 文本（供预览页内嵌，不落盘）。"""
    opts = options or ScoreExportOptions()
    return render_jianpu_svg(score, opts.jianpu_options())


def _png_guarded(write, what: str, fallback: str) -> str:
    """位图落盘；缺 Pillow 时转成带安装指引的参数错误。

    Args:
        write: 实际落盘的可调用对象。
        what: 报错文案里的产物名（如「五线谱位图」）。
        fallback: 建议退回到的矢量格式名。
    """
    try:
        return write()
    except ImportError as exc:
        raise ParameterError(
            f"{what}需要 Pillow（{exc}）。请 pip install Pillow，或改用 --format {fallback}。"
        ) from exc
