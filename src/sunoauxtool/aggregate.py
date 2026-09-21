"""sunoaux：顶层聚合 CLI（前期 pre / 后期 post 的统一入口）。

设计铁律（继承自重构计划 R3）：
  - **薄转发层**：所有子命令直接二次注册既有命令函数（Typer 的 command
    装饰器返回原函数，可安全挂到新 app 上），零参数复制、零业务逻辑；
  - 核心层不得反向依赖 CLI 层——本模块只 import，不被 import；
  - 旧入口 ``sunoauxtool`` / ``videomaker`` / ``downloadhelper`` 保留（兼容期 >= 1 个版本）。

子命令结构：
    sunoaux pre melody / midi / score / render / transcribe     （前期：创作）
    sunoaux post probe / convert / fetch                        （后期：取回与转码）
    sunoaux post video render / multi                           （后期：音乐视频）
    sunoaux post dsp        （R6 交付占位）
    sunoaux post enhance    （R5 交付占位，AudioSR 超分）

映射表（新 -> 旧）：
    pre  melody      -> sunoauxtool generate melody
    pre  midi        -> sunoauxtool generate midi
    pre  score       -> sunoauxtool score
    pre  render      -> sunoauxtool render
    pre  transcribe  -> sunoauxtool transcribe
    post probe       -> downloadhelper probe
    post convert     -> downloadhelper decode
    post fetch       -> downloadhelper batch
    post video *     -> videomaker render / multi
"""

from __future__ import annotations

import typer

from sunoauxtool import __version__
from sunoauxtool import cli as core_cli
from sunoauxtool.download import cli as download_cli
from sunoauxtool.video import cli as video_cli

app = typer.Typer(
    name="sunoaux",
    help="SunoAuxTool 聚合入口：pre（前期创作）+ post（后期处理）",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"sunoaux {__version__}")
        raise typer.Exit(0)


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", help="显示版本号", callback=_version_callback, is_eager=True
    ),
) -> None:
    """sunoaux 聚合入口（薄转发层，业务逻辑在既有命令实现中）。"""


# ---------------------------------------------------------------------------
# pre：前期创作（映射 sunoauxtool 既有命令）
# ---------------------------------------------------------------------------

pre_app = typer.Typer(help="前期：旋律 / MIDI / 谱面 / 渲染 / 转谱", no_args_is_help=True)

pre_app.command("melody", help="(= generate melody) 生成旋律 MIDI")(core_cli.generate_melody)
pre_app.command("midi", help="(= generate midi) 程序化生成 MIDI")(core_cli.generate_midi)
pre_app.command("score", help="(= score) 从 MIDI 生成谱面")(core_cli.score_cmd)
pre_app.command("render", help="(= render) MIDI -> WAV 渲染")(core_cli.render_cmd)
pre_app.command("transcribe", help="(= transcribe) WAV -> MIDI 转谱")(core_cli.transcribe_cmd)

app.add_typer(pre_app, name="pre")


# ---------------------------------------------------------------------------
# post：后期处理（映射 downloadhelper / videomaker 既有命令）
# ---------------------------------------------------------------------------

post_app = typer.Typer(help="后期：取回 / 转码 / 视频 / DSP / 音质提升", no_args_is_help=True)

post_app.command("probe", help="(= downloadhelper probe) 取证判定：明文 / 加密密文")(
    download_cli.probe
)
post_app.command("convert", help="(= downloadhelper decode) fMP4 -> Opus/MP3 转码")(
    download_cli.decode
)
post_app.command("fetch", help="(= downloadhelper batch) 批量扫描目录取回音频")(
    download_cli.batch
)


def _not_implemented(name: str, phase: str) -> None:
    typer.echo(f"post {name} 尚未实现（计划于 {phase} 交付）。", err=True)
    raise typer.Exit(code=1)


@post_app.command("dsp", help="[R6 交付] DSP 操作串（norm/fade/trim...）——尚未接线")
def dsp_stub() -> None:
    """R6（DSP 功能包）交付占位。"""
    _not_implemented("dsp", "R6")


@post_app.command("enhance", help="[R5 交付] AudioSR 音质提升——尚未接线")
def enhance_stub() -> None:
    """R5（VASR 接入）交付占位。"""
    _not_implemented("enhance", "R5")


video_app = typer.Typer(help="音乐视频（= videomaker）", no_args_is_help=True)
video_app.command("render")(video_cli.render)
video_app.command("multi")(video_cli.multi)
post_app.add_typer(video_app, name="video")

app.add_typer(post_app, name="post")
