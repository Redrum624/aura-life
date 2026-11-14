"""
Chaos & Entropy Engine

Cross-cutting randomness injection into every engine:
- Activity chaos: unexpected twists during activities
- Serendipity: delightful surprises
- Message delays: realistic "person with a life" timing
- Universal chaos: random life events
"""

import json
import random
from datetime import datetime
from typing import Dict, List, Optional

from ..personas.parameters import PersonaParameters
from ..personas.pronoun_render import render_line
from ..settings import DEFAULT_SETTING, SettingSpec, get_setting
# Legacy names: the event pools and their emotion table moved, unchanged, into
# the contemporary setting pack (aura_life.settings.contemporary) in Task 9 --
# the engine reads its persona's setting now; re-exported so an import from
# here keeps working.
from ..settings.contemporary import (  # noqa: F401
    ACTIVITY_CHAOS,
    CHAOS_EMOTIONS,
    SERENDIPITY,
    UNIVERSAL_CHAOS,
    UNIVERSAL_CHAOS_EFFECTS,
)

logger = __import__("logging").getLogger(__name__)

# Message delay reasons and ranges (min_minutes, max_minutes)
MESSAGE_DELAYS = {
    "absorbed_in_activity": (5, 30),
    "fell_asleep": (60, 180),
    "phone_in_another_room": (10, 45),
    "mid_conversation_distraction": (2, 10),
    "low_energy": (30, 90),
    "having_a_moment": (15, 60),
    "forgot_to_reply": (60, 240),
}


class ChaosEngine:
    """Cross-cutting randomness injection system."""

    PROBABILITY = 0.20  # 20% per tick for chaos event (times her openness's chaos_event_scale)

    def __init__(self, rng=None, params: Optional[PersonaParameters] = None,
                 setting: Optional[SettingSpec] = None):
        """``rng``: optional ``random.Random``. ``None`` -- the default --
        is a fresh, unseeded ``random.Random()`` (never the module), so a
        bare ``ChaosEngine()`` still works and shares no draw sequence with
        any other instance or the module.

        ``params``: her traits' engine parameters
        (:class:`~aura_life.personas.parameters.PersonaParameters`); her
        openness scales PROBABILITY (``params.chaos_event_scale``). Without
        them, PROBABILITY as it is.

        ``setting``: her setting pack (:class:`~aura_life.settings.SettingSpec`),
        whose ``activity_chaos`` (an activity's twists), ``universal_chaos``,
        ``universal_chaos_effects`` and ``serendipity`` (what can happen
        whatever she is doing) and ``chaos_emotions`` this engine draws from.
        ``None`` -- the default -- is
        :data:`~aura_life.settings.DEFAULT_SETTING`'s. A pool the setting
        leaves empty is never drawn from: a roll that would land on it comes
        back empty-handed."""
        self._events_today: List[dict] = []
        self._last_event: Optional[dict] = None
        self._last_date: Optional[str] = None
        self._total_events: int = 0
        self._rng = rng if rng is not None else random.Random()
        self._chaos_event_scale = params.chaos_event_scale if params is not None else 1.0
        self._setting = setting if setting is not None else get_setting(DEFAULT_SETTING)

    @property
    def _probability(self) -> float:
        """Her chance of a chaos event per roll, before regulation's share:
        PROBABILITY (read live) times her openness's scale."""
        return self.PROBABILITY * self._chaos_event_scale

    def roll(self, current_activity: str, energy: float,
             regulation: float, *, now: Optional[datetime] = None) -> Optional[dict]:
        """Roll for a chaos event. Returns event dict or None. The daily cap
        is per day of ``now`` (her local world time, ``LifeService`` passes
        it, humanness Task 19; the host's clock when omitted)."""
        # Reset daily counter
        today = (now if now is not None else datetime.now()).strftime("%Y-%m-%d")
        if today != self._last_date:
            self._events_today = []
            self._last_date = today

        # Cap at 5 events per day
        if len(self._events_today) >= 5:
            return None

        # Lower regulation = slightly higher chaos chance
        adjusted_prob = self._probability + (1.0 - regulation) * 0.05
        if self._rng.random() > adjusted_prob:
            return None

        # Weighted selection: 60% activity-specific, 25% universal, 15% serendipity
        roll = self._rng.random()
        if roll < 0.60:
            event = self._activity_chaos(current_activity)
        elif roll < 0.85:
            event = self._universal_chaos()
        else:
            event = self._serendipity()

        if event:
            self._events_today.append(event)
            self._last_event = event
            self._total_events += 1

        return event

    def _activity_chaos(self, activity: str) -> Optional[dict]:
        """Generate activity-specific chaos (a twist from her setting's
        ``activity_chaos``; a universal event when the activity has none)."""
        events = self._setting.activity_chaos.get(activity)
        if not events:
            return self._universal_chaos()
        text = self._rng.choice(events)
        return {
            "type": "activity_chaos",
            "text": text,
            "activity": activity,
            "emotions": self._match_emotions(text),
            "share_worthy": self._rng.random() < 0.3,
        }

    def _universal_chaos(self) -> Optional[dict]:
        """Generate universal chaos event.

        Most universals are pure narrative (a random string from her
        setting's ``universal_chaos``). A minority carry an `effect` that
        mutates engine state (shadow nudges, acute illness/injury; her
        setting's ``universal_chaos_effects``). Rare physical-injury events
        are down-weighted so sprains/falls stay uncommon. None when the
        setting has no narrative universal to fall back on.
        """
        # ~22% of universal rolls produce an effectful event.
        if self._rng.random() < 0.22:
            event = self._effectful_chaos()
            if event:
                return event
        pool = self._setting.universal_chaos
        if not pool:
            return None
        text = self._rng.choice(pool)
        return {
            "type": "universal",
            "text": text,
            "emotions": self._match_emotions(text),
            "share_worthy": self._rng.random() < 0.2,
        }

    def _effectful_chaos(self) -> Optional[dict]:
        """Pick a state-mutating universal event (shadow/body). Injury events
        are rarer than illness/shadow nudges."""
        effects = self._setting.universal_chaos_effects
        if not effects:
            return None
        # Down-weight injuries: give them ~1/3 the pick weight of other effects.
        weights = [
            0.4 if e.get("category") == "injury" else 1.0
            for e in effects
        ]
        chosen = self._rng.choices(effects, weights=weights, k=1)[0]
        # Build a fresh event dict (don't mutate the setting's template).
        return {
            "type": "universal",
            "text": chosen["text"],
            "emotions": dict(chosen.get("emotions", {})),
            "effect": dict(chosen["effect"]) if chosen.get("effect") else None,
            "category": chosen.get("category"),
            "share_worthy": False,
        }

    def _serendipity(self) -> Optional[dict]:
        """Generate positive serendipity event (from her setting's
        ``serendipity``; None when it has none)."""
        pool = self._setting.serendipity
        if not pool:
            return None
        text = self._rng.choice(pool)
        return {
            "type": "serendipity",
            "text": text,
            "emotions": {"joyful": 0.15, "surprised": 0.1},
            "share_worthy": True,
        }

    def _match_emotions(self, text: str) -> Dict[str, float]:
        """Match chaos text to emotion effects (her setting's
        ``chaos_emotions``: the first key found in the text, in order)."""
        text_lower = text.lower()
        for key, emotions in self._setting.chaos_emotions.items():
            if key in text_lower:
                return emotions
        # Default mild surprise
        return {"surprised": 0.05}

    def roll_message_delay(self, activity: str, energy: float,
                           regulation: float, gender: Optional[str] = None) -> Optional[dict]:
        """Roll for message response delay. Returns delay info or None.

        `gender` renders the persona's pronoun in "explanation" (see
        `_delay_explanation`); omitted, it reads as they/them -- this method
        has no LifeService call site yet to pass the real one through, so the
        lenient default matters."""
        # 10% base chance, higher when low energy or low regulation
        chance = 0.10 + (1.0 - energy) * 0.10 + (1.0 - regulation) * 0.05
        if self._rng.random() > chance:
            return None

        # Pick a reason weighted by state
        if energy < 0.3:
            reason = self._rng.choice(["low_energy", "fell_asleep"])
        elif activity in ("reading", "writing poetry", "meditating", "sketching ideas"):
            reason = "absorbed_in_activity"
        else:
            reason = self._rng.choice(list(MESSAGE_DELAYS.keys()))

        min_min, max_min = MESSAGE_DELAYS[reason]
        delay_minutes = self._rng.randint(min_min, max_min)

        return {
            "reason": reason,
            "delay_minutes": delay_minutes,
            "explanation": self._delay_explanation(reason, gender),
        }

    def _delay_explanation(self, reason: str, gender: Optional[str] = None) -> str:
        """Human-readable explanation for delay."""
        explanations = {
            "absorbed_in_activity": "{Subj} {was} completely absorbed and didn't notice",
            "fell_asleep": "{Subj} fell asleep",
            "phone_in_another_room": "{Poss} phone was in another room",
            "mid_conversation_distraction": "{Subj} got distracted for a moment",
            "low_energy": "{Subj} {was} too tired to look at {poss} phone",
            "having_a_moment": "{Subj} {was} having a moment to {refl}",
            "forgot_to_reply": "{Subj} meant to reply but forgot",
        }
        template = explanations.get(reason, "{Subj} {was} busy")
        return render_line(template, gender=gender)

    # ============= Export / Serialize =============

    def export_state(self) -> dict:
        """Structured export for pipeline digest."""
        result = {}
        if self._last_event:
            result["last_chaos_event"] = self._last_event.get("text", "")
            result["last_chaos_type"] = self._last_event.get("type", "")
        if self._events_today:
            result["today_events"] = [
                e.get("text", "") for e in self._events_today[-3:]
            ]
        result["events_today"] = len(self._events_today)
        return result

    def get_status(self) -> dict:
        """Status for API/debugging."""
        return {
            "events_today": len(self._events_today),
            "total_events": self._total_events,
            "last_event": self._last_event,
        }

    def to_dict(self) -> dict:
        """Serialize for DB storage."""
        return {
            "events_today": json.dumps([
                {"type": e.get("type", ""), "text": e.get("text", "")}
                for e in self._events_today
            ]),
            "last_event_text": self._last_event.get("text", "") if self._last_event else "",
            "last_date": self._last_date or "",
            "total_events": self._total_events,
        }

    @classmethod
    def from_dict(cls, data: dict, rng=None, params: Optional[PersonaParameters] = None,
                  setting: Optional[SettingSpec] = None) -> "ChaosEngine":
        """Deserialize from DB (``rng``, ``params`` and ``setting`` as in
        the constructor)."""
        engine = cls(rng=rng, params=params, setting=setting)
        if not data:
            return engine

        raw = data.get("events_today", "[]")
        try:
            engine._events_today = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            engine._events_today = []

        last_text = data.get("last_event_text", "")
        if last_text:
            engine._last_event = {"text": last_text, "type": "restored"}

        engine._last_date = data.get("last_date", "")
        engine._total_events = data.get("total_events", 0)

        return engine
