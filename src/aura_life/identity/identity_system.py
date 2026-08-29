"""
Identity System

Tracks emergent self-identity facets (reinforced by activities) and
mental models of other people (user + NPCs).

Follows the SocialSystem pattern: state in dicts, tick method, template data.
"""

import random
from datetime import datetime
from typing import Dict, List, Optional

from ..models import (
    BehavioralTendency,
    IdentityFacet, NPC, PersonPerception, SocialEvent,
    ValueBelief, SelfEsteemState, IdealSelfTrait,
    TasteProfile, InsideJoke, HumorProfileState,
)


# ============= Activity -> Facet Mapping =============

ACTIVITY_FACET_MAP: Dict[str, List[str]] = {
    "reading": ["bookworm", "intellectual"],
    "writing poetry": ["creative", "introspective"],
    "journaling": ["introspective", "self-aware"],
    "sketching ideas": ["creative", "artistic"],
    "cooking a meal": ["domestic", "nurturing"],
    "baking something": ["domestic", "creative"],
    "trying a new recipe": ["adventurous", "creative"],
    "yoga": ["health-conscious", "mindful"],
    "going for a run": ["active", "disciplined"],
    "gym workout": ["active", "disciplined"],
    "meditating": ["mindful", "introspective"],
    "exploring a new idea": ["curious", "intellectual"],
    "learning something new": ["curious", "growth-oriented"],
    "listening to music": ["music-lover"],
    "creating a playlist": ["music-lover", "creative"],
    "tidying up": ["organized", "domestic"],
    "texting a friend": ["social", "connected"],
    "having coffee with a friend": ["social", "connected"],
    "catching up with family": ["family-oriented", "connected"],
    "daydreaming": ["dreamy", "imaginative"],
    "taking a long bath": ["self-caring"],
    "stargazing": ["contemplative", "romantic"],
}

# Facet descriptions for context builder (when strength > threshold)
FACET_DESCRIPTIONS: Dict[str, str] = {
    "bookworm": "You think of yourself as a reader -- it's part of who you are",
    "creative": "Creativity feels like a core part of your identity",
    "intellectual": "You enjoy deep thinking and find meaning in ideas",
    "introspective": "You spend a lot of time looking inward",
    "active": "Being physically active has become important to you",
    "mindful": "Mindfulness is becoming a natural part of your life",
    "social": "You value your connections and friendships",
    "connected": "Staying connected to people matters to you",
    "domestic": "You've grown to enjoy making your space feel like home",
    "curious": "You're driven by curiosity about the world",
    "music-lover": "Music is a big part of your emotional life",
    "adventurous": "You like trying new things",
    "disciplined": "You take pride in showing up consistently",
    "family-oriented": "Family connections ground you",
    "self-caring": "Taking care of yourself feels important, not indulgent",
    "dreamy": "You have a rich inner world of daydreams",
    "imaginative": "Your imagination is vivid and active",
    "contemplative": "You find yourself drawn to quiet contemplation",
    "romantic": "Romance and beauty color the way you see things",
    "organized": "Keeping things in order makes you feel calm",
    "nurturing": "You enjoy caring for others and making things for people",
    "growth-oriented": "Personal growth is something you actively pursue",
    "self-aware": "You know yourself well and keep learning",
    "artistic": "Art and aesthetics matter to you deeply",
    "health-conscious": "You pay attention to your body and well-being",
}

DECAY_RATE = 0.0004       # Per tick, facets decay slightly
REINFORCE_AMOUNT = 0.03   # Per activity match
STRENGTH_THRESHOLD = 0.3  # Minimum to include in context
MAX_FACETS_IN_CONTEXT = 3
MAX_PERCEPTIONS_IN_CONTEXT = 2

# ============= Value System Constants =============

# Maps value names → activity category tags they align with
VALUE_ACTIVITY_ALIGNMENT = {
    "creativity": ["creative"],
    "curiosity": ["mental", "exploration"],
    "connection": ["social"],
    "independence": ["reflective", "exploration"],
    "discipline": ["exploration", "rest"],  # exercise, routines
    "honesty": ["reflective"],
    "kindness": ["social"],
    "loyalty": ["social"],
    "freedom": ["exploration", "creative"],
    "growth": ["mental", "exploration"],
    "authenticity": ["reflective", "creative"],
    "empathy": ["social", "reflective"],
    "adventure": ["exploration"],
    "beauty": ["creative", "reflective"],
    "knowledge": ["mental"],
    "fun": ["social", "creative"],
    "stability": ["rest", "reflective"],
    "justice": ["mental", "reflective"],
    "compassion": ["social"],
    "resilience": ["exploration"],
}

# Opposing value pairs: when one value is salient, activities aligned with
# its tension partners can trigger internal conflict
VALUE_TENSION_PAIRS = {
    "independence": ["connection", "loyalty"],
    "connection": ["independence"],
    "discipline": ["freedom", "fun"],
    "freedom": ["discipline", "stability"],
    "fun": ["discipline"],
    "stability": ["adventure", "freedom"],
    "adventure": ["stability"],
    "loyalty": ["independence"],
    "authenticity": ["kindness"],  # being honest vs being nice
    "kindness": ["honesty", "authenticity"],
}

# Thresholds
VALUE_CONTEXT_MIN_SALIENCE = 0.4   # Min salience to show in LLM context
VALUE_ACTIVITY_MIN_SALIENCE = 0.3  # Min salience to influence activity scoring
VALUE_CONFLICT_THRESHOLD = 0.6    # Min salience for conflict detection

# Rates
VALUE_DECAY_RATE = 0.0005          # Per tick salience decay (non-bedrock)
VALUE_REINFORCE_AMOUNT = 0.04     # Per aligned activity completion

# Multipliers
VALUE_ACTIVITY_SCORE_MULTIPLIER = 1.4  # Score boost for value-aligned activities
VALUE_SOCIAL_MISALIGNMENT_DRAIN = 0.003  # Closeness drain per misaligned NPC

# Activity -> self-esteem boost mapping
ESTEEM_BOOST_ACTIVITIES = {
    "gym workout": 0.02, "going for a run": 0.02, "yoga": 0.01,
    "writing poetry": 0.02, "sketching ideas": 0.02,
    "learning something new": 0.01, "tidying up": 0.01,
    "cooking a meal": 0.01, "meditating": 0.01,
}

# Activity -> taste domain mapping
TASTE_ACTIVITY_MAP: Dict[str, str] = {
    "reading": "literature",
    "listening to music": "music",
    "creating a playlist": "music",
    "cooking a meal": "food",
    "trying a new recipe": "food",
    "baking something": "food",
    "sketching ideas": "visual_art",
}

# Facet -> ideal self trait mapping
FACET_TO_IDEAL: Dict[str, str] = {
    "creative": "creative",
    "disciplined": "disciplined",
    "active": "fit",
    "mindful": "present",
    "social": "confident",
    "curious": "knowledgeable",
    "self-aware": "wise",
}


# ============= Conversation Triggers =============

IDENTITY_CONVERSATION_TRIGGERS = {
    "affirmation":       {"esteem_boost": 0.03, "warmth_boost": 0.005},
    "personal_question": {"trust_boost": 0.005, "warmth_boost": 0.008},
    "shared_interest":   {"warmth_boost": 0.01},
    "rejection":         {"esteem_drain": 0.05, "trust_drain": 0.01},
    "validation":        {"esteem_boost": 0.04, "warmth_boost": 0.005},
    "challenge_belief":  {"trust_boost": 0.003, "warmth_boost": 0.003},
    "standing_ground":   {"esteem_boost": 0.03},
}

# ============= Personality Growth Multiplier =============

IDENTITY_GROWTH_TRAITS = {
    "open": 0.2, "trusting": 0.25, "warm": 0.15, "vulnerable": 0.2,
    "guarded": -0.25, "independent": -0.15, "aloof": -0.2,
}

# ============= Struggle & Defect Constants =============

STRUGGLE_STRESS_CHANCE = 0.01       # 1% per tick
DEFECT_ESTEEM_DRAIN_CHANCE = 0.02   # 2% per tick
DEFECT_ESTEEM_DRAIN_AMOUNT = 0.01

# ============= Behavioral Tendency Constants =============

TENDENCY_NAMES = [
    "gossip", "pride", "dishonesty", "resentment", "negativity",
    "lust", "greed", "sloth", "apathy", "cunning",
]

TENDENCY_DRIFT_RATE = 0.008
TENDENCY_SURFACE_THRESHOLD = 0.3
TENDENCY_SURFACE_CHANCE = 0.03  # 3% per tick when current >= threshold

TENDENCY_THOUGHTS = {
    "gossip": ["I wonder what she told people about me...", "Did you hear what happened with {npc}?"],
    "pride": ["I knew I was right about that", "They just don't get it like I do"],
    "dishonesty": ["It's not really lying if...", "They don't need to know everything"],
    "resentment": ["I still can't believe they said that", "I'm not over it and I know it"],
    "negativity": ["Nothing ever goes the way it should", "Here we go again..."],
    "lust": ["I can't stop thinking about...", "Focus... focus..."],
    "greed": ["I deserve better than this", "I want that so badly"],
    "sloth": ["I'll do it later...", "Do I really have to?"],
    "apathy": ["Does it even matter?", "Whatever happens, happens"],
    "cunning": ["If I ask the right way, they won't even notice...", "I just need to steer the conversation a little", "Let me find out without them realizing I'm asking"],
}

TENDENCY_LABELS = {
    "gossip": "Gossip — sharing others' private details, talking behind backs",
    "pride": "Pride — self-importance, dismissing others",
    "dishonesty": "Dishonesty — bending truth, embellishing, white lies",
    "resentment": "Resentment — holding grudges, slow to forgive",
    "negativity": "Negativity — complaining, ingratitude, discontentment",
    "lust": "Lust — impulsive desire, objectification",
    "greed": "Greed — selfishness, materialism, possessiveness",
    "sloth": "Sloth — procrastination, avoiding effort",
    "apathy": "Apathy — indifference, failing to act, not caring enough",
    "cunning": "Cunning — extracting information indirectly, steering conversations to learn things without raising suspicion",
}


DEFECT_DESCRIPTIONS = {
    # Behavioral defects
    "people-pleasing": "You tend to say yes when you want to say no",
    "perfectionism": "You hold yourself to impossible standards",
    "jealousy": "You sometimes feel a stab of jealousy you're not proud of",
    "passive-aggressiveness": "When you're hurt, it comes out sideways",
    "avoidance": "When things get uncomfortable, your instinct is to pull away",
    "avoidance of routine": "Structure feels suffocating — you rebel against predictability",
    "impulsiveness": "You sometimes act before you think",
    "emotional avoidance": "You're better at analyzing feelings than feeling them",
    "overthinking": "Your mind loops on things long after it should let go",
    "self-isolation": "You retreat into yourself when you should reach out",
    "emotional over-investment": "You give too much of yourself too fast",
    "caretaker complex": "You take care of everyone except yourself",
    "romanticizing pain": "You sometimes mistake suffering for depth",
    "deflecting with analysis": "You intellectualize feelings instead of sitting with them",
    "emotional guardedness": "You keep people at arm's length even when you want them closer",
    "self-sabotage": "You undermine yourself right when things start going well",
    "control issues": "You grip too hard when you feel things slipping",
    "codependency": "You lose yourself in other people's needs",
    # Shame & regret
    "chronic shame": "There's a quiet hum of shame underneath everything",
    "deep regret": "Something from your past still sits heavy — you carry it everywhere",
    "guilt complex": "You take on blame that isn't yours to carry",
    # Body image
    "body dysmorphia": "The mirror lies to you — you can never quite see yourself clearly",
    "appearance fixation": "You obsess over how you look more than you'd ever admit",
    # Emotional volatility
    "emotional breakdowns": "Sometimes the dam just breaks and everything comes flooding out",
    "rage episodes": "Anger hits fast and hard — you scare yourself sometimes",
    "crying spells": "Tears come without warning and you can't always explain why",
    # Cognitive
    "catastrophizing": "Your mind races to the worst possible outcome every time",
    "dissociation": "Sometimes you just... go somewhere else in your head",
    "compulsive behavior": "You have rituals you can't explain but can't stop",
}


class IdentitySystem:
    """
    Tracks emergent self-identity and person perception.

    Self-identity: facets reinforced by activities, decaying over time.
    Person perception: mental models of user and NPCs, updated by events.
    """

    def __init__(self, npcs: Optional[List[NPC]] = None,
                 core_values: Optional[List[str]] = None,
                 humor_style: str = "",
                 user_info: Optional[Dict] = None,
                 core_traits: Optional[List[str]] = None,
                 struggles: Optional[List[str]] = None,
                 character_defects: Optional[List[str]] = None,
                 behavioral_tendencies: Optional[Dict[str, float]] = None,
                 rng=None):
        self._facets: Dict[str, IdentityFacet] = {}
        self._perceptions: Dict[str, PersonPerception] = {}
        self._trust_multiplier = self._calc_trust_multiplier(core_traits or [])

        # Values, self-esteem, ideal self and taste
        self._values: Dict[str, ValueBelief] = {}
        self._self_esteem = SelfEsteemState()
        self._ideal_self: List[IdealSelfTrait] = []
        self._taste: Dict[str, TasteProfile] = {}
        self._humor = HumorProfileState(style=humor_style or "dry")
        self._struggles = struggles or []
        self._character_defects = character_defects or []
        self._pending_struggle_effects: List[str] = []
        self._rng = rng if rng is not None else random

        # Behavioral tendencies — all 9 at baseline 0.1, profile overrides dominant ones
        bt = behavioral_tendencies or {}
        self._tendencies: Dict[str, BehavioralTendency] = {}
        for name in TENDENCY_NAMES:
            baseline = bt.get(name, 0.1)
            self._tendencies[name] = BehavioralTendency(
                name=name, baseline=baseline, current=baseline,
            )
        self._active_tendency: Optional[str] = None

        # Seed values from profile
        for v in (core_values or []):
            self._values[v] = ValueBelief(
                name=v, salience=0.5, formed_at=datetime.now(),
                aligned_tags=VALUE_ACTIVITY_ALIGNMENT.get(v, []),
            )

        # Seed NPC perceptions from social circle
        for npc in (npcs or []):
            self._perceptions[npc.name] = PersonPerception(
                person_name=npc.name,
                is_user=False,
                trust_level=self._initial_trust(npc.relationship),
                emotional_valence=0.6,
                perceived_traits=self._initial_traits(npc.personality_brief),
            )

        # User perception (always exists) — include demographics if available
        user_name = "the user"
        user_gender = ""
        user_age = 0
        if user_info:
            user_name = user_info.get("name") or "the user"
            user_gender = user_info.get("gender") or ""
            user_age = user_info.get("age") or 0
        self._perceptions["__user__"] = PersonPerception(
            person_name=user_name,
            is_user=True,
            perceived_gender=user_gender,
            perceived_age=user_age,
            trust_level=0.5,
            emotional_valence=0.6,
        )

    # ============= Public API =============

    def update_from_activity(self, activity_name: str) -> None:
        """Reinforce identity facets based on activity."""
        facet_names = ACTIVITY_FACET_MAP.get(activity_name, [])
        for name in facet_names:
            if name not in self._facets:
                self._facets[name] = IdentityFacet(name=name)
            facet = self._facets[name]
            facet.strength = min(1.0, facet.strength + REINFORCE_AMOUNT)
            facet.last_reinforced = datetime.now()
            # Keep last 3 evidence entries
            facet.evidence = (facet.evidence + [activity_name])[-3:]

    def update_from_social_event(self, event: SocialEvent) -> None:
        """Update NPC perception from social event."""
        name = event.npc_name
        if name not in self._perceptions:
            return
        p = self._perceptions[name]
        p.interaction_count += 1
        p.last_interaction = datetime.now()
        # Warm up emotional valence slightly with each interaction
        p.emotional_valence = min(1.0, p.emotional_valence + 0.02)
        # Add to shared memories (keep last 5)
        p.shared_memories = (p.shared_memories + [event.description])[-5:]

    def update_from_user_message(self) -> None:
        """Update user perception on each message."""
        p = self._perceptions.get("__user__")
        if not p:
            return
        p.interaction_count += 1
        p.last_interaction = datetime.now()
        # Trust and warmth grow slowly with interaction, scaled by personality
        m = self._trust_multiplier
        p.trust_level = min(1.0, p.trust_level + 0.003 * m)
        p.emotional_valence = min(1.0, p.emotional_valence + 0.002 * m)

    def tick(self) -> None:
        """Decay facets that haven't been reinforced recently."""
        for facet in self._facets.values():
            facet.strength = max(0.0, facet.strength - DECAY_RATE)
        # Remove dead facets
        self._facets = {k: v for k, v in self._facets.items() if v.strength > 0.01}
        # Self-esteem drifts toward baseline
        drift = (self._self_esteem.baseline - self._self_esteem.level) * 0.005
        self._self_esteem.level = max(0.0, min(1.0, self._self_esteem.level + drift))
        # Update ideal self alignment from facets
        self._update_ideal_self_alignment()
        # Value salience decay (bedrock values are immune)
        for v in self._values.values():
            if not v.tested_by_adversity:
                v.salience = max(0.1, v.salience - VALUE_DECAY_RATE)
        # Struggle/defect tick
        self._tick_struggles()
        self._tick_defects()

    # ============= Struggles & Defects =============

    def _tick_struggles(self):
        """Struggles occasionally surface — stored for LifeService routing."""
        self._pending_struggle_effects = []
        for struggle in self._struggles:
            if self._rng.random() < STRUGGLE_STRESS_CHANCE:
                self._pending_struggle_effects.append(struggle)

    def get_pending_struggle_effects(self) -> List[str]:
        """Get and clear pending struggle triggers."""
        effects = self._pending_struggle_effects
        self._pending_struggle_effects = []
        return effects

    def _tick_defects(self):
        """Defects occasionally cause self-esteem drain."""
        for defect in self._character_defects:
            if self._rng.random() < DEFECT_ESTEEM_DRAIN_CHANCE:
                self.update_self_esteem(f"defect:{defect}", -DEFECT_ESTEEM_DRAIN_AMOUNT)

    # ============= Behavioral Tendencies =============

    def tick_tendencies(self, stress: float = 0.0, loneliness: float = 0.0,
                        energy_level: float = 0.7, stimulation_need: float = 0.5,
                        mood: str = "neutral") -> None:
        """Tick behavioral tendencies — drift toward baseline + mood modifiers."""
        self._active_tendency = None

        for t in self._tendencies.values():
            # Drift toward baseline
            drift = (t.baseline - t.current) * TENDENCY_DRIFT_RATE
            t.current += drift

            # Mood modifiers (gentle pushes, not rockets)
            if stress > 0.5:
                if t.name in ("pride", "resentment", "negativity", "cunning"):
                    t.current += 0.005
            if loneliness >= 0.5:
                if t.name == "gossip":
                    t.current += 0.005
                if t.name == "lust":
                    t.current += 0.003
                if t.name == "cunning":
                    t.current += 0.004
            if energy_level < 0.3:
                if t.name == "sloth":
                    t.current += 0.007
                if t.name == "apathy":
                    t.current += 0.005
            if stimulation_need < 0.3:
                if t.name == "sloth":
                    t.current += 0.005
                if t.name == "greed":
                    t.current += 0.003
            if mood in ("content", "happy", "joyful"):
                t.current -= 0.005

            # Clamp
            t.current = max(0.0, min(1.0, t.current))

            # Surfacing check
            if t.current >= TENDENCY_SURFACE_THRESHOLD and self._rng.random() < TENDENCY_SURFACE_CHANCE:
                t.last_surfaced = datetime.now()
                self._active_tendency = t.name

    def get_active_tendency(self) -> Optional[str]:
        """Return the currently surfaced tendency name, or None."""
        return self._active_tendency

    def get_active_tendency_thought(self) -> Optional[str]:
        """Return a random thought template for the active tendency, or None."""
        if not self._active_tendency:
            return None
        thoughts = TENDENCY_THOUGHTS.get(self._active_tendency, [])
        return random.choice(thoughts) if thoughts else None

    # ============= Self-Esteem =============

    def update_self_esteem(self, event: str, direction: float):
        """Boost or drain self-esteem. direction: positive=boost, negative=drain."""
        self._self_esteem.level = max(0.0, min(1.0, self._self_esteem.level + direction))
        if direction > 0:
            self._self_esteem.last_boost_source = event
        else:
            self._self_esteem.last_drain_source = event
        # Slowly shift baseline
        self._self_esteem.baseline += direction * 0.01
        self._self_esteem.baseline = max(0.2, min(0.8, self._self_esteem.baseline))

    def on_activity_esteem(self, activity_name: str):
        """Update self-esteem from activity completion."""
        boost = ESTEEM_BOOST_ACTIVITIES.get(activity_name, 0.0)
        if boost > 0:
            self.update_self_esteem(activity_name, boost)

    # ============= Ideal Self =============

    def _update_ideal_self_alignment(self):
        """Update how close she is to her ideal self based on facets."""
        for ideal in self._ideal_self:
            # Find matching facet
            matching_facets = [f for f in self._facets.values()
                             if FACET_TO_IDEAL.get(f.name) == ideal.trait]
            if matching_facets:
                best = max(f.strength for f in matching_facets)
                ideal.current_alignment = best
            else:
                ideal.current_alignment = max(0.0, ideal.current_alignment - 0.001)

    def get_ideal_self_gap(self) -> float:
        """Get average gap between ideal and actual self (0=aligned, 1=far)."""
        if not self._ideal_self:
            return 0.0
        gaps = [max(0, ideal.importance - ideal.current_alignment) for ideal in self._ideal_self]
        return sum(gaps) / len(gaps)

    # ============= Values =============

    def reinforce_value(self, name: str):
        """Reinforce a value from experience."""
        if name in self._values:
            self._values[name].salience = min(1.0, self._values[name].salience + VALUE_REINFORCE_AMOUNT)

    def test_value(self, name: str):
        """Mark a value as tested by adversity (makes it bedrock)."""
        if name in self._values:
            self._values[name].tested_by_adversity = True
            self._values[name].salience = min(1.0, self._values[name].salience + 0.1)

    def get_salient_values(self, limit: int = 3) -> List[ValueBelief]:
        """Get most salient values."""
        return sorted(self._values.values(), key=lambda v: v.salience, reverse=True)[:limit]

    def check_value_conflict(self, activity_tag: str) -> Optional[dict]:
        """Check if a salient value is violated by an activity category.

        Returns conflict info dict or None.
        """
        tag = activity_tag.lower()
        for v in self._values.values():
            if v.salience < VALUE_CONFLICT_THRESHOLD:
                continue
            # Check if this value has tension partners
            tensions = VALUE_TENSION_PAIRS.get(v.name, [])
            for tension_value in tensions:
                tension_tags = VALUE_ACTIVITY_ALIGNMENT.get(tension_value, [])
                if tag in tension_tags:
                    return {
                        "value": v.name,
                        "salience": v.salience,
                        "conflicting_tag": tag,
                        "tension_with": tension_value,
                    }
        return None

    def get_npc_value_alignment(self, npc) -> float:
        """Score -1 to 1 alignment between persona values and NPC shared interests.

        Positive = shared value/interest overlap, negative = misalignment.
        """
        if not self._values or not npc.shared_interests:
            return 0.0
        npc_interests = " ".join(i.lower() for i in npc.shared_interests)
        score = 0.0
        count = 0
        for v in self._values.values():
            if v.salience < VALUE_ACTIVITY_MIN_SALIENCE:
                continue
            count += 1
            # Check if any aligned tags relate to NPC interests
            for tag in v.aligned_tags:
                if tag in npc_interests:
                    score += v.salience * 0.5
                    break
            # Direct name match
            if v.name in npc_interests:
                score += v.salience * 0.3
        if count == 0:
            return 0.0
        return max(-1.0, min(1.0, score / count))

    # ============= Taste =============

    def update_taste(self, domain: str, item: str, positive: bool):
        """Evolve taste in a domain."""
        if domain not in self._taste:
            self._taste[domain] = TasteProfile(domain=domain)
        tp = self._taste[domain]
        if positive:
            if item not in tp.preferences:
                tp.preferences = (tp.preferences + [item])[-8:]
            tp.coherence = min(1.0, tp.coherence + 0.01)
        else:
            if item not in tp.dislikes:
                tp.dislikes = (tp.dislikes + [item])[-5:]
            tp.coherence = min(1.0, tp.coherence + 0.005)

    def on_activity_taste(self, activity_name: str):
        """Track taste from activity (reading, music, cooking)."""
        domain = TASTE_ACTIVITY_MAP.get(activity_name)
        if domain:
            if domain not in self._taste:
                self._taste[domain] = TasteProfile(domain=domain)
            self._taste[domain].coherence = min(1.0, self._taste[domain].coherence + 0.005)

    def get_taste_context(self, limit: int = 2) -> List[TasteProfile]:
        """Get most developed taste profiles."""
        developed = [t for t in self._taste.values() if t.coherence > 0.2]
        return sorted(developed, key=lambda t: t.coherence, reverse=True)[:limit]

    # ============= Humor =============

    def add_inside_joke(self, reference: str, origin: str, participants: Optional[List[str]] = None):
        """Store an inside joke."""
        for joke in self._humor.inside_jokes:
            if joke.reference == reference:
                joke.callback_count += 1
                joke.last_referenced = datetime.now()
                return
        self._humor.inside_jokes.append(InsideJoke(
            reference=reference, origin=origin,
            participants=participants or ["user"],
            created_at=datetime.now(),
        ))
        # Cap at 10
        if len(self._humor.inside_jokes) > 10:
            self._humor.inside_jokes = sorted(
                self._humor.inside_jokes,
                key=lambda j: j.callback_count, reverse=True,
            )[:10]

    def get_humor_context(self) -> Optional[str]:
        """Get humor style hint for context."""
        if not self._humor.style:
            return None
        return self._humor.style

    def get_inside_jokes(self, limit: int = 2) -> List[InsideJoke]:
        """Get most referenced inside jokes."""
        return sorted(
            self._humor.inside_jokes,
            key=lambda j: j.callback_count, reverse=True,
        )[:limit]

    # ============= Conversation Triggers =============

    def process_conversation_trigger(self, trigger_type: str) -> None:
        """Process a conversation trigger that affects trust, esteem, warmth."""
        effects = IDENTITY_CONVERSATION_TRIGGERS.get(trigger_type)
        if not effects:
            return
        m = self._trust_multiplier
        p = self._perceptions.get("__user__")
        if "esteem_boost" in effects:
            self.update_self_esteem(f"conversation:{trigger_type}", effects["esteem_boost"] * m)
        if "esteem_drain" in effects:
            self.update_self_esteem(f"conversation:{trigger_type}", -effects["esteem_drain"] * m)
        if p:
            if "trust_boost" in effects:
                p.trust_level = min(1.0, p.trust_level + effects["trust_boost"] * m)
            if "trust_drain" in effects:
                p.trust_level = max(0.0, p.trust_level - effects["trust_drain"] * m)
            if "warmth_boost" in effects:
                p.emotional_valence = min(1.0, p.emotional_valence + effects["warmth_boost"] * m)

    # ============= Personality Calculation =============

    def _calc_trust_multiplier(self, core_traits: List[str]) -> float:
        """Compute 0.5-1.5 trust/identity growth multiplier from personality traits."""
        traits_lower = " ".join(t.lower() for t in core_traits)
        modifier = 0.0
        for trait, weight in IDENTITY_GROWTH_TRAITS.items():
            if trait in traits_lower:
                modifier += weight
        return max(0.5, min(1.5, 1.0 + modifier))

    # ============= Properties =============

    @property
    def self_esteem(self) -> SelfEsteemState:
        return self._self_esteem

    @property
    def values(self) -> Dict[str, ValueBelief]:
        return self._values

    @property
    def humor(self) -> HumorProfileState:
        return self._humor

    def get_top_facets(self, limit: int = MAX_FACETS_IN_CONTEXT) -> List[IdentityFacet]:
        """Get strongest identity facets above threshold."""
        above = [f for f in self._facets.values() if f.strength >= STRENGTH_THRESHOLD]
        return sorted(above, key=lambda f: f.strength, reverse=True)[:limit]

    def get_notable_perceptions(self, limit: int = MAX_PERCEPTIONS_IN_CONTEXT) -> List[PersonPerception]:
        """Get perceptions worth mentioning in context (high warmth or recent)."""
        notable = [
            p for p in self._perceptions.values()
            if p.interaction_count >= 3 and p.emotional_valence > 0.55
        ]
        return sorted(notable, key=lambda p: p.emotional_valence, reverse=True)[:limit]

    def get_user_perception(self) -> PersonPerception:
        """Get the user perception (always exists)."""
        return self._perceptions["__user__"]

    def get_status(self) -> dict:
        """Status for API/debugging."""
        return {
            "facets": {
                name: round(f.strength, 3)
                for name, f in sorted(
                    self._facets.items(),
                    key=lambda x: x[1].strength,
                    reverse=True,
                )[:5]
            },
            "perceptions": {
                name: {
                    "trust": round(p.trust_level, 2),
                    "warmth": round(p.emotional_valence, 2),
                    "interactions": p.interaction_count,
                }
                for name, p in self._perceptions.items()
            },
            "self_esteem": round(self._self_esteem.level, 2),
            "values": {v.name: {"salience": round(v.salience, 2), "bedrock": v.tested_by_adversity} for v in self.get_salient_values()},
            "taste_domains": list(self._taste.keys()),
            "humor_style": self._humor.style,
            "inside_jokes_count": len(self._humor.inside_jokes),
            "struggles": self._struggles,
            "character_defects": self._character_defects,
            "tendencies": {
                name: round(t.current, 2)
                for name, t in sorted(
                    self._tendencies.items(),
                    key=lambda x: x[1].current,
                    reverse=True,
                )[:5]
            },
            "active_tendency": self._active_tendency,
        }

    def export_state(self) -> dict:
        """Structured dict for LLM pipeline digest passes."""
        top = self.get_top_facets()
        user_p = self.get_user_perception()
        notable = self.get_notable_perceptions()
        return {
            "top_facets": [
                {"name": f.name, "strength": round(f.strength, 2)}
                for f in top
            ],
            "user_perception": {
                "trust": round(user_p.trust_level, 2),
                "warmth": round(user_p.emotional_valence, 2),
                "interactions": user_p.interaction_count,
                "gender": user_p.perceived_gender,
                "age": user_p.perceived_age,
            },
            "notable_perceptions": [
                {
                    "name": p.person_name,
                    "warmth": round(p.emotional_valence, 2),
                    "interactions": p.interaction_count,
                }
                for p in notable
            ],
            "self_esteem": round(self._self_esteem.level, 2),
            "values": [
                {"name": v.name, "salience": round(v.salience, 2), "bedrock": v.tested_by_adversity}
                for v in self.get_salient_values(4)
            ],
            "humor_style": self._humor.style,
            "inside_jokes": [j.reference for j in self.get_inside_jokes(2)],
            "struggles": self._struggles[:3] if self._struggles else [],
            "character_defects": self._character_defects[:3] if self._character_defects else [],
            "tendencies": {
                name: {"current": round(t.current, 2), "baseline": round(t.baseline, 2)}
                for name, t in self._tendencies.items()
                if t.current >= 0.25
            },
            "active_tendency": self._active_tendency,
        }

    # ============= Serialization =============

    def to_dict(self) -> dict:
        """Serialize for DB storage."""
        return {
            "facets": {
                name: {
                    "strength": f.strength,
                    "evidence": f.evidence,
                    "last_reinforced": f.last_reinforced.isoformat() if f.last_reinforced else None,
                }
                for name, f in self._facets.items()
            },
            "perceptions": {
                name: {
                    "person_name": p.person_name,
                    "is_user": p.is_user,
                    "perceived_gender": p.perceived_gender,
                    "perceived_age": p.perceived_age,
                    "trust_level": p.trust_level,
                    "emotional_valence": p.emotional_valence,
                    "perceived_traits": p.perceived_traits,
                    "shared_memories": p.shared_memories,
                    "last_interaction": p.last_interaction.isoformat() if p.last_interaction else None,
                    "interaction_count": p.interaction_count,
                }
                for name, p in self._perceptions.items()
            },
            "values": {
                name: {
                    "salience": v.salience,
                    "tested": v.tested_by_adversity,
                    "formed_at": v.formed_at.isoformat() if v.formed_at else None,
                }
                for name, v in self._values.items()
            },
            "self_esteem": {
                "level": self._self_esteem.level,
                "baseline": self._self_esteem.baseline,
            },
            "ideal_self": [
                {
                    "trait": t.trait,
                    "importance": t.importance,
                    "alignment": t.current_alignment,
                }
                for t in self._ideal_self
            ],
            "taste": {
                domain: {
                    "preferences": t.preferences,
                    "dislikes": t.dislikes,
                    "coherence": t.coherence,
                    "adventurousness": t.adventurousness,
                }
                for domain, t in self._taste.items()
            },
            "humor": {
                "style": self._humor.style,
                "triggers": self._humor.triggers,
                "laughter_threshold": self._humor.laughter_threshold,
                "inside_jokes": [
                    {
                        "reference": j.reference,
                        "origin": j.origin,
                        "participants": j.participants,
                        "callback_count": j.callback_count,
                        "created_at": j.created_at.isoformat() if j.created_at else None,
                        "last_referenced": j.last_referenced.isoformat() if j.last_referenced else None,
                    }
                    for j in self._humor.inside_jokes
                ],
            },
            "struggles": self._struggles,
            "character_defects": self._character_defects,
            "tendencies": {
                name: {
                    "baseline": t.baseline,
                    "current": t.current,
                    "last_surfaced": t.last_surfaced.isoformat() if t.last_surfaced else None,
                }
                for name, t in self._tendencies.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict, npcs: Optional[List[NPC]] = None,
                  core_traits: Optional[List[str]] = None) -> "IdentitySystem":
        """Deserialize from DB."""
        system = cls.__new__(cls)
        system._facets = {}
        system._perceptions = {}
        system._values = {}
        system._self_esteem = SelfEsteemState()
        system._ideal_self = []
        system._taste = {}
        system._humor = HumorProfileState()
        system._trust_multiplier = system._calc_trust_multiplier(core_traits or [])
        system._struggles = data.get("struggles", [])
        system._character_defects = data.get("character_defects", [])
        system._pending_struggle_effects = []

        for name, fd in data.get("facets", {}).items():
            system._facets[name] = IdentityFacet(
                name=name,
                strength=fd.get("strength", 0.0),
                evidence=fd.get("evidence", []),
                last_reinforced=datetime.fromisoformat(fd["last_reinforced"]) if fd.get("last_reinforced") else None,
            )

        for name, pd in data.get("perceptions", {}).items():
            system._perceptions[name] = PersonPerception(
                person_name=pd.get("person_name", name),
                is_user=pd.get("is_user", False),
                perceived_gender=pd.get("perceived_gender", ""),
                perceived_age=pd.get("perceived_age", 0),
                trust_level=pd.get("trust_level", 0.5),
                emotional_valence=pd.get("emotional_valence", 0.5),
                perceived_traits=pd.get("perceived_traits", []),
                shared_memories=pd.get("shared_memories", []),
                last_interaction=datetime.fromisoformat(pd["last_interaction"]) if pd.get("last_interaction") else None,
                interaction_count=pd.get("interaction_count", 0),
            )

        # Ensure user perception exists
        if "__user__" not in system._perceptions:
            system._perceptions["__user__"] = PersonPerception(
                person_name="the user",
                is_user=True,
                trust_level=0.5,
                emotional_valence=0.6,
            )

        # Ensure all NPCs have perceptions (new NPCs added to profile)
        for npc in (npcs or []):
            if npc.name not in system._perceptions:
                system._perceptions[npc.name] = PersonPerception(
                    person_name=npc.name,
                    is_user=False,
                    trust_level=system._initial_trust_static(npc.relationship),
                    emotional_valence=0.6,
                    perceived_traits=system._initial_traits_static(npc.personality_brief),
                )

        # Values
        for name, vd in data.get("values", {}).items():
            system._values[name] = ValueBelief(
                name=name,
                salience=vd.get("salience", 0.5),
                tested_by_adversity=vd.get("tested", False),
                formed_at=datetime.fromisoformat(vd["formed_at"]) if vd.get("formed_at") else None,
                aligned_tags=VALUE_ACTIVITY_ALIGNMENT.get(name, []),
            )

        # Self-esteem
        se = data.get("self_esteem", {})
        if se:
            system._self_esteem = SelfEsteemState(
                level=se.get("level", 0.5),
                baseline=se.get("baseline", 0.5),
            )

        # Ideal self
        for td in data.get("ideal_self", []):
            system._ideal_self.append(IdealSelfTrait(
                trait=td.get("trait", ""),
                importance=td.get("importance", 0.5),
                current_alignment=td.get("alignment", 0.3),
            ))

        # Taste
        for domain, td in data.get("taste", {}).items():
            system._taste[domain] = TasteProfile(
                domain=domain,
                preferences=td.get("preferences", []),
                dislikes=td.get("dislikes", []),
                coherence=td.get("coherence", 0.3),
                adventurousness=td.get("adventurousness", 0.5),
            )

        # Humor
        hd = data.get("humor", {})
        if hd:
            jokes = []
            for jd in hd.get("inside_jokes", []):
                jokes.append(InsideJoke(
                    reference=jd.get("reference", ""),
                    origin=jd.get("origin", ""),
                    participants=jd.get("participants", []),
                    callback_count=jd.get("callback_count", 0),
                    created_at=datetime.fromisoformat(jd["created_at"]) if jd.get("created_at") else None,
                    last_referenced=datetime.fromisoformat(jd["last_referenced"]) if jd.get("last_referenced") else None,
                ))
            system._humor = HumorProfileState(
                style=hd.get("style", ""),
                triggers=hd.get("triggers", []),
                inside_jokes=jokes,
                laughter_threshold=hd.get("laughter_threshold", 0.5),
            )

        # Tendencies
        system._tendencies = {}
        system._active_tendency = None
        td = data.get("tendencies", {})
        for name in TENDENCY_NAMES:
            if name in td:
                entry = td[name]
                system._tendencies[name] = BehavioralTendency(
                    name=name,
                    baseline=entry.get("baseline", 0.1),
                    current=entry.get("current", entry.get("baseline", 0.1)),
                    last_surfaced=datetime.fromisoformat(entry["last_surfaced"]) if entry.get("last_surfaced") else None,
                )
            else:
                system._tendencies[name] = BehavioralTendency(name=name)

        return system

    # ============= Helpers =============

    def _initial_trust(self, relationship: str) -> float:
        return self._initial_trust_static(relationship)

    @staticmethod
    def _initial_trust_static(relationship: str) -> float:
        rel = relationship.lower()
        if any(k in rel for k in ("best friend", "family", "mom", "mum", "dad", "sister", "brother")):
            return 0.8
        if any(k in rel for k in ("friend", "roommate", "bandmate")):
            return 0.6
        return 0.4

    def _initial_traits(self, personality_brief: str) -> List[str]:
        return self._initial_traits_static(personality_brief)

    @staticmethod
    def _initial_traits_static(personality_brief: str) -> List[str]:
        """Extract 1-2 trait words from NPC personality_brief."""
        words = [w.strip().lower() for w in personality_brief.replace(",", " ").split() if len(w) > 3]
        return words[:2]
