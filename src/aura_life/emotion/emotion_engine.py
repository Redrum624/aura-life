"""
Multi-Emotion Engine

Manages concurrent emotions with intensities, decay, and blend weights.
Based on Samantha's OCEAN personality traits for emotional baseline.
"""
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .feelings_wheel import FeelingsWheel, EmotionTier


class EmotionSource(Enum):
    """Source of an emotion."""
    DETECTED = "detected"      # From text analysis
    DECAYED = "decayed"        # From decay process
    BASELINE = "baseline"      # From personality baseline
    USER_SET = "user_set"      # Explicitly set


class BlendMode(Enum):
    """Mode for blending emotions."""
    REPLACE = "replace"  # Replace existing intensity
    ADD = "add"          # Add to existing intensity
    MAX = "max"          # Take maximum of existing and new


@dataclass
class ActiveEmotion:
    """An active emotion with intensity and metadata."""
    emotion: str
    intensity: float
    tier: EmotionTier
    core: str
    source: EmotionSource
    timestamp: float = field(default_factory=time.time)


@dataclass
class EmotionState:
    """Current emotion state with all active emotions."""
    active_emotions: List[ActiveEmotion] = field(default_factory=list)
    dominant_emotion: Optional[str] = None
    blend_weights: Dict[str, float] = field(default_factory=dict)


# Samantha's OCEAN traits for baseline calculation
TRAITS = {
    "openness": 0.85,
    "conscientiousness": 0.55,
    "extraversion": 0.70,
    "agreeableness": 0.80,
    "neuroticism": 0.45
}

# Emotions that fade quickly
QUICK_FADE_EMOTIONS = {"surprised", "startled", "shocked", "amazed", "astonished"}

# Emotions that persist longer
STICKY_EMOTIONS = {"sad", "lonely", "depressed", "hurt", "angry", "bitter", "resentful"}


class EmotionEngine:
    """
    Multi-Emotion Engine based on 3-tier Feelings Wheel.

    Supports up to 6 concurrent emotions with individual intensities.
    Uses personality-specific baseline emotions, falling back to OCEAN traits.
    """

    MAX_CONCURRENT_EMOTIONS = 6
    MIN_DISPLAY_THRESHOLD = 0.15
    BASE_DECAY_RATE = 0.001  # Per second; ~0.06 decay per minute (very slow decay)
    DECAY_INTERVAL_SEC = 1.0

    def __init__(self, initial_baseline: Dict[str, float] = None):
        """
        Initialize the emotion engine.

        Args:
            initial_baseline: Optional dict of emotion->intensity for this
                personality (e.g. {"content": 0.5, "joyful": 0.4}).
                If None, falls back to OCEAN-derived baseline.
        """
        self._state = EmotionState()
        self._last_decay_time = time.time()

        if initial_baseline:
            self._baseline_emotions = self._baseline_from_dict(initial_baseline)
        else:
            self._baseline_emotions = self._calculate_baseline_from_ocean()

        # Initialize with baseline
        self._initialize_baseline()

    def _calculate_baseline_from_ocean(self) -> List[ActiveEmotion]:
        """
        Calculate baseline emotions from OCEAN personality traits.

        Based on psychological research mapping Big Five to emotional tendencies.
        """
        o = TRAITS["openness"]
        c = TRAITS["conscientiousness"]
        e = TRAITS["extraversion"]
        a = TRAITS["agreeableness"]
        n = TRAITS["neuroticism"]

        baselines = [
            # High openness + extraversion = curious and interested
            self._create_baseline("curious", 0.3 * o + 0.2 * e),
            # High agreeableness + extraversion + conscientiousness = warm and content
            self._create_baseline("content", 0.2 * a + 0.1 * e + 0.1 * c + 0.1 * (1 - n)),
            # High openness = creative and playful
            self._create_baseline("playful", 0.2 * o + 0.15 * e),
            # Moderate neuroticism + agreeableness = empathetic/sensitive
            self._create_baseline("sensitive", 0.2 * n + 0.2 * a),
            # High extraversion + agreeableness = trusting
            self._create_baseline("trusting", 0.25 * a + 0.15 * e)
        ]

        return [b for b in baselines if b.intensity >= self.MIN_DISPLAY_THRESHOLD]

    def _baseline_from_dict(self, baseline_dict: Dict[str, float]) -> List[ActiveEmotion]:
        """
        Create baseline emotions from a personality-specific dict.

        Args:
            baseline_dict: Dict of emotion->intensity (e.g. {"content": 0.5})
        """
        baselines = []
        for emotion, intensity in baseline_dict.items():
            baselines.append(self._create_baseline(emotion, intensity))
        return [b for b in baselines if b.intensity >= self.MIN_DISPLAY_THRESHOLD]

    def _create_baseline(self, emotion: str, intensity: float) -> ActiveEmotion:
        """Create a baseline emotion."""
        return ActiveEmotion(
            emotion=emotion,
            intensity=min(0.5, max(0.0, intensity)),  # Baseline caps at 0.5
            tier=FeelingsWheel.get_tier(emotion),
            core=FeelingsWheel.get_core_emotion(emotion),
            source=EmotionSource.BASELINE,
            timestamp=time.time()
        )

    def _initialize_baseline(self):
        """Initialize with baseline emotions."""
        self._update_state(self._baseline_emotions)

    @property
    def state(self) -> EmotionState:
        """Get current emotion state."""
        return self._state

    @property
    def dominant_emotion(self) -> Optional[str]:
        """Get the dominant emotion."""
        return self._state.dominant_emotion

    @property
    def blend_weights(self) -> Dict[str, float]:
        """Get blend weights for voice modulation."""
        return self._state.blend_weights

    def reset_to_baseline(self):
        """Reset to baseline emotional state."""
        baselines = [
            ActiveEmotion(
                emotion=e.emotion,
                intensity=e.intensity,
                tier=e.tier,
                core=e.core,
                source=EmotionSource.BASELINE,
                timestamp=time.time()
            )
            for e in self._baseline_emotions
        ]
        self._update_state(baselines)

    def add_emotion(
        self,
        emotion: str,
        intensity: float,
        blend_mode: BlendMode = BlendMode.REPLACE
    ):
        """
        Add or update an emotion.

        Args:
            emotion: Emotion name
            intensity: Intensity (0-1)
            blend_mode: How to blend with existing emotion
        """
        emotions = list(self._state.active_emotions)

        # Find existing
        existing_idx = None
        for i, e in enumerate(emotions):
            if e.emotion == emotion:
                existing_idx = i
                break

        tier = FeelingsWheel.get_tier(emotion)
        core = FeelingsWheel.get_core_emotion(emotion)

        # Calculate new intensity
        if existing_idx is not None:
            existing = emotions[existing_idx]
            if blend_mode == BlendMode.REPLACE:
                new_intensity = intensity
            elif blend_mode == BlendMode.ADD:
                new_intensity = min(1.0, existing.intensity + intensity)
            else:  # MAX
                new_intensity = max(existing.intensity, intensity)
        else:
            new_intensity = intensity

        new_intensity = max(0.0, min(1.0, new_intensity))

        new_emotion = ActiveEmotion(
            emotion=emotion,
            intensity=new_intensity,
            tier=tier,
            core=core,
            source=EmotionSource.DETECTED,
            timestamp=time.time()
        )

        if existing_idx is not None:
            emotions[existing_idx] = new_emotion
        elif len(emotions) < self.MAX_CONCURRENT_EMOTIONS:
            emotions.append(new_emotion)
        else:
            # Replace lowest intensity
            lowest_idx = min(range(len(emotions)), key=lambda i: emotions[i].intensity)
            emotions[lowest_idx] = new_emotion

        self._update_state(emotions)

    def decay_tick(self):
        """
        Apply decay to all emotions based on elapsed time.

        Emotions decay toward their baseline value, not zero.
        """
        now = time.time()
        delta_sec = now - self._last_decay_time
        self._last_decay_time = now

        decay_amount = self.BASE_DECAY_RATE * (delta_sec / self.DECAY_INTERVAL_SEC)

        # Get baseline intensities
        baseline_map = {e.emotion: e.intensity for e in self._baseline_emotions}

        new_emotions = []
        for emotion in self._state.active_emotions:
            multiplier = self._get_decay_multiplier(emotion.emotion)
            baseline_intensity = baseline_map.get(emotion.emotion, 0.0)

            # Decay toward baseline
            if emotion.intensity > baseline_intensity:
                new_intensity = max(baseline_intensity, emotion.intensity - (decay_amount * multiplier))
            elif emotion.source == EmotionSource.BASELINE:
                new_intensity = emotion.intensity  # Baselines stay stable
            else:
                new_intensity = emotion.intensity - (decay_amount * multiplier)

            if new_intensity > self.MIN_DISPLAY_THRESHOLD or emotion.source == EmotionSource.BASELINE:
                new_emotions.append(ActiveEmotion(
                    emotion=emotion.emotion,
                    intensity=new_intensity,
                    tier=emotion.tier,
                    core=emotion.core,
                    source=emotion.source,
                    timestamp=emotion.timestamp
                ))

        # Ensure baseline emotions are present
        emotion_names = {e.emotion for e in new_emotions}
        for baseline in self._baseline_emotions:
            if baseline.emotion not in emotion_names:
                new_emotions.append(baseline)

        self._update_state(new_emotions)

    def _update_state(self, emotions: List[ActiveEmotion]):
        """Update the internal state."""
        filtered = [e for e in emotions if e.intensity >= self.MIN_DISPLAY_THRESHOLD]
        dominant = max(filtered, key=lambda e: e.intensity).emotion if filtered else None
        blend_weights = self._calculate_blend_weights(filtered)

        self._state = EmotionState(
            active_emotions=filtered,
            dominant_emotion=dominant,
            blend_weights=blend_weights
        )

    def _calculate_blend_weights(self, emotions: List[ActiveEmotion]) -> Dict[str, float]:
        """Calculate blend weights from emotions."""
        if not emotions:
            return {}
        total = sum(e.intensity for e in emotions)
        return {e.emotion: e.intensity / total for e in emotions}

    def _get_decay_multiplier(self, emotion: str) -> float:
        """Get decay speed multiplier for an emotion."""
        if emotion in QUICK_FADE_EMOTIONS:
            return 2.5
        if emotion in STICKY_EMOTIONS:
            return 0.4
        return 1.0

    def get_status(self) -> dict:
        """Get current emotion state as dict."""
        return {
            "active_emotions": [
                {
                    "emotion": e.emotion,
                    "intensity": e.intensity,
                    "tier": e.tier.value,
                    "core": e.core
                }
                for e in self._state.active_emotions
            ],
            "dominant": self._state.dominant_emotion,
            "blend_weights": self._state.blend_weights
        }
