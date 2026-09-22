"""版本号对齐守卫。

主包历史上因「pyproject.toml / __init__.py / 测试断言」三处版本号不同步
漂移过两次（0.4.1→0.5.2、0.5.3→0.5.4）；sunoauxtool.video 在 2026-09-20 也查出
`pyproject.toml` 停留在 0.1.0 而源码已是 0.3.0。

本模块用纯文件断言把这类漂移钉死：任何一处版本号改动未同步，测试立刻失败。
不依赖环境（不需要包已安装），因此 CI 上同样有效。
"""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: (发行名, 包 __init__.py 相对路径, pyproject.toml 相对路径)
PACKAGES = [
    (
        "sunoauxtool",
        "src/sunoauxtool/__init__.py",
        "pyproject.toml",
    ),
]

#: 统一发行版内的子模块：__version__ 必须与主包镜像（0.6.0 起单包化，video/download
#: 不再有独立 pyproject，版本一律跟发行版走）
SUBMODULE_VERSION_MIRRORS = [
    ("sunoauxtool.video", "src/sunoauxtool/video/__init__.py"),
    ("sunoauxtool.download", "src/sunoauxtool/download/__init__.py"),
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

    未安装则跳过——CI 只 `pip install -e .` 主包，sunoauxtool.video / Suno 子包
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


@pytest.mark.parametrize("name, src_rel", SUBMODULE_VERSION_MIRRORS, ids=[p[0] for p in SUBMODULE_VERSION_MIRRORS])
def test_submodule_version_mirrors_release(name, src_rel):
    """子模块 __version__ 必须与主包版本一致（单发行版制）。"""
    main = _read_version(REPO_ROOT / "src/sunoauxtool/__init__.py")
    sub = _read_version(REPO_ROOT / src_rel)
    assert sub == main, (
        f"{name}: 子模块版本 {sub} != 主包版本 {main} —— 单发行版制下版本号必须镜像"
    )


# ---------------------------------------------------------------------------
# CHANGELOG 版本条目一致性（与 scripts/check_changelog.py 逻辑同源）
# ---------------------------------------------------------------------------

_CHECKER_SPEC = importlib.util.spec_from_file_location(
    "check_changelog", REPO_ROOT / "scripts" / "check_changelog.py"
)
assert _CHECKER_SPEC is not None and _CHECKER_SPEC.loader is not None
_check_mod = importlib.util.module_from_spec(_CHECKER_SPEC)
_CHECKER_SPEC.loader.exec_module(_check_mod)


def test_changelog_latest_version_matches_pyproject():
    """CHANGELOG 最新 `[X.Y.Z]` 条目必须等于 pyproject.toml 的 project.version。"""
    assert _check_mod.check() == 0
