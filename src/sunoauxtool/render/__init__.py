"""渲染器包。"""

from typing import Dict

from sunoauxtool.render.fluidsynth import Renderer, FluidSynthRenderer


def discover_render_engines() -> Dict[str, type]:
    """渲染引擎注册表 ``{name: Renderer 子类}`` = 内置 + entry point 插件。

    扩展点：``sunoauxtool.render_engines``（见 :mod:`sunoauxtool.plugins`）。
    """
    from sunoauxtool.plugins import discover

    builtins: Dict[str, type] = {"fluidsynth": FluidSynthRenderer}
    return discover("render_engines", builtins, base=Renderer, instantiate=False)


__all__ = ["Renderer", "FluidSynthRenderer", "discover_render_engines"]
