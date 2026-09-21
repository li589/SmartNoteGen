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

⚠️ 本机与 CI 均未安装 basic-pitch：真实推理路径**未在本仓库验证过**，
调用签名按官方文档（basic-pitch 0.4.x ``predict(model, audio)``）编写并对参数顺序
做了双保险；首次实际安装后请先跑一条音频确认输出后再依赖它。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Optional

from smartnotegen.ai.base import AIGenerator
from smartnotegen.exceptions import AiDependencyError, InputFileError

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
        self._model = None  # 惰性加载的模型实例

    # -- 可用性 ------------------------------------------------------------

    def is_available(self) -> bool:
        """检查 basic_pitch 是否已安装（find_spec 不触发实际 import）。"""
        return importlib.util.find_spec("basic_pitch") is not None

    def _load_model(self):
        """惰性加载 ICModel（权重缺失/下载失败在此转成 AiDependencyError）。"""
        if self._model is None:
            from basic_pitch import ICModel

            try:
                self._model = (
                    ICModel(self.model_path) if self.model_path else ICModel()
                )
            except Exception as exc:
                raise AiDependencyError(
                    f"basic-pitch 模型加载失败（权重下载/损坏？）: {exc}", code=6
                ) from exc
        return self._model

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
        # 官方签名 predict(model, audio) -> (model_output, midi_data, note_events)。
        # 对参数顺序做三重保险：官方位置序 → 历史反序 → 关键字序（各版本 API 有过
        # 两种签名，且都真实存在过；真实推理路径未在本仓库验证，见模块文档）。
        from basic_pitch.inference import predict

        model = self._load_model()
        try:
            output = predict(model, str(src))
        except TypeError:
            try:
                output = predict(str(src), model)
            except TypeError:
                output = predict(model=model, audio=str(src))

        midi_data = getattr(output, "midi_data", None)
        if midi_data is None:  # 兼容裸三元组返回
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
