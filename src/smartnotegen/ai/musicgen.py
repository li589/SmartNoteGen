"""MusicGen 适配器（P1 骨架；二期完整实现）。

- P0/P1-非AI 环境不安装 audiocraft/torch → is_available() 返回 False → AiDependencyError(退出码 6)
- 二期实现要点：audiocraft.models.MusicGen.get_pretrained("facebook/musicgen-medium")（fp16），
  melody conditioning 用 generate_with_chroma；model_size=small 降档；--seed 可复现。
"""

from __future__ import annotations

import importlib.util
from typing import Optional

from smartnotegen.ai.base import AIGenerator
from smartnotegen.exceptions import AiDependencyError

#: 模型规格 -> HuggingFace 模型名
_MODEL_SIZES = {
    "medium": "facebook/musicgen-medium",
    "small": "facebook/musicgen-small",
}


class MusicGenAdapter(AIGenerator):
    """MusicGen 适配器（melody conditioning 扩编曲）。"""

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: str = "cuda",
        model_size: str = "medium",
    ) -> None:
        """初始化。

        Args:
            model_name: 显式模型名；None 时按 model_size 选择。
            device: 推理设备 cuda|cpu。
            model_size: medium|small（默认 medium）。
        """
        if model_size not in _MODEL_SIZES:
            raise AiDependencyError(
                f"未知模型规格: {model_size!r}（可选 medium|small）", code=6
            )
        self.model_name = model_name or _MODEL_SIZES[model_size]
        self.device = device
        self.model_size = model_size

    def is_available(self) -> bool:
        """检查 audiocraft + torch 是否已安装（find_spec 不触发实际 import）。"""
        return (
            importlib.util.find_spec("audiocraft") is not None
            and importlib.util.find_spec("torch") is not None
        )

    def check_vram(self) -> Optional[float]:
        """返回可用显存 GB；无 CUDA 返回 None。二期实现。"""
        return None

    def generate(self, source_wav: str, prompt: str, **kw) -> str:
        """以旋律 WAV 为条件生成伴奏 WAV。

        Raises:
            AiDependencyError: P1 依赖未安装（退出码 6）。
            NotImplementedError: 依赖已安装但适配器尚未实现（二期里程碑）。
        """
        if not self.is_available():
            raise AiDependencyError(
                "MusicGen 不可用：未安装 P1 依赖。\n"
                "请先安装: pip install torch --index-url https://download.pytorch.org/whl/cu121\n"
                "然后: pip install -r requirements/ai.txt",
                code=6,
            )
        # 二期实现：延迟导入 audiocraft 后在此完成推理（generate_with_chroma）
        raise NotImplementedError(
            "MusicGen 适配器将在二期 AI 冲刺实现（audiocraft medium fp16 + generate_with_chroma）"
        )
