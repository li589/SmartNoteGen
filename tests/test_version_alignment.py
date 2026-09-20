"""版本号对齐守卫。

主包历史上因「pyproject.toml / __init__.py / 测试断言」三处版本号不同步
漂移过两次（0.4.1→0.5.2、0.5.3→0.5.4）；videomaker 在 2026-09-20 也查出
`pyproject.toml` 停留在 0.1.0 而源码已是 0.3.0。

本模块用纯文件断言把这类漂移钉死：任何一处版本号改动未同步，测试立刻失败。
不依赖环境（不需要包已安装），因此 CI 上同样有效。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: (发行名, 包 __init__.py 相对路径, pyproject.toml 相对路径)
PACKAGES = [
    (
        "smartnotegen",
        "src/smartnotegen/__init__.py",
        "pyproject.toml",
    ),
    (
        "videomaker",
        "src/videomaker/__init__.py",
        "src/videomaker/pyproject.toml",
    ),
    (
        "Suno-Cat-Catch-Resolve",
        "src/Suno-Cat-Catch-Resolve/suno_cat_catch_resolve/__init__.py",
        "src/Suno-Cat-Catch-Resolve/pyproject.toml",
    ),
]


def _read_version(path: Path) -> str:
    """从 __init__.py 中提取 __version__（不导入包，避免副作用）。"""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("__version__"):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    raise AssertionError(f"{path} 未声明 __version__")


@pytest.mark.parametrize("dist, src_rel, pyproject_rel", PACKAGES, ids=[p[0] for p in PACKAGES])
def test_pyproject_version_matches_module_version(dist, src_rel, pyproject_rel):
    """pyproject.toml 的 version 必须等于包内 __version__。"""
    src_version = _read_version(REPO_ROOT / src_rel)
    pyproject = tomllib.loads((REPO_ROOT / pyproject_rel).read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == src_version, (
        f"{dist}: pyproject.toml 声明 {pyproject['project']['version']}，"
        f"但 {src_rel} 声明 {src_version} —— 版本号漂移，请同步两处"
    )


@pytest.mark.parametrize("dist, src_rel, pyproject_rel", PACKAGES, ids=[p[0] for p in PACKAGES])
def test_installed_metadata_matches_source(dist, src_rel, pyproject_rel):
    """已安装（editable）的元数据版本必须等于源码版本。

    未安装则跳过——CI 只 `pip install -e .` 主包，videomaker / Suno 子包
    在 CI 上本来就未安装。本地启用 editable 后此断言可捕获「源码已升版、
    但没重装」的滞后（2026-09-20 实际发生的正是这种情况）。
    """
    import importlib.metadata as md

    try:
        installed = md.version(dist)
    except md.PackageNotFoundError:
        pytest.skip(f"{dist} 未安装（CI 中属正常）")

    src_version = _read_version(REPO_ROOT / src_rel)
    assert installed == src_version, (
        f"{dist}: 已安装元数据为 {installed}，源码为 {src_version} —— "
        f"editable 安装已滞后，请执行 `pip install -e {pyproject_rel.rsplit('/', 1)[0] or '.'}`"
    )
