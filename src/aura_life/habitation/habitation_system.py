"""
Habitation System (living-space engine)

Owns the persona's home/room so it feels lived-in and shifts over time:

- Tidiness slowly decays and is restored by cleaning activities.
- Evening/night candle ambiance.
- A derived ``comfort`` (cozy..bleak) from tidiness + ambiance that LifeService
  routes into Affect (a bleak, messy space is a mild stressor).

Engine contract: tick / on_activity / on_user_message / export_state /
get_status / to_dict / from_dict.
"""

import random
from typing import Optional

from ..models import RoomState, TimeOfDay


# ============= Habitation constants =============

TIDINESS_DECAY = 0.002          # per tick
CANDLE_CHANCE = 0.1             # per evening/night tick when unlit
TIDY_RESTORE = 0.3             # cleaning activity bump
COMFORT_BLEAK = 0.35           # below this → mild stressor

CLEAN_ACTIVITIES = ("cleaning", "tidying", "tidy", "chores", "organizing", "decluttering")


class HabitationSystem:
    """The persona's living space as a ticking engine."""

    def __init__(self, initial_state: Optional[RoomState] = None, home_type: str = ""):
        self._state = initial_state or RoomState()
        if home_type and self._state.home_type == "apartment":
            self._state.home_type = home_type
        self._recompute_comfort()

    @property
    def state(self) -> RoomState:
        return self._state

    @property
    def comfort(self) -> float:
        return self._state.comfort

    def tick(self, time_of_day: Optional[TimeOfDay] = None) -> None:
        """Decay tidiness, manage candle ambiance, recompute comfort."""
        self._state.tidiness = max(0.0, self._state.tidiness - TIDINESS_DECAY)

        if time_of_day in (TimeOfDay.EVENING, TimeOfDay.NIGHT):
            if not self._state.candle_lit and random.random() < CANDLE_CHANCE:
                self._state.candle_lit = True
        else:
            self._state.candle_lit = False

        self._recompute_comfort()

    def on_activity(self, activity_name: str) -> None:
        if not activity_name:
            return
        key = activity_name.lower().replace(" ", "_")
        if any(k in key for k in CLEAN_ACTIVITIES):
            self._state.tidiness = min(1.0, self._state.tidiness + TIDY_RESTORE)
            self._recompute_comfort()

    def on_user_message(self, text: str = "") -> None:
        """Part of the documented engine contract; this engine does not react to chat.

        Intentionally inert — kept so every engine presents the same surface.
        """
        return

    def leave_home(self) -> None:
        """Called when the persona heads out — kill the candle/music."""
        self._state.candle_lit = False
        self._state.music_playing = False
        self._recompute_comfort()

    def _recompute_comfort(self) -> None:
        c = 0.35 + self._state.tidiness * 0.4
        if self._state.candle_lit:
            c += 0.1
        if self._state.music_playing:
            c += 0.08
        if self._state.window_open:
            c += 0.05
        self._state.comfort = max(0.0, min(1.0, c))

    def export_state(self) -> dict:
        return {
            "home_type": self._state.home_type,
            "comfort": round(self._state.comfort, 2),
            "tidiness": round(self._state.tidiness, 2),
            "candle_lit": self._state.candle_lit,
            "music_playing": self._state.music_playing,
        }

    def get_status(self) -> dict:
        return {
            "home_type": self._state.home_type,
            "comfort": round(self._state.comfort, 2),
            "tidiness": round(self._state.tidiness, 2),
            "candle_lit": self._state.candle_lit,
            "music_playing": self._state.music_playing,
            "window_open": self._state.window_open,
        }

    def to_dict(self) -> dict:
        return {
            "candle_lit": 1 if self._state.candle_lit else 0,
            "music_playing": 1 if self._state.music_playing else 0,
            "window_open": 1 if self._state.window_open else 0,
            "tidiness": self._state.tidiness,
            "home_type": self._state.home_type,
            "comfort": self._state.comfort,
        }

    @classmethod
    def from_dict(cls, data: dict, home_type: str = "") -> "HabitationSystem":
        def _f(key, default):
            v = data.get(key, default)
            try:
                return float(v) if v is not None else default
            except (TypeError, ValueError):
                return default

        state = RoomState(
            candle_lit=bool(data.get("candle_lit", 0)),
            music_playing=bool(data.get("music_playing", 0)),
            window_open=bool(data.get("window_open", 0)),
            tidiness=_f("tidiness", 0.7),
            home_type=data.get("home_type") or "apartment",
            comfort=_f("comfort", 0.7),
        )
        return cls(initial_state=state, home_type=home_type)
