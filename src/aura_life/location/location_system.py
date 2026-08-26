"""
Location System (places & familiarity)

Owns the persona's known-places registry and daily visit tracking. The *current*
place is owned by the World engine (world.current_location); this engine owns the
map of places, how familiar she is with each, and which she's visited today.

``record_visit`` updates visit count + familiarity and reports what LifeService
needs to apply cross-engine effects (energy/affect) — engines never call each other.

Engine contract: record_visit / export_state / get_status (+ registry accessors).
"""

from datetime import datetime
from typing import Dict, Optional

from ..models import LocationProfile


class LocationSystem:
    """Known-places registry + familiarity + daily visits."""

    def __init__(self, registry: Optional[Dict[str, LocationProfile]] = None):
        # The registry dict is aliased by LifeService (build + persistence write here).
        self._registry: Dict[str, LocationProfile] = registry if registry is not None else {}
        self._visited_today: set = set()
        self._visited_today_date: str = ""

    @property
    def registry(self) -> Dict[str, LocationProfile]:
        return self._registry

    @property
    def visited_today(self) -> set:
        return self._visited_today

    def get_profile(self, loc_key: str) -> Optional[LocationProfile]:
        return self._registry.get(loc_key)

    def register(self, slug: str, profile: LocationProfile) -> None:
        self._registry[slug] = profile

    def record_visit(self, loc_key: str, now: Optional[datetime] = None) -> dict:
        """Record a visit: grow familiarity, track today's visits, and return the
        facts LifeService needs to apply energy/affect effects."""
        now = now or datetime.now()
        today = now.strftime("%Y-%m-%d")
        if self._visited_today_date != today:
            self._visited_today.clear()  # in-place so the LifeService alias stays valid
            self._visited_today_date = today

        is_new_today = loc_key not in self._visited_today
        self._visited_today.add(loc_key)

        profile = self._registry.get(loc_key)
        if profile:
            profile.visit_count += 1
            profile.last_visit = now.isoformat()
            profile.familiarity = min(1.0, profile.familiarity + 0.01 * (1.0 - profile.familiarity))
            place_type = profile.place_type
            familiarity = profile.familiarity
        else:
            place_type = "other"
            familiarity = 0.0

        return {
            "place_type": place_type,
            "is_nature": place_type in ("park", "beach"),
            "is_new_today": is_new_today,
            "visited_today_count": len(self._visited_today),
            "familiarity": familiarity,
        }

    def favorite_places(self, threshold: float = 0.8) -> list:
        return [p.name or k for k, p in self._registry.items() if p.familiarity >= threshold]

    def export_state(self) -> dict:
        return {
            "known_places": len(self._registry),
            "visited_today": len(self._visited_today),
            "favorites": self.favorite_places(),
        }

    def get_status(self) -> dict:
        return {
            "known_places": len(self._registry),
            "visited_today": sorted(self._visited_today),
            "favorites": self.favorite_places(),
        }
