"""Appraisal: what an event means to her, and so what she feels (humanness
program Task 14, spec section 4.7).

Measured before this task: every activity succeeded, and every activity was
felt as the same fixed emotions every time -- ``ActivityEngine`` copied its
setting's ``emotion_effects`` onto the log -- never judged against what she
wanted, needed or valued. An appraisal step (Chain-of-Emotion, PLOS ONE
2024) raised perceived naturalness (p = .008).

:func:`appraise` reads an :class:`AppraisalEvent` -- what happened, how it
turned out, what it feels like when it goes well -- against her: the goals it
serves, the needs it meets, the values it expresses, whose doing it was, how
expected the outcome was, and her volatility. It returns what she feels, as
:class:`~aura_life.emotion.text_emotion_analyzer.EmotionSpike` s, every name
one the vocabulary knows (:mod:`aura_life.emotion.vocabulary`). It draws no
randomness and reads no clock.

The checks
==========

=================  ============================================  ===================  ======================
Check              Reads                                         A success feels      A failure feels
=================  ============================================  ===================  ======================
the outcome        the event's own emotions (its setting's)      those emotions       "frustrated" (hers) or
and agency         and ``chosen`` (her own doing, or a                                "annoyed" (a
                   commitment she had to keep)                                        commitment)
expectedness       ``success_chance``: what she counted on       "relieved"           "resigned"
goal relevance     her active goals that list it                 "proud"              "disappointed"
need satisfaction  each need's shortfall x its trait weight x    NEED_FEELINGS[n][0]  NEED_FEELINGS[n][1]
                   how much the activity meets it
value congruence   her values aligned with it                    "fulfilled"          "discouraged"
volatility         ``PersonaParameters.affect_reactivity``       times every one      times every one
=================  ============================================  ===================  ======================

(The names are the constants below: FAILED_OWN_EMOTION, FAILED_IMPOSED_EMOTION,
RELIEF_EMOTION, RESIGNATION_EMOTION, GOAL_EMOTIONS, VALUE_EMOTIONS,
NEED_FEELINGS -- every one in the vocabulary.)

How strongly
============

The event's stake, ``S``, is the total of its own emotions' intensities
(clamped to 1): what it is worth to her when it goes well, as her setting
wrote it -- the only calibrated emotion magnitudes the library has
(``AffectSystem``'s EMOTION_MOOD_GAIN was measured on them). Every feeling is
a share of it, times her volatility's multiplier ``f`` (the one table of
:mod:`aura_life.personas.parameters`, row 1 -- 0.5 at volatility 0.1, 1 at
0.5, 1.5 at 0.9):

- **The outcome, and how expected it was.** ``p`` is the chance of success
  she had going in (``AppraisalEvent.success_chance``). A success is felt as
  its own emotions, each times ``p``, and as relief, ``S x (1 - p)``; a
  failure as frustration (annoyance, for a commitment), ``S x p``, and as
  resignation, ``S x (1 - p)``. The part she counted on is felt as the
  outcome itself, the part she doubted as relief or resignation -- the
  prospect-based emotions of the OCC model (Ortony, Clore & Collins 1988:
  disappointment grows with the hope that was dashed, relief with the fear
  that did not come true). Expectedness decides how the outcome is felt,
  never how strongly: the share is ``S`` either way, so a neutral persona's
  success she was sure of, serving nothing else, is felt exactly as her
  setting wrote it.
- **Relevance.** Goal ``g`` (the strongest motivation among her active goals
  that list it), need ``n`` (each need's shortfall times its trait weight
  times how much the activity meets it, their sum at most 1) and value ``v``
  (the strongest salience among her values aligned with its category or a
  tag) are each 0..1, and each adds its own feeling at ``S x x / 3``
  (``RELEVANCE_SHARE``): relevance is their mean, so an activity that serves
  everything she aims at, needs and values is felt twice as strongly as one
  that serves nothing else -- a goal alone, up to a third more.
- **Mixed** is half of each: half the success's feelings and half the
  failure's.

Every intensity is clamped to 0..1; a name several checks give is one spike,
their sum; a spike of no intensity is left out. An event whose setting gives
it no emotions at all has no stake and is not felt.

Volatility is applied here, once: ``AffectSystem.on_emotion_event`` is told
an appraised intensity already carries it (``reactivity_applied=True``) and
does not apply her reactivity a second time.

The LLM appraisal
=================

Optional, and off unless a host asks for it (``LifeService(appraisal_llm=True)``,
ruling R4): :func:`llm_appraisal_prompt` describes the event and asks for
what she feels as JSON, and :func:`parse_llm_appraisal` validates the reply
before anything uses it -- a name the vocabulary does not know is dropped, so
is one whose valence contradicts the outcome (a failure felt as joy; fix round
1, finding C1), each intensity is clamped to 0..1, and at most
LLM_APPRAISAL_MAX_EMOTIONS of the strongest are kept; nothing usable is
``None``, and the deterministic appraisal stands. The client is the host's
(``get_llm_service``), called synchronously on her tick: bounding how long it
takes is the host's (ruling T14-R2).
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

from ..personas.parameters import PersonaParameters
from .text_emotion_analyzer import EmotionSpike
from .vocabulary import EMOTION_VOCABULARY, normalize, valence_arousal

# ============= Outcomes =============

#: What can come of an activity: it went well, only half well, or wrong.
SUCCESS = "success"
MIXED = "mixed"
FAIL = "fail"
OUTCOMES: Tuple[str, ...] = (SUCCESS, MIXED, FAIL)

# ============= Every number, and where it comes from =============

#: Each of the three relevances -- goal, need, value, each 0..1 -- adds this
#: share of the stake: relevance is their mean, so all three at their fullest
#: double how strongly the event is felt. Chosen (the Task 14 report lists
#: it).
RELEVANCE_SHARE = 1.0 / 3.0

#: A mixed outcome is this much of a success and the rest of a failure:
#: half and half, the midpoint between the two (chosen).
MIXED_SUCCESS_SHARE = 0.5

#: At most this many feelings are taken from an LLM's appraisal: the most
#: emotions any contemporary activity is authored with
#: (``aura_life.settings.contemporary.ACTIVITIES``' ``emotion_effects``), so
#: a reply cannot give one event more feelings than the setting ever does.
LLM_APPRAISAL_MAX_EMOTIONS = 3

# ============= The names each check gives (all in the vocabulary) =============

#: A failed attempt of her own: the goal it was for, blocked.
FAILED_OWN_EMOTION = "frustrated"
#: A commitment she had to keep (a shift, a commute, a class, study) that
#: went wrong: circumstances, not her.
FAILED_IMPOSED_EMOTION = "annoyed"
#: A success she doubted: the fear that did not come true (OCC's relief).
RELIEF_EMOTION = "relieved"
#: A failure she half expected: the fear confirmed (OCC's fears-confirmed).
RESIGNATION_EMOTION = "resigned"
#: (success, failure) of something one of her goals is pursued through.
GOAL_EMOTIONS: Tuple[str, str] = ("proud", "disappointed")
#: (success, failure) of something that expresses a value she holds.
VALUE_EMOTIONS: Tuple[str, str] = ("fulfilled", "discouraged")
#: Need (``aura_life.settings.spec.NEED_KEYS``) -> (met, left unmet): how a
#: need she feels is felt when the activity meets it or fails to.
NEED_FEELINGS: Dict[str, Tuple[str, str]] = {
    "hunger": ("satisfied", "frustrated"),
    "rest": ("rested", "tired"),
    "social": ("connected", "lonely"),
    "solitude": ("peaceful", "drained"),
    "calm": ("calm", "stressed"),
    "stimulation": ("absorbed", "bored"),
    "reflection": ("clear", "unsettled"),
}


@dataclass(frozen=True)
class AppraisalEvent:
    """What happened, as her appraisal reads it.

    ``what``: the activity's name (what her goals list). ``outcome``: one of
    :data:`OUTCOMES`. ``emotions``: what it feels like when it goes well --
    an activity's ``emotion_effects``, its setting's. ``satisfies``: how
    much it meets each need, -1..1 (``aura_life.activities.choice
    .derived_satisfaction``; a cost -- a negative value -- is not a need it
    meets). ``aligned_tags``: what a value of hers can be aligned with -- its
    category's value and its tags. ``chosen``: whether it was her own doing
    (``False``: a commitment she had to keep). ``success_chance``: the
    chance of success she had going in, 0..1."""

    what: str
    outcome: str = SUCCESS
    emotions: Mapping[str, float] = field(default_factory=dict)
    satisfies: Mapping[str, float] = field(default_factory=dict)
    aligned_tags: FrozenSet[str] = frozenset()
    chosen: bool = True
    success_chance: float = 1.0

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError(f"an outcome is one of {OUTCOMES}, got {self.outcome!r}")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _field(item: Any, name: str, default: Any = None) -> Any:
    """``item[name]`` for a mapping, ``item.name`` for anything else."""
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def goal_relevance(what: str, goals: Iterable[Any]) -> float:
    """The strongest motivation among ``goals`` that list ``what`` among
    their related activities, 0..1; 0 when none does."""
    pulls = [float(_field(goal, "motivation_level", 0.0) or 0.0) for goal in goals or ()
             if what in (_field(goal, "related_activities", ()) or ())]
    return _clamp(max(pulls, default=0.0))


def need_relevance(satisfies: Mapping[str, float], needs: Mapping[str, float],
                   weights: Mapping[str, float]) -> Dict[str, float]:
    """Need -> how much of it the activity answers now: its shortfall
    (``needs``, 0..1) times its weight (her traits', 1 when none weighs it)
    times how much the activity meets it (a cost counts as none). Their sum
    is at most 1 -- scaled down together past it: all she needs, fully met,
    is one fully met need's worth."""
    parts = {}
    for need, amount in (satisfies or {}).items():
        shortfall = _clamp(float((needs or {}).get(need, 0.0) or 0.0))
        part = shortfall * float(weights.get(need, 1.0)) * max(0.0, float(amount))
        if part > 0.0:
            parts[need] = part
    total = sum(parts.values())
    if total > 1.0:
        parts = {need: part / total for need, part in parts.items()}
    return parts


def value_relevance(aligned_tags: Iterable[str], values: Iterable[Any]) -> float:
    """The strongest salience among ``values`` (``ValueBelief`` s, or
    IdentitySystem's ``{"name", "salience", "aligned_tags"}`` dicts) aligned
    with one of ``aligned_tags``, 0..1; 0 when none is."""
    tags = {str(tag).lower() for tag in aligned_tags or ()}
    saliences = [float(_field(value, "salience", 0.0) or 0.0) for value in values or ()
                 if tags & {str(tag).lower() for tag in (_field(value, "aligned_tags", ()) or ())}]
    return _clamp(max(saliences, default=0.0))


def _add(felt: Dict[str, Tuple[float, str]], name: str, intensity: float, source: str) -> None:
    """Add ``intensity`` of ``name`` to ``felt`` (name -> (intensity, the
    check that first gave it))."""
    if intensity <= 0.0:
        return
    held = felt.get(name)
    felt[name] = (intensity, source) if held is None else (held[0] + intensity, held[1])


def _appraise_outcome(outcome: str, event: AppraisalEvent, stake: float, relevance: Dict[str, Any],
                      scale: float, felt: Dict[str, Tuple[float, str]]) -> None:
    """Add what one pure outcome (success or fail) feels like, times
    ``scale``, to ``felt``."""
    p = _clamp(float(event.success_chance))
    success = outcome == SUCCESS
    if success:
        for name, intensity in (event.emotions or {}).items():
            _add(felt, normalize(name), max(0.0, float(intensity)) * p * scale, "outcome")
        _add(felt, RELIEF_EMOTION, stake * (1.0 - p) * scale, "expectedness")
    else:
        _add(felt, FAILED_OWN_EMOTION if event.chosen else FAILED_IMPOSED_EMOTION, stake * p * scale, "outcome")
        _add(felt, RESIGNATION_EMOTION, stake * (1.0 - p) * scale, "expectedness")
    side = 0 if success else 1
    _add(felt, GOAL_EMOTIONS[side], stake * RELEVANCE_SHARE * relevance["goal"] * scale, "goal")
    for need, part in relevance["needs"].items():
        names = NEED_FEELINGS.get(need)
        if names is not None:
            _add(felt, names[side], stake * RELEVANCE_SHARE * part * scale, f"need:{need}")
    _add(felt, VALUE_EMOTIONS[side], stake * RELEVANCE_SHARE * relevance["value"] * scale, "value")


def appraise(event: AppraisalEvent, parameters: Optional[PersonaParameters], goals: Iterable[Any],
             needs: Mapping[str, float], values: Iterable[Any]) -> List[EmotionSpike]:
    """What she feels about ``event`` (the module docstring's checks):
    ``parameters`` her traits (``None``: the neutral persona), ``goals`` her
    active goals (``Goal`` s), ``needs`` each need's shortfall now (need ->
    0..1, ``aura_life.settings.spec.NEED_KEYS``), ``values`` her salient
    values. One spike per name, in the order the checks give them; each
    spike's ``word`` names the check that first gave it ("outcome",
    "expectedness", "goal", "need:<need>", "value") and its ``position`` is
    0 (an appraisal has no text to be placed in)."""
    params = parameters if parameters is not None else PersonaParameters()
    stake = _clamp(sum(max(0.0, float(x)) for x in (event.emotions or {}).values()))
    if stake <= 0.0:
        return []
    relevance = {
        "goal": goal_relevance(event.what, goals),
        "needs": need_relevance(event.satisfies, needs, params.need_weights),
        "value": value_relevance(event.aligned_tags, values),
    }
    reactivity = params.affect_reactivity
    felt: Dict[str, Tuple[float, str]] = {}
    if event.outcome == MIXED:
        _appraise_outcome(SUCCESS, event, stake, relevance, MIXED_SUCCESS_SHARE * reactivity, felt)
        _appraise_outcome(FAIL, event, stake, relevance, (1.0 - MIXED_SUCCESS_SHARE) * reactivity, felt)
    else:
        _appraise_outcome(event.outcome, event, stake, relevance, reactivity, felt)
    return [EmotionSpike(position=0.0, emotion=name, intensity=_clamp(intensity), word=source)
            for name, (intensity, source) in felt.items() if intensity > 0.0]


def emotions_of(spikes: Iterable[EmotionSpike]) -> Dict[str, float]:
    """Spikes as the name -> intensity mapping the rest of the library reads
    (``ActivityLog.emotions_triggered``, ``LifeService._feel``); a name twice
    is summed, clamped to 1."""
    emotions: Dict[str, float] = {}
    for spike in spikes:
        emotions[spike.emotion] = _clamp(emotions.get(spike.emotion, 0.0) + spike.intensity)
    return emotions


def appraised_valence(spikes: Iterable[EmotionSpike]) -> Optional[float]:
    """How the event felt, -1..1: the intensity-weighted mean valence of what
    she felt (the vocabulary's) -- what her memory keeps of it (Task 12's
    episode valence). ``None`` when she felt nothing."""
    total = weighted = 0.0
    for spike in spikes:
        total += spike.intensity
        weighted += spike.intensity * valence_arousal(spike.emotion)[0]
    return weighted / total if total > 0.0 else None


# ============= The optional LLM appraisal =============

_OBJECT_RE = re.compile(r"\{[^{}]*\}")


def llm_appraisal_prompt(event: AppraisalEvent, *, goal_titles: Iterable[str] = (),
                         needs: Mapping[str, float] = (), values: Iterable[Any] = ()) -> str:
    """The prompt the optional LLM appraisal asks: the event, what it was
    for, and a JSON reply of what she feels."""
    goals = [str(title) for title in goal_titles or () if str(title).strip()]
    felt_needs = [need for need, level in dict(needs or {}).items() if float(level or 0.0) >= 0.3]
    held = [str(_field(value, "name", "")) for value in values or () if str(_field(value, "name", "")).strip()]
    how = {SUCCESS: "went well", MIXED: "only half went well", FAIL: "went wrong"}[event.outcome]
    lines = [
        f"A person just spent some time {event.what}, and it {how}.",
        f"It was {'their own choice' if event.chosen else 'something they had to do'}; "
        f"going in, they thought it had a {round(_clamp(event.success_chance) * 100)} in 100 chance of going well.",
    ]
    if goals:
        lines.append("It was for goals of theirs: " + "; ".join(goals) + ".")
    if felt_needs:
        lines.append("They needed: " + ", ".join(felt_needs) + ".")
    if held:
        lines.append("They value: " + ", ".join(held) + ".")
    lines.append(
        "How do they feel about it? Reply with ONLY a JSON object mapping up to "
        f"{LLM_APPRAISAL_MAX_EMOTIONS} plain one-word emotions to an intensity from 0 to 1, "
        'for example {"frustrated": 0.4, "tired": 0.2}.'
    )
    return "\n".join(lines)


def _fits(name: str, outcome: Optional[str]) -> bool:
    """Whether a feeling can be how ``outcome`` felt, by the sign of its
    valence in the vocabulary: a failure is never felt as something
    pleasant, a success never as something unpleasant; a mixed outcome can
    be either, a name of no valence always fits, and so does any name when
    the outcome is not known (Task 14 fix round, finding C1)."""
    valence = valence_arousal(name)[0]
    if outcome == FAIL:
        return valence <= 0.0
    if outcome == SUCCESS:
        return valence >= 0.0
    return True


def parse_llm_appraisal(raw: Any, *, outcome: Optional[str] = None) -> Optional[Dict[str, float]]:
    """The LLM's reply, validated -- or ``None`` when nothing in it is
    usable: the first flat JSON object in it that parses, each key
    normalised (``vocabulary.normalize``) and kept only when the vocabulary
    knows it and it fits ``outcome`` (when given: a FAIL keeps no pleasant
    feeling, a SUCCESS no unpleasant one, MIXED both; a name of no valence
    always), each value a number (never a bool) clamped to 0..1, a value of 0
    or less dropped, and at most LLM_APPRAISAL_MAX_EMOTIONS of the strongest
    kept (the first of equals) -- chosen among those that fit."""
    text = str(raw or "")
    for match in _OBJECT_RE.finditer(text):
        try:
            data = json.loads(match.group(0))
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        kept: Dict[str, float] = {}
        for key, value in data.items():
            name = normalize(str(key))
            if name not in EMOTION_VOCABULARY or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if not _fits(name, outcome):
                continue
            intensity = _clamp(float(value))
            if intensity > 0.0:
                kept[name] = max(intensity, kept.get(name, 0.0))
        if not kept:
            return None
        strongest = sorted(kept.items(), key=lambda item: -item[1])[:LLM_APPRAISAL_MAX_EMOTIONS]
        return dict(strongest)
    return None


def spikes_from_llm(emotions: Mapping[str, float], parameters: Optional[PersonaParameters]) -> List[EmotionSpike]:
    """A validated LLM appraisal (:func:`parse_llm_appraisal`) as spikes,
    scaled by her volatility like the deterministic appraisal, clamped to
    0..1; ``word`` is "llm"."""
    reactivity = (parameters if parameters is not None else PersonaParameters()).affect_reactivity
    return [EmotionSpike(position=0.0, emotion=name, intensity=_clamp(intensity * reactivity), word="llm")
            for name, intensity in emotions.items() if intensity * reactivity > 0.0]


__all__ = [
    "SUCCESS",
    "MIXED",
    "FAIL",
    "OUTCOMES",
    "RELEVANCE_SHARE",
    "MIXED_SUCCESS_SHARE",
    "LLM_APPRAISAL_MAX_EMOTIONS",
    "FAILED_OWN_EMOTION",
    "FAILED_IMPOSED_EMOTION",
    "RELIEF_EMOTION",
    "RESIGNATION_EMOTION",
    "GOAL_EMOTIONS",
    "VALUE_EMOTIONS",
    "NEED_FEELINGS",
    "AppraisalEvent",
    "appraise",
    "appraised_valence",
    "emotions_of",
    "goal_relevance",
    "need_relevance",
    "value_relevance",
    "llm_appraisal_prompt",
    "parse_llm_appraisal",
    "spikes_from_llm",
]
