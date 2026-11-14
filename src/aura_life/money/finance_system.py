"""
Finance System (Money engine)

Gives the persona a light, evolving ledger so her financial life progresses and
stays internally consistent over time:

- Monthly income credited on payday (fed by the Job engine in a later phase).
- Recurring expenses (rent/bills/food) deducted monthly.
- Discretionary spending shaped by a per-persona ``spending_habit`` (frugal..spender).
- A qualitative ``feeling`` and a 0..1 ``financial_stress`` signal that LifeService
  routes into Affect.

Set ``FinancialState.enabled = False`` to freeze the dynamics — the user's
"allow spending habits or not".

Engine contract (matches the other life engines): tick / on_activity /
on_user_message / export_state / get_status / to_dict / from_dict.
"""

import json
import random
from datetime import datetime, timedelta
from typing import List, Optional

from ..models import FinancialState
from ..personas.parameters import PersonaParameters


# ============= Finance constants (module level) =============

MAX_RECENT_PURCHASES = 8

# Discretionary amount as a fraction of monthly income (frugal..spender).
DISCRETIONARY_MIN_FRACTION = 0.01
DISCRETIONARY_MAX_FRACTION = 0.06

# Activity costs as a fraction of monthly income (before the habit multiplier).
ACTIVITY_COSTS = {
    "shopping_spree": 0.09, "shopping": 0.05, "concert": 0.04, "spa": 0.035,
    "salon": 0.03, "dining_out": 0.025, "restaurant": 0.025, "groceries": 0.02,
    "bar": 0.02, "drinks": 0.02, "movies": 0.01, "cafe": 0.004, "coffee": 0.004,
}

# Runway = balance / monthly_expenses (months of expenses on hand).
FEELING_TIGHT_RUNWAY = 0.5
FEELING_FLUSH_RUNWAY = 2.5
STRESS_RUNWAY_CEILING = 1.5   # at/above this runway, no financial stress
MAX_FINANCIAL_STRESS = 0.8

# ============= Spending on the world clock (Task 29) =============
# What she spends is a rate per world hour against a budget per world month,
# never a chance per tick: how often a host ticks the engine does not change
# how much she spends (the discretionary chance used to be 0.04 a tick, which
# at the 5-minute energy tick spent her whole balance in three days).

#: The hours of a mean Gregorian month (365.25 days / 12): her monthly
#: discretionary budget is spread over them as a chance per world hour.
HOURS_PER_MONTH = 365.25 / 12 * 24
#: The spending habit whose discretionary spending, on average, is exactly her
#: monthly surplus (income minus recurring expenses): FinancialState's default
#: spending_habit, the middle of frugal (0) .. spender (1). The expected
#: monthly total is surplus * spending_habit / BREAK_EVEN_HABIT -- a frugal
#: 0.1 spends a fifth of her surplus and saves the rest, a spender's 0.9 spends
#: 1.8 times it and runs down.
BREAK_EVEN_HABIT = FinancialState().spending_habit
#: A new persona's starting runway, in months of her recurring expenses:
#: STRESS_RUNWAY_CEILING, the runway at which financial_stress() is nil. A
#: month of spending her surplus at BREAK_EVEN_HABIT then leaves her at a
#: runway of about 1.1 (financial stress about 0.2), clear of the 0.4 at which
#: LifeService holds "money worries"; a spender's overshoot reaches it in her
#: second month. (FinancialState.balance, 1,200 against 1,850 of expenses, is
#: a runway of 0.65 -- financial stress 0.45, worried from her first tick.)
STARTING_RUNWAY = STRESS_RUNWAY_CEILING

PURCHASES = [
    "a coffee", "lunch out", "a new top", "a book", "skincare", "takeout",
    "a candle", "concert tickets", "a small treat", "fresh flowers",
]


class FinanceSystem:
    """Persona finances as a real, ticking engine."""

    def __init__(
        self,
        initial_state: Optional[FinancialState] = None,
        core_traits: Optional[List[str]] = None,
        rng=None,
        now: Optional[datetime] = None,
        params: Optional[PersonaParameters] = None,
    ):
        """``params``: her traits' engine parameters
        (:class:`~aura_life.personas.parameters.PersonaParameters`), whose
        ``frugal`` / ``spender`` cap or floor the spending habit; without them
        ``core_traits`` is read for them."""
        self._state = initial_state or FinancialState()
        if initial_state is None:
            # A new persona's first day is not a money emergency
            # (STARTING_RUNWAY); a saved one keeps her balance (from_dict).
            self._state.balance = self.starting_balance()
        self._rng = rng if rng is not None else random
        self._apply_trait_habits(params if params is not None else PersonaParameters.from_core_traits(core_traits))
        # Establish a baseline so income/expenses fire on the NEXT month boundary,
        # not immediately on the first tick. ``now`` is the clock the ticks will
        # be measured on -- a host that ticks on an injected world clock passes
        # it here too, or the baseline sits on the host's month and the first
        # tick pays a month that never passed. ``None`` reads the wall clock.
        now = now or datetime.now()
        if self._state.last_payday is None:
            self._state.last_payday = now
        if self._state.last_expense_run is None:
            self._state.last_expense_run = now
        # The last world hour her discretionary purchases are drawn for (None:
        # none yet, her first tick draws its own hour) and the hour whose
        # activities are already paid for (on_activity). The drawn hour is
        # saved (to_dict's "spend_hour"), so a reload draws the hours she was
        # away once, whichever of the host's live and catch-up ticks comes
        # first (fix round 1, T29-1); an old save has none. The paid hour is
        # not saved.
        self._spend_hour: Optional[datetime] = None
        self._paid_hour: tuple = (None, set())

    def _apply_trait_habits(self, params: PersonaParameters) -> None:
        """A frugal persona spends at most 0.3, a spender at least 0.7 (the
        words: parameters.FRUGAL_TRAITS / SPENDER_TRAITS)."""
        if params.frugal:
            self._state.spending_habit = min(self._state.spending_habit, 0.3)
        if params.spender:
            self._state.spending_habit = max(self._state.spending_habit, 0.7)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def state(self) -> FinancialState:
        return self._state

    @property
    def feeling(self) -> str:
        return self._state.feeling

    def starting_balance(self) -> float:
        """A new persona's balance: STARTING_RUNWAY months of her recurring
        expenses, 2,775 at FinancialState's defaults. Her expenses alone set
        it, so a salary the Job engine sets later does not move it. A saved
        persona keeps her saved balance (from_dict)."""
        return round(STARTING_RUNWAY * self._state.monthly_expenses, 2)

    def can_afford(self, amount: float) -> bool:
        return self._state.balance >= amount

    def financial_stress(self) -> float:
        """0..1 stress derived from low runway (balance vs monthly expenses)."""
        exp = max(1.0, self._state.monthly_expenses)
        runway = self._state.balance / exp
        if runway >= STRESS_RUNWAY_CEILING:
            return 0.0
        return max(0.0, min(MAX_FINANCIAL_STRESS,
                            (STRESS_RUNWAY_CEILING - runway) / STRESS_RUNWAY_CEILING * MAX_FINANCIAL_STRESS))

    # ------------------------------------------------------------------
    # Tick / reactions
    # ------------------------------------------------------------------

    def tick(self, now: Optional[datetime] = None) -> None:
        """Advance finances. Credits income / deducts expenses on month boundaries
        and rolls occasional discretionary spending. ``now`` may be backdated for
        catch-up. No-op dynamics when disabled (feeling still recomputed)."""
        now = now or datetime.now()
        if not self._state.enabled:
            self._spend_hour = None   # no purchases for the hours it was off
            self._recompute_feeling()
            return

        if self._is_new_month(self._state.last_payday, now):
            self._state.balance = round(self._state.balance + self._state.monthly_income, 2)
            self._state.last_payday = now

        if self._is_new_month(self._state.last_expense_run, now):
            self._state.balance = round(self._state.balance - self._state.monthly_expenses, 2)
            self._state.last_expense_run = now
            # Frugal personas saving for something sweep a little surplus to savings.
            if self._state.saving_for and self._state.spending_habit < 0.5:
                surplus = max(0.0, self._state.balance - self._state.monthly_expenses)
                sweep = round(surplus * (0.5 - self._state.spending_habit) * 0.2, 2)
                if sweep > 0:
                    self._state.balance = round(self._state.balance - sweep, 2)
                    self._state.savings = round(self._state.savings + sweep, 2)

        self._spend_discretionary(now)
        self._recompute_feeling()

    def _spend_discretionary(self, now: datetime) -> None:
        """One draw for each world hour after the last one drawn up to
        ``now``'s (the first tick draws its own hour), each a purchase with
        the chance that spreads her monthly budget
        (:meth:`discretionary_budget`) over HOURS_PER_MONTH: the hours a
        host's ticks cross, not the ticks, set how often she buys. A
        backdated tick draws nothing: its hour is drawn already."""
        hour = self._hour_of(now)
        if self._spend_hour is not None and hour <= self._spend_hour:
            return
        hours = 1 if self._spend_hour is None else self._hours_to_draw(self._spend_hour, hour)
        self._spend_hour = hour
        amount = round(self._state.monthly_income * self._discretionary_fraction(), 2)
        chance = (min(1.0, self.discretionary_budget() / amount / HOURS_PER_MONTH)
                  if amount > 0 else 0.0)
        for _ in range(hours):
            if chance > 0 and self._rng.random() < chance and self.can_afford(amount):
                self._spend(amount, self._rng.choice(PURCHASES))

    @staticmethod
    def _hours_to_draw(last: datetime, hour: datetime) -> int:
        """The world hours after ``last`` up to and including ``hour``, less
        those of the calendar months wholly between theirs: :meth:`tick`
        credits one month's pay and bills however many months a tick crosses
        (a process suspended past a month, a host off for one), so a tick
        draws only for the rest of the last drawn hour's month and for its
        own month, never for a month nothing paid for (fix round 1, T29-4)."""
        month_after_last = (last.replace(day=1, hour=0) + timedelta(days=32)).replace(day=1)
        unpaid = max(timedelta(0), hour.replace(day=1, hour=0) - month_after_last)
        return (hour - last - unpaid) // timedelta(hours=1)

    def _discretionary_fraction(self) -> float:
        """One purchase, as a fraction of monthly income (frugal..spender)."""
        return DISCRETIONARY_MIN_FRACTION + (
            DISCRETIONARY_MAX_FRACTION - DISCRETIONARY_MIN_FRACTION
        ) * self._state.spending_habit

    def discretionary_budget(self) -> float:
        """Her discretionary spending's expected monthly total: her monthly
        surplus (income minus recurring expenses; none when the bills take it
        all) times spending_habit / BREAK_EVEN_HABIT."""
        surplus = max(0.0, self._state.monthly_income - self._state.monthly_expenses)
        return surplus * self._state.spending_habit / BREAK_EVEN_HABIT

    def on_activity(self, activity_name: str, now: Optional[datetime] = None) -> None:
        """Charge for money-spending activities (shopping, dining, coffee, …).

        ``now`` is the world instant she does it at: an activity is paid for
        once in its world hour, however many activity ticks of that hour
        repeat it (the plan's slot governs every tick of its hour), so the
        activity tick's interval does not set what an hour of it costs.
        Without ``now`` every call is a purchase, as it always was. One she
        cannot afford is not paid for (:meth:`can_afford`)."""
        if not self._state.enabled or not activity_name:
            return
        key = activity_name.lower().replace(" ", "_")
        frac = next((f for k, f in ACTIVITY_COSTS.items() if k in key), None)
        if frac is None:
            return
        hour = self._hour_of(now) if now is not None else None
        if hour is not None:
            if self._paid_hour[0] != hour:
                self._paid_hour = (hour, set())
            if key in self._paid_hour[1]:
                return
        amount = round(self._state.monthly_income * frac * (0.6 + self._state.spending_habit * 0.8), 2)
        if amount > 0 and self.can_afford(amount):
            self._spend(amount, activity_name.replace("_", " "))
            if hour is not None:
                self._paid_hour[1].add(key)
            self._recompute_feeling()

    def on_user_message(self, text: str = "") -> None:
        """Part of the documented engine contract; this engine does not react to chat.

        Intentionally inert — kept so every engine presents the same surface.
        """
        return

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _hour_of(now: datetime) -> datetime:
        return now.replace(minute=0, second=0, microsecond=0)

    @staticmethod
    def _is_new_month(last: Optional[datetime], now: datetime) -> bool:
        """A month after ``last``'s, never one before it: a catch-up tick
        backdated into the month before the live tick's pays nothing and
        leaves the marker where it is, as a backdated tick draws no hour
        (:meth:`_spend_discretionary`). While the clock stays behind the
        marker's month, nothing is paid or billed."""
        if last is None:
            return False  # baseline is set in __init__/from_dict
        return (now.year, now.month) > (last.year, last.month)

    def _spend(self, amount: float, label: str) -> None:
        self._state.balance = round(self._state.balance - amount, 2)
        self._state.recent_splurge = label
        self._state.recent_purchases.append(label)
        if len(self._state.recent_purchases) > MAX_RECENT_PURCHASES:
            self._state.recent_purchases = self._state.recent_purchases[-MAX_RECENT_PURCHASES:]

    def _recompute_feeling(self) -> None:
        exp = max(1.0, self._state.monthly_expenses)
        runway = self._state.balance / exp
        if runway < FEELING_TIGHT_RUNWAY:
            self._state.feeling = "tight"
        elif self._state.saving_for and runway >= 1.0:
            self._state.feeling = "saving"
        elif runway >= FEELING_FLUSH_RUNWAY:
            self._state.feeling = "flush"
        else:
            self._state.feeling = "comfortable"

    def _balance_band(self) -> str:
        runway = self._state.balance / max(1.0, self._state.monthly_expenses)
        if runway < FEELING_TIGHT_RUNWAY:
            return "low"
        if runway >= FEELING_FLUSH_RUNWAY:
            return "high"
        return "okay"

    # ------------------------------------------------------------------
    # Export / status / persistence
    # ------------------------------------------------------------------

    def export_state(self) -> dict:
        """Structured, mostly-qualitative dict for the LLM digest passes."""
        return {
            "feeling": self._state.feeling,
            "saving_for": self._state.saving_for,
            "recent_splurge": self._state.recent_splurge,
            "balance_band": self._balance_band(),
            "stress": round(self.financial_stress(), 2),
        }

    def get_status(self) -> dict:
        """Full numeric status for /api/life/status and debugging."""
        return {
            "feeling": self._state.feeling,
            "balance": round(self._state.balance, 2),
            "savings": round(self._state.savings, 2),
            "currency": self._state.currency,
            "monthly_income": self._state.monthly_income,
            "monthly_expenses": self._state.monthly_expenses,
            "spending_habit": round(self._state.spending_habit, 2),
            "enabled": self._state.enabled,
            "saving_for": self._state.saving_for,
            "recent_splurge": self._state.recent_splurge,
            "recent_purchases": list(self._state.recent_purchases),
            "financial_stress": round(self.financial_stress(), 2),
        }

    def to_dict(self) -> dict:
        """DB-ready column values (symmetric with from_dict)."""
        return {
            "feeling": self._state.feeling,
            "saving_for": self._state.saving_for,
            "recent_splurge": self._state.recent_splurge,
            "balance": self._state.balance,
            "savings": self._state.savings,
            "monthly_income": self._state.monthly_income,
            "monthly_expenses": self._state.monthly_expenses,
            "spending_habit": self._state.spending_habit,
            "enabled": 1 if self._state.enabled else 0,
            "currency": self._state.currency,
            "last_payday": self._state.last_payday.isoformat() if self._state.last_payday else None,
            "last_expense_run": self._state.last_expense_run.isoformat() if self._state.last_expense_run else None,
            "recent_purchases": json.dumps(self._state.recent_purchases),
            "spend_hour": self._spend_hour.isoformat() if self._spend_hour else None,
        }

    @classmethod
    def from_dict(cls, data: dict, core_traits: Optional[List[str]] = None,
                  rng=None, now: Optional[datetime] = None,
                  params: Optional[PersonaParameters] = None) -> "FinanceSystem":
        def _dt(v):
            return datetime.fromisoformat(v) if v else None

        purchases = data.get("recent_purchases") or "[]"
        if isinstance(purchases, str):
            try:
                purchases = json.loads(purchases)
            except Exception:
                purchases = []

        def _f(key, default):
            v = data.get(key, default)
            try:
                return float(v) if v is not None else default
            except (TypeError, ValueError):
                return default

        state = FinancialState(
            feeling=data.get("feeling") or "comfortable",
            saving_for=data.get("saving_for"),
            recent_splurge=data.get("recent_splurge"),
            balance=_f("balance", 1200.0),
            savings=_f("savings", 400.0),
            monthly_income=_f("monthly_income", 2600.0),
            monthly_expenses=_f("monthly_expenses", 1850.0),
            spending_habit=_f("spending_habit", 0.5),
            enabled=bool(data.get("enabled", 1)),
            currency=data.get("currency") or "$",
            last_payday=_dt(data.get("last_payday")),
            last_expense_run=_dt(data.get("last_expense_run")),
            recent_purchases=list(purchases),
        )
        system = cls(initial_state=state, core_traits=core_traits, rng=rng, now=now, params=params)
        # The last world hour drawn (None in an old save: drawn again from
        # her first tick, as before the column).
        system._spend_hour = _dt(data.get("spend_hour"))
        return system
