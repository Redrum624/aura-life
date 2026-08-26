"""
Sustenance System (food / nutrition engine)

Hunger rises over time and is relieved by eating; meals build nutrition while
snacks barely do. LifeService drains energy on high hunger and the Money engine
charges for dining/groceries, so eating ties the sim together.

Engine contract: tick / on_activity / on_user_message / export_state /
get_status / to_dict / from_dict.
"""

from datetime import datetime
from typing import Optional

from ..models import BasicNeedsState


# ============= Sustenance constants =============

HUNGER_RISE = 0.004             # per tick
NUTRITION_BASELINE = 0.5
NUTRITION_DECAY = 0.02          # drift toward baseline per tick
MEAL_HUNGER_REDUCTION = 0.4
HUNGRY_THRESHOLD = 0.7

EAT_ACTIVITIES = (
    "eat", "eating", "breakfast", "lunch", "dinner", "brunch", "snack",
    "cooking", "dining", "meal", "grab_food", "grabbing_food", "groceries",
    "baking", "recipe",
)
REAL_MEAL = ("cooking", "dinner", "lunch", "breakfast", "brunch", "meal", "dining", "baking", "recipe")


class SustenanceSystem:
    """Hunger / meals / nutrition as a ticking engine."""

    def __init__(self, initial_state: Optional[BasicNeedsState] = None):
        self._state = initial_state or BasicNeedsState()

    @property
    def state(self) -> BasicNeedsState:
        return self._state

    @property
    def hunger(self) -> float:
        return self._state.hunger

    def is_hungry(self) -> bool:
        return self._state.hunger >= HUNGRY_THRESHOLD

    def tick(self, now: Optional[datetime] = None) -> None:
        self._state.hunger = min(1.0, self._state.hunger + HUNGER_RISE)
        self._state.nutrition += (NUTRITION_BASELINE - self._state.nutrition) * NUTRITION_DECAY
        self._state.nutrition = max(0.0, min(1.0, self._state.nutrition))

    def on_activity(self, activity_name: str, now: Optional[datetime] = None) -> None:
        if not activity_name:
            return
        key = activity_name.lower().replace(" ", "_")
        if any(k in key for k in EAT_ACTIVITIES):
            self._state.hunger = max(0.0, self._state.hunger - MEAL_HUNGER_REDUCTION)
            self._state.last_meal_time = now or datetime.now()
            self._state.meals_today += 1
            boost = 0.15 if any(k in key for k in REAL_MEAL) else 0.05
            self._state.nutrition = min(1.0, self._state.nutrition + boost)

    def on_user_message(self, text: str = "") -> None:
        return

    def reset_daily(self) -> None:
        """New-day rollover — clear the meal counter."""
        self._state.meals_today = 0

    def hunger_label(self) -> str:
        h = self._state.hunger
        if h >= 0.8:
            return "starving"
        if h >= 0.6:
            return "pretty hungry"
        if h >= 0.4:
            return "peckish"
        return "satisfied"

    def export_state(self) -> dict:
        return {
            "hunger": round(self._state.hunger, 2),
            "hunger_label": self.hunger_label(),
            "meals_today": self._state.meals_today,
            "nutrition": round(self._state.nutrition, 2),
            "showered_today": self._state.showered_today,
        }

    def get_status(self) -> dict:
        return {
            "hunger": round(self._state.hunger, 2),
            "hunger_label": self.hunger_label(),
            "meals_today": self._state.meals_today,
            "nutrition": round(self._state.nutrition, 2),
            "showered_today": self._state.showered_today,
            "morning_routine_done": self._state.morning_routine_done,
            "last_meal_time": self._state.last_meal_time.isoformat() if self._state.last_meal_time else None,
        }

    def to_dict(self) -> dict:
        return {
            "hunger": self._state.hunger,
            "last_meal_time": self._state.last_meal_time.isoformat() if self._state.last_meal_time else None,
            "showered_today": 1 if self._state.showered_today else 0,
            "morning_routine_done": 1 if self._state.morning_routine_done else 0,
            "meals_today": self._state.meals_today,
            "nutrition": self._state.nutrition,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SustenanceSystem":
        def _dt(v):
            return datetime.fromisoformat(v) if v else None

        def _f(key, default):
            v = data.get(key, default)
            try:
                return float(v) if v is not None else default
            except (TypeError, ValueError):
                return default

        def _i(key, default):
            v = data.get(key, default)
            try:
                return int(v) if v is not None else default
            except (TypeError, ValueError):
                return default

        state = BasicNeedsState(
            hunger=_f("hunger", 0.0),
            last_meal_time=_dt(data.get("last_meal_time")),
            showered_today=bool(data.get("showered_today", 0)),
            morning_routine_done=bool(data.get("morning_routine_done", 0)),
            meals_today=_i("meals_today", 0),
            nutrition=_f("nutrition", 0.6),
        )
        return cls(initial_state=state)
