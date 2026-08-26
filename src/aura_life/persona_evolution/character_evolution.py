"""
Character Evolution Engine

Tracks slow personality drift based on lived experience.
The persona's emotional baseline shifts based on what she does and feels.

Instead of OCEAN traits (not used in this codebase), we track drift in
emotional_baseline values and core trait salience.
"""

import json
from datetime import datetime
from typing import Dict, List, Optional

logger = __import__("logging").getLogger(__name__)

# Maximum drift per emotional baseline value from original
MAX_DRIFT = 0.15

# Activity patterns -> baseline drift direction
DRIFT_INFLUENCES = {
    # Activities that increase baseline warmth
    "warmth_up": [
        "texting a friend", "having coffee with a friend",
        "catching up with family", "cooking a meal",
    ],
    # Activities that increase baseline calm
    "calm_up": [
        "meditating", "yoga", "reading", "journaling",
        "taking a long bath",
    ],
    # Activities that increase baseline energy
    "energy_up": [
        "going for a run", "gym workout", "exploring a new idea",
        "learning something new",
    ],
    # Activities that increase baseline creativity
    "creativity_up": [
        "writing poetry", "sketching ideas", "creating a playlist",
        "trying a new recipe", "daydreaming",
    ],
}

# Drift amount per monthly cycle
DRIFT_PER_MONTH = 0.01

# Soft reset: how strongly baseline pulls back toward original each month
# Acts like a rubber band — larger drift = stronger pull
BASELINE_PULL_STRENGTH = 0.3  # 30% of the gap is closed each month

# Alert threshold: flag when drift exceeds this portion of MAX_DRIFT
DRIFT_ALERT_THRESHOLD = 0.10  # Alert at 67% of MAX_DRIFT (0.10/0.15)


class CharacterEvolution:
    """Tracks slow personality evolution based on lived experience."""

    def __init__(self, original_baseline: Optional[Dict[str, float]] = None,
                 core_traits: Optional[List[str]] = None):
        self._original_baseline: Dict[str, float] = dict(original_baseline or {})
        self._current_baseline: Dict[str, float] = dict(original_baseline or {})
        self._core_traits: List[str] = list(core_traits or [])
        self._drift_history: List[dict] = []
        self._activity_counts: Dict[str, int] = {}  # Track activity frequencies
        self._last_evolution: Optional[datetime] = None

    def track_activity(self, activity_name: str):
        """Track activity for evolution calculations."""
        self._activity_counts[activity_name] = (
            self._activity_counts.get(activity_name, 0) + 1
        )

    def monthly_evolution(self, identity_facets: Dict[str, float],
                           relationship_trust: float,
                           avg_mood: str) -> Dict[str, float]:
        """Apply slow personality drift. Returns dict of changes made."""
        changes = {}
        now = datetime.now()

        # Calculate drift direction from activity patterns
        warmth_score = sum(
            self._activity_counts.get(a, 0)
            for a in DRIFT_INFLUENCES["warmth_up"]
        )
        calm_score = sum(
            self._activity_counts.get(a, 0)
            for a in DRIFT_INFLUENCES["calm_up"]
        )
        energy_score = sum(
            self._activity_counts.get(a, 0)
            for a in DRIFT_INFLUENCES["energy_up"]
        )
        creativity_score = sum(
            self._activity_counts.get(a, 0)
            for a in DRIFT_INFLUENCES["creativity_up"]
        )

        # Normalize scores
        total = max(1, warmth_score + calm_score + energy_score + creativity_score)

        # Apply drifts to baseline values
        drift_map = {
            "warmth": warmth_score / total * DRIFT_PER_MONTH,
            "calm": calm_score / total * DRIFT_PER_MONTH,
            "energy": energy_score / total * DRIFT_PER_MONTH,
            "creativity": creativity_score / total * DRIFT_PER_MONTH,
        }

        for key, drift in drift_map.items():
            if drift > 0 and key in self._current_baseline:
                original = self._original_baseline.get(key, 0.5)
                current = self._current_baseline[key]
                # Clamp within MAX_DRIFT of original
                new_val = min(
                    original + MAX_DRIFT,
                    max(original - MAX_DRIFT, current + drift)
                )
                if abs(new_val - current) > 0.001:
                    self._current_baseline[key] = round(new_val, 3)
                    changes[key] = round(new_val - current, 3)

        # Relationship depth can gently increase warmth
        if relationship_trust > 0.7 and "warmth" in self._current_baseline:
            original = self._original_baseline.get("warmth", 0.5)
            current = self._current_baseline["warmth"]
            bonus = 0.005
            new_val = min(original + MAX_DRIFT, current + bonus)
            if new_val > current:
                self._current_baseline["warmth"] = round(new_val, 3)
                changes["warmth"] = changes.get("warmth", 0) + round(bonus, 3)

        # Record drift
        if changes:
            self._drift_history.append({
                "date": now.isoformat(),
                "changes": changes,
                "activity_sample": dict(list(self._activity_counts.items())[:5]),
            })
            # Keep last 12 months
            if len(self._drift_history) > 12:
                self._drift_history = self._drift_history[-12:]

        # Soft reset: pull values without recent activity support back toward original
        # If a trait drifted up from warm activities but warm activities stopped,
        # the trait slowly returns toward the original baseline
        for key in list(self._current_baseline.keys()):
            original = self._original_baseline.get(key, 0.5)
            current = self._current_baseline[key]
            gap = current - original
            if abs(gap) < 0.002:
                continue
            # Check if this trait had supporting activity this month
            supported = key in changes and changes[key] * gap > 0  # Same direction
            if not supported and abs(gap) > 0.005:
                pull = gap * BASELINE_PULL_STRENGTH
                new_val = round(current - pull, 3)
                self._current_baseline[key] = new_val
                reset_amount = round(-pull, 3)
                if abs(reset_amount) > 0.001:
                    changes[f"{key}_reset"] = reset_amount

        # Reset activity counts for next period
        self._activity_counts = {}
        self._last_evolution = now

        return changes

    def get_current_baseline(self) -> Dict[str, float]:
        """Get the current (possibly drifted) emotional baseline."""
        return dict(self._current_baseline)

    def get_drift_summary(self) -> Dict[str, float]:
        """Get total drift from original per baseline value."""
        return {
            key: round(self._current_baseline.get(key, 0) - self._original_baseline.get(key, 0), 3)
            for key in self._original_baseline
            if abs(self._current_baseline.get(key, 0) - self._original_baseline.get(key, 0)) > 0.001
        }

    def get_drift_alerts(self) -> List[str]:
        """Check for significant personality drift that may warrant attention.

        Returns human-readable alerts for any trait that has drifted beyond
        DRIFT_ALERT_THRESHOLD from its original value.
        """
        alerts = []
        direction_labels = {
            "warmth": ("warmer", "colder"),
            "calm": ("calmer", "more anxious"),
            "energy": ("more energetic", "more lethargic"),
            "creativity": ("more creative", "less creative"),
        }
        for key in self._original_baseline:
            original = self._original_baseline[key]
            current = self._current_baseline.get(key, original)
            drift = current - original
            if abs(drift) >= DRIFT_ALERT_THRESHOLD:
                labels = direction_labels.get(key, ("higher", "lower"))
                direction = labels[0] if drift > 0 else labels[1]
                alerts.append(
                    f"Personality drift: becoming noticeably {direction} "
                    f"({key}: {original:.2f} → {current:.2f})"
                )
        return alerts

    def get_drift_narrative(self) -> Optional[str]:
        """Get a narrative description of personality evolution for context/digest.

        Returns None if drift is negligible.
        """
        drift = self.get_drift_summary()
        if not drift:
            return None
        direction_phrases = {
            "warmth": ("warmer and more open", "more guarded"),
            "calm": ("more centered", "more on edge"),
            "energy": ("more driven", "lower-energy"),
            "creativity": ("more creatively alive", "less inspired"),
        }
        parts = []
        for key, amount in sorted(drift.items(), key=lambda x: abs(x[1]), reverse=True):
            if abs(amount) < 0.005 or key.endswith("_reset"):
                continue
            phrases = direction_phrases.get(key)
            if phrases:
                direction = phrases[0] if amount > 0 else phrases[1]
                parts.append(direction)
        if not parts:
            return None
        return f"Lately becoming {' and '.join(parts[:2])}"

    # ============= Export / Serialize =============

    def export_state(self) -> dict:
        """Structured export for pipeline digest."""
        result = {}
        drift = self.get_drift_summary()
        if drift:
            result["personality_drift"] = drift
        narrative = self.get_drift_narrative()
        if narrative:
            result["drift_narrative"] = narrative
        alerts = self.get_drift_alerts()
        if alerts:
            result["drift_alerts"] = alerts
        return result

    def get_status(self) -> dict:
        """Status for API/debugging."""
        return {
            "original_baseline": self._original_baseline,
            "current_baseline": self._current_baseline,
            "drift": self.get_drift_summary(),
            "drift_history_count": len(self._drift_history),
            "tracked_activities": len(self._activity_counts),
            "last_evolution": self._last_evolution.isoformat() if self._last_evolution else None,
        }

    def to_dict(self) -> dict:
        """Serialize for DB storage."""
        return {
            "original_baseline": json.dumps(self._original_baseline),
            "current_baseline": json.dumps(self._current_baseline),
            "core_traits": json.dumps(self._core_traits),
            "drift_history": json.dumps(self._drift_history),
            "activity_counts": json.dumps(self._activity_counts),
            "last_evolution": self._last_evolution.isoformat() if self._last_evolution else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CharacterEvolution":
        """Deserialize from DB."""
        system = cls()
        if not data:
            return system

        raw = data.get("original_baseline", "{}")
        try:
            system._original_baseline = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (json.JSONDecodeError, TypeError):
            system._original_baseline = {}

        raw = data.get("current_baseline", "{}")
        try:
            system._current_baseline = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (json.JSONDecodeError, TypeError):
            system._current_baseline = {}

        raw = data.get("core_traits", "[]")
        try:
            system._core_traits = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            system._core_traits = []

        raw = data.get("drift_history", "[]")
        try:
            system._drift_history = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            system._drift_history = []

        raw = data.get("activity_counts", "{}")
        try:
            system._activity_counts = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (json.JSONDecodeError, TypeError):
            system._activity_counts = {}

        ts = data.get("last_evolution")
        if ts:
            try:
                system._last_evolution = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                pass

        return system
