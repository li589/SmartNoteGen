"""CHANGELOG 版本条目一致性检查脚本。

检测两类漂移：
1. CHANGELOG 中「最新版本条目」的版本号必须与 pyproject.toml 的 version 一致。
2. CHANGELOG 中每个 `[X.Y.Z]` 条目的版本号必须按 semver 降序排列，
   且不得出现比当前发行版本更新的条目（避免「未来版本」写入）。

用法：
    python scripts/check_changelog.py           # 检测并退出 0/1
    python scripts/check_changelog.py --fix     # 自动修正最新条目版本号（仅当唯一偏差时）

本脚本不依赖已安装包，纯文件读取，适合 CI 与本地预检。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"

# 匹配 CHANGELOG 开头的版本行，如 `## [1.3.0] - 2026-09-22 (...)`
_VERSION_LINE_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\]")


def _read_text(path: Path) -> str:
    """读取文本，newline="" 关闭通用换行转换，保留原始行尾字节。

    Windows 文本模式下 read_text/write_text 会做 LF<->CRLF 互转：
    若仓库存 LF 而写入时转 CRLF，整个文件会被判为 modified（内容其实未变）。
    用 open() 而非 Path.read_text()：后者直到 3.13 才支持 newline 参数。
    """
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def _read_changelog_versions() -> list[str]:
    """按出现顺序返回 CHANGELOG 中所有 `[X.Y.Z]` 版本号。"""
    versions: list[str] = []
    for line in _read_text(CHANGELOG).splitlines():
        m = _VERSION_LINE_RE.match(line.strip())
        if m:
            versions.append(m.group(1))
    return versions


def _read_pyproject_version() -> str:
    """返回 pyproject.toml 的 project.version。"""
    data = tomllib.loads(_read_text(PYPROJECT))
    return data["project"]["version"]


def check() -> int:
    """执行一致性检查。返回 0=通过，1=失败。"""
    errors: list[str] = []
    current = _read_pyproject_version()
    versions = _read_changelog_versions()

    if not versions:
        errors.append("CHANGELOG.md 未找到任何版本条目")
    else:
        latest = versions[0]
        if latest != current:
            errors.append(
                f"CHANGELOG 最新条目版本 [{latest}] != pyproject.toml version [{current}]"
            )

        # 降序检查：不允许后一条版本号大于前一条（出现顺序即发布顺序）
        parsed = [(int(x.split(".")[0]), int(x.split(".")[1]), int(x.split(".")[2])) for x in versions]
        for i in range(1, len(parsed)):
            if parsed[i] > parsed[i - 1]:
                errors.append(
                    f"CHANGELOG 版本顺序错误：第 {i+1} 条目 [{versions[i]}] "
                    f"大于前一条 [{versions[i-1]}]，违反降序排列"
                )

        # 不得存在比当前发行版本更新的条目
        cur_parsed = tuple(int(p) for p in current.split("."))
        for v in versions:
            v_parsed = tuple(int(p) for p in v.split("."))
            if v_parsed > cur_parsed:
                errors.append(
                    f"CHANGELOG 含未来版本 [{v}]，比当前发行版本 [{current}] 更新"
                )

    if errors:
        print("CHANGELOG 一致性检查失败：")
        for e in errors:
            print(f"  ✗ {e}")
        return 1

    print(f"CHANGELOG 一致性通过（最新条目 [{versions[0]}] == pyproject [{current}]，"
          f"共 {len(versions)} 个版本条目，降序排列正常）")
    return 0


def main() -> None:
    fix = "--fix" in sys.argv[1:]
    if fix:
        current = _read_pyproject_version()
        versions = _read_changelog_versions()
        if versions and versions[0] != current:
            content = _read_text(CHANGELOG)
            new_content = re.sub(
                r"^(## \[)\d+\.\d+\.\d+(\])",
                rf"\g<1>{current}\g<2>",
                content,
                count=1,
                flags=re.MULTILINE,
            )
            if new_content != content:
                with open(CHANGELOG, "w", encoding="utf-8", newline="") as f:
                    f.write(new_content)
                print(f"已自动修正 CHANGELOG 最新条目为 [{current}]")
            else:
                print("未找到需要修正的版本行（无 [X.Y.Z] 条目或正则未命中）")
        else:
            print("无需修正（版本一致或 CHANGELOG 为空）")
    else:
        raise SystemExit(check())


if __name__ == "__main__":
    main()
