"""Task 29: money on the hours scale.

The controller's runs of 2026-11-13 found her balance going from about 1,200
to 0 in three simulated days at production cadence, and to 54-1,092 at the
15-minute cadence: the discretionary spend was a chance per TICK, so the tick
interval set how much she spent. And the default balance (1,200 against
1,850 of monthly expenses) already sat in the band where LifeService holds
"money worries" (``financial_stress() >= 0.4``), so every new persona was
worried from her first tick.

The acceptance is measured on :class:`FinanceSystem` alone on a simulated
clock (a month is thousands of ticks of a tiny object), with her activities
fed from one day taken once from a LifeService run
(``fixtures/finance_day_activities.json``, repeated every day).
"""

import json
import pathlib
import random
import sqlite3
from datetime import datetime, timedelta

import pytest

from aura_life import hooks
from aura_life.life_service import LifeService
from aura_life.models import FinancialState
from aura_life.money.finance_system import STARTING_RUNWAY, FinanceSystem
from aura_life.world import WorldEnvironment
from sim_helpers import DEFAULT_START

#: LifeService._on_energy_tick holds "money worries" while
#: FinanceSystem.financial_stress() is at or above this (Task 15).
WORRIED = 0.4

#: The production energy tick (LifeScheduler.TICK_INTERVAL_MINUTES["energy"],
#: where LifeService ticks the finance engine) and the 15-minute cadence of
#: the 2026-09-25 harness.
PRODUCTION_MINUTES = 5
HARNESS_MINUTES = 15

DAYS = 30
SEEDS = (1, 2, 3)

#: One day of her activities, minutes after DEFAULT_START (the fixture's
#: "source" says which run).
DAY = json.loads((pathlib.Path(__file__).parent / "fixtures" / "finance_day_activities.json")
                 .read_text(encoding="utf-8"))
assert DAY["start"] == DEFAULT_START.isoformat()


def _month(habit: float, seed: int, step_minutes: int, days: int = DAYS, start: datetime = DEFAULT_START,
           balance=None):
    """Drive a default-finances FinanceSystem for ``days`` from ``start``:
    a tick every ``step_minutes`` on the world clock, the fixture's activities
    at their own times. Returns (start balance, end balance, discretionary
    total, activity total, share of ticks in the worried band). ``balance``
    replaces the default starting balance."""
    fin = FinanceSystem(rng=random.Random(seed), now=start)
    fin.state.spending_habit = habit
    if balance is not None:
        fin.state.balance = balance
    spent = {"tick": 0.0, "activity": 0.0}
    source = {"now": None}
    original = fin._spend

    def spend(amount, label):
        spent[source["now"]] += amount
        original(amount, label)

    fin._spend = spend
    events = [(start + timedelta(minutes=step_minutes * i), "tick", None)
              for i in range(1, days * 24 * 60 // step_minutes + 1)]
    events += [(start + timedelta(days=day, minutes=minute), "activity", name)
               for day in range(days) for minute, name in DAY["activities"]
               if day * 24 * 60 + minute <= days * 24 * 60]
    events.sort(key=lambda e: (e[0], e[1] == "tick"))
    start_balance = fin.state.balance
    ticks = worried = 0
    for when, kind, name in events:
        source["now"] = kind
        if kind == "tick":
            fin.tick(now=when)
            ticks += 1
            worried += fin.financial_stress() >= WORRIED
        else:
            fin.on_activity(name, now=when)
    return start_balance, fin.state.balance, spent["tick"], spent["activity"], worried / ticks


def _surplus() -> float:
    state = FinancialState()
    return state.monthly_income - state.monthly_expenses


# ----------------------------------------------------------------------
# (a) the tick interval does not set how much she spends
# ----------------------------------------------------------------------

#: Money no object: a balance no month of her spending reaches the bottom of,
#: so what the tick interval does to her spending is not hidden by what she
#: can afford (with the default balance a per-tick chance spent everything at
#: either cadence, and the two totals matched). Test value: a hundred months
#: of the default income.
AMPLE = 100 * FinancialState().monthly_income


#: The tick intervals compared with the production one: the harness's, and
#: ticks of one and of two hours (fix round 1, T29-3: at 5 and 15 minutes
#: every hour is crossed by exactly one tick, so one draw per tick entering an
#: hour passed; a two-hour tick crosses two).
OTHER_MINUTES = (HARNESS_MINUTES, 60, 120)


@pytest.mark.parametrize("balance", (None, AMPLE), ids=("default balance", "ample balance"))
@pytest.mark.parametrize("seed", SEEDS)
def test_a_month_s_discretionary_spending_does_not_follow_the_tick_interval(seed, balance):
    *_, at_production, _, _ = _month(0.5, seed, PRODUCTION_MINUTES, balance=balance)
    assert at_production > 0
    for minutes in OTHER_MINUTES:
        *_, at_other, _, _ = _month(0.5, seed, minutes, balance=balance)
        assert abs(at_production - at_other) / at_production < 0.10, (minutes, at_production, at_other)


class CountingRandom(random.Random):
    """A seeded stream that counts its random() calls: FinanceSystem calls
    it once per world hour drawn, so the count is the number of hours drawn.
    getrandbits is defined too, so that rng.choice (a purchase's label) draws
    from it and not from random(): a subclass of random.Random that defines
    only random() has its choice() call random()."""

    def __init__(self, seed=1):
        super().__init__(seed)
        self.draws = 0

    def random(self):
        self.draws += 1
        return super().random()

    def getrandbits(self, k):
        return super().getrandbits(k)


T0 = DEFAULT_START.replace(minute=10)


def _counted(now=T0, rng=None):
    fin = FinanceSystem(rng=rng or CountingRandom(), now=now)
    fin.state.balance = AMPLE
    return fin


def test_one_tick_draws_every_hour_it_crosses():
    """Fix round 1, T29-3 (i): a tick six hours after the last draws the six
    hours, not one."""
    fin = _counted()
    fin.tick(now=T0)
    drawn = fin._rng.draws
    fin.tick(now=T0 + timedelta(hours=6))
    assert fin._rng.draws - drawn == 6


def test_a_backdated_tick_draws_nothing_and_no_hour_is_drawn_twice():
    """Fix round 1, T29-3 (ii): a catch-up tick behind the last one drawn
    neither draws nor moves the drawn hour back."""
    fin = _counted()
    fin.tick(now=T0)
    fin.tick(now=T0 + timedelta(hours=5))
    drawn = fin._rng.draws
    fin.tick(now=T0 + timedelta(hours=2))
    assert fin._rng.draws == drawn
    fin.tick(now=T0 + timedelta(hours=6))
    assert fin._rng.draws == drawn + 1


def test_the_hours_her_spending_was_off_are_not_drawn_when_it_is_back_on():
    """Fix round 1, T29-3 (iii): ten hours with spending disabled are not
    bought for when it is enabled again: the first tick back draws its own
    hour only."""
    fin = _counted()
    fin.tick(now=T0)
    fin.state.enabled = False
    for hours in range(1, 10):
        fin.tick(now=T0 + timedelta(hours=hours))
    fin.state.enabled = True
    drawn = fin._rng.draws
    fin.tick(now=T0 + timedelta(hours=10))
    assert fin._rng.draws - drawn == 1


def test_two_priced_activities_in_one_hour_are_both_paid_for():
    """Fix round 1, T29-3 (iv): an hour pays once for each activity, not once
    for the first priced one."""
    fin = FinanceSystem(rng=random.Random(1), now=DEFAULT_START)
    start = fin.state.balance
    fin.on_activity("online shopping", now=T0)
    after_shopping = fin.state.balance
    fin.on_activity("coffee", now=T0 + timedelta(minutes=20))
    assert start > after_shopping > fin.state.balance


def test_a_first_tick_draws_the_hour_it_falls_in():
    """Fix round 1, T29-2 (aura's tests/test_finance_system.py
    test_spending_habit_drives_discretionary): a new engine's first tick is a
    draw for its own world hour, so one tick with a sure chance buys once,
    and every hour from her first tick on is drawn exactly once."""

    class Sure(random.Random):
        def random(self):
            return 0.0

    state = FinancialState(balance=5000.0, monthly_income=2000.0, spending_habit=1.0,
                           last_payday=datetime(2026, 6, 1), last_expense_run=datetime(2026, 6, 1))
    fin = FinanceSystem(initial_state=state, rng=Sure(1))
    fin.tick(now=datetime(2026, 6, 20))
    assert fin.state.balance < 5000.0
    assert len(fin.state.recent_purchases) == 1
    fin.tick(now=datetime(2026, 6, 20, 0, 30))
    assert len(fin.state.recent_purchases) == 1


# ----------------------------------------------------------------------
# A reload: the hours she was away are drawn once, whatever the tick order
# (fix round 1, T29-1)
# ----------------------------------------------------------------------

#: The hours a host is down in these tests, and the backdated instants its
#: catch-up ticks (LifeService.catch_up_from_downtime ticks the engines at
#: backfilled slots of the gap; LifeService.start's first live tick may run
#: before or after it).
GAP_HOURS = 8
CATCH_UP_AT = (2, 5)


def _reloaded(saved: dict) -> FinanceSystem:
    fin = FinanceSystem.from_dict(dict(saved), rng=CountingRandom(), now=T0 + timedelta(hours=GAP_HOURS))
    fin.state.balance = AMPLE
    return fin


@pytest.mark.parametrize("live_first", (True, False), ids=("live tick first", "catch-up first"))
def test_a_reload_draws_the_hours_she_was_away_once_whatever_the_tick_order(live_first):
    fin = _counted()
    fin.tick(now=T0)
    again = _reloaded(fin.to_dict())
    live = [T0 + timedelta(hours=GAP_HOURS)]
    catch_up = [T0 + timedelta(hours=h) for h in CATCH_UP_AT]
    for when in (live + catch_up if live_first else catch_up + live):
        again.tick(now=when)
    assert again._rng.draws == GAP_HOURS


#: A host off over a month's end: her last tick before it, the first live tick
#: after it, and the catch-up's backdated slots on both sides of midnight.
MONTH_END_LAST = datetime(2026, 10, 31, 22, 10)
MONTH_END_LIVE = datetime(2026, 11, 1, 8, 10)
MONTH_END_CATCH_UP = (datetime(2026, 10, 31, 23, 40), datetime(2026, 11, 1, 3, 40))


@pytest.mark.parametrize("live_first", (True, False), ids=("live tick first", "catch-up first"))
def test_a_reload_over_a_month_s_end_pays_and_bills_her_once_whatever_the_tick_order(live_first):
    """A catch-up tick backdated into the month before the live tick's is not
    a new month. With the live tick first she was paid and billed three times
    for the one month (a month counted as new whenever it differed from the
    last payday's, in either direction, and the backdated tick moved the
    payday back)."""
    fin = FinanceSystem(rng=CountingRandom(), now=MONTH_END_LAST)
    fin.state.spending_habit = 0.0   # no purchases: only her pay and her bills move her money
    fin.tick(now=MONTH_END_LAST)
    again = FinanceSystem.from_dict(fin.to_dict(), rng=CountingRandom(), now=MONTH_END_LIVE)
    before = again.state.balance + again.state.savings
    order = (MONTH_END_LIVE,) + MONTH_END_CATCH_UP if live_first else MONTH_END_CATCH_UP + (MONTH_END_LIVE,)
    for when in order:
        again.tick(now=when)
    surplus = again.state.monthly_income - again.state.monthly_expenses
    assert again.state.balance + again.state.savings == pytest.approx(before + surplus)
    for marker in (again.state.last_payday, again.state.last_expense_run):
        assert (marker.year, marker.month) == (2026, 11)


def test_the_hour_her_purchases_are_drawn_to_is_saved_and_loaded(tmp_path, clock):
    """Through LifeService's save and load: a reloaded persona's first tick
    eight hours on draws the eight hours."""
    svc = _service(tmp_path, clock)
    svc._finance.tick(now=clock.instant)
    svc._save_financial_state()
    clock.instant += timedelta(hours=GAP_HOURS)
    again = _service(tmp_path, clock)
    again._load_state()
    again._finance._rng = CountingRandom()
    again._finance.state.balance = AMPLE
    again._finance.tick(now=clock.instant)
    assert again._finance._rng.draws == GAP_HOURS


# ----------------------------------------------------------------------
# A tick across whole months (fix round 1, T29-4)
# ----------------------------------------------------------------------

def test_a_tick_across_whole_months_draws_only_the_months_it_pays_for():
    """tick credits one month's pay and bills however many months it crosses
    (a process suspended past a month, a host off for one), so it draws the
    rest of the month of the last hour drawn and its own month up to its hour,
    not the whole months between, which nothing paid for."""
    last = datetime(2026, 10, 5, 10, 20)
    now = datetime(2027, 1, 3, 10, 40)
    fin = _counted(now=last)
    fin.tick(now=last)
    drawn = fin._rng.draws
    balance = fin.state.balance
    fin.tick(now=now)
    rest_of_october = (datetime(2026, 11, 1) - datetime(2026, 10, 5, 11)) // timedelta(hours=1)
    january_to_now = (datetime(2027, 1, 3, 10) - datetime(2027, 1, 1)) // timedelta(hours=1) + 1
    assert fin._rng.draws - drawn == rest_of_october + january_to_now
    # one month credited, as before
    surplus = fin.state.monthly_income - fin.state.monthly_expenses
    assert fin.state.balance <= balance + surplus


# ----------------------------------------------------------------------
# (b) the default habit about breaks even over a month
# ----------------------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_the_default_habit_about_breaks_even_over_a_month(seed):
    start, end, _, _, worried_share = _month(0.5, seed, PRODUCTION_MINUTES)
    assert abs(end - start) <= _surplus(), (start, end)
    assert worried_share < 0.10, worried_share


# ----------------------------------------------------------------------
# (c) a frugal persona saves, a spender overshoots and can run low
# ----------------------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_a_frugal_persona_saves_and_a_spender_ends_lower(seed):
    frugal_start, frugal_end, *_ = _month(0.1, seed, PRODUCTION_MINUTES)
    _, default_end, *_ = _month(0.5, seed, PRODUCTION_MINUTES)
    _, spender_end, *_ = _month(0.9, seed, PRODUCTION_MINUTES)
    assert frugal_end > frugal_start, (frugal_start, frugal_end)
    assert spender_end < default_end, (spender_end, default_end)


#: How long a spender takes to run into money worries from a new persona's
#: starting runway. The brief proposed 30 days (spec R12: a proposal); from
#: STRESS_RUNWAY_CEILING months of expenses a spender's first 26 days (to the
#: world's first payday, 1 November) reach the worried band in 15 of seeds
#: 1-50 and in none of seeds 1-3, her first 60 days in 41 of 50 (Task 29's
#: report): she runs low in her second month.
SPENDER_DAYS = 60


def test_a_spender_runs_into_money_worries():
    worried = [_month(0.9, seed, PRODUCTION_MINUTES, days=SPENDER_DAYS)[4] for seed in SEEDS]
    assert any(share > 0 for share in worried), worried


def test_a_month_s_spending_is_a_share_of_what_she_has_left_over():
    """Nothing left over after the bills: no discretionary spending at all."""
    fin = FinanceSystem(rng=random.Random(1), now=DEFAULT_START)
    fin.state.monthly_income = fin.state.monthly_expenses
    before = fin.state.balance
    for i in range(1, 7 * 24 * 12 + 1):
        fin.tick(now=DEFAULT_START + timedelta(minutes=5 * i))
    assert fin.state.balance == before


def test_an_activity_is_paid_for_once_in_its_hour():
    """The plan's slot governs every activity tick of its hour (Task 10), so
    an hour of online shopping is one purchase, however often the activity
    tick runs in it."""
    fin = FinanceSystem(rng=random.Random(1), now=DEFAULT_START)
    start = fin.state.balance
    hour = DEFAULT_START.replace(minute=0) + timedelta(hours=1)
    balances = []
    for minute in (0, 20, 40, 60):
        fin.on_activity("online shopping", now=hour + timedelta(minutes=minute))
        balances.append(fin.state.balance)
    assert balances[0] < start
    assert balances[0] == balances[1] == balances[2]
    assert balances[3] < balances[2]


def test_an_activity_without_an_instant_is_paid_for_every_time_as_before():
    """A host that calls on_activity(name) with no instant keeps the old
    contract: every call is a purchase."""
    fin = FinanceSystem(rng=random.Random(1), now=DEFAULT_START)
    first = fin.state.balance
    fin.on_activity("online shopping")
    second = fin.state.balance
    fin.on_activity("online shopping")
    assert first > second > fin.state.balance


# ----------------------------------------------------------------------
# (d) a new persona's first day is not a money emergency
# ----------------------------------------------------------------------

class ScriptedClock:
    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant


@pytest.fixture
def clock():
    saved = hooks.provider_for("persona_now")
    scripted = ScriptedClock(DEFAULT_START)
    hooks.configure(persona_now=lambda timezone=None: scripted.instant)
    yield scripted
    hooks.configure(persona_now=saved)


def _service(tmp_path, clock, name="nova"):
    pathlib.Path(tmp_path).mkdir(parents=True, exist_ok=True)
    return LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=name,
                       world_environment=WorldEnvironment(now=clock, seed=1), rng=random.Random(1))


def test_her_activity_tick_pays_for_an_hour_of_shopping_once(tmp_path, clock):
    svc = _service(tmp_path, clock)
    shopping = svc._activity_engine.get_activity("online shopping")
    start = svc._finance.state.balance
    svc._perform_activity(shopping, None)
    once = svc._finance.state.balance
    clock.instant += timedelta(minutes=20)
    svc._perform_activity(shopping, None)
    assert once < start
    assert svc._finance.state.balance == once


def test_a_new_persona_starts_out_of_reach_of_money_worries():
    """Her first day is no money emergency by construction, and a month of
    spending her surplus -- what the default habit spends on average -- does
    not bring her down to the worried band either: she starts with no
    financial stress at all."""
    fin = FinanceSystem(rng=random.Random(1), now=DEFAULT_START)
    assert fin.financial_stress() == 0.0
    fin.state.balance -= _surplus()
    assert fin.financial_stress() < WORRIED


def test_a_new_persona_with_default_finances_is_not_worried_about_money(tmp_path, clock):
    svc = _service(tmp_path, clock)
    svc._on_energy_tick()
    assert svc._finance.financial_stress() < WORRIED
    assert "money worries" not in svc.affect.stress.sources


# ----------------------------------------------------------------------
# (e) an old save loads to the same values
# ----------------------------------------------------------------------

#: A finance row as LifeService._save_financial_state wrote it before Task 29.
OLD_ROW = {
    "feeling": "tight", "saving_for": "a trip", "recent_splurge": "a book", "balance": 640.25,
    "savings": 410.0, "monthly_income": 2600.0, "monthly_expenses": 1850.0, "spending_habit": 0.35,
    "enabled": 1, "currency": "$", "last_payday": "2026-10-01T08:00:00",
    "last_expense_run": "2026-10-01T08:00:00", "recent_purchases": json.dumps(["a book", "a coffee"]),
}


#: OLD_ROW as it saves again: the same values, and no world hour drawn yet
#: (``spend_hour``, the column fix round 1 added, NULL in an old database:
#: her first tick after the load draws its own hour).
OLD_ROW_SAVED = {**OLD_ROW, "spend_hour": None}


def test_an_old_finance_save_loads_to_the_same_values():
    fin = FinanceSystem.from_dict(dict(OLD_ROW), now=DEFAULT_START)
    assert fin.to_dict() == OLD_ROW_SAVED


def test_an_old_save_without_a_balance_keeps_the_balance_it_always_loaded():
    """The column's default (``balance REAL DEFAULT 1200.0``) and
    from_dict's: an old row reads 1,200 as it always did -- the new starting
    runway is a new persona's, not a reloaded one's."""
    row = {k: v for k, v in OLD_ROW.items() if k != "balance"}
    assert FinanceSystem.from_dict(row, now=DEFAULT_START).state.balance == 1200.0


def test_an_old_save_loads_to_the_same_values_through_life_service(tmp_path, clock):
    svc = _service(tmp_path, clock)
    old = FinanceSystem.from_dict(dict(OLD_ROW), now=DEFAULT_START).state
    for key in ("balance", "savings", "spending_habit", "saving_for", "recent_splurge", "feeling",
                "last_payday", "last_expense_run", "recent_purchases"):
        setattr(svc._finance.state, key, getattr(old, key))
    svc._save_financial_state()
    saved = svc._finance.to_dict()
    again = _service(tmp_path, clock)
    again._load_state()
    assert again._finance.to_dict() == saved == OLD_ROW_SAVED


# ----------------------------------------------------------------------
# (f) a database from before the hours-scale money: her runway, once
# ----------------------------------------------------------------------

#: The finance table as every released version up to 0.5.0 created it: no
#: ``spend_hour`` (read from a database 0.5.0 wrote, 2026-11-13).
OLD_FINANCE_TABLE = """
    CREATE TABLE life_financial_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        feeling TEXT DEFAULT 'comfortable',
        saving_for TEXT,
        recent_splurge TEXT,
        balance REAL DEFAULT 1200.0,
        savings REAL DEFAULT 400.0,
        monthly_income REAL DEFAULT 2600.0,
        monthly_expenses REAL DEFAULT 1850.0,
        spending_habit REAL DEFAULT 0.5,
        enabled INTEGER DEFAULT 1,
        currency TEXT DEFAULT '$',
        last_payday TEXT,
        last_expense_run TEXT,
        recent_purchases TEXT DEFAULT '[]'
    )
"""


def _released_database(tmp_path, balance, name="nova", expenses=1850.0):
    """A life.db whose finance row a released version saved."""
    pathlib.Path(tmp_path).mkdir(parents=True, exist_ok=True)
    stamp = DEFAULT_START.isoformat()
    conn = sqlite3.connect(tmp_path / f"{name}.db")
    conn.execute(OLD_FINANCE_TABLE)
    conn.execute("INSERT INTO life_financial_state (id, feeling, balance, monthly_income, monthly_expenses, "
                 "spending_habit, last_payday, last_expense_run) VALUES (1, 'tight', ?, 1800.0, ?, 0.2, ?, ?)",
                 (balance, expenses, stamp, stamp))
    conn.commit()
    conn.close()


def _loaded(tmp_path, clock):
    svc = _service(tmp_path, clock)
    svc._load_state()
    return svc


@pytest.mark.parametrize("saved", [17.0, 444.0, 1200.0], ids=["emptied", "nearly-emptied", "the-old-default"])
def test_a_persona_from_before_the_hours_scale_money_gets_her_runway_once(tmp_path, clock, saved):
    """Ruling T37-R1: the engines before 0.6.0 emptied every balance within
    three days at the app's cadence (purchases per tick), and their default
    (1,200 against 1,850 of expenses) was worried from her first tick. So
    the first time this code opens a database a released version wrote, her
    balance is raised to a new persona's starting runway -- once: what she
    spends afterwards is hers (the second open leaves it)."""
    _released_database(tmp_path, saved)
    svc = _loaded(tmp_path, clock)
    state = svc._finance.state
    assert state.balance == pytest.approx(STARTING_RUNWAY * 1850.0)
    assert svc._finance.financial_stress() == 0.0
    assert (state.monthly_income, state.spending_habit, state.feeling) == (1800.0, 0.2, "tight")
    state.balance = 100.0  # she spends it down under the new engine
    svc._save_financial_state()
    assert _loaded(tmp_path, clock)._finance.state.balance == 100.0


def test_a_persona_from_before_who_has_more_than_the_runway_keeps_it(tmp_path, clock):
    _released_database(tmp_path, 9000.0)
    assert _loaded(tmp_path, clock)._finance.state.balance == 9000.0


def test_the_runway_follows_her_own_expenses(tmp_path, clock):
    _released_database(tmp_path, 50.0, expenses=1000.0)
    assert _loaded(tmp_path, clock)._finance.state.balance == pytest.approx(STARTING_RUNWAY * 1000.0)


def test_a_persona_of_this_engine_who_ran_low_is_not_topped_up(tmp_path, clock):
    """Her balance under the hours-scale engine is her own spending: a
    reload never raises it (the database already has ``spend_hour``)."""
    svc = _service(tmp_path, clock)
    svc._finance.state.balance = 100.0
    svc._save_financial_state()
    assert _loaded(tmp_path, clock)._finance.state.balance == 100.0
    assert _loaded(tmp_path, clock)._finance.state.balance == 100.0


class _Stopped(Exception):
    """The open was cut short (a full disk, a kill) after the finance table's migration."""


def _connect_that_stops_at(marker):
    """``sqlite3.connect`` whose cursors raise on the first statement holding ``marker``."""
    real = sqlite3.connect

    class Cursor(sqlite3.Cursor):
        def execute(self, sql, *args):
            if marker in sql:
                raise _Stopped(marker)
            return super().execute(sql, *args)

    class Connection(sqlite3.Connection):
        def cursor(self, *args, **kwargs):
            return super().cursor(Cursor)

    return lambda *args, **kwargs: real(*args, **{**kwargs, "factory": Connection})


@pytest.mark.parametrize("cut_at", ["SET balance = ROUND", "life_career_state"],
                         ids=["before-the-raise", "after-the-raise"])
def test_her_runway_and_its_column_land_together(tmp_path, clock, monkeypatch, cut_at):
    """The task's review: ALTER committed by itself and the raise waited for
    the end of the whole initialisation; an open cut short in between kept
    the column and lost the raise for good (the next open found the column
    and raised nothing). Both are one transaction: wherever an open is cut
    short, the next one leaves her with her runway, once."""
    _released_database(tmp_path, 444.0)
    with monkeypatch.context() as cut_short:
        cut_short.setattr(sqlite3, "connect", _connect_that_stops_at(cut_at))
        with pytest.raises(_Stopped):
            _service(tmp_path, clock)
    svc = _loaded(tmp_path, clock)
    assert svc._finance.state.balance == pytest.approx(STARTING_RUNWAY * 1850.0)
    svc._finance.state.balance = 100.0
    svc._save_financial_state()
    assert _loaded(tmp_path, clock)._finance.state.balance == 100.0
