"""统一插件 / 扩展发现（R12）。

第三方包可通过 ``importlib.metadata`` entry points 注册扩展，**无需改核心代码**：

.. code-block:: toml

    [project.entry-points."sunoauxtool.download_sources"]
    my-source = "my_pkg.sources:MySource"

    [project.entry-points."sunoauxtool.video_visuals"]
    my-visual = "my_pkg.visuals:MyVisualizer"

扩展点（group 全名 = ``sunoauxtool.<point>``）：

=============  ============================  ==================================
point          group                         注册表条目
=============  ============================  ==================================
ai_backends    sunoauxtool.ai_backends       ``AIGenerator`` 子类
render_engines sunoauxtool.render_engines    ``Renderer`` 子类
download_srcs  sunoauxtool.download_sources  ``SourceAdapter`` 实例
transcribe     sunoauxtool.transcribe_backends  转谱后端类
video_visuals  sunoauxtool.video_visuals     ``Visualizer`` 子类（**保留类**）
=============  ============================  ==================================

不变约束（继承 R0–R8）：
- builtins 仍硬编码注册，entry points 只追加（同名时插件覆盖内置，见 :func:`discover`）；
- **单个 entry point 加载失败只 ``warnings.warn`` 并跳过**，绝不拖垮内置能力；
- 核心层不得反向依赖 CLI 层；本模块是核心基础设施，只被 import。
"""

from __future__ import annotations

import warnings
from importlib.metadata import EntryPoint, entry_points
from typing import Any, Dict, Optional, Sequence

#: entry point group 前缀
GROUP_PREFIX = "sunoauxtool."


def group_of(point: str) -> str:
    """扩展点短名 -> 完整 group 名。"""
    return GROUP_PREFIX + point


def _iter_entry_points(group: str) -> Sequence[EntryPoint]:
    """列出指定 group 的 entry points（兼容 py<3.10 的 dict 形式）。"""
    try:
        return entry_points(group=group)
    except TypeError:  # pragma: no cover - py<3.10 兜底
        return tuple(entry_points().get(group, ()))


def _resolve(loaded: Any, instantiate: bool) -> Any:
    """entry point 载入对象 -> 注册表条目。"""
    if instantiate and isinstance(loaded, type):
        return loaded()
    return loaded


def discover(
    point: str,
    builtins: Dict[str, Any],
    *,
    base: Optional[type] = None,
    instantiate: bool = True,
) -> Dict[str, Any]:
    """合并 builtins 与该扩展点的 entry point 插件。

    Args:
        point: 扩展点短名（如 ``download_sources``）。
        builtins: 内置注册表（硬编码），先入。
        base: 可选基类/接口；不符则 warn 跳过。``instantiate=True`` 时校验实例，
            否则校验类是否为子类。
        instantiate: 载入对象是类时是否实例化。visuals 需保留类本身
            （工厂稍后按 config 实例化），传 ``False``。

    Returns:
        ``{name: obj}``；entry point 与 builtin 同名时**插件覆盖内置**。

    Notes:
        任何 entry point 的导入/实例化异常都被吞掉并降级为 :class:`UserWarning`，
        保证「一个坏插件不会让 CLI 起不来」。
    """
    registry: Dict[str, Any] = dict(builtins)
    group = group_of(point)
    for ep in _iter_entry_points(group):
        try:
            obj = _resolve(ep.load(), instantiate)
        except Exception as exc:  # noqa: BLE001 - 插件隔离：任何异常都不得外泄
            warnings.warn(
                f"插件 {ep.name!r}（group={group}）加载失败，已跳过: {exc}",
                stacklevel=2,
            )
            continue
        if base is not None:
            ok = (
                isinstance(obj, base)
                if instantiate
                else (isinstance(obj, type) and issubclass(obj, base))
            )
            if not ok:
                warnings.warn(
                    f"插件 {ep.name!r}（group={group}）不是 {base.__name__} 的"
                    f"{'实例' if instantiate else '子类'}，已跳过",
                    stacklevel=2,
                )
                continue
        registry[ep.name] = obj
    return registry


__all__ = ["GROUP_PREFIX", "group_of", "discover"]
