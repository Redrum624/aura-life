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
from datetime import datetime
from typing import List, Optional

from ..models import FinancialState


# ============= Finance constants (module level) =============

MAX_RECENT_PURCHASES = 8

# Discretionary spend probability per tick, scaled by spending_habit.
DISCRETIONARY_BASE_CHANCE = 0.04
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
    ):
        self._state = initial_state or FinancialState()
        self._apply_trait_habits(core_traits or [])
        # Establish a baseline so income/expenses fire on the NEXT month boundary,
        # not immediately on the first tick.
        now = datetime.now()
        if self._state.last_payday is None:
            self._state.last_payday = now
        if self._state.last_expense_run is None:
            self._state.last_expense_run = now

    def _apply_trait_habits(self, core_traits: List[str]) -> None:
        text = " ".join(t.lower() for t in core_traits)
        if any(w in text for w in ("frugal", "thrifty", "saver", "careful", "disciplined")):
            self._state.spending_habit = min(self._state.spending_habit, 0.3)
        if any(w in text for w in ("impulsive", "lavish", "extravagant", "spender", "indulgent", "hedonist")):
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

        chance = DISCRETIONARY_BASE_CHANCE * (0.4 + self._state.spending_habit * 1.2)
        if random.random() < chance:
            frac = DISCRETIONARY_MIN_FRACTION + (
                DISCRETIONARY_MAX_FRACTION - DISCRETIONARY_MIN_FRACTION
            ) * self._state.spending_habit
            amount = round(self._state.monthly_income * frac, 2)
            if self.can_afford(amount):
                self._spend(amount, random.choice(PURCHASES))

        self._recompute_feeling()

    def on_activity(self, activity_name: str) -> None:
        """Charge for money-spending activities (shopping, dining, coffee, …)."""
        if not self._state.enabled or not activity_name:
            return
        key = activity_name.lower().replace(" ", "_")
        frac = next((f for k, f in ACTIVITY_COSTS.items() if k in key), None)
        if frac is None:
            return
        amount = round(self._state.monthly_income * frac * (0.6 + self._state.spending_habit * 0.8), 2)
        if amount > 0 and self.can_afford(amount):
            self._spend(amount, activity_name.replace("_", " "))
            self._recompute_feeling()

    def on_user_message(self, text: str = "") -> None:
        """Finances don't react to chat directly."""
        return

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _is_new_month(last: Optional[datetime], now: datetime) -> bool:
        if last is None:
            return False  # baseline is set in __init__/from_dict
        return (now.year, now.month) != (last.year, last.month)

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
        }

    @classmethod
    def from_dict(cls, data: dict, core_traits: Optional[List[str]] = None) -> "FinanceSystem":
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
        return cls(initial_state=state, core_traits=core_traits)
