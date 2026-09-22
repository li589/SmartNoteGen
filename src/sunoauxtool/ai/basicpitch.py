"""Basic Pitch 适配器（#13 预留，多音轨复调转谱的可选 AI 后端）。

定位
--------
内置转谱（``analysis/transcribe.py``）只做单旋律/主导声部；多音轨复调（钢琴和弦、
多乐器混音）是研究级问题，交给 Spotify 的 basic-pitch（轻量 NMP 模型，CPU 可跑）。

隔离原则（与 ai/musicgen.py 同一模式）：
- 模块顶部零 basic_pitch/torch import；``is_available()`` 用 ``find_spec`` 探测（不触发实际 import）
- 依赖未装 → ``AiDependencyError``（退出码 6），带安装指引
- basic-pitch **不在 base.txt**：走 requirements/ai.txt 可选装（见该文件「可选转谱后端」段）
- 首次运行 ``ICModel()`` 会自动下载约 100MB 权重到用户缓存目录

真实推理已实测（2026-09-22）
--------------------------------
在隔离环境 **Python 3.9 + basic-pitch 0.4.0（onnxruntime 后端）** 实跑通过，
据此修正了三处与真实 API 不符的写法：

1. **``ICModel`` 不存在**：``from basic_pitch import ICModel`` → ImportError
   （0.4.0 顶层只有常量与子模块）。0.4.x 无需手动实例化模型，
   ``predict()`` 第二参默认就是随包安装的 ``saved_models/icassp_2022/nmp.onnx``。
2. **参数顺序是 ``(audio, model)`` 而非 ``(model, audio)``**：
   ``predict(audio_path, model_or_model_path=..., onset_threshold=0.5, ...)``。
3. **顺序写错抛的是 ``ValueError`` 不是 ``TypeError``**（模型路径被当音频去加载），
   因此历史写法里的 ``except TypeError`` 兜不住，必须一开始就用对顺序。

返回值为三元组 ``(model_output: dict, midi_data: PrettyMIDI, note_events: list)``，
``midi_data`` 有 ``.write(path)``。实测 3 秒复调音频（C-E-G 和弦 → A-C）识别出 5 个音符。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Optional

from sunoauxtool.ai.base import AIGenerator
from sunoauxtool.exceptions import AiDependencyError, InputFileError

_INSTALL_GUIDE = (
    "basic-pitch 不可用：未安装可选转谱依赖。\n"
    "请安装: pip install basic-pitch（首次运行会自动下载约 100MB 权重）\n"
    "或继续使用内置单旋律转谱：transcribe --backend builtin"
)


class BasicPitchAdapter(AIGenerator):
    """basic-pitch 复调转谱适配器（可选 AI 后端，#13 预留）。"""

    def __init__(
        self,
        device: str = "cpu",
        model_path: Optional[str] = None,
    ) -> None:
        """初始化。

        Args:
            device: 推理设备（basic-pitch 主要面向 CPU，GPU 传 "cuda" 由其自行处理）。
            model_path: 显式权重路径；None 用默认权重（首次运行自动下载）。
        """
        self.device = device
        self.model_path = model_path

    # -- 可用性 ------------------------------------------------------------

    def is_available(self) -> bool:
        """检查 basic_pitch 是否已安装（find_spec 不触发实际 import）。"""
        return importlib.util.find_spec("basic_pitch") is not None

    def _resolve_model_path(self) -> Optional[str]:
        """解析模型路径（不实际实例化模型，0.4.x predict 内部自行加载）。"""
        if self.model_path:
            p = Path(self.model_path).expanduser().resolve()
            if not p.is_file():
                raise AiDependencyError(
                    f"basic-pitch 模型路径不存在: {p}", code=6
                ) from None
            return str(p)
        return None  # None 表示使用 predict 内置默认模型路径

    # -- 推理 --------------------------------------------------------------

    def transcribe(
        self,
        source_wav: str,
        output_path: Optional[str] = None,
        **_kw,
    ) -> str:
        """把音频转成多音轨 MIDI 文件。

        Args:
            source_wav: 输入音频路径。
            output_path: 输出 .mid 路径；None 时 ``<stem>_basicpitch.mid`` 落在输入旁。

        Returns:
            输出 .mid 绝对路径字符串。

        Raises:
            AiDependencyError: 依赖未装或模型加载失败（退出码 6）。
            InputFileError: 输入文件不存在（退出码 3）。
        """
        if not self.is_available():
            raise AiDependencyError(_INSTALL_GUIDE, code=6)

        src = Path(source_wav).expanduser().resolve()
        if not src.is_file():
            raise InputFileError(f"音频文件不存在: {src}", code=3)

        # 延迟导入（P0 模块零重型 import 约束）
        # 0.4.x 签名：predict(audio, model=...) -> (model_output, midi_data, note_events)。
        # 实测官方顺序，此处直接使用；保留关键字序兜底兼容历史版本。
        #
        # 注意：basic_pitch/__init__.py 的后端选择链 if/elif **没有 else 分支**，
        # 四个后端（tf/coreml/tflite/onnx）一个都没装时会在模块级抛
        # `NameError: _default_model_type is not defined`。这种「装了包但没装后端」
        # 的状态必须报成退出码 6 并给出可操作的指引，而不是漏成退出码 1 的 NameError。
        try:
            from basic_pitch.inference import predict
        except Exception as exc:  # pragma: no cover - 依赖真实环境
            raise AiDependencyError(
                f"basic-pitch 已安装但导入失败（多半是没装推理后端）：{exc}。"
                f"Windows/onnx 路线请执行 `pip install onnxruntime`；"
                f"也可用 `pip install 'basic-pitch[tf]'` 走 TensorFlow 后端。",
                code=6,
            ) from exc

        model = self._resolve_model_path()
        try:
            output = predict(str(src), model) if model is not None else predict(str(src))
        except (TypeError, ValueError):
            kw = {"audio": str(src)}
            if model is not None:
                kw["model"] = model
            output = predict(**kw)

        # 0.4.x 返回三元组 (dict, PrettyMIDI, list)，不用 getattr 裸三元组兼容
        midi_data = output[1]

        out = (
            Path(output_path).expanduser().resolve()
            if output_path
            else src.with_name(f"{src.stem}_basicpitch.mid")
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        midi_data.write(str(out))
        return str(out)

    # AIGenerator 接口适配：basic-pitch 是转谱不是生成，映射为「输入音频 → 输出 MIDI」
    def generate(self, source_wav: str, prompt: str = "", **kw) -> str:
        """AIGenerator 接口兼容：prompt 忽略，行为同 :meth:`transcribe`。"""
        return self.transcribe(source_wav, **kw)
