"""生成器包。"""

from sunoauxtool.generators.base import (
    GenerationRequest,
    Generator,
    SeedContext,
    resolve_scale_pitch_classes,
    scale_pitches_in_range,
    chord_tones_in_range,
)
from sunoauxtool.generators.procedural import ProceduralGenerator, STYLE_PRESETS
from sunoauxtool.generators.music21_melody import Music21MelodyGenerator, VARIATION_KINDS

__all__ = [
    "GenerationRequest",
    "Generator",
    "SeedContext",
    "resolve_scale_pitch_classes",
    "scale_pitches_in_range",
    "chord_tones_in_range",
    "ProceduralGenerator",
    "STYLE_PRESETS",
    "Music21MelodyGenerator",
    "VARIATION_KINDS",
]
