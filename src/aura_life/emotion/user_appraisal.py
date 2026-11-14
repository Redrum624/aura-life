"""Her appraisal of the user's turn (humanness Task 16a, spec section 4.8).

"The persona appraises the user's emotion (concern, amusement, irritation),
never copies it." :func:`appraise_user_turn` reads the user's emotions (a
host's, or the text analyzer's, name -> intensity) and whether the turn is
aimed at her, against her traits, and returns what she feels:

==========================================  ==========================================
The user's emotion                          She feels
==========================================  ==========================================
hostile (:func:`is_hostile`), aimed at      hurt and irritation, split by her
her                                         volatility: irritated ``i x v``, hurt
                                            ``i x (1 - v)``
playful (:data:`PLAYFUL_EMOTIONS`)          amused, ``i``
any other unpleasant one (vocabulary        concerned, ``i x empathy`` (her warmth,
valence < 0), hostility at something else   ``PersonaParameters.empathy``)
any other pleasant one (valence > 0)        warm (glad for them), ``i x empathy``
==========================================  ==========================================

Every intensity is then times her volatility's multiplier
(``PersonaParameters.affect_reactivity``), applied here once, as Task 14's
event appraisal (:mod:`aura_life.emotion.appraisal`) does: she feels them
with ``reactivity_applied=True``. A name several emotions give is their sum;
each is clamped to 0..1. The user's own label is never one of hers. A warm
word the vocabulary has no name for ("love") is felt by its analyzer label's
valence ("loving"), as its warmth is read for trust (:func:`is_warm`).

Her trust in the user reads :attr:`UserTurnAppraisal.hostility` and
:attr:`UserTurnAppraisal.warmth` (``IdentitySystem.apply_user_turn``): the
strongest hostile (:func:`is_hostile`) and warm (:func:`is_warm`) emotion aimed at her, 0
when the turn is about something else. It draws no randomness and reads no
clock.
"""

from typing import Dict, Mapping, NamedTuple, Optional

from aura_life.emotion.text_emotion_analyzer import EMOTION_KEYWORDS
from aura_life.emotion.vocabulary import is_known, normalize, valence_arousal
from aura_life.personas.parameters import PersonaParameters

#: The labels the text analyzer's "ANGRY FAMILY" block gives
#: (``text_emotion_analyzer.EMOTION_KEYWORDS``): hostility, when aimed at her.
#: A host's name the analyzer reads as one of them is hostility too
#: (:func:`is_hostile`: "angry" is its "mad", "irritated" its "annoyed").
HOSTILE_EMOTIONS = frozenset({
    "aggressive", "annoyed", "bitter", "critical", "dismissive", "frustrated", "furious",
    "hostile", "infuriated", "jealous", "judgmental", "mad", "resentful", "sceptical",
})

#: The labels the analyzer's "PLAYFUL/AMUSED" block gives.
PLAYFUL_EMOTIONS = frozenset({"playful", "cheeky"})

#: Warmth toward her, when aimed at her: the labels the analyzer gives its
#: loving, grateful, trusting/secure and intimate words. A host's name the
#: analyzer reads as one of them is warmth too (:func:`is_warm`).
WARM_EMOTIONS = frozenset({"loving", "thankful", "trusting", "secure", "intimate"})

#: What she feels (every one in the vocabulary).
CONCERN_EMOTION = "concerned"
AMUSEMENT_EMOTION = "amused"
HURT_EMOTION = "hurt"
IRRITATION_EMOTION = "irritated"
GLAD_EMOTION = "warm"


class UserTurnAppraisal(NamedTuple):
    """What she feels about a user's turn, and what her trust reads."""
    #: name -> intensity, 0..1, volatility applied.
    emotions: Dict[str, float]
    #: The strongest hostile emotion aimed at her, 0..1 (0: none).
    hostility: float
    #: The strongest warm emotion aimed at her, 0..1 (0: none).
    warmth: float


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def is_hostile(name: str) -> bool:
    """True when the emotion ``name`` (normalized) is hostility: one of
    :data:`HOSTILE_EMOTIONS`, or a word the text analyzer reads as one of
    them (``EMOTION_KEYWORDS``) -- a host's "angry", "irritated" or
    "enraged" (the vocabulary's names, or the user's own word) are the
    analyzer's "mad", "annoyed" and "furious". Every label the analyzer
    gives reads as itself, so its own readings are unchanged."""
    if name in HOSTILE_EMOTIONS:
        return True
    entry = EMOTION_KEYWORDS.get(name)
    return entry is not None and entry[0] in HOSTILE_EMOTIONS


def is_warm(name: str) -> bool:
    """True when the emotion ``name`` (normalized) is warmth toward her: one
    of :data:`WARM_EMOTIONS`, or a word the text analyzer reads as one of
    them (``EMOTION_KEYWORDS``) -- a host's "grateful", "affectionate",
    "warm" or "connected" are the analyzer's "thankful", "loving" and
    "intimate" (humanness Task 16b step 0.3, the reading :func:`is_hostile`
    gives anger). Every label the analyzer gives reads as itself, so its own
    readings are unchanged."""
    if name in WARM_EMOTIONS:
        return True
    entry = EMOTION_KEYWORDS.get(name)
    return entry is not None and entry[0] in WARM_EMOTIONS


def _felt_as(name: str) -> str:
    """The name whose vocabulary valence she feels ``name`` (normalized) by:
    a warm word the vocabulary has no entry for ("love", "adore", "caring")
    is felt as the analyzer's label for it ("loving"; Task 16b fix round 1:
    warmth for the appraisal as for her trust, :func:`is_warm`); any other
    name is itself."""
    if not is_known(name) and is_warm(name):
        return EMOTION_KEYWORDS[name][0]
    return name


def appraise_user_turn(user_emotions: Mapping[str, float], *, aimed_at_her: bool,
                       parameters: Optional[PersonaParameters] = None) -> UserTurnAppraisal:
    """Her appraisal of the user's ``user_emotions`` (name -> intensity) --
    the module docstring's table. ``aimed_at_her``: the turn speaks to her
    (``text_emotion_analyzer.addresses_listener``), so hostility in it is at
    her and warmth in it is for her."""
    params = parameters or PersonaParameters()
    reactivity = params.affect_reactivity
    felt: Dict[str, float] = {}
    hostility = warmth = 0.0

    def add(name: str, intensity: float) -> None:
        felt[name] = felt.get(name, 0.0) + intensity * reactivity

    for raw_name, raw_intensity in (user_emotions or {}).items():
        intensity = _clamp(raw_intensity)
        name = normalize(raw_name)
        if intensity <= 0.0 or not name:
            continue
        if aimed_at_her and is_hostile(name):
            hostility = max(hostility, intensity)
            add(IRRITATION_EMOTION, intensity * params.volatility)
            add(HURT_EMOTION, intensity * (1.0 - params.volatility))
            continue
        if aimed_at_her and is_warm(name):
            warmth = max(warmth, intensity)
        if name in PLAYFUL_EMOTIONS:
            add(AMUSEMENT_EMOTION, intensity)
            continue
        valence = valence_arousal(_felt_as(name))[0]
        if valence < 0.0:
            add(CONCERN_EMOTION, intensity * params.empathy)
        elif valence > 0.0:
            add(GLAD_EMOTION, intensity * params.empathy)

    emotions = {name: _clamp(value) for name, value in felt.items() if value > 0.0}
    return UserTurnAppraisal(emotions, hostility, warmth)


def appraisal_valence(emotions: Mapping[str, float]) -> Optional[float]:
    """The valence of what she feels: her emotions' vocabulary valences,
    weighted by intensity; ``None`` when she feels nothing."""
    total = sum(emotions.values())
    if total <= 0.0:
        return None
    return sum(valence_arousal(name)[0] * value for name, value in emotions.items()) / total
