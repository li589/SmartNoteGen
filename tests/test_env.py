"""M-1 环境接入单测：ProjectRootResolver + PathResolver 三分支（OK/MISSING/BROKEN）。

路径探测通过 runner 注入，不依赖真实二进制（M-1 验收 6）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from smartnotegen.config import Config
from smartnotegen.env import PathResolver, ProbeStatus, ProjectRootResolver
from smartnotegen.exceptions import ConfigError, ModuleError, RenderError

#: 注入 runner：模拟 fluidsynth 加载 SF2 成功（退出码 0，无错误文本）
_OK_RUNNER = lambda cmd: SimpleNamespace(returncode=0, stdout="FluidSynth runtime version 2.5.7", stderr="")
#: 模拟 SF2 无法识别（退出码 0 但输出错误文本 —— Windows fluidsynth 实际行为）
_BROKEN_RUNNER = lambda cmd: SimpleNamespace(
    returncode=0,
    stdout="",
    stderr="fluidsynth: error: fluid_is_soundfont(): fopen() failed: 'File does not exist.'\n"
    "Parameter '/tmp/x.sf2' not a SoundFont or MIDI file or error occurred identifying it.",
)


def _make_cfg(tmp_path, *, fluidsynth=None, soundfont=None, soundfont_backup=None) -> Config:
    """构造测试用 Config（绝对路径注入）。"""
    cfg = Config()
    return cfg.merge_cli(
        fluidsynth=fluidsynth or str(tmp_path / "fluidsynth.exe"),
        soundfont=soundfont or str(tmp_path / "a.sf2"),
        soundfont_backup=soundfont_backup or str(tmp_path / "b.sf2"),
    )


# ---------------------------------------------------------------------------
# ProjectRootResolver
# ---------------------------------------------------------------------------

def test_project_root_base_injection(tmp_path):
    """显式注入 base 直接返回。"""
    root = ProjectRootResolver(base=tmp_path).resolve()
    assert root == tmp_path.resolve()


def test_project_root_upward_search(tmp_path):
    """向上查找 pyproject.toml。"""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    root = ProjectRootResolver(start=sub).resolve()
    assert root == tmp_path.resolve()


def test_project_root_module_dir_search(tmp_path):
    """向上查找 module/ 目录。"""
    (tmp_path / "module").mkdir()
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    root = ProjectRootResolver(start=sub).resolve()
    assert root == tmp_path.resolve()


def test_project_root_resolve_returns_path(tmp_path):
    """resolve 返回绝对 Path 且不抛错（找不到项目根时回退 start 的兼容语义）。"""
    root = ProjectRootResolver(start=tmp_path).resolve()
    assert isinstance(root, Path)
    assert root.is_absolute()


# ---------------------------------------------------------------------------
# PathResolver：OK 分支
# ---------------------------------------------------------------------------

def test_probe_all_ok(tmp_path):
    """fluidsynth + soundfont 均 OK，且 SF2 可被加载 -> ensure_ready 不抛错。"""
    fs_bin = tmp_path / "fluidsynth.exe"
    fs_bin.write_bytes(b"MZ")
    sf = tmp_path / "good.sf2"
    sf.write_bytes(b"RIFFgood")
    cfg = _make_cfg(tmp_path, fluidsynth=str(fs_bin), soundfont=str(sf),
                    soundfont_backup=str(tmp_path / "backup.sf2"))
    resolver = PathResolver(cfg, project_root=tmp_path, runner=_OK_RUNNER)
    probes = resolver.probe_all()
    status = {p.component: p.status for p in probes}
    assert status["fluidsynth"] == ProbeStatus.OK
    assert status["soundfont"] == ProbeStatus.OK
    resolver.ensure_ready()  # 不应抛错


def test_resolve_soundfont_primary(tmp_path):
    """主音色库存在时返回主库。"""
    sf = tmp_path / "a.sf2"
    sf.write_bytes(b"RIFFa")
    cfg = _make_cfg(tmp_path, soundfont=str(sf))
    resolver = PathResolver(cfg, project_root=tmp_path)
    assert resolver.resolve_soundfont() == sf.resolve()


# ---------------------------------------------------------------------------
# PathResolver：MISSING / BROKEN 分支（module 默认路径 -> ModuleError 7）
# ---------------------------------------------------------------------------

def test_module_fluidsynth_missing_raises_7(tmp_path):
    """module/ 下 fluidsynth 缺失 -> ensure_ready 抛 ModuleError(7)。"""
    cfg = Config().merge_cli(
        fluidsynth="module/fluidsynth/bin/fluidsynth.exe",
        soundfont="module/GeneralUser_GS/GeneralUser-GS/GeneralUser-GS.sf2",
        soundfont_backup="module/GeneralUser_GS/ColomboGMGS2_SF2/ColomboGMGS2.sf2",
    )
    resolver = PathResolver(cfg, project_root=tmp_path)  # tmp 下无 module/
    with pytest.raises(ModuleError) as exc:
        resolver.ensure_ready()
    assert exc.value.code == 7
    assert "fluidsynth" in str(exc.value)


def test_module_soundfont_missing_raises_7(tmp_path):
    """module/ 下主+备选音色库均缺失 -> resolve_soundfont 抛 ModuleError(7)。"""
    fs_bin = tmp_path / "fluidsynth.exe"
    fs_bin.write_bytes(b"MZ")
    cfg = Config().merge_cli(
        fluidsynth=str(fs_bin),
        soundfont="module/x/a.sf2",
        soundfont_backup="module/x/b.sf2",
    )
    resolver = PathResolver(cfg, project_root=tmp_path)
    with pytest.raises(ModuleError) as exc:
        resolver.resolve_soundfont()
    assert exc.value.code == 7


def test_soundfont_broken_load_raises_7(tmp_path):
    """SF2 存在但 fluidsynth 无法加载（BROKEN）-> ensure_ready 抛 ModuleError(7)。"""
    fs_bin = tmp_path / "fluidsynth.exe"
    fs_bin.write_bytes(b"MZ")
    sf = tmp_path / "broken.sf2"
    sf.write_bytes(b"RIFFgarbage")
    cfg = Config().merge_cli(
        fluidsynth=str(fs_bin),
        soundfont="module/x/broken.sf2",  # module 相对路径，指向 project_root 下
        soundfont_backup="module/x/backup.sf2",
    )
    # 实际在 project_root/module/x/broken.sf2 放置文件
    (tmp_path / "module" / "x").mkdir(parents=True)
    (tmp_path / "module" / "x" / "broken.sf2").write_bytes(b"RIFFgarbage")
    resolver = PathResolver(cfg, project_root=tmp_path, runner=_BROKEN_RUNNER)
    probes = resolver.probe_all()
    sf_probe = next(p for p in probes if p.component == "soundfont")
    assert sf_probe.status == ProbeStatus.BROKEN
    with pytest.raises(ModuleError) as exc:
        resolver.ensure_ready()
    assert exc.value.code == 7


# ---------------------------------------------------------------------------
# PathResolver：双音色库回退（M-1e）
# ---------------------------------------------------------------------------

def test_soundfont_backup_fallback(tmp_path):
    """主音色库缺失、备选存在 -> resolve_soundfont 返回备选；ensure_ready 不抛错。"""
    fs_bin = tmp_path / "fluidsynth.exe"
    fs_bin.write_bytes(b"MZ")
    backup = tmp_path / "module" / "x" / "backup.sf2"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"RIFFbackup")
    cfg = Config().merge_cli(
        fluidsynth=str(fs_bin),
        soundfont="module/x/primary.sf2",
        soundfont_backup="module/x/backup.sf2",
    )
    resolver = PathResolver(cfg, project_root=tmp_path, runner=_OK_RUNNER)
    assert resolver.resolve_soundfont() == backup.resolve()
    resolver.ensure_ready()  # 主库 MISSING + 备选 OK -> 不抛错


# ---------------------------------------------------------------------------
# PathResolver：非 module 路径 -> 保持 P0 语义（ConfigError 2 / RenderError 4）
# ---------------------------------------------------------------------------

def test_non_module_soundfont_missing_raises_2(tmp_path):
    """非 module 音色库缺失 -> ConfigError(2)，且 ensure_ready 不抛错（P0 兼容）。"""
    cfg = _make_cfg(tmp_path)  # 全部为绝对路径（非 module）
    resolver = PathResolver(cfg, project_root=tmp_path)
    resolver.ensure_ready()  # 仅记录分级日志
    with pytest.raises(ConfigError) as exc:
        resolver.resolve_soundfont()
    assert exc.value.code == 2


def test_non_module_fluidsynth_missing_raises_4(tmp_path):
    """非 module fluidsynth 缺失 -> resolve_fluidsynth 抛 RenderError(4)。"""
    cfg = Config().merge_cli(fluidsynth=str(tmp_path / "nope.exe"))
    resolver = PathResolver(cfg, project_root=tmp_path)
    with pytest.raises(RenderError) as exc:
        resolver.resolve_fluidsynth()
    assert exc.value.code == 4


def test_probe_sf2_loadable_true(tmp_path):
    """SF2 可加载：退出码 0 且无错误文本 -> True。"""
    fs_bin = tmp_path / "fs.exe"
    fs_bin.write_bytes(b"MZ")
    sf = tmp_path / "ok.sf2"
    sf.write_bytes(b"RIFFok")
    cfg = _make_cfg(tmp_path, fluidsynth=str(fs_bin), soundfont=str(sf))
    resolver = PathResolver(cfg, project_root=tmp_path, runner=_OK_RUNNER)
    assert resolver._probe_sf2_loadable(fs_bin, sf) is True


def test_probe_sf2_loadable_false(tmp_path):
    """SF2 无法识别（含错误文本）-> False。"""
    fs_bin = tmp_path / "fs.exe"
    fs_bin.write_bytes(b"MZ")
    sf = tmp_path / "bad.sf2"
    sf.write_bytes(b"garbage")
    cfg = _make_cfg(tmp_path, fluidsynth=str(fs_bin), soundfont=str(sf))
    resolver = PathResolver(cfg, project_root=tmp_path, runner=_BROKEN_RUNNER)
    assert resolver._probe_sf2_loadable(fs_bin, sf) is False


def test_probe_sf2_loadable_runner_exception(tmp_path):
    """runner 抛异常（启动失败）-> False。"""

    def _boom(cmd):
        raise OSError("no such binary")

    fs_bin = tmp_path / "fs.exe"
    fs_bin.write_bytes(b"MZ")
    sf = tmp_path / "x.sf2"
    sf.write_bytes(b"RIFFx")
    cfg = _make_cfg(tmp_path, fluidsynth=str(fs_bin), soundfont=str(sf))
    resolver = PathResolver(cfg, project_root=tmp_path, runner=_boom)
    assert resolver._probe_sf2_loadable(fs_bin, sf) is False
