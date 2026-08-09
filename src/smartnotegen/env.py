"""module 环境接入：项目根解析 + 路径分级探测（OK/MISSING/BROKEN）。

设计要点（docs/architecture-P1P2.md §1.1）：
- ProjectRootResolver：向上查找 pyproject.toml / module 目录定位项目根；
  可注入 base 供测试覆盖；找不到时回退 start（保持 P0 行为）。
- PathResolver：fluidsynth / SoundFont 路径解析与三分级探测；
  runner 可注入（Callable[[list[str]], CompletedProcess]）以便单测不依赖真实二进制。
- 双音色库：默认 SoundFont（GeneralUser-GS）缺失时自动回退备选（ColomboGMGS2）。
- 禁静默 mock：仅 --dry-run 允许 mock；探测失败按分级给出修复指引并抛错。

错误码语义：
- 默认 module 环境（配置值以 module/ 开头或位于项目根 module/ 下）缺失/损坏 -> ModuleError(7)
- 非 module 路径（用户显式配置/内置兼容默认）缺失：
    fluidsynth -> RenderError(4)（与 P0 renderer 一致）；SoundFont -> ConfigError(2)（与 P0 一致）
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional, Union

from smartnotegen.config import Config
from smartnotegen.exceptions import ConfigError, ModuleError, RenderError
from smartnotegen.logging_setup import get_logger

logger = get_logger("env")

#: subprocess.run 返回类型（兼容注入 runner 的鸭子类型）
CompletedProcessLike = Union[subprocess.CompletedProcess, object]


class ProbeStatus(Enum):
    """路径探测结果分级。"""

    OK = "OK"          # 存在且可用
    MISSING = "MISSING"  # 路径不存在
    BROKEN = "BROKEN"    # 存在但不可用（不可执行 / SF2 无法加载）


@dataclass
class EnvProbe:
    """单个组件的探测结果。"""

    component: str                    # "fluidsynth" | "soundfont" | "soundfont_backup"
    status: ProbeStatus
    path: Optional[Path] = None
    detail: str = ""                  # 修复指引（人类可读）
    is_module_default: bool = False   # 是否为默认 module 环境路径（决定错误码 7 还是 2/4）


class ProjectRootResolver:
    """项目根探测：向上查找 pyproject.toml / module 目录；可注入 base 供测试覆盖。"""

    def __init__(
        self,
        start: Optional[Path] = None,
        base: Optional[Path] = None,
    ) -> None:
        """初始化。

        Args:
            start: 探测起点（目录或文件）；None 时取当前工作目录。
            base: 显式注入的项目根（测试用）；非 None 时直接返回，不做向上查找。
        """
        self.start = Path(start) if start is not None else Path.cwd()
        self.base = Path(base) if base is not None else None

    def resolve(self) -> Path:
        """返回项目根目录。

        探测顺序：base（显式注入，测试用）> start 向上找 pyproject.toml 或 module/ > start。
        找不到时回退 start（不抛错，保持 P0 行为）。
        """
        if self.base is not None:
            return self.base.resolve()
        current = self.start
        if current.is_file():
            current = current.parent
        for candidate in [current, *current.parents]:
            if (candidate / "pyproject.toml").is_file() or (candidate / "module").is_dir():
                return candidate.resolve()
        return current.resolve()


class PathResolver:
    """module 路径解析与分级探测。可注入 runner 供单测（不依赖真实二进制）。"""

    def __init__(
        self,
        config: Config,
        project_root: Optional[Path] = None,
        runner: Optional[Callable[[List[str]], CompletedProcessLike]] = None,
    ) -> None:
        """初始化。

        Args:
            config: 合并后的生效配置（fluidsynth/soundfont/soundfont_backup 均来自此处）。
            project_root: 项目根；None 时用 ProjectRootResolver 自动探测。
            runner: subprocess 运行器注入（单测用）；None 时使用 subprocess.run。
        """
        self.config = config
        self.project_root = (
            Path(project_root).resolve()
            if project_root is not None
            else ProjectRootResolver().resolve()
        )
        self.runner = runner

    # -- 路径解析 ----------------------------------------------------------

    def _resolve_config_path(self, value: str) -> Path:
        """将配置值解析为绝对路径：相对路径按项目根解析。"""
        p = Path(value).expanduser()
        if p.is_absolute():
            return p
        return (self.project_root / p).resolve()

    def _is_module_path(self, value: str, resolved: Optional[Path] = None) -> bool:
        """判断配置值是否属于「默认 module 环境」路径。

        判定规则：路径首段为 module，或解析后位于项目根 module/ 目录下。
        """
        parts = Path(value).parts
        if parts and parts[0] == "module":
            return True
        if resolved is not None:
            module_dir = (self.project_root / self.config.paths.module_dir).resolve()
            try:
                resolved.relative_to(module_dir)
                return True
            except ValueError:
                pass
        return False

    def resolve_fluidsynth(self) -> Path:
        """解析最终使用的 fluidsynth 可执行文件路径。

        优先级：显式路径（绝对/项目根相对）> PATH 查找（仅裸名）> 报错。

        Raises:
            ModuleError: 默认 module 路径缺失（错误码 7）。
            RenderError: 非 module 路径缺失/不可用（错误码 4，与 P0 一致）。
        """
        value = self.config.paths.fluidsynth
        resolved = self._resolve_config_path(value)
        is_module = self._is_module_path(value, resolved)
        if resolved.is_file():
            return resolved
        # 仅裸名（无路径分隔）做 PATH 查找，避免 module/xxx 相对路径被 CWD 命中
        if "/" not in value and "\\" not in value:
            found = shutil.which(value)
            if found:
                return Path(found)
        if is_module:
            raise ModuleError(
                "渲染环境不完整: fluidsynth 缺失\n"
                f"  ✗ MISSING fluidsynth: {resolved} 不存在\n"
                "    修复: 请确认已下载 fluidsynth win64 发行版到 module/fluidsynth/，"
                "或通过 --fluidsynth 指定绝对路径",
                code=7,
            )
        raise RenderError(
            f"配置的 fluidsynth 路径无效: {value}\n"
            "请在配置 [paths] fluidsynth 指定绝对路径，或将 fluidsynth 加入 PATH",
            code=4,
        )

    def resolve_soundfont(self) -> Path:
        """解析最终使用的 SoundFont 路径。

        双音色库回退（M-1e）仅对「默认 module 路径」生效：主库（module/...）缺失时
        自动尝试备选库；非 module 路径（用户显式配置/内置兼容默认）缺失时直接报错
        （不静默回退，避免掩盖用户配置错误）。

        Raises:
            ModuleError: 默认 module 音色库（主+备选）均缺失（错误码 7）。
            ConfigError: 非 module 音色库缺失（错误码 2，与 P0 一致）。
        """
        primary_value = self.config.paths.soundfont
        primary = self._resolve_config_path(primary_value)
        primary_module = self._is_module_path(primary_value, primary)
        if primary.is_file():
            return primary

        if primary_module:
            backup_value = self.config.paths.soundfont_backup
            backup = self._resolve_config_path(backup_value)
            if backup.is_file():
                logger.info("主音色库缺失，自动回退备选音色库: %s", backup)
                return backup
            raise ModuleError(
                "渲染环境不完整: 默认 SoundFont 缺失\n"
                f"  ✗ MISSING soundfont: {primary} 不存在\n"
                f"  ✗ MISSING soundfont_backup: {backup} 不存在\n"
                "    修复: 请确认已下载 GeneralUser GS 音色库到 module/GeneralUser_GS/，"
                "或通过 --soundfont 指定",
                code=7,
            )
        raise ConfigError(
            f"SoundFont 文件不存在: {primary}\n"
            "请下载 GeneralUser GS / FluidR3 放入 assets/soundfonts/ 并在配置 [paths] soundfont 中指定",
            code=2,
        )

    # -- 探测 --------------------------------------------------------------

    def _probe_fluidsynth(self) -> EnvProbe:
        """探测 fluidsynth：文件存在 + 可执行（Windows 上以文件存在 + os.access 判定）。"""
        value = self.config.paths.fluidsynth
        resolved = self._resolve_config_path(value)
        is_module = self._is_module_path(value, resolved)
        if resolved.is_file():
            if not os.access(resolved, os.X_OK):
                return EnvProbe(
                    "fluidsynth", ProbeStatus.BROKEN, resolved,
                    f"存在但不可执行: {resolved}（请检查文件权限/依赖 DLL）", is_module,
                )
            return EnvProbe("fluidsynth", ProbeStatus.OK, resolved, f"可用: {resolved}", is_module)
        # 仅裸名（无路径分隔）做 PATH 查找
        if "/" not in value and "\\" not in value:
            found = shutil.which(value)
            if found:
                return EnvProbe("fluidsynth", ProbeStatus.OK, Path(found), f"PATH 命中: {found}", is_module)
        if is_module:
            return EnvProbe(
                "fluidsynth", ProbeStatus.MISSING, resolved,
                f"缺失: {resolved} 不存在\n修复: 请确认已下载 fluidsynth win64 发行版到 "
                f"module/fluidsynth/，或通过 --fluidsynth 指定绝对路径", True,
            )
        return EnvProbe(
            "fluidsynth", ProbeStatus.MISSING, resolved,
            f"未找到 fluidsynth（配置: {value!r}）\n修复: 请将 fluidsynth 加入 PATH，"
            f"或在配置 [paths] fluidsynth 指定绝对路径", False,
        )

    def _probe_soundfont(self, key: str) -> EnvProbe:
        """探测单个 SoundFont 的存在性（可加载性由 probe_all 中统一校验）。"""
        value = getattr(self.config.paths, key)
        resolved = self._resolve_config_path(value)
        is_module = self._is_module_path(value, resolved)
        if not resolved.is_file():
            if is_module:
                return EnvProbe(
                    key, ProbeStatus.MISSING, resolved,
                    f"缺失: {resolved} 不存在\n修复: 请确认已下载 GeneralUser GS 音色库到 "
                    f"module/GeneralUser_GS/，或通过 --soundfont 指定", True,
                )
            return EnvProbe(
                key, ProbeStatus.MISSING, resolved,
                f"缺失: {resolved} 不存在\n修复: 请通过 --soundfont 指定有效的 .sf2 路径", False,
            )
        return EnvProbe(key, ProbeStatus.OK, resolved, f"存在: {resolved}", is_module)

    def _probe_sf2_loadable(self, fs: Path, sf: Path) -> bool:
        """跑 fluidsynth 加载校验（非渲染）：退出码 0 且无识别错误文本视为可加载。

        注意：Windows 版 fluidsynth 对无法识别的文件仍返回 0，但会在输出中打印
        "not a SoundFont or MIDI file" / "error occurred identifying it"，
        因此以「退出码 0 且无上述错误文本」作为可加载判定。
        """
        cmd = [str(fs), "-ni", str(sf)]
        try:
            if self.runner is not None:
                result = self.runner(cmd)
            else:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL
                )
        except Exception:  # 启动失败/超时/注入 runner 抛错 -> 视为不可加载
            logger.warning("SF2 加载校验失败（无法启动 fluidsynth 或超时）: %s", sf)
            return False
        combined = str(getattr(result, "stdout", "") or "") + str(getattr(result, "stderr", "") or "")
        if "not a SoundFont or MIDI file" in combined or "error occurred identifying" in combined:
            return False
        return getattr(result, "returncode", -1) == 0

    def probe_all(self) -> List[EnvProbe]:
        """三分级探测：fluidsynth / soundfont / soundfont_backup。

        - 主音色库缺失但备选存在：主库 probe 保持 MISSING（detail 标注回退），备选 probe OK。
        - 当 fluidsynth OK 且音色库文件存在时，进一步执行 SF2 可加载性校验（BROKEN 判定）。
        """
        probes: List[EnvProbe] = [self._probe_fluidsynth()]
        sf_probe = self._probe_soundfont("soundfont")
        backup_probe = self._probe_soundfont("soundfont_backup")
        if sf_probe.status != ProbeStatus.OK and backup_probe.status == ProbeStatus.OK:
            sf_probe.detail = f"{sf_probe.detail}\n（主音色库缺失，自动回退备选音色库）"
        probes.append(sf_probe)
        probes.append(backup_probe)

        fs_probe = probes[0]
        if fs_probe.status == ProbeStatus.OK and fs_probe.path is not None:
            for probe in (sf_probe, backup_probe):
                if probe.status == ProbeStatus.OK and probe.path is not None:
                    if not self._probe_sf2_loadable(fs_probe.path, probe.path):
                        probe.status = ProbeStatus.BROKEN
                        probe.detail = f"{probe.detail}\n（fluidsynth 无法加载该 SoundFont: {probe.path}）"
        return probes

    def ensure_ready(self) -> None:
        """确保渲染环境可用。

        分级行为：
        - 默认 module 环境缺失/损坏（fluidsynth 或音色库）-> ModuleError(7)；
        - 非 module 的 BROKEN（用户提供了存在但不可加载的文件）-> 显式报错
          （SoundFont -> ConfigError(2)，fluidsynth -> RenderError(4)），避免静默产出坏音频；
        - 非 module 的 MISSING（内置兼容默认/用户路径缺失）只记录分级日志，
          由下游 FluidSynthRenderer 按 P0 语义抛 ConfigError(2)/RenderError(4)。
        """
        probes = self.probe_all()
        for p in probes:
            if p.status != ProbeStatus.OK:
                logger.warning("环境探测 [%s] %s: %s", p.status.value, p.component, p.detail)
            else:
                logger.debug("环境探测 [OK] %s: %s", p.component, p.path)

        soundfonts = [p for p in probes if p.component in ("soundfont", "soundfont_backup")]
        has_ok_sf = any(p.status == ProbeStatus.OK for p in soundfonts)

        # 1) 默认 module 环境硬错误（fluidsynth；或音色库全部不可用时的主库）-> ModuleError(7)
        bad_fluidsynth = next(
            (p for p in probes if p.component == "fluidsynth" and p.status != ProbeStatus.OK), None
        )
        if bad_fluidsynth is not None and bad_fluidsynth.is_module_default:
            self._raise_module_error(bad_fluidsynth)
        # module 主音色库 BROKEN（存在但不可加载）：即使有备选也不静默使用损坏主库
        for p in probes:
            if (
                p.component == "soundfont"
                and p.status == ProbeStatus.BROKEN
                and p.is_module_default
            ):
                self._raise_module_error(p)
        if not has_ok_sf:
            primary = next((p for p in probes if p.component == "soundfont"), soundfonts[0])
            if primary.is_module_default:
                self._raise_module_error(primary)

        # 2) 非 module 的 BROKEN -> 显式报错（不静默产出坏音频）
        for p in probes:
            if p.component == "soundfont_backup":
                continue
            if p.status == ProbeStatus.BROKEN and not p.is_module_default:
                if p.component == "fluidsynth":
                    raise RenderError(f"fluidsynth 不可用: {p.detail}", code=4)
                raise ConfigError(f"SoundFont 不可用: {p.detail}", code=2)

    @staticmethod
    def _raise_module_error(probe: EnvProbe) -> None:
        """对默认 module 环境缺失/损坏抛 ModuleError(7)。"""
        raise ModuleError(
            "渲染环境不完整: 环境探测未通过\n"
            f"  ✗ {probe.status.value} {probe.component}: {probe.detail}\n"
            "修复: 请检查 module/ 目录完整性（fluidsynth 二进制与 SoundFont 音色库），"
            "或通过 --fluidsynth / --soundfont 指定有效路径",
            code=7,
        )
