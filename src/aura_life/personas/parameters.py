"""
Persona parameters: the eight traits, and the engine numbers they set.

``PersonaParameters.from_definition(defn)`` compiles a persona once, when her
engines are built (humanness program spec section 4.3). The object holds the
eight traits of :data:`aura_life.personas.keys.TRAIT_KEYS`, each 0..1, and the
engine parameters derived from them through the one table below. Engines
receive the object; none of them reads trait text itself. An engine built the
old way, from ``core_traits=``, has this module read the text for it
(:meth:`PersonaParameters.from_core_traits`).

Where each trait comes from
===========================

1. The definition's explicit ``traits`` -- ``Traits:`` in a profile's
   ``== ENGINE SEEDS ==``. A value that is not a number in 0..1 is ignored and
   the trait inferred instead (``ProfileParser`` drops such a value too).
2. Otherwise inferred from the definition's ``core_traits``, the free text the
   nine retired keyword tables read. Each word of the trait's vocabulary
   (:data:`TRAIT_VOCABULARY`) the matcher finds is one piece of evidence that
   the trait is high or low, and the trait is
   ``0.5 + INFERENCE_SPAN * (high - low) / (high + low + 1)``.
   One word moves it 0.2 -- the step of the retired
   ``AffectSystem._calc_social_need`` and ``_calc_empathy`` -- and more words
   approach, never reach, their 0.1..0.9 clamp: text alone cannot take a trait
   past the old bounds; an author can.
3. 0.5 when the text says nothing either way.

The matcher
===========

:func:`match_keywords` is the one place trait text is read. Text is lowercased
(curly apostrophes straightened), cut into clauses at punctuation and dashes,
and each clause into words; a hyphen splits words ("warm-hearted" is "warm
hearted") except after a negating prefix ("anti-social" is "antisocial"). At
each word the longest keyword that starts there wins, so "open-minded" is
never "open" and the hedge "kind of" is never kindness. A keyword counts as its
opposite when

* a negator -- ``not``, ``never``, ``no``, or a word ending in ``n't`` -- is
  one of the ``NEGATION_WINDOW`` (2) words before it in the same clause ("not
  very social"; a comma or a new list item ends its reach: "not shy, social");
* or, for a one-word keyword, the word carries a negating prefix -- ``un``,
  ``in``, ``non``, ``anti`` -- in front of it ("uncaring", "insensitive",
  "antisocial"). A word that is itself a keyword is never split this way:
  "intense" is intense, not in + "tense".

Both at once cancel ("not unkind" is kind). Each keyword counts once, with the
sign of the sum of its occurrences (+1 affirmed, -1 its opposite, 0 both).

The table
=========

``f(t) = 1 + TRAIT_RATE_SLOPE * (t - 0.5)`` (:func:`trait_multiplier`) scales a
rate: 0.5 at t = 0.1, 1 at 0.5, 1.5 at 0.9 (0.375..1.625 over 0..1). Its slope,
1.25, maps the ends of what text alone infers (0.1, 0.9) onto the 0.5..1.5
clamp every retired trait multiplier had, and one keyword (t = 0.7) onto 1.25,
the weight the retired ``AFFECT_GROWTH_TRAITS`` gave "emotional" and
"sensitive". Column "0.5" is today's number everywhere: a persona with no
traits and no trait text runs exactly as before this module existed.

| # | Trait               | Parameter (attribute)     | Formula                          | t = 0.1        | t = 0.5 (today) | t = 0.9         |
|---|---------------------|---------------------------|----------------------------------|----------------|-----------------|-----------------|
| 1 | volatility          | affect_reactivity         | f(v)                             | 0.5            | 1.0             | 1.5             |
| 2 | volatility          | mood_half_life_scale      | 1 / f(v)                         | 8.0 h / 4.0 h  | 4.0 h / 2.0 h   | 2.67 h / 1.33 h |
| 3 | volatility          | regulation_baseline       | 0.7 - 0.5 (v - 0.5), in 0.3..0.9 | 0.9            | 0.7             | 0.5             |
| 4 | warmth              | setpoint_valence_offset   | 0.25 (w - 0.5)                   | -0.1           | 0               | +0.1            |
| 5 | warmth              | empathy                   | w, in 0.1..0.9                   | 0.1            | 0.5             | 0.9             |
| 6 | sociability         | desired_contact           | s, in 0.1..0.9                   | 0.1            | 0.5             | 0.9             |
| 7 | sociability         | introversion              | 1 - s                            | 0.36/.066/.022 | 0.6/.05/.03     | 0.84/.034/.038  |
| 8 | sociability         | npc_event_scale           | f(s)                             | 0.125          | 0.25            | 0.375           |
| 9 | rumination          | rumination_rate           | f(r)                             | 0.05 / 0.01    | 0.1 / 0.005     | 0.15 / 0.0033   |
| 10| conscientiousness   | plan_adherence            | f(c)                             | 0.5 / 0.2      | 0.25 / 0.4      | 0.167 / 0.6     |
| 11| impulsivity         | plan_deviation_chance     | 0.15 max(0, i - 0.5) / 0.4       | 0              | 0               | 0.15            |
| 12| openness            | chaos_event_scale         | f(o)                             | 0.10           | 0.20            | 0.30            |
| 13| openness            | micro_event_scale         | f(o)                             | 0.10           | 0.20            | 0.30            |
| 14| weather_sensitivity | weather_mood_scale        | f(ws)                            | x 0.5          | x 1             | x 1.5           |
| 15| sociability         | need_weights["social"]    | f(s)                             | x 0.5          | x 1             | x 1.5           |
| 16| sociability         | need_weights["solitude"]  | f(1 - s)                         | x 1.5          | x 1             | x 0.5           |
| 17| volatility          | need_weights["calm"]      | f(v)                             | x 0.5          | x 1             | x 1.5           |
| 18| openness            | need_weights["stimulation"] | f(o)                           | x 0.5          | x 1             | x 1.5           |
| 19| rumination          | need_weights["reflection"] | f(r)                            | x 0.5          | x 1             | x 1.5           |
| 20| conscientiousness, rumination | problem_focus   | f(c) - f(r)                      | c - r = -0.8: -1.0 | c = r: 0     | c - r = +0.8: +1.0 |
| 21| conscientiousness, rumination | avoidance_scale | 1 + max(0, -problem_focus)       | c - r = -0.8: x 2 | c = r: x 1   | c >= r: x 1     |
| 22| sociability         | contact_seeking           | f(s) - 1                         | -0.5           | 0               | +0.5            |
| 23| 20-22               | coping_style              | the strongest of 20 and 22       | "avoidant"     | "balanced"      | "problem-focused" / "social" |

What each row sets, and what its value columns show:

1. AffectSystem's affect multiplier (conversation, location and weather
   nudges) and the scale on EMOTION_MOOD_GAIN (how far one emotion moves her
   mood). The column is the multiplier.
2. Times MOOD_VALENCE_HALF_LIFE_HOURS / MOOD_AROUSAL_HALF_LIFE_HOURS: a
   volatile mood settles faster. The columns are the two half-lives.
3. RegulationState.baseline, and the capacity she starts at (the retired
   ``_calc_regulation_baseline``).
4. Added to her set-point's valence (spec section 4.7: the set-point comes
   from the baseline "and traits").
5. EmpathyState.contagion_susceptibility: how much of the user's emotion she
   catches (the retired ``_calc_empathy``).
6. LonelinessState.desired_contact_baseline: how fast loneliness grows (the
   retired ``_calc_social_need``).
7. SocialSystem's ``introversion``, which LifeService never passed before:
   the social battery's capacity max(0.3, 0.9 - 0.6 i), recharge
   0.03 + 0.04 i and drain 0.02 + 0.02 (1 - i) (SocialSystem's own formulas).
   The columns are capacity / recharge / drain.
8. Times SocialSystem's NPC_EVENT_CHANCE, per activity tick. The column is
   the chance.
9. Times CognitiveSystem's RUMINATION_REPLAY_CHANCE, and divides its
   RUMINATION_DECAY (per cognitive tick, times the cognitive multiplier). The
   columns are replay chance / decay.
10. DailyPlanner.revise_upcoming drops upcoming slots when her energy is below
    PLAN_REVISE_ENERGY_BELOW / f(c), or a low mood's intensity is above
    PLAN_REVISE_MOOD_INTENSITY_ABOVE x f(c). The columns are those two
    thresholds.
11. DailyPlanner.abandons_slot: the chance she does something else in a
    planned free-time slot's hour (PLAN_DEVIATION_SCALE is the 0.15). Never
    a routine anchor, an important commitment or a plan agreed with the user;
    0 at and below neutral, where no draw is taken.
12. Times ChaosEngine.PROBABILITY, per activity tick. The column is the
    chance (before regulation's share).
13. Times LifeService's MICRO_EVENT_CHANCE, per activity tick. The column is
    the chance.
14. Times WEATHER_MOOD_MAP's shift of her mood target, and times the
    weather-change nudge (LifeService WEATHER_MOOD_WEIGHT).
15.-19. How much each of her needs weighs when she chooses what to do
    (``aura_life.activities.choice``: a need's shortfall times this weight
    times how much an activity meets it). An extrovert's loneliness weighs
    more, an introvert's drained social battery more (solitude is the other
    side of sociability), a volatile persona's stress, an open one's
    curiosity, a ruminating one's loops. Hunger and tiredness read no trait
    (weight 1). The columns are the multipliers.
20.-23. How she copes with what weighs on her (Task 15, the stressors of
    ``aura_life.affect``; the columns give c and r, conscientiousness and
    rumination, not one trait). Conscientiousness turns her toward a
    problem, rumination away from it (dwelling on it instead of dealing with
    it); sociability toward other people.

    20. Problem-focused (> 0) or avoidant (< 0): times COPING_WEIGHT, the pull
        of an activity that ends a stressor she can end herself, weighted by
        its controllability, when she chooses what to do
        (``aura_life.activities.choice``; ChoiceState.resolving). Only the
        problem-focused side pulls: an avoidant persona gets no push away from
        what would end it -- her avoidance is row 21.
    21. Times DriveSystem's chance to start putting something off
        (AVOIDANCE_CHANCE) and the growth of its guilt (GUILT_GROWTH_RATE):
        an avoidant persona puts more off and feels it sooner. 1 for anyone
        not avoidant.
    22. Seeking company (> 0) or not (<= 0): under stress, times COPING_WEIGHT
        and her stress level, the pull of an activity that meets her need for
        company (``aura_life.activities.choice``); on a low day, the weight of
        company among the comforts her plan swaps to (``DailyPlanner``), where
        a persona who does not seek it keeps to the gentle ones -- she
        withdraws. 0 at neutral: no pull, and a low day as it was.
    23. The name of the strongest part: "problem-focused" (row 20 above 0),
        "avoidant" (row 20 below 0) or "social" (row 22 above 0), the one
        furthest from 0 (ties in that order); "balanced" when none is. It
        names the blend; rows 20-22 are what act. ``AffectSystem`` exports it
        with her stress. Her disposition -- not ShadowSystem's
        ``coping_style``, how she is coping right now under strain.

Text-derived multipliers
========================

Five of the retired tables, and the shadow, finance and body keyword lists, do
not read one trait: their words span several, or none. They are moved here
verbatim and read by the same matcher (so "not curious" now lowers what
"curious" raises), and the numbers they give ride on the same object:

* ``energy_multiplier`` -- :data:`ENERGY_GROWTH_TRAITS`; EnergySystem's social
  boost and conversation triggers.
* ``cognitive_multiplier`` -- :data:`COGNITIVE_GROWTH_TRAITS`; CognitiveSystem's
  focus baseline, rumination decay and conversation triggers.
* ``drive_multiplier`` -- :data:`DRIVE_GROWTH_TRAITS`; DriveSystem's curiosity
  sparks, guilt growth, curiosity decay and conversation triggers.
* ``trust_multiplier`` -- :data:`IDENTITY_GROWTH_TRAITS`; IdentitySystem's trust
  and warmth growth toward the user and its esteem triggers.
* ``desire_multiplier`` -- :data:`DESIRE_GROWTH_TRAITS`; DesireSystem's arousal
  growth.

Each is ``1 + the sum of its matched words' weights`` (a word read as its
opposite subtracts its weight), clamped 0.5..1.5 -- the rule the tables had.
``shadow_leanings`` gives each of ShadowSystem's keyword sets
(:data:`SHADOW_TRAIT_SETS`) the sign of its net evidence: +1 applies the seed
as before, -1 its opposite. ``frugal`` and ``spender`` cap and floor
FinanceSystem's spending habit as :data:`FRUGAL_TRAITS` and
:data:`SPENDER_TRAITS` did, a negated word of one list counting for the
other. ``body_image_struggle`` reads :data:`BODY_IMAGE_STRUGGLE_MARKERS` over
the struggles and the core traits, as BodySystem did; a negated marker ("no
body image issues") is not a struggle.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from .keys import TRAIT_KEYS

logger = logging.getLogger(__name__)

# ============= Numbers: every one, and where it comes from =============

#: A trait with no evidence either way.
NEUTRAL = 0.5

#: How far inferred evidence can move a trait from NEUTRAL, approached and
#: never reached: the half-width of the 0.1..0.9 clamp of the retired
#: AffectSystem._calc_social_need and _calc_empathy.
INFERENCE_SPAN = 0.4

#: The slope of trait_multiplier: maps t = 0.1 / 0.9 onto 0.5 / 1.5, the
#: clamp every retired *_GROWTH_TRAITS multiplier had (derived: 0.5 / 0.4).
TRAIT_RATE_SLOPE = 1.25

#: The clamp of the retired _calc_social_need and _calc_empathy, kept for the
#: trait-valued parameters that replace them (desired_contact, empathy).
LEGACY_SCORE_BOUNDS = (0.1, 0.9)

#: The clamp of every retired trait multiplier (_calc_affect_multiplier,
#: _calc_energy_multiplier, ...), kept for the text-derived multipliers.
LEGACY_MULTIPLIER_BOUNDS = (0.5, 1.5)

#: The retired _calc_regulation_baseline: 0.7, 0.1 higher or lower per
#: keyword group, clamped 0.3..0.9. Per unit of volatility that is
#: 0.1 / 0.2 = 0.5 (one keyword moves a trait 0.2).
REGULATION_BASELINE = 0.7
REGULATION_PER_VOLATILITY = 0.5
REGULATION_BOUNDS = (0.3, 0.9)

#: Resting valence per unit of warmth above neutral. Chosen: +/-0.1 at warmth
#: 0.9 / 0.1, "slight" on the vocabulary's own valence scale
#: (aura_life.emotion.vocabulary: "+/-0.1 slight"), and below
#: MOOD_VALENCE_BAND, so warmth alone never changes a resting label.
SETPOINT_VALENCE_PER_WARMTH = 0.25

#: The chance, at impulsivity 0.9, that she drops a planned free-time slot for
#: something else; 0 at and below neutral (the planner has never dropped one
#: on a whim). Chosen: the planner's own chance of a spur-of-the-moment want
#: after an activity (DailyPlanner.generate_desire_from_activity, 0.15).
PLAN_DEVIATION_SCALE = 0.15

# ============= The matcher's rules (the brief) =============

#: Words that turn the next NEGATION_WINDOW words into their opposite. A word
#: ending in "n't" ("isn't", "doesn't") negates too.
NEGATORS = frozenset({"not", "never", "no"})
NEGATION_WINDOW = 2
#: Prefixes that make a one-word keyword its opposite, longest first.
NEGATING_PREFIXES = ("anti", "non", "un", "in")
#: Phrases that consume their words without meaning anything: "kind of shy"
#: says nothing about kindness.
HEDGES = ("kind of", "sort of")

# ============= Trait vocabularies =============

#: trait -> (words that say it is high, words that say it is low). Seeded
#: from the retired tables that read that trait (named beside each), then the
#: plain synonyms and the persona generator's own descriptors
#: (aura_life.personas.genre_randomizer) that read unambiguously one way.
TRAIT_VOCABULARY: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    "sociability": (
        # _calc_social_need: extrovert, social, outgoing, bubbly, talkative;
        # ATTENTION_TRAITS: extroverted.
        ("extrovert", "extroverted", "extravert", "extraverted", "social", "sociable",
         "outgoing", "bubbly", "talkative", "chatty", "gregarious", "people person",
         "enthusiastic"),
        # _calc_social_need: introvert, quiet, reserved, solitary, independent;
        # RESERVED_TRAITS / PRIVATE_TRAITS: shy, private.
        ("introvert", "introverted", "quiet", "reserved", "solitary", "independent",
         "loner", "shy", "withdrawn", "reclusive", "private", "socially awkward"),
    ),
    "volatility": (
        # _calc_regulation_baseline / AFFECT_GROWTH_TRAITS: volatile, emotional,
        # passionate, intense, sensitive; DRIVE_GROWTH_TRAITS: anxious.
        ("volatile", "emotional", "passionate", "intense", "sensitive", "oversensitive",
         "hypersensitive", "moody", "temperamental", "hot-tempered", "short-tempered",
         "explosive", "fiery", "mercurial", "erratic", "neurotic", "anxious", "nervous",
         "tense", "high-strung", "insecure", "self-doubting", "jealous", "clingy", "fragile",
         "unhinged"),
        # _calc_regulation_baseline / AFFECT_GROWTH_TRAITS: stable, calm, stoic,
        # composed, grounded.
        ("stable", "calm", "stoic", "composed", "grounded", "steady", "even-tempered",
         "level-headed", "cool-headed", "unflappable", "serene", "placid", "collected",
         "relaxed", "resilient", "fearless"),
    ),
    "rumination": (
        ("brooding", "broody", "ruminative", "ruminating", "overthinker", "overthinking",
         "obsessive", "fixated", "worrier", "haunted", "melancholic"),
        # COGNITIVE_GROWTH_TRAITS: carefree.
        ("carefree", "easygoing", "easy-going", "laid-back", "happy-go-lucky", "unbothered",
         "forgiving"),
    ),
    "impulsivity": (
        # UNINHIBITED_TRAITS: impulsive, wild, uninhibited, reckless;
        # SPENDER_TRAITS: impulsive, hedonist.
        ("impulsive", "wild", "uninhibited", "reckless", "spontaneous", "rash", "daring",
         "impatient", "free-spirited", "thrill-seeking", "hedonistic", "hedonist"),
        # DRIVE_GROWTH_TRAITS: cautious; FRUGAL_TRAITS: careful, disciplined.
        ("cautious", "careful", "deliberate", "measured", "patient", "restrained",
         "disciplined", "prudent", "controlled", "predictable", "inhibited"),
    ),
    "conscientiousness": (
        # DRIVE_GROWTH_TRAITS: ambitious, driven; FRUGAL_TRAITS: careful, disciplined.
        ("conscientious", "organized", "organised", "disciplined", "diligent", "responsible",
         "reliable", "dependable", "meticulous", "methodical", "systematic", "thorough",
         "rigorous", "efficient", "neat", "punctual", "orderly", "hardworking", "hard-working",
         "dutiful", "principled", "ambitious", "driven", "careful", "precise", "determined",
         "tenacious", "perfectionist"),
        # DRIVE_GROWTH_TRAITS: lazy.
        ("lazy", "disorganized", "disorganised", "careless", "messy", "sloppy", "flaky",
         "scatterbrained", "chaotic", "haphazard", "negligent", "irresponsible",
         "procrastinator"),
    ),
    "openness": (
        # COGNITIVE_GROWTH_TRAITS / DRIVE_GROWTH_TRAITS: curious, adventurous,
        # intellectual.
        ("curious", "adventurous", "intellectual", "creative", "imaginative", "inquisitive",
         "open-minded", "artistic", "philosophical", "existential", "idealistic", "eccentric",
         "whimsical", "experimental", "inventive", "innovative", "cultured", "literary",
         "well-read", "poetic"),
        ("conventional", "traditional", "rigid", "closed-minded", "narrow-minded"),
    ),
    "warmth": (
        # _calc_empathy: empathetic, caring, nurturing, warm, compassionate;
        # IDENTITY_GROWTH_TRAITS: trusting, warm.
        ("warm", "caring", "empathetic", "empathic", "nurturing", "compassionate", "trusting",
         "kind", "kind-hearted", "kindhearted", "gentle", "affectionate", "tender", "loving",
         "adoring", "devoted", "loyal", "generous", "friendly", "helpful", "cooperative",
         "supportive", "considerate", "sympathetic", "gracious", "selfless"),
        # _calc_empathy: detached, guarded (its "analytical" and "logical" are
        # not warmth words and are dropped); IDENTITY_GROWTH_TRAITS: guarded,
        # aloof; DESIRE_GROWTH_TRAITS: cold, guarded.
        ("detached", "guarded", "cold", "aloof", "distant", "callous", "cruel", "harsh", "rude",
         "hostile", "manipulative", "calculating", "controlling", "coercive", "deceitful",
         "two-faced", "disloyal", "distrustful", "vindictive", "ruthless", "menacing",
         "predatory", "selfish", "stingy", "heartless"),
    ),
    "weather_sensitivity": (
        ("weather-sensitive", "sensitive to weather", "sensitive to the weather",
         "affected by weather", "affected by the weather"),
        (),
    ),
}

# ============= The retired engine tables, moved here verbatim =============

#: EnergySystem's growth multiplier (was energy_system.ENERGY_GROWTH_TRAITS).
ENERGY_GROWTH_TRAITS = {
    "energetic": 0.2, "bubbly": 0.2, "lively": 0.15,
    "quiet": -0.1, "reserved": -0.1, "lethargic": -0.15,
}

#: CognitiveSystem's multiplier (was cognitive_system.COGNITIVE_GROWTH_TRAITS).
COGNITIVE_GROWTH_TRAITS = {
    "curious": 0.25, "analytical": 0.2, "intellectual": 0.2, "thoughtful": 0.15,
    "impulsive": -0.15, "carefree": -0.1,
}

#: DriveSystem's multiplier (was drive_system.DRIVE_GROWTH_TRAITS).
DRIVE_GROWTH_TRAITS = {
    "curious": 0.3, "adventurous": 0.2, "ambitious": 0.15, "driven": 0.15,
    "lazy": -0.2, "cautious": -0.1, "anxious": -0.1,
}

#: IdentitySystem's trust multiplier (was identity_system.IDENTITY_GROWTH_TRAITS).
IDENTITY_GROWTH_TRAITS = {
    "open": 0.2, "trusting": 0.25, "warm": 0.15, "vulnerable": 0.2,
    "guarded": -0.25, "independent": -0.15, "aloof": -0.2,
}

#: DesireSystem's growth multiplier (was desire_system.DESIRE_GROWTH_TRAITS).
DESIRE_GROWTH_TRAITS = {
    "passionate": 0.3, "sensual": 0.3, "romantic": 0.2, "flirty": 0.2,
    "warm": 0.1,
    "reserved": -0.2, "cold": -0.3, "guarded": -0.2, "stoic": -0.15,
}

#: ShadowSystem's seeding keyword sets (were shadow_system.REBEL_TRAITS ...
#: AUTONOMY_TRAITS), by the name ShadowSystem looks them up under.
SHADOW_TRAIT_SETS: Dict[str, FrozenSet[str]] = {
    "rebel": frozenset({"rebellious", "defiant", "stubborn", "contrarian"}),
    "submissive": frozenset({"submissive", "deferential", "meek", "compliant"}),
    "dominant": frozenset({"dominant", "assertive", "commanding", "domineering"}),
    "uninhibited": frozenset({"impulsive", "wild", "uninhibited", "reckless"}),
    "reserved": frozenset({"reserved", "proper", "shy"}),
    "attention": frozenset({"dramatic", "extroverted", "flirty", "validation", "needy"}),
    "private": frozenset({"private", "reserved"}),
    "autonomy": frozenset({"independent", "assertive", "strong-willed", "stubborn"}),
}

#: FinanceSystem's spending-habit words (were inline in
#: FinanceSystem._apply_trait_habits).
FRUGAL_TRAITS = ("frugal", "thrifty", "saver", "careful", "disciplined")
SPENDER_TRAITS = ("impulsive", "lavish", "extravagant", "spender", "indulgent", "hedonist")

#: Phrases in struggles/traits that lower the body_image baseline (was
#: body_system.BODY_IMAGE_STRUGGLE_MARKERS). "eating disorders" is added: the
#: substring check matched the plural, a word-boundary match does not.
BODY_IMAGE_STRUGGLE_MARKERS = (
    "body issues",
    "body image",
    "insecure about her looks",
    "insecure about my looks",
    "eating disorder",
    "eating disorders",
    "hates her body",
    "hate my body",
)

# ============= The matcher =============

_WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)*")
_CLAUSE_RE = re.compile(r"[.,;:!?()\[\]{}\"/|\u2014\u2013\r\n]+|\s-\s")
_PREFIX_HYPHEN_RE = re.compile(r"\b(" + "|".join(NEGATING_PREFIXES) + r")-(?=[a-z])")


def _normalise(text: str) -> str:
    """Lowercase, straighten curly apostrophes, and join a negating prefix to
    its word ("anti-social" -> "antisocial")."""
    text = str(text).lower().replace("\u2019", "'").replace("\u2018", "'")
    return _PREFIX_HYPHEN_RE.sub(r"\1", text)


def _key(keyword: str) -> str:
    """A keyword as the matcher stores it: its words joined by one space."""
    return " ".join(_WORD_RE.findall(_normalise(keyword)))


def _all_keywords() -> List[str]:
    words: List[str] = list(HEDGES) + list(FRUGAL_TRAITS) + list(SPENDER_TRAITS)
    words += list(BODY_IMAGE_STRUGGLE_MARKERS)
    for raise_words, lower_words in TRAIT_VOCABULARY.values():
        words += list(raise_words) + list(lower_words)
    for table in (ENERGY_GROWTH_TRAITS, COGNITIVE_GROWTH_TRAITS, DRIVE_GROWTH_TRAITS,
                  IDENTITY_GROWTH_TRAITS, DESIRE_GROWTH_TRAITS):
        words += list(table)
    for members in SHADOW_TRAIT_SETS.values():
        words += list(members)
    return words


def _build_index() -> Tuple[Dict[str, List[Tuple[str, ...]]], FrozenSet[str]]:
    """First word -> every keyword starting with it, longest first; and the
    set of one-word keywords (the roots a negating prefix can attach to)."""
    index: Dict[str, List[Tuple[str, ...]]] = {}
    for keyword in _all_keywords():
        words = tuple(_key(keyword).split())
        if not words:
            raise ValueError(f"keyword {keyword!r} has no words")
        candidates = index.setdefault(words[0], [])
        if words not in candidates:
            candidates.append(words)
    for candidates in index.values():
        candidates.sort(key=len, reverse=True)
    singles = frozenset(w[0] for candidates in index.values() for w in candidates if len(w) == 1)
    return index, singles


_INDEX, _SINGLE_WORDS = _build_index()
_HEDGE_KEYS = frozenset(_key(h) for h in HEDGES)


def _clauses(texts: Iterable[str]) -> Iterable[List[str]]:
    for text in texts:
        for clause in _CLAUSE_RE.split(_normalise(text)):
            words = _WORD_RE.findall(clause)
            if words:
                yield words


def _match_at(words: Sequence[str], i: int) -> Tuple[Optional[str], int, int]:
    """(keyword, polarity, words consumed) for the longest keyword starting at
    ``words[i]``: polarity +1, or -1 for a one-word keyword behind a negating
    prefix. (None, 0, 1) when none starts there."""
    word = words[i]
    for candidate in _INDEX.get(word, ()):
        if tuple(words[i:i + len(candidate)]) == candidate:
            return " ".join(candidate), 1, len(candidate)
    if word not in _SINGLE_WORDS:
        for prefix in NEGATING_PREFIXES:
            if word.startswith(prefix) and word[len(prefix):] in _SINGLE_WORDS:
                return word[len(prefix):], -1, 1
    return None, 0, 1


def _negated(words: Sequence[str], i: int) -> bool:
    return any(w in NEGATORS or w.endswith("n't") for w in words[max(0, i - NEGATION_WINDOW):i])


def match_keywords(texts: Iterable[str]) -> Dict[str, int]:
    """Every keyword this module knows that ``texts`` mention, with its
    direction: +1 affirmed, -1 read as its opposite (a negator within
    NEGATION_WINDOW words before it, or a negating prefix), 0 when both occur.
    Keys are the keywords as stored (words joined by one space, hyphens
    split). The rules are in the module docstring."""
    sums: Dict[str, int] = {}
    for words in _clauses(texts):
        i = 0
        while i < len(words):
            keyword, polarity, consumed = _match_at(words, i)
            if keyword is not None and keyword not in _HEDGE_KEYS:
                if _negated(words, i):
                    polarity = -polarity
                sums[keyword] = sums.get(keyword, 0) + polarity
            i += consumed
    return {keyword: (total > 0) - (total < 0) for keyword, total in sums.items()}


# ============= From evidence to numbers =============

def trait_multiplier(t: float) -> float:
    """f(t) = 1 + TRAIT_RATE_SLOPE * (t - 0.5): how far a trait scales a rate
    (0.5 at 0.1, 1 at 0.5, 1.5 at 0.9)."""
    return 1.0 + TRAIT_RATE_SLOPE * (t - NEUTRAL)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


_VOCABULARY = {
    trait: (tuple(_key(w) for w in raise_words), tuple(_key(w) for w in lower_words))
    for trait, (raise_words, lower_words) in TRAIT_VOCABULARY.items()
}


def _inferred(evidence: Mapping[str, int], trait: str) -> Optional[float]:
    raise_words, lower_words = _VOCABULARY[trait]
    high = low = 0
    for keyword, says_high in [(w, True) for w in raise_words] + [(w, False) for w in lower_words]:
        sign = evidence.get(keyword, 0)
        if sign == 0:
            continue
        if (sign > 0) == says_high:
            high += 1
        else:
            low += 1
    if high == low == 0:
        return None
    return NEUTRAL + INFERENCE_SPAN * (high - low) / (high + low + 1)


def _weighted_multiplier(evidence: Mapping[str, int], table: Mapping[str, float]) -> float:
    total = 1.0 + sum(weight * evidence.get(_key(word), 0) for word, weight in table.items())
    return _clamp(total, *LEGACY_MULTIPLIER_BOUNDS)


def _lean(evidence: Mapping[str, int], words: Iterable[str]) -> int:
    net = sum(evidence.get(_key(word), 0) for word in words)
    return (net > 0) - (net < 0)


def _any_sign(evidence: Mapping[str, int], words: Iterable[str], sign: int) -> bool:
    return any(evidence.get(_key(word), 0) == sign for word in words)


def _texts(raw) -> List[str]:
    """A definition's text field as a list of strings (a bare string is one
    text, not a sequence of characters)."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    try:
        return [str(item) for item in raw if item is not None]
    except TypeError:
        return []


def _authored(raw) -> Dict[str, float]:
    """The explicit traits worth taking: a TRAIT_KEYS name with a number in
    0..1. Anything else is left to inference."""
    if not isinstance(raw, Mapping):
        return {}
    taken: Dict[str, float] = {}
    for key, value in raw.items():
        name = str(key).strip().lower()
        if name not in TRAIT_KEYS:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
            logger.warning("PersonaParameters: trait %r = %r is not a number in 0..1; inferred instead",
                           name, value)
            continue
        taken[name] = float(value)
    return taken


# ============= The object =============

@dataclass(frozen=True)
class PersonaParameters:
    """One persona's eight traits and the engine parameters derived from them
    (the table in this module's docstring). Build it with
    :meth:`from_definition`; ``PersonaParameters()`` is the neutral persona,
    every trait 0.5, which runs every engine exactly as it ran before traits
    existed."""

    sociability: float = NEUTRAL
    volatility: float = NEUTRAL
    rumination: float = NEUTRAL
    impulsivity: float = NEUTRAL
    conscientiousness: float = NEUTRAL
    openness: float = NEUTRAL
    warmth: float = NEUTRAL
    weather_sensitivity: float = NEUTRAL
    #: The traits the definition authored; the rest were inferred or neutral.
    explicit: FrozenSet[str] = frozenset()
    # Text-derived multipliers (module docstring, "Text-derived multipliers").
    energy_multiplier: float = 1.0
    cognitive_multiplier: float = 1.0
    drive_multiplier: float = 1.0
    trust_multiplier: float = 1.0
    desire_multiplier: float = 1.0
    #: SHADOW_TRAIT_SETS name -> +1 / -1; a set with no net evidence is absent.
    shadow_leanings: Mapping[str, int] = field(default_factory=dict)
    frugal: bool = False
    spender: bool = False
    body_image_struggle: bool = False

    def __post_init__(self) -> None:
        for key in TRAIT_KEYS:
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
                raise ValueError(f"PersonaParameters.{key} must be a number in 0..1, got {value!r}")

    # ---- Building one ----

    @classmethod
    def from_definition(cls, defn) -> "PersonaParameters":
        """Compile a persona definition (a ``PersonalityDefinition``, or
        anything with its ``traits`` / ``core_traits`` / ``struggles``
        attributes; ``None`` is neutral). Explicit ``traits`` win; a trait
        they do not give is inferred from ``core_traits``, or 0.5."""
        if defn is None:
            return cls()
        return cls._compile(
            core_traits=_texts(getattr(defn, "core_traits", None)),
            struggles=_texts(getattr(defn, "struggles", None)),
            authored=_authored(getattr(defn, "traits", None)),
        )

    @classmethod
    def from_core_traits(cls, core_traits=None, struggles=None) -> "PersonaParameters":
        """The parameters trait text alone gives -- what an engine built from
        ``core_traits=`` (and BodySystem from ``struggles=``) used to read
        itself."""
        return cls._compile(core_traits=_texts(core_traits), struggles=_texts(struggles), authored={})

    @classmethod
    def _compile(cls, core_traits: List[str], struggles: List[str],
                 authored: Dict[str, float]) -> "PersonaParameters":
        evidence = match_keywords(core_traits)
        traits: Dict[str, float] = {}
        for key in TRAIT_KEYS:
            if key in authored:
                traits[key] = authored[key]
            else:
                inferred = _inferred(evidence, key)
                traits[key] = NEUTRAL if inferred is None else inferred
        leanings = {}
        for name, words in SHADOW_TRAIT_SETS.items():
            lean = _lean(evidence, words)
            if lean:
                leanings[name] = lean
        body_evidence = match_keywords(struggles + core_traits) if struggles else evidence
        return cls(
            **traits,
            explicit=frozenset(authored),
            energy_multiplier=_weighted_multiplier(evidence, ENERGY_GROWTH_TRAITS),
            cognitive_multiplier=_weighted_multiplier(evidence, COGNITIVE_GROWTH_TRAITS),
            drive_multiplier=_weighted_multiplier(evidence, DRIVE_GROWTH_TRAITS),
            trust_multiplier=_weighted_multiplier(evidence, IDENTITY_GROWTH_TRAITS),
            desire_multiplier=_weighted_multiplier(evidence, DESIRE_GROWTH_TRAITS),
            shadow_leanings=leanings,
            frugal=_any_sign(evidence, FRUGAL_TRAITS, 1) or _any_sign(evidence, SPENDER_TRAITS, -1),
            spender=_any_sign(evidence, SPENDER_TRAITS, 1) or _any_sign(evidence, FRUGAL_TRAITS, -1),
            body_image_struggle=_any_sign(body_evidence, BODY_IMAGE_STRUGGLE_MARKERS, 1),
        )

    def traits(self) -> Dict[str, float]:
        """The eight traits, in TRAIT_KEYS order."""
        return {key: getattr(self, key) for key in TRAIT_KEYS}

    # ---- The table (module docstring) ----

    @property
    def affect_reactivity(self) -> float:
        """volatility: AffectSystem's affect multiplier and emotion-gain scale."""
        return trait_multiplier(self.volatility)

    @property
    def mood_half_life_scale(self) -> float:
        """volatility: times the mood half-lives (a volatile mood settles faster)."""
        return 1.0 / trait_multiplier(self.volatility)

    @property
    def regulation_baseline(self) -> float:
        """volatility: her regulation baseline (the retired _calc_regulation_baseline)."""
        return _clamp(REGULATION_BASELINE - REGULATION_PER_VOLATILITY * (self.volatility - NEUTRAL),
                      *REGULATION_BOUNDS)

    @property
    def setpoint_valence_offset(self) -> float:
        """warmth: added to her set-point's valence."""
        return SETPOINT_VALENCE_PER_WARMTH * (self.warmth - NEUTRAL)

    @property
    def empathy(self) -> float:
        """warmth: her contagion susceptibility (the retired _calc_empathy)."""
        return _clamp(self.warmth, *LEGACY_SCORE_BOUNDS)

    @property
    def desired_contact(self) -> float:
        """sociability: her desired contact baseline (the retired _calc_social_need)."""
        return _clamp(self.sociability, *LEGACY_SCORE_BOUNDS)

    @property
    def introversion(self) -> float:
        """sociability: SocialSystem's introversion, which sizes her social battery."""
        return 1.0 - self.sociability

    @property
    def npc_event_scale(self) -> float:
        """sociability: times the chance her people get in touch."""
        return trait_multiplier(self.sociability)

    @property
    def rumination_rate(self) -> float:
        """rumination: times a loop's replay chance, and divides its decay."""
        return trait_multiplier(self.rumination)

    @property
    def plan_adherence(self) -> float:
        """conscientiousness: how much tiredness or low mood it takes to drop plans."""
        return trait_multiplier(self.conscientiousness)

    @property
    def plan_deviation_chance(self) -> float:
        """impulsivity: the chance she drops a planned free-time slot on a whim."""
        return PLAN_DEVIATION_SCALE * max(0.0, self.impulsivity - NEUTRAL) / INFERENCE_SPAN

    @property
    def chaos_event_scale(self) -> float:
        """openness: times the chance of a chaos event."""
        return trait_multiplier(self.openness)

    @property
    def micro_event_scale(self) -> float:
        """openness: times the chance of a small moment (a micro-event)."""
        return trait_multiplier(self.openness)

    @property
    def weather_mood_scale(self) -> float:
        """weather_sensitivity: times the weather's pull on her mood."""
        return trait_multiplier(self.weather_sensitivity)

    @property
    def need_weights(self) -> Dict[str, float]:
        """Rows 15-19: need -> how much it weighs when she chooses what to
        do (``aura_life.activities.choice``). A need not listed weighs 1."""
        return {
            "social": trait_multiplier(self.sociability),
            "solitude": trait_multiplier(1.0 - self.sociability),
            "calm": trait_multiplier(self.volatility),
            "stimulation": trait_multiplier(self.openness),
            "reflection": trait_multiplier(self.rumination),
        }

    # ---- How she copes (rows 20-23; Task 15) ----

    @property
    def problem_focus(self) -> float:
        """Row 20, conscientiousness and rumination: above 0 she turns to what
        would end a stressor she can end herself; below 0 she avoids it."""
        return trait_multiplier(self.conscientiousness) - trait_multiplier(self.rumination)

    @property
    def avoidance_scale(self) -> float:
        """Row 21: times the chance she starts putting something off and the
        growth of its guilt -- above 1 only when she is avoidant."""
        return 1.0 + max(0.0, -self.problem_focus)

    @property
    def contact_seeking(self) -> float:
        """Row 22, sociability: above 0 she reaches for company under stress
        and on a low day; at or below 0 she does not."""
        return trait_multiplier(self.sociability) - 1.0

    @property
    def coping_style(self) -> str:
        """Row 23: "problem-focused", "avoidant" or "social" -- the strongest
        of rows 20 and 22 -- or "balanced" when none leans."""
        strengths = (("problem-focused", self.problem_focus), ("avoidant", -self.problem_focus),
                     ("social", self.contact_seeking))
        style, strength = max(strengths, key=lambda item: item[1])
        return style if strength > 0.0 else "balanced"


__all__ = [
    "PersonaParameters",
    "match_keywords",
    "trait_multiplier",
    "TRAIT_VOCABULARY",
    "NEGATORS",
    "NEGATION_WINDOW",
    "NEGATING_PREFIXES",
    "HEDGES",
    "ENERGY_GROWTH_TRAITS",
    "COGNITIVE_GROWTH_TRAITS",
    "DRIVE_GROWTH_TRAITS",
    "IDENTITY_GROWTH_TRAITS",
    "DESIRE_GROWTH_TRAITS",
    "SHADOW_TRAIT_SETS",
    "FRUGAL_TRAITS",
    "SPENDER_TRAITS",
    "BODY_IMAGE_STRUGGLE_MARKERS",
]
