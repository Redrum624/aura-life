"""Activity choice from the persona: what serves her best, now (humanness
program Task 10, spec sections 4.3 and 4.4).

Before this module, what she did next read no trait and no taste -- a fixed
score of time of day, place, weather and variety -- so an introvert and an
extrovert did the same things, her interests were stored and never read, and
no need ever moved her: hunger stood at or above 0.7 on 65-80% of ticks.

The utility
===========

::

    utility(a) = NEED_WEIGHT     * sum over needs n of shortfall(n) * weight(n) * satisfies(a, n)
               + AFFINITY_WEIGHT * affinity(a)
               + GOAL_FIT_WEIGHT * goal_fit(a)
               + MOOD_FIT_WEIGHT * mood_fit(a)
               - EFFORT_WEIGHT   * effort(a)
               + COPING_WEIGHT   * coping(a)

- ``shortfall(n)``: how unmet need ``n`` is now, 0..1 --
  :data:`~aura_life.settings.spec.NEED_KEYS` names the state each is read
  from; ``LifeService`` reads them every activity tick (:class:`ChoiceState`).
- ``weight(n)``: what her traits make of it,
  :attr:`PersonaParameters.need_weights <aura_life.personas.parameters.PersonaParameters.need_weights>`
  (an extrovert's loneliness weighs 1.5, an introvert's 0.5 ...); 1 for a
  need no trait weighs.
- ``satisfies(a, n)``, -1..1: :data:`DERIVED_SATISFACTION` from its
  category and tags, and ``Activity.needs`` for each need it states.
- ``affinity(a)``, -1..1: how well it matches what she is into -- her
  interests, comfort-zone seeds, tastes, media and substance tendencies
  (:class:`ActivityPreferences`); negative only for a substance she avoids.
- ``goal_fit(a)``, 0..1: the strongest pull on it of an active goal
  (its motivation) or want (its urgency) that lists it.
- ``mood_fit(a)``, -1..1: a soothing or gentle activity fits a low mood, a
  demanding one high arousal and a restorative one low arousal.
- ``effort(a)``, 0..: its energy cost against the energy she has.
- ``coping(a)``: how she copes with what weighs on her (Task 15;
  :attr:`PersonaParameters.problem_focus` and ``contact_seeking``, rows 20
  and 22 of its table) -- ``max(0, problem_focus) * resolving(a)`` +
  ``max(0, contact_seeking) * shortfall(calm) * satisfies(a, social)``:
  a problem-focused persona is drawn to what ends a stressor she can end
  herself (``resolving(a)``: that stressor's controllability,
  :attr:`ChoiceState.resolving`), a social one, under stress (her "calm"
  need's shortfall is her stress level), to company. 0 for a persona whose
  coping leans neither way.

She chooses as ``ActivityEngine`` always has -- among the TOP_CANDIDATES
best, drawn in proportion to their weight -- each weight now being
``context(a) * exp(utility(a) / TEMPERATURE)``, where ``context`` is the old
fit of time of day, weather, place, variety and her values
(``ActivityEngine._score_activity``).

Her habits are not in the utility: they count once, as aura-life 0.5.0's
dated habits (``BehaviorSystem.habit_factors``, a ``(raise, damp)`` pair per
activity and part of her day) around the cut -- the raise multiplies a weight
before it, the damp a weight after it (``ActivityEngine.select_activity``'s
``habit``; for her plan, ``DailyPlanner._slot_draw``). The undated habit term
this utility had (Task 10's ``HABIT_WEIGHT`` times an activity's share of her
recent activities) is gone with the merge of 0.5.0 (Task 31).

Her plan
========

``DailyPlanner`` fills a free hour before any of that hour's needs is known,
so it weighs what she likes and what her traits lean her to::

    plan_preference(a) = AFFINITY_WEIGHT * affinity(a) + lean(a)
    lean(a) = NEED_WEIGHT * PLAN_NEED_LEVEL * sum over n of (weight(n) - 1) * satisfies(a, n)

``lean`` is 0 for a persona whose traits are all neutral: her plan leans
exactly as far as her traits do.

Matching her words to activities
================================

Her interests, comfort zones, tastes and media are free text; an activity is
its name, narratives and thoughts. Both are cut into words by :func:`terms`
-- lowercase, no :data:`STOPWORDS`, each word crudely stemmed the same way
(:func:`stem`: "running" and "run", "books" and "book", "baking" and "bake"
meet) -- and a seed matches an activity by the share of the seed's words
found in the activity's name (full strength) or only in its narratives and
thoughts (TEXT_MATCH_WEIGHT of it). Her affinity for an activity is the best
match of any seed, times that seed's weight (SEED_WEIGHTS), plus
SUBSTANCE_FREQUENCY for a substance she takes that the activity carries the
tag of (SUBSTANCE_TAGS).
"""

import math
import re
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..models import Activity, ActivityCategory
from ..personas.genre_randomizer import PRONOUNS
from ..personas.parameters import PersonaParameters
from ..settings.spec import NEED_KEYS
from ..sustenance.sustenance_system import HUNGRY_THRESHOLD

# ============= Every number of the choice, and where it comes from =============
# Chosen for Task 10 and measured in its three-day, production-cadence runs
# (the values and the measurements are listed in the Task 10 report).

#: The needs term's weight: a need she feels at its fullest (shortfall 1,
#: weight 1) for an activity that fully meets it adds 1 to its utility.
NEED_WEIGHT = 1.0
#: What she is into: an activity whose name is one of her interests adds this.
AFFINITY_WEIGHT = 1.5
#: An activity a goal or want of hers lists adds this times the strongest
#: such pull (a goal's motivation, a want's urgency).
GOAL_FIT_WEIGHT = 0.5
#: How much her mood's fit with an activity counts.
MOOD_FIT_WEIGHT = 0.5
#: How much an activity's cost against her energy counts against it.
EFFORT_WEIGHT = 1.0
#: How much her coping counts (Task 15): a pull at its fullest -- a stressor
#: fully in her hands that this activity ends, at problem focus 1; company
#: at full stress, at contact seeking 1 -- adds as much as a need fully felt
#: and fully met (derived: NEED_WEIGHT).
COPING_WEIGHT = NEED_WEIGHT
#: How sharply utility decides: each TEMPERATURE of utility multiplies an
#: activity's weight by e.
TEMPERATURE = 0.5
#: How many of the best she chooses among (ActivityEngine.select_activity's
#: top five, as before).
TOP_CANDIDATES = 5
#: The shortfall a plan assumes for every need when it leans her free hours
#: by her traits (``lean``): as if each were fully felt.
PLAN_NEED_LEVEL = 1.0
#: A seed found only in an activity's narratives or thoughts, not its name,
#: matches at this share of the strength.
TEXT_MATCH_WEIGHT = 0.5
#: How much each kind of seed counts toward her affinity for an activity:
#: what she says she is into, or is at home doing, fully; what she likes the
#: taste of, or reads, watches and listens to, half.
SEED_WEIGHTS: Dict[str, float] = {
    "interests": 1.0,
    "comfort_zone_seeds": 1.0,
    "taste_seeds": 0.5,
    "media_preferences": 0.5,
}
#: How a substance tendency's word (``PersonalityDefinition.substance_tendencies``
#: values; the ones profiles and the persona generator write) moves her
#: affinity for an activity that carries its tag: "avoidant" keeps her from
#: it, the rest draw her in by how often she takes it.
SUBSTANCE_FREQUENCY: Dict[str, float] = {
    "avoidant": -1.0,
    "occasional": 0.25,
    "social": 0.5,
    "regular": 0.5,
    "frequent": 0.75,
    "heavy": 1.0,
    "daily": 1.0,
}
#: A tendency whose word is not in SUBSTANCE_FREQUENCY counts as this.
SUBSTANCE_UNKNOWN_FREQUENCY = 0.5
#: Which activity tag a substance is (the substances profiles and the persona
#: generator name). A substance not listed has no activity to draw her to.
SUBSTANCE_TAGS: Dict[str, str] = {
    "alcohol": "alcohol", "wine": "alcohol", "beer": "alcohol", "whiskey": "alcohol",
    "whisky": "alcohol", "tequila": "alcohol", "champagne": "alcohol", "absinthe": "alcohol",
    "vodka": "alcohol", "rum": "alcohol", "gin": "alcohol", "cocktails": "alcohol",
    "cigarettes": "smoking", "cigarette": "smoking", "tobacco": "smoking", "cigars": "smoking",
}
#: A seed of hers counts an activity as hers (a goal's or want's activities,
#: ``matching_activities``) from this match strength up: half of its words in
#: the activity's name, or all of them in its narratives.
MATCH_MINIMUM = 0.5
#: A need this unmet takes a free-time slot of her plan (``LifeService``):
#: she eats when she is hungry, whatever the hour was planned for -- at
#: SustenanceSystem's own HUNGRY_THRESHOLD. Her plan's anchors and her
#: commitments are kept.
PRESSING_NEEDS: Dict[str, float] = {"hunger": HUNGRY_THRESHOLD}

#: Where an activity's ``needs`` come from when it states none: (what it is --
#: ``("tag", name)`` or ``("category", ActivityCategory value)`` -- the need,
#: how much). The strongest row that applies sets each need; a negative value
#: is a cost (company, to a drained introvert). Chosen from what the tags and
#: categories already say (aura_life.settings.spec.ACTIVITY_TAGS).
DERIVED_SATISFACTION: Tuple[Tuple[Tuple[str, str], str, float], ...] = (
    (("tag", "meal"), "hunger", 1.0),
    (("tag", "restful"), "rest", 1.0),
    (("category", "social"), "social", 1.0),
    (("category", "social"), "solitude", -1.0),
    (("tag", "quiet"), "solitude", 1.0),
    (("category", "reflective"), "solitude", 0.5),
    (("tag", "soothing"), "calm", 1.0),
    (("tag", "gentle"), "calm", 0.5),
    (("tag", "focus"), "stimulation", 1.0),
    (("tag", "flow"), "stimulation", 1.0),
    (("category", "mental"), "stimulation", 0.5),
    (("category", "creative"), "stimulation", 0.5),
    (("category", "exploration"), "stimulation", 0.5),
    (("category", "reflective"), "reflection", 1.0),
)
#: A restorative activity (negative energy cost) with no "restful" tag meets
#: her need for rest this much.
RESTORATIVE_REST = 0.5
#: An activity costing at least this much energy is demanding (it fits high
#: arousal); one with a negative cost is restorative (it fits low arousal).
#: The midpoint of the contemporary costs of the steady ones ("reading" 0.1)
#: and the strenuous ones ("going for a run" 0.25, "gym workout" 0.3).
DEMANDING_ENERGY_COST = 0.2
#: effort's floor on her energy (so an activity's cost is never divided by 0).
EFFORT_ENERGY_FLOOR = 0.1

# ============= Words =============

#: Words that say nothing about what an activity is: function words, the
#: pronoun and user tokens of the narratives, the persona pronouns themselves
#: (every form in ``genre_randomizer.PRONOUNS``), and the narratives' own
#: filler verbs and adverbs ("spent some time ... for a while").
STOPWORDS: FrozenSet[str] = frozenset("""
a about above after again against all almost also am an and another any anyone anything are around as at
away back be because been before being between both but by can could did do does doing done down during
each even ever every everything few for from further get gets getting got had has have having here how i
if in into is it its itself just less like lot lots made make makes making many me might more most much my
myself never no nor not nothing now of off often on once one only or other our ours out over own poss pron
really refl same should so some something somehow spend spending spent still subj such than that the then
there these thing things this those though through to too took under until up upon user very was way we
went were what when where which while who why will with would yet you your yours obj stuff bit little time
times day days going gonna wanna kinda maybe okay yeah actually pretty sure
""".split()) | frozenset(
    form.lower() for forms in PRONOUNS.values()
    for key, form in forms.items() if key in ("subj", "obj", "poss", "poss_pron", "refl")
)

_WORD_RE = re.compile(r"[a-z]+")


def stem(word: str) -> str:
    """A crude stem, the same for her words and an activity's, so "running"
    meets "run", "books" "book" and "baking" "bake" (the matcher needs them to
    meet, not to be English)."""
    if len(word) > 4 and word.endswith("ies"):
        word = word[:-3] + "y"
    elif len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]
    elif len(word) > 4 and word.endswith("es") and (word[-3] in "sxz" or word[-4:-2] in ("ch", "sh")):
        word = word[:-2]
    elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if len(word) > 2 and word[-1] == word[-2] and word[-1] not in "lsz":
        word = word[:-1]  # "runn" -> "run", "stopp" -> "stop"
    if len(word) > 3 and word.endswith("e"):
        word = word[:-1]  # "bake" and "bak(ing)" meet
    return word


def terms(text) -> FrozenSet[str]:
    """The stemmed words of ``text`` that say something (see STOPWORDS)."""
    words = _WORD_RE.findall(str(text or "").lower().replace("’", "'"))
    return frozenset(stem(w) for w in words if len(w) > 2 and w not in STOPWORDS)


# ============= The live state she chooses in =============

@dataclass(frozen=True)
class ChoiceState:
    """What ``LifeService`` knows of her now, each activity tick: her needs'
    shortfalls (need -> 0..1, NEED_KEYS), her mood (valence -1..1, arousal
    0..1), her effective energy, her recent activities (oldest first), the
    pull of her goals and wants (activity name -> 0..1), and what would end a
    stressor she can end herself (activity name -> that stressor's
    controllability, the largest when it ends several; Task 15).

    ``history`` (her recent activities) is still accepted and ``LifeService``
    still fills it, but nothing reads it since Task 31: her habits act as
    ``BehaviorSystem.habit_factors`` around the cut, not in the utility."""

    needs: Mapping[str, float] = field(default_factory=dict)
    valence: float = 0.0
    arousal: float = 0.5
    energy: float = 0.7
    history: Sequence[str] = ()
    pulls: Mapping[str, float] = field(default_factory=dict)
    resolving: Mapping[str, float] = field(default_factory=dict)


# ============= Her preferences =============

def derived_satisfaction(activity: Activity) -> Dict[str, float]:
    """How much ``activity`` meets each need: DERIVED_SATISFACTION's rows
    for its category and tags (the largest of each need's rows, or the most
    negative when every row that applies is a cost), with its own ``needs``
    winning for each need they state. (Stated needs replaced the derived
    ones wholesale, so a meal that stated any lost its pull on her hunger
    while its tag still fed her: fix round 1, finding 10.)"""
    found: Dict[str, List[float]] = {}
    category = activity.category.value if isinstance(activity.category, ActivityCategory) else str(activity.category)
    for (kind, value), need, amount in DERIVED_SATISFACTION:
        if (kind == "tag" and value in activity.tags) or (kind == "category" and value == category):
            found.setdefault(need, []).append(amount)
    if "rest" not in found and activity.energy_cost < 0:
        found["rest"] = [RESTORATIVE_REST]
    meets = {need: (max(amounts) if max(amounts) > 0 else min(amounts)) for need, amounts in found.items()}
    meets.update({need: float(amount) for need, amount in (activity.needs or {}).items() if need in NEED_KEYS})
    return meets


def _activity_words(activity: Activity) -> Tuple[FrozenSet[str], FrozenSet[str]]:
    """(its name's words, its narratives' and thoughts' words)."""
    text = " ".join(list(activity.narrative_templates) + list(activity.thought_possibilities))
    return terms(activity.name), terms(text)


def match_strength(seed_words: FrozenSet[str], name_words: FrozenSet[str], text_words: FrozenSet[str]) -> float:
    """How well a seed's words meet an activity's: the share found in its
    name, or TEXT_MATCH_WEIGHT of the share found in its narratives and
    thoughts, whichever is more."""
    if not seed_words:
        return 0.0
    in_name = len(seed_words & name_words) / len(seed_words)
    in_text = len(seed_words & (name_words | text_words)) / len(seed_words)
    return max(in_name, TEXT_MATCH_WEIGHT * in_text)


def matching_activities(text: str, activities: Iterable[Activity], minimum: float = MATCH_MINIMUM) -> List[str]:
    """The names of ``activities`` that ``text`` matches at least ``minimum``
    (see :func:`match_strength`), best first, catalogue order among equals."""
    seed = terms(text)
    scored = []
    for index, activity in enumerate(activities):
        strength = match_strength(seed, *_activity_words(activity))
        if strength >= minimum:
            scored.append((-strength, index, activity.name))
    return [name for _, _, name in sorted(scored)]


def _seed_texts(values) -> List[str]:
    """A seed field as a list of texts: a str is one text, a list its items,
    a mapping its keys and every item of its values."""
    if not values:
        return []
    if isinstance(values, str):
        return [values]
    if isinstance(values, Mapping):
        texts: List[str] = []
        for key, items in values.items():
            texts.append(str(key))
            texts.extend(_seed_texts(items))
        return texts
    try:
        return [str(v) for v in values if v]
    except TypeError:
        return [str(values)]


class ActivityPreferences:
    """One persona's standing preferences over her setting's activities: how
    much each meets each need, what her traits make of each need, and how
    well each matches what she is into. Built once, with her engines;
    :meth:`utility` adds what the moment brings (:class:`ChoiceState`).

    ``ActivityPreferences()`` -- no traits, no seeds -- is the neutral
    persona: every need weighs 1, nothing draws her by affinity, and her plan
    does not lean."""

    def __init__(self, params: Optional[PersonaParameters] = None, *,
                 interests=None, comfort_zone_seeds=None, taste_seeds=None,
                 media_preferences=None, substance_tendencies=None):
        params = params or PersonaParameters()
        self._weights: Dict[str, float] = dict(params.need_weights)
        # How she copes (Task 15): only the side that pulls counts here.
        self._problem_focus = max(0.0, params.problem_focus)
        self._contact_seeking = max(0.0, params.contact_seeking)
        self._seeds: List[Tuple[float, FrozenSet[str]]] = []
        for field_name, values in (("interests", interests), ("comfort_zone_seeds", comfort_zone_seeds),
                                   ("taste_seeds", taste_seeds), ("media_preferences", media_preferences)):
            for text in _seed_texts(values):
                words = terms(text)
                if words:
                    self._seeds.append((SEED_WEIGHTS[field_name], words))
        self._substances: Dict[str, float] = {}
        for substance, tendency in (substance_tendencies or {}).items():
            tag = SUBSTANCE_TAGS.get(str(substance).strip().lower())
            if tag:
                word = str(tendency or "").strip().lower()
                pull = SUBSTANCE_FREQUENCY.get(word, SUBSTANCE_UNKNOWN_FREQUENCY)
                # Two substances of one kind: the stronger pull, but any
                # avoidance wins (she keeps from what she avoids).
                held = self._substances.get(tag)
                self._substances[tag] = pull if held is None else min(held, pull) if pull < 0 or held < 0 else max(held, pull)
        self._cache: Dict[str, Tuple[Dict[str, float], float, float]] = {}

    @classmethod
    def from_definition(cls, definition, params: Optional[PersonaParameters] = None, *,
                        interests=None, media_preferences=None) -> "ActivityPreferences":
        """Her preferences from a ``PersonalityDefinition`` (anything with its
        attributes; ``None`` is the neutral persona). ``interests`` and
        ``media_preferences``, when given, replace the definition's (a host
        may pass its own, as ``LifeService`` takes them)."""
        def _field(name, default):
            return (getattr(definition, name, default) if definition is not None else default) or default

        return cls(
            params if params is not None else PersonaParameters.from_definition(definition),
            interests=interests if interests else _field("interests", []),
            comfort_zone_seeds=_field("comfort_zone_seeds", []),
            taste_seeds=_field("taste_seeds", {}),
            media_preferences=media_preferences if media_preferences else _field("media_preferences", {}),
            substance_tendencies=_field("substance_tendencies", {}),
        )

    # ---- What stays the same for her ----

    def need_weight(self, need: str) -> float:
        """What her traits make of ``need`` (1 when none weighs it)."""
        return self._weights.get(need, 1.0)

    def _profile(self, activity: Activity) -> Tuple[Dict[str, float], float, float]:
        cached = self._cache.get(activity.name)
        if cached is None:
            satisfaction = derived_satisfaction(activity)
            name_words, text_words = _activity_words(activity)
            affinity = max((weight * match_strength(words, name_words, text_words)
                            for weight, words in self._seeds), default=0.0)
            affinity += sum(pull for tag, pull in self._substances.items() if tag in activity.tags)
            affinity = max(-1.0, min(1.0, affinity))
            lean = NEED_WEIGHT * PLAN_NEED_LEVEL * sum(
                (self.need_weight(need) - 1.0) * amount for need, amount in satisfaction.items())
            cached = (satisfaction, affinity, lean)
            self._cache[activity.name] = cached
        return cached

    def satisfaction(self, activity: Activity) -> Dict[str, float]:
        """How much ``activity`` meets each need (:func:`derived_satisfaction`)."""
        return dict(self._profile(activity)[0])

    def affinity(self, activity: Activity) -> float:
        """How well ``activity`` matches what she is into, -1..1."""
        return self._profile(activity)[1]

    def lean(self, activity: Activity) -> float:
        """How far her traits lean her toward ``activity`` (0 when neutral)."""
        return self._profile(activity)[2]

    def plan_preference(self, activity: Activity) -> float:
        """What a free hour of her plan weighs ``activity`` by: affinity and
        lean (see the module docstring)."""
        _, affinity, lean = self._profile(activity)
        return AFFINITY_WEIGHT * affinity + lean

    # ---- What the moment brings ----

    def utility(self, activity: Activity, state: ChoiceState) -> float:
        """The module docstring's utility of ``activity`` for her in ``state``."""
        satisfaction, affinity, _ = self._profile(activity)
        needs = sum(max(0.0, min(1.0, state.needs.get(need, 0.0))) * self.need_weight(need) * amount
                    for need, amount in satisfaction.items())
        goal_fit = max(0.0, min(1.0, state.pulls.get(activity.name, 0.0)))
        return (NEED_WEIGHT * needs
                + AFFINITY_WEIGHT * affinity
                + GOAL_FIT_WEIGHT * goal_fit
                + MOOD_FIT_WEIGHT * mood_fit(activity, state.valence, state.arousal)
                - EFFORT_WEIGHT * effort(activity, state.energy)
                + COPING_WEIGHT * self.coping(activity, state))

    def coping(self, activity: Activity, state: ChoiceState) -> float:
        """How her coping draws her to ``activity`` in ``state`` (the module
        docstring's ``coping``): toward what ends a stressor she can end
        herself, if she is problem-focused; toward company under stress, if
        she seeks it. 0 when she leans neither way."""
        pull = 0.0
        if self._problem_focus:
            pull += self._problem_focus * max(0.0, min(1.0, state.resolving.get(activity.name, 0.0)))
        if self._contact_seeking:
            stress = max(0.0, min(1.0, state.needs.get("calm", 0.0)))
            pull += self._contact_seeking * stress * self._profile(activity)[0].get("social", 0.0)
        return pull


def mood_fit(activity: Activity, valence: float, arousal: float) -> float:
    """-1..1: a soothing or gentle activity fits a low mood (by how low); a
    demanding one fits high arousal and a restorative one low arousal (by how
    far arousal is from its middle)."""
    fit = 0.0
    if valence < 0 and activity.tags & {"soothing", "gentle"}:
        fit += min(1.0, -valence)
    intensity = 1.0 if activity.energy_cost >= DEMANDING_ENERGY_COST else -1.0 if activity.energy_cost < 0 else 0.0
    fit += (max(0.0, min(1.0, arousal)) - 0.5) * 2.0 * intensity
    return max(-1.0, min(1.0, fit))


def effort(activity: Activity, energy: float) -> float:
    """Its energy cost against the energy she has (0 for a restorative one)."""
    return max(0.0, activity.energy_cost) / max(EFFORT_ENERGY_FLOOR, energy)


def choice_weight(context: float, utility: float) -> float:
    """An activity's weight in her draw: its context fit times
    exp(utility / TEMPERATURE)."""
    return context * math.exp(utility / TEMPERATURE)


def pressing_needs(state: ChoiceState) -> List[str]:
    """Her needs unmet enough to take a free-time slot (PRESSING_NEEDS)."""
    return [need for need, level in PRESSING_NEEDS.items() if state.needs.get(need, 0.0) >= level]


__all__ = [
    "ActivityPreferences",
    "ChoiceState",
    "DERIVED_SATISFACTION",
    "derived_satisfaction",
    "match_strength",
    "matching_activities",
    "mood_fit",
    "effort",
    "choice_weight",
    "pressing_needs",
    "stem",
    "terms",
]
