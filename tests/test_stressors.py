"""Stressors as objects, and coping (humanness program Task 15).

Before this task her stress was a number every new label bumped once (+0.05)
and every tick wore down (-0.005), beside a list of labels nothing cleared:
over three simulated days every persona carried "money worries", "errands
piling up" and four "avoiding: ..." labels on every tick while her stress read
0.00-0.01 (the Task 15 report). Now each thing that weighs on her is a
:class:`~aura_life.models.Stressor` -- what it is about, in words a person
would use (``source``), how much it weighs (``severity``), how far it is hers
to end (``controllability``) and when it lapses (``expires_at``, on the world
clock) -- her stress level is what her stressors weigh, plus the tension a
hard moment adds and that fades by the world hour, and the producers that
raise a stressor clear it when its cause is gone. How she copes comes from
her traits (``PersonaParameters``): problem-focused, avoidant or social.

Sections:

1. the stressor and the level it makes (AffectSystem);
2. what raises a stressor and what clears it (LifeService);
3. saves, new and old;
4. coping;
5. three simulated days (acceptance).
"""

import contextlib
import json
import pathlib
import random
import re
import sqlite3
from datetime import datetime, timedelta

import pytest

from aura_life import hooks
from aura_life.activities.choice import COPING_WEIGHT, ActivityPreferences, ChoiceState
from aura_life.affect.affect_system import (
    AffectSystem,
    HUNGER_STRESSOR_SEVERITY,
    STRESS_EXCESS_DECAY_PER_HOUR,
    STRESSOR_CONTROLLABILITY,
    STRESSOR_KINDS,
    STRESSOR_SEVERITY,
)
from aura_life.drive.drive_system import AVOIDANCE_CHANCE, MAX_AVOIDANCE, DriveSystem
from aura_life.errands.errands_system import MAX_TOTAL as ERRANDS_MAX_TOTAL
from aura_life.life_service import SANITY_STRESS_SOURCE, LifeService
from aura_life.models import DailyPlan, PlannedSlot, Stressor, Weather
from aura_life.money.finance_system import MAX_FINANCIAL_STRESS
from aura_life.personas.parameters import PersonaParameters
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.planner.daily_planner import DailyPlanner
from aura_life.settings import DEFAULT_SETTING, get_setting
from aura_life.world import WorldEnvironment

#: A Tuesday afternoon: awake on the library's default schedule, a workday
#: inside the default shift (9:00-17:00).
TUESDAY_1400 = datetime(2026, 10, 6, 14, 0)

#: Her traits, every other one neutral (0.5).
PROBLEM_FOCUSED = {"conscientiousness": 0.9, "rumination": 0.1}
AVOIDANT = {"conscientiousness": 0.1, "rumination": 0.9}
SOCIAL = {"sociability": 0.9}

#: What a person would not say about what weighs on her: a snake_case key or
#: an engine label's "key:" prefix.
RAW_KEY = re.compile(r"[a-z]_[a-z]|^[a-z ]+:")

STILL = dict(weather="snowy", season="autumn")


class ScriptedClock:
    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant

    def advance(self, **delta) -> datetime:
        self.instant += timedelta(**delta)
        return self.instant


@pytest.fixture
def clock():
    """The world's clock and her local one (the ``persona_now`` hook) on one
    scripted instant; the previous provider is put back afterwards."""
    saved = hooks.provider_for("persona_now")
    scripted = ScriptedClock(TUESDAY_1400)
    hooks.configure(persona_now=lambda timezone=None: scripted.instant)
    yield scripted
    hooks.configure(persona_now=saved)


def _service(tmp_path, clock, name: str = "nora", seed: int = 11, traits=None, **kwargs) -> LifeService:
    """A persona of a world on ``clock``, her draws seeded; no NPC event,
    chaos, micro-event or intimate interlude on her activity ticks."""
    pathlib.Path(tmp_path).mkdir(parents=True, exist_ok=True)
    if traits is not None:
        kwargs["definition"] = PersonalityDefinition(id=name, name=name.title(), traits=dict(traits),
                                                     appearance_details={"gender": "female"})
    svc = LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=name,
                      world_environment=WorldEnvironment(now=clock, seed=seed), rng=random.Random(seed), **kwargs)
    svc._desire_system.should_do_intimate_activity = lambda *args, **kw: False
    svc._social.tick = lambda *args, **kw: None
    svc._chaos.roll = lambda *args, **kw: None
    svc._micro_event_chance = 0.0
    return svc


def _do(svc: LifeService, name: str):
    """She does ``name`` now, through her whole activity pipeline."""
    return svc._perform_activity(svc._activity_engine.get_activity(name), None)


def _kinds(affect: AffectSystem) -> dict:
    """Her stressors, by kind -> their sources."""
    kinds = {}
    for stressor in affect.stressors:
        kinds.setdefault(stressor.kind, []).append(stressor.source)
    return kinds


def _tick(affect: AffectSystem, hours: float, now=None, **body) -> None:
    affect.tick(body_state={"hunger": 0.0, "hours_awake": 8.0, **body}, social_state={"recent_events": []},
                hours=hours, now=now, **STILL)


# ======================================================================
# 1. The stressor, and the level it makes
# ======================================================================

def test_a_stressor_is_a_source_a_severity_a_controllability_and_an_expiry():
    lapses = datetime(2026, 10, 6, 18, 0)
    stressor = Stressor("errands piling up", 0.05, 1.0, lapses)
    assert (stressor.source, stressor.severity, stressor.controllability, stressor.expires_at) == (
        "errands piling up", 0.05, 1.0, lapses)
    assert Stressor("money worries", 0.05, 0.0).expires_at is None


def test_her_stress_is_what_her_stressors_weigh():
    affect = AffectSystem()
    assert affect.stress.level == 0.0
    affect.add_stressor(Stressor("money worries", 0.05, 0.0))
    affect.add_stressor(Stressor("a hangover", 0.1, 0.0))
    assert affect.stress.level == pytest.approx(0.15)
    assert affect.stress.sources == ["a hangover", "money worries"]  # heaviest first
    assert [s.source for s in affect.stressors] == affect.stress.sources == [
        s.source for s in affect.stress.stressors]


def test_a_listed_stressor_always_weighs_whatever_eases_her():
    """The acceptance: no "money worries" at stress 0. A kind word, a joke, a
    calm place and a restful activity ease the tension on top of what weighs
    on her -- never below it."""
    affect = AffectSystem()
    affect.add_stressor(Stressor("money worries", STRESSOR_SEVERITY, 0.0))
    for _ in range(50):
        affect.process_conversation_trigger("encouragement")
        affect.process_conversation_trigger("humor")
        affect.on_location_effects(stress_delta=-0.04, social_drain=0.0, is_nature=True)
        affect.on_activity("yoga")
        _tick(affect, hours=1.0)
    assert affect.stress.sources == ["money worries"]
    assert affect.stress.level == pytest.approx(STRESSOR_SEVERITY)
    assert affect.stress.level > 0.0


def test_a_hard_moment_adds_tension_that_fades_by_the_world_hour():
    affect = AffectSystem()
    affect.add_stressor(Stressor("money worries", 0.05, 0.0))
    affect.process_conversation_trigger("criticism")  # +0.08 at her neutral reactivity
    assert affect.stress.level == pytest.approx(0.05 + 0.08)
    _tick(affect, hours=0.5)
    assert affect.stress.level == pytest.approx(0.05 + 0.08 - 0.5 * STRESS_EXCESS_DECAY_PER_HOUR)
    _tick(affect, hours=5.0)
    assert affect.stress.level == pytest.approx(0.05)


def test_the_tension_fades_the_same_whatever_the_cadence():
    """Ruling T4-R3: the scheduler's 5-minute energy tick and the legacy
    15-minute one agree on how her stress fades and when a stressor lapses."""
    start = datetime(2026, 10, 6, 9, 0)
    runs = {}
    for minutes in (5, 15):
        affect = AffectSystem()
        affect.add_stressor(Stressor("someone", 0.05, 0.0, start + timedelta(hours=2)))
        affect.process_conversation_trigger("criticism")
        levels = {}
        for step in range(1, 3 * 60 // minutes + 1):
            now = start + timedelta(minutes=minutes * step)
            _tick(affect, hours=minutes / 60, now=now)
            if (minutes * step) % 15 == 0:
                levels[minutes * step] = (round(affect.stress.level, 9), tuple(affect.stress.sources))
        runs[minutes] = levels
    assert runs[5] == runs[15]
    assert runs[5][120] == (0.0, ())  # lapsed at two hours, the tension long gone


def test_resolving_a_stressor_takes_its_weight_away_at_once(clock):
    affect = AffectSystem()
    affect.add_stressor(Stressor("errands piling up", 0.05, 1.0))
    affect.add_stressor(Stressor("money worries", 0.05, 0.0))
    affect.on_stressor_resolved("errands piling up", now=clock.instant)
    assert affect.stress.sources == ["money worries"]
    assert affect.stress.level == pytest.approx(0.05)
    assert affect.stress.last_relief == clock.instant
    affect.on_stressor_resolved("errands piling up", now=clock.instant)  # nothing left to resolve
    assert affect.stress.level == pytest.approx(0.05)


def test_a_stressor_lapses_at_its_expiry_on_the_world_clock():
    start = datetime(2026, 10, 6, 9, 0)
    affect = AffectSystem()
    affect.add_stressor(Stressor("Shirley", 0.05, 0.0, start + timedelta(hours=4)))
    _tick(affect, hours=1.0, now=start + timedelta(hours=3, minutes=55))
    assert affect.stress.sources == ["Shirley"]
    _tick(affect, hours=1.0, now=start + timedelta(hours=4))
    assert affect.stress.sources == [] and affect.stress.level == 0.0
    # Without the world's instant nothing lapses: the engine reads no clock.
    affect.add_stressor(Stressor("Shirley", 0.05, 0.0, start))
    _tick(affect, hours=1.0)
    assert affect.stress.sources == ["Shirley"]


@pytest.mark.parametrize("volatility, hours", [(0.5, 4.0), (0.9, 4.0 / 1.5)])
def test_an_upset_weighs_on_her_as_long_as_her_mood_takes_to_settle_half_way(volatility, hours):
    """A struggle flaring up, someone unwelcome getting in touch, compromising
    on a value: an episode, that lapses after her mood's valence half-life
    (MOOD_VALENCE_HALF_LIFE_HOURS, shorter for a volatile persona)."""
    affect = AffectSystem(params=PersonaParameters(volatility=volatility))
    now = datetime(2026, 10, 6, 9, 0)
    for kind, words in (("struggle", {"what": "self-doubt"}), ("unwelcome", {"name": "Shirley"}),
                        ("torn", {"value": "honesty"})):
        stressor = affect.raise_stressor(kind, now=now, **words)
        assert stressor.expires_at == now + timedelta(hours=hours), kind
    assert affect.stress.sources == ["self-doubt", "Shirley", "compromising on honesty"]


def test_a_held_kind_is_exactly_what_its_producer_says_now():
    """hold_stressors: the stressors of a kind become exactly the ones named
    -- a new one is added, a held one refreshed, the rest resolved."""
    affect = AffectSystem()
    affect.hold_stressors("obligation", [{"what": "call Mo back"}, {"what": "return the drill"}])
    assert _kinds(affect) == {"obligation": ["not getting to call Mo back", "not getting to return the drill"]}
    affect.hold_stressors("obligation", [{"what": "return the drill"}], share=0.5)
    assert _kinds(affect) == {"obligation": ["not getting to return the drill"]}
    assert affect.stress.level == pytest.approx(0.5 * STRESSOR_KINDS["obligation"].severity)
    affect.hold_stressor("money", True)
    affect.hold_stressor("money", False)
    assert "money worries" not in affect.stress.sources


def test_hunger_and_not_enough_sleep_come_and_go_with_her_body():
    affect = AffectSystem()
    _tick(affect, hours=0.25, hunger=0.8, hours_awake=17.0)
    assert set(affect.stress.sources) == {"hunger", "not enough sleep"}
    assert affect.stress.level == pytest.approx(HUNGER_STRESSOR_SEVERITY + STRESSOR_SEVERITY)
    _tick(affect, hours=0.25, hunger=0.5, hours_awake=17.0)
    assert affect.stress.sources == ["not enough sleep"]
    _tick(affect, hours=0.25, hunger=0.5, hours_awake=0.0)
    assert affect.stress.sources == [] and affect.stress.level == 0.0


def test_a_stressor_added_the_old_way_weighs_what_one_always_added():
    """on_stressor_added(source) keeps its meaning: a stressor a host names
    weighs STRESSOR_SEVERITY (the +0.05 each one used to add once) until it is
    resolved, and naming it again changes nothing."""
    affect = AffectSystem()
    affect.on_stressor_added("exam next week")
    affect.on_stressor_added("exam next week")
    [stressor] = affect.stressors
    assert (stressor.source, stressor.severity, stressor.controllability, stressor.expires_at, stressor.kind) == (
        "exam next week", STRESSOR_SEVERITY, STRESSOR_CONTROLLABILITY, None, "")
    assert affect.stress.level == pytest.approx(STRESSOR_SEVERITY)


def test_the_export_keeps_its_short_keys_and_the_status_lists_the_stressors():
    """The host reads stress.level and the sources as a list of words (aura's
    context_extract.py and prompt), and aura's inner digest prints the whole
    ``stress`` dict into an LLM prompt: the engine export stays short keys with
    primitive values (aura's engine rule), so the structured stressors are in
    get_status() only, and the export adds just ``coping``, a word."""
    affect = AffectSystem()
    lapses = datetime(2026, 10, 6, 18, 0)
    affect.add_stressor(Stressor("Shirley", 0.1, 0.0, lapses, "unwelcome"))
    affect.add_stressor(Stressor("money worries", 0.05, 0.0, None, "money"))
    assert affect.export_state()["stress"] == {
        "level": 0.15, "sources": ["Shirley", "money worries"], "coping": "balanced"}
    status = affect.get_status()
    assert status["stress"] == 0.15 and status["stress_sources"] == ["Shirley", "money worries"]
    assert status["stressors"] == [
        {"source": "Shirley", "severity": 0.1, "controllability": 0.0, "expires_at": lapses.isoformat(),
         "kind": "unwelcome"},
        {"source": "money worries", "severity": 0.05, "controllability": 0.0, "expires_at": None, "kind": "money"},
    ]
    row = affect.to_dict()
    assert row["stress_level"] == pytest.approx(0.15)
    assert json.loads(row["stress_sources"]) == ["Shirley", "money worries"]


def test_a_save_keeps_every_stressor_and_the_tension():
    affect = AffectSystem()
    lapses = datetime(2026, 10, 6, 18, 0)
    affect.add_stressor(Stressor("Shirley", 0.1, 0.0, lapses, "unwelcome"))
    affect.hold_stressor("errands", True)
    affect.process_conversation_trigger("criticism")
    again = AffectSystem.from_dict(affect.to_dict(), now=datetime(2026, 10, 6, 15, 0))
    assert again.stressors == affect.stressors
    assert again.stress.level == pytest.approx(affect.stress.level)
    # One that lapsed while she was saved is gone when she loads.
    later = AffectSystem.from_dict(affect.to_dict(), now=lapses)
    assert later.stress.sources == ["errands piling up"]
    assert later.stress.level == pytest.approx(affect.stress.level - 0.1)


def test_every_stressor_kind_the_library_raises_is_worded_for_a_person():
    """What she is stressed about reads as words (tests/test_render_lint.py
    lints how each renders): no key, no engine label."""
    for kind, spec in STRESSOR_KINDS.items():
        assert not RAW_KEY.search(spec.words), kind
        assert 0.0 < spec.severity <= 1.0 and 0.0 <= spec.controllability <= 1.0, kind
    assert SANITY_STRESS_SOURCE == STRESSOR_KINDS["sanity"].words
    assert not RAW_KEY.search(SANITY_STRESS_SOURCE) and SANITY_STRESS_SOURCE != "sanity"


# ======================================================================
# 2. What raises a stressor, and what clears it
# ======================================================================

def test_eating_clears_her_hunger(tmp_path, clock):
    svc = _service(tmp_path, clock)
    svc._sustenance.state.hunger = 0.85
    svc._on_energy_tick()
    assert "hunger" in svc.affect.stress.sources
    _do(svc, "having lunch")
    clock.advance(minutes=5)
    svc._on_energy_tick()
    assert "hunger" not in svc.affect.stress.sources


def test_sleeping_clears_not_enough_sleep(tmp_path, clock):
    svc = _service(tmp_path, clock)
    svc.energy._state.last_sleep_time = clock.instant - timedelta(hours=17)
    svc._on_energy_tick()
    assert "not enough sleep" in svc.affect.stress.sources
    svc.energy.sleep(hours=8)
    clock.advance(minutes=5)
    svc._on_energy_tick()
    assert "not enough sleep" not in svc.affect.stress.sources


def test_money_restored_clears_money_worries(tmp_path, clock):
    svc = _service(tmp_path, clock)
    svc._finance.state.balance = 100.0
    svc._on_energy_tick()
    assert "money worries" in svc.affect.stress.sources
    # By how tight money is, on the finance engine's own scale.
    [money] = [s for s in svc.affect.stressors if s.kind == "money"]
    assert money.severity == pytest.approx(STRESSOR_SEVERITY * svc._finance.financial_stress() / MAX_FINANCIAL_STRESS)
    svc._finance.state.balance = 5000.0
    clock.advance(minutes=5)
    svc._on_energy_tick()
    assert "money worries" not in svc.affect.stress.sources


def test_an_errand_done_clears_errands_piling_up(tmp_path, clock):
    svc = _service(tmp_path, clock)
    svc._errands.state.pending = []
    svc._errands.state.overdue = ["pay a bill", "buy stamps", "call the dentist"]
    svc._on_energy_tick()
    assert "errands piling up" in svc.affect.stress.sources
    [errands] = [s for s in svc.affect.stressors if s.kind == "errands"]
    assert errands.severity == pytest.approx(STRESSOR_SEVERITY * 3 / ERRANDS_MAX_TOTAL)
    _do(svc, "running errands")
    assert svc._errands.overdue_count == 2
    clock.advance(minutes=5)
    svc._on_energy_tick()
    assert "errands piling up" not in svc.affect.stress.sources


def test_the_end_of_her_shift_clears_work(tmp_path, clock):
    svc = _service(tmp_path, clock, occupation="baker")
    career = svc._career.state
    career.work_days = [clock.instant.weekday()]
    career.shift_start_hour, career.shift_end_hour = 10, 16
    career.workload = 0.9
    svc._on_energy_tick()
    assert "work" in svc.affect.stress.sources
    [work] = [s for s in svc.affect.stressors if s.kind == "work"]
    assert work.severity == pytest.approx(STRESSOR_SEVERITY * svc._career.work_stress(now=clock.instant))
    clock.instant = clock.instant.replace(hour=17)
    svc._on_energy_tick()
    assert "work" not in svc.affect.stress.sources


def test_what_she_puts_off_is_one_stressor_named_for_the_worst_of_it(tmp_path, clock):
    svc = _service(tmp_path, clock)
    drive = svc._drive
    drive.add_avoidance("replying to that message")
    drive.add_avoidance("finishing that project")
    drive._avoidances[0].guilt_accumulated = 0.5
    drive._avoidances[1].guilt_accumulated = 0.9
    svc._on_energy_tick()
    [put_off] = [s for s in svc.affect.stressors if s.kind == "put_off"]
    assert put_off.source == "putting off finishing that project"
    # A hassle's worth at MAX_AVOIDANCE things put off at full guilt.
    guilt = sum(a.guilt_accumulated for a in drive._avoidances)
    assert 1.4 < guilt < 1.5
    assert put_off.severity == pytest.approx(STRESSOR_SEVERITY * guilt / MAX_AVOIDANCE)
    drive.resolve_avoidance("finishing that project")
    clock.advance(minutes=5)
    svc._on_energy_tick()
    assert [s.source for s in svc.affect.stressors if s.kind == "put_off"] == ["putting off replying to that message"]
    drive.resolve_avoidance("replying to that message")
    clock.advance(minutes=5)
    svc._on_energy_tick()
    assert "put_off" not in _kinds(svc.affect)


def test_an_overdue_obligation_weighs_until_it_is_kept(tmp_path, clock):
    svc = _service(tmp_path, clock)
    svc._social.add_obligation("call Mo back", "Mo", deadline=datetime(2000, 1, 1))
    svc._on_energy_tick()
    assert "not getting to call Mo back" in svc.affect.stress.sources
    svc._social.fulfill_obligation("call Mo back")
    clock.advance(minutes=5)
    svc._on_energy_tick()
    assert "not getting to call Mo back" not in svc.affect.stress.sources


def test_a_surfacing_struggle_lapses(tmp_path, clock):
    svc = _service(tmp_path, clock, definition=PersonalityDefinition(struggles=["self-doubt"]))
    svc._identity._pending_struggle_effects = ["self-doubt"]
    svc._identity._tick_struggles = lambda: None  # only the one above surfaces
    svc._on_energy_tick()
    [struggle] = [s for s in svc.affect.stressors if s.kind == "struggle"]
    assert struggle.source == "self-doubt"
    assert struggle.expires_at == clock.instant + timedelta(hours=4)
    clock.advance(hours=4)
    svc._on_energy_tick()
    assert "self-doubt" not in svc.affect.stress.sources


def test_a_hangover_weighs_until_it_wears_off(tmp_path, clock):
    """BodySystem's hangover (is_hungover past 0.1 severity): "a hangover"
    while it lasts, gone the tick after it has worn off."""
    svc = _service(tmp_path, clock)
    svc._body._inebriation.hangover_severity = 0.5
    svc._on_energy_tick()
    assert "a hangover" in svc.affect.stress.sources
    svc._body._inebriation.hangover_severity = 0.0
    clock.advance(minutes=5)
    svc._on_energy_tick()
    assert "a hangover" not in svc.affect.stress.sources


def test_the_sanity_stressor_is_worded_for_a_person(tmp_path, clock):
    svc = _service(tmp_path, clock)
    svc.on_sanity_blow("grief", 1.0)
    assert svc.affect.stress.sources == [SANITY_STRESS_SOURCE] == ["keeping it together"]


# ======================================================================
# 3. Saves, new and old
# ======================================================================

#: A row as the library saved it before Task 15: the labels, and the level
#: the one-time bumps had worn down to.
LEGACY_ROW = {
    "stress_level": 0.01,
    "stress_sources": json.dumps([
        "money worries", "errands piling up", "work stress", "messy space", "hangover", "hunger",
        "sleep_deprivation", "sanity", "struggle:self-doubt", "avoiding: finishing that project",
    ]),
}


def test_an_old_save_s_labels_become_stressors_in_words():
    now = datetime(2026, 10, 6, 9, 0)
    affect = AffectSystem.from_dict(dict(LEGACY_ROW), now=now)
    by_source = {s.source: s for s in affect.stressors}
    assert set(by_source) == {
        "money worries", "errands piling up", "work", "the mess at home", "a hangover", "hunger",
        "not enough sleep", "keeping it together", "self-doubt", "putting off finishing that project",
    }
    for source, kind in (("money worries", "money"), ("work", "work"), ("the mess at home", "home"),
                         ("not enough sleep", "sleep"), ("keeping it together", "sanity"),
                         ("putting off finishing that project", "put_off")):
        assert by_source[source].kind == kind
        assert by_source[source].severity == STRESSOR_KINDS[kind].severity
        assert by_source[source].controllability == STRESSOR_KINDS[kind].controllability
    # The struggle was an episode: it lapses her valence half-life after the load.
    assert by_source["self-doubt"].expires_at == now + timedelta(hours=4)
    # A listed stressor weighs: the level is at least what they weigh.
    assert affect.stress.level == pytest.approx(sum(s.severity for s in affect.stressors))


def test_an_old_save_s_unknown_label_is_an_episode_of_the_old_weight():
    now = datetime(2026, 10, 6, 9, 0)
    affect = AffectSystem.from_dict({"stress_level": 0.3, "stress_sources": json.dumps(["Shirley"])}, now=now)
    [stressor] = affect.stressors
    assert (stressor.source, stressor.severity, stressor.controllability, stressor.expires_at, stressor.kind) == (
        "Shirley", STRESSOR_SEVERITY, STRESSOR_CONTROLLABILITY, now + timedelta(hours=4), "")
    assert affect.stress.level == pytest.approx(0.3)  # the saved level above what it weighs: tension


def test_an_old_database_opens_and_keeps_its_stress(tmp_path, clock):
    """A life.db from before Task 15 (no stressors column) migrates in place
    and her labels load as stressors."""
    svc = _service(tmp_path, clock, name="old")
    svc._save_affect()
    with sqlite3.connect(svc._db_path) as conn:
        conn.execute("UPDATE life_affect_state SET stressors = NULL, stress_level = 0.02, stress_sources = ?",
                     (json.dumps(["money worries", "struggle:self-doubt"]),))
    again = _service(tmp_path, clock, name="old")
    again._load_state()
    assert again.affect.stress.sources == ["money worries", "self-doubt"]
    assert again.affect.stress.level == pytest.approx(0.1)


def _on_a_baker_s_shift(svc: LifeService) -> LifeService:
    """Her shift today is 10:00-16:00, hard going (as in
    test_the_end_of_her_shift_clears_work)."""
    career = svc._career.state
    career.work_days = [svc._world.now().weekday()]
    career.shift_start_hour, career.shift_end_hour = 10, 16
    career.workload = 0.9
    return svc


def _rows(affect: AffectSystem) -> list:
    return [(s.source, s.kind, s.severity, s.controllability, s.expires_at) for s in affect.stressors]


def test_a_reload_keeps_what_each_stressor_is_and_when_it_lapses(tmp_path, clock):
    """Saved and opened again on the same database, she has the same
    stressors -- each of its kind, weight and expiry -- and each still goes
    with its cause. Were the stressors not saved, the row's words would load
    as labels: "keeping it together" and "work" as unknown ones, episodes of
    no kind, and "work" would outlive her shift."""
    svc = _on_a_baker_s_shift(_service(tmp_path, clock, name="saved", occupation="baker"))
    svc.on_sanity_blow("grief", 1.0)
    svc._on_energy_tick()
    svc.affect.add_stressor(Stressor("Shirley", 0.1, 0.0, clock.instant + timedelta(hours=2), "unwelcome"))
    before = _rows(svc.affect)
    assert {"sanity", "work", "unwelcome"} <= set(_kinds(svc.affect))
    svc._save_affect()
    again = _on_a_baker_s_shift(_service(tmp_path, clock, name="saved", occupation="baker"))
    again._load_state()
    assert _rows(again.affect) == before
    assert again.affect.stress.level == pytest.approx(svc.affect.stress.level)
    # 17:00: her shift is over and the upset (16:00) has lapsed.
    clock.instant = clock.instant.replace(hour=17)
    again._on_energy_tick()
    assert "work" not in again.affect.stress.sources
    assert "Shirley" not in again.affect.stress.sources
    assert "keeping it together" in again.affect.stress.sources


def test_an_old_database_s_episode_lapses_on_the_world_clock_after_the_reload(tmp_path, clock):
    """A struggle saved before Task 15 is an episode raised at the load: it
    lapses her valence half-life later on the world clock (no producer ever
    resolves a struggle, so without the load's instant it would weigh on her
    for good)."""
    svc = _service(tmp_path, clock, name="older")
    svc._save_affect()
    with contextlib.closing(sqlite3.connect(svc._db_path)) as conn:
        conn.execute("UPDATE life_affect_state SET stressors = NULL, stress_level = 0.05, stress_sources = ?",
                     (json.dumps(["struggle:self-doubt"]),))
        conn.commit()
    again = _service(tmp_path, clock, name="older")
    again._load_state()
    [struggle] = [s for s in again.affect.stressors if s.kind == "struggle"]
    assert (struggle.source, struggle.expires_at) == ("self-doubt", clock.instant + timedelta(hours=4))
    clock.advance(hours=4)
    again._on_energy_tick()
    assert "self-doubt" not in again.affect.stress.sources


# ======================================================================
# 4. Coping
# ======================================================================

@pytest.mark.parametrize("traits, problem_focus, avoidance_scale, contact_seeking, style", [
    ({}, 0.0, 1.0, 0.0, "balanced"),
    (PROBLEM_FOCUSED, 1.0, 1.0, 0.0, "problem-focused"),
    (AVOIDANT, -1.0, 2.0, 0.0, "avoidant"),
    (SOCIAL, 0.0, 1.0, 0.5, "social"),
    ({"sociability": 0.1, "rumination": 0.8}, -0.375, 1.375, -0.5, "avoidant"),
    ({"sociability": 0.9, "rumination": 0.2}, 0.375, 1.0, 0.5, "social"),
])
def test_how_she_copes_comes_from_her_traits(traits, problem_focus, avoidance_scale, contact_seeking, style):
    params = PersonaParameters(**traits)
    assert params.problem_focus == pytest.approx(problem_focus)
    assert params.avoidance_scale == pytest.approx(avoidance_scale)
    assert params.contact_seeking == pytest.approx(contact_seeking)
    assert params.coping_style == style
    assert AffectSystem(params=params).export_state()["stress"]["coping"] == style


def test_problem_focus_pulls_only_toward_what_ends_a_controllable_stressor():
    running = next(a for a in get_setting(DEFAULT_SETTING).resolved_activities() if a.name == "running errands")
    reading = next(a for a in get_setting(DEFAULT_SETTING).resolved_activities() if a.name == "reading")
    focused = ActivityPreferences(PersonaParameters(**PROBLEM_FOCUSED))
    avoidant = ActivityPreferences(PersonaParameters(**AVOIDANT))
    calm = ChoiceState(energy=0.8)
    stressed = ChoiceState(energy=0.8, resolving={"running errands": 1.0})
    assert focused.utility(running, stressed) - focused.utility(running, calm) == pytest.approx(COPING_WEIGHT * 1.0)
    assert focused.utility(reading, stressed) == focused.utility(reading, calm)
    assert avoidant.utility(running, stressed) == avoidant.utility(running, calm)


def test_a_problem_focused_persona_deals_with_a_controllable_stressor_more_often_than_an_avoidant_one(
        tmp_path, clock):
    """The acceptance: the same controllable stressor -- errands piling up,
    held for 100 activity ticks with nothing planned -- and the
    problem-focused persona runs errands (what clears one: ErrandsSystem)
    more often than the avoidant one."""
    counts = {}
    for label, traits in (("focused", PROBLEM_FOCUSED), ("avoidant", AVOIDANT)):
        svc = _service(tmp_path / label, clock, name=label, traits=traits)
        clears = svc._resolving_activities("errands")
        assert clears and all(svc._errands.clears(name) for name in clears)
        done = []
        real_record = svc._record_activity
        svc._record_activity = lambda log, real=real_record: (done.append(log.activity_name), real(log))[1]
        for _ in range(100):
            svc._daily_planner._current_plan = None
            svc._errands.state.pending = []
            svc._errands.state.overdue = ["pay a bill", "buy stamps", "call the dentist"]
            svc._affect.hold_stressor("errands", True, now=clock.instant)
            svc._energy._state.level = 0.8
            svc._sustenance.state.hunger = 0.2
            assert svc._choice_state().resolving == {name: 1.0 for name in clears}
            svc._activity_tick()
        counts[label] = sum(1 for name in done if name in clears)
        assert len(done) == 100, label
    print(f"errand-clearing choices in 100 ticks: {counts}")
    assert counts["focused"] > 2 * counts["avoidant"], counts


def test_what_she_is_hungry_for_is_what_problem_focus_reaches_for(tmp_path, clock):
    svc = _service(tmp_path, clock)
    svc._sustenance.state.hunger = 0.85
    svc._on_energy_tick()
    resolving = svc._choice_state().resolving
    assert set(resolving) == set(svc._setting.names_tagged("meal")) & {a.name for a in svc._setting.activities_for("nora")}
    assert set(resolving.values()) == {STRESSOR_KINDS["hunger"].controllability}


def test_an_avoidant_persona_puts_more_off_and_feels_its_guilt_sooner():
    neutral = DriveSystem(rng=random.Random(1), params=PersonaParameters())
    avoidant = DriveSystem(rng=random.Random(1), params=PersonaParameters(**AVOIDANT))
    for drive in (neutral, avoidant):
        drive.add_avoidance("replying to that message")
        for _ in range(20):
            drive.tick()
    assert avoidant._avoidances[0].guilt_accumulated == pytest.approx(2 * neutral._avoidances[0].guilt_accumulated)

    class _Draw:
        """A roll that lands between the neutral chance and the avoidant one."""

        def random(self):
            return AVOIDANCE_CHANCE * 1.5

        def choice(self, pool):
            return pool[0]

    started = {}
    for label, params in (("neutral", PersonaParameters()), ("avoidant", PersonaParameters(**AVOIDANT))):
        drive = DriveSystem(rng=_Draw(), params=params)
        drive.roll_avoidance()
        started[label] = len(drive._avoidances)
    assert started == {"neutral": 0, "avoidant": 1}


def test_under_stress_a_social_coper_reaches_for_company():
    texting = next(a for a in get_setting(DEFAULT_SETTING).resolved_activities() if a.name == "texting a friend")
    for traits, rise in ((SOCIAL, COPING_WEIGHT * 0.5 * 0.6), ({}, 0.0), ({"sociability": 0.1}, 0.0)):
        preferences = ActivityPreferences(PersonaParameters(**traits))
        calm = preferences.utility(texting, ChoiceState(needs={"calm": 0.0}))
        stressed = preferences.utility(texting, ChoiceState(needs={"calm": 0.6}))
        assert stressed - calm == pytest.approx(rise), traits


def _low_day_swaps(traits, seed) -> list:
    """What a low mood swaps her free afternoon for (four free slots, each
    something demanding), on a planner of her traits."""
    params = PersonaParameters(**traits)
    planner = DailyPlanner(rng=random.Random(seed), params=params)
    free = ["learning something new", "sketching ideas", "writing poetry", "going for a walk"]
    planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=15 + i, activity_name=name, reason="free time", location="home") for i, name in enumerate(free)])
    planner.revise_upcoming(Weather.CLOUDY, energy_level=0.9, mood="low", mood_intensity=0.9,
                            now=datetime(2026, 10, 6, 14, 0))
    return [slot.activity_name for slot in planner.current_plan.slots]


def test_on_a_low_day_a_social_coper_seeks_contact_and_the_others_withdraw():
    """Ruling T14-R3's carry-in: coping makes low days differ. The comforts a
    low mood swaps her plan for include company only for a persona who seeks
    it (her contact_seeking); everyone else keeps to the gentle ones."""
    spec = get_setting(DEFAULT_SETTING)
    gentle = set(spec.names_tagged("gentle"))
    contact = {a.name for a in spec.resolved_activities()
               if ActivityPreferences().satisfaction(a).get("social", 0.0) > 0}
    swaps = {label: [name for seed in range(10) for name in _low_day_swaps(traits, seed)]
             for label, traits in (("social", SOCIAL), ("neutral", {}),
                                   ("avoidant", {"sociability": 0.1, "rumination": 0.8}))}
    assert set(swaps["neutral"]) <= gentle and set(swaps["avoidant"]) <= gentle
    reached = [name for name in swaps["social"] if name in contact]
    print(f"a social coper's low-day comforts: {len(reached)} of {len(swaps['social'])} with company")
    assert len(reached) > len(swaps["social"]) / 2
    assert set(swaps["social"]) <= gentle | contact


def test_on_a_low_day_a_social_coper_keeps_her_plans_to_see_people():
    kept = {}
    for label, params in (("social", PersonaParameters(**SOCIAL)), ("neutral", PersonaParameters())):
        planner = DailyPlanner(rng=random.Random(3), params=params)
        planner._current_plan = DailyPlan(date="2026-10-06", slots=[
            PlannedSlot(hour=16, activity_name="having coffee with a friend", reason="free time", location="cafe")])
        planner.revise_upcoming(Weather.CLOUDY, energy_level=0.9, mood="low", mood_intensity=0.9,
                                now=datetime(2026, 10, 6, 14, 0))
        kept[label] = planner.current_plan.slots[0].activity_name
    assert kept["social"] == "having coffee with a friend"
    assert kept["neutral"] != "having coffee with a friend"


# ======================================================================
# 5. Three simulated days (acceptance)
# ======================================================================

@pytest.fixture(scope="module")
def stress_trace(tmp_path_factory):
    from sim_helpers import PRODUCTION, SimPersona, run_days

    def persona(pid, **fields):
        return SimPersona(pid, service_kwargs={"definition": PersonalityDefinition(
            id=pid, name=pid.title(), appearance_details={"gender": "female"}, **fields),
            **({"occupation": fields["occupation"]} if "occupation" in fields else {})})

    personas = [
        SimPersona("control"),
        persona("nell", occupation="nurse", struggles=["self-doubt", "money"]),
        persona("ivy", traits={"sociability": 0.1, "rumination": 0.8}),
        persona("eve", traits={"sociability": 0.9, "rumination": 0.2}),
    ]
    return run_days(personas, days=3, seed=9, cadence=PRODUCTION, data_dir=tmp_path_factory.mktemp("stressors"))


def test_three_days_list_no_stressor_at_zero_stress_and_only_words(stress_trace):
    """The acceptance: a listed stressor implies stress > 0, on every step of
    every persona; and every source listed is words, not a key."""
    assert stress_trace.errors == []
    for pid, records in stress_trace.records.items():
        listed = [r for r in records if r.stress_sources]
        assert listed, pid
        assert all(r.stress > 0.0 for r in listed), pid
        for record in listed:
            for source in record.stress_sources:
                assert not RAW_KEY.search(source), (pid, source)
