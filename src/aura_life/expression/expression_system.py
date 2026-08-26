"""
Expression & Perception Engine

Tracks:
- Connection awareness: user online/offline, response timing, availability
- Communication style: formality, emoji usage, humor, vulnerability
- Style adapts based on interaction count and relationship depth
"""

import json
from datetime import datetime
from typing import List, Optional

from ..models import ConnectionState, CommunicationStyleState

logger = __import__("logging").getLogger(__name__)

# Interaction count thresholds for relationship stages
STAGE_THRESHOLDS = {
    "early": 0,
    "comfortable": 50,
    "deep": 200,
}

# Work hours (heuristic)
WORK_HOURS = set(range(9, 18))  # 9 AM - 5 PM

# Style hints per relationship stage
STYLE_HINTS = {
    "early": "Write in complete sentences. Be warm but slightly measured. You have your own views and share them honestly.",
    "comfortable": "Can use casual contractions, occasional lol/lmao, light emoji. Don't be afraid to disagree or push back.",
    "deep": "Use natural shorthand, inside jokes, sentence fragments. You can be blunt, challenge them, call out things you disagree with.",
}


class ExpressionSystem:
    """Tracks connection state and communication style adaptation."""

    def __init__(self):
        self._connection = ConnectionState()
        self._style = CommunicationStyleState()
        self._interaction_count: int = 0
        self._response_times: List[float] = []  # Recent response times in seconds

    # ============= Connection Awareness =============

    def on_user_message(self):
        """Update connection state when user sends a message."""
        now = datetime.now()

        # Track response time (time between our last known state and this message)
        if self._connection.last_message_at:
            gap = (now - self._connection.last_message_at).total_seconds()
            self._response_times.append(gap)
            self._response_times = self._response_times[-20:]  # Keep last 20
            self._connection.avg_response_time_seconds = (
                sum(self._response_times) / len(self._response_times)
            )

        self._connection.last_message_at = now
        self._connection.is_online = True
        self._connection.time_since_last_message_hours = 0.0
        self._interaction_count += 1

        # Late night detection
        hour = now.hour
        self._connection.late_night_chat = hour >= 1 and hour < 4

        # Work hours detection
        self._connection.likely_at_work = hour in WORK_HOURS and now.weekday() < 5

        # Update style based on interaction count
        self._update_relationship_stage()

    def tick(self):
        """Per-tick update for connection awareness."""
        now = datetime.now()
        if self._connection.last_message_at:
            gap = (now - self._connection.last_message_at).total_seconds() / 3600.0
            self._connection.time_since_last_message_hours = gap

            # Mark offline after 30 min of silence
            if gap > 0.5:
                self._connection.is_online = False

    # ============= Communication Style =============

    def _update_relationship_stage(self):
        """Update relationship stage based on interaction count."""
        if self._interaction_count >= STAGE_THRESHOLDS["deep"]:
            new_stage = "deep"
        elif self._interaction_count >= STAGE_THRESHOLDS["comfortable"]:
            new_stage = "comfortable"
        else:
            new_stage = "early"

        if new_stage != self._style.relationship_stage:
            old_stage = self._style.relationship_stage
            self._style.relationship_stage = new_stage
            logger.info(f"Relationship stage: {old_stage} → {new_stage}")

            # Adjust style parameters with stage
            if new_stage == "comfortable":
                self._style.formality = max(0.3, self._style.formality - 0.15)
                self._style.emoji_frequency = min(0.5, self._style.emoji_frequency + 0.1)
                self._style.humor_density = min(0.5, self._style.humor_density + 0.1)
                self._style.vulnerability_openness = min(0.5, self._style.vulnerability_openness + 0.1)
            elif new_stage == "deep":
                self._style.formality = max(0.1, self._style.formality - 0.10)
                self._style.emoji_frequency = min(0.6, self._style.emoji_frequency + 0.05)
                self._style.humor_density = min(0.7, self._style.humor_density + 0.1)
                self._style.vulnerability_openness = min(0.8, self._style.vulnerability_openness + 0.15)

        # Gradual openness growth with each interaction
        self._style.vulnerability_openness = min(
            1.0, self._style.vulnerability_openness + 0.001
        )

    def get_style_hint(self) -> str:
        """Get communication style hint for system prompt."""
        return STYLE_HINTS.get(self._style.relationship_stage, STYLE_HINTS["early"])

    def get_connection_context(self) -> Optional[str]:
        """Get connection awareness context for system prompt."""
        parts = []
        if self._connection.late_night_chat:
            parts.append("It's late at night — the vibe is more chill and personal.")
        elif self._connection.time_since_last_message_hours > 8:
            parts.append("It's been a while since you last talked.")
        if self._connection.likely_at_work:
            parts.append("They're probably at work right now.")
        return " ".join(parts) if parts else None

    # ============= Export / Serialize =============

    def export_state(self) -> dict:
        """Structured export for pipeline digest."""
        result = {
            "style_hint": self.get_style_hint(),
            "relationship_stage": self._style.relationship_stage,
        }
        conn_ctx = self.get_connection_context()
        if conn_ctx:
            result["connection_context"] = conn_ctx
        return result

    def get_status(self) -> dict:
        """Status for API/debugging."""
        return {
            "interaction_count": self._interaction_count,
            "relationship_stage": self._style.relationship_stage,
            "is_online": self._connection.is_online,
            "hours_since_last_message": round(self._connection.time_since_last_message_hours, 1),
            "late_night": self._connection.late_night_chat,
            "formality": round(self._style.formality, 2),
            "vulnerability": round(self._style.vulnerability_openness, 2),
            "avg_response_time_sec": round(self._connection.avg_response_time_seconds, 1),
        }

    def to_dict(self) -> dict:
        """Serialize for DB storage."""
        return {
            "interaction_count": self._interaction_count,
            "formality": self._style.formality,
            "avg_message_length": self._style.avg_message_length,
            "emoji_frequency": self._style.emoji_frequency,
            "humor_density": self._style.humor_density,
            "vulnerability_openness": self._style.vulnerability_openness,
            "relationship_stage": self._style.relationship_stage,
            "last_message_at": (
                self._connection.last_message_at.isoformat()
                if self._connection.last_message_at else None
            ),
            "avg_response_time": self._connection.avg_response_time_seconds,
            "response_times": json.dumps(self._response_times[-20:]),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExpressionSystem":
        """Deserialize from DB."""
        system = cls()
        if not data:
            return system

        system._interaction_count = data.get("interaction_count", 0)
        system._style.formality = data.get("formality", 0.7)
        system._style.avg_message_length = data.get("avg_message_length", "measured")
        system._style.emoji_frequency = data.get("emoji_frequency", 0.2)
        system._style.humor_density = data.get("humor_density", 0.2)
        system._style.vulnerability_openness = data.get("vulnerability_openness", 0.2)
        system._style.relationship_stage = data.get("relationship_stage", "early")

        ts = data.get("last_message_at")
        if ts:
            try:
                system._connection.last_message_at = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                pass

        system._connection.avg_response_time_seconds = data.get("avg_response_time", 0.0)

        raw = data.get("response_times", "[]")
        try:
            system._response_times = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            system._response_times = []

        return system
