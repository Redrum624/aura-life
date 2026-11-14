"""
Affect Engine

Tracks background emotional coloring that persists beyond discrete emotion spikes:
- Mood: hours-to-days emotional undertone, a (valence, arousal) point read as
  a label (content, happy, calm, restless, irritable, anxious, low, flat,
  neutral) -- see "Mood model" below
- Stress: what weighs on her -- stressors, each with a severity, a
  controllability and an expiry, and the level they make -- see "Stress"
  below
- Loneliness: gap between desired and actual social contact
- Regulation: emotional capacity battery (depletes under sustained demand)
- Empathy: emotional contagion from user and NPCs
"""

import json
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from ..body.body_system import SLEEP_QUALITY_BASE, UNWELL_THRESHOLD
from ..emotion.vocabulary import NEUTRAL_POINT, valence_arousal
from ..energy.energy_system import EnergySystem
from ..models import (
    MoodState,
    StressState,
    Stressor,
    LonelinessState,
    RegulationState,
    EmpathyState,
)
from ..personas.parameters import PersonaParameters
from ..social.social_system import UNWELCOME_STRESSOR
from ..sustenance.sustenance_system import HUNGRY_THRESHOLD
# Legacy name: what each work event makes her feel moved, unchanged, into the
# contemporary setting pack (aura_life.settings.contemporary) with the events
# it is keyed by, in Task 9's fix round (ruling T9-R5) -- LifeService reads
# the persona's setting now; re-exported so an import from here keeps working.
from ..settings.contemporary import WORK_EVENT_EMOTIONS  # noqa: F401

logger = logging.getLogger(__name__)

# ============= Mood model: every constant, and where it comes from =============
# Mood is a point: valence -1..1 (unpleasant..pleasant) and arousal 0..1
# (depleted..keyed up), the axes of the emotion vocabulary
# (aura_life.emotion.vocabulary). What moves it:
#
# * It is pulled back toward a target, with half-lives in hours. The caller
#   passes the hours (LifeService: world-clock time since its last energy
#   tick); this engine reads no clock for it.
# * The target is her set-point -- where her emotional_baseline puts her,
#   negative entries included, and her warmth moves its valence -- shifted by
#   the day's quality (a good or a bad day, drawn each morning: DAY_QUALITY_SD,
#   ruling T14-R1), the weather and season she is in (WEATHER_MOOD_MAP,
#   SEASON_MOOD_MAP), and pulled down by her unmet needs: loneliness, chronic
#   stress, hunger, sleep pressure, illness or pain.
# * Each emotion event moves mood part of the way toward that emotion's own
#   point in the vocabulary, so a stream of mild pleasant emotions can bring
#   her near "content" but never carry her past it.
# * Conversation, location and weather nudges move valence part of the way
#   toward the end they point at.
#
# Her traits scale four of the numbers below, through the one table in
# aura_life.personas.parameters (PersonaParameters): volatility the half-lives
# (mood_half_life_scale) and how far an emotion or a nudge moves her
# (affect_reactivity), warmth her set-point's valence
# (setpoint_valence_offset), weather_sensitivity the weather's pull
# (weather_mood_scale). At every trait 0.5 each scale is 1 and the offset 0:
# the numbers below, as they are.
#
# mood.current_mood is the label read off the (valence, arousal) pair
# (mood_label) and mood.intensity how far the pair sits from neutral
# (mood_intensity).

#: Hours for the valence (arousal) gap to its target to halve. Chosen: mood is
#: this module's "hours-to-days undertone", slow beside EmotionEngine's
#: emotions, which fade in minutes (EmotionEngine.BASE_DECAY_RATE, 0.001 per
#: second); how keyed-up she is settles faster than how good she feels.
#: Per persona, times PersonaParameters.mood_half_life_scale (volatility).
MOOD_VALENCE_HALF_LIFE_HOURS = 4.0
MOOD_AROUSAL_HALF_LIFE_HOURS = 2.0

#: The share of the way to an emotion's point that one emotion event of
#: intensity 1.0 moves mood, scaled by the event's intensity (after the
#: regulation modulation on_emotion_event applies). Set from a measurement, so
#: that an hour's emotions pull about as hard as the hour's pull back to the
#: target, valence's 1 - 2 ** (-1 / MOOD_VALENCE_HALF_LIFE_HOURS) = 0.159: in
#: three simulated days of tests/sim_helpers.py at production cadence (each
#: tick at LifeScheduler's own interval), the emotion events of a waking hour
#: -- activities, intimate activities, micro-events, chaos, goals, work,
#: anticipations -- add up to 2.03 of effective intensity (1.97-2.13 over four
#: seeds and three personas), so 0.159 / 2.03 = 0.078, rounded to 0.08. (At
#: the legacy cadence, every tick every 15 minutes, the same measure is 2.50,
#: which would give 0.064.) Re-measured the same way after Task 14 made each
#: activity's feelings her appraisal of how it went: 1.922 per waking hour
#: before it (Task 10's tree) and 2.076 after (2.02-2.18; seeds 1-4, the same
#: three personas), which gives 0.077 -- still 0.08 to its rounding, so it
#: stands. Per persona, times
#: PersonaParameters.affect_reactivity (volatility) -- once: an appraised
#: emotion (Task 14, aura_life.emotion.appraisal) comes with it already
#: applied (on_emotion_event's reactivity_applied).
EMOTION_MOOD_GAIN = 0.08

#: The set-point is the mean of her baseline emotions' points, each weighted by
#: its intensity, together with the vocabulary's neutral point at this weight.
#: Chosen: the neutral point weighs as much as one emotion felt at full
#: intensity, so a faint baseline stays near neutral and every entry moves the
#: set-point its own way -- a sad entry always lowers it, a glad one raises it.
#: Her warmth then adds PersonaParameters.setpoint_valence_offset to its
#: valence (0 at warmth 0.5).
SETPOINT_NEUTRAL_WEIGHT = 1.0

#: The level below which each need does not move mood; above it, the need's
#: shortfall rises linearly to 1 at the need's maximum (1.0).
NEED_FLOORS = {
    # get_loneliness_description says nothing below 0.2.
    "loneliness": 0.2,
    # get_stress_description says nothing below 0.2 (LifeService's
    # SANITY_STRESSED_LEVEL reads stress from the same floor).
    "stress": 0.2,
    # SustenanceSystem.hunger_label calls her "satisfied" below 0.4.
    "hunger": 0.4,
    # Below the pressure she needs to fall asleep, she is not short of sleep.
    "sleep_pressure": EnergySystem.SLEEP_PRESSURE_TO_FALL_ASLEEP,
    # Below body_system's UNWELL_THRESHOLD an illness or injury counts as over.
    "illness": UNWELL_THRESHOLD,
}

#: How far each need, at its full shortfall, pulls the valence target down.
#: Chosen, and the same for every need: nothing measured says one need weighs
#: more than another. One need at its full shortfall about cancels an
#: afternoon of pleasant activities; several together take her negative.
NEED_VALENCE_PULL = 0.4

#: How far a need at its full shortfall moves the arousal target. Loneliness
#: quiets her by as much as "lonely" sits below neutral arousal in the
#: vocabulary (derived: 0.2 - 0.3 = -0.1), so a lonely mood reads low, not
#: irritable. Sleep pressure makes her drowsy and chronic stress keeps her
#: keyed up (chosen: -0.3, +0.3). Hunger and illness leave arousal alone.
NEED_AROUSAL_PULLS = {
    "loneliness": valence_arousal("lonely")[1] - NEUTRAL_POINT[1],
    "sleep_pressure": -0.3,
    "stress": 0.3,
}

#: While she sleeps, arousal is pulled to sleep's own level instead of the
#: waking target, so her mood reads quiet through the night and groggy for a
#: while after she wakes. Derived: the vocabulary's arousal for "sleepy". (Her
#: sleep pressure falls while she sleeps, so without this her arousal would
#: climb back toward her waking set-point as the night went on.)
ASLEEP_AROUSAL = valence_arousal("sleepy")[1]

# ---- Mood inputs the events bring (LifeService feeds them) ----

#: What completing a goal makes her feel (LifeService._on_goal_tick): the
#: emotions the goal-completion life event has always recorded.
GOAL_COMPLETION_EMOTIONS = {"proud": 0.4, "satisfied": 0.3}

#: How strongly an anticipation (looking forward to something, or dreading
#: it) is felt: this times its intensity, per world hour it lasts
#: (LifeService._on_energy_tick). The 0.1 the energy tick always fed, per tick
#: until now -- read per hour, so she feels it the same whatever the tick
#: cadence (twelve times less than a 5-minute tick fed it per hour).
ANTICIPATION_MOOD_PER_HOUR = 0.1

# ---- A day's quality (ruling T14-R1: "bad days") ----
# Some days are better than others, for no reason that shows. Once per
# persona-local date, at her first waking tick outside her sleep window
# (LifeService._draw_day_quality), a day is drawn (new_day): an offset on the
# valence of her mood's target that lasts until the next day's draw,
#
#     offset = affect_reactivity x (gauss(0, DAY_QUALITY_SD)
#                                   + DAY_QUALITY_PER_SLEEP_QUALITY x (last night's sleep quality
#                                                                      - SLEEP_QUALITY_BASE))
#
# clamped to the valence scale -- her volatility makes her days swing wider,
# and a poor night lowers the day after it. Valence only: how keyed up she is
# stays the energy model's.

#: The spread of the drawn part of a day's quality, on the valence of her
#: mood's target: a normal distribution's standard deviation. TUNED against
#: the humanness spec's "no mood label on more than 70% of a persona's waking
#: ticks" (section 6; rulings P1, T4-R2, T14-R1), as OUTCOME_BASE_RISK was
#: against its own threshold: over three simulated days at the scheduler's
#: own cadence, the no-profile control and Lina's and Roberta's emotional
#: baselines, seeds 1-10 (the Task 14 report, fix round 1), the seeds on
#: which no label held more than 70% of a persona's waking ticks were, for
#: control / Lina / Roberta, 6-9/6-8/6-7 at 0.3-0.35, 9/8/8 at 0.4, 9/9/8
#: at 0.45, 9/9/10 at 0.5, 8/10/10 at 0.55 and 8/10/10 at 0.6 (wider days
#: pin the lonely control on "low" instead) -- 0.5 is the best of both ends
#: (the same 9/9/10 with DailyPlanner's low-mood comforts drawn by her
#: preference). Her mood settles about half way from her other pulls toward
#: this target, so a day one SD out moves her actual mood by about 0.25: an
#: eighth of the valence scale.
DAY_QUALITY_SD = 0.5
#: How far a night's sleep quality away from SLEEP_QUALITY_BASE (the
#: body's own base for an untroubled night) moves the next day's quality,
#: per unit of quality. Chosen, not tuned against the threshold: sleep
#: quality barely moves in the three-day runs it is measured on (no stress
#: builds there), so the threshold cannot tell values apart. At this weight
#: a poor night (quality 0.3) lowers the day by 0.2 before her volatility's
#: multiplier: 0.4 SD of the drawn part.
DAY_QUALITY_PER_SLEEP_QUALITY = 0.5

# (The words each label reads as in context are text, not numbers:
# AffectSystem.MOOD_DESCRIPTIONS.)

#: Valence within this band either side of zero is neither pleasant nor
#: unpleasant. Chosen.
MOOD_VALENCE_BAND = 0.15
#: Arousal below MOOD_AROUSAL_LOW is quiet (calm, flat); at or above
#: MOOD_AROUSAL_HIGH keyed up (happy, restless, anxious). Chosen with the
#: vocabulary's neutral arousal (0.3) inside the middle band, not on an edge,
#: so a mood resting at neutral reads "neutral".
MOOD_AROUSAL_LOW = 0.25
MOOD_AROUSAL_HIGH = 0.55
#: An unpleasant mood is quiet -- "low" -- up to and including this arousal;
#: "irritable" needs arousal raised above it. Derived: the vocabulary's neutral
#: arousal. Sadness, grief and loneliness are unpleasant without being keyed
#: up, and a baseline of them rests near neutral arousal, which the pleasant
#: and neutral rows count as middle; for them it has to read low.
MOOD_UNPLEASANT_QUIET_UP_TO = NEUTRAL_POINT[1]

#: The label grid: (valence band, arousal band) -> label.
_MOOD_GRID = {
    ("pleasant", "quiet"): "calm", ("pleasant", "middle"): "content", ("pleasant", "keyed"): "happy",
    ("neither", "quiet"): "flat", ("neither", "middle"): "neutral", ("neither", "keyed"): "restless",
    ("unpleasant", "quiet"): "low", ("unpleasant", "middle"): "irritable", ("unpleasant", "keyed"): "anxious",
}
#: Every label mood.current_mood can take.
MOOD_LABELS = ("content", "happy", "calm", "restless", "irritable", "anxious", "low", "flat", "neutral")

#: The emotions that drain regulation when felt: the five names this set has
#: always listed, kept as they are -- the vocabulary does not widen it to every
#: aroused name.
HIGH_AROUSAL_EMOTIONS = {"excited", "anxious", "angry", "startled", "restless"}

#: The emotions whose empathic contagion tires her: the eight names the old
#: NEGATIVE_EMOTIONS set listed, kept as they are -- the vocabulary does not
#: widen it to every unpleasant name.
EMPATHIC_FATIGUE_EMOTIONS = {"sad", "anxious", "frustrated", "angry", "lonely", "hurt", "overwhelmed", "raw"}

#: The hours a tick() given none stands for. Derived: LifeScheduler runs the
#: energy tick every 5 minutes (LifeScheduler.TICK_INTERVAL_MINUTES["energy"]),
#: the cadence the old per-tick mood decay assumed.
DEFAULT_TICK_HOURS = 5 / 60

# ============= Loneliness, regulation, empathy: on the hours scale =============
#
# Each amount below is the value the code had per 5-minute energy tick
# (DEFAULT_TICK_HOURS), kept as it was (ruling R18; Task 34). They were per
# tick whatever the world time a tick stood for, so the host's tick interval
# set how lonely she got, how fast she steadied and how long another's pain
# stayed with her: at the 15-minute cadence of the simulation harness she had
# a third of the loneliness she had at the scheduler's 5-minute tick. Now a
# tick of ``hours`` does what hours / DEFAULT_TICK_HOURS default ticks ending
# at its ``now`` did, and one default tick does bit for bit what a tick
# always did.

#: Her loneliness before any meaningful interaction, times her desired
#: contact: 0.005 a tick -- 0.06 an hour.
LONELINESS_GROWTH_PER_TICK = 0.005
#: Her loneliness counted from her last meaningful interaction: a tick adds
#: her desired contact x 0.003 x the hours since past LONELINESS_GRACE_HOURS,
#: over LONELINESS_GAP_SCALE_HOURS -- an hour, twelve such ticks: 0.036 x her
#: desired contact x the hours past the grace / 4, the hours since counted at
#: each tick.
LONELINESS_GAP_GROWTH_PER_TICK = 0.003
#: The hours after a meaningful interaction before her loneliness grows again.
LONELINESS_GRACE_HOURS = 4
#: The hours past the grace over which a tick's growth reaches
#: LONELINESS_GAP_GROWTH_PER_TICK (times her desired contact).
LONELINESS_GAP_SCALE_HOURS = 4
#: Her regulation's pull back to its baseline: 2% of the gap a tick -- an
#: hour closes 1 - 0.98 ** 12, about 21.5% of it (half in about 2.86 hours).
REGULATION_RETURN_PER_TICK = 0.02
#: Her empathic fatigue's fade: 0.005 a tick -- 0.06 an hour.
EMPATHIC_FATIGUE_FADE_PER_TICK = 0.005
#: An absorbed emotion's fade: 0.02 a tick -- 0.24 an hour; under
#: ABSORBED_EMOTION_LET_GO_BELOW she lets it go.
ABSORBED_EMOTION_FADE_PER_TICK = 0.02
ABSORBED_EMOTION_LET_GO_BELOW = 0.01


def mood_label(valence: float, arousal: float) -> str:
    """The mood label for a (valence, arousal) point: its cell in the 3 x 3 grid
    that MOOD_VALENCE_BAND and MOOD_AROUSAL_LOW / MOOD_AROUSAL_HIGH draw -- the
    unpleasant row's quiet cell ("low") reaching up to
    MOOD_UNPLEASANT_QUIET_UP_TO instead of MOOD_AROUSAL_LOW."""
    if valence >= MOOD_VALENCE_BAND:
        tone = "pleasant"
    elif valence <= -MOOD_VALENCE_BAND:
        tone = "unpleasant"
    else:
        tone = "neither"
    if tone == "unpleasant":
        quiet = arousal <= MOOD_UNPLEASANT_QUIET_UP_TO
    else:
        quiet = arousal < MOOD_AROUSAL_LOW
    if quiet:
        energy = "quiet"
    elif arousal >= MOOD_AROUSAL_HIGH:
        energy = "keyed"
    else:
        energy = "middle"
    return _MOOD_GRID[(tone, energy)]


def mood_intensity(valence: float, arousal: float) -> float:
    """How far a (valence, arousal) point sits from neutral, 0..1: the larger of
    |valence| and arousal's distance from the neutral arousal, the latter over
    the room arousal has above neutral in either direction -- so drowsy never
    reads as strong a mood as keyed-up."""
    neutral_arousal = NEUTRAL_POINT[1]
    return min(1.0, max(abs(valence), abs(arousal - neutral_arousal) / (1.0 - neutral_arousal)))


# ============= Stress: what weighs on her (humanness program Task 15) =============
# Each thing that weighs on her is a Stressor (aura_life.models): what it is
# about, in her words (``source``), how much it weighs (``severity``), how far
# ending it is in her own hands (``controllability``) and the world instant it
# lapses unless its producer raises it again (``expires_at``; None: until it
# is resolved). Her stress level is
#
#     min(1, sum of her stressors' severities) + tension
#
# (at most 1), recomputed whenever a stressor comes, goes or lapses. The
# tension is what a hard moment adds on top of what weighs on her -- a sharp
# word, a busy place (process_conversation_trigger, on_location_effects) --
# and it fades by STRESS_EXCESS_DECAY_PER_HOUR of world time; comfort, a joke,
# a calm place or anything she does ease it, never what her stressors weigh:
# a listed stressor always weighs, so the level is above 0 whenever
# stress.sources is not empty. Resolving a stressor takes its weight away at
# once. Before Task 15 each new label added +0.05 once and every tick took
# 0.005 off, so labels nothing cleared ("money worries", four "avoiding: ...")
# stayed listed while her stress read 0.00 -- on 90% of a three-day run's
# energy ticks (the Task 15 report).
#
# The producers (LifeService, and this engine's tick for her body's two) raise
# or hold a stressor while its cause holds and resolve it when the cause is
# gone: eating ends hunger, sleep ends "not enough sleep", money coming in
# ends money worries, an errand done ends "errands piling up", the end of her
# shift ends work. An upset -- a struggle flaring up, someone unwelcome
# getting in touch, compromising on a value -- is an episode instead: it
# lapses by itself (STRESSOR_KINDS' ``lapses``).

#: What a stressor weighs at the full of its cause: the stress every new
#: stressor has always added (on_stressor_added's one-time +0.05 before Task
#: 15) -- now for as long as it lasts. Every kind below but hunger weighs
#: this, times the share of its cause there is when the cause is a matter of
#: degree (hold_stressors' ``share``, on its producer's own scale: financial
#: stress over its maximum, work stress, overdue errands over the backlog's
#: cap, the guilt of what she has put off over the most she can put off). A
#: hassle alone stays under the 0.2 at which her stress starts to show
#: (get_stress_description, NEED_FLOORS["stress"], LifeService's
#: SANITY_STRESSED_LEVEL); it takes four at their fullest to reach it --
#: what a persona carries day in, day out (money a little tight, a backlog of
#: errands, things put off) weighs about 0.1 (the Task 15 report), so the
#: 0.2 marks days that are harder than that.
STRESSOR_SEVERITY = 0.05
#: Hunger's weight: the +0.03 _update_stress has always added for it.
HUNGER_STRESSOR_SEVERITY = 0.03
#: The controllability of a stressor a host names without one
#: (on_stressor_added): unknown, neither in her hands nor out of them.
STRESSOR_CONTROLLABILITY = 0.5
#: How fast the tension above what her stressors weigh fades, per world hour:
#: the 0.005 _update_stress took off her stress every tick, read per hour at
#: the scheduler's 5-minute energy tick (DEFAULT_TICK_HOURS) -- 0.06 an hour,
#: as it was at the scheduler's own cadence, and now the same at any other.
STRESS_EXCESS_DECAY_PER_HOUR = 0.005 / DEFAULT_TICK_HOURS
#: The relief any activity brings (on_activity), from the tension: the 0.005
#: it has always taken off her stress.
ACTIVITY_STRESS_RELIEF = 0.005
#: Awake longer than this, she has not had enough sleep: the 16 hours
#: _update_stress has always used (a usual waking day,
#: EnergySystem.sleep's "a normal day is ~16h awake").
SLEEP_STRESS_AFTER_HOURS_AWAKE = 16.0


@dataclass(frozen=True)
class StressorKind:
    """One kind of stressor the library raises: its words (what she is
    stressed about; a template when it names something -- ``{what}``,
    ``{name}``, ``{value}``), its severity and controllability, and whether it
    is an episode that ``lapses`` by itself (after her mood's valence
    half-life, MOOD_VALENCE_HALF_LIFE_HOURS times her mood_half_life_scale: an
    upset weighs on her about as long as her mood takes to settle half way
    back from it) or lasts until its cause is resolved."""
    words: str
    severity: float
    controllability: float
    lapses: bool = False


#: Every stressor the library raises, by kind. The words are what she is
#: stressed about as a person says it (tests/test_render_lint.py): they are
#: what ``stress.sources`` lists and a host quotes ("You're stressed about
#: money worries"). The severity is the kind's at the full of its cause (a
#: producer passes the share there is). Controllability is 1 where something
#: she can choose to do ends it -- eating, running errands, tidying, doing
#: what she has been putting off, keeping her word -- and 0 where only time,
#: pay day, the end of her shift or someone else ends it.
STRESSOR_KINDS: Dict[str, StressorKind] = {
    # Her body's (this engine's tick): hunger above SustenanceSystem's
    # HUNGRY_THRESHOLD; awake past SLEEP_STRESS_AFTER_HOURS_AWAKE.
    "hunger": StressorKind("hunger", HUNGER_STRESSOR_SEVERITY, 1.0),
    "sleep": StressorKind("not enough sleep", STRESSOR_SEVERITY, 0.0),
    # LifeService's energy tick, while the cause holds.
    "money": StressorKind("money worries", STRESSOR_SEVERITY, 0.0),
    "work": StressorKind("work", STRESSOR_SEVERITY, 0.0),
    "errands": StressorKind("errands piling up", STRESSOR_SEVERITY, 1.0),
    "home": StressorKind("the mess at home", STRESSOR_SEVERITY, 1.0),
    "hangover": StressorKind("a hangover", STRESSOR_SEVERITY, 0.0),
    "put_off": StressorKind("putting off {what}", STRESSOR_SEVERITY, 1.0),
    "obligation": StressorKind("not getting to {what}", STRESSOR_SEVERITY, 1.0),
    "sanity": StressorKind("keeping it together", STRESSOR_SEVERITY, 0.0),
    # Episodes: they lapse by themselves.
    "struggle": StressorKind("{what}", STRESSOR_SEVERITY, 0.0, lapses=True),
    # Someone she does not want to hear from (ruling T11-R1): named for them.
    "unwelcome": StressorKind(UNWELCOME_STRESSOR, STRESSOR_SEVERITY, 0.0, lapses=True),
    "torn": StressorKind("compromising on {value}", STRESSOR_SEVERITY, 0.0, lapses=True),
}

#: The kinds this engine raises and clears itself from her body state (see
#: _update_stress); never evicted by the MAX_STRESS_SOURCES cap, which would
#: only see them raised again at the next tick.
INTERNAL_STRESSOR_KINDS = frozenset({"hunger", "sleep"})
#: Their words (the sources the cap never evicts).
INTERNAL_STRESSORS = frozenset(STRESSOR_KINDS[kind].words for kind in INTERNAL_STRESSOR_KINDS)

#: A saved row from before Task 15 lists labels, not stressors
#: (``stress_sources``). Each label the library wrote becomes the stressor of
#: its kind, in its words: the labels it wrote as they were ...
LEGACY_STRESS_LABELS: Dict[str, str] = {
    "hunger": "hunger",
    "sleep_deprivation": "sleep",
    "money worries": "money",
    "work stress": "work",
    "errands piling up": "errands",
    "messy space": "home",
    "hangover": "hangover",
    "sanity": "sanity",
}
#: ... and the ones it wrote with what they named after a prefix: label
#: prefix -> (kind, the template field the rest fills). "value conflict:
#: <value> vs <activity tag>" keeps its value.
LEGACY_STRESS_PREFIXES: Tuple[Tuple[str, str, str], ...] = (
    ("struggle:", "struggle", "what"),
    ("avoiding: ", "put_off", "what"),
    ("overdue: ", "obligation", "what"),
    ("value conflict: ", "torn", "value"),
)

# Weather → mood influence (per persona, times
# PersonaParameters.weather_mood_scale: weather_sensitivity)
WEATHER_MOOD_MAP = {
    "sunny": 0.02,
    "clear_night": 0.01,
    "starry": 0.02,
    "cloudy": -0.01,
    "rainy": -0.02,
    "stormy": -0.03,
    "foggy": -0.01,
    "snowy": 0.0,
}

# Season → mood influence
SEASON_MOOD_MAP = {
    "spring": 0.01,
    "summer": 0.01,
    "autumn": 0.0,
    "winter": -0.01,
}

# Activities that recharge regulation
REGULATION_RECHARGE_ACTIVITIES = {
    "meditating": 0.05,
    "journaling": 0.03,
    "yoga": 0.04,
    "stargazing": 0.03,
    "taking a long bath": 0.04,
    "reading": 0.02,
    "listening to music": 0.02,
    "daydreaming": 0.02,
}


# ============= Conversation Triggers =============

AFFECT_CONVERSATION_TRIGGERS = {
    "encouragement":       {"mood_shift": 0.08, "stress_relief": 0.05},
    "emotional_support":   {"mood_shift": 0.10, "loneliness_relief": 0.10, "stress_relief": 0.03},
    "criticism":           {"mood_shift": -0.10, "stress_add": 0.08},
    "conflict_topic":      {"stress_add": 0.05},
    "healthy_debate":      {"mood_shift": 0.06, "stress_relief": 0.03},
    "humor":               {"mood_shift": 0.06, "stress_relief": 0.04},
    "deep_conversation":   {"loneliness_relief": 0.12, "regulation_drain": 0.02},
    "vulnerability_shared": {"mood_shift": 0.05, "loneliness_relief": 0.08},
}

class AffectSystem:
    """Tracks background emotional state across mood, stress, loneliness, regulation, and empathy."""

    # Upper bound on her stressors (and `_stress.sources`). The list is what is
    # weighing on the persona now, not an audit log.
    MAX_STRESS_SOURCES = 10

    def __init__(self, core_traits: Optional[List[str]] = None,
                 emotional_baseline: Optional[Dict[str, float]] = None,
                 params: Optional[PersonaParameters] = None):
        """``params``: her traits' engine parameters
        (:class:`~aura_life.personas.parameters.PersonaParameters`). Without
        them, ``core_traits`` is read for them
        (``PersonaParameters.from_core_traits``); with neither, every trait is
        0.5 and every number is the constant below."""
        if params is None:
            params = PersonaParameters.from_core_traits(core_traits)
        self._mood = MoodState()
        self._stress = StressState()
        # Her stressors by source, in the order they came (see "Stress"
        # above), and what they weighed together when her stress was last
        # settled -- the level above it is tension.
        self._stressors: Dict[str, Stressor] = {}
        self._stress_target = 0.0
        # How she copes (PersonaParameters rows 20-23), named in her export.
        self._coping_style = params.coping_style
        self._loneliness = LonelinessState(desired_contact_baseline=params.desired_contact)
        self._regulation = RegulationState(
            baseline=params.regulation_baseline,
            capacity=params.regulation_baseline,
        )
        self._empathy = EmpathyState(contagion_susceptibility=params.empathy)
        self._base_affect_multiplier = params.affect_reactivity
        self._affect_multiplier = self._base_affect_multiplier
        # How far one emotion moves her (times EMOTION_MOOD_GAIN): the trait's
        # own reactivity, not the hormonally modulated _affect_multiplier.
        self._mood_reactivity = params.affect_reactivity
        self._valence_half_life_hours = MOOD_VALENCE_HALF_LIFE_HOURS * params.mood_half_life_scale
        self._arousal_half_life_hours = MOOD_AROUSAL_HALF_LIFE_HOURS * params.mood_half_life_scale
        self._weather_mood_scale = params.weather_mood_scale
        # Her set-point, from her emotional baseline and her warmth; her mood
        # starts there.
        valence, arousal = self._setpoint_from_baseline(emotional_baseline or {})
        self._setpoint = (max(-1.0, min(1.0, valence + params.setpoint_valence_offset)), arousal)
        self._set_mood(*self._setpoint)
        # The label mood.since was last stamped for (see _stamp_mood_start).
        self._since_label = self._mood.current_mood
        # The day's quality (ruling T14-R1; new_day): the date of the day it
        # was drawn for (the day her last night ended, not the calendar's)
        # -- none until her first draw -- and the offset on
        # her mood's target valence it gives until the next.
        self._day_date: Optional[date] = None
        self._day_offset: float = 0.0

    # ============= Tick =============

    def tick(self, body_state: dict, social_state: dict, weather: str, season: str,
             hours: Optional[float] = None, now: Optional[datetime] = None):
        """Per-tick update of all affect modules.

        ``hours`` is the world time since the previous tick, which mood's
        half-lives and the fading of her stress's tension run on, and her
        loneliness, regulation and empathy as that many default ticks
        (``hours / DEFAULT_TICK_HOURS``, Task 34) (``None``: one energy tick,
        ``DEFAULT_TICK_HOURS``).
        ``now`` is the world instant of the tick: it stamps when a new mood
        label began (``mood.since``), is when a stressor's expiry is judged
        against (``None``: none lapses -- this engine reads no clock for it)
        and when her loneliness counts the hours since her last meaningful
        interaction from (``None``: the host's wall clock, as before).
        ``body_state`` carries ``hunger`` and ``hours_awake``, and for mood also
        ``sleep_pressure`` and ``illness`` (the worst of illness, injury and
        pain), each 0..1, and ``asleep`` (bool); a missing key reads as 0 /
        awake.
        """
        hours = DEFAULT_TICK_HOURS if hours is None else max(0.0, hours)
        self._update_mood(weather, season, body_state, hours, now)
        self._update_stress(body_state, hours, now)
        # Loneliness, regulation and empathy count default ticks (Task 34):
        # exactly 1.0 at one (x / x).
        ticks = hours / DEFAULT_TICK_HOURS
        self._update_loneliness(social_state, now, ticks)
        self._decay_regulation(ticks)
        self._decay_empathy_fatigue(ticks)

    # ============= Event Handlers =============

    def on_emotion_event(self, emotion: str, intensity: float, *, reactivity_applied: bool = False):
        """A discrete emotion moves mood part of the way toward the emotion's own
        point in the vocabulary (``EMOTION_MOOD_GAIN`` of the way per unit of
        intensity, times her reactivity). Any name counts: one the vocabulary
        does not know pulls toward neutral.

        ``reactivity_applied``: the intensity is already as she felt it -- her
        appraisal of an event (:mod:`aura_life.emotion.appraisal`, Task 14)
        scaled it by her volatility's multiplier, the same
        ``PersonaParameters.affect_reactivity`` this engine scales a pull by
        -- so her reactivity is not applied a second time."""
        emotion_lower = emotion.lower()
        # Modulate by regulation capacity
        effective = intensity * (1.0 + (1.0 - self._regulation.capacity) * 0.5)

        valence, arousal = valence_arousal(emotion_lower)
        reactivity = 1.0 if reactivity_applied else self._mood_reactivity
        self._pull_mood_toward(valence, arousal, EMOTION_MOOD_GAIN * reactivity * effective)

        if emotion_lower in HIGH_AROUSAL_EMOTIONS:
            # High arousal depletes regulation
            self.deplete_regulation(effective * 0.1, f"emotion:{emotion_lower}")

    def new_day(self, day: date, rng, sleep_quality: Optional[float] = None) -> float:
        """Draw ``day``'s quality (ruling T14-R1; the "A day's quality" block
        above): one ``rng.gauss(0, DAY_QUALITY_SD)`` -- ``rng`` is her own
        "day_quality" stream (``LifeService``) -- shifted by last night's
        ``sleep_quality`` (``None``: no night to go by, no shift) and scaled
        by her volatility's multiplier. Kept, with ``day``, as the offset on
        her mood's target valence until the next draw; returned."""
        drawn = rng.gauss(0.0, DAY_QUALITY_SD)
        slept = 0.0 if sleep_quality is None else DAY_QUALITY_PER_SLEEP_QUALITY * (
            float(sleep_quality) - SLEEP_QUALITY_BASE)
        self._day_offset = max(-1.0, min(1.0, self._mood_reactivity * (drawn + slept)))
        self._day_date = day
        return self._day_offset

    @property
    def day_quality(self) -> Tuple[Optional[date], float]:
        """``(the date of the day it was drawn for -- the day her last night
        ended --, its offset on her mood's target valence)`` -- ``(None, 0.0)``
        before her first draw."""
        return self._day_date, self._day_offset

    def on_social_interaction(self, meaningful: bool, now: Optional[datetime] = None):
        """Reduce loneliness on meaningful interaction. ``now`` is when it
        happened -- the world instant (``LifeService`` passes its world
        clock; ``None``: the host's wall clock, as before)."""
        if meaningful:
            self._loneliness.last_meaningful_interaction = now if now is not None else datetime.now()
            self._loneliness.level = max(0.0, self._loneliness.level - 0.15)
        else:
            self._loneliness.level = max(0.0, self._loneliness.level - 0.05)

    def on_user_emotion_detected(self, emotion: str, intensity: float, trust_level: float):
        """Empathy contagion from user's detected emotion."""
        contagion = intensity * self._empathy.contagion_susceptibility * trust_level
        # Low regulation = more porous boundaries
        if self._regulation.capacity < 0.4:
            contagion *= 1.5
        self._empathy.current_absorbed_emotion = emotion
        self._empathy.absorbed_intensity = min(1.0, contagion)
        # Heavy negative emotions cause empathic fatigue
        if emotion.lower() in EMPATHIC_FATIGUE_EMOTIONS and intensity > 0.5:
            self._empathy.empathic_fatigue = min(1.0, self._empathy.empathic_fatigue + contagion * 0.1)

    def on_activity(self, activity_name: str):
        """Activity-based regulation recharge and stress relief (from the
        tension, never below what her stressors weigh)."""
        recharge = REGULATION_RECHARGE_ACTIVITIES.get(activity_name, 0.0)
        if recharge > 0:
            self.recharge_regulation(recharge)
        # Any activity provides minor stress relief
        self._move_tension(-ACTIVITY_STRESS_RELIEF)

    def process_conversation_trigger(self, trigger_type: str) -> None:
        """Process a conversation trigger that affects mood/stress/loneliness.
        Stress is relieved or added as tension, on top of what her stressors
        weigh (see "Stress")."""
        effects = AFFECT_CONVERSATION_TRIGGERS.get(trigger_type)
        if not effects:
            return
        m = self._affect_multiplier
        if "mood_shift" in effects:
            self._nudge_valence(effects["mood_shift"] * m)
        if "stress_relief" in effects:
            self._move_tension(-effects["stress_relief"] * m)
        if "stress_add" in effects:
            self._move_tension(effects["stress_add"] * m)
        if "loneliness_relief" in effects:
            self._loneliness.level = max(0.0, self._loneliness.level - effects["loneliness_relief"] * m)
        if "regulation_drain" in effects:
            self.deplete_regulation(effects["regulation_drain"] * m, f"conversation:{trigger_type}")

    def on_location_effects(self, stress_delta: float, social_drain: float, is_nature: bool):
        """Apply location-based effects to mood/stress/loneliness.

        Called by LifeService each activity tick — engines never call each other directly.

        Args:
            stress_delta: Positive adds tension, negative relieves it (never
                below what her stressors weigh -- see "Stress").
            social_drain: Positive drains social battery (increases loneliness tendency).
            is_nature: True for park/beach/trail — gives a small mood boost.
        """
        m = self._affect_multiplier
        # Stress
        self._move_tension(stress_delta * m)
        # Loneliness: social_drain > 0 means busy social environment (slows loneliness growth),
        # social_drain < 0 means isolated (accelerates it slightly)
        if social_drain < 0:
            self._loneliness.level = min(1.0, self._loneliness.level + abs(social_drain) * 0.5 * m)
        else:
            self._loneliness.level = max(0.0, self._loneliness.level - social_drain * 0.3 * m)
        # Nature boost: small positive mood nudge
        if is_nature:
            self._nudge_valence(0.02 * m)

    def on_weather_nudge(self, delta: float) -> None:
        """Apply a one-time bounded weather mood nudge routed from LifeService.

        Called by LifeService on weather CHANGE (not every tick) so the push
        cannot accumulate unboundedly. delta > 0 = positive mood push,
        delta < 0 = negative.  Magnitude should be tiny (e.g. 0.03 * weight).
        Scaled by her weather sensitivity as well as her reactivity.
        """
        self._nudge_valence(delta * self._affect_multiplier * self._weather_mood_scale)

    # ============= Stressors (see "Stress" above) =============

    @property
    def stressors(self) -> List[Stressor]:
        """What weighs on her now, heaviest first (the order of
        ``stress.sources``)."""
        return list(self._stress.stressors)

    @property
    def coping_style(self) -> str:
        """How she copes with what weighs on her, by nature:
        PersonaParameters.coping_style (row 23). Not ShadowSystem's
        ``coping_style``, which is how she is coping right now under strain
        (healthily, self-soothing, destructively)."""
        return self._coping_style

    def stressor(self, kind: str, now: Optional[datetime] = None, **words: str) -> Stressor:
        """The stressor of ``kind`` (STRESSOR_KINDS) naming ``words``: its
        source is the kind's words filled in with them, its severity and
        controllability the kind's. An episode (a kind that ``lapses``)
        expires her mood's valence half-life after ``now``; with no ``now``,
        or of a kind that lasts until resolved, it has no expiry."""
        spec = STRESSOR_KINDS[kind]
        expires_at = None
        if spec.lapses and now is not None:
            expires_at = now + timedelta(hours=self._valence_half_life_hours)
        return Stressor(spec.words.format(**words), spec.severity, spec.controllability, expires_at, kind)

    def add_stressor(self, stressor: Stressor) -> None:
        """Add ``stressor``, or refresh the one listed with its source: its
        severity, controllability, expiry and kind become the new one's (a
        refresh moves an episode's expiry on). Her stress moves by the change
        in what it weighs. A severity outside (0, 1] is brought into it -- a
        stressor that weighs nothing is none, and is not added."""
        severity = min(1.0, float(stressor.severity))
        if severity <= 0.0:
            logger.debug("Stressor %r weighs nothing; not added", stressor.source)
            return
        tension = self._tension()
        self._stressors[stressor.source] = Stressor(
            stressor.source, severity, max(0.0, min(1.0, float(stressor.controllability))),
            stressor.expires_at, stressor.kind)
        self._settle_stress(tension)

    def raise_stressor(self, kind: str, now: Optional[datetime] = None, **words: str) -> Stressor:
        """Add (or refresh) the stressor of ``kind`` naming ``words``
        (:meth:`stressor`) -- what a producer calls when its cause holds, or
        an episode happens. Returns it."""
        stressor = self.stressor(kind, now, **words)
        self.add_stressor(stressor)
        return stressor

    def hold_stressors(self, kind: str, entries: Iterable[Mapping[str, str]] = (),
                       now: Optional[datetime] = None, share: float = 1.0) -> None:
        """Her stressors of ``kind`` become exactly those ``entries`` name
        (each a mapping of the kind's template fields): each new one is added,
        each she has is refreshed, and every other of that kind is resolved --
        what a producer calls on every tick with what its cause is now.
        ``share`` is how much of its cause there is, 0..1, on the producer's
        own scale (1: all of it): each weighs the kind's severity times it."""
        keep = []
        for fields in entries:
            stressor = self.stressor(kind, now, **fields)
            stressor.severity *= max(0.0, min(1.0, share))
            keep.append(stressor)
        sources = {stressor.source for stressor in keep}
        for source in [s.source for s in self._stressors.values() if s.kind == kind and s.source not in sources]:
            self._resolve(source, now)
        for stressor in keep:
            self.add_stressor(stressor)

    def hold_stressor(self, kind: str, held: bool, now: Optional[datetime] = None,
                      share: float = 1.0, **words: str) -> None:
        """:meth:`hold_stressors` for a kind she has one of at most: the one
        naming ``words`` while ``held``, none once it is not."""
        self.hold_stressors(kind, [words] if held else [], now=now, share=share)

    def on_stressor_added(self, source: str, severity: float = STRESSOR_SEVERITY,
                          controllability: float = STRESSOR_CONTROLLABILITY,
                          expires_at: Optional[datetime] = None, kind: str = ""):
        """Add a stressor a host names (an unmet need, an overdue obligation,
        a conflict): ``source`` in the words she would use, weighing
        ``severity`` (STRESSOR_SEVERITY: the +0.05 every stressor used to add
        once), until it is resolved (or ``expires_at``). Naming one she
        already has changes nothing -- the library's own producers refresh
        theirs with :meth:`add_stressor`.

        Her stressors are capped (MAX_STRESS_SOURCES), the least weighty and
        oldest going first: a host that names a new one every tick without
        resolving the old never piles up more than the cap.
        """
        if source in self._stressors:
            return
        self.add_stressor(Stressor(source, severity, controllability, expires_at, kind))

    def on_stressor_resolved(self, source: str, now: Optional[datetime] = None):
        """Its cause is gone: the stressor ``source`` leaves, and its weight
        with it, at once (the tension on top stays and fades as it would).
        ``now`` is when -- ``stress.last_relief`` (the world instant
        ``LifeService`` passes; ``None``: the host's wall clock, as before).
        Resolving one she does not have does nothing."""
        if self._resolve(source, now) and now is None:
            self._stress.last_relief = datetime.now()

    def _resolve(self, source: str, now: Optional[datetime]) -> bool:
        """Take the stressor ``source`` away, with its weight; ``now`` (when
        given) is her last relief. Whether she had it."""
        if source not in self._stressors:
            return False
        tension = self._tension()
        del self._stressors[source]
        self._settle_stress(tension)
        if now is not None:
            self._stress.last_relief = now
        return True

    def _tension(self) -> float:
        """How far her stress stands above what her stressors weighed when it
        was last settled: the tension on top of them (0 when a host set the
        level below it)."""
        return max(0.0, self._stress.level - self._stress_target)

    def _move_tension(self, delta: float) -> None:
        """Add ``delta`` to the tension on top of what her stressors weigh --
        a relief never takes it below 0, so never below them."""
        self._settle_stress(max(0.0, self._tension() + delta))

    def _settle_stress(self, tension: float) -> None:
        """Her stress from her stressors: at most MAX_STRESS_SOURCES of them
        (the least weighty, then the oldest, go first; her body's are never
        evicted), heaviest first then oldest (``stress.stressors`` and
        ``stress.sources``), and the level what they weigh together plus
        ``tension``, at most 1."""
        excess = len(self._stressors) - self.MAX_STRESS_SOURCES
        if excess > 0:
            order = {source: index for index, source in enumerate(self._stressors)}
            evictable = sorted((s for s in self._stressors.values() if s.kind not in INTERNAL_STRESSOR_KINDS),
                               key=lambda s: (s.severity, order[s.source]))
            for stressor in evictable[:excess]:
                del self._stressors[stressor.source]
        ordered = sorted(self._stressors.values(), key=lambda s: -s.severity)
        self._stress.stressors = ordered
        self._stress.sources = [s.source for s in ordered]
        self._stress_target = min(1.0, math.fsum(s.severity for s in ordered))
        self._stress.level = min(1.0, self._stress_target + max(0.0, tension))

    def _expire_stressors(self, now: datetime) -> None:
        """The stressors whose expiry ``now`` has reached lapse."""
        lapsed = [s.source for s in self._stressors.values() if s.expires_at is not None and s.expires_at <= now]
        if lapsed:
            tension = self._tension()
            for source in lapsed:
                del self._stressors[source]
            self._settle_stress(tension)

    def deplete_regulation(self, amount: float, event: str):
        """Drain regulation capacity."""
        self._regulation.capacity = max(0.0, self._regulation.capacity - amount)
        self._regulation.last_depletion_event = event

    def recharge_regulation(self, amount: float):
        """Recharge regulation capacity."""
        self._regulation.capacity = min(1.0, self._regulation.capacity + amount)

    # ============= Internal Update Logic =============

    def _update_mood(self, weather: str, season: str, body_state: dict,
                     hours: float, now: Optional[datetime]) -> None:
        """Pull mood toward the hour's target by the world hours elapsed.

        The target is her set-point, shifted by the day's quality (its valence
        only; new_day), the weather (times her weather sensitivity) and season
        she is in and pulled by her needs' shortfalls (NEED_VALENCE_PULL,
        NEED_AROUSAL_PULLS); asleep, arousal's target is ASLEEP_AROUSAL. Each
        axis closes half its gap to the target every
        MOOD_VALENCE_HALF_LIFE_HOURS / MOOD_AROUSAL_HALF_LIFE_HOURS (times her
        volatility's mood_half_life_scale), whatever the cadence of the ticks.
        """
        weather_push = WEATHER_MOOD_MAP.get(weather, 0.0) * self._weather_mood_scale
        self._mood.weather_influence = weather_push
        season_push = SEASON_MOOD_MAP.get(season, 0.0)
        self._mood.seasonal_influence = season_push

        shortfalls = self._need_shortfalls(body_state)
        setpoint_valence, setpoint_arousal = self._setpoint
        target_valence = (setpoint_valence + self._day_offset + weather_push + season_push
                          - NEED_VALENCE_PULL * sum(shortfalls.values()))
        if body_state.get("asleep"):
            target_arousal = ASLEEP_AROUSAL
        else:
            target_arousal = setpoint_arousal + sum(
                pull * shortfalls[need] for need, pull in NEED_AROUSAL_PULLS.items()
            )
        target_valence = max(-1.0, min(1.0, target_valence))
        target_arousal = max(0.0, min(1.0, target_arousal))

        keep_valence = 0.5 ** (hours / self._valence_half_life_hours)
        keep_arousal = 0.5 ** (hours / self._arousal_half_life_hours)
        self._set_mood(
            target_valence + (self._mood.valence - target_valence) * keep_valence,
            target_arousal + (self._mood.arousal - target_arousal) * keep_arousal,
        )
        self._stamp_mood_start(now)

    def _need_shortfalls(self, body_state: dict) -> Dict[str, float]:
        """Each need's shortfall, 0..1: how far past its floor (NEED_FLOORS) the
        need stands, on the room between the floor and 1."""
        levels = {
            "loneliness": self._loneliness.level,
            "stress": self._stress.level,
            "hunger": body_state.get("hunger") or 0.0,
            "sleep_pressure": body_state.get("sleep_pressure") or 0.0,
            "illness": body_state.get("illness") or 0.0,
        }
        return {
            need: max(0.0, min(1.0, (level - NEED_FLOORS[need]) / (1.0 - NEED_FLOORS[need])))
            for need, level in levels.items()
        }

    def _set_mood(self, valence: float, arousal: float) -> None:
        """Put mood at (valence, arousal), clamped to their ranges, and read the
        label and intensity off the pair."""
        self._mood.valence = max(-1.0, min(1.0, valence))
        self._mood.arousal = max(0.0, min(1.0, arousal))
        self._mood.current_mood = mood_label(self._mood.valence, self._mood.arousal)
        self._mood.intensity = mood_intensity(self._mood.valence, self._mood.arousal)

    def _pull_mood_toward(self, valence: float, arousal: float, share: float) -> None:
        """Move mood the share (0..1) of the way toward the point (valence, arousal)."""
        share = max(0.0, min(1.0, share))
        self._set_mood(
            self._mood.valence + (valence - self._mood.valence) * share,
            self._mood.arousal + (arousal - self._mood.arousal) * share,
        )

    def _nudge_valence(self, delta: float) -> None:
        """Move valence the share |delta| of the way toward the end delta points
        at (+1 or -1), so repeated nudges never carry it past that end."""
        end = 1.0 if delta > 0 else -1.0
        self._set_mood(
            self._mood.valence + (end - self._mood.valence) * min(1.0, abs(delta)),
            self._mood.arousal,
        )

    def _stamp_mood_start(self, now: Optional[datetime]) -> None:
        """Stamp ``mood.since`` with ``now`` at the first tick that sees a new
        label (a label an emotion event set in between ticks included); a
        neutral mood has no start."""
        label = self._mood.current_mood
        if label == self._since_label:
            return
        self._since_label = label
        self._mood.since = None if label == "neutral" else now

    def _update_stress(self, body_state: dict, hours: float, now: Optional[datetime]) -> None:
        """Her stress, a tick on: the stressors whose expiry ``now`` has
        reached lapse (none without ``now``); her body's two are held while
        their cause holds -- hunger above HUNGRY_THRESHOLD (eating ends it),
        awake longer than SLEEP_STRESS_AFTER_HOURS_AWAKE (sleep ends it); and
        the tension on top of what they weigh fades by
        STRESS_EXCESS_DECAY_PER_HOUR over the ``hours`` since the last tick."""
        if now is not None:
            self._expire_stressors(now)
        self.hold_stressor("hunger", (body_state.get("hunger") or 0.0) > HUNGRY_THRESHOLD, now=now)
        self.hold_stressor("sleep", (body_state.get("hours_awake") or 0.0) > SLEEP_STRESS_AFTER_HOURS_AWAKE,
                           now=now)
        self._settle_stress(max(0.0, self._tension() - STRESS_EXCESS_DECAY_PER_HOUR * hours))

    def _update_loneliness(self, social_state: dict, now: Optional[datetime] = None,
                           ticks: float = 1.0):
        """Update loneliness based on social contact gap, counted to ``now``
        (the tick's world instant; ``None``: the host's wall clock), over
        ``ticks`` default ticks ending at ``now`` (a real-valued count)."""
        desired = self._loneliness.desired_contact_baseline
        if not self._loneliness.last_meaningful_interaction:
            # No interaction yet — loneliness grows from baseline
            self._loneliness.level = min(1.0, self._loneliness.level + LONELINESS_GROWTH_PER_TICK * desired * ticks)
        else:
            current = now if now is not None else datetime.now()
            hours_since = (current - self._loneliness.last_meaningful_interaction).total_seconds() / 3600
            # The more social the persona, the faster loneliness grows; each
            # default tick's growth counts the hours since at that tick.
            past_grace = self._summed_hours_past(hours_since - LONELINESS_GRACE_HOURS, ticks)
            growth = desired * LONELINESS_GAP_GROWTH_PER_TICK * past_grace / LONELINESS_GAP_SCALE_HOURS
            self._loneliness.level = min(1.0, self._loneliness.level + growth)

        # Track lifetime peak
        if self._loneliness.level > self._loneliness.lifetime_peak:
            self._loneliness.lifetime_peak = self._loneliness.level

    @staticmethod
    def _summed_hours_past(excess: float, ticks: float) -> float:
        """The sum, over the ``ticks`` default ticks ending at a tick whose
        hours past a mark are ``excess``, of each one's hours past it
        (``max(0, excess - k * DEFAULT_TICK_HOURS)``, k = 0, 1, ...): the
        closed form ``m * (excess - DEFAULT_TICK_HOURS * (m - 1) / 2)`` of the
        arithmetic series, where ``m`` -- the ticks counted -- is ``ticks``,
        or, when the span reaches back across the mark, only the default
        ticks past it (``ceil(excess / DEFAULT_TICK_HOURS)``). At one tick
        ``m`` is 1.0 and the sum is ``excess`` exactly."""
        if excess <= 0 or ticks <= 0:
            return 0.0
        counted = min(ticks, math.ceil(excess / DEFAULT_TICK_HOURS))
        return counted * (excess - DEFAULT_TICK_HOURS * (counted - 1) / 2)

    def _decay_regulation(self, ticks: float = 1.0):
        """Regulation slowly returns to baseline: REGULATION_RETURN_PER_TICK
        of the gap a default tick, compounded over ``ticks`` of them -- the
        share ``1 - keep ** ticks`` (keep = 1 - the per-tick share), written
        as the per-tick share times the geometric series
        ``(1 - keep ** ticks) / (1 - keep)``, which is x / x = 1.0 at one
        tick, so one tick takes exactly the per-tick share."""
        diff = self._regulation.baseline - self._regulation.capacity
        keep = 1.0 - REGULATION_RETURN_PER_TICK
        series = (1.0 - keep ** ticks) / (1.0 - keep)
        self._regulation.capacity += diff * (REGULATION_RETURN_PER_TICK * series)

    def _decay_empathy_fatigue(self, ticks: float = 1.0):
        """Empathic fatigue decays over time, by its per-tick fade times
        ``ticks``; so does an absorbed emotion, let go under
        ABSORBED_EMOTION_LET_GO_BELOW (no time, no fading: nothing let go)."""
        self._empathy.empathic_fatigue = max(0.0, self._empathy.empathic_fatigue
                                             - EMPATHIC_FATIGUE_FADE_PER_TICK * ticks)
        # Absorbed emotion fades
        if self._empathy.absorbed_intensity > 0 and ticks > 0:
            self._empathy.absorbed_intensity = max(0.0, self._empathy.absorbed_intensity
                                                   - ABSORBED_EMOTION_FADE_PER_TICK * ticks)
            if self._empathy.absorbed_intensity < ABSORBED_EMOTION_LET_GO_BELOW:
                self._empathy.current_absorbed_emotion = None
                self._empathy.absorbed_intensity = 0.0

    # ============= Personality =============
    # Desired contact, regulation baseline, empathy and the affect multiplier
    # come from her traits (PersonaParameters: desired_contact,
    # regulation_baseline, empathy, affect_reactivity), no longer from
    # substring tables here.

    @staticmethod
    def _setpoint_from_baseline(emotional_baseline: Dict[str, float]) -> Tuple[float, float]:
        """Her set-point: the mean of her baseline emotions' points in the
        vocabulary, each weighted by its intensity (clamped to 0..1, so a
        non-positive one counts for nothing), together with the neutral point
        weighted SETPOINT_NEUTRAL_WEIGHT. Negative emotions count like any
        other: a sad or anxious baseline gives a set-point below zero."""
        weight = SETPOINT_NEUTRAL_WEIGHT
        valence_sum = SETPOINT_NEUTRAL_WEIGHT * NEUTRAL_POINT[0]
        arousal_sum = SETPOINT_NEUTRAL_WEIGHT * NEUTRAL_POINT[1]
        for name, intensity in emotional_baseline.items():
            try:
                w = max(0.0, min(1.0, float(intensity)))
            except (TypeError, ValueError):
                continue
            valence, arousal = valence_arousal(name)
            weight += w
            valence_sum += w * valence
            arousal_sum += w * arousal
        return (valence_sum / weight, arousal_sum / weight)

    # ============= Description Generators =============

    #: What each mood label reads as in context (neutral says nothing).
    MOOD_DESCRIPTIONS = {
        "content": "You're in a good mood, things feel good",
        "happy": "You're in a really good mood, bright and up",
        "calm": "You're calm and settled, easy in yourself",
        "restless": "You're restless, can't really settle",
        "flat": "You're feeling flat, a bit blah, nothing much stirring",
        "irritable": "You're a bit irritable, short on patience right now",
        "anxious": "You're on edge, uneasy, can't quite shake it",
        "low": "You're feeling kinda down right now",
    }

    def get_mood_description(self) -> str:
        """Narrative description of current mood for context."""
        if self._mood.current_mood == "neutral" or self._mood.intensity < 0.1:
            return ""
        base = self.MOOD_DESCRIPTIONS.get(self._mood.current_mood, f"You're feeling {self._mood.current_mood}")
        if self._mood.intensity > 0.6:
            base += " (strongly)"
        return base

    def get_stress_description(self) -> str:
        """Narrative description of stress level."""
        if self._stress.level < 0.2:
            return ""
        if self._stress.level < 0.4:
            return "A little stressed but managing"
        if self._stress.level < 0.7:
            sources_str = ", ".join(self._stress.sources[:2]) if self._stress.sources else "stuff piling up"
            return f"Stressed about {sources_str}"
        return "Really overwhelmed right now, everything's too much"

    def get_loneliness_description(self) -> str:
        """Narrative description of loneliness."""
        if self._loneliness.level < 0.2:
            return ""
        if self._loneliness.level < 0.5:
            return "Kinda wishing {subj} had someone to talk to"
        if self._loneliness.level < 0.7:
            return "Feeling pretty lonely, wants some real connection"
        return "Really lonely right now, it's getting to {obj}"

    def get_irritability_level(self) -> float:
        """Compute irritability as a function of stress, regulation, and mood.

        Returns 0.0–1.0 where:
        - 0.0–0.2: chill, patient
        - 0.2–0.5: slightly edgy, less tolerant of nonsense
        - 0.5–0.7: noticeably irritable, snappy
        - 0.7–1.0: on a hair trigger
        """
        # Base: stress × inverse regulation
        base = self._stress.level * (1.0 - self._regulation.capacity)
        # Negative mood amplifies: keyed-up or edgy moods as the retired "raw"
        # and "restless" did (0.3), a low one as "blue" did (0.15).
        if self._mood.current_mood in ("irritable", "anxious", "restless"):
            base += self._mood.intensity * 0.3
        elif self._mood.current_mood == "low":
            base += self._mood.intensity * 0.15
        # Empathic fatigue adds edge
        base += self._empathy.empathic_fatigue * 0.15
        return min(1.0, base)

    # ============= Properties =============

    @property
    def mood(self) -> MoodState:
        return self._mood

    @property
    def setpoint(self) -> Tuple[float, float]:
        """Her resting mood, (valence, arousal): where mood is pulled back to
        when nothing else is moving it (see _setpoint_from_baseline)."""
        return self._setpoint

    @property
    def stress(self) -> StressState:
        return self._stress

    @property
    def loneliness(self) -> LonelinessState:
        return self._loneliness

    @property
    def regulation(self) -> RegulationState:
        return self._regulation

    @property
    def empathy(self) -> EmpathyState:
        return self._empathy

    # ============= Export / Serialize =============

    def export_state(self) -> dict:
        """Structured export for pipeline digest."""
        return {
            "mood": {
                "current": self._mood.current_mood,
                "intensity": round(self._mood.intensity, 2),
                "valence": round(self._mood.valence, 2),
                "arousal": round(self._mood.arousal, 2),
            },
            # "level" and "sources" (her words, heaviest first) as they have
            # always been; how she copes, a word, is new (Task 15). The
            # stressors themselves are in get_status(): this export is short
            # keys with primitive values, and a host prints it into a prompt
            # (aura's inner digest quotes the whole "stress" dict).
            "stress": {
                "level": round(self._stress.level, 2),
                "sources": self._stress.sources[:3],
                "coping": self._coping_style,
            },
            "loneliness": {"level": round(self._loneliness.level, 2)},
            "regulation": {"capacity": round(self._regulation.capacity, 2)},
            "empathy": {
                "absorbed_emotion": self._empathy.current_absorbed_emotion,
                "fatigue": round(self._empathy.empathic_fatigue, 2),
            },
        }

    def get_status(self) -> dict:
        """Status for API/debugging."""
        return {
            "mood": self._mood.current_mood,
            "mood_intensity": round(self._mood.intensity, 2),
            "mood_valence": round(self._mood.valence, 2),
            "mood_arousal": round(self._mood.arousal, 2),
            "stress": round(self._stress.level, 2),
            "stress_sources": self._stress.sources,
            "stressors": [_stressor_view(s) for s in self._stress.stressors],
            "coping_style": self._coping_style,
            "loneliness": round(self._loneliness.level, 2),
            "regulation": round(self._regulation.capacity, 2),
            "empathy_absorbed": self._empathy.current_absorbed_emotion,
            "empathy_fatigue": round(self._empathy.empathic_fatigue, 2),
        }

    def to_dict(self) -> dict:
        """Serialize for DB storage."""
        return {
            "mood_current": self._mood.current_mood,
            "mood_intensity": self._mood.intensity,
            "mood_valence": self._mood.valence,
            "mood_arousal": self._mood.arousal,
            "mood_since": self._mood.since.isoformat() if self._mood.since else None,
            "stress_level": self._stress.level,
            # Her words, as every save has kept them (a library from before
            # Task 15 reads these); the stressors themselves beside them.
            "stress_sources": json.dumps(self._stress.sources),
            "stressors": json.dumps([_stressor_row(s) for s in self._stress.stressors]),
            "stress_coping_capacity": self._stress.coping_capacity,
            "stress_last_relief": self._stress.last_relief.isoformat() if self._stress.last_relief else None,
            "loneliness_level": self._loneliness.level,
            "loneliness_desired_baseline": self._loneliness.desired_contact_baseline,
            "loneliness_last_meaningful": self._loneliness.last_meaningful_interaction.isoformat() if self._loneliness.last_meaningful_interaction else None,
            "loneliness_lifetime_peak": self._loneliness.lifetime_peak,
            "regulation_capacity": self._regulation.capacity,
            "regulation_baseline": self._regulation.baseline,
            "regulation_last_event": self._regulation.last_depletion_event,
            "empathy_susceptibility": self._empathy.contagion_susceptibility,
            "empathy_absorbed_emotion": self._empathy.current_absorbed_emotion,
            "empathy_absorbed_intensity": self._empathy.absorbed_intensity,
            "empathy_fatigue": self._empathy.empathic_fatigue,
            "day_quality_offset": self._day_offset,
            "day_quality_date": self._day_date.isoformat() if self._day_date else None,
        }

    @classmethod
    def from_dict(cls, data: dict, core_traits: Optional[List[str]] = None,
                  emotional_baseline: Optional[Dict[str, float]] = None,
                  params: Optional[PersonaParameters] = None,
                  now: Optional[datetime] = None) -> "AffectSystem":
        """Deserialize from DB.

        Given ``params``, her desired contact, regulation baseline and empathy
        come from them, not from the row: they are who she is, not state, so a
        persona whose traits changed since the row was saved (or whose row was
        derived by the retired substring tables) gets the current numbers. The
        row still restores them when no ``params`` are given, as before.

        ``now`` is the world instant she loads at (``LifeService`` passes its
        world clock): a stressor whose expiry it has reached lapses, and a
        label from a row saved before Task 15 that was an episode lapses her
        mood's valence half-life after it (see :meth:`_load_stress`)."""
        system = cls(core_traits=core_traits, emotional_baseline=emotional_baseline, params=params)
        if not data:
            return system
        from_traits = params is not None
        # Mood is the (valence, arousal) pair; label and intensity are read off
        # it. A row saved before the pair existed starts at her set-point (its
        # label came from the retired one-axis model), as a new persona does.
        valence, arousal = data.get("mood_valence"), data.get("mood_arousal")
        if valence is not None and arousal is not None:
            system._set_mood(valence, arousal)
        system._since_label = system._mood.current_mood
        if data.get("mood_since") and data.get("mood_current") == system._mood.current_mood:
            system._mood.since = datetime.fromisoformat(data["mood_since"])
        system._load_stress(data, now)
        system._stress.coping_capacity = data.get("stress_coping_capacity", 0.7)
        system._stress.last_relief = datetime.fromisoformat(data["stress_last_relief"]) if data.get("stress_last_relief") else None
        system._loneliness.level = data.get("loneliness_level", 0.0)
        if not from_traits:
            system._loneliness.desired_contact_baseline = data.get("loneliness_desired_baseline", system._loneliness.desired_contact_baseline)
        system._loneliness.last_meaningful_interaction = datetime.fromisoformat(data["loneliness_last_meaningful"]) if data.get("loneliness_last_meaningful") else None
        system._loneliness.lifetime_peak = data.get("loneliness_lifetime_peak", 0.0)
        system._regulation.capacity = data.get("regulation_capacity", system._regulation.baseline)
        if not from_traits:
            system._regulation.baseline = data.get("regulation_baseline", system._regulation.baseline)
        system._regulation.last_depletion_event = data.get("regulation_last_event")
        if not from_traits:
            system._empathy.contagion_susceptibility = data.get("empathy_susceptibility", system._empathy.contagion_susceptibility)
        system._empathy.current_absorbed_emotion = data.get("empathy_absorbed_emotion")
        system._empathy.absorbed_intensity = data.get("empathy_absorbed_intensity", 0.0)
        system._empathy.empathic_fatigue = data.get("empathy_fatigue", 0.0)
        # The day's quality (ruling T14-R1): kept across a reload, so the day
        # is not drawn again; a row saved before it has none -- no offset
        # until her next draw.
        day = data.get("day_quality_date")
        if day:
            try:
                system._day_date = date.fromisoformat(str(day)[:10])
                system._day_offset = float(data.get("day_quality_offset") or 0.0)
            except (TypeError, ValueError):
                system._day_date, system._day_offset = None, 0.0
        return system

    def _load_stress(self, data: dict, now: Optional[datetime]) -> None:
        """Her stress from a saved row: the stressors themselves when the row
        has them (``stressors``); from a row saved before Task 15, each of its
        labels (``stress_sources``) as a stressor -- see
        :func:`_legacy_stressor`. The saved level above what they weigh is
        tension (below it, it is what they weigh: a listed stressor weighs).
        Then whatever ``now`` has reached the expiry of lapses."""
        saved = _json_list(data.get("stressors"))
        if saved:
            stressors = [s for s in (_stressor_from_row(row) for row in saved) if s is not None]
        else:
            stressors = [s for s in (self._legacy_stressor(label, now)
                                     for label in _json_list(data.get("stress_sources"))) if s is not None]
        for stressor in stressors:
            if stressor.source not in self._stressors and stressor.severity > 0.0:
                self._stressors[stressor.source] = stressor
        # What the stressors weigh, before the cap (a row written before the
        # cap existed can be arbitrarily long): the saved level above it is
        # tension.
        target = min(1.0, math.fsum(s.severity for s in self._stressors.values()))
        try:
            level = float(data.get("stress_level") or 0.0)
        except (TypeError, ValueError):
            level = 0.0
        self._settle_stress(max(0.0, level - target))
        if now is not None:
            self._expire_stressors(now)

    def _legacy_stressor(self, label, now: Optional[datetime]) -> Optional[Stressor]:
        """The stressor a label from before Task 15 stands for: a label the
        library wrote is the stressor of its kind, in its words
        (LEGACY_STRESS_LABELS, LEGACY_STRESS_PREFIXES) -- an episode lapsing
        her valence half-life after ``now``, as one raised now would; any other
        label (a host's, or an unwelcome person's name) keeps its words and
        weighs STRESSOR_SEVERITY -- what it added when it came -- with
        STRESSOR_CONTROLLABILITY, and lapses like an episode (its producer, if
        any, never raises it again). Without ``now`` nothing lapses."""
        if not isinstance(label, str) or not label.strip():
            return None
        if label in LEGACY_STRESS_LABELS:
            return self.stressor(LEGACY_STRESS_LABELS[label], now)
        for prefix, kind, field_name in LEGACY_STRESS_PREFIXES:
            if label.startswith(prefix) and label[len(prefix):].strip():
                named = label[len(prefix):].strip()
                if kind == "torn":
                    named = named.split(" vs ")[0].strip() or named
                return self.stressor(kind, now, **{field_name: named})
        expires_at = now + timedelta(hours=self._valence_half_life_hours) if now is not None else None
        return Stressor(label, STRESSOR_SEVERITY, STRESSOR_CONTROLLABILITY, expires_at, "")


def _json_list(raw) -> list:
    """A JSON list column as a list (a list passes through; anything else --
    NULL, malformed -- is empty)."""
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, str) or not raw:
        return []
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return loaded if isinstance(loaded, list) else []


def _stressor_row(stressor: Stressor) -> dict:
    """A stressor as its saved row stores it."""
    return {
        "source": stressor.source,
        "severity": stressor.severity,
        "controllability": stressor.controllability,
        "expires_at": stressor.expires_at.isoformat() if stressor.expires_at else None,
        "kind": stressor.kind,
    }


def _stressor_view(stressor: Stressor) -> dict:
    """A stressor as the exports show it (rounded)."""
    return dict(_stressor_row(stressor), severity=round(stressor.severity, 3),
                controllability=round(stressor.controllability, 3))


def _stressor_from_row(row) -> Optional[Stressor]:
    """A saved stressor row back as a Stressor -- ``None`` for one that cannot
    be read."""
    if not isinstance(row, dict) or not isinstance(row.get("source"), str) or not row["source"]:
        return None
    try:
        expires = row.get("expires_at")
        return Stressor(
            row["source"],
            max(0.0, min(1.0, float(row.get("severity", STRESSOR_SEVERITY)))),
            max(0.0, min(1.0, float(row.get("controllability", STRESSOR_CONTROLLABILITY)))),
            datetime.fromisoformat(expires) if expires else None,
            str(row.get("kind") or ""),
        )
    except (TypeError, ValueError):
        return None
