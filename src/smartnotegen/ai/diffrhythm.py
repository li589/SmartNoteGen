"""DiffRhythm 适配器（二期完整实现）。

- 完整歌曲草稿（带人声）生成：风格提示（+ 可选歌词）-> ≥60s 歌曲 WAV
- 8GB 显存必需：`chunked=True` 默认（_patch_chunked 自动注入 infer 脚本，用户无需改脚本）
- 依赖 espeak-ng（Windows 需 .msi 并加入 PATH）；权重经 hf-mirror 下载
- 延迟导入：本模块顶部零 torch/diffrhythm import（P0 模块零重型 import 约束）
- 草稿不自动进 Suno 导出链（含人声，CLI 不提供联动）
- DiffRhythm 官方仓库不可 pip 安装：适配器以子进程方式运行仓库 infer/infer.py
  （仓库存在 cwd 相对路径依赖：./config/xxx.json、./g2p/g2p/vocab.json、infer/example/vocal.npy）
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from smartnotegen.ai.base import AIGenerator
from smartnotegen.exceptions import AiDependencyError, ParameterError

#: DiffRhythm 最低显存要求。T-S1 spike（RTX 4060 8GB）实测峰值 6954 MiB（6.8GB）。
#: 判断分两层：显卡总显存 >= 7800 MiB（≈8GB，8GB 卡实际报告 8188 MiB，避免浮点 7.999<8.0 误判）；
#: 启动时可用显存 >= 6.8GB（保证峰值可容纳）。
_MIN_VRAM_MIB = 7800 * 1024 * 1024  # 7800 MiB（字节）
_MIN_FREE_GB = 6.8

#: 输出采样率（DiffRhythm 官方默认 44.1kHz）
OUTPUT_SAMPLE_RATE = 44100

#: 合法时长：95 或 96-285（官方限制）
_SUPPORTED_DURATIONS = "95 或 96-285"

_INSTALL_GUIDE = (
    "DiffRhythm 不可用：未安装 P1 依赖或仓库未就绪。\n"
    "1. 安装 CUDA 版 torch + torchaudio：\n"
    "     pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121\n"
    "2. 安装其余 AI 依赖：\n"
    "     pip install -r requirements/ai.txt\n"
    "3. 克隆 DiffRhythm 仓库到 module/diffrhythm（或设置环境变量 DIFFRHYTHM_DIR）：\n"
    "     git clone https://github.com/ASLP-lab/DiffRhythm.git module/diffrhythm\n"
    "4. Windows 需安装 espeak-ng（.msi）并加入 PATH：\n"
    "     https://github.com/espeak-ng/espeak-ng/releases\n"
    "5. 权重下载较慢时设置环境变量 HF_ENDPOINT=https://hf-mirror.com 使用国内镜像。"
)


class DiffRhythmAdapter(AIGenerator):
    """DiffRhythm 适配器（完整歌曲草稿，含人声）。"""

    def __init__(
        self,
        model_dir: Optional[str] = None,
        chunked: bool = True,
        device: str = "cuda",
    ) -> None:
        """初始化。

        Args:
            model_dir: DiffRhythm 仓库根目录；None 时按 DIFFRHYTHM_DIR 环境变量
                或项目根 module/diffrhythm 查找。
            chunked: 分块推理（8GB 显存必需，默认 True）。
            device: 推理设备 cuda|cpu。
        """
        self.model_dir = model_dir
        self.chunked = chunked
        self.device = device

    # -- 仓库发现 ----------------------------------------------------------

    def repo_dir(self) -> Optional[Path]:
        """定位 DiffRhythm 仓库根目录（含 infer/infer.py）。"""
        candidates: list[Optional[Path]] = []
        if self.model_dir:
            candidates.append(Path(self.model_dir).expanduser())
        env_dir = os.environ.get("DIFFRHYTHM_DIR") or os.environ.get("SMARTNOTEGEN_DIFFRHYTHM_DIR")
        if env_dir:
            candidates.append(Path(env_dir).expanduser())
        candidates.append(Path.cwd() / "module" / "diffrhythm")
        for cand in candidates:
            if cand is None:
                continue
            if (cand / "infer" / "infer.py").is_file():
                return cand.resolve()
        return None

    # -- 可用性 ------------------------------------------------------------

    def is_available(self) -> bool:
        """检查 torch 已安装 + 仓库就绪 + espeak-ng 可用（find_spec 不触发 import）。"""
        torch_ok = importlib.util.find_spec("torch") is not None
        repo_ok = self.repo_dir() is not None
        espeak_ok = self._check_espeak()
        return torch_ok and repo_ok and espeak_ok

    def check_vram(self) -> Optional[float]:
        """返回当前可用显存 GB；无 CUDA 返回 None。"""
        try:
            import torch  # 延迟导入
        except ImportError:  # pragma: no cover - 依赖缺失路径由 is_available 拦截
            return None
        if not torch.cuda.is_available():
            return None
        try:
            free, _total = torch.cuda.mem_get_info(0)
        except (AttributeError, RuntimeError):  # pragma: no cover - 老版本/驱动异常兜底
            props = torch.cuda.get_device_properties(0)
            free = props.total_memory
        return free / (1024**3)

    def _espeak_dir(self) -> Optional[str]:
        """返回 espeak-ng 可执行文件所在目录（供子进程 PATH 注入）。"""
        exe = shutil.which("espeak-ng") or shutil.which("espeak")
        if exe:
            return str(Path(exe).parent)
        # Windows 常见安装位置（PATH 未刷新时兜底）
        for cand in (
            Path(r"C:\Program Files\eSpeak NG"),
            Path(r"C:\Program Files (x86)\eSpeak NG"),
            Path(os.environ.get("PROGRAMFILES", "")) / "eSpeak NG",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "eSpeak NG",
        ):
            if (cand / "espeak-ng.exe").is_file():
                return str(cand)
        return None

    def _espeak_library(self) -> Optional[str]:
        """返回 espeak-ng DLL 路径（供 PHONEMIZER_ESPEAK_LIBRARY 注入）。"""
        env_lib = os.environ.get("PHONEMIZER_ESPEAK_LIBRARY")
        if env_lib and Path(env_lib).is_file():
            return env_lib
        d = self._espeak_dir()
        if d:
            for name in ("libespeak-ng.dll", "espeak-ng.dll", "libespeak.dll"):
                cand = Path(d) / name
                if cand.is_file():
                    return str(cand)
        return None

    def _check_espeak(self) -> bool:
        """检查 espeak-ng 是否可用（shutil.which + 常见安装位置，不触发重型 import）。"""
        return self._espeak_dir() is not None

    # -- chunked 补丁 ------------------------------------------------------

    def _patch_chunked(self, infer_script: str) -> None:
        """将 infer 脚本中 decode_audio/inference 的 chunked 强制为 True（8GB 显存必需）。

        兼容两种写法：
          - `decode_audio(latent, vae_model, chunked=False)` / `chunked=chunked`
          - `def inference(..., chunked=False)` 默认参数

        Args:
            infer_script: infer/infer.py 路径。

        Raises:
            AiDependencyError: 未定位到 chunked 参数（脚本结构已变化）。
        """
        p = Path(infer_script)
        if not p.is_file():
            raise AiDependencyError(f"infer 脚本不存在: {p}", code=6)
        src = p.read_text(encoding="utf-8")
        # 幂等：已补丁（含 chunked=True）则直接返回
        if "chunked=True" in src:
            return
        pat_call = re.compile(r"(decode_audio\([^)]*?chunked\s*=\s*)(?:False|chunked)(\))")
        new_src, n_call = pat_call.subn(r"\1True\2", src)
        pat_sig = re.compile(r"(def inference\([^)]*?chunked\s*=\s*)False")
        new_src, n_sig = pat_sig.subn(r"\1True", new_src)
        if n_call + n_sig == 0:
            raise AiDependencyError(
                f"未能定位 infer 脚本中的 chunked 参数（脚本可能已升级）: {p}", code=6
            )
        p.write_text(new_src, encoding="utf-8")

    # -- 推理 --------------------------------------------------------------

    def _build_lrc(self, lyrics: Optional[str], duration: float, out_path: Path) -> Path:
        """把歌词字符串转为简单 LRC 文件（行级时间戳均匀分布）。

        无歌词时写出空 LRC（DiffRhythm 按哼唱/空词处理）。
        """
        lines = [ln.strip() for ln in (lyrics or "").splitlines() if ln.strip()]
        n = max(len(lines), 1)
        seg = duration / n
        buf = ["[ti:SmartNoteGen]"]
        for i, line in enumerate(lines):
            secs = i * seg
            mm = int(secs // 60)
            ss = secs % 60
            buf.append(f"[{mm:02d}:{ss:05.2f}]{line}")
        out_path.write_text("\n".join(buf) + "\n", encoding="utf-8")
        return out_path

    def _resolve_duration(self, duration: Optional[float]) -> float:
        """校验时长：官方支持 95 或 96-285。"""
        d = 95.0 if duration is None else float(duration)
        if d != 95.0 and not (96.0 <= d <= 285.0):
            raise ParameterError(
                f"duration 非法: {d:g}（DiffRhythm 支持 {_SUPPORTED_DURATIONS}s）", code=1
            )
        return d

    def _ensure_vram(self) -> None:
        """显存前置检查（T-S1 spike 数据驱动）。

        - 无 CUDA（--device cuda 但无 GPU）-> 提示改用 cpu
        - 显卡总显存 < 8GB -> 明确不可用（NO-GO 语义）
        - 可用显存 < 6.8GB -> 提示关闭其他占用 GPU 的应用（避免 OOM）
        """
        import torch  # 延迟导入

        if not torch.cuda.is_available():
            raise AiDependencyError(
                "DiffRhythm 需要 CUDA GPU（--device cuda 但未检测到 CUDA）。\n"
                "请使用 --device cpu 显式降级（极慢，仅试听）或检查驱动。",
                code=6,
            )
        props = torch.cuda.get_device_properties(0)
        free, _total = torch.cuda.mem_get_info(0)
        free_gb = free / (1024**3)
        if props.total_memory < _MIN_VRAM_MIB:
            raise AiDependencyError(
                "DiffRhythm 需要 ≥8GB 显存且当前环境不可用。\n"
                f"检测到显卡总显存 {props.total_memory / (1024**3):.1f}GB < 8GB。spike 证据见 docs/ai-integration.md（T-S1 报告）。\n"
                "降级路径: 使用 MusicGen（ai musicgen）生成器乐伴奏；人声歌曲草稿暂不可用。",
                code=6,
            )
        if free_gb < _MIN_FREE_GB:
            raise AiDependencyError(
                f"当前可用显存不足（{free_gb:.1f}GB < 需 {_MIN_FREE_GB:.1f}GB）。\n"
                "请关闭其他占用 GPU 的应用（浏览器/剪辑软件等）后重试；spike 实测峰值约 6.8GB。",
                code=6,
            )

    def generate(
        self,
        source_wav: str,
        prompt: str,
        *,
        lyrics: Optional[str] = None,
        duration: Optional[float] = None,
        seed: Optional[int] = None,
        output_path: Optional[str] = None,
        **_kw,
    ) -> str:
        """以风格提示（+ 可选歌词）生成完整歌曲草稿 WAV（含人声）。

        Args:
            source_wav: 可选旋律/参考音频 WAV（当前 DiffRhythm 仅使用风格提示；保留接口兼容）。
            prompt: 风格提示，如 "slow ballad"。
            lyrics: 歌词（纯文本，行分隔）；None/空串为无词哼唱。
            duration: 目标时长（秒）；默认 95；支持 95 或 96-285。
            seed: 保留参数（DiffRhythm 推理当前不支持确定性种子，会记录日志）。
            output_path: 输出 WAV 路径；None 时自动命名。

        Returns:
            输出 WAV 绝对路径字符串。

        Raises:
            AiDependencyError: 依赖未安装 / 显存不足 / 仓库缺失（退出码 6）。
            ParameterError: duration 非法（退出码 1）。
        """
        if seed is not None:
            # DiffRhythm 推理含随机性且官方脚本未暴露 seed；记录提示而非静默忽略
            print(f"[DiffRhythm] 提示: 当前 DiffRhythm 推理不支持确定性 --seed（忽略 seed={seed}）")

        if not self.is_available():
            raise AiDependencyError(_INSTALL_GUIDE, code=6)

        repo = self.repo_dir()
        assert repo is not None  # is_available() 已保证
        infer_script = repo / "infer" / "infer.py"

        # 显存检查（T-S1 spike 数据驱动：总显存 ≥8GB 且可用 ≥6.8GB）
        if self.device == "cuda":
            self._ensure_vram()

        target_duration = self._resolve_duration(duration)

        # 落地 chunked=True 补丁（幂等：已补丁则跳过）
        src_text = infer_script.read_text(encoding="utf-8")
        if "chunked=True" not in src_text:
            self._patch_chunked(str(infer_script))

        # 准备歌词 LRC（放入临时目录）
        work_dir = Path(output_path).expanduser().resolve().parent if output_path else repo / "infer" / "output"
        work_dir.mkdir(parents=True, exist_ok=True)
        lrc_path = work_dir / "_smartnotegen_lyrics.lrc"
        self._build_lrc(lyrics, target_duration, lrc_path)

        # 输出目录（子进程写 output.wav 后由本进程改名）
        out_dir = work_dir / "_smartnotegen_run"
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            str(infer_script),
            "--lrc-path", str(lrc_path),
            "--ref-prompt", prompt,
            "--audio-length", str(int(target_duration)),
            "--output-dir", str(out_dir),
        ]
        if self.chunked:
            cmd.append("--chunked")

        env = dict(os.environ)
        env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        if self.device == "cpu":
            env["CUDA_VISIBLE_DEVICES"] = ""
        # espeak-ng 目录注入 PATH（PATH 未刷新时也能被 phonemizer 找到）
        espeak_dir = self._espeak_dir()
        if espeak_dir and espeak_dir not in env.get("PATH", "").split(os.pathsep):
            env["PATH"] = espeak_dir + os.pathsep + env.get("PATH", "")
        # phonemizer 通过 DLL 路径定位 espeak-ng（Windows 常见：libespeak-ng.dll）
        espeak_lib = self._espeak_library()
        if espeak_lib:
            env["PHONEMIZER_ESPEAK_LIBRARY"] = espeak_lib
        # 仓库根 + thirdparty 需要进入 PYTHONPATH（LangSegment 等相对导入）
        pythonpath = os.pathsep.join(
            [str(repo), str(repo / "thirdparty"), env.get("PYTHONPATH", "")]
        )
        env["PYTHONPATH"] = pythonpath

        result = subprocess.run(
            cmd,
            cwd=str(repo),
            env=env,
            capture_output=True,
            text=True,
            timeout=3600,
        )
        if result.returncode != 0:
            tail = (result.stderr or result.stdout)[-800:]
            raise AiDependencyError(
                f"DiffRhythm 推理失败（退出码 {result.returncode}）。\n{tail}", code=6
            )

        generated = out_dir / "output.wav"
        if not generated.is_file():
            raise AiDependencyError(
                f"DiffRhythm 推理结束但未找到输出: {generated}", code=6
            )

        if output_path:
            final_path = Path(output_path).expanduser().resolve()
        elif source_wav and Path(source_wav).suffix:
            final_path = Path(source_wav).with_name(f"{Path(source_wav).stem}_song.wav")
        else:
            final_path = repo / "infer" / "output" / "output.wav"
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(generated), str(final_path))
        return str(final_path)
