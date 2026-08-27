"""
Career System (Job engine)

Models the persona's work life so it progresses sensibly over time:

- A weekly shift schedule (work_days + shift hours) → an ``on_shift`` state.
- Per-workday workload/satisfaction drift and the occasional work event.
- A monthly salary that LifeService feeds into the Money engine as income.
- Work stress (workload while on shift) that LifeService routes into Affect.

Engine contract: tick / on_activity / on_user_message / export_state /
get_status / to_dict / from_dict.
"""

import json
import random
from datetime import datetime
from typing import List, Optional

from ..models import CareerState


# ============= Career constants (module level) =============

WORKLOAD_DRIFT = 0.04          # per worked day, toward a rolled target
SATISFACTION_DRIFT = 0.02      # per worked day, toward a workload-shaped baseline
WORK_EVENT_CHANCE = 0.35       # chance of a notable work event on a workday

POSITIVE_EVENTS = [
    "got praised by her boss", "wrapped up a big task", "had a good team lunch",
    "made real progress on a project", "got a nice note from a coworker",
]
NEGATIVE_EVENTS = [
    "sat through a draining meeting", "dealt with a difficult client",
    "got handed a tight deadline", "had a frustrating day", "stayed late to finish up",
]

# Activity keywords that change workload.
BUSY_ACTIVITIES = ("working", "work", "meeting", "deadline", "overtime", "commuting")
RESTFUL_ACTIVITIES = ("day_off", "vacation", "weekend", "relaxing", "resting")


class CareerSystem:
    """Persona's job as a ticking engine."""

    def __init__(
        self,
        initial_state: Optional[CareerState] = None,
        occupation: str = "",
        monthly_salary: Optional[float] = None,
    ):
        self._state = initial_state or CareerState()
        if occupation and not self._state.occupation:
            self._state.occupation = occupation
        if monthly_salary is not None:
            self._state.monthly_salary = monthly_salary

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def state(self) -> CareerState:
        return self._state

    @property
    def monthly_salary(self) -> float:
        return self._state.monthly_salary if self._state.employed else 0.0

    def is_working_now(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now()
        if not self._state.employed:
            return False
        if now.weekday() not in self._state.work_days:
            return False
        return self._state.shift_start_hour <= now.hour < self._state.shift_end_hour

    def work_stress(self, now: Optional[datetime] = None) -> float:
        """0..1 stress — workload matters most while on shift."""
        if not self._state.employed:
            return 0.0
        base = self._state.workload
        return round(base * (1.0 if self.is_working_now(now) else 0.35), 2)

    # ------------------------------------------------------------------
    # Tick / reactions
    # ------------------------------------------------------------------

    def tick(self, now: Optional[datetime] = None) -> None:
        """Advance the work life. Registers a workday once per calendar day on
        scheduled work days, drifting workload/satisfaction and rolling events.
        ``now`` may be backdated for catch-up."""
        now = now or datetime.now()
        if not self._state.employed:
            return

        is_workday = now.weekday() in self._state.work_days
        new_day = (
            self._state.last_workday is None
            or self._state.last_workday.date() != now.date()
        )

        # Register a workday once we've reached/passed the shift start.
        if is_workday and new_day and now.hour >= self._state.shift_start_hour:
            self._state.last_workday = now
            self._state.days_worked += 1

            target = random.uniform(0.2, 0.95)
            self._state.workload += (target - self._state.workload) * WORKLOAD_DRIFT * 5

            # Satisfaction drifts toward a baseline shaped by workload (too much
            # work erodes it, a healthy load lifts it).
            sat_baseline = 0.75 - max(0.0, self._state.workload - 0.6) * 0.8
            self._state.satisfaction += (sat_baseline - self._state.satisfaction) * SATISFACTION_DRIFT * 5

            if random.random() < WORK_EVENT_CHANCE:
                if self._state.satisfaction >= 0.5 and random.random() < self._state.satisfaction:
                    self._state.recent_work_event = random.choice(POSITIVE_EVENTS)
                else:
                    self._state.recent_work_event = random.choice(NEGATIVE_EVENTS)

        self._clamp()

    def on_activity(self, activity_name: str) -> None:
        if not self._state.employed or not activity_name:
            return
        key = activity_name.lower().replace(" ", "_")
        if any(k in key for k in BUSY_ACTIVITIES):
            self._state.workload = min(1.0, self._state.workload + 0.05)
        elif any(k in key for k in RESTFUL_ACTIVITIES):
            self._state.workload = max(0.0, self._state.workload - 0.06)
        self._clamp()

    def on_user_message(self, text: str = "") -> None:
        """Part of the documented engine contract; this engine does not react to chat.

        Intentionally inert — kept so every engine presents the same surface.
        """
        return

    def _clamp(self) -> None:
        self._state.workload = max(0.0, min(1.0, self._state.workload))
        self._state.satisfaction = max(0.0, min(1.0, self._state.satisfaction))

    # ------------------------------------------------------------------
    # Export / status / persistence
    # ------------------------------------------------------------------

    def export_state(self) -> dict:
        return {
            "occupation": self._state.occupation,
            "employed": self._state.employed,
            "on_shift": self.is_working_now(),
            "workload": round(self._state.workload, 2),
            "satisfaction": round(self._state.satisfaction, 2),
            "recent_work_event": self._state.recent_work_event,
        }

    def get_status(self) -> dict:
        return {
            "occupation": self._state.occupation,
            "employer": self._state.employer,
            "employed": self._state.employed,
            "on_shift": self.is_working_now(),
            "work_days": list(self._state.work_days),
            "shift": f"{self._state.shift_start_hour:02d}:00-{self._state.shift_end_hour:02d}:00",
            "monthly_salary": self._state.monthly_salary,
            "workload": round(self._state.workload, 2),
            "satisfaction": round(self._state.satisfaction, 2),
            "days_worked": self._state.days_worked,
            "recent_work_event": self._state.recent_work_event,
            "work_stress": self.work_stress(),
        }

    def to_dict(self) -> dict:
        return {
            "occupation": self._state.occupation,
            "employer": self._state.employer,
            "employed": 1 if self._state.employed else 0,
            "work_days": json.dumps(self._state.work_days),
            "shift_start_hour": self._state.shift_start_hour,
            "shift_end_hour": self._state.shift_end_hour,
            "monthly_salary": self._state.monthly_salary,
            "workload": self._state.workload,
            "satisfaction": self._state.satisfaction,
            "days_worked": self._state.days_worked,
            "last_workday": self._state.last_workday.isoformat() if self._state.last_workday else None,
            "recent_work_event": self._state.recent_work_event,
        }

    @classmethod
    def from_dict(cls, data: dict, occupation: str = "") -> "CareerSystem":
        def _dt(v):
            return datetime.fromisoformat(v) if v else None

        days = data.get("work_days") or "[0, 1, 2, 3, 4]"
        if isinstance(days, str):
            try:
                days = json.loads(days)
            except Exception:
                days = [0, 1, 2, 3, 4]

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

        state = CareerState(
            occupation=data.get("occupation") or occupation or "",
            employer=data.get("employer") or "",
            employed=bool(data.get("employed", 1)),
            work_days=list(days),
            shift_start_hour=_i("shift_start_hour", 9),
            shift_end_hour=_i("shift_end_hour", 17),
            monthly_salary=_f("monthly_salary", 2600.0),
            workload=_f("workload", 0.5),
            satisfaction=_f("satisfaction", 0.6),
            days_worked=_i("days_worked", 0),
            last_workday=_dt(data.get("last_workday")),
            recent_work_event=data.get("recent_work_event"),
        )
        return cls(initial_state=state, occupation=occupation)
