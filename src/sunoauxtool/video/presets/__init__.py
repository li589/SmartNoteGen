"""平台预设模块。

提供四套平台预设：
- douyin：9:16 竖屏（1080x1920，抖音/快手）
- youtube：16:9 横屏（1920x1080，YouTube/B站）
- instagram：1:1 方形（1080x1080，Instagram）
- official：4:5 竖屏（1080x1350，官网/公众号）

每套预设包含：分辨率、帧率、CRF、色彩配置。
"""

from typing import Dict, Any

# 预设定义
PRESETS: Dict[str, Dict[str, Any]] = {
    "douyin": {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "crf": 18,
        "letterbox": False,
        "safe_area": {"top": 100, "bottom": 100, "left": 50, "right": 50},
    },
    "youtube": {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "crf": 18,
        "letterbox": True,
        "safe_area": {"top": 80, "bottom": 80, "left": 100, "right": 100},
    },
    "instagram": {
        "width": 1080,
        "height": 1080,
        "fps": 30,
        "crf": 18,
        "letterbox": False,
        "safe_area": {"top": 60, "bottom": 60, "left": 60, "right": 60},
    },
    "official": {
        "width": 1080,
        "height": 1350,
        "fps": 30,
        "crf": 18,
        "letterbox": False,
        "safe_area": {"top": 80, "bottom": 80, "left": 80, "right": 80},
    },
}

DEFAULT_PRESET = "douyin"


def get_preset(name: str) -> Dict[str, Any]:
    """获取指定预设。"""
    preset = PRESETS.get(name.lower())
    if preset is None:
        raise ValueError(
            f"未知预设: {name}（可用: {list(PRESETS.keys())}）"
        )
    return preset.copy()


def list_presets() -> list:
    """列出所有预设名称。"""
    return list(PRESETS.keys())


def resolve_preset(name: str) -> Dict[str, Any]:
    """解析预设名称并返回。"""
    if not name:
        return get_preset(DEFAULT_PRESET)
    return get_preset(name)
