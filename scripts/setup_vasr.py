#!/usr/bin/env python3
"""Setup AudioSR (VASR) source tree for SunoAuxTool (R9).

把 haoheliu/versatile_audio_super_resolution 克隆到
``src/versatile_audio_super_resolution``（或 ``AUDIOSR_DIR`` 指向的目录），
剥离内嵌 ``.git``，并应用 ``patches/vasr_super_resolution_long_audio.patch``
修复长音频末块 bug（[SunoAuxTool patch R5]）。幂等：已存在则跳过。

本脚本只准备**源码**；重型依赖 torch/torchaudio 见 ``requirements/vasr.txt``，
约 2.6GB 模型权重首次运行自动下载到 ``~/.cache/huggingface``。

用法::

    python scripts/setup_vasr.py
    AUDIOSR_DIR=/path/to/audiosr python scripts/setup_vasr.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = REPO_ROOT / "src" / "versatile_audio_super_resolution"
UPSTREAM = "https://github.com/haoheliu/versatile_audio_super_resolution"
PINNED_COMMIT = "d312fba"
PATCH = REPO_ROOT / "patches" / "vasr_super_resolution_long_audio.patch"
PATCH_MARKER = "[SunoAuxTool patch R5]"


def log(msg: str) -> None:
    print(f"[setup_vasr] {msg}", flush=True)


def run(cmd: list[str], cwd: str | None = None) -> None:
    log(f"$ {' '.join(cmd)}" + (f"  (cwd={cwd})" if cwd else ""))
    subprocess.run(cmd, cwd=cwd, check=True)


def resolve_target() -> Path:
    env = os.environ.get("AUDIOSR_DIR")
    return Path(env) if env else DEFAULT_TARGET


def clone(target: Path) -> None:
    if (target / "audiosr").is_dir():
        log(f"audiosr 已存在，跳过克隆: {target}")
        return
    if target.exists():
        log(f"目标目录已存在但无 audiosr 子包，中止以避免覆盖: {target}")
        sys.exit(2)
    tmp = target.with_name(target.name + ".clone_tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    run(["git", "clone", UPSTREAM, str(tmp)])
    run(["git", "-C", str(tmp), "checkout", PINNED_COMMIT])
    # 去掉嵌套 .git，纳入本仓 gitignore 管理（src/versatile_audio_super_resolution/）
    git_dir = tmp / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)
    tmp.rename(target)
    log(f"克隆完成 @ {PINNED_COMMIT}: {target}")


def apply_patch(target: Path) -> None:
    pipeline = target / "audiosr" / "pipeline.py"
    if not pipeline.is_file():
        log(f"缺失 audiosr/pipeline.py，补丁无法应用: {pipeline}")
        sys.exit(3)
    if PATCH_MARKER in pipeline.read_text(encoding="utf-8"):
        log("补丁 [SunoAuxTool patch R5] 已应用，跳过。")
        return
    if not PATCH.is_file():
        log(f"补丁文件缺失: {PATCH}")
        sys.exit(4)
    # 优先 git apply（可在非 git 仓库目录工作），失败回退 patch -p1
    try:
        subprocess.run(
            ["git", "apply", "-p1", str(PATCH)],
            cwd=str(target),
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        log("git apply 失败，回退 patch -p1 ...")
        try:
            subprocess.run(
                ["patch", "-p1", "-i", str(PATCH)],
                cwd=str(target),
                check=True,
                capture_output=True,
            )
        except FileNotFoundError:
            log("patch 命令不可用；请手动 `git apply -p1 patches/vasr_super_resolution_long_audio.patch`")
            sys.exit(5)
        except subprocess.CalledProcessError as exc:
            log(f"补丁应用失败: {exc}")
            sys.exit(5)
    log("补丁已应用。")


def main() -> None:
    target = resolve_target()
    log(f"目标目录: {target}")
    log(f"上游 @ {PINNED_COMMIT}: {UPSTREAM}")
    clone(target)
    apply_patch(target)
    log("权重首次运行自动下载到: ~/.cache/huggingface")
    log("运行依赖见 requirements/vasr.txt")
    log("完成。")


if __name__ == "__main__":
    main()
