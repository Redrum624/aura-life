"""
3-Tier Feelings Wheel

7 core emotions with ~35 secondary and 80+ tertiary emotions.
Based on psychological emotion research for nuanced emotional representation.
"""
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


class EmotionTier(Enum):
    """Emotion hierarchy tier."""
    CORE = "core"
    SECONDARY = "secondary"
    TERTIARY = "tertiary"


# 7 Core emotions
CORE_EMOTIONS = {"happy", "sad", "angry", "fearful", "surprised", "disgusted", "bad"}

# Secondary emotions mapped to their core parent
SECONDARY_EMOTIONS: Dict[str, List[str]] = {
    "happy": ["playful", "content", "interested", "proud", "accepted", "powerful", "peaceful", "trusting", "optimistic"],
    "sad": ["lonely", "vulnerable", "despair", "guilty", "depressed", "hurt"],
    "angry": ["let_down", "humiliated", "bitter", "mad", "aggressive", "frustrated", "distant", "critical"],
    "fearful": ["scared", "anxious", "insecure", "weak", "rejected", "threatened"],
    "surprised": ["startled", "confused", "amazed", "excited"],
    "disgusted": ["disapproving", "disappointed", "awful", "repelled"],
    "bad": ["bored", "busy", "stressed", "tired"]
}

# Tertiary emotions mapped to their secondary parent
TERTIARY_EMOTIONS: Dict[str, List[str]] = {
    # Happy family
    "playful": ["aroused", "cheeky", "flirty"],
    "content": ["free", "joyful"],
    "interested": ["curious", "inquisitive"],
    "proud": ["successful", "confident"],
    "accepted": ["respected", "valued"],
    "powerful": ["courageous", "creative"],
    "peaceful": ["loving", "thankful"],
    "trusting": ["sensitive", "intimate", "passionate"],
    "optimistic": ["hopeful", "inspired"],
    # Sad family
    "lonely": ["isolated", "abandoned"],
    "vulnerable": ["victimised", "fragile"],
    "despair": ["grief", "powerless"],
    "guilty": ["ashamed", "remorseful"],
    "depressed": ["empty", "inferior"],
    "hurt": ["disappointed", "embarrassed"],
    # Angry family
    "let_down": ["betrayed", "resentful"],
    "humiliated": ["disrespected", "ridiculed"],
    "bitter": ["indignant", "violated"],
    "mad": ["furious", "jealous"],
    "aggressive": ["provoked", "hostile"],
    "frustrated": ["infuriated", "annoyed"],
    "distant": ["withdrawn", "numb"],
    "critical": ["sceptical", "dismissive"],
    # Fearful family
    "scared": ["helpless", "frightened"],
    "anxious": ["overwhelmed", "worried"],
    "insecure": ["inadequate", "inferior"],
    "weak": ["worthless", "insignificant"],
    "rejected": ["excluded", "persecuted"],
    "threatened": ["nervous", "exposed"],
    # Surprised family
    "startled": ["shocked", "dismayed"],
    "confused": ["disillusioned", "perplexed"],
    "amazed": ["astonished", "awe"],
    "excited": ["eager", "energetic", "ecstatic"],
    # Disgusted family
    "disapproving": ["judgmental", "embarrassed"],
    "disappointed": ["appalled", "revolted"],
    "awful": ["nauseated", "detestable"],
    "repelled": ["horrified", "hesitant"],
    # Bad family
    "bored": ["indifferent", "apathetic"],
    "busy": ["pressured", "rushed"],
    "stressed": ["overwhelmed", "out_of_control"],
    "tired": ["sleepy", "unfocused"]
}

# Opposing emotion pairs for tension detection
OPPOSING_PAIRS = [
    ("happy", "sad"),
    ("angry", "fearful"),
    ("disgusted", "trusting")
]


class FeelingsWheel:
    """
    3-Tier Feelings Wheel for emotion hierarchy navigation.

    Provides methods to traverse the emotion hierarchy and check relationships.
    """

    # Build reverse lookup maps
    _secondary_to_core: Dict[str, str] = {}
    _tertiary_to_secondary: Dict[str, str] = {}

    @classmethod
    def _build_lookups(cls):
        """Build reverse lookup maps on first use."""
        if not cls._secondary_to_core:
            for core, secondaries in SECONDARY_EMOTIONS.items():
                for sec in secondaries:
                    cls._secondary_to_core[sec] = core

        if not cls._tertiary_to_secondary:
            for sec, tertiaries in TERTIARY_EMOTIONS.items():
                for tert in tertiaries:
                    cls._tertiary_to_secondary[tert] = sec

    @classmethod
    def get_tier(cls, emotion: str) -> EmotionTier:
        """
        Get the tier of an emotion.

        Args:
            emotion: Emotion name

        Returns:
            EmotionTier (CORE, SECONDARY, or TERTIARY)
        """
        cls._build_lookups()

        if emotion in CORE_EMOTIONS:
            return EmotionTier.CORE
        if emotion in cls._secondary_to_core:
            return EmotionTier.SECONDARY
        if emotion in cls._tertiary_to_secondary:
            return EmotionTier.TERTIARY

        return EmotionTier.CORE  # Default fallback

    @classmethod
    def get_core_emotion(cls, emotion: str) -> str:
        """
        Get the core emotion for any emotion (propagate up hierarchy).

        Args:
            emotion: Any emotion name

        Returns:
            The core (top-level) emotion
        """
        cls._build_lookups()

        # Already core
        if emotion in CORE_EMOTIONS:
            return emotion

        # Secondary -> Core
        if emotion in cls._secondary_to_core:
            return cls._secondary_to_core[emotion]

        # Tertiary -> Secondary -> Core
        if emotion in cls._tertiary_to_secondary:
            secondary = cls._tertiary_to_secondary[emotion]
            return cls._secondary_to_core.get(secondary, "happy")

        return "happy"  # Default fallback

    @classmethod
    def get_secondary_emotion(cls, emotion: str) -> Optional[str]:
        """
        Get the secondary emotion for a tertiary emotion.

        Args:
            emotion: A tertiary emotion name

        Returns:
            The parent secondary emotion, or None
        """
        cls._build_lookups()
        return cls._tertiary_to_secondary.get(emotion)

    @classmethod
    def get_emotion_family(cls, core: str) -> List[str]:
        """
        Get all emotions in a core family.

        Args:
            core: A core emotion name

        Returns:
            List of all emotions (core, secondary, tertiary) in the family
        """
        result = [core]
        secondaries = SECONDARY_EMOTIONS.get(core, [])

        for sec in secondaries:
            result.append(sec)
            tertiaries = TERTIARY_EMOTIONS.get(sec, [])
            result.extend(tertiaries)

        return result

    @classmethod
    def are_same_family(cls, emotion1: str, emotion2: str) -> bool:
        """
        Check if two emotions are in the same family.

        Args:
            emotion1: First emotion
            emotion2: Second emotion

        Returns:
            True if same core family
        """
        return cls.get_core_emotion(emotion1) == cls.get_core_emotion(emotion2)

    @classmethod
    def are_opposing(cls, emotion1: str, emotion2: str) -> bool:
        """
        Check if two emotions are opposing.

        Args:
            emotion1: First emotion
            emotion2: Second emotion

        Returns:
            True if emotions are from opposing families
        """
        core1 = cls.get_core_emotion(emotion1)
        core2 = cls.get_core_emotion(emotion2)

        for pair in OPPOSING_PAIRS:
            if (pair[0] == core1 and pair[1] == core2) or \
               (pair[0] == core2 and pair[1] == core1):
                return True

        return False

    @classmethod
    def get_all_emotions(cls) -> Set[str]:
        """Get all emotions across all tiers."""
        cls._build_lookups()
        all_emotions = set(CORE_EMOTIONS)
        all_emotions.update(cls._secondary_to_core.keys())
        all_emotions.update(cls._tertiary_to_secondary.keys())
        return all_emotions
