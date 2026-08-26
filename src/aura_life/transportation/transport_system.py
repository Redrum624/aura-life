"""
Transportation System (getting around)

Owns travel-time estimation and the persona's get-around mode. The transit
state-machine itself (PREPARING → IN_TRANSIT → ARRIVED) is orchestrated by
LifeService because arriving moves the World and schedules planner rendezvous —
engines never reach into other engines. This engine provides the pure pieces:
estimate a trip, pick a mode, and describe an active transit overlay.

Engine contract: estimate / pick_mode / export_state / get_status.
"""

import random
from datetime import datetime, timedelta
from typing import Optional


# ============= Transport constants (module level) =============

PREP_TIME_MINUTES = 12

# Travel-time ranges (minutes) by rough distance band.
TRAVEL_TIME_RANGES = {
    "near": (5, 12),
    "moderate": (15, 30),
    "far": (35, 60),
}

# Rough distance band per destination place_type / key.
PLACE_TYPE_DISTANCES = {
    "home": "near", "cafe": "near", "park": "near", "gym": "near",
    "library": "moderate", "workplace": "moderate", "restaurant": "moderate",
    "bar": "moderate", "campus": "moderate", "beach": "far", "airport": "far",
}

# Mode chosen by distance band.
MODE_BY_DISTANCE = {"near": "walk", "moderate": "transit", "far": "car"}


class TransportSystem:
    """Travel-time estimation + get-around mode."""

    def __init__(self, default_mode: str = "transit"):
        self._mode = default_mode
        self._last_trip_minutes: int = 0

    @property
    def mode(self) -> str:
        return self._mode

    def pick_mode(self, destination: str) -> str:
        band = PLACE_TYPE_DISTANCES.get(destination, "moderate")
        self._mode = MODE_BY_DISTANCE.get(band, "transit")
        return self._mode

    def estimate(
        self,
        destination: str,
        total_minutes: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> dict:
        """Estimate a trip. Returns total minutes, expected arrival, whether to
        skip the PREPARING phase, the prep window, and the chosen mode."""
        now = now or datetime.now()
        if total_minutes and total_minutes > 0:
            tot = total_minutes
        else:
            band = PLACE_TYPE_DISTANCES.get(destination, "moderate")
            lo, hi = TRAVEL_TIME_RANGES[band]
            tot = PREP_TIME_MINUTES + random.randint(lo, hi)
        self._last_trip_minutes = tot
        return {
            "total_minutes": tot,
            "expected_arrival": now + timedelta(minutes=tot),
            "skip_prep": tot < PREP_TIME_MINUTES,
            "prep_minutes": PREP_TIME_MINUTES,
            "mode": self.pick_mode(destination),
        }

    def export_state(self, transit) -> dict:
        """Describe an active transit overlay (``transit`` is a TransitState or None)."""
        if not transit:
            return {"in_transit": False, "mode": self._mode}
        phase = getattr(transit, "phase", None)
        return {
            "in_transit": True,
            "phase": phase.value if hasattr(phase, "value") else str(phase),
            "destination": getattr(transit, "destination", ""),
            "origin": getattr(transit, "origin", ""),
            "mode": self._mode,
        }

    def get_status(self, transit=None) -> dict:
        st = self.export_state(transit)
        st["last_trip_minutes"] = self._last_trip_minutes
        return st
