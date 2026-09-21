"""R7 下载源适配器测试：catcatch 直通 + API 源契约（mock HTTP）。

API 契约（与 sources/api.py docstring 一致，两端同步修改）：
- GET {endpoint}?id={query}，Authorization: Bearer {token}
- 响应 {"files": [{"url", "name"}, ...]}
- 逐个下载到 out_dir
"""

from __future__ import annotations

import io
import json
import urllib.request

import pytest
from typer.testing import CliRunner

from sunoauxtool.aggregate import app
from sunoauxtool.download.sources.api import ApiSource, load_source_config
from sunoauxtool.download.sources.base import list_sources
from sunoauxtool.download.sources.catcatch import CatCatchSource
from sunoauxtool.exceptions import (
    SourceCredentialError,
    SourceRequestError,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------


def test_source_registry():
    names = {s.name for s in list_sources()}
    assert names == {"catcatch", "suno-api", "haimeng", "tianyin"}


def test_api_source_unknown_name_rejected():
    with pytest.raises(ValueError):
        ApiSource("not-a-source")


# ---------------------------------------------------------------------------
# 配置加载（凭证缺失 -> 25）
# ---------------------------------------------------------------------------


def test_load_config_missing_file_exit_25(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))  # 隔离 ~ 候选

    monkeypatch.setattr(
        "sunoauxtool.download.sources.api.CONFIG_CANDIDATES",
        [tmp_path / "none.toml"],
    )
    with pytest.raises(SourceCredentialError) as exc:
        load_source_config("suno-api")
    assert exc.value.code == 25


def test_load_config_ok_and_merge(tmp_path, monkeypatch):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "sources.toml").write_text(
        '[sources."suno-api"]\nendpoint = "https://api.example.com/v1/songs"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sunoauxtool.download.sources.api.CONFIG_CANDIDATES",
        [tmp_path / "cfg" / "sources.toml"],
    )
    cfg = load_source_config("suno-api")
    assert cfg["endpoint"].endswith("/songs")
    # token 可缺省
    assert "token" not in cfg
    # 缺 endpoint -> 25
    (tmp_path / "cfg" / "sources.toml").write_text(
        '[sources."haimeng"]\ntoken = "abc"\n', encoding="utf-8"
    )
    with pytest.raises(SourceCredentialError):
        load_source_config("haimeng")


# ---------------------------------------------------------------------------
# API 契约（mock urlopen）
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _make_urlopen(calls: list, responses: list[bytes | Exception]):
    """顺序返回预设响应，并记录每次请求。"""

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        item = responses[len([c for c in calls]) - 1]
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(item)

    return fake_urlopen


@pytest.fixture()
def api_env(tmp_path, monkeypatch):
    """写入临时配置并隔离 CONFIG_CANDIDATES。"""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "sources.toml").write_text(
        '[sources."suno-api"]\nendpoint = "https://api.example.com/v1/songs"\ntoken = "T0K"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sunoauxtool.download.sources.api.CONFIG_CANDIDATES",
        [cfg_dir / "sources.toml"],
    )
    return tmp_path


def test_api_source_contract(api_env, tmp_path):
    """契约：请求行/鉴权头/JSON 结构/落盘命名。"""
    src = ApiSource("suno-api")
    listing = json.dumps(
        {"files": [{"url": "https://cdn.example.com/a1.mp3", "name": "song.mp3"},
                   {"url": "https://cdn.example.com/b2.wav"}]}
    ).encode()
    file_bytes = [b"ID3AUDIO", b"RIFFWAV"]
    calls: list = []
    src.urlopen = _make_urlopen(calls, [listing, file_bytes[0], file_bytes[1]])

    out = tmp_path / "out"
    files = src.fetch("song-42", out)

    # 1) 列表请求：endpoint + id 参数 + Bearer 头
    req0 = calls[0]
    assert req0.full_url.startswith("https://api.example.com/v1/songs?")
    assert "id=song-42" in req0.full_url
    assert req0.get_header("Authorization") == "Bearer T0K"
    # 2) 两个文件按序下载
    assert len(files) == 2
    assert files[0].path == out / "song.mp3" and files[0].path.read_bytes() == b"ID3AUDIO"
    # 3) 缺 name 时从 URL 推断
    assert files[1].path == out / "b2.wav" and files[1].path.read_bytes() == b"RIFFWAV"
    assert files[0].source == "suno-api"


def test_api_source_bad_json_exit_26(api_env, tmp_path):
    src = ApiSource("suno-api")
    src.urlopen = _make_urlopen([], [b"not-json"])
    with pytest.raises(SourceRequestError) as exc:
        src.fetch("q", tmp_path)
    assert exc.value.code == 26


def test_api_source_missing_files_key_exit_26(api_env, tmp_path):
    src = ApiSource("suno-api")
    src.urlopen = _make_urlopen([], [json.dumps({"data": []}).encode()])
    with pytest.raises(SourceRequestError, match="files"):
        src.fetch("q", tmp_path)


def test_api_source_http_error_exit_26(api_env, tmp_path):
    src = ApiSource("suno-api")
    src.urlopen = _make_urlopen([], [urllib.error.HTTPError("u", 401, "no", None, io.BytesIO())])
    with pytest.raises(SourceRequestError) as exc:
        src.fetch("q", tmp_path)
    assert exc.value.code == 26


def test_api_source_credential_missing_exit_25(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "sunoauxtool.download.sources.api.CONFIG_CANDIDATES",
        [tmp_path / "none.toml"],
    )
    src = ApiSource("tianyin")
    with pytest.raises(SourceCredentialError) as exc:
        src.fetch("q", tmp_path / "out")
    assert exc.value.code == 25


# ---------------------------------------------------------------------------
# catcatch 直通（能力复用，mock 转码）
# ---------------------------------------------------------------------------


def test_catcatch_source_fetch(tmp_path, encrypted_bytes, make_fmp4, monkeypatch):
    import sunoauxtool.download.sources.catcatch as cc

    d = tmp_path / "cache"
    d.mkdir()
    (d / "enc.m4a").write_bytes(encrypted_bytes)
    (d / "song.mp3").write_bytes(make_fmp4())
    out = tmp_path / "out"
    monkeypatch.setattr(
        cc, "decode_fmp4", lambda f, o, **kw: [o / "song.opus"]
    )

    src = CatCatchSource()
    files = src.fetch(str(d), out)
    assert len(files) == 1
    assert files[0].path == out / "song.opus"
    assert files[0].meta["from"] == "song.mp3"


def test_catcatch_source_missing_dir_exit_3(tmp_path):
    src = CatCatchSource()
    from sunoauxtool.exceptions import InputFileError

    with pytest.raises(InputFileError):
        src.fetch(str(tmp_path / "nope"), tmp_path)


# ---------------------------------------------------------------------------
# CLI：post fetch --source
# ---------------------------------------------------------------------------


def test_cli_fetch_catcatch_default(tmp_path, make_fmp4, monkeypatch):
    """CLI 猫抓路径 = downloadhelper batch 直通（mock 打在 download_cli）。"""
    import sunoauxtool.download.cli as dl_cli

    d = tmp_path / "cache"
    d.mkdir()
    (d / "a.mp3").write_bytes(make_fmp4())
    monkeypatch.setattr(dl_cli, "decode_fmp4", lambda f, o, **kw: [o / "a.opus"])
    result = runner.invoke(app, ["post", "fetch", str(d), "-o", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    assert "解码成功 1 个文件" in result.output  # batch 报告口径保持


def test_cli_fetch_api_source(api_env, tmp_path):
    out = tmp_path / "out"
    listing = json.dumps({"files": [{"url": "https://cdn.x/1.mp3", "name": "1.mp3"}]}).encode()
    calls: list = []

    # 在 CLI 进程内 mock ApiSource.urlopen

    orig_init = ApiSource.__init__

    def patched_init(self, name):
        orig_init(self, name)
        self.urlopen = _make_urlopen(calls, [listing, b"MUSIC"])

    monkeypatch = api_env  # noqa: F841 (配置已就位)
    ApiSource.__init__ = patched_init
    try:
        result = runner.invoke(
            app,
            ["post", "fetch", "song-7", "--source", "suno-api", "-o", str(out)],
        )
    finally:
        ApiSource.__init__ = orig_init
    assert result.exit_code == 0, result.output
    assert "取回 1 个文件" in result.output
    assert (out / "1.mp3").read_bytes() == b"MUSIC"


def test_cli_fetch_unknown_source_exit_1(tmp_path):
    result = runner.invoke(
        app, ["post", "fetch", str(tmp_path), "--source", "netdisk"]
    )
    assert result.exit_code == 1
    assert "未知下载源" in result.output


def test_cli_fetch_api_missing_credentials_exit_25(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "sunoauxtool.download.sources.api.CONFIG_CANDIDATES",
        [tmp_path / "none.toml"],
    )
    result = runner.invoke(
        app, ["post", "fetch", "song-7", "--source", "haimeng", "-o", str(tmp_path / "o")]
    )
    assert result.exit_code == 25
