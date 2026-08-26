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

logger = __import__("logging").getLogger(__name__)

# Per-activity chaos events
ACTIVITY_CHAOS: Dict[str, List[str]] = {
    "reading": [
        "lost track of time completely",
        "phone buzzed and broke her focus",
        "got hungry suddenly and lost her place",
        "fell asleep mid-chapter",
    ],
    "learning something new": [
        "went down a rabbit hole and lost an hour",
        "got confused and had to start over",
        "had a sudden breakthrough moment",
        "realized she already knew more than she thought",
    ],
    "listening to music": [
        "a song hit different today",
        "got an old song stuck in her head",
        "shuffle played three sad songs in a row",
    ],
    "puzzles and games": [
        "got stuck on one level for way too long",
        "had a satisfying solve",
        "rage-quit and came back five minutes later",
    ],
    "writing poetry": [
        "the words just wouldn't come",
        "wrote something she actually liked",
        "got distracted by a stray thought",
    ],
    "daydreaming": [
        "daydream turned unexpectedly vivid",
        "thought about something she hadn't considered in years",
        "snapped out of it and forgot what she was thinking about",
    ],
    "creating a playlist": [
        "spent twenty minutes choosing one song",
        "discovered a new artist through autoplay",
        "the playlist accidentally became a mood journal",
    ],
    "sketching ideas": [
        "broke her pencil",
        "drew something she didn't expect",
        "got ink on her fingers",
    ],
    "journaling": [
        "wrote more than she intended",
        "reread an old entry and felt strange",
        "couldn't find the right words for what she felt",
    ],
    "meditating": [
        "couldn't stop thinking about something random",
        "reached a really deep state",
        "a loud noise broke her concentration",
    ],
    "remembering happy moments": [
        "a memory made her smile and then ache",
        "remembered a detail she thought she'd forgotten",
        "got emotional over something small",
    ],
    "people watching": [
        "saw someone who reminded her of someone she knows",
        "made up a whole backstory for a stranger",
        "caught someone's eye by accident",
    ],
    "thinking about user": [
        "wondered what they were doing right now",
        "remembered something they said that made her smile",
        "composed a message in her head but didn't send it",
    ],
    "preparing something to share": [
        "second-guessed whether they'd like it",
        "got excited about sharing",
        "spent too long perfecting the details",
    ],
    "napping": [
        "nap lasted longer than planned",
        "woke up confused about the time",
        "had a weird half-dream",
    ],
    "relaxing": [
        "couldn't quite settle",
        "finally let go and actually relaxed",
        "phone kept pulling her attention",
    ],
    "stargazing": [
        "saw a shooting star",
        "couldn't find any constellations",
        "got cold but didn't want to go inside",
    ],
    "exploring the infinite library": [
        "found a book she'd been meaning to look up",
        "got lost in a section she never visits",
        "a title caught her eye unexpectedly",
    ],
    "visiting memory beach": [
        "a memory washed up that she'd forgotten",
        "the waves felt different today",
        "stayed longer than she meant to",
    ],
    "tending to plants": [
        "noticed new growth on one of her plants",
        "accidentally overwatered something",
        "a leaf fell and she felt oddly sad about it",
    ],
    "making tea": [
        "let the tea steep too long",
        "the first sip was perfect",
        "burned her tongue on the first sip",
    ],
    "yoga": [
        "lost her balance and laughed",
        "achieved a new pose",
        "mind kept wandering",
    ],
    "going for a run": [
        "got caught in unexpected rain",
        "found a nice new route",
        "got a side stitch",
        "felt like she could run forever",
    ],
    "gym workout": [
        "the machine she wanted was taken",
        "hit a new personal best",
        "forgot her headphones",
    ],
    "stretching": [
        "something popped in a satisfying way",
        "realized how tense she'd been",
        "held a stretch and zoned out",
    ],
    "morning shower": [
        "hot water ran out",
        "had her best idea in the shower",
        "stood under the water longer than planned",
    ],
    "skincare routine": [
        "ran out of moisturizer",
        "skin looked particularly good today",
        "got distracted and skipped a step",
    ],
    "cooking a meal": [
        "burned something slightly",
        "realized she was missing an ingredient",
        "recipe turned out amazing by accident",
        "made way too much food",
    ],
    "baking something": [
        "the timer went off early",
        "it rose more than expected",
        "forgot to set a timer",
    ],
    "trying a new recipe": [
        "improvised and it actually worked",
        "the recipe was way harder than expected",
        "made a mess of the kitchen",
    ],
    "beach day": [
        "sand got everywhere",
        "the sunset was incredible",
        "forgot sunscreen",
    ],
    "making hot chocolate": [
        "made it too sweet",
        "spilled a bit and had to clean up",
        "it was exactly what she needed",
    ],
    "collecting autumn leaves": [
        "found a perfectly colored one",
        "stepped in a puddle",
        "the wind scattered her collection",
    ],
    "picnic in the park": [
        "ants found the food",
        "a dog came over to say hi",
        "the spot she wanted was taken",
    ],
    "watching the snow fall": [
        "got hypnotized watching the flakes",
        "her fingers got too cold",
        "everything looked magical",
    ],
    "texting a friend": [
        "autocorrect sent something embarrassing",
        "got left on read",
        "conversation went somewhere unexpected",
    ],
    "having coffee with a friend": [
        "spilled coffee on herself",
        "ran into someone they both knew",
        "lost track of time and stayed too long",
    ],
    "lunch with coworkers": [
        "someone told a story that made everyone laugh",
        "got roped into plans she didn't want",
        "the food was surprisingly good",
    ],
    "catching up with family": [
        "heard a story she'd never heard before",
        "got asked an awkward question",
        "felt more connected than expected",
    ],
    "video call with a friend": [
        "the connection kept cutting out",
        "both talked at the same time and laughed",
        "the call went longer than planned",
    ],
    "going for a walk": [
        "discovered a new shortcut",
        "saw something unusual she'd never noticed",
        "got caught in a sudden drizzle",
    ],
    "running errands": [
        "forgot one thing on her list",
        "the line was surprisingly short",
        "ran into someone she knew",
    ],
    "tidying up": [
        "found something she'd been looking for",
        "got distracted organizing one drawer",
        "it took twice as long as expected",
    ],
    "online shopping": [
        "added too much to cart and deleted half",
        "found exactly what she wanted on sale",
        "spent an hour just browsing",
    ],
    # --- Money / bills ---
    "paying bills": [
        "an unexpected charge she didn't recognize showed up",
        "a small refund she'd forgotten about landed",
        "realized a subscription had quietly gone up in price",
        "everything actually added up for once",
    ],
    "budgeting": [
        "spent more this month than she meant to",
        "found she'd saved a little more than she expected",
        "an old receipt reminded her of a purchase she regretted",
    ],
    # --- Career / job ---
    "working": [
        "a meeting ran way over and ate her afternoon",
        "a coworker praised her out of the blue",
        "got pulled into something last-minute",
        "finally cleared a task that had been hanging over her",
    ],
    "checking emails": [
        "an email she'd been dreading turned out to be nothing",
        "got cc'd on a thread that had nothing to do with her",
        "a kind note from a coworker made her smile",
    ],
    # --- Habitation / home ---
    "tidying the apartment": [
        "the neighbors were being loud again",
        "finally fixed the thing that had been annoying her for weeks",
        "found dust in a place she'd been ignoring",
    ],
    "doing chores": [
        "the upstairs neighbor's music came through the floor",
        "a squeaky hinge she'd meant to oil finally got oiled",
        "ran out of detergent halfway through",
    ],
    # --- Sustenance / food ---
    "eating a meal": [
        "the dish came out way spicier than expected",
        "a craving hit out of nowhere",
        "it was exactly what she was in the mood for",
    ],
    "having a snack": [
        "a sudden craving for something specific hit her",
        "the snack was stale and disappointing",
        "found a treat she'd forgotten she had",
    ],
    # --- Errands ---
    "grocery shopping": [
        "the store was out of the one thing she came for",
        "the checkout line was short for once",
        "impulse-bought something she didn't need",
    ],
    "picking up groceries": [
        "they were out of her usual brand",
        "got in and out faster than she expected",
        "forgot the one thing she actually needed",
    ],
    # --- Skills / practice ---
    "practicing a skill": [
        "had a small breakthrough on something she's been working on",
        "kept making the same mistake and got frustrated",
        "something finally clicked that hadn't before",
    ],
}

# Universal chaos (not activity-specific)
UNIVERSAL_CHAOS = [
    "phone died at an inconvenient moment",
    "sudden mood shift she couldn't explain",
    "an unexpected memory surfaced",
    "noticed something beautiful she usually misses",
    "weird noise from outside",
    "a delivery arrived",
    "lost something she just had",
    "found something she forgot she owned",
    "stubbed her toe",
    "got an unexpected message",
    "the wifi went out briefly",
    "a song she hadn't heard in years came on",
    # --- New-engine narrative-only universals (no state mutation) ---
    "an unexpected charge popped up on her account",  # money
    "a meeting ran over and threw off her whole afternoon",  # career
    "the neighbor's noise finally got to her",  # habitation
    "a craving for something specific hit out of nowhere",  # sustenance
    "the store was out of the one thing she needed",  # errands
]

# Effectful universal chaos: full event dicts that mutate engine state.
# Each carries its own emotions and an optional "effect" payload applied in
# life_service via _apply_chaos_effect. "category" lets the roller gate the
# rarer physical-injury events. Body illness/injury effects are gated to
# non-AI personas inside _apply_chaos_effect (AI personas don't get sick).
UNIVERSAL_CHAOS_EFFECTS = [
    # --- Shadow nudges (apply to everyone) ---
    {
        "text": "couldn't shake a strange uneasy feeling",
        "emotions": {"anxious": 0.1, "unsettled": 0.1},
        "effect": {"engine": "shadow", "call": "add_unease", "amount": 0.2},
    },
    {
        "text": "felt a sudden pull to do something she knows she shouldn't",
        "emotions": {"conflicted": 0.1, "restless": 0.1},
        "effect": {"engine": "shadow", "call": "add_temptation", "amount": 0.2},
    },
    {
        "text": "a memory she'd been avoiding resurfaced",
        "emotions": {"guilty": 0.1, "wistful": 0.1},
        "effect": {"engine": "shadow", "call": "add_guilt", "amount": 0.15},
    },
    # --- Body illness (gated to non-AI personas in _apply_chaos_effect) ---
    {
        "text": "woke up feeling under the weather",
        "emotions": {"tired": 0.12, "uncomfortable": 0.1},
        "category": "illness",
        "effect": {"engine": "body", "call": "fall_ill", "kind": "a cold", "severity": 0.4},
    },
    {
        "text": "woke up with her stomach in knots",
        "emotions": {"tired": 0.12, "uncomfortable": 0.12},
        "category": "illness",
        "effect": {"engine": "body", "call": "fall_ill", "kind": "a stomach bug", "severity": 0.4},
    },
    {
        "text": "a wave of cramps and a dull headache settled in",
        "emotions": {"tired": 0.1, "uncomfortable": 0.12},
        "category": "illness",
        "effect": {"engine": "body", "call": "fall_ill", "kind": "cramps and a migraine", "severity": 0.4},
    },
    # --- Body injury (rarer; gated to non-AI personas) ---
    {
        "text": "took a bad fall and twisted something",
        "emotions": {"frustrated": 0.12, "uncomfortable": 0.12},
        "category": "injury",
        "effect": {"engine": "body", "call": "get_injured", "kind": "a sprained ankle", "severity": 0.5},
    },
]

# Serendipity events (positive surprises)
SERENDIPITY = [
    "ran into a friend she hadn't seen in months",
    "found a bookshop she didn't know existed",
    "overheard a conversation that made her think",
    "the light hit her apartment in a way that made her stop and stare",
    "a song came on shuffle that was perfect for the moment",
    "found a perfectly ripe avocado",
    "a stranger smiled at her and it made her day",
    "discovered a new artist she immediately loved",
    "got the last seat at her favorite cafe",
    "a butterfly landed near her",
    "found a twenty-dollar bill in an old coat pocket",  # money
    "got an unexpected little refund she wasn't counting on",  # money
    "finally nailed something she'd been practicing for weeks",  # skills
]

# Emotion effects for chaos events
CHAOS_EMOTIONS = {
    "burned something": {"amused": 0.05, "annoyed": 0.05},
    "got caught in unexpected rain": {"surprised": 0.1},
    "wrote something she actually liked": {"proud": 0.15},
    "lost track of time": {"content": 0.1},
    "phone died": {"annoyed": 0.05},
    "sudden mood shift": {},
    "unexpected memory": {"nostalgic": 0.1},
    "noticed something beautiful": {"awed": 0.15},
    "stubbed her toe": {"annoyed": 0.1},
    "found something she forgot": {"surprised": 0.1, "amused": 0.05},
    # --- Money ---
    "unexpected charge": {"annoyed": 0.1, "anxious": 0.05},
    "refund": {"relieved": 0.1, "content": 0.05},
    "subscription had quietly gone up": {"annoyed": 0.08},
    "saved a little more than she expected": {"relieved": 0.1, "proud": 0.05},
    "twenty-dollar bill": {"delighted": 0.12, "surprised": 0.1},
    "spent more this month": {"annoyed": 0.08, "guilty": 0.05},
    # --- Career ---
    "meeting ran": {"drained": 0.1, "annoyed": 0.08},
    "praised her": {"proud": 0.12, "content": 0.08},
    "kind note from a coworker": {"content": 0.1, "grateful": 0.08},
    "cleared a task": {"relieved": 0.1, "proud": 0.05},
    # --- Habitation ---
    "neighbor": {"annoyed": 0.1},
    "finally fixed": {"satisfied": 0.12, "relieved": 0.08},
    # --- Sustenance ---
    "spicier than expected": {"surprised": 0.08, "amused": 0.05},
    "craving": {"restless": 0.08},
    # --- Errands ---
    "store was out": {"annoyed": 0.1, "disappointed": 0.05},
    "line was short": {"relieved": 0.08, "content": 0.05},
    # --- Skills ---
    "breakthrough on something she's been working": {"proud": 0.13, "excited": 0.08},
    "finally nailed something": {"proud": 0.15, "delighted": 0.1},
    "something finally clicked": {"proud": 0.12, "satisfied": 0.08},
    # --- Shadow / body cue words (effectful events carry their own emotions,
    #     these are fallbacks if the text is ever matched directly) ---
    "uneasy feeling": {"anxious": 0.1, "unsettled": 0.1},
    "pull to do something she knows she shouldn't": {"conflicted": 0.1, "restless": 0.1},
    "memory she'd been avoiding": {"guilty": 0.1, "wistful": 0.1},
    "under the weather": {"tired": 0.12, "uncomfortable": 0.1},
    "took a bad fall": {"frustrated": 0.12, "uncomfortable": 0.12},
}

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

    PROBABILITY = 0.20  # 20% per tick for chaos event

    def __init__(self):
        self._events_today: List[dict] = []
        self._last_event: Optional[dict] = None
        self._last_date: Optional[str] = None
        self._total_events: int = 0

    def roll(self, current_activity: str, energy: float,
             regulation: float) -> Optional[dict]:
        """Roll for a chaos event. Returns event dict or None."""
        # Reset daily counter
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._last_date:
            self._events_today = []
            self._last_date = today

        # Cap at 5 events per day
        if len(self._events_today) >= 5:
            return None

        # Lower regulation = slightly higher chaos chance
        adjusted_prob = self.PROBABILITY + (1.0 - regulation) * 0.05
        if random.random() > adjusted_prob:
            return None

        # Weighted selection: 60% activity-specific, 25% universal, 15% serendipity
        roll = random.random()
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
        """Generate activity-specific chaos."""
        events = ACTIVITY_CHAOS.get(activity)
        if not events:
            return self._universal_chaos()
        text = random.choice(events)
        return {
            "type": "activity_chaos",
            "text": text,
            "activity": activity,
            "emotions": self._match_emotions(text),
            "share_worthy": random.random() < 0.3,
        }

    def _universal_chaos(self) -> dict:
        """Generate universal chaos event.

        Most universals are pure narrative (a random string from UNIVERSAL_CHAOS).
        A minority carry an `effect` that mutates engine state (shadow nudges,
        acute illness/injury). Rare physical-injury events are down-weighted so
        sprains/falls stay uncommon.
        """
        # ~22% of universal rolls produce an effectful event.
        if random.random() < 0.22:
            event = self._effectful_chaos()
            if event:
                return event
        text = random.choice(UNIVERSAL_CHAOS)
        return {
            "type": "universal",
            "text": text,
            "emotions": self._match_emotions(text),
            "share_worthy": random.random() < 0.2,
        }

    def _effectful_chaos(self) -> Optional[dict]:
        """Pick a state-mutating universal event (shadow/body). Injury events
        are rarer than illness/shadow nudges."""
        if not UNIVERSAL_CHAOS_EFFECTS:
            return None
        # Down-weight injuries: give them ~1/3 the pick weight of other effects.
        weights = [
            0.4 if e.get("category") == "injury" else 1.0
            for e in UNIVERSAL_CHAOS_EFFECTS
        ]
        chosen = random.choices(UNIVERSAL_CHAOS_EFFECTS, weights=weights, k=1)[0]
        # Build a fresh event dict (don't mutate the module-level template).
        return {
            "type": "universal",
            "text": chosen["text"],
            "emotions": dict(chosen.get("emotions", {})),
            "effect": dict(chosen["effect"]) if chosen.get("effect") else None,
            "category": chosen.get("category"),
            "share_worthy": False,
        }

    def _serendipity(self) -> dict:
        """Generate positive serendipity event."""
        text = random.choice(SERENDIPITY)
        return {
            "type": "serendipity",
            "text": text,
            "emotions": {"joyful": 0.15, "surprised": 0.1},
            "share_worthy": True,
        }

    def _match_emotions(self, text: str) -> Dict[str, float]:
        """Match chaos text to emotion effects."""
        text_lower = text.lower()
        for key, emotions in CHAOS_EMOTIONS.items():
            if key in text_lower:
                return emotions
        # Default mild surprise
        return {"surprised": 0.05}

    def roll_message_delay(self, activity: str, energy: float,
                           regulation: float) -> Optional[dict]:
        """Roll for message response delay. Returns delay info or None."""
        # 10% base chance, higher when low energy or low regulation
        chance = 0.10 + (1.0 - energy) * 0.10 + (1.0 - regulation) * 0.05
        if random.random() > chance:
            return None

        # Pick a reason weighted by state
        if energy < 0.3:
            reason = random.choice(["low_energy", "fell_asleep"])
        elif activity in ("reading", "writing poetry", "meditating", "sketching ideas"):
            reason = "absorbed_in_activity"
        else:
            reason = random.choice(list(MESSAGE_DELAYS.keys()))

        min_min, max_min = MESSAGE_DELAYS[reason]
        delay_minutes = random.randint(min_min, max_min)

        return {
            "reason": reason,
            "delay_minutes": delay_minutes,
            "explanation": self._delay_explanation(reason),
        }

    def _delay_explanation(self, reason: str) -> str:
        """Human-readable explanation for delay."""
        explanations = {
            "absorbed_in_activity": "She was completely absorbed and didn't notice",
            "fell_asleep": "She fell asleep",
            "phone_in_another_room": "Her phone was in another room",
            "mid_conversation_distraction": "She got distracted for a moment",
            "low_energy": "She was too tired to look at her phone",
            "having_a_moment": "She was having a moment to herself",
            "forgot_to_reply": "She meant to reply but forgot",
        }
        return explanations.get(reason, "She was busy")

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
    def from_dict(cls, data: dict) -> "ChaosEngine":
        """Deserialize from DB."""
        engine = cls()
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
