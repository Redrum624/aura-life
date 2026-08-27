"""
Errands System (everyday to-do backlog)

A light backlog of chores that accrues over time, slips to "overdue" when it
piles up, and is cleared by errand/chore activities. LifeService routes overdue
errands into Affect as a nagging stressor, so a neglected to-do list weighs on her.

Engine contract: tick / on_activity / on_user_message / export_state /
get_status / to_dict / from_dict.
"""

import json
import random
from datetime import datetime
from typing import List, Optional

from ..models import ErrandsState


# ============= Errands constants =============

ADD_CHANCE = 0.05               # per tick chance a new errand appears
MAX_PENDING_BEFORE_OVERDUE = 4  # backlog past this slips the oldest to overdue
MAX_TOTAL = 12                  # hard cap so the list can't grow unbounded

ERRAND_CATALOG = [
    "pick up groceries", "do the laundry", "reply to emails", "call the dentist",
    "return a package", "pay a bill", "water the plants", "tidy the closet",
    "book a haircut", "renew a subscription", "drop off recycling", "buy stamps",
]

DO_ERRAND_ACTIVITIES = (
    "errand", "errands", "chores", "chore", "groceries", "laundry", "appointment",
    "shopping", "cleaning", "tidying", "organizing", "paying_bills",
)


class ErrandsSystem:
    """The persona's to-do backlog as a ticking engine."""

    def __init__(self, initial_state: Optional[ErrandsState] = None):
        self._state = initial_state or ErrandsState()

    @property
    def state(self) -> ErrandsState:
        return self._state

    @property
    def overdue_count(self) -> int:
        return len(self._state.overdue)

    @property
    def pending_count(self) -> int:
        return len(self._state.pending) + len(self._state.overdue)

    def tick(self, now: Optional[datetime] = None) -> None:
        """Occasionally add an errand; slip the oldest pending to overdue when the
        backlog grows. ``now`` may be backdated for catch-up."""
        total = len(self._state.pending) + len(self._state.overdue)
        if total < MAX_TOTAL and random.random() < ADD_CHANCE:
            choices = [e for e in ERRAND_CATALOG
                       if e not in self._state.pending and e not in self._state.overdue]
            if choices:
                self._state.pending.append(random.choice(choices))
                self._state.last_added = now or datetime.now()

        # Backlog pressure: oldest pending slips to overdue.
        while len(self._state.pending) > MAX_PENDING_BEFORE_OVERDUE:
            slipped = self._state.pending.pop(0)
            if slipped not in self._state.overdue:
                self._state.overdue.append(slipped)

    def on_activity(self, activity_name: str) -> None:
        """An errand/chore activity clears one item (overdue first)."""
        if not activity_name:
            return
        key = activity_name.lower().replace(" ", "_")
        if any(k in key for k in DO_ERRAND_ACTIVITIES):
            if self._state.overdue:
                self._state.overdue.pop(0)
                self._state.completed_count += 1
            elif self._state.pending:
                self._state.pending.pop(0)
                self._state.completed_count += 1

    def on_user_message(self, text: str = "") -> None:
        """Part of the documented engine contract; this engine does not react to chat.

        Intentionally inert — kept so every engine presents the same surface.
        """
        return

    def add_errand(self, title: str) -> None:
        if title and title not in self._state.pending and title not in self._state.overdue:
            self._state.pending.append(title)

    def export_state(self) -> dict:
        return {
            "pending": list(self._state.pending),
            "overdue": list(self._state.overdue),
            "overdue_count": len(self._state.overdue),
        }

    def get_status(self) -> dict:
        return {
            "pending": list(self._state.pending),
            "overdue": list(self._state.overdue),
            "pending_count": self.pending_count,
            "overdue_count": len(self._state.overdue),
            "completed_count": self._state.completed_count,
        }

    def to_dict(self) -> dict:
        return {
            "pending": json.dumps(self._state.pending),
            "overdue": json.dumps(self._state.overdue),
            "completed_count": self._state.completed_count,
            "last_added": self._state.last_added.isoformat() if self._state.last_added else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ErrandsSystem":
        def _list(key):
            v = data.get(key) or "[]"
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except Exception:
                    return []
            return list(v)

        def _dt(v):
            return datetime.fromisoformat(v) if v else None

        def _i(key, default):
            v = data.get(key, default)
            try:
                return int(v) if v is not None else default
            except (TypeError, ValueError):
                return default

        state = ErrandsState(
            pending=_list("pending"),
            overdue=_list("overdue"),
            completed_count=_i("completed_count", 0),
            last_added=_dt(data.get("last_added")),
        )
        return cls(initial_state=state)
