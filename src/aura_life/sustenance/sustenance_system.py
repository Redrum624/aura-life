"""
Sustenance System (food / nutrition engine)

Hunger rises over time and is relieved by eating; meals build nutrition while
snacks barely do. LifeService drains energy on high hunger and the Money engine
charges for dining/groceries, so eating ties the sim together.

Rates run per hour on the world clock (ruling T4-R4, humanness program Task
10): ``LifeService`` hands :meth:`SustenanceSystem.tick` the world hours since
its last one. They were per call, and the host's energy tick calls it every
five minutes, so the more often a host ticked, the hungrier she got. A bare
``tick()`` (no ``hours``) is still one such energy interval, exactly what one
call gave before.

Eating is the activity's "meal" tag (``aura_life.settings.spec.ACTIVITY_TAGS``;
ruling T9-R8), which the caller passes as ``meal=`` -- never a word inside the
activity's name ("creating a playlist" fed her because "creating" contains
"eat").

Engine contract: tick / on_activity / on_user_message / export_state /
get_status / to_dict / from_dict.
"""

from datetime import datetime, timedelta
from typing import Optional

from ..models import BasicNeedsState
from ..scheduler.life_scheduler import LifeScheduler


# ============= Sustenance constants =============

#: The hours one bare ``tick()`` stands for: one energy interval of
#: ``LifeScheduler`` (5 minutes), the interval the per-call rates below were
#: written for.
TICK_HOURS = LifeScheduler.TICK_INTERVAL_MINUTES["energy"] / 60
#: Hunger's rise per world hour. It was 0.004 per energy tick; at the 12
#: energy ticks an hour ``LifeScheduler`` runs, that is 0.048 an hour -- the
#: rate production hosts already had, now whatever the cadence.
HUNGER_RISE_PER_HOUR = 0.048
#: Legacy name: the rise per bare ``tick()`` (HUNGER_RISE_PER_HOUR * TICK_HOURS).
HUNGER_RISE = 0.004
NUTRITION_BASELINE = 0.5
#: The share of the gap to NUTRITION_BASELINE that nutrition closes per energy
#: interval (TICK_HOURS); over ``hours`` it closes 1 - (1 - 0.02) ** (hours /
#: TICK_HOURS) of it -- the per-call drift it had, on the clock.
NUTRITION_DECAY = 0.02
MEAL_HUNGER_REDUCTION = 0.4
HUNGRY_THRESHOLD = 0.7
#: The energy that hunger above HUNGRY_THRESHOLD drains per waking hour. It
#: was 0.01 per energy tick (``LifeService``'s energy tick), so 0.12 an hour at
#: LifeScheduler's 12 energy ticks an hour. None while she sleeps: the drain
#: ran through her nights and beat sleep's recovery (ruling T4-R4).
HUNGER_ENERGY_DRAIN_PER_HOUR = 0.12
#: A meal within this long of the start of her last one is that meal going on,
#: not another (one relief, one count): her planned meal slot governs a whole
#: hour -- ``DailyPlanner`` plans by the hour -- and so spans several activity
#: ticks.
MEAL_LENGTH_MINUTES = 60

#: Legacy names: the name keywords that used to feed her (a meal is its tag
#: now, ruling T9-R8). No longer read; kept so an import from here keeps working.
EAT_ACTIVITIES = (
    "eat", "eating", "breakfast", "lunch", "dinner", "brunch", "snack",
    "cooking", "dining", "meal", "grab_food", "grabbing_food", "groceries",
    "baking", "recipe",
)
REAL_MEAL = ("cooking", "dinner", "lunch", "breakfast", "brunch", "meal", "dining", "baking", "recipe")
#: Nutrition a meal adds (the "real meal" boost the keywords gave).
MEAL_NUTRITION_BOOST = 0.15


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

    def tick(self, now: Optional[datetime] = None, hours: Optional[float] = None) -> None:
        """Advance hunger and nutrition by ``hours`` of world time (``None``:
        one energy interval, TICK_HOURS -- what a bare call always gave)."""
        hours = TICK_HOURS if hours is None else max(0.0, hours)
        self._state.hunger = min(1.0, self._state.hunger + HUNGER_RISE_PER_HOUR * hours)
        drift = 1.0 - (1.0 - NUTRITION_DECAY) ** (hours / TICK_HOURS)
        self._state.nutrition += (NUTRITION_BASELINE - self._state.nutrition) * drift
        self._state.nutrition = max(0.0, min(1.0, self._state.nutrition))

    def energy_drain(self, hours: float, asleep: bool = False) -> float:
        """The energy her hunger costs her over ``hours`` of world time: none
        asleep, none unless hunger is above HUNGRY_THRESHOLD, else
        HUNGER_ENERGY_DRAIN_PER_HOUR an hour. The caller applies it."""
        if asleep or self._state.hunger <= HUNGRY_THRESHOLD:
            return 0.0
        return HUNGER_ENERGY_DRAIN_PER_HOUR * max(0.0, hours)

    def on_activity(self, activity_name: str, now: Optional[datetime] = None, *, meal: bool = False) -> None:
        """Eating relieves hunger: ``meal`` is the caller's word that the
        activity is a meal (it carries the "meal" tag,
        aura_life.settings.spec.ACTIVITY_TAGS), whatever its name. A meal
        within MEAL_LENGTH_MINUTES of her last one's start continues it."""
        if not activity_name or not meal:
            return
        now = now or datetime.now()
        last = self._state.last_meal_time
        if last is not None and timedelta(0) <= now - last < timedelta(minutes=MEAL_LENGTH_MINUTES):
            return  # the same meal, still going
        self._state.hunger = max(0.0, self._state.hunger - MEAL_HUNGER_REDUCTION)
        self._state.last_meal_time = now
        self._state.meals_today += 1
        self._state.nutrition = min(1.0, self._state.nutrition + MEAL_NUTRITION_BOOST)

    def on_user_message(self, text: str = "") -> None:
        """Part of the documented engine contract; this engine does not react to chat.

        Intentionally inert — kept so every engine presents the same surface.
        """
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
