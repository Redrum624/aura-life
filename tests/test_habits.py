"""Habits that drift over days (0.5.0).

What she has done often lately becomes a habit her planner favours (comfort); what she has done too much loses its pull
(staleness), so her days shift slowly over a week and keep their variety. The activity history behind it is dated -- the
world clock's instant and her local hour -- and kept four weeks, so a habit belongs to a part of her day and fades over days.

Everything here runs on a fake clock: no assertion depends on the hour the host runs at.

The design values are written here as literals from the design note (aura-life CHANGELOG 0.5.0), never read from the
module, so a changed constant turns a test red instead of moving the test with it.
"""
import contextlib
import importlib
import json
import random
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

import pytest

from aura_life.activities.activity_engine import ActivityEngine
from aura_life.behavior.behavior_system import BehaviorSystem, habit_band
from aura_life.life_service import LifeService
from aura_life.models import Weather
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.planner import daily_planner
from aura_life.planner.daily_planner import NOT_HABIT_FORMING, DailyPlanner
from aura_life.world import WorldEnvironment

#: A simulated Monday, years from any host clock.
MONDAY = datetime(2031, 3, 10, 0, 0)

#: The bound: a habit moves an activity's chance in any one choice by at most x1.5 up or /1.5 down.
MAX_RATIO = 1.5
#: Comfort peaks when an activity fills 15% of a part of her day; neutral at twice that, fully stale from three times.
PEAK_SHARE = 0.15
#: What she did 3.5 days ago counts half as much as what she did today.
HALF_LIFE_DAYS = 3.5
#: A habit reaches full strength once a part of her day holds 60 weighted ticks (20 hours) of free time.
FULL_EVIDENCE = 60
#: The dated history keeps four weeks, at most four weeks of 20-minute ticks.
HISTORY_DAYS = 28
HISTORY_CAP = 28 * 72


def _factor(signal: float, confidence: float = 1.0) -> float:
    return MAX_RATIO ** (confidence * signal / 2)


class ScriptedClock:
    """A clock that moves only when told to (as in tests/test_world_clock_routes.py)."""

    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant


def _service(db_path, world) -> LifeService:
    return LifeService(
        db_path=str(db_path),
        persona_id="habits",
        world_environment=world,
        definition=PersonalityDefinition(core_traits=["curious"], home_type="studio"),
        rng=random.Random(5),
    )


# ---------------------------------------------------------------- the parts of her day

def test_a_habit_belongs_to_a_part_of_her_day():
    hours = (5, 6, 11, 12, 16, 17, 21, 22, 0)
    assert [habit_band(h) for h in hours] == [
        "night", "morning", "morning", "afternoon", "afternoon", "evening", "evening", "night", "night"]


# ---------------------------------------------------------------- the dated history

def test_the_dated_history_is_saved_and_read_back():
    bs = BehaviorSystem()
    bs.track_activity("reading", at=MONDAY.replace(hour=9), hour=9)
    bs.track_activity("journaling", at=MONDAY.replace(hour=9, minute=20), hour=9)
    # Her local hour is her own: a persona in another timezone than the world clock's.
    bs.track_activity("yoga", at=MONDAY.replace(hour=18), hour=19)
    bs.track_activity("making tea", at=MONDAY.replace(hour=20))   # no hour given: the instant's own

    back = BehaviorSystem.from_dict(json.loads(json.dumps(bs.to_dict())))

    assert back.activity_log == [
        ("reading", MONDAY.replace(hour=9), 9),
        ("journaling", MONDAY.replace(hour=9, minute=20), 9),
        ("yoga", MONDAY.replace(hour=18), 19),
        ("making tea", MONDAY.replace(hour=20), 20),
    ]
    assert back._activity_history == ["reading", "journaling", "yoga", "making tea"]
    back.activity_log.clear()   # a reader's copy: the history itself is untouched
    assert len(back.activity_log) == 4


def test_an_old_undated_history_still_loads():
    """The 0.4.0 row: no dated history, the activity history a flat list of names."""
    old = {
        "routines": json.dumps([{"name": "reading", "activities": ["reading"], "consistency_streak": 4,
                                 "comfort_level": 0.34, "staleness": 0.0}]),
        "creative_portfolio": "[]", "possessions": "[]", "neighborhood": "[]",
        "activity_history": json.dumps(["reading"] * 5 + ["yoga"]),
    }
    bs = BehaviorSystem.from_dict(old)
    assert bs._activity_history == ["reading"] * 5 + ["yoga"]
    assert bs._routines["reading"].comfort_level == 0.34
    assert bs.activity_log == []
    # No dated history, no habit: the planner draws exactly as before.
    assert bs.habit_factors(MONDAY) == {}


def test_a_damaged_dated_history_loads_empty():
    bs = BehaviorSystem.from_dict({"activity_log": "not json", "activity_history": "[]"})
    assert bs.activity_log == []
    assert BehaviorSystem.from_dict({"activity_log": "5"}).activity_log == []   # JSON, but not a list
    bs = BehaviorSystem.from_dict({"activity_log": json.dumps([["reading", "not a date", 9], ["yoga"], 7,
                                                               [["a", "list"], MONDAY.isoformat(), 8],
                                                               ["tea", MONDAY.isoformat(), 8]])})
    assert bs.activity_log == [("tea", MONDAY, 8)]


OLD_BEHAVIOR_TABLE = """
    CREATE TABLE life_behavior_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        routines TEXT DEFAULT '{}',
        creative_portfolio TEXT DEFAULT '[]',
        possessions TEXT DEFAULT '[]',
        neighborhood TEXT DEFAULT '[]',
        activity_history TEXT DEFAULT '[]'
    )
"""


def test_an_old_life_db_loads_and_then_keeps_a_dated_history(tmp_path):
    db = tmp_path / "old.db"
    with contextlib.closing(sqlite3.connect(db)) as conn:
        conn.execute(OLD_BEHAVIOR_TABLE)
        conn.execute(
            "INSERT INTO life_behavior_state (id, routines, creative_portfolio, possessions, neighborhood, activity_history)"
            " VALUES (1, '[]', '[]', '[]', '[]', ?)", (json.dumps(["reading", "yoga", "reading"]),))
        conn.commit()
    clock = ScriptedClock(MONDAY.replace(hour=9))

    svc = _service(db, WorldEnvironment(now=clock))   # its schema setup adds the new column to the old table
    svc._load_state()                                 # what start() loads (start() also spawns the scheduler)
    assert svc._behavior._activity_history == ["reading", "yoga", "reading"]
    assert svc._behavior.activity_log == []

    svc._behavior.track_activity("journaling", at=clock(), hour=9)
    svc._save_behavior()
    again = _service(db, WorldEnvironment(now=clock))
    again._load_state()
    assert again._behavior.activity_log == [("journaling", MONDAY.replace(hour=9), 9)]
    assert again._behavior._activity_history == ["reading", "yoga", "reading", "journaling"]


def test_the_history_keeps_four_weeks():
    bs = BehaviorSystem()
    for day in range(40):
        bs.track_activity("reading", at=MONDAY + timedelta(days=day), hour=9)
    last = MONDAY + timedelta(days=39)
    ages = [(last - at).days for _, at, _ in bs.activity_log]
    assert max(ages) == HISTORY_DAYS
    assert len(bs.activity_log) == HISTORY_DAYS + 1


def test_the_history_is_capped_at_four_weeks_of_twenty_minute_ticks():
    bs = BehaviorSystem()
    for i in range(2100):   # faster than her 20-minute tick: 2100 entries inside 15 days
        bs.track_activity("reading", at=MONDAY + timedelta(minutes=10 * i), hour=9)
    assert len(bs.activity_log) == HISTORY_CAP
    assert bs.activity_log[-1][1] == MONDAY + timedelta(minutes=10 * 2099)   # the newest are kept


def test_an_undated_activity_is_not_in_the_dated_history():
    bs = BehaviorSystem()
    bs.track_activity("reading")
    assert bs._activity_history == ["reading"]
    assert bs.activity_log == []


# ---------------------------------------------------------------- the drift rule

def _lived(bs, counts, at, hour=9):
    for name, n in counts.items():
        for _ in range(n):
            bs.track_activity(name, at=at, hour=hour)


def test_comfort_rises_to_its_peak_then_staleness_takes_the_pull_away():
    bs = BehaviorSystem()
    now = MONDAY.replace(hour=12)
    # 200 ticks of this morning, all lived now (no decay): shares 15%, 30%, 45%, 7.5%, 2.5%.
    _lived(bs, {"journaling": 30, "reading": 60, "puzzles and games": 90, "yoga": 15, "making tea": 5}, now)

    morning = bs.habit_factors(now)["morning"]
    assert morning["journaling"] == pytest.approx(_factor(1.0))         # at the peak: the full pull
    assert morning["reading"] == pytest.approx(_factor(0.0))            # twice the peak: neutral
    assert morning["puzzles and games"] == pytest.approx(_factor(-1.0))  # three times: fully stale
    assert morning["yoga"] == pytest.approx(_factor(0.5))
    assert morning["making tea"] == pytest.approx(_factor(0.025 / PEAK_SHARE))

    detail = {h["name"]: h for h in bs.habits(now) if h["band"] == "morning"}
    assert detail["journaling"]["comfort"] == pytest.approx(1.0)
    assert detail["journaling"]["staleness"] == pytest.approx(0.0)
    assert detail["reading"]["staleness"] == pytest.approx(1.0)
    assert detail["puzzles and games"]["staleness"] == pytest.approx(2.0)
    assert detail["yoga"]["comfort"] == pytest.approx(0.5)
    assert detail["puzzles and games"]["share"] == pytest.approx(0.45)


def test_what_she_did_half_a_week_ago_counts_half():
    bs = BehaviorSystem()
    now = MONDAY + timedelta(days=7)
    _lived(bs, {"reading": 100}, now)
    _lived(bs, {"journaling": 100}, now - timedelta(days=HALF_LIFE_DAYS))
    _lived(bs, {"yoga": 10}, now + timedelta(days=2))   # dated after `now` (a clock set back): counts as today
    detail = {h["name"]: h for h in bs.habits(now)}
    assert detail["reading"]["count"] == pytest.approx(100.0)
    assert detail["journaling"]["count"] == pytest.approx(50.0)
    assert detail["yoga"]["count"] == pytest.approx(10.0)
    assert detail["journaling"]["share"] == pytest.approx(50 / 160)


def test_a_new_life_has_no_habits_yet():
    bs = BehaviorSystem()
    now = MONDAY.replace(hour=10)
    bs.track_activity("reading", at=now, hour=9)   # one tick: a share of 100%, but no evidence
    assert bs.habit_factors(now)["morning"]["reading"] == pytest.approx(_factor(-1.0, 1 / FULL_EVIDENCE))
    bs = BehaviorSystem()
    _lived(bs, {"reading": 30}, now)               # half the evidence: half the pull
    assert bs.habit_factors(now)["morning"]["reading"] == pytest.approx(_factor(-1.0, 0.5))


def test_the_day_anchors_and_sleep_form_no_habit():
    bs = BehaviorSystem()
    now = MONDAY.replace(hour=12)
    _lived(bs, {"having breakfast": 100, "sleeping": 50, "reading": 30, "sketching ideas": 170}, now)
    morning = bs.habit_factors(now, exclude=NOT_HABIT_FORMING)["morning"]
    assert "having breakfast" not in morning and "sleeping" not in morning
    assert morning["reading"] == pytest.approx(_factor(1.0))   # 30 of her 200 free ticks: the peak
    assert NOT_HABIT_FORMING >= {"waking up", "having breakfast", "having lunch", "having dinner",
                                 "getting ready for bed", "working", "commuting", "sleeping", "napping"}


# ---------------------------------------------------------------- the planner

ACTIVITIES = ActivityEngine().get_all_activities()


def _record_draws(monkeypatch):
    """Every slot draw: its candidates before the cut, the six it kept, their weights without and with the habit."""
    real = daily_planner._slot_draw
    draws = []

    def spy(candidates, habit):
        before = list(candidates)
        top, weights = real(candidates, habit)
        draws.append({"before": before, "top": list(top), "weights": list(weights),
                      "base": list(real(list(before), None)[1]), "habit": habit})
        return top, weights

    monkeypatch.setattr(daily_planner, "_slot_draw", spy)
    return draws


def _shares(top, weights):
    total = sum(weights)
    out = defaultdict(float)
    for (name, _, _), w in zip(top, weights):
        out[name] += w / total
    return out


def _plan(planner, habits=None):
    plan = planner.generate_daily_plan(goals=[], weather=Weather.CLOUDY, available_activities=ACTIVITIES,
                                       recent_activity_names=[], habits=habits)
    return [(s.hour, s.activity_name) for s in plan.slots]


def test_without_habits_the_planner_draws_exactly_as_before():
    def seeded(**kw):
        random.seed(11)
        planner = DailyPlanner(occupation="", interests=[])
        return planner.generate_daily_plan(goals=[], weather=Weather.CLOUDY, available_activities=ACTIVITIES,
                                           recent_activity_names=[], **kw)

    base = [(s.hour, s.activity_name) for s in seeded().slots]
    assert [(s.hour, s.activity_name) for s in seeded(habits=None).slots] == base
    assert [(s.hour, s.activity_name) for s in seeded(habits={}).slots] == base
    neutral = {"morning": {"reading": 1.0}, "afternoon": {"reading": 1.0}, "evening": {"reading": 1.0}}
    assert [(s.hour, s.activity_name) for s in seeded(habits=neutral).slots] == base


@pytest.mark.parametrize("is_ai", [False, True], ids=["human", "ai"])
def test_a_habit_reweights_a_slots_own_candidates_within_the_bound(monkeypatch, is_ai):
    draws = _record_draws(monkeypatch)
    strong = {"reading": MAX_RATIO ** 0.5, "puzzles and games": MAX_RATIO ** -0.5, "daydreaming": MAX_RATIO ** 0.5,
              "listening to music": MAX_RATIO ** -0.5}
    habits = {"morning": strong, "afternoon": strong, "evening": strong}
    random.seed(3)
    for _ in range(20):
        _plan(DailyPlanner(occupation="", interests=[], is_ai=is_ai), habits=habits)

    moved = 0
    for d in draws:
        # The cut is the planner's own: the six best by score, whatever the habit.
        assert d["top"] == sorted(d["before"], key=lambda c: c[1], reverse=True)[:6]
        base, weighted = _shares(d["top"], d["base"]), _shares(d["top"], d["weights"])
        for name, p in base.items():
            ratio = weighted[name] / p
            assert 1 / MAX_RATIO - 1e-9 <= ratio <= MAX_RATIO + 1e-9, (name, ratio)
            moved += abs(ratio - 1) > 0.01
        for name in ("reading", "daydreaming"):   # favoured: up whenever the draw holds a less favoured one
            if name in base and any(strong.get(n, 1.0) < strong[name] for n in base):
                assert weighted[name] > base[name]
    assert d["habit"] is strong
    assert moved > 20


# ---------------------------------------------------------------- the simulated week (acceptance)

REPEATED = "journaling"            # two of her own ticks every morning: it becomes a habit
OVERDONE = "puzzles and games"     # six of her own ticks every morning: too much
VARIETY = ["listening to music", "learning something new", "sketching ideas", "reading", "meditating",
           "making tea", "yoga", "tending to plants"]   # her other morning picks, one after the other
#: Her own ticks of the morning (the plan's slot is each hour's first tick): who fills each 20-minute tick.
MORNING_OWN = {(7, 20): OVERDONE, (7, 40): OVERDONE, (8, 20): REPEATED, (8, 40): OVERDONE, (9, 20): OVERDONE,
               (9, 40): None, (10, 20): REPEATED, (10, 40): OVERDONE, (11, 20): None, (11, 40): OVERDONE}
WEEKS = 30
SEED_BASE = 1000   # the weeks are seeded: the run is the same every time
#: No activity takes more than a quarter of a part of her day's planned slots over a week.
VARIETY_CAP = 0.25


#: The day's anchors for the default schedule (wake 7, bed 23, no work): waking up, breakfast, lunch, dinner, bed.
ANCHOR_HOURS = {7, 8, 12, 19, 22}


def _next_variety(state):
    state["i"] = (state["i"] + 1) % len(VARIETY)
    return VARIETY[state["i"]]


def _simulate_weeks(monkeypatch):
    """WEEKS independent weeks of her life on the fake clock. Each day: the plan is drawn at dawn with the habits of
    the dated history so far, then she lives it -- a planned slot fills its hour's first tick (its whole hour after
    noon), the morning's other ticks are her own (MORNING_OWN), and the anchors are lived too (no habit forms on them)."""
    draws = _record_draws(monkeypatch)
    planned = defaultdict(lambda: defaultdict(int))   # band -> activity -> planned slots, over every week
    per_day = []                                      # (week, day index, band, draw)
    for week in range(WEEKS):
        random.seed(SEED_BASE + week)
        bs = BehaviorSystem()
        planner = DailyPlanner(occupation="", interests=[])
        state = {"i": -1}
        for d in range(7):
            day = MONDAY + timedelta(days=d)
            start = len(draws)
            plan = planner.generate_daily_plan(goals=[], weather=Weather.CLOUDY, available_activities=ACTIVITIES,
                                               recent_activity_names=[],
                                               habits=bs.habit_factors(day.replace(hour=6), exclude=NOT_HABIT_FORMING))
            free = sorted((s for s in plan.slots if s.hour not in ANCHOR_HOURS), key=lambda s: s.hour)
            assert len(free) == len(draws) - start == 11   # one draw per free slot, in hour order
            for s, draw in zip(free, draws[start:]):
                per_day.append((week, d, habit_band(s.hour), draw))
                planned[habit_band(s.hour)][s.activity_name] += 1
            by_hour = {s.hour: s.activity_name for s in plan.slots}
            for hour in range(7, 23):
                for minute in (0, 20, 40):
                    name = by_hour.get(hour)
                    if hour < 12 and minute:
                        name = MORNING_OWN[(hour, minute)] or _next_variety(state)
                    if name:
                        bs.track_activity(name, at=day.replace(hour=hour, minute=minute), hour=hour)
    return per_day, planned


def _ratio(per_day, day, band, name):
    """Her chance of `name` over that day's draws with her habits, over the same draws without them."""
    hab = base = 0.0
    for _, d, b, draw in per_day:
        if d == day and b == band:
            hab += _shares(draw["top"], draw["weights"]).get(name, 0.0)
            base += _shares(draw["top"], draw["base"]).get(name, 0.0)
    return hab / base, base


def test_a_simulated_week_drifts_toward_what_she_repeats_and_away_from_what_she_overdoes(monkeypatch):
    per_day, planned = _simulate_weeks(monkeypatch)

    # Day one: no history, no habit -- every draw is the planner's own.
    for _, d, _, draw in per_day:
        if d == 0:
            assert draw["weights"] == draw["base"]

    # The bound holds in every draw of every day, every part of the day.
    for _, _, _, draw in per_day:
        base, weighted = _shares(draw["top"], draw["base"]), _shares(draw["top"], draw["weights"])
        for name, p in base.items():
            assert 1 / MAX_RATIO - 1e-9 <= weighted[name] / p <= MAX_RATIO + 1e-9

    # By the end of the week her mornings lean toward the habit and away from the overdone one, and the lean grew.
    repeated = [_ratio(per_day, d, "morning", REPEATED)[0] for d in range(7)]
    overdone = [_ratio(per_day, d, "morning", OVERDONE)[0] for d in range(7)]
    assert repeated[0] == pytest.approx(1.0) and overdone[0] == pytest.approx(1.0)
    assert repeated[6] > 1.05
    assert overdone[6] < 0.90
    assert 1.0 < repeated[1] < repeated[6]
    assert overdone[6] < overdone[1] < 1.0

    # And her days keep their variety: no activity takes over a part of her day.
    for band, counts in planned.items():
        total = sum(counts.values())
        assert max(counts.values()) / total <= VARIETY_CAP, (band, max(counts.items(), key=lambda kv: kv[1]))


# ---------------------------------------------------------------- the service

def test_a_lived_tick_is_dated_on_the_world_clock_and_her_hour(tmp_path, monkeypatch):
    clock = ScriptedClock(MONDAY.replace(hour=10))
    svc = _service(tmp_path / "tick.db", WorldEnvironment(now=clock))
    monkeypatch.setattr(svc, "persona_local_hour", lambda: 15)   # her local hour, not the world clock's
    monkeypatch.setattr(svc._energy, "should_sleep", lambda **kw: False)
    monkeypatch.setattr(svc._energy, "should_rest", lambda: False)
    monkeypatch.setattr(svc._desire_system, "should_do_intimate_activity", lambda *a, **k: False)

    svc._on_activity_tick()

    done = svc._recent_activities[0].activity_name
    assert svc._behavior.activity_log[-1] == (done, MONDAY.replace(hour=10), 15)


def _habit_history(bs):
    # Yesterday morning she journaled a lot; five days ago she read a lot (ages differ, so the instant matters); her
    # breakfasts form no habit (so leaving the anchors out matters too).
    _lived(bs, {"journaling": 40, "sketching ideas": 20, "having breakfast": 30}, MONDAY - timedelta(hours=20))
    _lived(bs, {"reading": 60}, MONDAY - timedelta(days=5))


def test_the_daily_plan_is_drawn_with_her_habits_on_the_world_clock(tmp_path, monkeypatch):
    clock = ScriptedClock(MONDAY.replace(hour=6))
    svc = _service(tmp_path / "plan.db", WorldEnvironment(now=clock))
    _habit_history(svc._behavior)
    seen = []
    real = svc._daily_planner.generate_daily_plan
    monkeypatch.setattr(svc._daily_planner, "generate_daily_plan", lambda **kw: seen.append(kw) or real(**kw))
    monkeypatch.setattr(svc._daily_planner, "needs_new_plan", lambda: True)

    svc._on_plan_tick()

    expected = svc._behavior.habit_factors(clock(), exclude=NOT_HABIT_FORMING)
    assert expected["morning"]["journaling"] != pytest.approx(1.0)
    assert [kw["habits"] for kw in seen] == [expected]


def test_a_catch_up_slot_of_a_physical_activity_has_a_category(tmp_path):
    """``_categorize_activity`` returned ``ActivityCategory.PHYSICAL``, which does not exist: a catch-up whose gap
    held a run, yoga or the gym raised AttributeError and lost the whole catch-up."""
    from aura_life.models import ActivityCategory
    svc = _service(tmp_path / "cat.db", WorldEnvironment(now=ScriptedClock(MONDAY)))
    assert svc._categorize_activity("going for a run") is ActivityCategory.EXPLORATION
    assert svc._categorize_activity("yoga") is ActivityCategory.REST
    assert svc._categorize_activity("gentle_walk") is ActivityCategory.EXPLORATION


def _frozen(instant: datetime) -> type:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz is None else instant.replace(tzinfo=tz)

    return FrozenDateTime


def test_a_catch_up_plan_is_drawn_with_her_habits_but_its_hours_train_none(tmp_path, monkeypatch):
    # The catch-up judges its gap on the host clock: freeze it mid-afternoon so the gap always holds planned slots.
    monkeypatch.setattr(importlib.import_module("aura_life.life_service"), "datetime", _frozen(datetime(2031, 3, 10, 15)))
    clock = ScriptedClock(MONDAY.replace(hour=6))
    svc = _service(tmp_path / "catchup.db", WorldEnvironment(now=clock))
    _habit_history(svc._behavior)
    dated = list(svc._behavior.activity_log)
    seen = []
    real = svc._daily_planner.generate_daily_plan
    monkeypatch.setattr(svc._daily_planner, "generate_daily_plan", lambda **kw: seen.append(kw) or real(**kw))

    result = svc.catch_up_from_downtime(10)

    assert result["activities_generated"] > 0
    expected = svc._behavior.habit_factors(clock(), exclude=NOT_HABIT_FORMING)
    assert seen and all(kw["habits"] == expected for kw in seen)
    # The routines still count the hours she did not live, as before; her habits learn nothing from them.
    replayed = result["activities"]
    assert svc._behavior._activity_history[-len(replayed):] == replayed
    assert svc._behavior.activity_log == dated
