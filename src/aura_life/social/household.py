"""Personas who live together (humanness program Task 11, spec section 4.5).

A :class:`Household` is a runtime link between the ``LifeService`` of each
persona who lives in one home: ``LifeService(..., household=h)`` joins ``h``
under its persona id when it is built, ``stop()`` leaves it and ``start()``
joins it again. Nothing about it is saved -- not the membership, and nothing
of one member's state in another's database: each persona's database holds
her own life.

What living together changes (``LifeService``):

- Her view of a housemate is the housemate's state as of the housemate's
  last tick -- asleep, where, doing what (:class:`HousemateState`, which
  each member publishes whole at the end of each of her ticks, and when she
  is built or loaded, and never changes in place: a view read on another
  thread while her tick runs is her last complete state, never half of the
  next). It is what her life context's "The people you live with" and
  ``export_outer_state()["social"]["household"]`` tell, worded by
  :func:`describe_housemate`. Her social-circle entry for that person (the
  entry whose name is the housemate's persona id or her definition's name,
  compared case-insensitively) draws no ordinary NPC event: the housemate's
  life is simulated, so she is never "texted to check in" by someone asleep
  in the next room.
- What they do together. An activity tagged "joint"
  (``aura_life.settings.ACTIVITY_TAGS``) that one member is about to do can
  take in the housemates who are free for it -- awake and outside their
  sleep window, where she is, not on the way anywhere, not already doing
  something at this instant, in an hour their plan leaves free (or plans for
  that very activity), with the energy and the social battery for it -- on
  a roll of her own household stream. It is written into each one's log from
  her own side (:data:`JOINT_LINES`: the one whose activity it is was joined,
  each other one joined her), and each does it once: a housemate who joins
  does it through her own activity pipeline, where the activity takes them
  both, and her own next activity tick within one activity interval is taken
  by it. Each one's company eases the other's loneliness like any meaningful
  interaction. Every member's activity tick holds the household's
  :attr:`Household.lock`, so a joint activity never writes into a housemate
  whose own activity tick is running.

  Who asks is whoever's activity tick comes first. Driven in lock-step --
  every member ticked at the same instants, in the same order, as
  ``tests/sim_helpers.py`` does -- joint activities are deterministic per
  seed: the first member to tick at an instant is the one who asks, the
  others having not yet acted. On a host where each member's ticks run on
  their own timers, whose tick comes first -- and so who asks, and what
  they do together -- can differ from run to run.

``PersonalityDefinition.household`` lists the members a persona expects. One
who is not joined at runtime is absent, and nothing else: her social-circle
entry is an ordinary NPC again, and the status export lists her as missing.
"""

import gc
import threading
import weakref
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple

#: What a joint activity adds to each member's log, after the activity's own
#: line: ``{name}`` is the other side -- for the one whose activity it was,
#: whoever joined her; for one who joined, the one she joined. The pronoun
#: tokens are each persona's own (``aura_life.personas.pronoun_render``).
JOINT_LINES: Dict[str, List[str]] = {
    "initiator": [
        "{name} joined {obj}",
        "{name} came along",
        "{name} kept {obj} company",
    ],
    "joiner": [
        "{Subj} joined {name}",
        "{Subj} went along with {name}",
        "{Subj} kept {name} company",
    ],
}


@dataclass(frozen=True)
class JointSide:
    """One member's side of a joint activity (``LifeService``): whom she does
    it with, as she names them (``with_name``) and as her social circle knows
    them (``npc_names``: her entries for them, possibly none); the line her
    log adds (from :data:`JOINT_LINES`, unrendered); and, for one who joins,
    where the activity is (``place``), the instant its entry has in the
    log of the one whose activity it is (``started_at``) and how it went for
    that one (``outcome``, Task 14: one event, one outcome, each appraising
    it her own way) -- all ``None`` on that one's own side. ``names``: each
    of them as she names them, one by one (``with_name`` is the phrase), for
    her memory of it (Task 12)."""

    with_name: str
    npc_names: Tuple[str, ...]
    line: str
    place: Optional[str] = None
    started_at: Optional[datetime] = None
    names: Tuple[str, ...] = ()
    outcome: Optional[str] = None


@dataclass(frozen=True)
class HousemateState:
    """What a member shows the people she lives with, as of her last tick:
    whether she is asleep, where she is (her location key; on the way to
    ``destination`` while ``in_transit``), and what she is doing (her last
    activity as she would say it -- empty while she sleeps, or when it was
    one of her intimate activities: what she does in private is hers alone).
    ``LifeService`` publishes a new one whole and never changes one in
    place."""

    asleep: bool = False
    location: str = "home"
    in_transit: bool = False
    destination: str = ""
    activity: str = ""


def _key(persona_id: Optional[str]) -> str:
    return str(persona_id or "").strip().lower()


class Household:
    """The services of the personas who live together.

    Members are keyed by persona id (lower-cased), in the order they joined,
    and held weakly: the household keeps no one alive, so a service the host
    drops without ``stop()`` leaves once nothing else holds it. (A
    ``LifeService`` sits in reference cycles of its own until the cyclic
    garbage collector frees it, so :meth:`join` collects once before it
    refuses a persona id that looks taken.) Two locks: :attr:`lock`, held by
    each member's whole activity tick, and a short one around the member list
    alone, so reading who lives here (a member's life context, her status)
    never waits on anyone's tick.
    """

    def __init__(self) -> None:
        self._members: Dict[str, "weakref.ref"] = {}
        self._members_lock = threading.Lock()
        self._tick_lock = threading.RLock()

    def _alive(self) -> Dict[str, Any]:
        """Every member still alive, by persona id, in the order they joined;
        the entry of one gone is dropped. Called with the members lock held."""
        alive = {}
        for key, ref in list(self._members.items()):
            member = ref()
            if member is None:
                del self._members[key]
            else:
                alive[key] = member
        return alive

    @property
    def lock(self) -> threading.RLock:
        """Held by each member's activity tick (``LifeService._on_activity_tick``)
        -- a joint activity writes into a housemate's life, so no two
        members' activity ticks run at once -- and by :meth:`leave`, so no
        tick that is running can still pull in a member who has gone."""
        return self._tick_lock

    def join(self, persona_id: str, member: Any) -> None:
        """Add ``member`` (a ``LifeService``) under ``persona_id``. Joining
        again is a no-op. A persona id held by another member still alive is
        refused (``ValueError``: stop that service, or drop it, first) -- once
        the garbage collector has had a chance to free a dropped one -- as is
        an empty id."""
        key = _key(persona_id)
        if not key:
            raise ValueError("a household member needs a persona id")
        for attempt in (1, 2):
            with self._members_lock:
                current = self._alive().get(key)
                if current is member:
                    return
                if current is None:
                    self._members[key] = weakref.ref(member)
                    return
            current = None  # hold no reference to it while it may be collected
            if attempt == 1:
                gc.collect()
        raise ValueError(f"persona {key!r} already lives in this household; stop that service first")

    def leave(self, member: Any) -> bool:
        """Remove ``member``, once no member's activity tick is running;
        ``True`` if it was a member."""
        with self._tick_lock, self._members_lock:
            for key, ref in list(self._members.items()):
                if ref() is member:
                    del self._members[key]
                    return True
        return False

    def member(self, persona_id: Optional[str]) -> Optional[Any]:
        """The member under ``persona_id`` (any case), or ``None``."""
        with self._members_lock:
            return self._alive().get(_key(persona_id))

    def member_ids(self) -> List[str]:
        """Every member's persona id, in the order they joined."""
        with self._members_lock:
            return list(self._alive())

    def housemates(self, member: Any) -> List[Any]:
        """Every member but ``member``, in the order they joined."""
        with self._members_lock:
            return [other for other in self._alive().values() if other is not member]


def _place(location: str) -> str:
    """A location key as a place to be: "home", or "the cafe"."""
    place = str(location or "").replace("_", " ").strip()
    if place.lower() in ("", "home"):
        return "home"
    if place.lower().startswith(("the ", "a ", "an ")):
        return place
    return f"the {place}"


def describe_housemate(view: Mapping[str, Any]) -> str:
    """One housemate as she is right now, for the context of someone she
    lives with (addressed to that someone): "Roberta is asleep", "Roberta is
    here with you (reading)", "Roberta is at the cafe", "Roberta is on the way
    home". ``view`` is ``LifeService``'s view of her: ``name``, ``asleep``,
    ``here`` (where the viewer is), ``in_transit`` and ``destination``,
    ``location``, ``activity`` (an activity's name, as her setting has it --
    "reading", "gym workout" -- or empty when unknown or private)."""
    name = view["name"]
    if view["asleep"]:
        return f"{name} is asleep"
    if view["here"]:
        where = "here with you"
    elif view.get("in_transit"):
        destination = _place(view.get("destination", ""))
        where = "on the way home" if destination == "home" else f"on the way to {destination}"
    else:
        place = _place(view["location"])
        where = "at home" if place == "home" else f"at {place}"
    return f"{name} is {where} ({view['activity']})" if view.get("activity") else f"{name} is {where}"


def name_list(names: List[str]) -> str:
    """Names as a phrase: "Roberta", "Roberta and Farid", "Ada, Roberta and
    Farid"."""
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


__all__ = ["Household", "HousemateState", "JointSide", "JOINT_LINES", "describe_housemate", "name_list"]
