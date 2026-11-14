"""
Expression & Perception Engine

Tracks:
- Connection awareness: user online/offline, response timing, availability
- Communication style: formality, emoji usage, humor, vulnerability
- Style: the persona's own communication traits plus one distance line by
  relationship depth (humanness Task 16b)
- Relationship depth, from disclosure reciprocity and time, regressing after
  a week of silence (:mod:`aura_life.expression.relationship`)
"""

import json
from datetime import datetime
from typing import Iterable, List, Optional

from ..models import ConnectionState, CommunicationStyleState
from .relationship import (
    CONTACT_DAY_GAIN,
    DISCLOSURE_GAIN,
    HER_DISCLOSURE,
    ABSENCE_AFTER_HOURS,
    IN_CONVERSATION_MINUTES,
    OPEN_DISCLOSURE_CAP,
    STAGE_DEPTHS,
    STAGES,
    regressed,
    silent_days,
    stage_for,
)

logger = __import__("logging").getLogger(__name__)

# Interaction count thresholds the relationship stages had before Task 16b
# (the stage is now read from depth, ``relationship.STAGE_DEPTHS``); kept for
# the record of what an old save's stage meant.
STAGE_THRESHOLDS = {
    "early": 0,
    "comfortable": 50,
    "deep": 200,
}

# Work hours (heuristic)
WORK_HOURS = set(range(9, 18))  # 9 AM - 5 PM

# One distance line per relationship stage (humanness Task 16b): how close
# she is to the user -- what she discloses, whether she teases, inside jokes.
# They set no register (no sentence form, slang or emoji): that is the
# persona's own ``communication_traits``.
DISTANCE_LINES = {
    "early": ("You are still getting to know them: keep what is personal for when they open up, "
              "and share your own views honestly."),
    "comfortable": ("You know each other a little: you can tease them, tell them a bit of your own life, "
                    "and disagree or push back."),
    "deep": ("You know each other well: inside jokes and shorthand between you, and you can be blunt "
             "and call out what you disagree with."),
}


def _trait_sentence(trait: str) -> str:
    """A communication trait as a sentence of the style hint."""
    text = " ".join(str(trait or "").split())
    if not text:
        return ""
    text = text[:1].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def _toward(value: float, step: float, bound: float) -> float:
    """``value`` moved by ``step`` toward ``bound``, never past it and never
    back: a value already past ``bound`` stays where it is."""
    if step >= 0.0:
        return max(value, min(bound, value + step))
    return min(value, max(bound, value + step))


class ExpressionSystem:
    """Tracks connection state and communication style adaptation."""

    def __init__(self, communication_traits: Iterable[str] = ()):
        self._connection = ConnectionState()
        self._style = CommunicationStyleState()
        self._interaction_count: int = 0
        self._response_times: List[float] = []  # Recent response times in seconds
        # The persona's own register (``PersonalityDefinition.communication_traits``)
        self._communication_traits: List[str] = [t for t in (communication_traits or ()) if str(t).strip()]
        # Relationship depth (Task 16b): 0..1, as of the last user turn
        self._depth: float = 0.0
        # Disclosures one side made that the other has not answered yet, 0..1
        self._user_open: float = 0.0
        self._her_open: float = 0.0
        # Hours of the absence the present conversation ended (None: none)
        self._reunion_hours: Optional[float] = None

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

        # Gradual openness growth with each interaction (the stage itself is
        # read from depth: note_user_turn)
        self._style.vulnerability_openness = min(
            1.0, self._style.vulnerability_openness + 0.001
        )

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

    def _set_stage(self, new_stage: str) -> None:
        """The relationship stage, read from depth. A deeper stage adjusts the
        style parameters as a stage reached by message count did, once per
        stage passed, each toward its stage's bound and never back (a value
        already past the bound stays: Task 16b fix round 1); a stage lost to
        silence leaves them as they are."""
        old_stage = self._style.relationship_stage
        if new_stage == old_stage:
            return
        self._style.relationship_stage = new_stage
        logger.info(f"Relationship stage: {old_stage} → {new_stage}")
        old_rank = STAGES.index(old_stage) if old_stage in STAGES else 0
        style = self._style
        for stage in STAGES[old_rank + 1:STAGES.index(new_stage) + 1]:
            if stage == "comfortable":
                style.formality = _toward(style.formality, -0.15, 0.3)
                style.emoji_frequency = _toward(style.emoji_frequency, 0.1, 0.5)
                style.humor_density = _toward(style.humor_density, 0.1, 0.5)
                style.vulnerability_openness = _toward(style.vulnerability_openness, 0.1, 0.5)
            elif stage == "deep":
                style.formality = _toward(style.formality, -0.10, 0.1)
                style.emoji_frequency = _toward(style.emoji_frequency, 0.05, 0.6)
                style.humor_density = _toward(style.humor_density, 0.1, 0.7)
                style.vulnerability_openness = _toward(style.vulnerability_openness, 0.15, 0.8)

    # ============= Relationship depth (Task 16b) =============

    @property
    def depth(self) -> float:
        """Relationship depth 0..1 as of the user's last turn (before any
        regression since): :meth:`depth_at` reads it at an instant."""
        return self._depth

    @property
    def reunion_hours(self) -> Optional[float]:
        """Hours of the absence the present conversation ended, or ``None``
        (the conversation began less than ``ABSENCE_AFTER_HOURS`` after the
        last one, or there is none yet)."""
        return self._reunion_hours

    def depth_at(self, now: datetime, last_turn_at: Optional[datetime]) -> float:
        """Depth at the world instant ``now``: regressed by the silence since
        the user's last turn (``relationship.regressed``)."""
        return regressed(self._depth, silent_days(now, last_turn_at))

    def note_user_turn(self, at: datetime, previous_at: Optional[datetime], disclosure: float = 0.0) -> None:
        """A user turn at the world instant ``at``, the one before it at
        ``previous_at`` (``None``: their first), with the user's
        ``disclosure`` 0..1: the silence before it regresses depth, a new
        contact day and a disclosure that answers one of hers deepen it, and
        the stage follows (``aura_life.expression.relationship``)."""
        new_day = True
        if previous_at is not None:
            gap_days = silent_days(at, previous_at)
            self._depth = regressed(self._depth, gap_days)
            new_day = at.date() != previous_at.date()
            gap_hours = gap_days * 24.0
            if gap_hours >= ABSENCE_AFTER_HOURS:
                self._reunion_hours = gap_hours
            elif gap_hours * 60.0 >= IN_CONVERSATION_MINUTES:
                self._reunion_hours = None
        else:
            self._reunion_hours = None
        if new_day:
            self._depth += CONTACT_DAY_GAIN * (1.0 - self._depth)
        given = max(0.0, min(1.0, float(disclosure or 0.0)))
        if given > 0.0:
            answered = min(given, self._her_open)
            self._her_open -= answered
            self._user_open = min(OPEN_DISCLOSURE_CAP, self._user_open + given - answered)
            self._depth += DISCLOSURE_GAIN * answered * (1.0 - self._depth)
        self._set_stage(stage_for(self._depth))

    def note_her_disclosure(self, at: datetime, last_turn_at: Optional[datetime]) -> None:
        """She told the user something of her own life (``mark_shared``): a
        whole disclosure, which deepens the bond as far as it answers one of
        theirs; the stage follows at ``at``."""
        answered = min(HER_DISCLOSURE, self._user_open)
        self._user_open -= answered
        self._her_open = min(OPEN_DISCLOSURE_CAP, self._her_open + HER_DISCLOSURE - answered)
        self._depth += DISCLOSURE_GAIN * answered * (1.0 - self._depth)
        self.refresh_stage(at, last_turn_at)

    def refresh_stage(self, now: datetime, last_turn_at: Optional[datetime]) -> None:
        """The stage from depth at ``now`` (a week of silence can lower it
        before the user's next turn)."""
        self._set_stage(stage_for(self.depth_at(now, last_turn_at)))

    def distance_line(self) -> str:
        """The style hint's distance line for the present stage."""
        return DISTANCE_LINES.get(self._style.relationship_stage, DISTANCE_LINES["early"])

    def get_style_hint(self) -> str:
        """Communication style hint for the system prompt: the persona's own
        communication traits, then one distance line by relationship depth
        (Task 16b; no register line of the library's own)."""
        parts = [_trait_sentence(t) for t in self._communication_traits]
        parts.append(self.distance_line())
        return " ".join(p for p in parts if p)

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
        """Status for API/debugging. Its ``depth`` is as of the user's last
        turn (no clock here); ``LifeService.get_status`` gives it now."""
        return {
            "interaction_count": self._interaction_count,
            "relationship_stage": self._style.relationship_stage,
            "depth": round(self._depth, 3),
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
            "depth_state": json.dumps({
                "depth": self._depth,
                "user_open": self._user_open,
                "her_open": self._her_open,
                "reunion_hours": self._reunion_hours,
            }),
        }

    @classmethod
    def from_dict(cls, data: dict, communication_traits: Iterable[str] = ()) -> "ExpressionSystem":
        """Deserialize from DB. A save from before Task 16b (no
        ``depth_state``) loads to the depth its stage begins at
        (``relationship.STAGE_DEPTHS``, ruling T16-R6)."""
        system = cls(communication_traits=communication_traits)
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

        depth_state = None
        try:
            raw_depth = data.get("depth_state")
            depth_state = json.loads(raw_depth) if isinstance(raw_depth, str) else raw_depth
        except (json.JSONDecodeError, TypeError):
            depth_state = None
        if isinstance(depth_state, dict):
            system._depth = float(depth_state.get("depth", 0.0) or 0.0)
            system._user_open = float(depth_state.get("user_open", 0.0) or 0.0)
            system._her_open = float(depth_state.get("her_open", 0.0) or 0.0)
            reunion = depth_state.get("reunion_hours")
            system._reunion_hours = float(reunion) if reunion is not None else None
        else:
            stage = system._style.relationship_stage
            system._depth = STAGE_DEPTHS.get(stage, 0.0)
            if stage not in STAGE_DEPTHS:
                system._style.relationship_stage = "early"

        return system
