"""
Social System

Manages NPC interactions, social events, and friend activity.
Follows the DesireSystem pattern: state that ticks, templates, dice rolls.
"""

import json
import random
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

from ..models import (
    NPC, SocialEvent,
    RelationshipArc, SocialObligation, SocialConflict,
    FriendGroup, SocialBatteryState,
)
from ..personas.parameters import PersonaParameters
from ..personas.pronoun_render import format_lenient
from ..settings import DEFAULT_SETTING, SettingSpec, get_setting
from ..settings.spec import DEFAULT_NPC_KIND, UNWELCOME_NPC_KINDS
# Legacy names: the NPC event templates (today's are the "friend" kind's), the
# text topics and the invitation activities moved, unchanged, into the
# contemporary setting pack (aura_life.settings.contemporary) in Task 9 -- the
# system reads its persona's setting now; re-exported so an import from here
# keeps working.
from ..settings.contemporary import EVENT_TEMPLATES, INVITE_ACTIVITIES, TEXT_TOPICS  # noqa: F401


# Frequency weights: how likely each contact_frequency type triggers
FREQUENCY_WEIGHTS = {
    "daily": 0.40,
    "regular": 0.25,
    "occasional": 0.12,
}

#: The chance, per activity tick, that one of her people does something
#: (SocialSystem.tick). Per persona, times PersonaParameters.npc_event_scale
#: (sociability).
NPC_EVENT_CHANCE = 0.25

# ============= What her people's events are to her (Task 11) =============
# SocialSystem marks each event with its NPC's kind and a valence
# (SocialEvent.valence); LifeService turns them into what she feels.

#: The event types that are contact -- someone reaching her, or with her. A
#: "mentioned" event is her thinking of them: no contact.
CONTACT_EVENT_TYPES = frozenset({"text_received", "call", "invitation", "hangout"})
#: Of that contact, what is a meaningful interaction for her loneliness --
#: in person, or by voice (AffectSystem.on_social_interaction's larger
#: relief); a text or an invitation is a small one.
MEANINGFUL_CONTACT_TYPES = frozenset({"call", "hangout"})
#: What an event from an unwelcome kind (UNWELCOME_NPC_KINDS) makes her feel.
#: Each weighs what her default setting's "uneasy feeling" chaos line does
#: (aura_life.settings.contemporary.CHAOS_EMOTIONS: two emotions at 0.1) --
#: a threat, those two; someone she is estranged from, guilt and sadness.
#: Chosen (Task 11).
UNWELCOME_KIND_EMOTIONS = {
    "threat": {"anxious": 0.1, "unsettled": 0.1},
    "estranged": {"guilty": 0.1, "sad": 0.1},
}
#: The stressor anything from an unwelcome kind adds -- getting in touch, or
#: her thinking of them (ruling T11-R1): what she is stressed about, named for
#: them (her stress then reads "Stressed about <this>"). One per person, an
#: episode that lapses by itself (Task 15: AffectSystem's STRESSOR_KINDS
#: "unwelcome" kind, which these words are).
UNWELCOME_STRESSOR = "{name}"


def event_valence(kind: str, event_type: str) -> float:
    """What an event is to her: -1.0 anything from an unwelcome kind, 1.0
    contact from anyone else (CONTACT_EVENT_TYPES), 0.0 her thinking of
    them."""
    if kind in UNWELCOME_NPC_KINDS:
        return -1.0
    return 1.0 if event_type in CONTACT_EVENT_TYPES else 0.0


class SocialSystem:
    """
    Manages NPC social interactions.

    Follows the DesireSystem pattern:
    - State stored in simple data structures
    - Tick method called periodically
    - Random events generated from templates
    """

    def __init__(self, npcs: Optional[List[NPC]] = None,
                 introversion: float = 0.5, rng=None,
                 params: Optional[PersonaParameters] = None,
                 setting: Optional[SettingSpec] = None):
        """``rng``: optional ``random.Random``. ``None`` -- the default --
        is a fresh, unseeded ``random.Random()`` (never the module), so a
        bare ``SocialSystem()`` still works and shares no draw sequence with
        any other instance or the module.

        ``params``: her traits' engine parameters
        (:class:`~aura_life.personas.parameters.PersonaParameters`). Given,
        her sociability sets ``introversion`` (``params.introversion``, which
        sizes the social battery) and the chance her people get in touch
        (NPC_EVENT_CHANCE times ``params.npc_event_scale``); ``introversion``
        is then not read. Without them, ``introversion`` as passed and
        NPC_EVENT_CHANCE as it is.

        ``setting``: her setting pack (:class:`~aura_life.settings.SettingSpec`),
        whose ``npc_event_templates`` (for the NPC's kind, falling back to
        the default kind's), ``text_topics`` and ``invite_activities`` what
        her people do is drawn from. ``None`` -- the default -- is
        :data:`~aura_life.settings.DEFAULT_SETTING`'s. With no template for
        the event drawn, nothing happens."""
        self._rng = rng if rng is not None else random.Random()
        self._setting = setting if setting is not None else get_setting(DEFAULT_SETTING)
        # Whether the battery's size is her sociability's (load_expansion then
        # keeps it) or the caller's own introversion.
        self._battery_from_traits = params is not None
        if params is not None:
            introversion = params.introversion
            self._npc_event_chance = NPC_EVENT_CHANCE * params.npc_event_scale
        else:
            self._npc_event_chance = NPC_EVENT_CHANCE
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

    def tick(self, skip: Iterable[str] = (), *, now: Optional[datetime] = None) -> Optional[SocialEvent]:
        """Called on activity tick. NPC_EVENT_CHANCE (~25%, scaled by her
        sociability) that an NPC does something.

        ``skip``: the names of her people who draw no event here -- someone
        she lives with, whose own life runs beside hers (``LifeService``'s
        household, Task 11). Nothing skipped, the draws are exactly as
        before.

        ``now``: the world instant (``LifeService`` passes it, humanness Task
        19): an NPC's contact cooldown, its stamp and the event's; the host's
        clock when omitted."""
        now = now if now is not None else datetime.now()
        if not self._npcs or self._rng.random() > self._npc_event_chance:
            return None

        # Pick an NPC weighted by contact frequency
        npc = self._pick_npc(skip)
        if not npc:
            return None

        # Respect contact frequency cooldown
        last = self._last_contact.get(npc.name)
        if last:
            cooldown = self._cooldown_hours(npc.contact_frequency)
            if (now - last).total_seconds() < cooldown * 3600:
                return None

        event = self._generate_event(npc, now=now)
        if event is None:
            return None  # her setting has no template for what was drawn
        self._recent_events.append(event)
        self._recent_events = self._recent_events[-10:]
        self._last_contact[npc.name] = now
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

        return self._rng.choice(candidates) if candidates else None

    def get_recent_events(self, limit: int = 3) -> List[SocialEvent]:
        return self._recent_events[-limit:]

    # ============= Relationship Arcs =============

    def update_arc(self, npc_name: str, event_type: str = "interaction", *, now: Optional[datetime] = None):
        """Update relationship arc from interaction, stamped ``now`` (the world
        instant ``LifeService`` passes, humanness Task 19: :meth:`tick_arcs`
        compares it; the host's clock when omitted)."""
        if npc_name not in self._arcs:
            self._arcs[npc_name] = RelationshipArc(npc_name=npc_name)
        arc = self._arcs[npc_name]
        arc.shared_history_depth += 1
        arc.last_meaningful_interaction = now if now is not None else datetime.now()
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

    def tick_arcs(self, *, now: Optional[datetime] = None):
        """Decay arcs from neglect: an arc cools after 7 days without contact,
        counted to ``now`` (the world instant ``LifeService`` passes, humanness
        Task 19; the host's clock when omitted)."""
        now = now if now is not None else datetime.now()
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
                       urgency: float = 0.3, deadline: Optional[datetime] = None, *,
                       now: Optional[datetime] = None):
        """Add a social obligation, created ``now`` (the world instant; the
        host's clock when omitted -- no caller inside aura-life)."""
        for o in self._obligations:
            if o.description == description and not o.duration_min:  # a plan is not a debt
                return
        self._obligations.append(SocialObligation(
            description=description, person=person,
            urgency=urgency, deadline=deadline,
            created_at=now if now is not None else datetime.now(),
        ))
        debts = [o for o in self._obligations if not o.duration_min]
        if len(debts) > 5:
            keep = sorted(debts, key=lambda o: o.urgency, reverse=True)[:5]
            # Plans with people are commitments, not debts: the cap never drops one.
            self._obligations = [o for o in self._obligations if o.duration_min or o in keep]

    def add_plan(self, people: List[str], what: str, at: datetime, duration_min: int, *,
                 now: Optional[datetime] = None):
        """Record a plan with people (names already validated by the caller),
        created ``now`` (the world instant ``LifeService`` passes, humanness
        Task 19, as ``at`` is one; the host's clock when omitted)."""
        for o in self._obligations:
            if o.duration_min and o.description == what and o.deadline == at and o.people == people:
                return o
        plan = SocialObligation(
            description=what, person=", ".join(people), urgency=0.3, deadline=at,
            created_at=now if now is not None else datetime.now(), people=list(people), duration_min=duration_min,
        )
        self._obligations.append(plan)
        return plan

    def upcoming_plans(self, now: datetime, within_hours: float) -> List[dict]:
        """Plans still running or starting within ``within_hours`` of ``now``, soonest first."""
        horizon = now + timedelta(hours=within_hours)
        found = [
            o for o in self._obligations
            if o.duration_min and o.deadline
            and o.deadline + timedelta(minutes=o.duration_min) > now and o.deadline <= horizon
        ]
        found.sort(key=lambda o: o.deadline)
        return [
            {"people": list(o.people), "what": o.description, "at": o.deadline, "duration_min": o.duration_min}
            for o in found
        ]

    def prune_plans(self, now: datetime, keep_hours: float = 24.0) -> None:
        """Forget plans that ended more than ``keep_hours`` before ``now``."""
        cutoff = now - timedelta(hours=keep_hours)
        self._obligations = [
            o for o in self._obligations
            if not (o.duration_min and o.deadline and o.deadline + timedelta(minutes=o.duration_min) < cutoff)
        ]

    def fulfill_obligation(self, description: str):
        """Fulfill a social obligation."""
        self._obligations = [o for o in self._obligations if o.description != description or o.duration_min]

    def tick_obligations(self, *, now: Optional[datetime] = None):
        """Check for overdue obligations: a deadline before ``now`` (the world
        instant ``LifeService`` passes, humanness Task 19; the host's clock
        when omitted)."""
        now = now if now is not None else datetime.now()
        for o in self._obligations:
            if o.duration_min:
                continue  # a plan is a commitment, not a debt: it never goes overdue
            if o.deadline and now > o.deadline:
                o.overdue = True
                o.urgency = min(1.0, o.urgency + 0.01)

    def get_overdue_obligations(self) -> List[str]:
        """Get overdue obligation descriptions for stress feeding."""
        return [o.description for o in self._obligations if o.overdue]

    # ============= Conflicts =============

    def trigger_conflict(self, parties: List[str], cause: str, severity: float = 0.3, *,
                         now: Optional[datetime] = None):
        """Create a social conflict, ``now`` (the world instant; the host's
        clock when omitted -- no caller inside aura-life)."""
        now = now if now is not None else datetime.now()
        self._conflicts.append(SocialConflict(
            parties=parties, cause=cause, severity=severity,
            created_at=now,
        ))
        for party in parties:
            self.update_arc(party, "conflict", now=now)
        if len(self._conflicts) > 3:
            self._conflicts = sorted(
                self._conflicts, key=lambda c: c.severity, reverse=True
            )[:3]

    def resolve_conflict(self, cause: str, *, now: Optional[datetime] = None):
        """Resolve a conflict, ``now`` (the world instant; :meth:`tick_conflicts`
        compares it; the host's clock when omitted -- no caller inside
        aura-life)."""
        now = now if now is not None else datetime.now()
        for c in self._conflicts:
            if c.cause == cause and c.status != "resolved":
                c.status = "resolved"
                c.resolved_at = now
                for party in c.parties:
                    self.update_arc(party, "resolution", now=now)
                return

    def tick_conflicts(self, *, now: Optional[datetime] = None):
        """Conflicts cool over time; a resolved one is kept 3 days, counted to
        ``now`` (the world instant ``LifeService`` passes, humanness Task 19;
        the host's clock when omitted)."""
        now = now if now is not None else datetime.now()
        for c in self._conflicts:
            if c.status == "unresolved":
                c.severity = max(0.05, c.severity - 0.002)
                if c.severity < 0.1:
                    c.status = "cooling"
        self._conflicts = [c for c in self._conflicts if c.status != "resolved"
                          or (c.resolved_at and (now - c.resolved_at).days < 3)]

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

    def circle(self) -> List[dict]:
        """Everyone in her circle as plain dicts, closest first."""
        people = []
        for npc in self._npcs.values():
            arc = self._arcs.get(npc.name)
            people.append({
                "name": npc.name,
                "relationship": npc.relationship,
                "closeness": round(arc.closeness, 2) if arc else None,
                "trend": arc.trend if arc else None,
            })
        # Stable sort: people without an arc go last, ties keep circle order.
        people.sort(key=lambda p: -1.0 if p["closeness"] is None else p["closeness"], reverse=True)
        return people

    def export_state(self, now: Optional[datetime] = None) -> dict:
        """Structured dict for LLM pipeline digest passes.

        ``now`` is the instant the next 24 h of plans is measured from (the host
        clock when omitted); ``LifeService`` passes its world clock.
        """
        now = now if now is not None else datetime.now()
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
            "people": [
                {"name": p["name"], "rel": p["relationship"], "close": p["closeness"], "trend": p["trend"]}
                for p in self.circle()[:5]
            ],
            "plans": [
                {"who": ", ".join(p["people"]), "what": p["what"],
                 "at": p["at"].isoformat(timespec="minutes"), "min": p["duration_min"]}
                for p in self.upcoming_plans(now, 24)
            ],
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
                    "people": list(o.people), "duration_min": o.duration_min,
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
                people=list(o.get("people") or []),
                duration_min=int(o.get("duration_min") or 0),
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
        # Battery. Its capacity is her sociability's when this system was
        # built from her parameters -- who she is, not state -- so a row saved
        # before her traits changed does not shrink or grow it; the charge is
        # state and comes back, never above the capacity.
        if "battery_capacity" in data and not self._battery_from_traits:
            self._social_battery.capacity = data["battery_capacity"]
        if "battery_charge" in data:
            charge = data["battery_charge"]
            if self._battery_from_traits:
                charge = min(charge, self._social_battery.capacity)
            self._social_battery.charge = charge

    # ============= Private Methods =============

    def _pick_npc(self, skip: Iterable[str] = ()) -> Optional[NPC]:
        """Pick an NPC weighted by contact frequency, none of ``skip``."""
        skipped = set(skip)
        npcs = [n for n in self._npcs.values() if n.name not in skipped]
        if not npcs:
            return None

        weights = [FREQUENCY_WEIGHTS.get(n.contact_frequency, 0.20) for n in npcs]
        return self._rng.choices(npcs, weights=weights)[0]

    def _generate_event(self, npc: NPC, *, now: Optional[datetime] = None) -> Optional[SocialEvent]:
        """Generate a random social event for an NPC, from her setting's
        templates for the NPC's kind (an NPC with none on record is the
        default kind, spec section 4.1). An event type drawn that the
        setting has no template for is told by a "mentioned" one, and so is a
        mention; None when it has neither. The event carries the kind and
        what it is to her (:func:`event_valence`)."""
        event_type = self._rng.choices(
            ["text_received", "mentioned", "call", "invitation", "hangout"],
            weights=[0.35, 0.25, 0.15, 0.15, 0.10],
        )[0]

        kind = getattr(npc, "kind", None) or DEFAULT_NPC_KIND
        by_type = self._setting.npc_event_templates_for(kind)
        templates = by_type.get(event_type)
        if not templates:
            event_type = "mentioned"
            templates = by_type.get(event_type)
        if not templates:
            return None
        template = self._rng.choice(templates)

        # Fill in template variables
        topics = self._setting.text_topics
        invites = self._setting.invite_activities
        if npc.shared_interests:
            topic = self._rng.choice(npc.shared_interests)
        else:
            topic = self._rng.choice(topics) if topics else ""
        activity = self._rng.choice(invites) if invites else ""

        # format_lenient, not str.format: a template's pronoun tokens
        # ({obj}, {Subj}, ...) are filled downstream by LifeService, once it
        # knows the persona's gender and user_info -- this call only owns
        # name/topic/activity.
        description = format_lenient(template, name=npc.name, topic=topic, activity=activity)

        # Unwelcome news is never something to share (ruling T11-R1): it is
        # not share-worthy, and no roll is drawn for it.
        valence = event_valence(kind, event_type)
        share_worthy = valence >= 0 and (event_type in ("invitation", "hangout") or self._rng.random() < 0.2)

        return SocialEvent(
            npc_name=npc.name,
            event_type=event_type,
            description=description,
            timestamp=now if now is not None else datetime.now(),
            share_worthy=share_worthy,
            kind=kind,
            valence=valence,
        )

    def _cooldown_hours(self, frequency: str) -> float:
        """Minimum hours between events for a contact frequency."""
        return {
            "daily": 4.0,
            "regular": 8.0,
            "occasional": 24.0,
        }.get(frequency, 12.0)
