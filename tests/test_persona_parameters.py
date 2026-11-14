"""Persona parameters from traits (humanness program Task 8, spec section 4.3).

Measured before: free-text traits reached the simulation only through nine
separate substring keyword tables with no negation -- "insensitive" and
"unemotional" read as MORE emotional, "antisocial loner" as MORE social,
"uncaring" gave empathy 0.7, "introverted; watches before speaking" only moved
social need 0.5 -> 0.3 -- and none of the numbers fed the plan or the event
rates. ``PersonaParameters.from_definition`` now compiles a persona once: the
eight traits (explicit ``traits`` win; the rest inferred by one word-boundary,
negation-aware matcher; absent evidence 0.5) and the engine parameters derived
from them through the one table in ``aura_life.personas.parameters``.

1. The acceptance probes, and the measured bugs, on the engines themselves.
2. The matcher: word boundaries, the negation window, the prefixes.
3. Explicit traits override the text.
4. Neutral -- no traits, no trait text -- reproduces today's numbers.
5. Every wired parameter changes its engine between 0.1 and 0.9 (ruling P2:
   end-to-end activity divergence is asserted by Task 10).
6. The service builds its engines from the definition's parameters.
7. The legacy keyword tables read through the same matcher.
"""

import importlib
import pathlib
import random
from dataclasses import fields as dc_fields
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from aura_life.affect.affect_system import AffectSystem
from aura_life.body.body_system import BodySystem
from aura_life.chaos.chaos_engine import ChaosEngine
from aura_life.cognitive.cognitive_system import CognitiveSystem
from aura_life.drive.drive_system import DriveSystem
from aura_life.energy.energy_system import EnergySystem
from aura_life.identity.identity_system import IdentitySystem
from aura_life.intimacy.desire_system import DesireSystem
from aura_life.models import NPC, DailyPlan, PlannedSlot, Weather
from aura_life.money.finance_system import FinanceSystem
from aura_life.personas import PersonalityDefinition, ProfileParser, TRAIT_KEYS
from aura_life.personas.parameters import TRAIT_VOCABULARY, PersonaParameters, match_keywords
from aura_life.planner.daily_planner import DailyPlanner
from aura_life.shadow.shadow_system import ShadowSystem
from aura_life.social.social_system import SocialSystem

LOW, HIGH = 0.1, 0.9

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "profile_full_sections.txt"
DEF_FIELDS = {f.name for f in dc_fields(PersonalityDefinition)}


def _from_text(*core_traits) -> PersonaParameters:
    return PersonaParameters.from_definition(PersonalityDefinition(core_traits=list(core_traits)))


def _with(**traits) -> PersonaParameters:
    return PersonaParameters.from_definition(PersonalityDefinition(traits=dict(traits)))


# ======================================================================
# 1. The acceptance probes, and the measured bugs
# ======================================================================

def test_insensitive_reads_as_low_volatility():
    assert _from_text("insensitive").volatility < 0.5


def test_antisocial_loner_reads_as_low_sociability():
    assert _from_text("antisocial loner").sociability < 0.5


def test_uncaring_reads_as_low_warmth():
    assert _from_text("uncaring").warmth < 0.5


def test_emotionally_unstable_reads_as_high_volatility():
    assert _from_text("emotionally unstable").volatility > 0.5


def test_the_same_words_unnegated_read_the_other_way():
    assert _from_text("sensitive").volatility > 0.5
    assert _from_text("social").sociability > 0.5
    assert _from_text("caring").warmth > 0.5
    assert _from_text("emotionally stable").volatility < 0.5
    assert _from_text("unemotional").volatility < 0.5


def test_the_measured_bugs_are_gone_from_the_engines():
    """What the humanness analysis measured, read off the engines."""
    uncaring = AffectSystem(core_traits=["uncaring"])
    assert uncaring.empathy.contagion_susceptibility < 0.5          # was 0.7
    cold = AffectSystem(core_traits=["insensitive", "unemotional"])
    assert cold._base_affect_multiplier < 1.0                        # was 1.5: both read as MORE emotional
    assert cold.regulation.baseline > 0.7                            # was 0.6
    loner = AffectSystem(core_traits=["antisocial loner"])
    assert loner.loneliness.desired_contact_baseline < 0.5          # was 0.7


def test_introverted_watches_before_speaking_reaches_more_than_social_need():
    """It moved social need 0.5 -> 0.3 and nothing else."""
    params = _from_text("introverted; watches before speaking")
    assert params.sociability == pytest.approx(0.3)
    assert AffectSystem(params=params).loneliness.desired_contact_baseline == pytest.approx(0.3)
    assert SocialSystem(params=params).social_battery.capacity < SocialSystem().social_battery.capacity
    assert SocialSystem(params=params)._npc_event_chance < SocialSystem()._npc_event_chance


# ======================================================================
# 2. The matcher
# ======================================================================

@pytest.mark.parametrize("text", ["quietly brave", "quietly devoted", "socially anxious"])
def test_a_keyword_inside_a_longer_word_is_not_that_keyword(text):
    """Word boundaries: "quietly" is not "quiet", "socially" not "social"."""
    assert _from_text(text).sociability == 0.5


@pytest.mark.parametrize("text", [
    "not social", "never social", "no longer social", "not very social", "isn't social",
    "isn’t social",  # a curly apostrophe
])
def test_a_negator_up_to_two_words_before_a_trait_word_reverses_it(text):
    assert _from_text(text).sociability < 0.5


def test_a_negator_three_words_back_is_out_of_the_window():
    """The window is two tokens (the brief): "not at all social" reads as social."""
    assert _from_text("not at all social").sociability > 0.5


def test_the_negation_window_stops_at_a_clause_or_list_boundary():
    one_clause = _from_text("not shy social").sociability             # "not" reaches both words
    assert one_clause == 0.5
    assert _from_text("not shy, social").sociability > 0.5
    assert _from_text("not shy — social").sociability > 0.5     # an em dash
    assert _from_text("not shy - social").sociability > 0.5          # a spaced hyphen
    assert _from_text("not shy", "social").sociability > 0.5


@pytest.mark.parametrize("word, trait, direction", [
    ("unsociable", "sociability", -1),
    ("antisocial", "sociability", -1),
    ("anti-social", "sociability", -1),
    ("non-social", "sociability", -1),
    ("insensitive", "volatility", -1),
    ("unstable", "volatility", +1),
    ("unkind", "warmth", -1),
    ("incurious", "openness", -1),
    ("unconventional", "openness", +1),
    ("unreliable", "conscientiousness", -1),
])
def test_a_negating_prefix_on_a_trait_word_reverses_it(word, trait, direction):
    value = getattr(_from_text(word), trait)
    assert (value - 0.5) * direction > 0


def test_a_word_that_is_itself_a_keyword_is_never_read_as_prefix_plus_root():
    """ "intense" is a volatility word; read as in + "tense" it would be calm."""
    assert _from_text("tense").volatility > 0.5
    assert _from_text("intense").volatility > 0.5


def test_two_negations_cancel():
    assert _from_text("not unkind").warmth > 0.5
    assert _from_text("never insensitive").volatility > 0.5


def test_a_hedge_is_not_a_trait_word():
    """ "kind of shy" says nothing about kindness."""
    params = _from_text("kind of shy")
    assert params.warmth == 0.5
    assert params.sociability < 0.5


def test_case_and_punctuation_do_not_matter():
    assert _from_text("SHY!").sociability == _from_text("shy").sociability < 0.5


def test_text_without_trait_words_leaves_every_trait_at_neutral():
    params = _from_text("Wants the Moon, and has since she was a child", "reads a room before anyone else")
    assert params.traits() == dict.fromkeys(TRAIT_KEYS, 0.5)
    assert params == PersonaParameters()


def test_one_word_moves_a_trait_by_the_legacy_step_and_more_words_stay_inside_the_legacy_bounds():
    """One keyword: 0.5 +/- 0.2, the step of the retired
    AffectSystem._calc_social_need / _calc_empathy. Many: closer to, never
    past, their 0.1..0.9 clamp."""
    assert _from_text("shy").sociability == pytest.approx(0.3)
    assert _from_text("outgoing").sociability == pytest.approx(0.7)
    many = _from_text("shy", "quiet", "reserved", "introverted", "loner", "withdrawn").sociability
    assert 0.1 < many < 0.3


def test_the_matcher_reports_each_keyword_with_its_direction():
    assert match_keywords(["antisocial loner"]) == {"social": -1, "loner": 1}
    assert match_keywords(["not social", "social"]) == {"social": 0}


def test_the_vocabulary_covers_the_eight_traits_and_no_word_says_both_ways():
    assert set(TRAIT_VOCABULARY) == set(TRAIT_KEYS)
    for trait, (raise_words, lower_words) in TRAIT_VOCABULARY.items():
        assert not set(raise_words) & set(lower_words), trait


@pytest.mark.parametrize("trait, word, direction", [
    (trait, word, direction)
    for trait, (raise_words, lower_words) in TRAIT_VOCABULARY.items()
    for words, direction in ((raise_words, +1), (lower_words, -1))
    for word in words
])
def test_every_vocabulary_word_moves_its_trait_its_way(trait, word, direction):
    """No word is swallowed by a longer keyword or lost to normalisation."""
    assert (getattr(_from_text(word), trait) - 0.5) * direction > 0


# ======================================================================
# 3. Explicit traits override the text
# ======================================================================

def test_explicit_traits_override_the_text():
    params = PersonaParameters.from_definition(PersonalityDefinition(
        core_traits=["calm", "antisocial loner"], traits={"volatility": 0.9}))
    assert params.volatility == 0.9                 # the text says calm
    assert params.sociability < 0.5                 # not authored: still inferred
    assert params.explicit == frozenset({"volatility"})


def test_every_authored_trait_is_taken_as_written():
    authored = dict(zip(TRAIT_KEYS, (0.0, 0.15, 0.3, 0.45, 0.55, 0.7, 0.85, 1.0)))
    params = PersonaParameters.from_definition(PersonalityDefinition(
        core_traits=["shy", "volatile", "brooding", "reckless", "lazy", "curious", "cold"],
        traits=authored))
    assert params.traits() == authored
    assert params.explicit == frozenset(TRAIT_KEYS)


def test_traits_authored_in_a_profile_reach_the_parameters():
    parsed = ProfileParser.parse_file(FIXTURE).to_personality_definition()
    definition = PersonalityDefinition(**{k: v for k, v in parsed.items() if k in DEF_FIELDS})
    assert PersonaParameters.from_definition(definition).traits() == {
        "sociability": 0.35, "volatility": 0.2, "rumination": 0.5, "impulsivity": 0.3,
        "conscientiousness": 0.75, "openness": 0.6, "warmth": 0.55, "weather_sensitivity": 0.9,
    }


@pytest.mark.parametrize("bad", [1.5, -0.1, "0.3", True, None, float("nan")])
def test_an_authored_value_that_is_not_a_number_in_0_1_is_ignored(bad):
    params = PersonaParameters.from_definition(PersonalityDefinition(
        core_traits=["antisocial"], traits={"sociability": bad, "grit": 0.9}))
    assert params.sociability == pytest.approx(0.3)   # inferred instead
    assert params.explicit == frozenset()


# ======================================================================
# 4. Neutral reproduces today's numbers
# ======================================================================

def test_a_definition_without_traits_or_trait_text_is_neutral():
    for definition in (None, PersonalityDefinition()):
        params = PersonaParameters.from_definition(definition)
        assert params.traits() == dict.fromkeys(TRAIT_KEYS, 0.5)
        assert params == PersonaParameters()


def test_neutral_parameters_reproduce_todays_constants(monkeypatch):
    """Every engine number this task parameterises, at every trait 0.5, equals
    the single constant today's code had. The expected values are literals
    copied from the code before this task (the symbol is named beside each)."""
    params = PersonaParameters.from_definition(PersonalityDefinition())

    # The derived parameters themselves: identity scales, zero offsets.
    assert params.affect_reactivity == 1.0
    assert params.mood_half_life_scale == 1.0
    assert params.setpoint_valence_offset == 0.0
    assert params.npc_event_scale == 1.0
    assert params.rumination_rate == 1.0
    assert params.plan_adherence == 1.0
    assert params.plan_deviation_chance == 0.0
    assert params.chaos_event_scale == 1.0
    assert params.micro_event_scale == 1.0
    assert params.weather_mood_scale == 1.0
    for legacy in ("energy_multiplier", "cognitive_multiplier", "drive_multiplier",
                   "trust_multiplier", "desire_multiplier"):
        assert getattr(params, legacy) == 1.0

    # AffectSystem: the retired _calc_* defaults and the mood-model constants.
    affect = AffectSystem(params=params)
    assert affect.loneliness.desired_contact_baseline == 0.5      # _calc_social_need default
    assert affect.regulation.baseline == 0.7                      # _calc_regulation_baseline default
    assert affect.regulation.capacity == 0.7
    assert affect.empathy.contagion_susceptibility == 0.5         # _calc_empathy default
    assert affect._base_affect_multiplier == 1.0                  # _calc_affect_multiplier default
    assert affect._affect_multiplier == 1.0
    assert affect._mood_reactivity == 1.0                         # EMOTION_MOOD_GAIN as is (0.08)
    assert affect._valence_half_life_hours == 4.0                 # MOOD_VALENCE_HALF_LIFE_HOURS
    assert affect._arousal_half_life_hours == 2.0                 # MOOD_AROUSAL_HALF_LIFE_HOURS
    assert affect._weather_mood_scale == 1.0                      # WEATHER_MOOD_MAP as is
    assert affect.setpoint == (0.0, 0.3)                          # the vocabulary's NEUTRAL_POINT
    baseline = {"sad": 0.6, "tired": 0.4}
    assert AffectSystem(emotional_baseline=baseline, params=params).setpoint == \
        AffectSystem._setpoint_from_baseline(baseline)

    # SocialSystem: introversion 0.5 (the default LifeService never overrode)
    # and the 25% NPC roll of SocialSystem.tick.
    social = SocialSystem(params=params)
    battery = social.social_battery
    assert battery.capacity == pytest.approx(0.6)
    assert battery.charge == pytest.approx(0.6)
    assert battery.recharge_rate == pytest.approx(0.05)
    assert battery.drain_rate == pytest.approx(0.03)
    assert social._npc_event_chance == 0.25

    # CognitiveSystem._tick_ruminations: a 10% replay, 0.005 decay per tick.
    cognitive = CognitiveSystem(params=params)
    assert cognitive._rumination_replay_chance == 0.1
    assert cognitive._rumination_decay == 0.005
    assert cognitive._cognitive_multiplier == 1.0

    # ChaosEngine.PROBABILITY.
    assert ChaosEngine(params=params)._probability == 0.20

    # DailyPlanner.revise_upcoming's thresholds; no whim ever drops a slot.
    planner = DailyPlanner(params=params)
    assert planner._revise_energy_below == 0.25
    assert planner._revise_mood_intensity_above == 0.4
    assert planner._deviation_chance == 0.0

    # The text-derived multipliers, and the rest of the nine engines.
    assert EnergySystem(params=params)._energy_multiplier == 1.0
    assert IdentitySystem(params=params)._trust_multiplier == 1.0
    assert DriveSystem(params=params)._drive_multiplier == 1.0
    assert DesireSystem(params=params)._growth_multiplier == 1.0
    assert FinanceSystem(params=params).state.spending_habit == 0.5
    assert BodySystem(params=params).health.body_image == BodySystem().health.body_image
    plain = ShadowSystem()._state
    seeded = ShadowSystem(params=params)._state
    assert (seeded.rebelliousness, seeded.inhibition, seeded.attention_seeking, seeded.autonomy,
            seeded.dominance_disposition) == (plain.rebelliousness, plain.inhibition,
                                              plain.attention_seeking, plain.autonomy,
                                              plain.dominance_disposition)


class _CountingRandom(random.Random):
    def __init__(self, seed):
        super().__init__(seed)
        self.draws = 0

    def random(self):
        self.draws += 1
        return super().random()


def test_neutral_impulsivity_takes_no_draw_to_keep_a_plan():
    """A new roll would move every later draw on the planner's stream, so a
    neutral persona must not take one (neutral personas keep today's seeds)."""
    rng = _CountingRandom(1)
    planner = DailyPlanner(rng=rng, params=PersonaParameters())
    slot = PlannedSlot(hour=14, activity_name="going for a run", reason="routine")
    assert not any(planner.abandons_slot(slot) for _ in range(50))
    assert rng.draws == 0


# ======================================================================
# 5. Every wired parameter changes its engine between 0.1 and 0.9
# ======================================================================

def _quiet_tick(affect: AffectSystem, hours: float, weather: str = "") -> None:
    affect.tick(body_state={}, social_state={}, weather=weather, season="", hours=hours)


def test_volatility_sets_how_far_an_emotion_moves_mood():
    calm, volatile = AffectSystem(params=_with(volatility=LOW)), AffectSystem(params=_with(volatility=HIGH))
    for affect in (calm, volatile):
        affect._regulation.capacity = 0.7   # the same regulation: reactivity alone differs
        affect.on_emotion_event("joyful", 0.8)
    assert volatile.mood.valence > calm.mood.valence > 0.0


def test_volatility_sets_how_far_a_conversation_nudges_mood():
    calm, volatile = AffectSystem(params=_with(volatility=LOW)), AffectSystem(params=_with(volatility=HIGH))
    for affect in (calm, volatile):
        affect.process_conversation_trigger("humor")
    assert volatile.mood.valence > calm.mood.valence > 0.0


def test_volatility_sets_how_fast_mood_returns_to_its_setpoint():
    calm, volatile = AffectSystem(params=_with(volatility=LOW)), AffectSystem(params=_with(volatility=HIGH))
    assert calm._valence_half_life_hours == pytest.approx(8.0)
    assert volatile._valence_half_life_hours == pytest.approx(4.0 / 1.5)
    for affect in (calm, volatile):
        affect._set_mood(0.8, 0.8)
        _quiet_tick(affect, hours=2.0)
    assert abs(volatile.mood.valence - volatile.setpoint[0]) < abs(calm.mood.valence - calm.setpoint[0])
    assert abs(volatile.mood.arousal - volatile.setpoint[1]) < abs(calm.mood.arousal - calm.setpoint[1])


def test_volatility_sets_the_regulation_baseline():
    calm, volatile = AffectSystem(params=_with(volatility=LOW)), AffectSystem(params=_with(volatility=HIGH))
    assert calm.regulation.baseline == pytest.approx(0.9)
    assert volatile.regulation.baseline == pytest.approx(0.5)


def test_warmth_sets_where_mood_rests():
    cold, warm = AffectSystem(params=_with(warmth=LOW)), AffectSystem(params=_with(warmth=HIGH))
    assert warm.setpoint[0] == pytest.approx(0.1)
    assert cold.setpoint[0] == pytest.approx(-0.1)
    assert warm.setpoint[1] == cold.setpoint[1]          # arousal is the baseline's alone
    for affect in (cold, warm):
        _quiet_tick(affect, hours=24.0)
    assert warm.mood.valence > 0.0 > cold.mood.valence
    sad = {"sad": 0.6}
    assert AffectSystem(emotional_baseline=sad, params=_with(warmth=HIGH)).setpoint[0] > \
        AffectSystem(emotional_baseline=sad, params=_with(warmth=LOW)).setpoint[0]


def test_warmth_sets_how_much_of_the_users_emotion_she_catches():
    cold, warm = AffectSystem(params=_with(warmth=LOW)), AffectSystem(params=_with(warmth=HIGH))
    for affect in (cold, warm):
        affect.on_user_emotion_detected("sad", 0.8, trust_level=1.0)
    assert warm.empathy.absorbed_intensity > cold.empathy.absorbed_intensity > 0.0


def test_sociability_sets_how_fast_loneliness_grows():
    loner, social = AffectSystem(params=_with(sociability=LOW)), AffectSystem(params=_with(sociability=HIGH))
    for affect in (loner, social):
        for _ in range(24):
            _quiet_tick(affect, hours=5 / 60)
    assert social.loneliness.level > loner.loneliness.level > 0.0


def test_sociability_sets_the_social_battery():
    loner, social = SocialSystem(params=_with(sociability=LOW)), SocialSystem(params=_with(sociability=HIGH))
    assert loner.social_battery.capacity < social.social_battery.capacity
    assert loner.social_battery.recharge_rate > social.social_battery.recharge_rate
    for system in (loner, social):
        system.drain_social_battery()
    left = {name: s.social_battery.charge / s.social_battery.capacity
            for name, s in (("loner", loner), ("social", social))}
    assert left["loner"] < left["social"]       # a conversation costs the loner more of her battery


def test_sociability_sets_how_often_her_people_get_in_touch():
    npcs = [NPC(name="Ana", relationship="best friend", contact_frequency="daily"),
            NPC(name="Tom", relationship="coworker", contact_frequency="regular")]
    heard_from = {}
    for level in (LOW, HIGH):
        social = SocialSystem(npcs=npcs, rng=random.Random(7), params=_with(sociability=level))
        count = 0
        for _ in range(400):
            if social.tick():
                count += 1
                social._last_contact.clear()   # no cooldown: count the roll itself
        heard_from[level] = count
    assert heard_from[HIGH] > heard_from[LOW] > 0


def test_rumination_sets_how_long_a_rumination_loop_lasts():
    lasted = {}
    for level in (LOW, HIGH):
        cognitive = CognitiveSystem(rng=random.Random(3), params=_with(rumination=level))
        cognitive.on_failure("the audition")
        ticks = 0
        while cognitive.ruminations and ticks < 5000:
            cognitive._tick_ruminations()
            ticks += 1
        lasted[level] = ticks
    assert lasted[HIGH] > lasted[LOW]


def _freeze_planner_host(monkeypatch, instant: datetime) -> None:
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr(importlib.import_module("aura_life.planner.daily_planner"), "datetime", Frozen)


def _planner_with(slot_name: str, level: float, trait: str) -> DailyPlanner:
    planner = DailyPlanner(rng=random.Random(1), params=_with(**{trait: level}))
    planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=14, activity_name=slot_name, reason="routine", location="park")])
    return planner


def test_conscientiousness_sets_how_tired_she_must_be_to_drop_her_plans(monkeypatch):
    _freeze_planner_host(monkeypatch, datetime(2026, 10, 6, 8, 0))
    kept = {}
    for level in (LOW, HIGH):
        planner = _planner_with("going for a run", level, "conscientiousness")
        planner.revise_upcoming(weather=Weather.SUNNY, energy_level=0.3)
        kept[level] = planner.current_plan.slots[0].activity_name == "going for a run"
    assert kept == {LOW: False, HIGH: True}


def test_conscientiousness_sets_how_low_she_must_feel_to_drop_her_plans(monkeypatch):
    _freeze_planner_host(monkeypatch, datetime(2026, 10, 6, 8, 0))
    kept = {}
    for level in (LOW, HIGH):
        planner = _planner_with("going for a run", level, "conscientiousness")
        planner.revise_upcoming(weather=Weather.SUNNY, energy_level=0.9, mood="low", mood_intensity=0.5)
        kept[level] = planner.current_plan.slots[0].activity_name == "going for a run"
    assert kept == {LOW: False, HIGH: True}


def test_impulsivity_sets_how_often_she_drops_a_planned_slot_on_a_whim():
    slot = PlannedSlot(hour=14, activity_name="going for a run", reason="routine")
    dropped = {}
    for level in (LOW, HIGH):
        planner = DailyPlanner(rng=random.Random(11), params=_with(impulsivity=level))
        dropped[level] = sum(planner.abandons_slot(slot) for _ in range(400))
    assert dropped[LOW] == 0 < dropped[HIGH] < 400


def test_a_whim_never_drops_work_a_routine_anchor_or_a_plan_made_with_the_user():
    planner = DailyPlanner(rng=random.Random(11), params=_with(impulsivity=1.0))
    kept_slots = [PlannedSlot(hour=14, activity_name=name, reason="routine")
                  for name in ("working", "commuting", "having lunch", "waking up", "meeting up")]
    kept_slots.append(PlannedSlot(hour=14, activity_name="going for a run", reason="agreed with user"))
    for slot in kept_slots:
        assert not any(planner.abandons_slot(slot) for _ in range(200)), slot.activity_name


def test_openness_sets_how_often_chaos_strikes():
    struck = {}
    for level in (LOW, HIGH):
        chaos = ChaosEngine(rng=random.Random(5), params=_with(openness=level))
        count = 0
        for _ in range(300):
            chaos._events_today = []   # no daily cap: count the roll itself
            if chaos.roll(current_activity="reading", energy=0.8, regulation=0.7):
                count += 1
        struck[level] = count
    assert struck[HIGH] > struck[LOW] > 0


def test_weather_sensitivity_sets_how_far_the_weather_pulls_mood():
    hardy, sensitive = (AffectSystem(params=_with(weather_sensitivity=LOW)),
                        AffectSystem(params=_with(weather_sensitivity=HIGH)))
    for affect in (hardy, sensitive):
        _quiet_tick(affect, hours=6.0, weather="stormy")
    assert sensitive.mood.valence < hardy.mood.valence < 0.0


def test_weather_sensitivity_sets_how_far_a_change_of_weather_nudges_mood():
    hardy, sensitive = (AffectSystem(params=_with(weather_sensitivity=LOW)),
                        AffectSystem(params=_with(weather_sensitivity=HIGH)))
    for affect in (hardy, sensitive):
        affect.on_weather_nudge(-0.03)
    assert sensitive.mood.valence < hardy.mood.valence < 0.0


# ======================================================================
# 6. The service builds its engines from the definition's parameters
# ======================================================================

EPOCH = datetime(2026, 10, 6, 12, 0)  # a Tuesday noon


class ScriptedClock:
    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant

    def advance(self, hours: float) -> None:
        self.instant += timedelta(hours=hours)


def _service(tmp_path, name="traited", clock=None, **kwargs):
    from aura_life.life_service import LifeService
    from aura_life.world import WorldEnvironment

    clock = clock or ScriptedClock(EPOCH)
    svc = LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=name,
                      world_environment=WorldEnvironment(now=clock), **kwargs)
    return svc, clock


def _awake_activity_tick(svc):
    """One activity tick at Tuesday noon, awake, with no intimate interlude."""
    svc._desire_system.should_do_intimate_activity = lambda *a, **k: False
    svc._on_activity_tick()


ALL_HIGH_BUT_SOCIABILITY = {"sociability": LOW, "volatility": HIGH, "rumination": HIGH, "impulsivity": HIGH,
                            "conscientiousness": HIGH, "openness": HIGH, "warmth": HIGH,
                            "weather_sensitivity": HIGH}


def test_the_service_builds_its_engines_from_the_definitions_parameters(tmp_path):
    definition = PersonalityDefinition(traits=dict(ALL_HIGH_BUT_SOCIABILITY))
    svc, _ = _service(tmp_path, definition=definition)
    params = svc._params
    assert params.traits() == ALL_HIGH_BUT_SOCIABILITY

    reference = AffectSystem(params=params)
    affect = svc._affect
    assert affect.loneliness.desired_contact_baseline == reference.loneliness.desired_contact_baseline == LOW
    assert affect.regulation.baseline == reference.regulation.baseline
    assert affect.empathy.contagion_susceptibility == reference.empathy.contagion_susceptibility
    assert affect._base_affect_multiplier == reference._base_affect_multiplier > 1.0
    assert affect._valence_half_life_hours == reference._valence_half_life_hours
    assert affect._weather_mood_scale == reference._weather_mood_scale > 1.0
    assert affect.setpoint == reference.setpoint

    assert svc._social.social_battery.capacity == SocialSystem(params=params).social_battery.capacity
    assert svc._social._npc_event_chance == SocialSystem(params=params)._npc_event_chance
    assert svc._cognitive._rumination_replay_chance == CognitiveSystem(params=params)._rumination_replay_chance
    assert svc._chaos._probability == ChaosEngine(params=params)._probability > 0.20
    assert svc._daily_planner._revise_energy_below == DailyPlanner(params=params)._revise_energy_below
    assert svc._daily_planner._deviation_chance == params.plan_deviation_chance > 0.0
    assert svc._micro_event_chance == pytest.approx(0.20 * params.micro_event_scale)


def test_the_engines_keep_the_parameters_through_a_reset(tmp_path):
    svc, _ = _service(tmp_path, definition=PersonalityDefinition(traits=dict(ALL_HIGH_BUT_SOCIABILITY)))
    svc.reset_state()
    params = svc._params
    assert svc._affect.loneliness.desired_contact_baseline == LOW
    assert svc._chaos._probability == ChaosEngine(params=params)._probability
    assert svc._daily_planner._deviation_chance == params.plan_deviation_chance
    assert svc._cognitive._rumination_replay_chance == CognitiveSystem(params=params)._rumination_replay_chance


def test_a_reload_takes_the_trait_constants_from_the_traits_not_the_saved_row(tmp_path):
    """desired contact, regulation baseline, empathy and the battery's size are
    who she is, not state: a persona whose traits changed (or whose old row was
    derived by the retired substring tables) gets the new numbers on reload.
    Her mood and her battery's charge are state and come back from the row."""
    before = PersonalityDefinition(traits={"sociability": HIGH, "volatility": LOW, "warmth": HIGH})
    first, clock = _service(tmp_path, name="reborn", definition=before)
    first._load_state()
    first._affect._set_mood(0.4, 0.5)
    first._save_state()

    after = PersonalityDefinition(
        traits={"sociability": LOW, "volatility": HIGH, "warmth": LOW, "openness": HIGH, "rumination": HIGH},
        core_traits=["energetic", "curious", "sensual"])
    again, _ = _service(tmp_path, name="reborn", clock=clock, definition=after)
    constructed = {name: getattr(again, name) for name in
                   ("_affect", "_energy", "_desire_system", "_cognitive", "_drive", "_chaos")}
    again._load_state()
    for name, engine in constructed.items():
        assert getattr(again, name) is not engine, f"{name} was not rebuilt from its row"
    params = again._params
    fresh = AffectSystem(params=params)
    assert again._affect.loneliness.desired_contact_baseline == fresh.loneliness.desired_contact_baseline
    assert again._affect.regulation.baseline == fresh.regulation.baseline
    assert again._affect.empathy.contagion_susceptibility == fresh.empathy.contagion_susceptibility
    battery = again._social.social_battery
    assert battery.capacity == SocialSystem(params=params).social_battery.capacity
    assert battery.charge <= battery.capacity
    assert (again._affect.mood.valence, again._affect.mood.arousal) == pytest.approx((0.4, 0.5))
    # Every engine the load rebuilds from its row keeps her parameters.
    assert again._energy._energy_multiplier == params.energy_multiplier > 1.0
    assert again._desire_system._growth_multiplier == params.desire_multiplier > 1.0
    assert again._cognitive._rumination_replay_chance == CognitiveSystem(params=params)._rumination_replay_chance
    assert again._cognitive._cognitive_multiplier == params.cognitive_multiplier > 1.0
    assert again._drive._drive_multiplier == params.drive_multiplier > 1.0
    assert again._chaos._probability == ChaosEngine(params=params)._probability > 0.20


def test_openness_sets_how_often_a_small_moment_happens(tmp_path, monkeypatch):
    import dataclasses

    kettle = [{"text": "The kettle clicked off", "emotion": {"wistful": 0.1}, "share_worthy": False}]
    happened = {}
    for level in (LOW, HIGH):
        svc, _ = _service(tmp_path, name=f"open{level}",
                          definition=PersonalityDefinition(traits={"openness": level}))
        # The pool is her setting's (Task 9 moved MICRO_EVENTS into the
        # contemporary pack), so it is patched there.
        monkeypatch.setattr(svc, "_setting", dataclasses.replace(svc._setting, micro_events=kettle))
        svc._chaos.roll = lambda **kwargs: None
        # Every service draw lands at 0.2: under 0.20 * 1.5, over 0.20 * 0.5.
        monkeypatch.setattr(svc, "_service_rng", SimpleNamespace(
            random=lambda: 0.2, choice=lambda seq: list(seq)[0], uniform=lambda a, b: a,
            sample=lambda seq, k: list(seq)[:k]))
        _awake_activity_tick(svc)
        happened[level] = "The kettle clicked off" in svc._recent_activities[0].narrative
    assert happened == {LOW: False, HIGH: True}


def test_the_activity_tick_asks_the_planner_before_it_follows_a_planned_slot(tmp_path):
    for abandons, expected in ((False, "reading"), (True, "listening to music")):
        svc, _ = _service(tmp_path, name=f"whim{abandons}")
        svc._on_plan_tick()
        # The tick reads the slot for her local world time (Task 28: the
        # world's clock, Tuesday noon, for a persona with no timezone); plan
        # the free-time slot there.
        hour = svc._local_world_now().hour
        svc._daily_planner.set_planned_activity(hour, "reading", location="home", reason="free time",
                                                now=datetime(2026, 10, 6, hour, 0))
        asked = []

        def abandons_slot(slot, _answer=abandons):
            asked.append(slot.activity_name)
            return _answer

        svc._daily_planner.abandons_slot = abandons_slot
        ad_hoc = svc._activity_engine.get_activity("listening to music")
        svc._activity_engine.select_activity = lambda **kwargs: ad_hoc
        _awake_activity_tick(svc)
        assert asked == ["reading"]
        assert svc._recent_activities[0].activity_name == expected


# ======================================================================
# 7. The legacy keyword tables read through the same matcher
# ======================================================================

def test_the_legacy_multipliers_keep_their_weights():
    assert _from_text("curious").cognitive_multiplier == pytest.approx(1.25)   # COGNITIVE_GROWTH_TRAITS
    assert _from_text("curious").drive_multiplier == pytest.approx(1.3)        # DRIVE_GROWTH_TRAITS
    assert _from_text("energetic").energy_multiplier == pytest.approx(1.2)     # ENERGY_GROWTH_TRAITS
    assert _from_text("trusting").trust_multiplier == pytest.approx(1.25)      # IDENTITY_GROWTH_TRAITS
    assert _from_text("sensual").desire_multiplier == pytest.approx(1.3)       # DESIRE_GROWTH_TRAITS
    assert _from_text("passionate", "sensual", "romantic", "flirty", "warm").desire_multiplier == 1.5


def test_the_legacy_multipliers_read_negation_and_word_boundaries():
    assert _from_text("not curious").cognitive_multiplier == pytest.approx(0.75)
    assert _from_text("incurious").drive_multiplier == pytest.approx(0.7)
    assert _from_text("untrusting").trust_multiplier == pytest.approx(0.75)
    assert _from_text("unromantic").desire_multiplier == pytest.approx(0.8)
    assert _from_text("quietly brave").energy_multiplier == 1.0    # substring "quiet" made it 0.9


def test_the_engines_take_the_legacy_multipliers_from_the_same_matcher():
    assert CognitiveSystem(core_traits=["not curious"])._cognitive_multiplier == pytest.approx(0.75)
    assert DriveSystem(core_traits=["incurious"])._drive_multiplier == pytest.approx(0.7)
    assert EnergySystem(core_traits=["quietly brave"])._energy_multiplier == 1.0
    assert IdentitySystem(core_traits=["untrusting"])._trust_multiplier == pytest.approx(0.75)
    assert DesireSystem(core_traits=["unromantic"])._growth_multiplier == pytest.approx(0.8)


def test_shadow_seeds_read_negation():
    plain = ShadowSystem()._state.rebelliousness
    assert ShadowSystem(core_traits=["rebellious"])._state.rebelliousness > plain
    assert ShadowSystem(core_traits=["not rebellious"])._state.rebelliousness < plain
    assert ShadowSystem(core_traits=["reckless"])._state.inhibition < ShadowSystem()._state.inhibition
    assert ShadowSystem(core_traits=["never reckless"])._state.inhibition > ShadowSystem()._state.inhibition


def test_spending_habits_read_negation():
    assert FinanceSystem(core_traits=["frugal", "disciplined"]).state.spending_habit <= 0.3
    assert FinanceSystem(core_traits=["impulsive", "indulgent"]).state.spending_habit >= 0.7
    assert FinanceSystem(core_traits=["not frugal"]).state.spending_habit >= 0.7


def test_body_image_markers_read_word_boundaries_and_negation():
    plain = BodySystem().health.body_image
    assert BodySystem(struggles=["recurring body image issues"]).health.body_image < plain
    assert BodySystem(core_traits=["anxious", "insecure about her looks"]).health.body_image < plain
    assert BodySystem(struggles=["no body image issues"]).health.body_image == plain
