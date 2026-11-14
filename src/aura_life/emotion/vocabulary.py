"""
Emotion Vocabulary

One table for every emotion name the library emits: name -> (valence, arousal).
Valence runs -1..1 (unpleasant..pleasant), arousal 0..1 (depleted..intensely
activated) -- the two axes of the circumplex model of affect. Mood
(``aura_life.affect.affect_system``) moves toward these points, and the
feelings wheel places a name it does not list by them
(``FeelingsWheel.get_core_emotion``).

Where the values come from: chosen by hand for this library, one ordinal
placement per name on the scale below. No published lexicon was consulted (the
build is offline), so these are placements, not measurements; what the tests
hold them to is order and sign (joyful > content > 0 > sad > despair;
excited > content > sleepy on arousal), never a value to two decimals.

    valence   +/-0.9 extreme (ecstatic, despair) . +/-0.7 strong (joyful, angry)
              +/-0.5 clear (content, disappointed) . +/-0.3 mild (calm, bored)
              +/-0.1 slight (nostalgic, restless) . 0 neutral
    arousal   0.1 depleted (sleepy, empty) . 0.2 deactivated (peaceful, tired, sad)
              0.3 quiet (content; the neutral point) . 0.5 engaged (proud, annoyed)
              0.6 activated (joyful, curious) . 0.75 high (excited, anxious)
              0.9 intense (ecstatic, furious)

The deactivated placements of sadness and the engaged ones of annoyance keep
each mood label's own word inside its own cell of AffectSystem's label grid
(``aura_life.affect.affect_system.mood_label``): sad reads low, annoyed
irritable, anxious anxious.

A name the table does not know reads as :data:`NEUTRAL_POINT` and is logged at
DEBUG -- neutral, never "happy". The table covers every name the library
writes (activity, intimate, chaos, micro-event, goal, work, life-event, dream
and life-chapter emotions, the text analyzer's labels, the feelings wheel,
EmotionEngine's OCEAN baselines, the mood labels) and the words the authored
personas' profiles use in their ``Emotional Baseline``;
``tests/test_mood_model.py`` scans the source for emitted names and fails on
any the table lacks, except the few words it lists as not feelings (a life
chapter's theme, how her money stands). Names are the library's own and are
never renamed here: this maps names, it does not change them.
"""

import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

#: What a name the table does not know reads as: neutral valence, quiet
#: arousal. Given by the humanness program's Task 4 brief ("unknown names ->
#: (0.0, 0.3)"); it is also the entry for "neutral" below.
NEUTRAL_POINT: Tuple[float, float] = (0.0, 0.3)

EMOTION_VOCABULARY: Dict[str, Tuple[float, float]] = {
    # ============= Feelings wheel: happy =============
    "happy": (0.7, 0.55),
    "playful": (0.6, 0.6), "aroused": (0.4, 0.8), "cheeky": (0.5, 0.6), "flirty": (0.5, 0.6),
    "content": (0.5, 0.3), "free": (0.5, 0.5), "joyful": (0.8, 0.6),
    "interested": (0.4, 0.55), "curious": (0.4, 0.6), "inquisitive": (0.3, 0.6),
    "proud": (0.6, 0.55), "successful": (0.6, 0.5), "confident": (0.5, 0.5),
    "accepted": (0.5, 0.35), "respected": (0.5, 0.4), "valued": (0.6, 0.4),
    "powerful": (0.5, 0.65), "courageous": (0.4, 0.65), "creative": (0.4, 0.55),
    "peaceful": (0.5, 0.15), "loving": (0.7, 0.45), "thankful": (0.6, 0.35),
    "trusting": (0.4, 0.3), "sensitive": (0.1, 0.45), "intimate": (0.5, 0.45), "passionate": (0.6, 0.75),
    "optimistic": (0.5, 0.5), "hopeful": (0.5, 0.45), "inspired": (0.6, 0.65),
    # ============= Feelings wheel: sad =============
    "sad": (-0.6, 0.2),
    "lonely": (-0.6, 0.2), "isolated": (-0.6, 0.2), "abandoned": (-0.7, 0.35),
    "vulnerable": (-0.3, 0.45), "victimised": (-0.7, 0.5), "fragile": (-0.4, 0.35),
    "despair": (-0.9, 0.2), "grief": (-0.8, 0.2), "powerless": (-0.7, 0.2),
    "guilty": (-0.6, 0.45), "ashamed": (-0.7, 0.45), "remorseful": (-0.6, 0.35),
    "depressed": (-0.8, 0.15), "empty": (-0.6, 0.1), "inferior": (-0.6, 0.35),
    "hurt": (-0.6, 0.45), "disappointed": (-0.5, 0.35), "embarrassed": (-0.5, 0.6),
    # ============= Feelings wheel: angry =============
    "angry": (-0.7, 0.8),
    "let_down": (-0.5, 0.4), "betrayed": (-0.8, 0.7), "resentful": (-0.6, 0.55),
    "humiliated": (-0.8, 0.65), "disrespected": (-0.6, 0.6), "ridiculed": (-0.7, 0.6),
    "bitter": (-0.6, 0.5), "indignant": (-0.5, 0.7), "violated": (-0.8, 0.7),
    "mad": (-0.7, 0.8), "furious": (-0.8, 0.9), "jealous": (-0.6, 0.7),
    "aggressive": (-0.6, 0.85), "provoked": (-0.5, 0.75), "hostile": (-0.7, 0.8),
    "frustrated": (-0.5, 0.5), "infuriated": (-0.8, 0.9), "annoyed": (-0.4, 0.5),
    "distant": (-0.3, 0.2), "withdrawn": (-0.4, 0.15), "numb": (-0.3, 0.1),
    "critical": (-0.3, 0.55), "sceptical": (-0.2, 0.45), "dismissive": (-0.3, 0.4),
    # ============= Feelings wheel: fearful =============
    "fearful": (-0.7, 0.75),
    "scared": (-0.7, 0.8), "helpless": (-0.7, 0.55), "frightened": (-0.7, 0.85),
    "anxious": (-0.6, 0.75), "overwhelmed": (-0.6, 0.8), "worried": (-0.5, 0.65),
    "insecure": (-0.5, 0.55), "inadequate": (-0.6, 0.4),
    "weak": (-0.5, 0.2), "worthless": (-0.8, 0.2), "insignificant": (-0.6, 0.2),
    "rejected": (-0.7, 0.45), "excluded": (-0.6, 0.4), "persecuted": (-0.8, 0.7),
    "threatened": (-0.7, 0.8), "nervous": (-0.4, 0.7), "exposed": (-0.5, 0.65),
    # ============= Feelings wheel: surprised =============
    "surprised": (0.1, 0.75),
    "startled": (-0.2, 0.8), "shocked": (-0.3, 0.85), "dismayed": (-0.5, 0.65),
    "confused": (-0.2, 0.5), "disillusioned": (-0.5, 0.35), "perplexed": (-0.2, 0.5),
    "amazed": (0.6, 0.8), "astonished": (0.4, 0.85), "awe": (0.6, 0.65),
    "excited": (0.7, 0.8), "eager": (0.6, 0.7), "energetic": (0.5, 0.75), "ecstatic": (0.9, 0.9),
    # ============= Feelings wheel: disgusted =============
    "disgusted": (-0.6, 0.55),
    "disapproving": (-0.4, 0.45), "judgmental": (-0.3, 0.45),
    "appalled": (-0.7, 0.7), "revolted": (-0.7, 0.65),
    "awful": (-0.6, 0.45), "nauseated": (-0.6, 0.45), "detestable": (-0.7, 0.5),
    "repelled": (-0.6, 0.55), "horrified": (-0.8, 0.85), "hesitant": (-0.2, 0.45),
    # ============= Feelings wheel: bad =============
    "bad": (-0.4, 0.4),
    "bored": (-0.3, 0.15), "indifferent": (-0.1, 0.15), "apathetic": (-0.3, 0.1),
    "busy": (-0.1, 0.65), "pressured": (-0.4, 0.7), "rushed": (-0.3, 0.75),
    "stressed": (-0.5, 0.7), "out_of_control": (-0.6, 0.8),
    "tired": (-0.3, 0.15), "sleepy": (-0.1, 0.1), "unfocused": (-0.2, 0.35),

    # ============= Names the library adds to the wheel =============
    # Activities, intimate activities, micro-events, chaos, goals, work days,
    # life events, dreams, anticipations and the text analyzer's extra labels.
    "absorbed": (0.4, 0.5), "affectionate": (0.7, 0.45), "amused": (0.6, 0.55),
    "awed": (0.6, 0.65), "calm": (0.3, 0.15), "centered": (0.4, 0.2),
    "clear": (0.3, 0.35), "comfortable": (0.4, 0.2), "conflicted": (-0.3, 0.55),
    "connected": (0.6, 0.4), "contemplative": (0.1, 0.3), "cozy": (0.5, 0.2),
    "delighted": (0.8, 0.65), "desire": (0.3, 0.7), "determined": (0.3, 0.65),
    "discouraged": (-0.5, 0.2), "dissatisfied": (-0.4, 0.4), "doubtful": (-0.3, 0.4),
    "drained": (-0.4, 0.1), "dreading": (-0.6, 0.7), "dreamy": (0.3, 0.2),
    "ecstasy": (0.9, 0.9), "empathetic": (0.2, 0.45), "empowered": (0.6, 0.65),
    "energized": (0.5, 0.75), "exhausted": (-0.4, 0.05), "flustered": (0.1, 0.7),
    "focused": (0.3, 0.55), "fulfilled": (0.7, 0.35), "grateful": (0.7, 0.35),
    "guarded": (-0.2, 0.5), "introspective": (0.1, 0.25), "longing": (-0.1, 0.55),
    "lost": (-0.5, 0.2), "motivated": (0.5, 0.65), "moved": (0.5, 0.5),
    "nostalgic": (0.1, 0.3), "nurturing": (0.6, 0.35), "pleasure": (0.8, 0.6),
    "refreshed": (0.5, 0.45), "relaxed": (0.5, 0.15), "relieved": (0.5, 0.25),
    "resigned": (-0.4, 0.15), "resolve": (0.3, 0.55), "rested": (0.4, 0.25),
    "restless": (-0.1, 0.7), "satisfied": (0.6, 0.3), "secure": (0.5, 0.25),
    "sensual": (0.5, 0.55), "strange": (-0.1, 0.5), "sympathetic": (0.1, 0.4),
    "thoughtful": (0.2, 0.35), "uncomfortable": (-0.4, 0.45), "uneasy": (-0.4, 0.55),
    "unsettled": (-0.4, 0.55), "warm": (0.6, 0.35), "wistful": (-0.2, 0.25),
    "wonder": (0.6, 0.6),
    # A life chapter's feelings (ContinuitySystem's dominant_emotions), at the
    # points of "successful" and "exhausted".
    "accomplishment": (0.6, 0.5), "exhaustion": (-0.4, 0.05),

    # ============= Mood labels =============
    # AffectSystem's labels (``MOOD_LABELS``), each placed inside its own cell
    # of the label grid (``mood_label``), and the retired labels a persisted
    # row or life event may still carry ("blue", "raw").
    "neutral": NEUTRAL_POINT,
    "irritable": (-0.5, 0.45), "low": (-0.5, 0.2), "flat": (-0.05, 0.15),
    "blue": (-0.5, 0.2), "raw": (-0.5, 0.6),
}

# Her appraisal of the user's turn (humanness Task 16a,
# aura_life.emotion.user_appraisal): concern and irritation, each at the
# point of the name the text analyzer already reads the word as
# (EMOTION_KEYWORDS: "concerned" -> worried, "irritated" -> annoyed).
EMOTION_VOCABULARY["concerned"] = EMOTION_VOCABULARY["worried"]
EMOTION_VOCABULARY["irritated"] = EMOTION_VOCABULARY["annoyed"]


def normalize(name: str) -> str:
    """The table's form of a name: stripped, lower case, words joined by "_"
    (the feelings wheel's own spelling, as in "let_down")."""
    return "_".join(str(name).strip().lower().split())


def is_known(name: str) -> bool:
    """True when the table has an entry for ``name``."""
    return normalize(name) in EMOTION_VOCABULARY


def valence_arousal(name: str) -> Tuple[float, float]:
    """``(valence, arousal)`` for an emotion name; :data:`NEUTRAL_POINT`
    (logged at DEBUG) for a name the table does not know."""
    point = EMOTION_VOCABULARY.get(normalize(name))
    if point is None:
        logger.debug("Emotion %r is not in the vocabulary; reading it as neutral %s", name, NEUTRAL_POINT)
        return NEUTRAL_POINT
    return point
