"""Goals, wants and activity choice from the persona (humanness program Task 10).

Measured before this task (three simulated days, ``tests/sim_helpers.py``):
activity choice read no trait, so an introvert and an extrovert diverged by
0.043-0.059 bits against a same-persona noise floor of 0.032 (the analysis'
legacy cadence; 0.10-0.16 against 0.07-0.11 at the production cadence);
goals and wants came from shared pools; the planner stored ``interests`` and
never read them; hunger was at or above 0.7 on 65-80% of ticks because no
need ever moved her to eat and her meal slots named no activity; planned
slots ran 0-3% of the time; and intimate activities pre-empted work shifts.

Section 1 pins each mechanism on its own. Section 2 is the acceptance:
three-day simulations at the production cadence (ruling T4-R3), two seeds,
several personas sharing one world.
"""

import dataclasses
import math
import random
from collections import Counter
from datetime import date, datetime, timedelta

import pytest

from aura_life import hooks
from aura_life.energy import EnergySystem
from aura_life.life_service import LifeService
from aura_life.models import Activity, ActivityCategory, DailyPlan, PlannedSlot, TimeOfDay, Weather
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.planner import daily_planner
from aura_life.planner.daily_planner import DailyPlanner
from aura_life.settings import SettingSpec, get_setting, register_setting, unregister_setting
from aura_life.sustenance import sustenance_system
from aura_life.sustenance.sustenance_system import SustenanceSystem
from aura_life.world import WorldEnvironment

from sim_helpers import PRODUCTION, SimPersona, effective_nights, in_windows, run_days

# ======================================================================
# 1. The mechanisms, one at a time
# ======================================================================


class ScriptedClock:
    """A clock that advances only when told to (see tests/test_energy_clock.py)."""

    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant

    def advance(self, minutes: float) -> None:
        self.instant += timedelta(minutes=minutes)


#: A Tuesday morning: she is up, and the night that follows is a weekday's.
TUESDAY_0900 = datetime(2026, 10, 6, 9, 0)


def _service(tmp_path, name: str, clock: ScriptedClock, seed: int = 7, **kwargs) -> LifeService:
    """A persona on ``clock``, her draws and her world's weather seeded."""
    return LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=name,
                       world_environment=WorldEnvironment(now=clock, seed=seed), rng=random.Random(seed),
                       **kwargs)


# ----------------------------------------------------------------------
# Hunger: per hour on the world clock (ruling T4-R4); a meal is its tag (T9-R8)
# ----------------------------------------------------------------------

def _hunger_after_three_hours(tmp_path, name: str, every_minutes: int) -> float:
    clock = ScriptedClock(TUESDAY_0900)
    svc = _service(tmp_path, name, clock)
    for _ in range(3 * 60 // every_minutes):
        clock.advance(every_minutes)
        svc._on_energy_tick()
    return svc._sustenance.hunger


def test_hunger_rises_per_world_hour_whatever_the_tick_cadence(tmp_path):
    """It rose a fixed step per energy tick, so a host that ticked every five
    minutes starved her three times as fast as one that ticked every fifteen."""
    every_5 = _hunger_after_three_hours(tmp_path, "five", 5)
    every_15 = _hunger_after_three_hours(tmp_path, "fifteen", 15)
    assert every_5 == pytest.approx(every_15)
    assert every_5 == pytest.approx(3 * sustenance_system.HUNGER_RISE_PER_HOUR)


def test_a_bare_tick_is_one_energy_interval_as_before():
    """A host that ticks the engine itself, with no hours, gets what one tick
    gave before: LifeScheduler's energy interval's worth."""
    sustenance = SustenanceSystem()
    sustenance.tick()
    assert sustenance.hunger == pytest.approx(0.004)
    assert sustenance.state.nutrition == pytest.approx(0.6 + (0.5 - 0.6) * 0.02)


def test_hunger_drains_her_energy_while_awake_but_never_while_she_sleeps(tmp_path):
    """The drain ran on every energy tick, asleep or not, so a hungry night
    cost more energy than sleep gave back (Task 4's production-cadence finding)."""
    clock = ScriptedClock(datetime(2026, 10, 7, 2, 0))  # Wednesday 02:00: inside her night
    svc = _service(tmp_path, "sleeper", clock)
    assert svc.is_asleep()
    svc._sustenance.state.hunger = 0.9
    before = svc.energy.level
    for _ in range(3 * 12):
        clock.advance(5)
        svc._on_energy_tick()
    assert svc.energy.level - before == pytest.approx(3 * EnergySystem.SLEEP_ENERGY_RECOVERY_PER_HOUR, abs=1e-6)

    sustenance = SustenanceSystem()
    sustenance.state.hunger = 0.9
    assert sustenance.energy_drain(hours=2.0, asleep=False) == pytest.approx(
        2 * sustenance_system.HUNGER_ENERGY_DRAIN_PER_HOUR)
    assert sustenance.energy_drain(hours=2.0, asleep=True) == 0.0
    sustenance.state.hunger = 0.5
    assert sustenance.energy_drain(hours=2.0, asleep=False) == 0.0


def test_only_an_activity_tagged_meal_feeds_her_whatever_its_name():
    """"creating a playlist" fed her because "creating" contains "eat"."""
    sustenance = SustenanceSystem()
    sustenance.state.hunger = 0.8
    for name in ("creating a playlist", "having lunch", "baking something"):
        sustenance.on_activity(name, now=TUESDAY_0900)
        assert sustenance.hunger == 0.8, name
    sustenance.on_activity("chop-shop eggs", now=TUESDAY_0900, meal=True)
    assert sustenance.hunger == pytest.approx(0.8 - sustenance_system.MEAL_HUNGER_REDUCTION)


def test_a_meal_that_spans_several_activity_ticks_is_one_meal():
    """Her meal slot governs its whole hour (three activity ticks): she eats
    one meal in it, not three."""
    sustenance = SustenanceSystem()
    sustenance.state.hunger = 0.9
    for minutes in (0, 20, 40):
        sustenance.on_activity("having lunch", now=TUESDAY_0900 + timedelta(minutes=minutes), meal=True)
    assert sustenance.hunger == pytest.approx(0.9 - sustenance_system.MEAL_HUNGER_REDUCTION)
    assert sustenance.state.meals_today == 1
    sustenance.on_activity("having dinner", now=TUESDAY_0900 + timedelta(minutes=60), meal=True)
    assert sustenance.hunger == pytest.approx(0.9 - 2 * sustenance_system.MEAL_HUNGER_REDUCTION)
    assert sustenance.state.meals_today == 2


# ----------------------------------------------------------------------
# The day's anchors are activities, and a planned slot governs its hour
# ----------------------------------------------------------------------

#: The contemporary names of the planner's anchors, and the tag of the slot each fills.
ANCHORS = {
    "waking up": "wake_up", "having breakfast": "breakfast", "having lunch": "lunch",
    "having dinner": "dinner", "getting ready for bed": "bedtime", "working": "work",
    "commuting": "commute", "attending classes": "class", "studying": "study", "meeting up": "meetup",
}


@pytest.fixture
def registered():
    """Register setting specs for one test and unregister them afterwards."""
    keys = []

    def _register(spec):
        register_setting(spec)
        keys.append(spec.key)
        return get_setting(spec.key)

    yield _register
    for key in keys:
        unregister_setting(key)


@pytest.fixture
def persona_clock():
    """Her local clock (the ``persona_now`` hook) on a scripted instant, so a
    test decides which planned hour she is in; the previous provider is put
    back afterwards."""
    saved = hooks.provider_for("persona_now")
    clock = ScriptedClock(TUESDAY_0900)
    hooks.configure(persona_now=lambda timezone=None: clock.instant)
    yield clock
    hooks.configure(persona_now=saved)


def _freeze_planner_day(monkeypatch, instant: datetime) -> None:
    """The daily planner reads its "today" from the host clock."""
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr(daily_planner, "datetime", Frozen)


def test_the_days_anchors_are_contemporary_activities_tagged_for_their_slot():
    """They were names only (``SettingSpec.name_tags``), so a planned meal,
    shift or commute named no activity and never ran as planned."""
    spec = get_setting()
    by_name = {activity.name: activity for activity in spec.activities}
    for name, tag in ANCHORS.items():
        assert name in by_name, name
        assert tag in by_name[name].tags, name
    assert not set(spec.name_tags) & set(ANCHORS)
    assert spec.names_tagged("meal") >= {"having breakfast", "having lunch", "having dinner"}


#: Monday 5 October 2026 to Sunday 11 October: every weekday and the weekend.
WEEK = [datetime(2026, 10, 5 + day, 6, 0) for day in range(7)]
EVERY_DAY = {"employed": True, "work_days": list(range(7)), "shift_start_hour": 9, "shift_end_hour": 17}


@pytest.mark.parametrize("occupation", ["", "software engineer", "nurse", "bartender", "student", "writer"])
def test_every_slot_the_planner_emits_is_an_activity_of_her_setting(monkeypatch, occupation):
    spec = get_setting()
    names = {activity.name for activity in spec.resolved_activities()}
    emitted = set()
    for instant in WEEK:
        _freeze_planner_day(monkeypatch, instant)
        for work_schedule in (None, EVERY_DAY):
            planner = DailyPlanner(occupation=occupation, rng=random.Random(instant.day), setting=spec)
            plan = planner.generate_daily_plan(goals=[], weather=Weather.SUNNY,
                                               available_activities=spec.resolved_activities(),
                                               recent_activity_names=[], work_schedule=work_schedule)
            emitted |= {slot.activity_name for slot in plan.slots}
    assert emitted <= names, sorted(emitted - names)
    assert {"waking up", "having breakfast", "having lunch", "having dinner", "getting ready for bed"} <= emitted
    if occupation:
        assert emitted & {"working", "attending classes", "studying"}, occupation


def test_a_setting_without_the_days_anchors_plans_only_its_own_activities(monkeypatch, registered):
    """Its meals are the universal meal; it has no waking, bedtime, shift or
    commute activity, so those hours are left to her choice rather than
    named for something she cannot do."""
    spec = registered(SettingSpec(
        key="test-anchorless",
        activities=[
            Activity(name="fixing the car", category=ActivityCategory.EXPLORATION, energy_cost=0.05,
                     min_energy=0.0, duration_minutes=20, preferred_times=list(TimeOfDay),
                     preferred_weather=list(Weather), suitable_locations=["home"],
                     narrative_templates=["{Subj} worked on the car"], thought_possibilities=["Good."],
                     emotion_effects={"content": 0.1}),
            Activity(name="sitting on the stairs", category=ActivityCategory.REST, energy_cost=-0.1,
                     min_energy=0.0, duration_minutes=20, preferred_times=list(TimeOfDay),
                     preferred_weather=list(Weather), suitable_locations=["home"],
                     narrative_templates=["{Subj} sat on the stairs"], thought_possibilities=["Quiet."],
                     emotion_effects={"calm": 0.1}, tags=frozenset({"fallback_rest", "restful"})),
        ],
        places={"home": "home"},
    ))
    names = {activity.name for activity in spec.resolved_activities()}
    _freeze_planner_day(monkeypatch, WEEK[1])
    plan = DailyPlanner(occupation="nurse", rng=random.Random(3), setting=spec).generate_daily_plan(
        goals=[], weather=Weather.SUNNY, available_activities=spec.resolved_activities(),
        recent_activity_names=[], work_schedule=EVERY_DAY)
    emitted = [slot.activity_name for slot in plan.slots]
    assert set(emitted) <= names, emitted
    assert emitted.count("having a meal") == 3, emitted


def test_a_planned_slot_governs_every_activity_tick_of_its_hour(tmp_path, persona_clock):
    """It governed only the first activity tick of its hour -- the tick
    marked it done and the next two chose freely -- so plan adherence and a
    whim (conscientiousness, impulsivity) had no room to act (ruling from
    Task 8)."""
    persona_clock.instant = datetime(2026, 10, 6, 14, 0)
    svc = _service(tmp_path, "planned", persona_clock)
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
    svc._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=14, activity_name="reading", reason="routine", location="home")])
    unplanned = svc._activity_engine.get_activity("relaxing")
    svc._activity_engine.select_activity = lambda **kwargs: unplanned
    done = []
    for minute in (0, 20, 40):
        persona_clock.instant = datetime(2026, 10, 6, 14, minute)
        svc._on_activity_tick()
        done.append(svc._recent_activities[0].activity_name)
    assert done == ["reading"] * 3


def test_the_days_anchors_that_need_their_slot_are_never_an_ordinary_choice():
    """Waking up, bedtime, a shift, a commute, a class, study and a meetup
    happen when the plan says; a meal may also be eaten when she is hungry."""
    from aura_life.activities import ActivityEngine

    engine = ActivityEngine(rng=random.Random(5))
    chosen = set()
    for time_of_day in TimeOfDay:
        for _ in range(60):
            activity = engine.select_activity(energy_level=0.8, time_of_day=time_of_day, weather=Weather.SUNNY,
                                              current_location="home")
            chosen.add(activity.name)
    plan_only = {name for name, tag in ANCHORS.items() if tag not in ("breakfast", "lunch", "dinner")}
    assert not chosen & plan_only, sorted(chosen & plan_only)
    assert "working" in {a.name for a in engine.get_all_activities()}


# ----------------------------------------------------------------------
# Her definition reaches the engines that read it
# ----------------------------------------------------------------------

def _defined(tmp_path, name: str, **kwargs) -> LifeService:
    definition = kwargs.pop("definition")
    return LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=name, definition=definition, **kwargs)


def test_her_occupation_comes_from_her_definition_for_both_her_career_and_her_planner(tmp_path):
    """The career read the definition's occupation and the planner only the
    constructor's, so a host that handed over a definition alone got a
    nurse whose plans never held a shift."""
    nell = _defined(tmp_path, "nell", definition=PersonalityDefinition(id="nell", occupation="nurse"))
    assert nell._career.state.occupation == "nurse"
    assert nell._daily_planner._occupation == "nurse"
    assert nell._daily_planner._occupation_type == daily_planner.OCC_SERVICE
    # A host's own occupation still wins, for both.
    wren = _defined(tmp_path, "wren", occupation="writer", definition=PersonalityDefinition(occupation="nurse"))
    assert wren._career.state.occupation == wren._daily_planner._occupation == "writer"


def test_her_interests_come_from_her_definition_when_the_host_passes_none(tmp_path):
    ivy = _defined(tmp_path, "ivy", definition=PersonalityDefinition(interests=["reading", "running"]))
    assert ivy._daily_planner._interests == ["reading", "running"]
    own = _defined(tmp_path, "own", interests=["chess"], definition=PersonalityDefinition(interests=["reading"]))
    assert own._daily_planner._interests == ["chess"]


def test_her_body_image_seed_reaches_her_body_and_survives_a_reset(tmp_path):
    """BodySystem lowers her body-image baseline when her struggles say so
    (PersonaParameters.body_image_struggle), but the service never handed
    it the definition (the ruling carried from Task 8)."""
    from aura_life.body.body_system import BODY_IMAGE_SEED_LOW

    svc = _defined(tmp_path, "bo", definition=PersonalityDefinition(struggles=["body image issues since school"]))
    assert svc._body._health.body_image == svc._body._health.body_image_baseline == BODY_IMAGE_SEED_LOW
    svc.reset_state()
    assert svc._body._health.body_image_baseline == BODY_IMAGE_SEED_LOW
    plain = _defined(tmp_path, "plain", definition=PersonalityDefinition(struggles=["a short temper"]))
    assert plain._body._health.body_image_baseline != BODY_IMAGE_SEED_LOW


# ----------------------------------------------------------------------
# What she does is what serves her best (aura_life.activities.choice)
# ----------------------------------------------------------------------

def _catalogue() -> dict:
    return {activity.name: activity for activity in get_setting().resolved_activities()}


def _chosen(engine, state=None, draws: int = 300, time_of_day=TimeOfDay.AFTERNOON, energy: float = 0.8):
    """What an engine picks over many draws, at home, in the sun."""
    from collections import Counter

    picked = Counter()
    for _ in range(draws):
        picked[engine.select_activity(energy_level=energy, time_of_day=time_of_day, weather=Weather.SUNNY,
                                      current_location="home", state=state).name] += 1
    return picked


def _share(picked, names) -> float:
    return sum(count for name, count in picked.items() if name in names) / sum(picked.values())


def test_her_traits_set_how_much_each_need_weighs():
    """PersonaParameters' table rows 15-19: sociability weighs loneliness up
    and a drained social battery down; rumination her loops; neutral is 1."""
    from aura_life.personas.parameters import PersonaParameters, trait_multiplier

    extrovert = PersonaParameters(sociability=0.9, rumination=0.2).need_weights
    introvert = PersonaParameters(sociability=0.1, rumination=0.8).need_weights
    assert extrovert["social"] == pytest.approx(1.5) and introvert["social"] == pytest.approx(0.5)
    assert extrovert["solitude"] == pytest.approx(0.5) and introvert["solitude"] == pytest.approx(1.5)
    assert introvert["reflection"] == pytest.approx(trait_multiplier(0.8))
    assert introvert["reflection"] > extrovert["reflection"]
    assert set(PersonaParameters().need_weights.values()) == {1.0}


def test_what_an_activity_meets_comes_from_its_tags_and_category_unless_it_says():
    import dataclasses

    from aura_life.activities.choice import derived_satisfaction

    by_name = _catalogue()
    assert derived_satisfaction(by_name["cooking a meal"])["hunger"] == 1.0
    texting = derived_satisfaction(by_name["texting a friend"])
    assert texting["social"] == 1.0 and texting["solitude"] == -1.0
    assert derived_satisfaction(by_name["journaling"])["reflection"] == 1.0
    assert derived_satisfaction(by_name["relaxing"])["rest"] == 1.0
    stated = derived_satisfaction(dataclasses.replace(by_name["reading"], needs={"calm": 0.3}))
    assert stated == {**derived_satisfaction(by_name["reading"]), "calm": 0.3}


@pytest.mark.parametrize("needs, why", [
    ({"boredom": 0.5}, "unknown needs"),
    ({"hunger": 2.0}, "-1..1"),
    ({"hunger": "a lot"}, "-1..1"),
])
def test_register_setting_refuses_needs_the_choice_cannot_weigh(needs, why):
    import dataclasses

    base = get_setting()
    bad = dataclasses.replace(base.activities[0], needs=needs)
    try:
        with pytest.raises(ValueError, match=why):
            register_setting(dataclasses.replace(base, key="test-bad-needs", activities=[bad]))
    finally:
        unregister_setting("test-bad-needs")


def test_hunger_draws_her_to_a_meal():
    from aura_life.activities import ActivityEngine
    from aura_life.activities.choice import ChoiceState

    meals = get_setting().names_tagged("meal")
    fed = _share(_chosen(ActivityEngine(rng=random.Random(1)), ChoiceState(needs={"hunger": 0.0})), meals)
    hungry = _share(_chosen(ActivityEngine(rng=random.Random(1)), ChoiceState(needs={"hunger": 0.9})), meals)
    assert hungry > 0.5 and hungry > 3 * fed, (hungry, fed)


def test_the_same_loneliness_draws_an_extrovert_to_company_more_than_an_introvert():
    """Equally lonely, the extrovert seeks company more; drained, the
    introvert keeps from it (solitude, the other side of sociability)."""
    from aura_life.activities import ActivityEngine
    from aura_life.activities.choice import ActivityPreferences, ChoiceState
    from aura_life.personas.parameters import PersonaParameters

    company = {name for name, a in _catalogue().items() if a.category == ActivityCategory.SOCIAL}

    def social_share(sociability: float, **needs) -> float:
        engine = ActivityEngine(rng=random.Random(2),
                                preferences=ActivityPreferences(PersonaParameters(sociability=sociability)))
        return _share(_chosen(engine, ChoiceState(needs=needs)), company)

    extrovert, introvert = social_share(0.9, social=0.6), social_share(0.1, social=0.6)
    assert extrovert - introvert > 0.25, (extrovert, introvert)
    drained = social_share(0.1, social=0.6, solitude=0.8)
    assert drained < introvert / 2, (drained, introvert)


def test_what_she_is_into_draws_her():
    from aura_life.activities import ActivityEngine
    from aura_life.activities.choice import ActivityPreferences

    def poems(preferences) -> float:
        engine = ActivityEngine(rng=random.Random(3), preferences=preferences)
        return _share(_chosen(engine, time_of_day=TimeOfDay.NIGHT), {"writing poetry"})

    assert poems(ActivityPreferences(interests=["poetry"])) > 2 * poems(ActivityPreferences())


def test_habit_goals_mood_and_effort_each_move_her_utility():
    from aura_life.activities.choice import ActivityPreferences, ChoiceState

    by_name = _catalogue()
    prefs = ActivityPreferences()
    sketching = by_name["sketching ideas"]
    base = prefs.utility(sketching, ChoiceState())
    # Her habits are not in the utility: they count once, as habit_factors around the cut.
    assert prefs.utility(sketching, ChoiceState(history=("sketching ideas",) * 10)) == base
    assert prefs.utility(sketching, ChoiceState(pulls={"sketching ideas": 1.0})) > base
    reading = by_name["reading"]  # soothing, gentle
    assert prefs.utility(reading, ChoiceState(valence=-0.8)) > prefs.utility(reading, ChoiceState(valence=0.0))
    gym = by_name["gym workout"]  # demanding
    assert prefs.utility(gym, ChoiceState(energy=0.3)) < prefs.utility(gym, ChoiceState(energy=0.9))
    assert prefs.utility(gym, ChoiceState(arousal=0.9)) > prefs.utility(gym, ChoiceState(arousal=0.1))


#: A drink (the contemporary pack has none).
PINT = Activity(
    name="having a pint", category=ActivityCategory.SOCIAL, energy_cost=0.05, min_energy=0.1,
    duration_minutes=45, preferred_times=list(TimeOfDay), preferred_weather=list(Weather),
    suitable_locations=["bar", "home"], narrative_templates=["{Subj} had a pint"],
    thought_possibilities=["Cheers."], emotion_effects={"relaxed": 0.1}, tags=frozenset({"alcohol"}),
)


def test_a_drink_draws_a_drinker_by_how_often_she_drinks_and_keeps_an_abstainer_away():
    from aura_life.activities.choice import SUBSTANCE_FREQUENCY, ActivityPreferences

    assert ActivityPreferences(substance_tendencies={"alcohol": "frequent"}).affinity(PINT) == pytest.approx(
        SUBSTANCE_FREQUENCY["frequent"])
    assert ActivityPreferences(substance_tendencies={"whiskey": "heavy"}).affinity(PINT) == pytest.approx(1.0)
    assert ActivityPreferences(substance_tendencies={"wine": "avoidant"}).affinity(PINT) == pytest.approx(-1.0)
    assert ActivityPreferences(substance_tendencies={"cigarettes": "daily"}).affinity(PINT) == 0.0
    assert ActivityPreferences(substance_tendencies={"alcohol": "frequent"}).affinity(_catalogue()["reading"]) == 0.0


def _planned(monkeypatch, params=None, interests=None, days: int = 14):
    """Every slot of two weeks of her plans, by activity."""
    from collections import Counter

    planned = Counter()
    for day in range(days):
        _freeze_planner_day(monkeypatch, datetime(2026, 10, 5, 6, 0) + timedelta(days=day))
        planner = DailyPlanner(rng=random.Random(day), params=params, interests=interests)
        plan = planner.generate_daily_plan(goals=[], weather=Weather.SUNNY,
                                           available_activities=get_setting().resolved_activities(),
                                           recent_activity_names=[])
        planned.update(slot.activity_name for slot in plan.slots)
    return planned


def test_her_plan_leans_by_her_traits_and_is_filled_from_her_interests(monkeypatch):
    """The planner read no trait, and stored her interests without reading
    them: two personas' free hours were drawn alike."""
    from aura_life.personas.parameters import PersonaParameters

    company = {name for name, a in _catalogue().items() if a.category == ActivityCategory.SOCIAL}
    extrovert = _share(_planned(monkeypatch, PersonaParameters(sociability=0.9)), company)
    introvert = _share(_planned(monkeypatch, PersonaParameters(sociability=0.1)), company)
    assert extrovert > 2 * introvert, (extrovert, introvert)

    writing = {"writing poetry", "journaling"}
    poet = _share(_planned(monkeypatch, interests=["poetry", "journaling"]), writing)
    plain = _share(_planned(monkeypatch), writing)
    assert poet > 2 * plain, (poet, plain)


def test_a_low_day_swaps_her_plan_for_the_comforts_she_likes():
    """A low mood swaps her plan's slots for gentle activities drawn by who
    she is -- her plan preference, as her free hours are filled -- so a
    bookish persona's low day is a reading day and a music lover's a music
    one, not the same uniform draw for everyone (Task 14 fix round: a day's
    quality makes low days, ruling T14-R1)."""
    from aura_life.activities.choice import ActivityPreferences

    def swaps(interests):
        preferences = ActivityPreferences(interests=interests)
        chosen = Counter()
        for seed in range(200):
            planner = DailyPlanner(rng=random.Random(seed), preferences=preferences)
            planner._current_plan = DailyPlan(date="2026-10-06", slots=[
                PlannedSlot(hour=20, activity_name="gym workout", reason="free time", location="home")])
            planner.revise_upcoming(Weather.SUNNY, energy_level=0.9, mood="low", mood_intensity=0.9,
                                    now=datetime(2026, 10, 6, 9, 0))
            chosen[planner.current_plan.slots[0].activity_name] += 1
        return chosen

    bookish, musical = swaps(["reading"]), swaps(["music"])
    assert bookish["reading"] > 2 * bookish["listening to music"]
    assert musical["listening to music"] > 2 * musical["reading"]

def test_hunger_takes_a_free_time_slot_but_never_a_commitment(tmp_path, persona_clock):
    """Hungry (HUNGRY_THRESHOLD) in an hour planned for reading, she gives
    it up and chooses by what she needs -- almost always a meal (she draws
    among her best five); in an hour planned for work, she works."""
    meals = get_setting().names_tagged("meal")
    done = []
    for seed in range(20):
        persona_clock.instant = datetime(2026, 10, 6, 15, 0)
        svc = _service(tmp_path, f"hungry{seed}", persona_clock, seed=seed)
        svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
        svc._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
            PlannedSlot(hour=15, activity_name="reading", reason="routine", location="home"),
            PlannedSlot(hour=16, activity_name="working", reason="work", location="workplace")])
        svc._sustenance.state.hunger = 0.9
        svc._on_activity_tick()
        done.append(svc._recent_activities[0].activity_name)
    assert "reading" not in done, done
    assert sum(name in meals for name in done) >= 16, done

    persona_clock.instant = datetime(2026, 10, 6, 16, 0)
    svc._sustenance.state.hunger = 0.9
    svc._on_activity_tick()
    assert svc._recent_activities[0].activity_name == "working"


# ----------------------------------------------------------------------
# Her goals are hers
# ----------------------------------------------------------------------

#: A profile with every goal source: values, a struggle, interests, a goal.
WRITER = PersonalityDefinition(
    id="writer", name="Wren", core_values=["curiosity", "creativity"], struggles=["self-doubt"],
    interests=["poetry", "reading"], personal_goal="To publish my poetry.",
)


def _goal_engine(definition=None, seed: int = 1, **kwargs):
    from aura_life.goals import GoalEngine
    from aura_life.personas.parameters import PersonaParameters

    return GoalEngine(rng=random.Random(seed), setting=get_setting(), definition=definition,
                      parameters=PersonaParameters.from_definition(definition), **kwargs)


def test_her_starting_goals_come_from_her_goal_her_interests_her_values_and_her_struggles():
    from aura_life.models import GoalTimeframe

    engine = _goal_engine(WRITER)
    engine.initialize_goals()
    goals = {goal.title: goal for goal in engine.active_goals}
    dream = [g for g in goals.values() if g.timeframe == GoalTimeframe.DREAM]
    assert [g.title for g in dream] == ["To publish my poetry."]
    long_term = [g for g in goals.values() if g.timeframe == GoalTimeframe.LONG_TERM]
    assert len(long_term) == 1 and "poetry" in long_term[0].title
    assert "writing poetry" in long_term[0].related_activities
    weekly = {g.title for g in goals.values() if g.timeframe == GoalTimeframe.WEEKLY}
    assert any("curiosity" in title for title in weekly) and any("self-doubt" in title for title in weekly)
    setting_titles = {t["title"] for pool in (get_setting().dream_goals, get_setting().long_term_goals,
                                              get_setting().personality_goals, get_setting().daily_intentions)
                      for t in pool}
    assert not set(goals) & setting_titles, sorted(set(goals) & setting_titles)


def test_her_daily_intention_comes_from_her_own_pool():
    """Every persona drew hers from one list ("Appreciate something
    beautiful" twice in the analysis' two personas)."""
    from aura_life.models import GoalTimeframe

    for seed in range(10):
        engine = _goal_engine(WRITER, seed=seed)
        daily = engine.generate_daily_goal()
        assert daily is not None and daily.timeframe == GoalTimeframe.DAILY
        assert any(word in daily.title for word in ("curiosity", "creativity", "poetry", "reading")), daily.title


def test_without_a_profile_her_goals_come_from_her_settings_pools_as_before():
    engine = _goal_engine(None)
    engine.initialize_goals()
    setting_titles = {t["title"] for pool in (get_setting().dream_goals, get_setting().long_term_goals,
                                              get_setting().personality_goals, get_setting().daily_intentions)
                      for t in pool}
    titles = {goal.title for goal in engine.active_goals}
    assert titles and titles <= setting_titles
    assert engine.generate_daily_goal() is None  # one a day: initialize_goals drew it


def test_a_goal_she_drops_is_picked_up_again_from_her_own_first():
    """After a goalless spell she reaches for something of hers before the
    setting's pools."""
    engine = _goal_engine(WRITER, seed=3)
    picked = engine._pick_up_new_goal()
    assert picked is not None
    assert any(word in picked.title for word in ("curiosity", "creativity", "poetry", "reading", "self-doubt")), (
        picked.title)


#: Values, a struggle and a goal of which only some can be pursued in the
#: contemporary pack: nothing there is about loyalty, and nothing about
#: finishing a novel.
TORN = PersonalityDefinition(
    id="torn", name="Tess", core_values=["loyalty", "curiosity"], struggles=["a short temper"],
    interests=["reading", "falconry"], personal_goal="To finish my first novel.",
)


def test_every_goal_of_her_own_is_one_she_can_pursue(tmp_path):
    """Her own goals kept their activities only when her words matched some,
    and progress only comes from a goal's activities: "Stay true to
    loyalty" had none and was abandoned around day six (fix round, finding 3).
    A goal of hers her setting offers no way to pursue is not taken up."""
    engine = _goal_engine(TORN)
    own = engine._own_dream + engine._own_long_term + engine._own_weekly + engine._own_intentions
    assert own and all(template["related_activities"] for template in own), [
        t["title"] for t in own if not t["related_activities"]]
    titles = {template["title"] for template in own}
    assert "Stay true to curiosity" in titles and "Go deeper into reading" in titles
    assert "Work on a short temper" in titles
    assert not {"Stay true to loyalty", "Go deeper into falconry", "To finish my first novel.",
                "Make room for loyalty today", "Spend some time on falconry"} & titles
    engine.initialize_goals()
    assert all(goal.related_activities for goal in engine.active_goals
               if goal.timeframe.value != "daily" or goal.title in titles), [
        (g.title, g.related_activities) for g in engine.active_goals]
    # Her dream is then her setting's best fit for her.
    dream_titles = {t["title"] for t in get_setting().dream_goals}
    assert [g.title for g in engine.active_goals if g.timeframe.value == "dream"][0] in dream_titles


# ----------------------------------------------------------------------
# Her wants are hers, and her setting's
# ----------------------------------------------------------------------

#: Every kind of want seed.
SEEDED = PersonalityDefinition(
    id="seeded", name="Sid", interests=["poetry"], comfort_zone_seeds=["journaling"],
    taste_seeds={"music": ["jazz"]}, media_preferences={"books": ["Dune"]},
    substance_tendencies={"alcohol": "frequent", "cigarettes": "avoidant"},
)


def _own_wants(definition, setting=None) -> dict:
    planner = DailyPlanner(rng=random.Random(1), setting=setting or get_setting(), definition=definition)
    return {want["title"]: want for want in planner._own_wants}


def test_her_wants_come_from_her_interests_comfort_zones_tastes_media_and_substances(registered):
    import dataclasses

    wants = _own_wants(SEEDED)
    assert "writing poetry" in wants["Make time for poetry"]["related_activities"]
    assert "journaling" in wants["Get back to journaling"]["related_activities"]
    assert "listening to music" in wants["Put on some jazz"]["related_activities"]
    assert "reading" in wants["Get back into Dune"]["related_activities"]
    # A want nothing in her setting can meet is not a want: the contemporary
    # pack has no drink; one that has gives her one. What she avoids never is.
    assert not any("drink" in title for title in wants)
    bar = registered(dataclasses.replace(get_setting(), key="test-pint",
                                         activities=list(get_setting().activities) + [PINT]))
    at_the_bar = _own_wants(SEEDED, bar)
    assert at_the_bar["Have a drink"]["related_activities"] == ["having a pint"]
    assert not any("smoke" in title.lower() for title in at_the_bar)


def test_her_wants_are_drawn_from_hers_and_her_settings(monkeypatch):
    """The planner drew every persona's wants from one list."""
    setting_titles = {want["title"] for want in get_setting().wants}
    drawn = set()
    for day in range(10):
        _freeze_planner_day(monkeypatch, datetime(2026, 10, 5, 6, 0) + timedelta(days=day))
        planner = DailyPlanner(rng=random.Random(day), definition=SEEDED)
        planner._refresh_desires([])
        drawn |= {want.title for want in planner.desires}
    own = set(_own_wants(SEEDED))
    assert drawn <= own | setting_titles
    assert drawn & own and drawn & setting_titles, sorted(drawn)


def test_two_personas_with_nothing_in_common_want_different_things(monkeypatch):
    other = PersonalityDefinition(interests=["running"], comfort_zone_seeds=["gym workout"],
                                  taste_seeds={"food": ["thai"]})
    assert not set(_own_wants(SEEDED)) & set(_own_wants(other))


# ----------------------------------------------------------------------
# Intimacy keeps to her free time (spec R6)
# ----------------------------------------------------------------------

def _eager(svc) -> None:
    """She wants it now, whenever it is allowed."""
    svc._desire_system._state.arousal = 0.95
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: True


def test_an_intimate_activity_never_takes_a_work_slot(tmp_path, persona_clock):
    """Measured before: intimate activities took 15-32% of activity ticks,
    work shifts included."""
    persona_clock.instant = datetime(2026, 10, 6, 10, 0)
    svc = _service(tmp_path, "shift", persona_clock)
    svc._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=10, activity_name="working", reason="work", location="workplace"),
        PlannedSlot(hour=11, activity_name="reading", reason="routine", location="home")])
    _eager(svc)
    svc._on_activity_tick()
    assert svc._recent_activities[0].activity_name == "working"
    persona_clock.instant = datetime(2026, 10, 6, 11, 0)
    svc._on_activity_tick()  # free time: allowed
    intimate = {a.name for a in get_setting().intimate_catalogue()}
    assert svc._recent_activities[0].activity_name in intimate


def test_an_intimate_activity_never_takes_her_sleep_window(tmp_path, persona_clock):
    """Awake inside her window (a conversation keeps her up), she does not
    start one."""
    persona_clock.instant = datetime(2026, 10, 6, 21, 0)
    svc = _service(tmp_path, "night", persona_clock)
    svc._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[])
    _eager(svc)
    persona_clock.instant = datetime(2026, 10, 6, 23, 30)  # her window is 23:00-07:00
    svc._last_user_message_at = datetime.now()  # chatting: she stays up
    svc._on_activity_tick()
    intimate = {a.name for a in get_setting().intimate_catalogue()}
    assert svc._recent_activities[0].activity_name not in intimate
    assert not svc.energy.is_asleep()
    assert svc.energy.in_sleep_window(persona_clock.instant)


class _Rolls:
    """A random source that always rolls ``value``."""

    def __init__(self, value: float):
        self.value = value

    def random(self) -> float:
        return self.value


def test_an_intimacy_rate_scales_the_chance_and_unset_keeps_todays():
    from aura_life.intimacy import DesireSystem

    def does(rate, roll) -> bool:
        desire = DesireSystem(rng=_Rolls(roll), intimacy_rate=rate)
        return desire.should_do_intimate_activity(0.8, TimeOfDay.AFTERNOON)  # today's chance: 0.1

    assert does(None, 0.09) and not does(None, 0.11)          # unset: today's 0.1
    assert does(1.0, 0.09) and not does(1.0, 0.11)            # 1.0: today's
    assert does(0.5, 0.04) and not does(0.5, 0.06)            # half of it
    assert not does(0.0, 0.0)                                 # never


def test_her_definitions_intimacy_rate_reaches_her_desire(tmp_path):
    svc = _defined(tmp_path, "rate", definition=PersonalityDefinition(intimacy_rate=0.3))
    assert svc._desire_system.intimacy_rate == 0.3
    svc.reset_state()
    assert svc._desire_system.intimacy_rate == 0.3
    assert _defined(tmp_path, "unset", definition=PersonalityDefinition())._desire_system.intimacy_rate is None


@pytest.mark.parametrize("rate", [1.5, -0.2, "often", True])
def test_an_intimacy_rate_outside_0_to_1_is_unset_not_obeyed(rate, caplog):
    """The profile parser drops such a value (Task 7); a definition built
    directly can still carry one, and it must not raise the chance past
    today's."""
    from aura_life.intimacy import DesireSystem

    desire = DesireSystem(rng=_Rolls(0.09), intimacy_rate=rate)
    assert desire.intimacy_rate is None
    assert desire.should_do_intimate_activity(0.8, TimeOfDay.AFTERNOON)  # today's 0.1
    assert not DesireSystem(rng=_Rolls(0.11), intimacy_rate=rate).should_do_intimate_activity(
        0.8, TimeOfDay.AFTERNOON)
    assert "intimacy_rate" in caplog.text


def test_her_sleep_window_is_also_the_night_her_sleep_drew():
    """A night drawn to start before her schedule's bedtime (its variance) is
    her window from its own bedtime on."""
    from aura_life.energy.energy_system import SleepNight

    energy = EnergySystem(now=lambda: datetime(2026, 10, 6, 22, 0))
    energy._night = SleepNight(date(2026, 10, 6), datetime(2026, 10, 6, 22, 10), datetime(2026, 10, 7, 6, 50))
    assert not energy.in_sleep_window(datetime(2026, 10, 6, 22, 5))
    assert energy.in_sleep_window(datetime(2026, 10, 6, 22, 30))    # the drawn night, before 23:00
    assert energy.in_sleep_window(datetime(2026, 10, 7, 6, 55))     # the schedule's, after the drawn wake
    assert not energy.in_sleep_window(datetime(2026, 10, 7, 7, 30))


# ----------------------------------------------------------------------
# The rest of the tick's wiring
# ----------------------------------------------------------------------

def test_what_she_chooses_by_reads_each_need_from_its_state(tmp_path, persona_clock):
    from aura_life.models import CuriosityQuestion, RuminationLoop

    persona_clock.instant = datetime(2026, 10, 6, 15, 0)
    svc = _service(tmp_path, "needs", persona_clock)
    svc._sustenance.state.hunger = 0.6
    svc._affect._loneliness.level = 0.4
    svc._affect._stress.level = 0.3
    battery = svc._social.social_battery
    battery.charge = battery.capacity / 4
    svc._drive._curiosities.append(CuriosityQuestion(topic="why", intensity=0.7))
    svc._cognitive._ruminations.append(RuminationLoop(topic="that", intensity=0.5))
    svc._goal_engine._active_goals.clear()
    needs = svc._choice_state().needs
    assert needs["hunger"] == pytest.approx(0.6)
    assert needs["social"] == pytest.approx(0.4)
    assert needs["calm"] == pytest.approx(0.3)
    assert needs["solitude"] == pytest.approx(0.75)
    assert needs["stimulation"] == pytest.approx(0.7)
    assert needs["reflection"] == pytest.approx(0.5)
    assert needs["rest"] == pytest.approx(1.0 - svc.energy.effective_level)
    ai = _service(tmp_path, "ai", persona_clock, definition=PersonalityDefinition(persona_type="ai"))
    assert "hunger" not in ai._choice_state().needs


def test_forced_to_rest_she_keeps_a_planned_rest_and_drops_anything_else(tmp_path, persona_clock):
    persona_clock.instant = datetime(2026, 10, 6, 12, 0)
    svc = _service(tmp_path, "tired", persona_clock)
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
    svc._energy.should_rest = lambda: True
    svc._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=12, activity_name="having lunch", reason="midday meal", location="home"),
        PlannedSlot(hour=13, activity_name="reading", reason="routine", location="home")])
    svc._on_activity_tick()
    assert svc._recent_activities[0].activity_name == "having lunch"
    persona_clock.instant = datetime(2026, 10, 6, 13, 0)
    svc._on_activity_tick()
    rested = svc._activity_engine.get_activity(svc._recent_activities[0].activity_name)
    assert rested.name != "reading" and rested.category == ActivityCategory.REST


def test_her_shift_and_her_commute_do_not_count_the_workday_twice(tmp_path, persona_clock):
    """CareerSystem.tick counts the workday; each hour of the shift itself
    reaching on_activity would add 0.05 a tick on top (her workload was
    full by noon every workday)."""
    persona_clock.instant = datetime(2026, 10, 6, 10, 0)
    svc = _defined(tmp_path, "worker", definition=PersonalityDefinition(occupation="software engineer"),
                   world_environment=WorldEnvironment(now=persona_clock, seed=7), rng=random.Random(7))
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
    svc._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=10, activity_name="working", reason="work", location="workplace"),
        PlannedSlot(hour=11, activity_name="commuting", reason="heading home", location="in transit")])
    svc._career.state.workload = 0.5
    svc._on_activity_tick()
    persona_clock.instant = datetime(2026, 10, 6, 11, 0)
    svc._on_activity_tick()
    assert [log.activity_name for log in svc._recent_activities[:2]] == ["commuting", "working"]
    assert svc._career.state.workload == 0.5
    svc._career.on_activity("working")  # the engine itself still reacts to the word
    assert svc._career.state.workload == pytest.approx(0.55)


def test_a_food_taste_is_met_by_her_meals_and_a_meetup_needs_a_meetup_activity(monkeypatch, registered):
    wants = _own_wants(PersonalityDefinition(taste_seeds={"food": ["thai"]}))
    fed_by = set(wants["Have some thai"]["related_activities"])
    assert "cooking a meal" in fed_by and fed_by <= get_setting().names_tagged("meal"), fed_by

    spec = registered(SettingSpec(key="test-no-meetup", activities=[
        Activity(name="fixing the car", category=ActivityCategory.EXPLORATION, energy_cost=0.05, min_energy=0.0,
                 duration_minutes=20, preferred_times=list(TimeOfDay), preferred_weather=list(Weather),
                 suitable_locations=["home"], narrative_templates=["{Subj} worked on the car"],
                 thought_possibilities=["Good."], emotion_effects={"content": 0.1})]))
    planner = DailyPlanner(rng=random.Random(1), setting=spec)
    planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=15, activity_name="fixing the car", reason="routine", location="home")])
    planner.schedule_rendezvous("the park", now=datetime(2026, 10, 6, 14, 0))
    slot = planner.current_plan.slots[0]
    assert (slot.activity_name, slot.location) == ("fixing the car", "the park")
    contemporary = DailyPlanner(rng=random.Random(1))
    contemporary._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=15, activity_name="reading", reason="routine", location="home")])
    contemporary.schedule_rendezvous("the park", now=datetime(2026, 10, 6, 14, 0))
    assert contemporary.current_plan.slots[0].activity_name == "meeting up"


# ----------------------------------------------------------------------
# Fix round 1: an override rewrites the hour she is in (review finding 1)
# ----------------------------------------------------------------------
# Every activity tick marks the hour's slot completed, and the slot governs
# the whole hour, so an override that skipped a completed slot left her
# doing the old plan for the rest of the hour.

def _in_an_hour_she_has_started(tmp_path, clock, name: str, slots) -> LifeService:
    """A persona whose 10:00 hour has already had its first activity tick
    (so its slot is completed), at 10:10."""
    clock.instant = datetime(2026, 10, 6, 10, 0)
    svc = _service(tmp_path, name, clock)
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
    svc._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=list(slots))
    svc._on_activity_tick()
    assert svc._daily_planner.get_planned_activity(10).completed
    clock.instant = datetime(2026, 10, 6, 10, 10)
    return svc


def _rest_of_the_hour(svc, clock) -> list:
    done = []
    for minute in (20, 40):
        clock.instant = datetime(2026, 10, 6, 10, minute)
        svc._on_activity_tick()
        done.append((svc._recent_activities[0].activity_name, svc._current_location))
    return done


def test_skipping_work_frees_the_hour_she_is_in(tmp_path, persona_clock):
    svc = _in_an_hour_she_has_started(tmp_path, persona_clock, "skip", [
        PlannedSlot(hour=10, activity_name="working", reason="work", location="workplace"),
        PlannedSlot(hour=11, activity_name="working", reason="work", location="workplace")])
    svc.apply_schedule_override("skip work")
    slot = svc._daily_planner.get_planned_activity(10)
    assert (slot.activity_name, slot.completed) == ("relaxing", False)
    assert _rest_of_the_hour(svc, persona_clock) == [("relaxing", "home")] * 2


def test_a_meetup_arrival_takes_the_hour_she_is_in(tmp_path, persona_clock):
    svc = _in_an_hour_she_has_started(tmp_path, persona_clock, "meet", [
        PlannedSlot(hour=10, activity_name="reading", reason="routine", location="home")])
    svc.schedule_meeting_arrival("the park")
    assert _rest_of_the_hour(svc, persona_clock) == [("meeting up", "the park")] * 2


def test_going_somewhere_or_staying_put_holds_for_the_hour_she_is_in(tmp_path, persona_clock):
    svc = _in_an_hour_she_has_started(tmp_path, persona_clock, "go", [
        PlannedSlot(hour=10, activity_name="reading", reason="routine", location="home")])
    svc.apply_schedule_override("go to cafe")
    assert _rest_of_the_hour(svc, persona_clock) == [("reading", "cafe")] * 2

    stay = _in_an_hour_she_has_started(tmp_path, persona_clock, "stay", [
        PlannedSlot(hour=10, activity_name="reading", reason="routine", location="library")])
    assert stay._current_location == "library"
    # Where she stays is her current slot's place, read at her local world
    # time since Task 28 -- the world's 10:10, whatever the host's clock says.
    stay._daily_planner.current_plan.slots[0].location = "library"
    stay.apply_schedule_override("stay here")
    slot = stay._daily_planner.get_planned_activity(10)
    assert (slot.location, slot.completed) == ("library", False)


def test_following_her_plan_she_stays_where_it_puts_her_for_the_whole_hour(tmp_path, persona_clock):
    """A slot the plan put outdoors (the outing guarantee) at a place the
    activity does not usually happen: she used to be moved away on the
    slot's second tick and back on its third."""
    svc = _in_an_hour_she_has_started(tmp_path, persona_clock, "outing", [
        PlannedSlot(hour=10, activity_name="journaling", reason="routine", location="cafe")])
    assert "cafe" not in svc._activity_engine.get_activity("journaling").suitable_locations
    assert svc._current_location == "cafe"
    assert _rest_of_the_hour(svc, persona_clock) == [("journaling", "cafe")] * 2


def test_in_transit_she_does_not_run_the_hours_plan(tmp_path, persona_clock):
    """While a transit is under way (getting ready, or on the way) the
    hour's slot does not run on every tick: she is going somewhere."""
    persona_clock.instant = datetime(2026, 10, 6, 15, 0)
    svc = _service(tmp_path, "transit", persona_clock)
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
    svc._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=15, activity_name="working", reason="work", location="home")])
    svc.begin_transit("cafe")
    assert svc.transit is not None
    done = []
    for minute in (0, 20, 40):
        persona_clock.instant = datetime(2026, 10, 6, 15, minute)
        svc._on_activity_tick()
        done.append(svc._recent_activities[0].activity_name)
    assert "working" not in done, done


# ----------------------------------------------------------------------
# Fix round 1: the minor findings (7-10) and rulings T10-R2, T10-R3
# ----------------------------------------------------------------------

def test_a_reloaded_body_keeps_her_definitions_seeds(tmp_path):
    """Reloaded, BodySystem was rebuilt from its saved row alone: a body saved
    before her body-image seed was wired kept the default baseline, and her
    substance tendencies -- never saved -- were forgotten (finding 7; the
    reload rule of Task 8: engines rebuilt on reload take her parameters)."""
    from aura_life.body.body_system import BODY_IMAGE_SEED_LOW

    definition = PersonalityDefinition(id="bo", struggles=["body image issues"],
                                       substance_tendencies={"alcohol": "avoidant"})
    first = LifeService(db_path=str(tmp_path / "bo.db"), persona_id="bo", definition=definition)
    first._body._health.body_image_baseline = 0.6  # as saved before the seed reached the body
    first._save_body()
    again = LifeService(db_path=str(tmp_path / "bo.db"), persona_id="bo", definition=definition)
    again._load_state()
    assert again._body._health.body_image_baseline == BODY_IMAGE_SEED_LOW
    assert again._body._substance_tendencies == {"alcohol": "avoidant"}


def test_a_meetup_is_not_a_busy_work_hour(tmp_path, persona_clock):
    """"meeting up" contains CareerSystem's "meeting": each rendezvous tick
    added 0.05 to her workload (finding 8)."""
    persona_clock.instant = datetime(2026, 10, 6, 12, 0)
    svc = _service(tmp_path, "meetup", persona_clock, definition=PersonalityDefinition(occupation="accountant"))
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
    svc._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=12, activity_name="meeting up", reason="planned meetup", location="cafe")])
    svc._career.state.workload = 0.5
    for minute in (0, 20, 40):
        persona_clock.instant = datetime(2026, 10, 6, 12, minute)
        svc._on_activity_tick()
        assert svc._recent_activities[0].activity_name == "meeting up"
    assert svc._career.state.workload == 0.5


def test_an_ai_persona_never_chooses_something_that_needs_a_body(tmp_path, persona_clock):
    """Her plan leaves physical activities out, but a free choice -- rest
    forced on her, say -- could still land on a meal or a shower (finding 9)."""
    body = get_setting().names_tagged("physical") | get_setting().names_tagged("meal")
    chosen = set()
    for seed in range(12):
        persona_clock.instant = datetime(2026, 10, 6, 13, 0)
        svc = _service(tmp_path, f"ai{seed}", persona_clock, seed=seed,
                       definition=PersonalityDefinition(persona_type="ai"))
        svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
        svc._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[])
        for forced in (True, False):
            svc._energy.should_rest = lambda forced=forced: forced
            for minute in (0, 20, 40):
                persona_clock.instant = datetime(2026, 10, 6, 13 + forced, minute)
                svc._on_activity_tick()
                chosen.add(svc._recent_activities[0].activity_name)
    assert not chosen & body, sorted(chosen & body)


def test_stated_needs_add_to_what_its_tags_say(registered):
    """Stated needs replaced the derived ones wholesale, so a meal that
    stated any lost its pull on her hunger while its tag still fed her
    (finding 10): a stated need wins for its own key only."""
    import dataclasses

    from aura_life.activities.choice import derived_satisfaction

    by_name = _catalogue()
    cooking = dataclasses.replace(by_name["cooking a meal"], needs={"calm": 0.3, "stimulation": 0.0})
    meets = derived_satisfaction(cooking)
    assert meets["hunger"] == 1.0 and meets["calm"] == 0.3 and meets["stimulation"] == 0.0
    assert derived_satisfaction(dataclasses.replace(by_name["texting a friend"], needs={"social": 0.4})) == {
        **derived_satisfaction(by_name["texting a friend"]), "social": 0.4}


DRINK_PATHS = ("her own pick", "a plan slot", "a housemate's joint activity", "the catch-up")


def _drink_by(svc: LifeService, path: str) -> None:
    """She has a pint, at 20:00, by ``path``: her own free choice (the
    selection hands it to her), her plan's slot for the hour, a housemate's
    activity she joins, or a downtime catch-up's activity."""
    pint = svc._activity_engine.get_activity("having a pint")
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
    slots = [PlannedSlot(hour=20, activity_name="having a pint", reason="routine", location="home")]
    svc._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=slots if path == "a plan slot" else [])
    if path == "her own pick":
        svc._activity_engine.select_activity = lambda **kwargs: pint
        svc._on_activity_tick()
    elif path == "a plan slot":
        svc._on_activity_tick()
    elif path == "a housemate's joint activity":
        from aura_life.social.household import JointSide

        svc._join_housemate(pint, None, JointSide(with_name="Lina", npc_names=(), line="{name} joined {obj}",
                                                  place="home", started_at=datetime(2026, 10, 6, 20, 0)))
    else:
        svc._tick_engines_for_catchup("having a pint", datetime(2026, 10, 6, 20, 0), "clear", "autumn")
    if path != "the catch-up":
        assert svc._recent_activities[0].activity_name == "having a pint"


@pytest.mark.parametrize("path", DRINK_PATHS)
@pytest.mark.parametrize("persona_type", ["ai", "human"])
def test_an_ai_persona_s_body_is_never_given_a_drink(tmp_path, persona_clock, registered, path, persona_type):
    """An AI persona has no body: a drink reaches it by no path -- whatever its
    tags say (the pack's pint is tagged "alcohol" only, not "physical", so the
    tag-based exclusions let it through) -- while a human who drinks still
    gets tipsy by each (humanness Task 19, ruling T19-R6: the gate is where
    the body is told). Before, the AI's body was inebriated by every path."""
    base = get_setting()
    registered(dataclasses.replace(base, key="test-pub", activities=list(base.activities) + [PINT]))
    persona_clock.instant = datetime(2026, 10, 6, 20, 0)
    svc = _service(tmp_path, f"{persona_type}-pub", persona_clock, definition=PersonalityDefinition(
        persona_type=persona_type, setting="test-pub", substance_tendencies={"alcohol": "frequent"}))
    _drink_by(svc, path)
    effects = svc._body.get_inebriation_effects()
    if persona_type == "ai":
        assert (effects["level"], effects["substance"], effects["is_inebriated"]) == (0.0, "", False)
    else:
        assert effects["is_inebriated"] and effects["substance"] == "alcohol"


def test_a_drink_her_setting_tags_makes_a_drinker_tipsy(tmp_path, persona_clock, registered):
    """Inebriation keyed on BodySystem's own drink names, so a pack's drink
    ("having a pint") drew a drinker to it but never made her tipsy (ruling
    T10-R2): the substance tags do it now, her tendency still applied."""
    from aura_life.body.body_system import SUBSTANCE_TAG_EFFECTS, BodySystem

    drinker = BodySystem(substance_tendencies={"alcohol": "frequent"})
    drinker.on_substance_activity("having a pint", tags=frozenset({"alcohol"}))
    assert drinker.get_inebriation_effects()["level"] == pytest.approx(SUBSTANCE_TAG_EFFECTS["alcohol"][1])
    assert drinker.get_inebriation_effects()["is_inebriated"]
    heavy = BodySystem(substance_tendencies={"whiskey": "heavy"})
    heavy.on_substance_activity("having a pint", tags=frozenset({"alcohol"}))
    assert heavy.get_inebriation_effects()["level"] == pytest.approx(SUBSTANCE_TAG_EFFECTS["alcohol"][1] * 1.3)
    abstainer = BodySystem(substance_tendencies={"wine": "avoidant"})
    abstainer.on_substance_activity("having a pint", tags=frozenset({"alcohol"}))
    assert abstainer.get_inebriation_effects()["level"] == 0.0
    smoker = BodySystem(substance_tendencies={"cigarettes": "daily"})
    smoker.on_substance_activity("smoking on the roof", tags=frozenset({"smoking"}))
    effects = smoker.get_inebriation_effects()
    assert effects["substance"] == "tobacco" and 0 < effects["level"] and not effects["is_inebriated"]
    plain = BodySystem()
    plain.on_substance_activity("reading", tags=frozenset({"quiet"}))
    assert plain.get_inebriation_effects()["level"] == 0.0

    import dataclasses

    base = get_setting()
    registered(dataclasses.replace(base, key="test-pub", activities=list(base.activities) + [PINT]))
    persona_clock.instant = datetime(2026, 10, 6, 20, 0)
    svc = _service(tmp_path, "pub", persona_clock, definition=PersonalityDefinition(
        setting="test-pub", substance_tendencies={"alcohol": "frequent"}))
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
    svc._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=20, activity_name="having a pint", reason="routine", location="home")])
    svc._on_activity_tick()
    assert svc._recent_activities[0].activity_name == "having a pint"
    assert svc._body.get_inebriation_effects()["is_inebriated"]


def test_an_ai_persona_keeps_her_nights_intimate_life(tmp_path, persona_clock):
    """The sleep-window exclusion is for a persona who sleeps (ruling
    T10-R3): an AI rests through her window awake, as she always did."""
    persona_clock.instant = datetime(2026, 10, 6, 23, 30)
    svc = _service(tmp_path, "ai-night", persona_clock, definition=PersonalityDefinition(persona_type="ai"))
    assert svc.energy.in_sleep_window(persona_clock.instant)
    svc._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[])
    _eager(svc)
    svc._on_activity_tick()
    intimate = {a.name for a in get_setting().intimate_catalogue()}
    assert svc._recent_activities[0].activity_name in intimate


# ----------------------------------------------------------------------
# Fix round 1: a whim has the whole hour to act in (tests-can-fail finding)
# ----------------------------------------------------------------------

def _follows_on_later_ticks(tmp_path, clock, name: str, impulsivity: float, slots, seeds=range(10)):
    """(ticks at :20 and :40 on which she did her plan's activity, all such
    ticks) over hours 14-21 of a day planned as ``slots``, for each seed --
    rested, fed, awake and alone, so a whim is the only reason to deviate."""
    followed = total = 0
    first_ticks_followed = first_ticks = 0
    for seed in seeds:
        clock.instant = datetime(2026, 10, 6, 14, 0)
        svc = _service(tmp_path, f"{name}{seed}", clock, seed=seed,
                       definition=PersonalityDefinition(traits={"impulsivity": impulsivity}))
        svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
        svc._energy.should_rest = lambda: False
        svc._energy.update_sleep = lambda *args, **kwargs: None
        svc._energy.is_asleep = lambda *args, **kwargs: False
        svc._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=list(slots))
        for hour in range(14, 22):
            for minute in (0, 20, 40):
                clock.instant = datetime(2026, 10, 6, hour, minute)
                svc._energy._state.level = 0.9
                svc._sustenance.state.hunger = 0.0
                svc._on_activity_tick()
                did = svc._recent_activities[0].activity_name == svc._daily_planner.get_planned_activity(hour).activity_name
                if minute:
                    followed, total = followed + did, total + 1
                else:
                    first_ticks_followed, first_ticks = first_ticks_followed + did, first_ticks + 1
    return followed, total, first_ticks_followed, first_ticks


def test_an_impulsive_persona_drops_a_free_hour_on_a_whim_on_any_of_its_ticks(tmp_path, persona_clock):
    """At impulsivity 0.9 (plan_deviation_chance 0.15) she mostly keeps a
    free-time slot on its second and third ticks too -- the slot governs the
    hour -- and now and then drops it on a whim there; at neutral impulsivity
    she never does."""
    reading = [PlannedSlot(hour=h, activity_name="reading", reason="routine", location="home") for h in range(14, 22)]
    followed, total, _, _ = _follows_on_later_ticks(tmp_path, persona_clock, "whim", 0.9, reading, range(6))
    print(f"impulsivity 0.9: kept a free slot on {followed}/{total} of its later ticks")
    assert 0.70 <= followed / total <= 0.97, (followed, total)
    steady, steady_total, first, first_total = _follows_on_later_ticks(tmp_path, persona_clock, "steady", 0.5,
                                                                       reading, range(3))
    assert (steady, first) == (steady_total, first_total)


def test_an_impulsive_persona_never_drops_an_anchor_or_a_commitment(tmp_path, persona_clock):
    kept = ([PlannedSlot(hour=h, activity_name="working", reason="work", location="home") for h in range(14, 18)]
            + [PlannedSlot(hour=18, activity_name="having dinner", reason="evening meal", location="home"),
               PlannedSlot(hour=19, activity_name="attending classes", reason="class", location="home"),
               PlannedSlot(hour=20, activity_name="commuting", reason="heading home", location="in transit"),
               PlannedSlot(hour=21, activity_name="getting ready for bed", reason="winding down", location="home")])
    followed, total, first, first_total = _follows_on_later_ticks(tmp_path, persona_clock, "kept", 0.9, kept, range(4))
    assert (followed, first) == (total, first_total)


# ----------------------------------------------------------------------
# Fix round 1: hunger across downtime and a paused host (finding 4)
# ----------------------------------------------------------------------

def _catch_up(tmp_path, monkeypatch, name: str, hunger: float, gap_hours: float, plan_slots) -> float:
    """Her hunger after a catch-up of ``gap_hours`` ending Tuesday 20:00
    (host clock), backfilled from a day planned as ``plan_slots``."""
    from aura_life import life_service

    end = datetime(2026, 10, 6, 20, 0)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return end

    monkeypatch.setattr(life_service, "datetime", Frozen)
    svc = LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=name, rng=random.Random(3),
                      world_environment=WorldEnvironment(now=lambda: end, seed=3))
    svc._daily_planner.generate_daily_plan = lambda *args, **kwargs: DailyPlan(
        date=end.strftime("%Y-%m-%d"),
        slots=[PlannedSlot(hour=hour, activity_name=activity, location="home") for hour, activity in plan_slots])
    svc._sustenance.state.hunger = hunger
    svc.catch_up_from_downtime(gap_hours)
    return svc._sustenance.hunger


def test_a_catch_up_charges_the_hunger_of_the_whole_gap(tmp_path, monkeypatch):
    """It charged one five-minute tick per backfilled hour (+0.004) while each
    backfilled meal still relieved 0.4: after a day away she came back less
    hungry than she left."""
    rate = sustenance_system.HUNGER_RISE_PER_HOUR
    fasting = _catch_up(tmp_path, monkeypatch, "fast", 0.3, 24, [(h, "reading") for h in range(24)])
    assert fasting == pytest.approx(1.0)  # 0.3 + 24 h of hunger, clamped

    # Six hours, three backfilled slots (14:00, 15:00 lunch, 16:00): the
    # hour before lunch, lunch, the hour after, then the four to 20:00.
    fed = _catch_up(tmp_path, monkeypatch, "fed", 0.5, 6,
                    [(14, "reading"), (15, "having lunch"), (16, "reading"), (17, "reading")])
    assert fed == pytest.approx(0.5 + rate - sustenance_system.MEAL_HUNGER_REDUCTION + rate + 4 * rate)


def _paused(tmp_path, name: str, hunger: float, start: datetime, hours: float):
    """A persona ticked once after the host was paused for ``hours``, her
    energy system itself stubbed out so only hunger moves her energy."""
    clock = ScriptedClock(start)
    svc = _service(tmp_path, name, clock)
    svc._energy.tick = lambda *args, **kwargs: None
    svc._energy._state.level = 1.0
    svc._sustenance.state.hunger = hunger
    clock.advance(hours * 60)
    svc._on_energy_tick()
    return svc


def test_a_paused_host_charges_the_gap_but_drains_her_only_for_its_waking_hours(tmp_path):
    """One tick charged a whole pause and sampled whether she was asleep only
    at its end: eight hours over her night at hunger 0.8 floored her energy."""
    drain = sustenance_system.HUNGER_ENERGY_DRAIN_PER_HOUR
    # Tuesday 22:00 to Wednesday 06:00: her window is 23:00-07:00, one waking hour.
    night = _paused(tmp_path, "night", 0.8, datetime(2026, 10, 6, 22, 0), 8)
    assert night.energy.level == pytest.approx(1.0 - 1 * drain)
    assert night._sustenance.hunger == pytest.approx(1.0)
    # Wholly inside her window: no drain at all.
    asleep = _paused(tmp_path, "asleep", 0.8, datetime(2026, 10, 7, 23, 30), 6)
    assert asleep.energy.level == pytest.approx(1.0)
    # Awake all through: hungry for all of it.
    day = _paused(tmp_path, "day", 0.8, datetime(2026, 10, 6, 10, 0), 3)
    assert day.energy.level == pytest.approx(1.0 - 3 * drain)
    # From 0.65 her hunger crosses 0.7 after 0.05 / 0.048 h: drained from then on.
    rising = _paused(tmp_path, "rising", 0.65, datetime(2026, 10, 6, 10, 0), 3)
    below = 0.05 / sustenance_system.HUNGER_RISE_PER_HOUR
    assert rising.energy.level == pytest.approx(1.0 - (3 - below) * drain, abs=drain / 12)


# ----------------------------------------------------------------------
# Fix round 1: a meal slot is a meal slot, whatever fills it (finding 2)
# ----------------------------------------------------------------------

#: A pack with no meal of its own: the universal "having a meal" fills its
#: meal slots. A park, so the outing guarantee has somewhere to send her.
MEAL_LESS = SettingSpec(
    key="test-meal-less",
    activities=[
        Activity(name="fixing the car", category=ActivityCategory.EXPLORATION, energy_cost=0.05, min_energy=0.0,
                 duration_minutes=20, preferred_times=list(TimeOfDay), preferred_weather=list(Weather),
                 suitable_locations=["home"], narrative_templates=["{Subj} worked on the car"],
                 thought_possibilities=["Good."], emotion_effects={"content": 0.1}),
        Activity(name="sitting on the stairs", category=ActivityCategory.REST, energy_cost=-0.1, min_energy=0.0,
                 duration_minutes=20, preferred_times=list(TimeOfDay), preferred_weather=list(Weather),
                 suitable_locations=["home"], narrative_templates=["{Subj} sat on the stairs"],
                 thought_possibilities=["Quiet."], emotion_effects={"calm": 0.1},
                 tags=frozenset({"fallback_rest", "restful"})),
    ],
    places={"home": "home", "park": "park"},
)


def test_a_slot_the_universal_meal_fills_is_never_dropped_swapped_or_moved(monkeypatch, registered):
    """Only tag-anchored activities were protected, so a pack relying on the
    universal meal had its meals dropped on a whim (140 in 1000 slots at
    impulsivity 0.9), swapped away when she was tired or low, and moved
    outdoors by the outing guarantee."""
    from aura_life.personas.parameters import PersonaParameters

    spec = registered(MEAL_LESS)
    impulsive = DailyPlanner(rng=random.Random(1), setting=spec, params=PersonaParameters(impulsivity=0.9))
    meal = PlannedSlot(hour=12, activity_name="having a meal", reason="midday meal", location="home")
    assert not impulsive.is_free_time(meal)
    assert not any(impulsive.abandons_slot(meal) for _ in range(1000))

    _freeze_planner_day(monkeypatch, datetime(2026, 10, 6, 6, 0))
    tired = DailyPlanner(rng=random.Random(2), setting=spec)
    tired._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=12, activity_name="having a meal", reason="midday meal", location="home")])
    tired.revise_upcoming(Weather.SUNNY, energy_level=0.01)
    tired.revise_upcoming(Weather.SUNNY, energy_level=0.9, mood="low", mood_intensity=0.9)
    assert tired.current_plan.slots[0].activity_name == "having a meal"

    for day in range(10):
        _freeze_planner_day(monkeypatch, datetime(2026, 10, 5, 6, 0) + timedelta(days=day))
        plan = DailyPlanner(rng=random.Random(day), setting=spec).generate_daily_plan(
            goals=[], weather=Weather.SUNNY, available_activities=spec.resolved_activities(),
            recent_activity_names=[])
        meals = [slot for slot in plan.slots if slot.activity_name == "having a meal"]
        assert len(meals) == 3 and {slot.location for slot in meals} == {"home"}, (day, meals)

    # A food taste is still met there: by her one meal.
    stew = _own_wants(PersonalityDefinition(taste_seeds={"food": ["stew"]}), spec)
    assert stew["Have some stew"]["related_activities"] == ["having a meal"]


# ======================================================================
# 2. Acceptance: three simulated days, two seeds
# ======================================================================

DAYS = 3
SEEDS = (1, 2)

#: Every trait but the two named is neutral (0.5).
INTROVERT = dict(traits={"sociability": 0.1, "rumination": 0.8})
EXTROVERT = dict(traits={"sociability": 0.9, "rumination": 0.2})
#: Two personas whose interests share no word.
BOOKISH = dict(interests=["reading", "poetry", "music", "journaling"])
SPORTY = dict(interests=["running", "gym", "cooking", "walking"])
#: A persona with work shifts: the slots no intimate activity may take.
NURSE = dict(occupation="nurse")

PERSONAS = {
    "ivy": INTROVERT,
    "eve": EXTROVERT,
    "bea": BOOKISH,
    "sam": SPORTY,
    "nell": NURSE,
}


def _sim_persona(pid: str, **fields) -> SimPersona:
    definition = PersonalityDefinition(id=pid, name=pid.title(), appearance_details={"gender": "female"},
                                       **fields)
    return SimPersona(pid, service_kwargs=dict(definition=definition))


@pytest.fixture(scope="module")
def traces(tmp_path_factory):
    """One run per seed: every persona above, three days from a Monday 15:00."""
    return {
        seed: run_days([_sim_persona(pid, **fields) for pid, fields in PERSONAS.items()],
                       days=DAYS, seed=seed, cadence=PRODUCTION,
                       data_dir=tmp_path_factory.mktemp(f"choice_{seed}"))
        for seed in SEEDS
    }


def _waking_ticks(records):
    """The steps whose activity tick ran while she was awake."""
    return [r for r in records if "activity" in r.ticks and not r.asleep]


def _activity_mix(records) -> Counter:
    """What she did on her waking activity ticks, by activity name."""
    return Counter(r.activity for r in _waking_ticks(records) if r.activity)


def jsd(a: Counter, b: Counter) -> float:
    """Jensen-Shannon divergence of two activity mixes, in bits."""
    total_a, total_b = sum(a.values()), sum(b.values())
    divergence = 0.0
    for name in set(a) | set(b):
        p, q = a[name] / total_a, b[name] / total_b
        m = (p + q) / 2
        if p:
            divergence += 0.5 * p * math.log2(p / m)
        if q:
            divergence += 0.5 * q * math.log2(q / m)
    return divergence


def cosine(a: Counter, b: Counter) -> float:
    dot = sum(a[name] * b[name] for name in set(a) | set(b))
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


def test_the_runs_are_clean(traces):
    for seed, trace in traces.items():
        assert trace.errors == [], (seed, trace.errors)


def test_an_introvert_and_an_extrovert_diverge_twice_the_noise_floor(traces):
    """Every introvert-vs-extrovert pair (both seeds each) diverges by at
    least twice the larger same-persona, cross-seed divergence (ruling P2
    moved this acceptance here from Task 8)."""
    mix = {(pid, seed): _activity_mix(trace.records[pid]) for seed, trace in traces.items() for pid in ("ivy", "eve")}
    s1, s2 = SEEDS
    noise = max(jsd(mix[("ivy", s1)], mix[("ivy", s2)]), jsd(mix[("eve", s1)], mix[("eve", s2)]))
    between = min(jsd(mix[("ivy", a)], mix[("eve", b)]) for a in SEEDS for b in SEEDS)
    print(f"introvert vs extrovert: {between:.3f} bits (smallest pair); noise floor {noise:.3f} bits")
    assert between >= 2 * noise, (between, noise)


@pytest.mark.parametrize("pid", sorted(PERSONAS))
def test_the_planned_slot_runs_on_at_least_half_her_waking_ticks(traces, pid):
    for seed, trace in traces.items():
        waking = _waking_ticks(trace.records[pid])
        followed = sum(1 for r in waking if r.planned_activity is not None and r.activity == r.planned_activity)
        print(f"{pid} seed {seed}: plan followed on {followed}/{len(waking)} waking ticks")
        assert followed / len(waking) >= 0.5, (seed, followed, len(waking))


@pytest.mark.parametrize("pid", sorted(PERSONAS))
def test_hunger_is_at_or_above_0_7_on_at_most_a_quarter_of_ticks(traces, pid):
    for seed, trace in traces.items():
        records = trace.records[pid]
        hungry = sum(1 for r in records if r.hunger >= 0.7)
        print(f"{pid} seed {seed}: hunger >= 0.7 on {hungry}/{len(records)} ticks")
        assert hungry / len(records) <= 0.25, (seed, hungry, len(records))


def test_two_personas_with_disjoint_interests_do_different_things(traces):
    for seed, trace in traces.items():
        similarity = cosine(_activity_mix(trace.records["bea"]), _activity_mix(trace.records["sam"]))
        print(f"seed {seed}: activity-mix cosine {similarity:.3f}")
        assert similarity < 0.90, (seed, similarity)


def test_no_intimate_activity_in_a_work_slot_or_her_sleep_window(traces):
    intimate = {a.name for a in get_setting().intimate_catalogue()}
    work = get_setting().names_tagged("work")
    assert work, "the default setting names its work slots"
    done = worked = 0
    for seed, trace in traces.items():
        for pid in PERSONAS:
            nights = effective_nights(trace, pid)
            for r in _waking_ticks(trace.records[pid]):
                worked += r.planned_activity in work
                if r.activity not in intimate:
                    continue
                done += 1
                assert r.planned_activity not in work, (seed, pid, r.t, r.activity, r.planned_activity)
                assert not in_windows(r.t, nights), (seed, pid, r.t, r.activity)
    # Not vacuous: she still has an intimate life, and the nurse has shifts.
    print(f"{done} intimate activities, {worked} waking ticks in a work slot")
    assert done > 0 and worked > 0, (done, worked)


# ----------------------------------------------------------------------
# A persona who drinks, in a setting that has a drink
# ----------------------------------------------------------------------

#: A drink the body knows (BodySystem's SUBSTANCE_ACTIVITIES), tagged so her
#: substance tendency finds it.
BEER = Activity(
    name="having a beer",
    category=ActivityCategory.SOCIAL,
    energy_cost=0.05,
    min_energy=0.1,
    duration_minutes=45,
    preferred_times=[TimeOfDay.AFTERNOON, TimeOfDay.EVENING, TimeOfDay.NIGHT],
    preferred_weather=list(Weather),
    suitable_locations=["bar", "home"],
    narrative_templates=["{Subj} had a cold beer and let the day go"],
    thought_possibilities=["That hits the spot"],
    emotion_effects={"relaxed": 0.1},
    tags=frozenset({"alcohol"}),
)


@pytest.fixture(scope="module")
def bar_traces(tmp_path_factory):
    """The contemporary pack plus a beer; a persona who drinks frequently, two seeds."""
    base = get_setting()
    register_setting(dataclasses.replace(base, key="test-bar", activities=list(base.activities) + [BEER]))
    try:
        return {
            seed: run_days([_sim_persona("dora", setting="test-bar", substance_tendencies={"alcohol": "frequent"})],
                           days=DAYS, seed=seed, cadence=PRODUCTION,
                           data_dir=tmp_path_factory.mktemp(f"bar_{seed}"))
            for seed in SEEDS
        }
    finally:
        unregister_setting("test-bar")


def test_a_frequent_drinker_has_a_drink(bar_traces):
    for seed, trace in bar_traces.items():
        assert trace.errors == [], (seed, trace.errors)
        drinks = sum(1 for r in trace.records["dora"] if r.activity == BEER.name)
        print(f"seed {seed}: {drinks} drinks")
        assert drinks >= 1, seed


# ----------------------------------------------------------------------
# Starting goals
# ----------------------------------------------------------------------

#: Two profiles with nothing in common.
DREAMER = PersonalityDefinition(
    id="dreamer", name="Dana", core_values=["curiosity", "creativity"], struggles=["self-doubt"],
    interests=["reading", "poetry"], personal_goal="To finish my first novel.",
)
FIGHTER = PersonalityDefinition(
    id="fighter", name="Frankie", core_values=["loyalty", "strength"], struggles=["a short temper"],
    interests=["running", "cooking"], personal_goal="To run a marathon.",
)


def _starting_goals(tmp_path, definition, seed: int) -> set:
    svc = LifeService(db_path=str(tmp_path / f"{definition.id}_{seed}.db"), persona_id=definition.id,
                      definition=definition, rng=random.Random(seed))
    svc._goal_engine.initialize_goals()  # what start() does for a new persona
    return {goal.title for goal in svc._goal_engine.active_goals}


def test_two_disjoint_profiles_do_not_share_their_starting_goals(tmp_path):
    """Thirty draws each: before this task the two drew from the same pools,
    and one in three draws or so shared enough to fail."""
    for seed in range(30):
        a, b = _starting_goals(tmp_path, DREAMER, seed), _starting_goals(tmp_path, FIGHTER, seed + 100)
        # Disjoint profiles share nothing (Jaccard < 0.3, the acceptance
        # threshold, would let 2 of 5 through: fix round, finding 5).
        assert not a & b, (seed, sorted(a & b))
