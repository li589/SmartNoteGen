"""DiffRhythm 适配器（P1 骨架；二期完整实现）。

- P0/P1-非AI 环境不安装 diffrhythm/torch → is_available() 返回 False → AiDependencyError(退出码 6)
- 二期实现要点：8GB 显存必需将 infer 脚本 decode_audio(..., chunked=False) 改为 chunked=True；
  Windows 需 espeak-ng；权重经 hf-mirror.com 下载。
"""

from __future__ import annotations

import importlib.util
from typing import Optional

from smartnotegen.ai.base import AIGenerator
from smartnotegen.exceptions import AiDependencyError


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
            model_dir: 模型目录（二期）。
            chunked: 分块推理（8GB 显存必需，默认 True）。
            device: 推理设备 cuda|cpu。
        """
        self.model_dir = model_dir
        self.chunked = chunked
        self.device = device

    def is_available(self) -> bool:
        """检查 diffrhythm + torch 是否已安装（find_spec 不触发实际 import）。"""
        return (
            importlib.util.find_spec("diffrhythm") is not None
            and importlib.util.find_spec("torch") is not None
        )

    def generate(self, source_wav: str, prompt: str, **kw) -> str:
        """以风格提示/可选旋律生成歌曲草稿 WAV。

        Raises:
            AiDependencyError: P1 依赖未安装（退出码 6）。
            NotImplementedError: 依赖已安装但适配器尚未实现（二期里程碑）。
        """
        if not self.is_available():
            raise AiDependencyError(
                "DiffRhythm 不可用：未安装 P1 依赖（含 CUDA 版 torch + diffrhythm）。\n"
                "请先安装: pip install torch --index-url https://download.pytorch.org/whl/cu121\n"
                "然后: pip install -r requirements/ai.txt\n"
                "Windows 还需安装 espeak-ng 并加入 PATH。",
                code=6,
            )
        # 二期实现：延迟 import + _patch_chunked 注入 chunked=True
        raise NotImplementedError(
            "DiffRhythm 适配器将在二期 AI 冲刺实现（chunked=True + espeak-ng + hf-mirror 权重）"
        )

    def _patch_chunked(self, infer_script: str) -> None:
        """将 infer 脚本 decode_audio(..., chunked=False) 替换为 chunked=True（8GB 显存必需）。"""
        # 二期实现：读脚本 -> 正则替换 -> 写回
        raise NotImplementedError("DiffRhythm _patch_chunked 将在二期 AI 冲刺实现")
