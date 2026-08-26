"""
Social System

Manages NPC interactions, social events, and friend activity.
Follows the DesireSystem pattern: state that ticks, templates, dice rolls.
"""

import json
import random
from datetime import datetime
from typing import Dict, List, Optional

from ..models import (
    NPC, SocialEvent,
    RelationshipArc, SocialObligation, SocialConflict,
    FriendGroup, SocialBatteryState,
)


# ============= Event Templates =============

EVENT_TEMPLATES = {
    "text_received": [
        "Got a text from {name} — {topic}",
        "{name} sent a funny meme",
        "{name} texted to check in",
        "{name} shared a link she thought was interesting",
        "{name} sent a voice note rambling about {topic}",
    ],
    "hangout": [
        "Had coffee with {name}",
        "Went for a walk with {name}",
        "Grabbed lunch with {name}",
        "Hung out with {name} for a bit",
    ],
    "invitation": [
        "{name} invited her to {activity} this weekend",
        "{name} wants to grab dinner sometime this week",
        "{name} suggested they try that new place together",
    ],
    "call": [
        "{name} called to catch up",
        "Had a quick phone call with {name}",
        "{name} called with some news",
    ],
    "mentioned": [
        "She was thinking about what {name} said the other day",
        "Something reminded her of {name}",
        "She remembered a funny thing {name} once said",
    ],
}

# Topics for text message templates
TEXT_TOPICS = [
    "her day", "something funny that happened", "weekend plans",
    "a new show", "work drama", "a recipe she tried",
    "a song she discovered", "something she read",
    "a photo she took", "an inside joke",
]

# Activities for invitation templates
INVITE_ACTIVITIES = [
    "brunch", "a movie", "a concert", "hiking",
    "shopping", "a gallery opening", "karaoke",
    "a yoga class", "a farmers market",
]

# Frequency weights: how likely each contact_frequency type triggers
FREQUENCY_WEIGHTS = {
    "daily": 0.40,
    "regular": 0.25,
    "occasional": 0.12,
}


class SocialSystem:
    """
    Manages NPC social interactions.

    Follows the DesireSystem pattern:
    - State stored in simple data structures
    - Tick method called periodically
    - Random events generated from templates
    """

    def __init__(self, npcs: Optional[List[NPC]] = None,
                 introversion: float = 0.5):
        self._npcs: Dict[str, NPC] = {n.name: n for n in (npcs or [])}
        self._recent_events: List[SocialEvent] = []
        self._last_contact: Dict[str, datetime] = {}
        # Phase 7 expansion
        self._arcs: Dict[str, RelationshipArc] = {}
        self._obligations: List[SocialObligation] = []
        self._conflicts: List[SocialConflict] = []
        self._groups: List[FriendGroup] = []
        self._social_battery = SocialBatteryState(
            capacity=max(0.3, 0.9 - introversion * 0.6),
            charge=max(0.3, 0.9 - introversion * 0.6),
            recharge_rate=0.03 + introversion * 0.04,
            drain_rate=0.02 + (1 - introversion) * 0.02,
        )
        # Seed arcs from NPCs
        for npc in (npcs or []):
            rel = npc.relationship.lower()
            closeness = 0.7 if "best" in rel or "family" in rel else 0.5
            self._arcs[npc.name] = RelationshipArc(
                npc_name=npc.name,
                closeness=closeness,
            )

    def tick(self) -> Optional[SocialEvent]:
        """Called on activity tick. ~25% chance an NPC does something."""
        if not self._npcs or random.random() > 0.25:
            return None

        # Pick an NPC weighted by contact frequency
        npc = self._pick_npc()
        if not npc:
            return None

        # Respect contact frequency cooldown
        last = self._last_contact.get(npc.name)
        if last:
            cooldown = self._cooldown_hours(npc.contact_frequency)
            if (datetime.now() - last).total_seconds() < cooldown * 3600:
                return None

        event = self._generate_event(npc)
        self._recent_events.append(event)
        self._recent_events = self._recent_events[-10:]
        self._last_contact[npc.name] = datetime.now()
        return event

    def get_npc_for_activity(self, activity_name: str) -> Optional[NPC]:
        """Get an appropriate NPC for a social activity."""
        if not self._npcs:
            return None

        name_lower = activity_name.lower()
        candidates = []

        for npc in self._npcs.values():
            rel = npc.relationship.lower()
            if "lunch with coworker" in name_lower and "coworker" in rel:
                candidates.append(npc)
            elif "catching up with family" in name_lower and "family" in rel:
                candidates.append(npc)
            elif ("mom" in rel or "dad" in rel or "sister" in rel or "brother" in rel or "mum" in rel):
                if "family" in name_lower:
                    candidates.append(npc)
            elif "coffee with a friend" in name_lower and "friend" in rel:
                candidates.append(npc)
            elif "texting" in name_lower or "video call" in name_lower:
                candidates.append(npc)

        if not candidates:
            # Fall back to any NPC
            candidates = list(self._npcs.values())

        return random.choice(candidates) if candidates else None

    def get_recent_events(self, limit: int = 3) -> List[SocialEvent]:
        return self._recent_events[-limit:]

    # ============= Relationship Arcs =============

    def update_arc(self, npc_name: str, event_type: str = "interaction"):
        """Update relationship arc from interaction."""
        if npc_name not in self._arcs:
            self._arcs[npc_name] = RelationshipArc(npc_name=npc_name)
        arc = self._arcs[npc_name]
        arc.shared_history_depth += 1
        arc.last_meaningful_interaction = datetime.now()
        if event_type == "interaction":
            arc.closeness = min(1.0, arc.closeness + 0.01)
            if arc.trend == "cooling":
                arc.trend = "stable"
        elif event_type == "conflict":
            arc.closeness = max(0.1, arc.closeness - 0.05)
            arc.trend = "strained"
        elif event_type == "resolution":
            arc.trend = "repairing"
            arc.closeness = min(1.0, arc.closeness + 0.02)
            arc.unresolved_tension = None

    def tick_arcs(self):
        """Decay arcs from neglect."""
        now = datetime.now()
        for arc in self._arcs.values():
            if arc.last_meaningful_interaction:
                days = (now - arc.last_meaningful_interaction).days
                if days > 7 and arc.trend != "strained":
                    arc.trend = "cooling"
                    arc.closeness = max(0.1, arc.closeness - 0.002)
            # Repairing trends recover
            if arc.trend == "repairing":
                arc.closeness = min(1.0, arc.closeness + 0.001)
                if arc.closeness > 0.5:
                    arc.trend = "stable"
            # Deepening detection
            if arc.closeness > 0.7 and arc.trend in ("stable", "repairing"):
                arc.trend = "deepening"

    # ============= Social Obligations =============

    def add_obligation(self, description: str, person: str,
                       urgency: float = 0.3, deadline: Optional[datetime] = None):
        """Add a social obligation."""
        for o in self._obligations:
            if o.description == description:
                return
        self._obligations.append(SocialObligation(
            description=description, person=person,
            urgency=urgency, deadline=deadline,
            created_at=datetime.now(),
        ))
        if len(self._obligations) > 5:
            self._obligations = sorted(
                self._obligations, key=lambda o: o.urgency, reverse=True
            )[:5]

    def fulfill_obligation(self, description: str):
        """Fulfill a social obligation."""
        self._obligations = [o for o in self._obligations if o.description != description]

    def tick_obligations(self):
        """Check for overdue obligations."""
        now = datetime.now()
        for o in self._obligations:
            if o.deadline and now > o.deadline:
                o.overdue = True
                o.urgency = min(1.0, o.urgency + 0.01)

    def get_overdue_obligations(self) -> List[str]:
        """Get overdue obligation descriptions for stress feeding."""
        return [o.description for o in self._obligations if o.overdue]

    # ============= Conflicts =============

    def trigger_conflict(self, parties: List[str], cause: str, severity: float = 0.3):
        """Create a social conflict."""
        self._conflicts.append(SocialConflict(
            parties=parties, cause=cause, severity=severity,
            created_at=datetime.now(),
        ))
        for party in parties:
            self.update_arc(party, "conflict")
        if len(self._conflicts) > 3:
            self._conflicts = sorted(
                self._conflicts, key=lambda c: c.severity, reverse=True
            )[:3]

    def resolve_conflict(self, cause: str):
        """Resolve a conflict."""
        for c in self._conflicts:
            if c.cause == cause and c.status != "resolved":
                c.status = "resolved"
                c.resolved_at = datetime.now()
                for party in c.parties:
                    self.update_arc(party, "resolution")
                return

    def tick_conflicts(self):
        """Conflicts cool over time."""
        for c in self._conflicts:
            if c.status == "unresolved":
                c.severity = max(0.05, c.severity - 0.002)
                if c.severity < 0.1:
                    c.status = "cooling"
        self._conflicts = [c for c in self._conflicts if c.status != "resolved"
                          or (c.resolved_at and (datetime.now() - c.resolved_at).days < 3)]

    # ============= Social Battery =============

    def drain_social_battery(self, amount: Optional[float] = None):
        """Drain social battery from interaction."""
        drain = amount or self._social_battery.drain_rate
        self._social_battery.charge = max(0.0, self._social_battery.charge - drain)

    def recharge_social_battery(self, amount: Optional[float] = None):
        """Recharge social battery from solitude."""
        recharge = amount or self._social_battery.recharge_rate
        self._social_battery.charge = min(
            self._social_battery.capacity,
            self._social_battery.charge + recharge,
        )

    def should_decline_social(self) -> bool:
        """Check if social battery is too low for more socializing."""
        return self._social_battery.charge < 0.2

    # ============= Properties =============

    @property
    def social_battery(self) -> SocialBatteryState:
        return self._social_battery

    @property
    def arcs(self) -> Dict[str, RelationshipArc]:
        return self._arcs

    @property
    def obligations(self) -> List[SocialObligation]:
        return self._obligations

    @property
    def conflicts(self) -> List[SocialConflict]:
        return self._conflicts

    def export_state(self) -> dict:
        """Structured dict for LLM pipeline digest passes."""
        return {
            "recent_events": [
                {"npc": e.npc_name, "type": e.event_type, "description": e.description}
                for e in self._recent_events[-3:]
            ],
            "npc_count": len(self._npcs),
            "social_battery": round(self._social_battery.charge, 2),
            "arcs": [
                {"name": a.npc_name, "closeness": round(a.closeness, 2), "trend": a.trend}
                for a in sorted(self._arcs.values(), key=lambda a: a.closeness, reverse=True)[:3]
            ],
            "obligations": [o.description for o in self._obligations if o.overdue][:2],
            "conflicts": [c.cause for c in self._conflicts if c.status == "unresolved"][:2],
        }

    def get_status(self) -> dict:
        return {
            "npc_count": len(self._npcs),
            "recent_events": [
                {"npc": e.npc_name, "type": e.event_type, "description": e.description}
                for e in self._recent_events[-3:]
            ],
            "social_battery": round(self._social_battery.charge, 2),
            "arcs": {
                name: {"closeness": round(a.closeness, 2), "trend": a.trend}
                for name, a in self._arcs.items()
            },
            "obligations_count": len(self._obligations),
            "conflicts_count": len([c for c in self._conflicts if c.status == "unresolved"]),
        }

    # ============= Serialization =============

    def to_dict(self) -> dict:
        """Serialize for DB storage."""
        return {
            "arcs": json.dumps([
                {
                    "npc_name": a.npc_name, "closeness": a.closeness, "trend": a.trend,
                    "last_meaningful": a.last_meaningful_interaction.isoformat() if a.last_meaningful_interaction else None,
                    "unresolved_tension": a.unresolved_tension,
                    "shared_history_depth": a.shared_history_depth,
                }
                for a in self._arcs.values()
            ]),
            "obligations": json.dumps([
                {
                    "description": o.description, "person": o.person,
                    "urgency": o.urgency, "overdue": o.overdue,
                    "deadline": o.deadline.isoformat() if o.deadline else None,
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                }
                for o in self._obligations
            ]),
            "conflicts": json.dumps([
                {
                    "parties": c.parties, "cause": c.cause,
                    "severity": c.severity, "status": c.status,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
                }
                for c in self._conflicts
            ]),
            "groups": json.dumps([
                {
                    "name": g.name, "members": g.members,
                    "energy": g.energy, "her_role": g.her_role,
                    "last_group_event": g.last_group_event.isoformat() if g.last_group_event else None,
                }
                for g in self._groups
            ]),
            "battery_charge": self._social_battery.charge,
            "battery_capacity": self._social_battery.capacity,
        }

    def load_expansion(self, data: dict):
        """Load expansion state from DB."""
        if not data:
            return
        # Arcs
        raw = data.get("arcs", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            items = []
        for a in items:
            self._arcs[a["npc_name"]] = RelationshipArc(
                npc_name=a.get("npc_name", ""),
                closeness=a.get("closeness", 0.5),
                trend=a.get("trend", "stable"),
                last_meaningful_interaction=datetime.fromisoformat(a["last_meaningful"]) if a.get("last_meaningful") else None,
                unresolved_tension=a.get("unresolved_tension"),
                shared_history_depth=a.get("shared_history_depth", 0),
            )
        # Obligations
        raw = data.get("obligations", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            items = []
        self._obligations = [
            SocialObligation(
                description=o.get("description", ""),
                person=o.get("person", ""),
                urgency=o.get("urgency", 0.3),
                overdue=o.get("overdue", False),
                deadline=datetime.fromisoformat(o["deadline"]) if o.get("deadline") else None,
                created_at=datetime.fromisoformat(o["created_at"]) if o.get("created_at") else None,
            ) for o in items
        ]
        # Conflicts
        raw = data.get("conflicts", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            items = []
        self._conflicts = [
            SocialConflict(
                parties=c.get("parties", []),
                cause=c.get("cause", ""),
                severity=c.get("severity", 0.3),
                status=c.get("status", "unresolved"),
                created_at=datetime.fromisoformat(c["created_at"]) if c.get("created_at") else None,
                resolved_at=datetime.fromisoformat(c["resolved_at"]) if c.get("resolved_at") else None,
            ) for c in items
        ]
        # Groups
        raw = data.get("groups", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            items = []
        self._groups = [
            FriendGroup(
                name=g.get("name", ""),
                members=g.get("members", []),
                energy=g.get("energy", "positive"),
                her_role=g.get("her_role", ""),
                last_group_event=datetime.fromisoformat(g["last_group_event"]) if g.get("last_group_event") else None,
            ) for g in items
        ]
        # Battery
        if "battery_charge" in data:
            self._social_battery.charge = data["battery_charge"]
        if "battery_capacity" in data:
            self._social_battery.capacity = data["battery_capacity"]

    # ============= Private Methods =============

    def _pick_npc(self) -> Optional[NPC]:
        """Pick an NPC weighted by contact frequency."""
        if not self._npcs:
            return None

        npcs = list(self._npcs.values())
        weights = [FREQUENCY_WEIGHTS.get(n.contact_frequency, 0.20) for n in npcs]
        return random.choices(npcs, weights=weights)[0]

    def _generate_event(self, npc: NPC) -> SocialEvent:
        """Generate a random social event for an NPC."""
        event_type = random.choices(
            ["text_received", "mentioned", "call", "invitation", "hangout"],
            weights=[0.35, 0.25, 0.15, 0.15, 0.10],
        )[0]

        templates = EVENT_TEMPLATES.get(event_type, EVENT_TEMPLATES["mentioned"])
        template = random.choice(templates)

        # Fill in template variables
        topic = random.choice(npc.shared_interests) if npc.shared_interests else random.choice(TEXT_TOPICS)
        activity = random.choice(INVITE_ACTIVITIES)

        description = template.format(name=npc.name, topic=topic, activity=activity)

        share_worthy = event_type in ("invitation", "hangout") or random.random() < 0.2

        return SocialEvent(
            npc_name=npc.name,
            event_type=event_type,
            description=description,
            timestamp=datetime.now(),
            share_worthy=share_worthy,
        )

    def _cooldown_hours(self, frequency: str) -> float:
        """Minimum hours between events for a contact frequency."""
        return {
            "daily": 4.0,
            "regular": 8.0,
            "occasional": 24.0,
        }.get(frequency, 12.0)
