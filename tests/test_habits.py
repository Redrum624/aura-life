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

#: The bound: a habit multiplies an activity's score in a choice by at most x1.5 up or /1.5 down (before the cut, so a
#: habit can bring an activity into the planner's six or take one out).
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
    return MAX_RATIO ** (confidence * signal)


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
    # Kept: four weeks before the previous tick (so one tick far ahead cannot wipe it); counted: four weeks before now.
    assert max(ages) == HISTORY_DAYS + 1
    assert len(bs.activity_log) == HISTORY_DAYS + 2
    counted = sum(0.5 ** (age / HALF_LIFE_DAYS) for age in range(HISTORY_DAYS + 1))
    assert bs.habits(last)[0]["count"] == pytest.approx(counted)


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
    _lived(bs, {"yoga": 10}, now + timedelta(days=2))   # dated after `now` (a clock set back): not counted at all
    detail = {h["name"]: h for h in bs.habits(now)}
    assert detail["reading"]["count"] == pytest.approx(100.0)
    assert detail["journaling"]["count"] == pytest.approx(50.0)
    assert "yoga" not in detail
    assert detail["journaling"]["share"] == pytest.approx(50 / 150)


def test_one_tick_with_the_clock_far_ahead_neither_wipes_her_history_nor_counts():
    bs = BehaviorSystem()
    for i in range(14 * 72):   # two weeks of her 20-minute tick, her mornings
        bs.track_activity("reading" if i % 3 else "journaling", at=MONDAY + timedelta(minutes=20 * i), hour=9)
    last = MONDAY + timedelta(minutes=20 * (14 * 72 - 1))
    before = bs.habit_factors(last)
    bs.track_activity("stargazing", at=last + timedelta(days=400), hour=9)   # a bad clock, for one tick
    bs.track_activity("reading", at=last + timedelta(minutes=20), hour=9)    # the clock back
    assert len(bs.activity_log) == 14 * 72 + 2
    after = bs.habit_factors(last + timedelta(minutes=20))
    assert "stargazing" not in after["morning"]
    assert after["morning"]["reading"] == pytest.approx(before["morning"]["reading"], abs=0.01)
    # A real absence of more than four weeks still prunes, by age.
    later = last + timedelta(days=30)
    bs.track_activity("yoga", at=later, hour=9)
    bs.track_activity("yoga", at=later + timedelta(minutes=20), hour=9)
    assert [name for name, _, _ in bs.activity_log] == ["stargazing", "yoga", "yoga"]
    assert set(bs.habit_factors(later + timedelta(minutes=20))["morning"]) == {"yoga"}


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
        base_top, base = real(list(before), None)
        draws.append({"before": before, "top": list(top), "weights": list(weights),
                      "base_top": list(base_top), "base": list(base), "habit": habit})
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


def test_a_habit_can_bring_an_activity_into_the_six_or_take_one_out():
    tied = [(f"pastime {i}", 1.0, "routine") for i in range(8)]   # eight tied: list order decides the six
    top, _ = daily_planner._slot_draw(list(tied), None)
    assert [n for n, _, _ in top] == [f"pastime {i}" for i in range(6)]
    top, weights = daily_planner._slot_draw(list(tied), {"pastime 7": MAX_RATIO, "pastime 0": 1 / MAX_RATIO})
    names = [n for n, _, _ in top]
    assert names[0] == "pastime 7" and "pastime 0" not in names   # in on its habit, out on its staleness
    assert weights[0] == pytest.approx(MAX_RATIO / (MAX_RATIO + 5))


#: Every part of her day its own habits: a slot drawn with another part's would score differently.
BAND_HABITS = {
    "morning": {"reading": MAX_RATIO, "puzzles and games": 1 / MAX_RATIO, "yoga": MAX_RATIO},
    "afternoon": {"daydreaming": MAX_RATIO, "reading": 1 / MAX_RATIO, "relaxing": MAX_RATIO},
    "evening": {"creating a playlist": 1 / MAX_RATIO, "reading": MAX_RATIO, "stretching": MAX_RATIO},
}


@pytest.mark.parametrize("is_ai", [False, True], ids=["human", "ai"])
def test_each_slot_draws_with_its_own_part_of_the_day_within_the_bound(monkeypatch, is_ai):
    draws = _record_draws(monkeypatch)
    moved = 0
    for seed in range(10):
        random.seed(seed)
        start = len(draws)
        plan = DailyPlanner(occupation="", interests=[], is_ai=is_ai).generate_daily_plan(
            goals=[], weather=Weather.CLOUDY, available_activities=ACTIVITIES, recent_activity_names=[],
            habits=BAND_HABITS)
        # The slots that drew, in the order they were drawn: the free hours of a human day, the AI's daytime hours,
        # less any that found no candidate at all (the planner's own "free time" fallback, which draws nothing).
        drawing = set(range(8, 22)) if is_ai else {h for h in range(24) if h not in ANCHOR_HOURS}
        hours = sorted(s.hour for s in plan.slots if s.hour in drawing and s.reason != "free time")
        assert len(draws) - start == len(hours)
        for hour, d in zip(hours, draws[start:]):
            own = BAND_HABITS[habit_band(hour)]
            assert d["habit"] is own, hour
            base_score = {(n, why): s for n, s, why in d["before"]}
            for n, s, why in d["top"]:
                factor = s / base_score[(n, why)]
                assert factor == pytest.approx(own.get(n, 1.0))      # its own part of the day's factor
                assert 1 / MAX_RATIO - 1e-9 <= factor <= MAX_RATIO + 1e-9
            # The cut comes after the habit: the six best of the scaled scores.
            scaled = sorted(((n, s * own.get(n, 1.0), why) for n, s, why in d["before"]), key=lambda c: c[1],
                            reverse=True)
            assert d["top"] == scaled[:6]
            moved += [n for n, _, _ in d["top"]] != [n for n, _, _ in d["base_top"]]
    assert moved >= 10   # habits do change which six she chooses from


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
    """Her chance of `name` over that day's draws with her habits, over the same draws without them (each with its
    own six: the habit's and the planner's)."""
    hab = base = 0.0
    for _, d, b, draw in per_day:
        if d == day and b == band:
            hab += _shares(draw["top"], draw["weights"]).get(name, 0.0)
            base += _shares(draw["base_top"], draw["base"]).get(name, 0.0)
    return hab / base, base


def test_a_simulated_week_drifts_toward_what_she_repeats_and_away_from_what_she_overdoes(monkeypatch):
    per_day, planned = _simulate_weeks(monkeypatch)

    # Day one: no history, no habit -- every draw is the planner's own.
    for _, d, _, draw in per_day:
        if d == 0:
            assert draw["top"] == draw["base_top"] and draw["weights"] == draw["base"]

    # The bound holds in every draw of every day, every part of the day: no score moved past x1.5 or /1.5.
    for _, _, _, draw in per_day:
        base_score = {(n, why): s for n, s, why in draw["before"]}
        for n, s, why in draw["top"]:
            assert 1 / MAX_RATIO - 1e-9 <= s / base_score[(n, why)] <= MAX_RATIO + 1e-9

    # By the end of the week her mornings lean toward the habit and away from the overdone one, and the lean grew.
    repeated = [_ratio(per_day, d, "morning", REPEATED)[0] for d in range(7)]
    overdone = [_ratio(per_day, d, "morning", OVERDONE)[0] for d in range(7)]
    assert repeated[0] == pytest.approx(1.0) and overdone[0] == pytest.approx(1.0)
    assert repeated[6] > 1.05
    assert overdone[6] < 0.90
    assert 1.0 < repeated[1] < repeated[6]
    # Its score tied with the others' at the cut, the overdone one leaves her six as soon as its pull turns negative.
    assert overdone[6] <= overdone[1] < 1.0

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


# ---------------------------------------------------------------- her own picks between slots

def test_her_own_picks_between_slots_lean_the_same_way_before_their_cut(monkeypatch):
    from aura_life.activities import activity_engine
    from aura_life.models import TimeOfDay
    seen = []
    real = random.choices
    monkeypatch.setattr(activity_engine.random, "choices",
                        lambda pop, weights: seen.append((list(pop), list(weights))) or real(pop, weights=weights))
    engine = ActivityEngine()

    def pick(habit=None):
        engine._recent_activities = []
        engine.select_activity(energy_level=0.8, time_of_day=TimeOfDay.MORNING, weather=Weather.CLOUDY,
                               current_location="home", habit=habit)
        return seen[-1]

    base_pop, _ = pick()
    assert len(base_pop) == 5
    outside = next(a for a in engine.get_all_activities() if a not in base_pop and TimeOfDay.MORNING in a.preferred_times
                   and "home" in a.suitable_locations and a.min_energy <= 0.8)
    pop, weights = pick({outside.name: MAX_RATIO, base_pop[0].name: 1 / MAX_RATIO})
    assert pop[0] is outside                     # her habit brought it into the five
    assert base_pop[0] not in pop                # the stale one went out
    assert pick({})[0] == base_pop               # no habit: the 0.4.0 five


def test_her_own_picks_use_the_habits_of_her_hour(tmp_path, monkeypatch):
    clock = ScriptedClock(MONDAY.replace(hour=10))
    svc = _service(tmp_path / "adhoc.db", WorldEnvironment(now=clock))
    _lived(svc._behavior, {"daydreaming": 40, "people watching": 20}, MONDAY - timedelta(hours=20), hour=15)
    _lived(svc._behavior, {"journaling": 40, "reading": 20}, MONDAY - timedelta(hours=20), hour=9)
    monkeypatch.setattr(svc, "persona_local_hour", lambda: 15)   # her afternoon
    monkeypatch.setattr(svc._energy, "should_sleep", lambda **kw: False)
    monkeypatch.setattr(svc._energy, "should_rest", lambda: False)
    monkeypatch.setattr(svc._desire_system, "should_do_intimate_activity", lambda *a, **k: False)
    seen = []
    real = svc._activity_engine.select_activity
    monkeypatch.setattr(svc._activity_engine, "select_activity", lambda **kw: seen.append(kw) or real(**kw))
    expected = svc._habit_factors()["afternoon"]   # before the tick dates what she picks

    svc._on_activity_tick()   # no plan yet: her own pick

    assert len(seen) == 1
    assert seen[0]["habit"] == expected
    assert "daydreaming" in seen[0]["habit"] and "journaling" not in seen[0]["habit"]


# ---------------------------------------------------------------- what the prompt says about her habits

def test_her_patterns_text_says_what_the_planner_draws_with(tmp_path):
    clock = ScriptedClock(MONDAY.replace(hour=12))
    svc = _service(tmp_path / "ctx.db", WorldEnvironment(now=clock))
    for day in range(1, 8):   # a week of mornings, 20 free ticks each: puzzles 40% (overdone), journaling 15%
        _lived(svc._behavior, {"puzzles and games": 8, "journaling": 3, "reading": 2, "sketching ideas": 2, "yoga": 2,
                               "making tea": 2, "meditating": 1}, MONDAY.replace(hour=9) - timedelta(days=day), hour=9)
    factors = svc._habit_factors()["morning"]
    assert factors["puzzles and games"] < 1.0 < factors["journaling"]   # the planner pushes one away, pulls the other

    text = svc._context_builder._build_behavior_section()

    assert "Puzzles and games has become a comforting" not in text
    assert "- You've had a lot of puzzles and games lately" in text
    assert "- Journaling has become a comforting part of your mornings" in text


def test_no_dated_history_no_habit_in_her_patterns_text(tmp_path):
    svc = _service(tmp_path / "ctx0.db", WorldEnvironment(now=ScriptedClock(MONDAY)))
    for _ in range(40):
        svc._behavior.track_activity("reading")   # undated: the old routine counters only
    assert "comforting" not in svc._context_builder._build_behavior_section()
