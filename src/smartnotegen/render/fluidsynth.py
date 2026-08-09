"""FluidSynth 渲染器：.mid → WAV（44.1kHz/16bit）。

通过 subprocess 调用 fluidsynth 二进制（可配置绝对路径、module 相对路径或 PATH 中的可执行名）。
midi2audio 为本项目的声明依赖，但为精确控制二进制路径与采样格式，
这里直接构造 fluidsynth 命令行（与架构 §4.2 时序图一致）。

M-1 扩展：
- module 相对路径解析：fluidsynth/soundfont 配置值如 "module/..." 按项目根解析
  （ProjectRootResolver），缺失时抛 ModuleError(7)（默认 module 环境不完整）。
- 双音色库回退：主音色库缺失时自动使用 soundfont_backup（若提供）。
- dry_run：跳过 subprocess，打印将执行的命令（仅 --dry-run 允许 mock 行为，不写产物）。
"""

from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from smartnotegen.exceptions import ConfigError, InputFileError, ModuleError, RenderError
from smartnotegen.logging_setup import get_logger

logger = get_logger("render.fluidsynth")


class Renderer(ABC):
    """渲染器抽象接口。"""

    @abstractmethod
    def render(self, midi_path: str, soundfont: str, out_path: str) -> str:
        """将 .mid 渲染为 WAV，返回输出路径。"""
        raise NotImplementedError


class FluidSynthRenderer(Renderer):
    """基于 FluidSynth 的渲染器。"""

    def __init__(
        self,
        fluidsynth_path: Optional[str] = None,
        sample_rate: int = 44100,
        gain: float = 0.6,
        soundfont_backup: Optional[str] = None,
        project_root: Optional[Path] = None,
    ) -> None:
        """初始化。

        Args:
            fluidsynth_path: fluidsynth 可执行文件路径（PATH 中的名字、module 相对路径或绝对路径）。
            sample_rate: 输出采样率（默认 44.1kHz）。
            gain: 渲染增益（0.6 为默认，防爆音）。
            soundfont_backup: 备选音色库（主库缺失时回退；M-1e）。
            project_root: 项目根（module 相对路径解析用）；None 时自动探测。
        """
        self.fluidsynth_path = fluidsynth_path
        self.sample_rate = sample_rate
        self.gain = gain
        self.soundfont_backup = soundfont_backup
        self.project_root = Path(project_root) if project_root is not None else None

    def render(
        self,
        midi_path: str,
        soundfont: str,
        out_path: str,
        dry_run: bool = False,
    ) -> str:
        """渲染 MIDI 为 WAV。

        Args:
            midi_path: 输入 .mid 路径。
            soundfont: .sf2 音色库路径（module 相对路径或绝对路径）。
            out_path: 输出 .wav 路径。
            dry_run: True 时不调用 subprocess、不写产物，打印将执行的命令（M-1f）。

        Returns:
            输出 WAV 绝对路径。

        Raises:
            InputFileError: midi 文件不存在。
            ModuleError: 默认 module 环境不完整（fluidsynth/SoundFont 缺失，错误码 7）。
            ConfigError: 非 module 的 SoundFont 缺失（错误码 2）。
            RenderError: fluidsynth 找不到或渲染进程失败（错误码 4）。
        """
        midi = Path(midi_path).expanduser().resolve()
        if not midi.is_file():
            raise InputFileError(f"MIDI 文件不存在: {midi}", code=3)

        target = Path(out_path).expanduser().resolve()
        if target.suffix.lower() != ".wav":
            target = target.with_suffix(".wav")

        # dry-run：仅打印将执行的命令，不校验/不解析路径、不写任何产物（M-1f）
        if dry_run:
            logger.info(
                "[DRY-RUN] 将执行: fluidsynth -ni -F %s -R %d -O s16 -g %.2f %s %s",
                target, self.sample_rate, self.gain, soundfont, midi,
            )
            return str(target)

        sf = self._resolve_soundfont(soundfont)
        target.parent.mkdir(parents=True, exist_ok=True)

        fluidsynth_bin = self._resolve_fluidsynth()
        cmd = [
            fluidsynth_bin,
            "-ni",  # 非交互
            "-F", str(target),
            "-R", str(self.sample_rate),
            "-O", "s16",  # 16bit PCM
            "-g", f"{self.gain:.2f}",
            str(sf),
            str(midi),
        ]
        if dry_run:
            logger.info("[DRY-RUN] 将执行: %s", " ".join(cmd))
            return str(target)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except OSError as exc:
            raise RenderError(f"无法启动 fluidsynth: {exc}", code=4) from exc

        if result.returncode != 0 or not target.is_file():
            tail = (result.stderr or result.stdout or "").strip()[-500:]
            raise RenderError(
                f"FluidSynth 渲染失败（退出码 {result.returncode}）: {tail}", code=4
            )
        return str(target)

    # -- 路径解析 ----------------------------------------------------------

    def _resolve_project_root(self) -> Path:
        """返回项目根（module 相对路径解析基准）。"""
        if self.project_root is not None:
            return self.project_root
        from smartnotegen.env import ProjectRootResolver

        return ProjectRootResolver().resolve()

    def _resolve_path(self, value: str) -> tuple[Path, bool]:
        """将配置值解析为绝对路径；返回 (绝对路径, 是否 module 默认路径)。"""
        p = Path(value).expanduser()
        if p.is_absolute():
            return p, self._looks_module(p)
        root = self._resolve_project_root()
        resolved = (root / p).resolve()
        return resolved, self._looks_module(resolved)

    def _looks_module(self, p: Path) -> bool:
        """判断路径是否属于默认 module 环境（首段 module 或位于项目根 module/ 下）。"""
        parts = p.parts
        if parts and parts[0] == "module":
            return True
        root = self._resolve_project_root()
        module_dir = (root / "module").resolve()
        try:
            p.resolve().relative_to(module_dir)
            return True
        except ValueError:
            return False

    def _resolve_soundfont(self, soundfont: str) -> str:
        """解析音色库：主库存在则用之；module 主库缺失时回退备选；否则按类型报错。"""
        sf, is_module = self._resolve_path(soundfont)
        if sf.is_file():
            return str(sf)
        # 双音色库回退（M-1e）仅对默认 module 路径生效
        if is_module and self.soundfont_backup:
            sf2, _is_module2 = self._resolve_path(self.soundfont_backup)
            if sf2.is_file():
                logger.info("主音色库缺失，自动回退备选音色库: %s", sf2)
                return str(sf2)
            raise ModuleError(
                "渲染环境不完整: 默认 SoundFont 缺失\n"
                f"  ✗ MISSING soundfont: {sf} 不存在\n"
                f"  ✗ MISSING soundfont_backup: {sf2} 不存在\n"
                "    修复: 请确认已下载 GeneralUser GS 音色库到 module/GeneralUser_GS/，"
                "或通过 --soundfont 指定",
                code=7,
            )
        if is_module:
            raise ModuleError(
                "渲染环境不完整: SoundFont 缺失\n"
                f"  ✗ MISSING soundfont: {sf} 不存在\n"
                "    修复: 请确认已下载 GeneralUser GS 音色库到 module/GeneralUser_GS/，"
                "或通过 --soundfont 指定",
                code=7,
            )
        raise ConfigError(
            f"SoundFont 文件不存在: {sf}\n"
            "请下载 GeneralUser GS / FluidR3 放入 assets/soundfonts/ 并在配置 [paths] soundfont 中指定",
            code=2,
        )

    def _resolve_fluidsynth(self) -> str:
        """解析 fluidsynth 可执行文件路径。

        优先级：显式路径（绝对/module 相对）> PATH 查找 > 报错。
        默认 module 路径缺失 -> ModuleError(7)；其余 -> RenderError(4)。
        """
        if self.fluidsynth_path:
            p = Path(self.fluidsynth_path).expanduser()
            if p.is_absolute():
                if p.is_file():
                    return str(p)
                if self._looks_module(p):
                    raise ModuleError(
                        "渲染环境不完整: fluidsynth 缺失\n"
                        f"  ✗ MISSING fluidsynth: {p} 不存在\n"
                        "    修复: 请确认已下载 fluidsynth win64 发行版到 module/fluidsynth/，"
                        "或通过 --fluidsynth 指定绝对路径",
                        code=7,
                    )
                raise RenderError(
                    f"配置的 fluidsynth 路径无效: {self.fluidsynth_path}\n"
                    "请在配置 [paths] fluidsynth 指定绝对路径，或将 fluidsynth 加入 PATH",
                    code=4,
                )
            # 相对路径：先按项目根解析；仅裸名（无路径分隔）才做 PATH 查找
            resolved, is_module = self._resolve_path(self.fluidsynth_path)
            if resolved.is_file():
                return str(resolved)
            if "/" not in self.fluidsynth_path and "\\" not in self.fluidsynth_path:
                found = shutil.which(self.fluidsynth_path)
                if found:
                    return found
            if is_module:
                raise ModuleError(
                    "渲染环境不完整: fluidsynth 缺失\n"
                    f"  ✗ MISSING fluidsynth: {resolved} 不存在\n"
                    "    修复: 请确认已下载 fluidsynth win64 发行版到 module/fluidsynth/，"
                    "或通过 --fluidsynth 指定绝对路径",
                    code=7,
                )
            raise RenderError(
                f"配置的 fluidsynth 路径无效: {self.fluidsynth_path}\n"
                "请在配置 [paths] fluidsynth 指定绝对路径，或将 fluidsynth 加入 PATH",
                code=4,
            )
        found = shutil.which("fluidsynth")
        if found:
            return found
        raise RenderError(
            "未找到 fluidsynth。请安装 fluidsynth 2.x win64 二进制（GitHub releases），\n"
            "将 bin/ 加入 PATH，或在配置 [paths] fluidsynth 指定绝对路径。",
            code=4,
        )
