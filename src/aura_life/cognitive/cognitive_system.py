"""
Cognitive Engine

Tracks mental processes:
- Focus: attention quality, flow state
- Rumination: obsessive thought loops
- Inner Monologue: stray thoughts generated per tick
- Dream Processing: dream fragments from sleep
- Opinion Formation: accumulated stances on subjects
"""

import json
import logging
import random
from datetime import datetime
from typing import Dict, List, Optional

from ..models import (
    FocusState,
    RuminationLoop,
    InnerMonologueEntry,
    DreamFragment,
    Opinion,
)
from ..personas.parameters import PersonaParameters
from ..personas.pronoun_render import render_line
from ..settings import DEFAULT_SETTING, SettingSpec, get_setting
# Legacy name: the dream-fragment templates moved, unchanged, into the
# contemporary setting pack as DREAM_FRAGMENT_TEMPLATES in Task 9's fix round
# (ruling T9-R5) -- the system reads its persona's setting now; re-exported
# so an import from here keeps working.
from ..settings.contemporary import DREAM_FRAGMENT_TEMPLATES as DREAM_TEMPLATES  # noqa: F401

logger = logging.getLogger(__name__)

# Activity → focus quality modifiers. Legacy names: no longer read -- since
# Task 9's fix round (ruling T9-R5) the persona's setting tags its
# activities "focus" and "distracting"; kept so an import from here keeps
# working.
FOCUS_BOOST_ACTIVITIES = {"reading", "writing poetry", "meditating", "learning something new", "sketching ideas"}
FOCUS_DRAIN_ACTIVITIES = {"texting a friend", "scrolling", "watching TV"}

# Dream content pools
DREAM_TONES = ["anxious", "warm", "surreal", "bittersweet", "adventurous", "peaceful"]

# Monologue templates by source
MONOLOGUE_TEMPLATES = {
    "activity": [
        "Am I actually getting into this?",
        "This is kinda nice honestly",
        "I should do this more",
    ],
    "environment": [
        "The light's nice right now",
        "I like this time of day",
        "Something feels different out today",
    ],
    "rumination": [
        "Ugh, I keep coming back to that...",
        "Why is that still bugging me?",
        "I'm probably overthinking this",
    ],
    "idle": [
        "What should I do now?",
        "Wonder what they're doing right now...",
        "Brain's just wandering",
    ],
}


# ============= Conversation Triggers =============

COGNITIVE_CONVERSATION_TRIGGERS = {
    "intellectual_topic":      0.08,
    "philosophical_question":  0.10,
    "confusing_topic":        -0.05,
    "disagreement":            0.06,
    "defending_opinion":       0.08,
    "compliment_intelligence": 0.05,
    "creative_prompt":         0.06,
}

# ============= Personality Growth Multiplier =============
# Read from her trait text by aura_life.personas.parameters
# (COGNITIVE_GROWTH_TRAITS, PersonaParameters.cognitive_multiplier).

# ============= Rumination loops =============

#: The chance per cognitive tick that an active loop replays (+0.02 to its
#: intensity). Per persona, times PersonaParameters.rumination_rate.
RUMINATION_REPLAY_CHANCE = 0.1
#: How much a loop fades per cognitive tick, times the cognitive multiplier.
#: Per persona, divided by PersonaParameters.rumination_rate.
RUMINATION_DECAY = 0.005

# ============= Intrusive Thought Constants =============

INTRUSIVE_THOUGHT_CHANCE = 0.08  # 8% per tick (within the 30% monologue window)

INTRUSIVE_TEMPLATES = [
    "What if {theme}...",
    "{theme} — there it is again",
    "Can't shake the feeling... {theme}",
    "Why does this keep coming back? {theme}",
]


class CognitiveSystem:
    """Tracks attention, rumination, inner monologue, dreams, and opinions."""

    def __init__(self, core_traits: Optional[List[str]] = None,
                 intrusive_thought_themes: Optional[List[str]] = None,
                 rng=None,
                 params: Optional[PersonaParameters] = None,
                 setting: Optional[SettingSpec] = None):
        """``params``: her traits' engine parameters
        (:class:`~aura_life.personas.parameters.PersonaParameters`) --
        ``cognitive_multiplier``, and ``rumination_rate``, which sets how often
        a rumination loop replays and how slowly it fades. Without them
        ``core_traits`` is read for them.

        ``setting``: her setting pack (:class:`~aura_life.settings.SettingSpec`),
        whose ``dream_fragment_templates`` a dream fragment is told with,
        and whose "focus" / "distracting" tags say what sharpens and what
        scatters her focus.
        ``None`` -- the default -- is
        :data:`~aura_life.settings.DEFAULT_SETTING`'s."""
        if params is None:
            params = PersonaParameters.from_core_traits(core_traits)
        self._setting = setting if setting is not None else get_setting(DEFAULT_SETTING)
        # What sharpens and what scatters her focus (her setting's tags
        # "focus" and "distracting"; ruling T9-R5).
        self._focus_names = self._setting.names_tagged("focus")
        self._distracting_names = self._setting.names_tagged("distracting")
        self._focus = FocusState()
        self._rng = rng if rng is not None else random
        self._ruminations: List[RuminationLoop] = []
        self._monologue = InnerMonologueEntry()
        self._last_dream: Optional[DreamFragment] = None
        self._dream_residue_emotion: Optional[str] = None
        self._dream_residue_intensity: float = 0.0
        self._opinions: Dict[str, Opinion] = {}
        self._cognitive_multiplier = params.cognitive_multiplier
        self._rumination_rate = params.rumination_rate
        self._rumination_replay_chance = RUMINATION_REPLAY_CHANCE * self._rumination_rate
        self._intrusive_themes = intrusive_thought_themes or []

    @property
    def _rumination_decay(self) -> float:
        """How much a loop fades per tick: RUMINATION_DECAY times the cognitive
        multiplier (read live, as the fade always did), over her rumination
        rate."""
        return RUMINATION_DECAY * self._cognitive_multiplier / self._rumination_rate

    # ============= Tick =============

    def tick(self, current_activity: str, stress_level: float, sleep_quality: float, hunger: float, *,
             now: Optional[datetime] = None):
        """Per-tick update of cognitive modules; a passing thought is stamped
        ``now`` (the world instant ``LifeService`` passes, humanness Task 19:
        :meth:`get_inner_monologue` compares it; the host's clock when
        omitted)."""
        self._update_focus(current_activity, stress_level, sleep_quality, hunger)
        self._tick_ruminations()
        self._generate_monologue(current_activity, now=now)
        self._decay_dream_residue()

    # ============= Focus =============

    def _update_focus(self, activity: str, stress: float, sleep_quality: float, hunger: float):
        """Update focus quality from multiple inputs."""
        base = 0.7 + (self._cognitive_multiplier - 1.0) * 0.1  # Slightly higher baseline for analytical personas
        # Sleep quality impact
        base += (sleep_quality - 0.5) * 0.3
        # Stress reduces focus
        base -= stress * 0.2
        # Hunger reduces focus
        if hunger > 0.7:
            base -= 0.15
        # Activity type
        if activity in self._focus_names:
            base += 0.1
        elif activity in self._distracting_names:
            base -= 0.1
        # Rumination reduces focus
        if self._ruminations:
            strongest = max(r.intensity for r in self._ruminations)
            base -= strongest * 0.2

        self._focus.quality = max(0.0, min(1.0, base))

        # Flow state tracking
        if self._focus.quality > 0.8 and activity in self._focus_names:
            self._focus.flow_streak_minutes += 5  # Assume 5-min ticks
        else:
            self._focus.flow_streak_minutes = 0

    # ============= Rumination =============

    def on_conflict(self, topic: str):
        """Start a rumination loop from conflict."""
        self._add_rumination(topic, "conflict", 0.5)

    def on_failure(self, topic: str):
        """Start a rumination loop from failure."""
        self._add_rumination(topic, "failure", 0.4)

    def on_embarrassment(self, topic: str):
        """Start a rumination loop from embarrassment."""
        self._add_rumination(topic, "embarrassment", 0.6)

    def resolve_rumination(self, topic: str):
        """Mark a rumination as resolved."""
        self._ruminations = [r for r in self._ruminations if r.topic != topic]

    def _add_rumination(self, topic: str, trigger: str, intensity: float):
        """Add or intensify a rumination loop."""
        for r in self._ruminations:
            if r.topic == topic:
                r.intensity = min(1.0, r.intensity + 0.1)
                r.replay_count += 1
                return
        self._ruminations.append(RuminationLoop(
            topic=topic, intensity=intensity,
            started_at=datetime.now(), trigger=trigger,
        ))
        # Cap at 3 active
        if len(self._ruminations) > 3:
            self._ruminations.sort(key=lambda r: r.intensity, reverse=True)
            self._ruminations = self._ruminations[:3]

    def _tick_ruminations(self):
        """Decay ruminations, replay them occasionally (RUMINATION_DECAY,
        RUMINATION_REPLAY_CHANCE, both scaled by her rumination rate)."""
        for r in self._ruminations:
            r.intensity = max(0.0, r.intensity - self._rumination_decay)
            # Occasional replay
            if self._rng.random() < self._rumination_replay_chance:
                r.replay_count += 1
                r.intensity = min(1.0, r.intensity + 0.02)
        # Remove faded ones
        self._ruminations = [r for r in self._ruminations if r.intensity > 0.05]

    # ============= Inner Monologue =============

    def _generate_monologue(self, current_activity: str, *, now: Optional[datetime] = None):
        """Generate a passing thought (30% chance per tick), stamped ``now``
        (the host's clock when omitted)."""
        if self._rng.random() > 0.3:
            return
        now = now if now is not None else datetime.now()

        # Intrusive thought chance (before normal monologue)
        if self._intrusive_themes and self._rng.random() < INTRUSIVE_THOUGHT_CHANCE / 0.3:
            theme = self._rng.choice(self._intrusive_themes)
            template = self._rng.choice(INTRUSIVE_TEMPLATES)
            self._monologue = InnerMonologueEntry(
                thought=template.format(theme=theme),
                source="intrusive",
                timestamp=now,
            )
            return

        if self._ruminations and self._rng.random() < 0.4:
            source = "rumination"
        elif current_activity:
            source = "activity"
        elif self._rng.random() < 0.3:
            source = "environment"
        else:
            source = "idle"

        templates = MONOLOGUE_TEMPLATES.get(source, MONOLOGUE_TEMPLATES["idle"])
        self._monologue = InnerMonologueEntry(
            thought=self._rng.choice(templates),
            source=source,
            timestamp=now,
        )

    def get_inner_monologue(self, *, now: Optional[datetime] = None) -> Optional[str]:
        """Get current thought if recent: thought in the 10 minutes before
        ``now`` (the world instant its thoughts are stamped on -- pass it,
        humanness Task 19; the host's clock when omitted)."""
        if not self._monologue.thought:
            return None
        now = now if now is not None else datetime.now()
        if self._monologue.timestamp and (now - self._monologue.timestamp).total_seconds() > 600:
            return None  # Too old
        return self._monologue.thought

    # ============= Dreams =============

    def generate_dream(self, recent_activities: List[str], sleep_quality: float,
                       gender: Optional[str] = None) -> Optional[DreamFragment]:
        """Generate a dream fragment during sleep.

        `gender` renders the persona's pronoun in `DreamFragment.description`
        (see `pronoun_render.render_line`); omitted, it reads as they/them --
        this method has no `LifeService` call site yet to pass the real one
        through, so the lenient default matters."""
        vividness = 0.3 + self._rng.uniform(0.0, 0.4)
        # Poor sleep = more vivid/disturbing dreams
        if sleep_quality < 0.4:
            vividness += 0.2

        source = self._rng.choice(recent_activities) if recent_activities else "something forgotten"
        tone = self._rng.choice(DREAM_TONES)
        templates = self._setting.dream_fragment_templates
        if not templates:
            return None  # her setting tells no dream fragments
        template = self._rng.choice(templates)

        # Rumination bleeds into dreams
        residue_emotion = ""
        residue_intensity = 0.0
        if self._ruminations:
            strongest = max(self._ruminations, key=lambda r: r.intensity)
            if strongest.intensity > 0.3:
                source = strongest.topic
                tone = "anxious"
                residue_emotion = "uneasy"
                residue_intensity = strongest.intensity * 0.3
        elif tone in ("warm", "peaceful"):
            residue_emotion = "content"
            residue_intensity = 0.1

        dream = DreamFragment(
            description=render_line(template, gender=gender, source=source),
            vividness=min(1.0, vividness),
            emotional_tone=tone,
            source_material=source,
            residue_emotion=residue_emotion,
            residue_intensity=residue_intensity,
        )
        self._last_dream = dream
        self._dream_residue_emotion = residue_emotion
        self._dream_residue_intensity = residue_intensity
        return dream

    def get_dream_residue(self) -> Optional[dict]:
        """Get lingering dream emotion if recent."""
        if self._dream_residue_emotion and self._dream_residue_intensity > 0.05:
            return {"emotion": self._dream_residue_emotion, "intensity": self._dream_residue_intensity}
        return None

    def _decay_dream_residue(self):
        """Dream residue fades over time."""
        self._dream_residue_intensity = max(0.0, self._dream_residue_intensity - 0.01)
        if self._dream_residue_intensity < 0.01:
            self._dream_residue_emotion = None

    # ============= Opinions =============

    def form_opinion(self, subject: str, stance: str, basis: str = "experience",
                     salient_values: Optional[List[str]] = None):
        """Create or reinforce an opinion.

        Args:
            salient_values: Optional list of salient value names. If the subject
                relates to a core value, new opinions start stronger.
        """
        if subject in self._opinions:
            op = self._opinions[subject]
            op.confidence = min(1.0, op.confidence + 0.05)
            op.last_reinforced = datetime.now()
            if stance != op.stance:
                if op.confidence < 0.5:
                    # Weak/new opinion → conflicting experience weakens to mixed
                    op.stance = "mixed"
                    op.confidence = max(0.1, op.confidence - 0.1)
                else:
                    # Established opinion → dig in, confidence grows
                    op.confidence = min(1.0, op.confidence + 0.03)
        else:
            # Value-biased initial confidence: if subject text relates to a
            # salient value name, the opinion starts stronger
            initial_confidence = 0.3
            opinion_basis = basis
            if salient_values:
                subject_lower = subject.lower()
                for val_name in salient_values:
                    if val_name.lower() in subject_lower:
                        initial_confidence = 0.5
                        opinion_basis = "values"
                        break
            self._opinions[subject] = Opinion(
                subject=subject, stance=stance, confidence=initial_confidence,
                basis=opinion_basis, formed_at=datetime.now(),
            )
        # Cap at 20 opinions
        if len(self._opinions) > 20:
            sorted_ops = sorted(self._opinions.items(), key=lambda x: x[1].confidence)
            self._opinions = dict(sorted_ops[5:])  # Remove 5 weakest

    def get_opinions_for_context(self, limit: int = 3) -> List[Opinion]:
        """Get strongest/most recent opinions."""
        return sorted(self._opinions.values(), key=lambda o: o.confidence, reverse=True)[:limit]

    # ============= Conversation Triggers =============

    def process_conversation_trigger(self, trigger_type: str) -> None:
        """Process a conversation trigger that affects focus quality."""
        amount = COGNITIVE_CONVERSATION_TRIGGERS.get(trigger_type, 0.0)
        if amount == 0.0:
            return
        scaled = amount * self._cognitive_multiplier
        self._focus.quality = max(0.0, min(1.0, self._focus.quality + scaled))

    # ============= Activity / Message Hooks =============

    FOCUS_ACTIVITIES = {
        "reading": 0.03, "writing poetry": 0.04, "meditating": 0.05,
        "studying": 0.04, "journaling": 0.03, "sketching ideas": 0.03,
    }

    def on_activity(self, activity_name: str):
        """Mental activities sharpen focus."""
        boost = self.FOCUS_ACTIVITIES.get(activity_name, 0.0)
        if boost:
            self._focus.quality = min(1.0, self._focus.quality + boost)

    def on_user_message(self, text: str = ""):
        """Conversation keeps mind engaged."""
        self._focus.quality = min(1.0, self._focus.quality + 0.01)

    # ============= Export / Serialize =============

    def export_state(self) -> dict:
        """Structured export for pipeline digest."""
        return {
            "focus": {"quality": round(self._focus.quality, 2), "in_flow": self._focus.flow_streak_minutes > 15},
            "ruminations": [
                {"topic": r.topic, "intensity": round(r.intensity, 2)}
                for r in self._ruminations[:2]
            ],
            "inner_thought": self._monologue.thought if self._monologue.thought else None,
            "dream_residue": self.get_dream_residue(),
            "opinions": [
                {"subject": o.subject, "stance": o.stance}
                for o in self.get_opinions_for_context(2)
            ],
            "intrusive_themes": self._intrusive_themes[:3] if self._intrusive_themes else [],
        }

    def get_status(self) -> dict:
        """Status for API/debugging."""
        return {
            "focus_quality": round(self._focus.quality, 2),
            "flow_minutes": self._focus.flow_streak_minutes,
            "active_ruminations": len(self._ruminations),
            "current_thought": self._monologue.thought,
            "last_dream": self._last_dream.description if self._last_dream else None,
            "opinions_count": len(self._opinions),
            "intrusive_themes": self._intrusive_themes,
        }

    def to_dict(self) -> dict:
        """Serialize for DB storage."""
        return {
            "focus_quality": self._focus.quality,
            "focus_flow_streak": self._focus.flow_streak_minutes,
            "active_ruminations": json.dumps([
                {"topic": r.topic, "intensity": r.intensity, "trigger": r.trigger,
                 "started_at": r.started_at.isoformat() if r.started_at else None,
                 "replay_count": r.replay_count}
                for r in self._ruminations
            ]),
            "last_monologue": self._monologue.thought,
            "last_dream": self._last_dream.description if self._last_dream else "",
            "dream_residue_emotion": self._dream_residue_emotion,
            "dream_residue_intensity": self._dream_residue_intensity,
            "opinions": json.dumps([
                {"subject": o.subject, "stance": o.stance, "confidence": o.confidence,
                 "basis": o.basis, "formed_at": o.formed_at.isoformat() if o.formed_at else None,
                 "last_reinforced": o.last_reinforced.isoformat() if o.last_reinforced else None}
                for o in self._opinions.values()
            ]),
        }

    @classmethod
    def from_dict(cls, data: dict, core_traits: Optional[List[str]] = None,
                  intrusive_thought_themes: Optional[List[str]] = None,
                  rng=None, params: Optional[PersonaParameters] = None,
                  setting: Optional[SettingSpec] = None) -> "CognitiveSystem":
        """Deserialize from DB (the other arguments as in the constructor)."""
        system = cls(core_traits=core_traits, intrusive_thought_themes=intrusive_thought_themes, rng=rng,
                     params=params, setting=setting)
        if not data:
            return system
        system._focus.quality = data.get("focus_quality", 0.7)
        system._focus.flow_streak_minutes = data.get("focus_flow_streak", 0)
        # Load ruminations
        rum_raw = data.get("active_ruminations", "[]")
        try:
            rums = json.loads(rum_raw) if isinstance(rum_raw, str) else rum_raw
        except (json.JSONDecodeError, TypeError):
            rums = []
        system._ruminations = [
            RuminationLoop(
                topic=r.get("topic", ""), intensity=r.get("intensity", 0.0),
                trigger=r.get("trigger", ""),
                started_at=datetime.fromisoformat(r["started_at"]) if r.get("started_at") else None,
                replay_count=r.get("replay_count", 0),
            ) for r in rums
        ]
        system._monologue.thought = data.get("last_monologue", "")
        if data.get("last_dream"):
            system._last_dream = DreamFragment(description=data["last_dream"])
        system._dream_residue_emotion = data.get("dream_residue_emotion")
        system._dream_residue_intensity = data.get("dream_residue_intensity", 0.0)
        # Load opinions
        ops_raw = data.get("opinions", "[]")
        try:
            ops = json.loads(ops_raw) if isinstance(ops_raw, str) else ops_raw
        except (json.JSONDecodeError, TypeError):
            ops = []
        for o in ops:
            system._opinions[o["subject"]] = Opinion(
                subject=o["subject"], stance=o.get("stance", "mixed"),
                confidence=o.get("confidence", 0.3), basis=o.get("basis", "experience"),
                formed_at=datetime.fromisoformat(o["formed_at"]) if o.get("formed_at") else None,
                last_reinforced=datetime.fromisoformat(o["last_reinforced"]) if o.get("last_reinforced") else None,
            )
        return system

    # ============= Properties =============

    @property
    def focus(self) -> FocusState:
        return self._focus

    @property
    def ruminations(self) -> List[RuminationLoop]:
        return self._ruminations

    @property
    def opinions(self) -> Dict[str, Opinion]:
        return self._opinions
