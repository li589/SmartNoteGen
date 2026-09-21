"""Suno 上传辅助（P3-B2 打包 + P3-B3 清单）。

将一批 Suno 合规片段 + metadata 打包成可上传的目录/zip，并生成 CSV/JSON 上传清单，
指引用户在 Suno 逐个上传。
"""

from __future__ import annotations

import csv
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any


def build_pack(
    wav_files: list[str | Path],
    output_dir: str | Path,
    pack_name: str = "suno_pack",
    make_zip: bool = True,
) -> dict[str, Any]:
    """将一批 WAV 片段打包成可上传目录（+ zip）。

    Args:
        wav_files: Suno 合规片段路径列表。
        output_dir: 打包输出根目录。
        pack_name: 打包目录名。
        make_zip: 是否同时生成 zip。

    Returns:
        打包结果：{pack_dir, zip_path, files, manifest_path}。
    """
    out = Path(output_dir).expanduser().resolve()
    pack_dir = out / pack_name
    pack_dir.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    manifest: list[dict[str, Any]] = []

    for wav in wav_files:
        src = Path(wav).expanduser().resolve()
        if not src.is_file():
            continue
        dest = pack_dir / src.name
        shutil.copy2(str(src), str(dest))
        copied.append(dest)

        # 提取该 WAV 的元数据（从同目录 metadata.json）
        meta = _extract_meta_for(src)
        manifest.append({
            "file": src.name,
            "path": str(dest),
            "duration_s": _get_duration(dest),
            "meta": meta,
        })

    # 生成上传清单
    manifest_path = _write_manifest(pack_dir, manifest)

    result: dict[str, Any] = {
        "pack_dir": str(pack_dir),
        "files": [str(p) for p in copied],
        "manifest_path": str(manifest_path),
        "zip_path": None,
    }

    # 生成 zip
    if make_zip and copied:
        zip_path = out / f"{pack_name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in copied:
                zf.write(str(f), arcname=f.name)
            if manifest_path.is_file():
                zf.write(str(manifest_path), arcname=manifest_path.name)
        result["zip_path"] = str(zip_path)

    return result


def write_upload_manifest(
    wav_files: list[str | Path],
    output_path: str | Path,
    format: str = "csv",
) -> Path:
    """生成上传清单（CSV 或 JSON）。

    Args:
        wav_files: Suno 合规片段路径列表。
        output_path: 清单输出路径。
        format: csv | json。

    Returns:
        清单文件路径。
    """
    rows = []
    for wav in wav_files:
        src = Path(wav).expanduser().resolve()
        if not src.is_file():
            continue
        meta = _extract_meta_for(src)
        rows.append({
            "file": src.name,
            "path": str(src),
            "duration_s": _get_duration(src),
            "style": meta.get("style", ""),
            "bpm": meta.get("bpm", ""),
            "seed": meta.get("seed", ""),
            "chords": meta.get("chords", ""),
            "tags": meta.get("tags", ""),
        })

    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    if format == "json":
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        fieldnames = ["file", "path", "duration_s", "style", "bpm", "seed", "chords", "tags"]
        with out.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    return out


# -- 内部 ---------------------------------------------------------------

def _write_manifest(pack_dir: Path, manifest: list[dict[str, Any]]) -> Path:
    """写入 manifest.json。"""
    path = pack_dir / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _extract_meta_for(wav: Path) -> dict[str, Any]:
    """从 WAV 同目录 metadata.json 提取该 WAV 的元数据。"""
    meta_file = wav.parent / "metadata.json"
    if not meta_file.is_file():
        return {}
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        for art in data.get("artifacts", []):
            if art.get("kind") in ("wav", "suno"):
                params = dict(art.get("params", {}))
                params["seed"] = art.get("seed")
                params["duration_s"] = art.get("duration_s")
                return params
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _get_duration(wav: Path) -> float:
    """获取 WAV 时长（秒）。"""
    try:
        import soundfile as sf
        return round(sf.info(str(wav)).duration, 2)
    except Exception:
        return 0.0