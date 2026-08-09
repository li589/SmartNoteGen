"""生成器包。"""

from smartnotegen.generators.base import (
    GenerationRequest,
    Generator,
    SeedContext,
    resolve_scale_pitch_classes,
    scale_pitches_in_range,
    chord_tones_in_range,
)
from smartnotegen.generators.procedural import ProceduralGenerator, STYLE_PRESETS
from smartnotegen.generators.music21_melody import Music21MelodyGenerator, VARIATION_KINDS

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
