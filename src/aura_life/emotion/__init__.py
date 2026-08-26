"""
Aura Emotion System

3-tier emotion hierarchy with real-time emotion detection and management.
"""
from .feelings_wheel import (
    FeelingsWheel,
    EmotionTier,
    CORE_EMOTIONS,
)
from .emotion_engine import (
    EmotionEngine,
    EmotionState,
    ActiveEmotion,
    EmotionSource,
    BlendMode,
)
from .text_emotion_analyzer import (
    TextEmotionAnalyzer,
    EmotionSpike,
)
from .emotion_persistence import (
    EmotionPersistence,
    PersistedEmotion,
    get_emotion_persistence,
)

__all__ = [
    "FeelingsWheel",
    "EmotionTier",
    "CORE_EMOTIONS",
    "EmotionEngine",
    "EmotionState",
    "ActiveEmotion",
    "EmotionSource",
    "BlendMode",
    "TextEmotionAnalyzer",
    "EmotionSpike",
    "EmotionPersistence",
    "PersistedEmotion",
    "get_emotion_persistence",
]
