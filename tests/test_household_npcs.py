"""NPC kinds and households (humanness program Task 11, spec sections 4.1 and 4.5).

Measured before this task: what the people in her life did ignored who they
were to her. "Shirley texted to check in" -- Shirley is the mother hunting
Lina; "Wilona called to catch up" -- Roberta has not called her back; "Had
coffee with Roberta" -- they live together. Contact never touched her
loneliness, and it was never unwelcome.

Section 1: a social-circle entry's ``[kind]`` reaches her NPC, and her
setting's templates for that kind tell what the person does -- a threat
never checks in, someone she is estranged from reaches her unanswered, and an
unwelcome kind never borrows a friend's lines.

Section 2: what contact does to her -- a friend's eases her loneliness, a
threat's is a stressor, unwelcome contact is felt, and cools how she sees
them.

Section 3: a household (spec section 4.5) -- the services of personas who
live together, joined at runtime: each one's view of the other is the
other's live state (asleep, where, doing what), a housemate's social-circle
entry draws no ordinary NPC event, one expected but not joined is an
ordinary NPC again, and nothing of one is saved in the other's database.

Section 4: what they do together -- an activity tagged "joint" can take in a
housemate who is free, awake and where she is; it is in both logs, each
worded from its own side, and each does it once. Joining takes the joiner's
hour (Task 28, ruling T13-R1): her plan's slot for it becomes the activity,
where it is, so no later sync of her plan sends her back; the joint tests run
at every host hour of ``tests/conftest.py``'s ``host_hour``. The acceptance
runs two simulated days at the production cadence (ruling T4-R3).
"""

import contextlib
import random
import re
import sqlite3
import threading
import weakref
from datetime import datetime, timedelta

import pytest

from aura_life import hooks
from aura_life.life_service import LifeService
from aura_life.models import (
    NPC, ActivityLog, DailyPlan, PlannedSlot, SocialEvent, TransitPhase, TransitState,
)
from aura_life.personas.keys import NPC_KINDS
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.personas.profile_parser import ProfileParser
from aura_life.settings import SettingSpec, get_setting, register_setting, unregister_setting
from aura_life.social import Household
from aura_life.social.social_system import SocialSystem
from aura_life.world import WorldEnvironment

from sim_helpers import PRODUCTION, SimPersona, run_days

#: A Tuesday afternoon: every default schedule is awake, the night far off.
TUESDAY_1400 = datetime(2026, 10, 6, 14, 0)


class ScriptedClock:
    """A clock that moves only when told to (tests/test_activity_choice.py)."""

    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant


@pytest.fixture
def persona_clock():
    """Her local clock (the ``persona_now`` hook) on a scripted instant; the
    previous provider is put back afterwards."""
    saved = hooks.provider_for("persona_now")
    clock = ScriptedClock(TUESDAY_1400)
    hooks.configure(persona_now=lambda timezone=None: clock.instant)
    yield clock
    hooks.configure(persona_now=saved)


@pytest.fixture
def registered():
    """Register setting specs for one test and unregister them afterwards."""
    keys = []

    def _register(spec):
        register_setting(spec)
        keys.append(spec.key)
        return get_setting(spec.key)

    yield _register
    for key in keys:
        unregister_setting(key)


def _service(tmp_path, name: str, clock=None, seed: int = 7, persona_id=None, **kwargs) -> LifeService:
    """A persona on ``clock`` (a scripted world clock), her draws seeded."""
    world = WorldEnvironment(now=clock, seed=seed) if clock is not None else None
    return LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=persona_id or name,
                       world_environment=world, rng=random.Random(seed), **kwargs)


def _template_re(template: str, name: str) -> "re.Pattern":
    """A template as SocialSystem leaves it: its NPC's name filled, a topic
    or an invitation any text, the pronoun tokens still in place (LifeService
    renders them later)."""
    pattern = re.escape(template).replace(re.escape("{name}"), re.escape(name))
    for field in ("topic", "activity"):
        pattern = pattern.replace(re.escape("{" + field + "}"), ".+")
    return re.compile(pattern + r"\Z")


def _matches_any(description: str, by_type: dict, name: str) -> bool:
    return any(_template_re(t, name).match(description) for pool in by_type.values() for t in pool)


def _events_from(social: SocialSystem, count: int) -> list:
    """``count`` events through the whole of ``SocialSystem.tick`` -- the roll
    always passing and no NPC ever on cooldown."""
    social._npc_event_chance = 1.0
    events = []
    for _ in range(count * 20):
        social._last_contact.clear()
        event = social.tick()
        if event is not None:
            events.append(event)
            if len(events) == count:
                return events
    raise AssertionError(f"only {len(events)} of {count} events came")


# ======================================================================
# 1. Her people's kinds, and what each kind does
# ======================================================================

def test_each_social_circle_entry_s_kind_reaches_her_npc(tmp_path):
    """Task 7 carried the ``[kind]`` tag to the definition and the database;
    the NPCs her engines hold never had it."""
    svc = _service(tmp_path, "kinds", social_circle=[
        {"name": "Shirley", "kind": "threat", "relationship": "her mother"},
        {"name": "Wilona", "kind": "estranged", "relationship": "auntie"},
        {"name": "Mo", "kind": " Family ", "relationship": "sister"},
        {"name": "Farid", "relationship": "driver"},
        {"name": "Glitch", "kind": "rival", "relationship": "a friendly rival"},
    ])
    kinds = {name: npc.kind for name, npc in svc._social._npcs.items()}
    assert kinds == {"Shirley": "threat", "Wilona": "estranged", "Mo": "family", "Farid": "friend",
                     "Glitch": "rival"}


def test_a_parsed_profile_s_kinds_reach_her_npcs(tmp_path):
    profile = ProfileParser.parse_text(
        "== SOCIAL CIRCLE ==\n"
        "- Shirley [threat]: her mother, still tracking her, shared interests: gridrunning\n"
        "- Farid: nomad driver, calm, shared interests: roads\n")
    svc = _service(tmp_path, "parsed", social_circle=profile.social_circle)
    assert svc._social._npcs["Shirley"].kind == "threat"
    assert svc._social._npcs["Farid"].kind == "friend"


def test_a_threat_never_yields_a_check_in_template_over_200_events(tmp_path):
    """The acceptance: Shirley, her mother and a threat, over 200 events --
    none is a friend's line ("texted to check in" first of all), every one is
    her setting's line for a threat."""
    svc = _service(tmp_path, "hunted", seed=11, social_circle=[
        {"name": "Shirley", "kind": "threat", "relationship": "her mother"}])
    events = _events_from(svc._social, 200)
    spec = get_setting()
    friendly = spec.npc_event_templates["friend"]
    threat = spec.npc_event_templates_for("threat")
    assert threat != friendly
    descriptions = [event.description for event in events]
    assert "Shirley texted to check in" not in descriptions
    assert not [d for d in descriptions if _matches_any(d, friendly, "Shirley")]
    assert all(_matches_any(d, threat, "Shirley") for d in descriptions), descriptions
    assert {event.event_type for event in events} >= {"text_received", "call", "mentioned"}


def test_someone_she_is_estranged_from_reaches_her_unanswered(tmp_path):
    """Wilona is not called back: every event is her setting's line for an
    estranged kind -- missed or unanswered contact, or a call she almost
    returns -- and never a friend's "called to catch up"."""
    svc = _service(tmp_path, "estranged", seed=5, social_circle=[
        {"name": "Wilona", "kind": "estranged", "relationship": "auntie"}])
    events = _events_from(svc._social, 200)
    spec = get_setting()
    friendly = spec.npc_event_templates["friend"]
    estranged = spec.npc_event_templates_for("estranged")
    assert estranged != friendly and set(estranged) >= {"text_received", "call", "mentioned"}
    descriptions = [event.description for event in events]
    assert "Wilona called to catch up" not in descriptions
    assert not [d for d in descriptions if _matches_any(d, friendly, "Wilona")]
    assert all(_matches_any(d, estranged, "Wilona") for d in descriptions), descriptions


def test_an_unwelcome_kind_never_borrows_a_friend_s_lines(registered):
    """A pack with lines for friends only: a threat or someone she is
    estranged from does nothing at all, while a kind whose contact is welcome
    still takes a friend's lines (Task 9's fallback)."""
    spec = registered(SettingSpec(
        key="test-friends-only",
        npc_event_templates={"friend": {"text_received": ["{name} texted to check in"],
                                        "mentioned": ["{name} came up"]}},
    ))
    assert spec.npc_event_templates_for("threat") == {}
    assert spec.npc_event_templates_for("estranged") == {}
    assert spec.npc_event_templates_for("family") == spec.npc_event_templates["friend"]
    assert spec.npc_event_templates_for("rival") == spec.npc_event_templates["friend"]
    for kind in ("threat", "estranged"):
        social = SocialSystem(npcs=[NPC(name="Shirley", relationship="mother", kind=kind)],
                              rng=random.Random(3), setting=spec)
        social._npc_event_chance = 1.0
        assert all(social.tick() is None for _ in range(30)), kind
    family = SocialSystem(npcs=[NPC(name="Mo", relationship="sister", kind="family")],
                          rng=random.Random(3), setting=spec)
    assert _events_from(family, 5)


@pytest.mark.parametrize("kind,event_type,valence", [
    ("friend", "text_received", 1.0), ("friend", "call", 1.0), ("friend", "invitation", 1.0),
    ("friend", "hangout", 1.0), ("friend", "mentioned", 0.0),
    ("family", "call", 1.0), ("partner", "hangout", 1.0), ("co_resident", "mentioned", 0.0),
    ("threat", "call", -1.0), ("threat", "mentioned", -1.0),
    ("estranged", "text_received", -1.0), ("estranged", "mentioned", -1.0),
])
def test_an_npc_event_carries_its_kind_and_whether_it_is_welcome(kind, event_type, valence):
    """Contact from someone she is glad of is positive, her thinking of them
    neutral; anything from a threat or someone she is estranged from is
    negative."""
    social = SocialSystem(
        npcs=[NPC(name="Sam", relationship="someone", kind=kind)],
        rng=_StubDraws(event_type))
    event = social._generate_event(social._npcs["Sam"])
    assert (event.kind, event.event_type, event.valence) == (kind, event_type, valence)


class _StubDraws:
    """Draws the given event type and the first of every choice."""

    def __init__(self, event_type: str):
        self._event_type = event_type

    def choices(self, population, weights=None, k=1):
        return [self._event_type] if self._event_type in population else [list(population)[0]]

    def choice(self, seq):
        return list(seq)[0]

    def random(self):
        return 0.5


def test_every_kind_the_profile_format_knows_is_welcome_or_not():
    """No kind is left out: each is a kind whose contact she welcomes, or one
    of the unwelcome ones."""
    from aura_life.settings.spec import UNWELCOME_NPC_KINDS

    assert set(UNWELCOME_NPC_KINDS) == {"estranged", "threat"}
    assert set(UNWELCOME_NPC_KINDS) < set(NPC_KINDS)


# ======================================================================
# 2. What contact does to her
# ======================================================================

def _ticked_with(tmp_path, name: str, clock, event, *, loneliness: float = 0.8, **kwargs) -> LifeService:
    """One activity tick of a persona who reads at home, her social tick
    handing over ``event`` (or nothing). Every twin shares a persona id and a
    seed, so the event is the only difference between them."""
    svc = _service(tmp_path, name, clock, persona_id="twin", social_circle=[
        {"name": "Sam", "relationship": "best friend"},
        {"name": "Shirley", "kind": "threat", "relationship": "her mother"},
        {"name": "Wilona", "kind": "estranged", "relationship": "auntie"}], **kwargs)
    svc._desire_system.should_do_intimate_activity = lambda *args, **kw: False
    svc._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=14, activity_name="reading", reason="routine", location="home")])
    svc._affect._loneliness.level = loneliness
    svc._social.tick = lambda *args, **kw: event
    svc._on_activity_tick()
    assert svc._recent_activities[0].activity_name == "reading"
    return svc


def _event(name: str, kind: str, event_type: str, valence: float) -> SocialEvent:
    return SocialEvent(npc_name=name, event_type=event_type, description=f"{name} ({event_type})",
                       kind=kind, valence=valence)


def test_loneliness_drops_after_a_positive_npc_contact(tmp_path, persona_clock):
    """The acceptance: the same tick with and without Sam calling -- the call
    eases her loneliness by what a meaningful interaction eases it
    (AffectSystem.on_social_interaction)."""
    alone = _ticked_with(tmp_path, "alone", persona_clock, None)
    called = _ticked_with(tmp_path, "called", persona_clock, _event("Sam", "friend", "call", 1.0))
    assert called._affect.loneliness.level < alone._affect.loneliness.level
    assert alone._affect.loneliness.level - called._affect.loneliness.level == pytest.approx(0.15)


@pytest.mark.parametrize("event_type,relief", [
    ("hangout", 0.15), ("call", 0.15), ("text_received", 0.05), ("invitation", 0.05), ("mentioned", 0.0),
])
def test_how_much_a_friend_s_contact_eases_her_loneliness(tmp_path, persona_clock, event_type, relief):
    """In person or by voice is a meaningful interaction; a text or an
    invitation a small one; thinking of someone is no contact at all."""
    alone = _ticked_with(tmp_path, "alone", persona_clock, None)
    valence = 0.0 if event_type == "mentioned" else 1.0
    touched = _ticked_with(tmp_path, "touched", persona_clock, _event("Sam", "friend", event_type, valence))
    assert alone._affect.loneliness.level - touched._affect.loneliness.level == pytest.approx(relief)


@pytest.mark.parametrize("name,kind,event_type", [
    ("Shirley", "threat", "call"), ("Shirley", "threat", "text_received"), ("Shirley", "threat", "mentioned"),
    ("Wilona", "estranged", "call"), ("Wilona", "estranged", "invitation"), ("Wilona", "estranged", "mentioned"),
])
def test_an_unwelcome_event_is_a_stressor_and_eases_nothing(tmp_path, persona_clock, name, kind, event_type):
    """Ruling T11-R1: whatever a threat or someone she is estranged from does
    -- getting in touch, or her thinking of them -- feeds her stress (named
    for them) and eases no loneliness."""
    alone = _ticked_with(tmp_path, "alone", persona_clock, None)
    reached = _ticked_with(tmp_path, "reached", persona_clock, _event(name, kind, event_type, -1.0))
    assert reached._affect.loneliness.level == pytest.approx(alone._affect.loneliness.level)
    assert name in reached._affect.stress.sources and name not in alone._affect.stress.sources
    assert reached._affect.stress.level > alone._affect.stress.level


@pytest.mark.parametrize("kind", ["threat", "estranged"])
def test_an_unwelcome_event_is_never_news_to_share(kind):
    """Ruling T11-R1: over hundreds of events, nothing a threat or someone she
    is estranged from does is share-worthy -- not by its type, not by the
    roll -- while a friend's still can be."""
    unwelcome = SocialSystem(npcs=[NPC(name="Shirley", relationship="someone", kind=kind)],
                             rng=random.Random(21))
    friend = SocialSystem(npcs=[NPC(name="Sam", relationship="best friend")], rng=random.Random(21))
    assert not [event for event in _events_from(unwelcome, 300) if event.share_worthy]
    assert [event for event in _events_from(friend, 300) if event.share_worthy]


class _FollowUps:
    """A host's follow-up manager: records every trigger created."""

    def __init__(self):
        self.triggers = []

    def create_trigger(self, **kwargs):
        self.triggers.append(kwargs)


@pytest.mark.parametrize("name,kind,valence,prompts", [
    ("Sam", "friend", 1.0, True),
    ("Shirley", "threat", -1.0, False),
    ("Wilona", "estranged", -1.0, False),
])
def test_only_welcome_news_prompts_her_to_share_it(tmp_path, name, kind, valence, prompts):
    """Ruling T11-R1: a friend's share-worthy news prompts a "share it
    naturally" SOCIAL_EVENT; an unwelcome event never does -- even one marked
    share-worthy -- and never becomes something to share."""
    follow_ups = _FollowUps()
    svc = _service(tmp_path, "prompted", follow_up_provider=lambda pid: follow_ups, social_circle=[
        {"name": name, "kind": kind, "relationship": "someone"}])
    event = SocialEvent(npc_name=name, event_type="call", description=f"{name} called with news",
                        share_worthy=True, kind=kind, valence=valence)
    log = ActivityLog(activity_name="reading", narrative="She read")
    svc._on_social_event(event, log, "reading")
    svc._social._recent_events.append(event)
    for _ in range(20):
        svc._life_trigger_cooldowns.clear()
        svc._evaluate_life_triggers()
    social = [t for t in follow_ups.triggers if t["trigger_type"] == "SOCIAL_EVENT"]
    assert bool(social) is prompts, follow_ups.triggers
    assert all("Share it naturally" in t["prompt_hint"] for t in social)
    shared = [s.content for s in svc._shareable_queue if name in s.content]
    assert bool(shared) is prompts, shared


@pytest.mark.parametrize("name,kind,event_type", [
    ("Shirley", "threat", "call"), ("Shirley", "threat", "mentioned"),
    ("Wilona", "estranged", "text_received"), ("Wilona", "estranged", "mentioned"),
])
def test_an_unwelcome_event_pulls_her_mood_down(tmp_path, persona_clock, name, kind, event_type):
    alone = _ticked_with(tmp_path, "alone", persona_clock, None)
    reached = _ticked_with(tmp_path, "reached", persona_clock, _event(name, kind, event_type, -1.0))
    assert reached._affect.mood.valence < alone._affect.mood.valence


def test_a_friend_s_contact_leaves_her_mood_as_it_was(tmp_path, persona_clock):
    """Welcome contact eases her loneliness (which mood reads on its next
    affect tick); the event itself is not felt as an emotion here."""
    alone = _ticked_with(tmp_path, "alone", persona_clock, None)
    called = _ticked_with(tmp_path, "called", persona_clock, _event("Sam", "friend", "call", 1.0))
    assert called._affect.mood.valence == pytest.approx(alone._affect.mood.valence)


def test_how_she_sees_someone_follows_whether_their_contact_is_welcome(tmp_path, persona_clock):
    """Her perception of a friend warms with each contact, as it always did;
    of a threat it cools, and their relationship arc strains."""
    called = _ticked_with(tmp_path, "called", persona_clock, _event("Sam", "friend", "call", 1.0))
    hunted = _ticked_with(tmp_path, "hunted", persona_clock, _event("Shirley", "threat", "call", -1.0))
    fresh = _service(tmp_path, "fresh", social_circle=[
        {"name": "Sam", "relationship": "best friend"},
        {"name": "Shirley", "kind": "threat", "relationship": "her mother"}])
    sam_before = fresh._identity._perceptions["Sam"].emotional_valence
    shirley_before = fresh._identity._perceptions["Shirley"].emotional_valence
    assert called._identity._perceptions["Sam"].emotional_valence == pytest.approx(sam_before + 0.02)
    assert hunted._identity._perceptions["Shirley"].emotional_valence == pytest.approx(shirley_before - 0.02)
    assert hunted._social.arcs["Shirley"].trend == "strained"
    assert hunted._social.arcs["Shirley"].closeness < fresh._social.arcs["Shirley"].closeness
    assert called._social.arcs["Sam"].closeness > fresh._social.arcs["Sam"].closeness


# ======================================================================
# 3. Living together: each one's view of the other is the other's life
# ======================================================================

#: A Wednesday, 02:00: Roberta (23:00-07:00) is asleep, Lina (04:00-12:00) up.
WEDNESDAY_0200 = datetime(2026, 10, 7, 2, 0)
LINA_NIGHT = {"bedtime_hour": 4, "bedtime_minute": 0, "wake_hour": 12, "wake_minute": 0}
ROBERTA_NIGHT = {"bedtime_hour": 23, "bedtime_minute": 0, "wake_hour": 7, "wake_minute": 0}
ROBERTA_ENTRY = {"name": "Roberta", "kind": "co_resident", "relationship": "partner in the gig"}
LINA_ENTRY = {"name": "Lina", "kind": "co_resident", "relationship": "partner in the gig"}
FARID_ENTRY = {"name": "Farid", "relationship": "nomad driver"}


def _housemate(tmp_path, pid: str, name: str, world, household, *, circle=(), expects=(),
               sleep_schedule=None, seed: int = 7) -> LifeService:
    """A persona of ``world`` living in ``household`` (``None``: alone), with
    a definition of her own -- her name, her pronouns, whom she expects to
    live with -- her social circle and her sleep schedule."""
    definition = PersonalityDefinition(id=pid, name=name, appearance_details={"gender": "female"},
                                       household=list(expects))
    svc = LifeService(db_path=str(tmp_path / f"{pid}.db"), persona_id=pid, world_environment=world,
                      rng=random.Random(seed), definition=definition, social_circle=list(circle),
                      sleep_schedule=sleep_schedule, household=household)
    svc._desire_system.should_do_intimate_activity = lambda *args, **kw: False
    return svc


def _home_at(tmp_path, clock):
    """Lina and Roberta in one home, one world, on ``clock``."""
    world = WorldEnvironment(now=clock, seed=3)
    home = Household()
    lina = _housemate(tmp_path, "lina", "Lina", world, home, circle=[ROBERTA_ENTRY, FARID_ENTRY],
                      expects=["roberta"], sleep_schedule=LINA_NIGHT, seed=7)
    roberta = _housemate(tmp_path, "roberta", "Roberta", world, home, circle=[LINA_ENTRY, FARID_ENTRY],
                         expects=["lina"], sleep_schedule=ROBERTA_NIGHT, seed=8)
    return home, lina, roberta


def _plan(svc: LifeService, activity: str, location: str, hour: int = 14) -> None:
    svc._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=hour, activity_name=activity, reason="routine", location=location)])


def _members(svc: LifeService) -> list:
    return svc.export_outer_state()["social"]["household"]["members"]


def _household_lines(svc: LifeService) -> list:
    """The lines of her context's "The people you live with" section."""
    context = svc.get_life_context()
    header = "**The people you live with:**"
    if header not in context:
        return []
    section = context.split(header, 1)[1].split("\n\n", 1)[0]
    return [line for line in section.splitlines() if line]


def test_while_roberta_sleeps_lina_s_context_describes_her_as_asleep(tmp_path):
    """The acceptance: at 02:00 Roberta is asleep and Lina is up. Lina's
    context says Roberta is asleep -- read from Roberta's own state -- and
    Roberta's says Lina is here, not asleep."""
    _, lina, roberta = _home_at(tmp_path, ScriptedClock(WEDNESDAY_0200))
    assert roberta.is_asleep() and not lina.is_asleep()
    assert _household_lines(lina) == ["- Roberta is asleep"]
    assert _household_lines(roberta) == ["- Lina is here with you"]
    assert [(m["persona_id"], m["name"], m["asleep"]) for m in _members(lina)] == [("roberta", "Roberta", True)]
    assert [(m["persona_id"], m["name"], m["asleep"]) for m in _members(roberta)] == [("lina", "Lina", False)]


def test_once_she_is_up_lina_s_context_says_where_roberta_is_and_what_she_is_doing(tmp_path, persona_clock):
    _, lina, roberta = _home_at(tmp_path, persona_clock)
    assert _household_lines(lina) == ["- Roberta is here with you"]
    _plan(roberta, "reading", "cafe")
    roberta._on_activity_tick()
    assert roberta._current_location == "cafe"
    assert _household_lines(lina) == ["- Roberta is at the cafe (reading)"]
    view = _members(lina)[0]
    assert (view["asleep"], view["location"], view["activity"], view["here"]) == (False, "cafe", "reading", False)
    persona_clock.instant += timedelta(minutes=20)
    _plan(roberta, "journaling", "home")
    roberta._on_activity_tick()
    assert _household_lines(lina) == ["- Roberta is here with you (journaling)"]
    assert lina.get_status()["social"]["household"]["members"][0]["activity"] == "journaling"


@pytest.mark.parametrize("private", [activity.name for activity in get_setting().intimate_catalogue()])
def test_what_she_does_in_private_is_never_in_a_housemate_s_view(tmp_path, persona_clock, private):
    """Every intimate activity is hers alone: done on her own activity tick,
    the one she lives with sees her home, and nothing of what she is doing --
    not in the context, the status or the export (the smoke run showed one
    named)."""
    _, lina, roberta = _home_at(tmp_path, persona_clock)
    chosen = next(a for a in roberta._setting.intimate_catalogue() if a.name == private)
    roberta._desire_system.should_do_intimate_activity = lambda *args, **kw: True
    roberta._desire_system.select_intimate_activity = lambda: chosen
    roberta._on_activity_tick()
    assert roberta._recent_activities[0].activity_name == private
    assert _household_lines(lina) == ["- Roberta is here with you"]
    assert _members(lina)[0]["activity"] == ""
    assert private not in lina.get_life_context()
    assert private not in str(lina.get_status()) and private not in str(lina.export_outer_state())


def test_a_view_read_mid_tick_is_the_housemate_s_last_complete_state(tmp_path, persona_clock):
    """Her view of Roberta is what Roberta published at the end of a tick.
    Read on another thread while Roberta's tick is half-way -- already at the
    cafe, her reading already logged, the tick not done -- it is her last
    complete state, never a mix of the two; once the tick ends, the new one."""
    _, lina, roberta = _home_at(tmp_path, persona_clock)
    before = _members(lina)[0]
    assert (before["location"], before["activity"], before["here"]) == ("home", "", True)
    _plan(roberta, "reading", "cafe")
    paused, resume = threading.Event(), threading.Event()
    record = roberta._record_activity

    def pausing(log):
        record(log)
        paused.set()
        resume.wait(10)

    roberta._record_activity = pausing
    worker = threading.Thread(target=roberta._on_activity_tick)
    worker.start()
    try:
        assert paused.wait(10), "her tick never reached its log"
        assert roberta._current_location == "cafe"
        assert roberta._recent_activities[0].activity_name == "reading"
        assert _members(lina)[0] == before
        assert _household_lines(lina) == ["- Roberta is here with you"]
    finally:
        resume.set()
        worker.join(10)
    assert not worker.is_alive()
    assert _household_lines(lina) == ["- Roberta is at the cafe (reading)"]


def test_lina_s_view_of_roberta_wakes_when_roberta_does(tmp_path, persona_clock):
    """Asleep at 02:00; at 09:00 -- past her wake -- Roberta's own tick wakes
    her and she reads: Lina's view says asleep until that tick, then where
    she is and what she is doing."""
    persona_clock.instant = WEDNESDAY_0200
    _, lina, roberta = _home_at(tmp_path, persona_clock)
    assert _household_lines(lina) == ["- Roberta is asleep"]
    persona_clock.instant = datetime(2026, 10, 7, 9, 0)
    assert _household_lines(lina) == ["- Roberta is asleep"]
    _plan(roberta, "reading", "home", hour=9)
    roberta._on_activity_tick()
    assert not roberta.is_asleep()
    assert _household_lines(lina) == ["- Roberta is here with you (reading)"]


def test_a_housemate_is_named_as_her_social_circle_names_her(tmp_path, persona_clock):
    """Her entry for a housemate is the one whose name is the housemate's
    persona id or definition name, in any case; with none, the housemate is
    named by her definition."""
    world = WorldEnvironment(now=persona_clock, seed=3)
    home = Household()
    lina = _housemate(tmp_path, "lina", "Lina", world, home,
                      circle=[{"name": "ROBERTA", "kind": "partner", "relationship": "choom"}])
    roberta = _housemate(tmp_path, "roberta", "Berta", world, home, circle=[FARID_ENTRY])
    assert lina._housemate_npc_names() == {"ROBERTA"}
    assert [m["name"] for m in _members(lina)] == ["ROBERTA"]
    assert roberta._housemate_npc_names() == set()
    assert [m["name"] for m in _members(roberta)] == ["Lina"]


def test_a_housemate_s_social_circle_entry_draws_no_ordinary_event():
    """SocialSystem.tick(skip=...): the people she lives with are never drawn;
    anyone else still is, and nothing skipped draws everyone."""
    def drawn(skip) -> set:
        social = SocialSystem(npcs=[NPC(name="Roberta", relationship="partner", kind="co_resident"),
                                    NPC(name="Farid", relationship="driver")], rng=random.Random(9))
        social._npc_event_chance = 1.0
        names = set()
        for _ in range(200):
            social._last_contact.clear()
            event = social.tick(skip=skip)
            if event is not None:
                names.add(event.npc_name)
        return names

    assert drawn({"Roberta"}) == {"Farid"}
    assert drawn(set()) == {"Roberta", "Farid"}
    assert drawn({"Roberta", "Farid"}) == set()


def _skips_asked(svc: LifeService) -> list:
    """Every ``skip`` her activity tick hands the social tick, in order."""
    asked = []
    original = svc._social.tick

    def recording(skip=(), **kwargs):
        asked.append(set(skip))
        return original(skip=skip, **kwargs)

    svc._social.tick = recording
    return asked


def test_a_household_member_missing_at_runtime_degrades_to_an_ordinary_npc(tmp_path, persona_clock):
    """Lina expects Roberta. Not joined, Roberta is an ordinary NPC -- drawn
    like anyone, missing from the status, absent from the context; joined,
    she is a housemate; stopped, an ordinary NPC again."""
    world = WorldEnvironment(now=persona_clock, seed=3)
    home = Household()
    lina = _housemate(tmp_path, "lina", "Lina", world, home, circle=[ROBERTA_ENTRY, FARID_ENTRY],
                      expects=["roberta"])
    asked = _skips_asked(lina)
    _plan(lina, "journaling", "home")

    def tick_lina():
        lina._on_activity_tick()
        persona_clock.instant += timedelta(minutes=20)

    tick_lina()
    assert asked[-1] == set()
    assert lina.export_outer_state()["social"]["household"] == {
        "members": [], "expected": ["roberta"], "missing": ["roberta"]}
    assert _household_lines(lina) == []

    roberta = _housemate(tmp_path, "roberta", "Roberta", world, home, circle=[LINA_ENTRY], expects=["lina"])
    tick_lina()
    assert asked[-1] == {"Roberta"}
    assert lina.get_status()["social"]["household"]["missing"] == []
    assert _household_lines(lina) == ["- Roberta is here with you"]

    roberta.stop()
    tick_lina()
    assert asked[-1] == set()
    assert lina.get_status()["social"]["household"]["missing"] == ["roberta"]
    assert _household_lines(lina) == []


def test_a_household_holds_one_service_per_persona(tmp_path, persona_clock):
    world = WorldEnvironment(now=persona_clock, seed=3)
    home = Household()
    lina = _housemate(tmp_path, "lina", "Lina", world, home)
    home.join("LINA", lina)  # again: nothing changes
    assert home.member_ids() == ["lina"] and home.member("Lina") is lina
    with pytest.raises(ValueError, match="lina"):
        LifeService(db_path=str(tmp_path / "other.db"), persona_id="lina", world_environment=world,
                    household=home)
    with pytest.raises(ValueError, match="persona_id"):
        LifeService(db_path=str(tmp_path / "nobody.db"), world_environment=world, household=Household())
    lina.stop()
    assert home.member_ids() == []
    lina.start()
    assert home.member_ids() == ["lina"]
    lina.stop()


def test_a_stop_that_fails_still_leaves_the_household(tmp_path, persona_clock):
    """A host that catches a failed stop() builds her again at once: the
    failed service has left, so the new one joins."""
    world = WorldEnvironment(now=persona_clock, seed=3)
    home = Household()
    lina = _housemate(tmp_path, "lina", "Lina", world, home)
    roberta = _housemate(tmp_path, "roberta", "Roberta", world, home)

    def failing():
        raise RuntimeError("the scheduler would not stop")

    lina._scheduler.stop = failing
    with pytest.raises(RuntimeError, match="would not stop"):
        lina.stop()
    assert home.member_ids() == ["roberta"]
    (tmp_path / "again").mkdir()
    again = _housemate(tmp_path / "again", "lina", "Lina", world, home)
    assert home.member("lina") is again and home.member_ids() == ["roberta", "lina"]
    assert roberta._housemates() == [again]


def test_a_service_dropped_without_stop_gives_her_place_up(tmp_path, persona_clock):
    """A household holds its members weakly: a service the host dropped
    without stop() leaves once nothing else holds it, and a new one for the
    same persona joins -- while one still held, and so still alive, is
    refused as before."""
    world = WorldEnvironment(now=persona_clock, seed=3)
    home = Household()
    old = _housemate(tmp_path, "lina", "Lina", world, home)
    roberta = _housemate(tmp_path, "roberta", "Roberta", world, home)
    old_is = weakref.ref(old)
    del old
    (tmp_path / "new").mkdir()
    new = _housemate(tmp_path / "new", "lina", "Lina", world, home)
    assert old_is() is None
    assert home.member("lina") is new and home.member_ids() == ["roberta", "lina"]
    assert roberta._housemates() == [new]
    with pytest.raises(ValueError, match="lina"):
        LifeService(db_path=str(tmp_path / "other.db"), persona_id="lina", world_environment=world, household=home)


def _stored(db_path) -> tuple:
    """(every table's name, every text value) of a database."""
    with contextlib.closing(sqlite3.connect(str(db_path))) as conn:
        tables = sorted(row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        values = [str(value) for table in tables for row in conn.execute(f'SELECT * FROM "{table}"')
                  for value in row if isinstance(value, str)]
    return tables, values


def test_nothing_about_a_housemate_is_saved_in_her_database(tmp_path):
    """Living together is a runtime link: saved, Lina's database has no table
    a persona living alone lacks and nothing of Roberta's state; reloaded
    alone, she knows nothing of Roberta's life."""
    clock = ScriptedClock(WEDNESDAY_0200)
    _, lina, roberta = _home_at(tmp_path, clock)
    assert _household_lines(lina) == ["- Roberta is asleep"]
    lina._save_state()
    tables, values = _stored(tmp_path / "lina.db")
    solo = _service(tmp_path, "solo")
    solo._save_state()
    assert tables == _stored(tmp_path / "solo.db")[0]
    stored = "\n".join(values)
    assert "asleep" not in stored and "here with you" not in stored and "roberta" not in stored

    alone = _housemate(tmp_path, "lina", "Lina", WorldEnvironment(now=clock, seed=3), None,
                       circle=[ROBERTA_ENTRY, FARID_ENTRY], expects=["roberta"], sleep_schedule=LINA_NIGHT)
    alone._load_state()
    assert _household_lines(alone) == []
    assert alone.export_outer_state()["social"]["household"] == {
        "members": [], "expected": ["roberta"], "missing": ["roberta"]}


# ======================================================================
# 4. What they do together
# ======================================================================

class _Asks:
    """A household stream whose roll always passes (``_Asks(True)``) or never
    does, and which takes the first of every choice."""

    def __init__(self, passes: bool):
        self._passes = passes

    def random(self) -> float:
        return 0.0 if self._passes else 0.999999

    def choice(self, seq):
        return list(seq)[0]


def _cooking_together(tmp_path, persona_clock, *, lonely: float = None, asks: bool = True):
    """Tuesday 14:00, both up and home: Lina's plan says cook, Roberta's
    says read; Lina's household roll passes (or never does)."""
    _, lina, roberta = _home_at(tmp_path, persona_clock)
    _plan(lina, "cooking a meal", "home")
    _plan(roberta, "reading", "home")
    if lonely is not None:
        lina._affect._loneliness.level = roberta._affect._loneliness.level = lonely
    lina._household_rng = _Asks(asks)
    return lina, roberta


def _rows(db_path) -> list:
    """(started_at, activity, location, narrative) of every activity_logs row."""
    with contextlib.closing(sqlite3.connect(str(db_path))) as conn:
        return list(conn.execute(
            "SELECT started_at, activity_name, location, narrative FROM activity_logs ORDER BY id"))


def test_a_joint_activity_is_in_both_logs_each_from_its_own_side(tmp_path, persona_clock, host_hour):
    """Lina cooks; Roberta -- free, awake, home -- joins her. One activity, in
    both logs (the recent ones and the database), at one instant and place,
    each worded from its own side: Roberta joined Lina."""
    lina, roberta = _cooking_together(tmp_path, persona_clock)
    lina._on_activity_tick()
    roberta._on_activity_tick()
    mine, hers = lina._recent_activities, roberta._recent_activities
    assert [log.activity_name for log in mine] == ["cooking a meal"]
    assert [log.activity_name for log in hers] == ["cooking a meal"]
    assert mine[0].started_at == hers[0].started_at
    assert mine[0].location == hers[0].location == "home"
    assert "Roberta joined her." in mine[0].narrative and "Lina" not in mine[0].narrative
    assert "She joined Lina." in hers[0].narrative and "Roberta" not in hers[0].narrative
    lina_rows, roberta_rows = _rows(tmp_path / "lina.db"), _rows(tmp_path / "roberta.db")
    assert [row[:3] for row in lina_rows] == [row[:3] for row in roberta_rows]
    assert "Roberta joined her." in lina_rows[0][3] and "She joined Lina." in roberta_rows[0][3]


def _state(svc: LifeService) -> tuple:
    return (len(svc._recent_activities), svc._energy.effective_level, svc._affect.loneliness.level,
            svc._affect.stress.level, svc._affect.mood.valence, svc._affect.mood.arousal,
            svc._social.social_battery.charge, svc._sustenance.hunger)


def test_loneliness_counts_the_hours_since_company_on_the_world_clock(tmp_path, persona_clock):
    """The world clock, not the host's: company at 14:00, then five simulated
    hours -- no time at all on the wall clock -- and she has been five hours
    without meaningful company; her loneliness grows by what five hours grow
    it (AffectSystem._update_loneliness: after the first four hours) -- since
    Task 34, what the sixty 5-minute ticks of those hours grow it, each by the
    hours since at that tick."""
    lina, roberta = _cooking_together(tmp_path, persona_clock)
    lina._on_activity_tick()
    assert "Roberta joined her." in lina._recent_activities[0].narrative
    stamped = lina._affect.loneliness.last_meaningful_interaction
    assert stamped == persona_clock.instant == roberta._affect.loneliness.last_meaningful_interaction
    persona_clock.instant += timedelta(hours=5)
    before = lina._affect.loneliness.level
    lina._affect.tick(body_state={}, social_state={}, weather="sunny", season="autumn",
                      hours=5.0, now=persona_clock())
    assert (persona_clock.instant - stamped).total_seconds() / 3600 == pytest.approx(5.0)
    grown = lina._affect.loneliness.level - before
    past_four = sum(max(0.0, 5 - k * 5 / 60 - 4) for k in range(60))
    assert grown == pytest.approx(lina._affect.loneliness.desired_contact_baseline * 0.003 * past_four / 4)
    assert grown > 0


@pytest.mark.parametrize("path", ["a friend's call", "a user message", "a theater conversation"])
def test_every_meaningful_interaction_is_stamped_on_the_world_clock(tmp_path, persona_clock, path):
    """Whatever the company -- one of her people, the user, another persona
    -- the moment is the world's (a week and more from the host's today)."""
    svc = _service(tmp_path, "stamped", persona_clock, social_circle=[{"name": "Sam", "relationship": "friend"}])
    if path == "a friend's call":
        svc._on_social_event(_event("Sam", "friend", "call", 1.0), ActivityLog(narrative="She read"), "reading")
    elif path == "a user message":
        svc.on_user_message("hey, how was your day?")
    else:
        svc.on_theater_conversation("Roberta", tone="positive")
    assert svc._affect.loneliness.last_meaningful_interaction == persona_clock.instant
    assert abs((datetime.now() - persona_clock.instant).days) >= 1


def test_a_joint_activity_is_done_once_by_each(tmp_path, persona_clock, host_hour):
    """Roberta does it through her own pipeline when she joins; her own tick
    at that instant is taken by it and changes nothing; her next is hers.
    Joining took her hour (Task 28): her next tick in it is her own -- no
    second joint entry -- and follows the hour as her plan now has it; the
    next hour is as she planned it."""
    lina, roberta = _cooking_together(tmp_path, persona_clock)
    roberta._household_rng = _Asks(False)
    roberta._daily_planner.current_plan.slots.append(
        PlannedSlot(hour=15, activity_name="reading", reason="routine", location="home"))
    lina._on_activity_tick()
    joined = _state(roberta)
    roberta._on_activity_tick()
    assert _state(roberta) == joined
    persona_clock.instant += timedelta(minutes=20)
    roberta._on_activity_tick()
    persona_clock.instant = TUESDAY_1400.replace(hour=15)
    roberta._on_activity_tick()
    entries = roberta._recent_activities
    assert [log.activity_name for log in entries] == ["reading", "cooking a meal", "cooking a meal"]
    assert ["She joined Lina." in log.narrative for log in entries] == [False, False, True]


def test_each_one_s_company_eases_the_other_s_loneliness_once(tmp_path, persona_clock):
    """Against the same tick with Lina never asking: together, each is less
    lonely by one meaningful interaction (AffectSystem.on_social_interaction),
    and each one's arc and view of the other counts the time together."""
    (tmp_path / "together").mkdir()
    (tmp_path / "apart").mkdir()
    lina, roberta = _cooking_together(tmp_path / "together", persona_clock, lonely=0.8)
    lina._on_activity_tick()
    roberta._on_activity_tick()
    lone_lina, lone_roberta = _cooking_together(tmp_path / "apart", persona_clock, lonely=0.8, asks=False)
    _plan(lone_roberta, "cooking a meal", "home")
    lone_lina._on_activity_tick()
    lone_roberta._on_activity_tick()
    assert [log.activity_name for log in lone_roberta._recent_activities] == ["cooking a meal"]
    assert lone_lina._affect.loneliness.level - lina._affect.loneliness.level == pytest.approx(0.15)
    assert lone_roberta._affect.loneliness.level - roberta._affect.loneliness.level == pytest.approx(0.15)
    assert lina._social.arcs["Roberta"].shared_history_depth == 1
    assert roberta._social.arcs["Lina"].shared_history_depth == 1
    assert lina._identity._perceptions["Roberta"].shared_memories == ["Cooking a meal with Roberta"]
    assert roberta._identity._perceptions["Lina"].shared_memories == ["Cooking a meal with Lina"]


@pytest.mark.parametrize("case", [
    "never asked", "not a joint activity", "asleep", "about to sleep", "elsewhere", "on the way",
    "at work", "another meal", "already busy this instant", "already joined", "too tired",
    "socially drained", "stopped",
])
def test_no_one_joins_her_who_cannot(tmp_path, persona_clock, case):
    """Roberta joins only an activity tagged "joint" that Lina chose to share,
    awake and not about to sleep, where Lina is and not on the way anywhere,
    in an hour her plan leaves free (or for that very activity), neither
    acting nor joined in something else already, with the energy and the
    social battery for it -- and only while she lives there."""
    persona_clock.instant = {"asleep": WEDNESDAY_0200,
                             "about to sleep": datetime(2026, 10, 6, 22, 50)}.get(case, TUESDAY_1400)
    lina, roberta = _cooking_together(tmp_path, persona_clock, asks=case != "never asked")
    hour = persona_clock.instant.hour
    _plan(lina, "journaling" if case == "not a joint activity" else "cooking a meal", "home", hour=hour)
    _plan(roberta, {"at work": "working", "another meal": "having dinner"}.get(case, "reading"), "home", hour=hour)
    if case == "elsewhere":
        roberta._current_location = "cafe"
    if case == "on the way":
        roberta._transit = TransitState(phase=TransitPhase.IN_TRANSIT, origin="home", destination="cafe")
    if case == "socially drained":
        roberta._social._social_battery.charge = 0.1
    if case == "already busy this instant":
        roberta._on_activity_tick()
    if case == "already joined":
        roberta._joint_until = persona_clock.instant + timedelta(minutes=10)
    if case == "too tired":
        roberta._energy._state.level = 0.1
    if case == "stopped":
        roberta.stop()
    if case == "about to sleep":
        assert not roberta.is_asleep()
    lina._on_activity_tick()
    assert lina._recent_activities, "Lina did nothing: the case proves nothing"
    assert not any("Roberta" in log.narrative for log in lina._recent_activities)
    assert not any("Lina" in log.narrative for log in roberta._recent_activities)
    if case == "asleep":
        assert roberta.is_asleep() and roberta._recent_activities == []


def test_on_the_way_somewhere_she_asks_no_one_in(tmp_path, persona_clock):
    """Lina is on her way out -- still home, where Roberta is free -- and does
    something that could be shared: she asks no one in."""
    lina, roberta = _cooking_together(tmp_path, persona_clock)
    lina._transit = TransitState(phase=TransitPhase.IN_TRANSIT, origin="home", destination="cafe")
    cooking = lina._activity_engine.get_activity("cooking a meal")
    lina._activity_engine.select_activity = lambda **kwargs: cooking
    lina._on_activity_tick()
    assert lina._recent_activities[0].activity_name == "cooking a meal"
    assert lina._current_location == roberta._current_location == "home"
    assert "Roberta" not in lina._recent_activities[0].narrative
    assert roberta._recent_activities == []


def test_a_meal_she_planned_too_they_have_together(tmp_path, persona_clock, host_hour):
    """An hour her plan anchors is never taken by another activity -- but the
    same meal, planned by both, they eat together."""
    lina, roberta = _cooking_together(tmp_path, persona_clock)
    _plan(lina, "having dinner", "home")
    _plan(roberta, "having dinner", "home")
    lina._on_activity_tick()
    assert roberta._recent_activities and roberta._recent_activities[0].activity_name == "having dinner"
    assert "She joined Lina." in roberta._recent_activities[0].narrative


def test_a_joint_activity_goes_where_the_activity_is(tmp_path, persona_clock, host_hour):
    """Lina's plan takes her to the park for a walk; Roberta, home with her,
    goes too -- and stays, whatever hour the host runs at: her plan's 14:00
    slot said reading at home, and the sync of her plan at the end of what
    she did sent her back home whenever the host's clock was past 14:00
    (Task 28)."""
    lina, roberta = _cooking_together(tmp_path, persona_clock)
    _plan(lina, "going for a walk", "park")
    lina._on_activity_tick()
    assert lina._current_location == roberta._current_location == "park"
    assert roberta._recent_activities[0].activity_name == "going for a walk"
    assert roberta._recent_activities[0].location == "park"


def test_joining_takes_her_hour_so_she_stays_where_the_activity_is(tmp_path, persona_clock, host_hour):
    """Joining is an override of her own plan for the hour (Task 28, ruling
    T13-R1): Roberta's 14:00 slot said reading at home; she joins Lina's
    walk, and the slot is the walk, at the park, done -- so every later sync
    of her plan keeps her there; the hour after it is as she planned it."""
    lina, roberta = _cooking_together(tmp_path, persona_clock)
    _plan(lina, "going for a walk", "park")
    roberta._daily_planner.current_plan.slots.append(
        PlannedSlot(hour=15, activity_name="journaling", reason="routine", location="home"))
    lina._on_activity_tick()
    assert roberta._recent_activities[0].activity_name == "going for a walk"
    slot = roberta._daily_planner.get_planned_activity(14)
    assert (slot.activity_name, slot.location, slot.reason, slot.completed, slot.actual_activity) == (
        "going for a walk", "park", "with Lina", True, "going for a walk")
    later = roberta._daily_planner.get_planned_activity(15)
    assert (later.activity_name, later.location, later.completed) == ("journaling", "home", False)
    assert roberta.get_current_location() == "park"
    assert roberta.get_status()["location"] == "park"
    roberta._check_visual_transition()
    assert roberta._current_location == "park"
    assert _household_lines(lina) == ["- Roberta is here with you (going for a walk)"]


def test_inside_a_joint_activity_reading_her_state_never_moves_her(tmp_path, persona_clock, host_hour):
    """She joined Lina's walk at 14:50; it is hers until 15:10 (``_joint_until``,
    one activity interval). At 15:05 her plan's slot is 15:00's journaling at
    home, and get_status(), the visual check and a resumed plan read her
    location: none sends her home -- she is where she is until the window
    closes; then her plan's hour is hers again (Task 28 fix round 1)."""
    persona_clock.instant = TUESDAY_1400.replace(minute=50)
    lina, roberta = _cooking_together(tmp_path, persona_clock)
    _plan(lina, "going for a walk", "park")
    roberta._daily_planner.current_plan.slots.append(
        PlannedSlot(hour=15, activity_name="journaling", reason="routine", location="home"))
    lina._on_activity_tick()
    assert roberta._current_location == "park"
    assert roberta._joint_until == datetime(2026, 10, 6, 15, 10)

    persona_clock.instant = datetime(2026, 10, 6, 15, 5)
    assert roberta.get_current_location() == "park"
    assert roberta.get_status()["location"] == "park"
    roberta._check_visual_transition()
    roberta.resume_planned_activity()
    assert roberta._current_location == "park"
    assert _household_lines(lina) == ["- Roberta is here with you (going for a walk)"]

    persona_clock.instant = datetime(2026, 10, 6, 15, 10)
    assert roberta.get_current_location() == "home"
    assert roberta._current_location == "home"


def _doing(svc: LifeService) -> tuple:
    """Every read of what she is doing (humanness Task 19, ruling T19-R5):
    current_activity_name, get_status()'s current_activity, her context's
    "Right now" line, her next activity, and the plan export_inner_state()
    hands a digest pass (its current and next slot)."""
    right_now = [line for line in svc.get_life_context().splitlines() if line.startswith("- Right now:")]
    plan = svc.export_inner_state()["drive"]["plan"]
    return (svc.current_activity_name, svc.get_status()["current_activity"], right_now,
            svc._next_activity_info()[0], (plan["current_slot"] or {}).get("activity"),
            (plan["next_slot"] or {}).get("activity"))


def test_at_a_joint_window_s_tail_what_she_is_doing_is_the_joint_activity(tmp_path, persona_clock, host_hour):
    """She joined Lina's walk at 14:50, at the park until 15:10 (``_joint_until``).
    At 15:05 her plan's hour is 15:00's journaling at home, but she is held at
    the park (``_location_held()``): every read of what she is doing says the
    walk, where she is, and what comes next is the journaling; from 15:10 on
    they read the new hour's slot again (Task 19, ruling T19-R5). Before, at
    15:05 they said journaling while her location said the park."""
    persona_clock.instant = TUESDAY_1400.replace(minute=50)
    lina, roberta = _cooking_together(tmp_path, persona_clock)
    _plan(lina, "going for a walk", "park")
    plan = roberta._daily_planner.current_plan
    plan.slots.append(PlannedSlot(hour=15, activity_name="journaling", reason="routine", location="home"))
    plan.slots.append(PlannedSlot(hour=17, activity_name="gaming", reason="routine", location="home"))
    lina._on_activity_tick()

    persona_clock.instant = datetime(2026, 10, 6, 15, 5)
    assert roberta._location_held() and roberta.get_current_location() == "park"
    assert _doing(roberta) == ("going for a walk", "Going for a walk", ["- Right now: going for a walk (at the park)"],
                               "journaling", "going for a walk", "journaling")

    persona_clock.instant = datetime(2026, 10, 6, 15, 10)
    assert not roberta._location_held() and roberta.get_current_location() == "home"
    assert _doing(roberta) == ("journaling", "Journaling", ["- Right now: journaling (at home)"],
                               "gaming", "journaling", "gaming")


class _TakesTriggers:
    """A host's follow-up manager: takes every trigger."""

    def create_trigger(self, *args, **kwargs):
        pass


def test_at_a_joint_window_s_tail_her_body_her_mind_her_moment_and_her_looks_follow_the_joint_activity(
        tmp_path, persona_clock, host_hour, monkeypatch):
    """The walk's tail as above, at 15:05: her energy tick hands her body and
    her mind the walk (her comfort takes a walk's toll, not a desk's), and her
    plan is read at the instant she joined by every read the tick makes -- the
    moment a proactive share would name among them -- and by the visual check
    (the walk, at the park). Before, these three read 15:00's journaling at
    home (Task 19 fix round 1, I2; ruling T19-R5: every read)."""
    persona_clock.instant = TUESDAY_1400.replace(minute=50)
    lina, roberta = _cooking_together(tmp_path, persona_clock)
    _plan(lina, "going for a walk", "park")
    plan = roberta._daily_planner.current_plan
    plan.slots.append(PlannedSlot(hour=15, activity_name="journaling", reason="routine", location="home"))
    lina._on_activity_tick()
    persona_clock.instant = datetime(2026, 10, 6, 15, 5)
    assert roberta._location_held() and roberta._joint_at == TUESDAY_1400.replace(minute=50)

    read_at, told = [], {}
    real_slot, real_body, real_mind = plan.get_current_slot, roberta._body.tick, roberta._cognitive.tick

    def slot(now=None):
        read_at.append(now)
        return real_slot(now)

    def body(*args, **kwargs):
        told["body"] = kwargs["activity_name"]
        return real_body(*args, **kwargs)

    def mind(*args, **kwargs):
        told["mind"] = kwargs["current_activity"]
        return real_mind(*args, **kwargs)

    monkeypatch.setattr(plan, "get_current_slot", slot)
    monkeypatch.setattr(roberta._body, "tick", body)
    monkeypatch.setattr(roberta._cognitive, "tick", mind)
    monkeypatch.setattr(roberta, "_trigger_visual_description_update", lambda: None)
    roberta._follow_up_provider = lambda persona_id: _TakesTriggers()
    roberta._on_energy_tick()
    assert told == {"body": "going for a walk", "mind": "going for a walk"}
    roberta._check_visual_transition()
    assert (roberta._last_visual_activity, roberta._last_visual_location) == ("going for a walk", "park")
    assert read_at and set(read_at) == {roberta._joint_at}, read_at


def test_joining_in_an_hour_her_plan_left_empty_gives_her_that_hour(tmp_path, persona_clock, host_hour):
    """Her plan had nothing at 14:00 -- noon's reading at home before it,
    journaling at 16:00 after: joining Lina's walk adds the 14:00 slot, so
    her plan's current slot is the walk at the park, not noon's."""
    lina, roberta = _cooking_together(tmp_path, persona_clock)
    _plan(lina, "going for a walk", "park")
    roberta._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=12, activity_name="reading", reason="routine", location="home"),
        PlannedSlot(hour=16, activity_name="journaling", reason="routine", location="home")])
    lina._on_activity_tick()
    assert roberta._recent_activities[0].activity_name == "going for a walk"
    assert [(s.hour, s.activity_name, s.location) for s in roberta._daily_planner.current_plan.slots] == [
        (12, "reading", "home"), (14, "going for a walk", "park"), (16, "journaling", "home")]
    assert roberta.get_current_location() == "park"
    assert roberta._current_location == "park"


def test_everyone_free_joins_and_each_log_names_them_from_its_own_side(tmp_path, persona_clock, host_hour):
    """Three at home: Roberta and Ada both join Lina's dinner -- one instant
    in three logs; Lina's names them both, each of theirs names Lina."""
    world = WorldEnvironment(now=persona_clock, seed=3)
    home = Household()
    lina = _housemate(tmp_path, "lina", "Lina", world, home, circle=[ROBERTA_ENTRY], seed=7)
    roberta = _housemate(tmp_path, "roberta", "Roberta", world, home, circle=[LINA_ENTRY], seed=8)
    ada = _housemate(tmp_path, "ada", "Ada", world, home, seed=9)
    for svc in (lina, roberta, ada):
        _plan(svc, "having dinner", "home")
    lina._household_rng = _Asks(True)
    lina._on_activity_tick()
    entries = [svc._recent_activities[0] for svc in (lina, roberta, ada)]
    assert {entry.activity_name for entry in entries} == {"having dinner"}
    assert len({entry.started_at for entry in entries}) == 1
    assert "Roberta and Ada joined her." in entries[0].narrative
    assert "She joined Lina." in entries[1].narrative and "She joined Lina." in entries[2].narrative
    # Her arc and her view: only for the one in her social circle.
    assert set(lina._social.arcs) >= {"Roberta"} and "Ada" not in lina._social.arcs
    assert lina._identity._perceptions["Roberta"].shared_memories == ["Having dinner with Roberta and Ada"]


def test_every_member_s_activity_tick_holds_the_household_lock(tmp_path, persona_clock):
    """A joint activity writes into a housemate's life: each member's activity
    tick runs under the household's lock, and leaving waits for it."""
    _, lina, roberta = _home_at(tmp_path, persona_clock)
    home = lina._household
    held = []
    run_tick = lina._activity_tick

    def watched():
        held.append(home.lock._is_owned())
        run_tick()

    lina._activity_tick = watched
    lina._on_activity_tick()
    assert held == [True]
    assert not home.lock._is_owned()
    alone = _service(tmp_path, "alone", persona_clock)
    assert alone._household is None
    alone._on_activity_tick()  # no household: no lock to take, the tick as it always was


@pytest.mark.parametrize("view,line", [
    (dict(name="Roberta", asleep=True, here=True, location="home", activity="reading"), "Roberta is asleep"),
    (dict(name="Roberta", asleep=False, here=True, location="home", activity="reading"),
     "Roberta is here with you (reading)"),
    (dict(name="Roberta", asleep=False, here=True, location="cafe", activity=""), "Roberta is here with you"),
    (dict(name="Roberta", asleep=False, here=False, location="home", activity="gym workout"),
     "Roberta is at home (gym workout)"),
    (dict(name="Roberta", asleep=False, here=False, location="rooftop_bar", activity=""),
     "Roberta is at the rooftop bar"),
    (dict(name="Roberta", asleep=False, here=False, location="the park", activity=""), "Roberta is at the park"),
    (dict(name="Roberta", asleep=False, here=False, location="in transit", in_transit=True,
          destination="cafe", activity=""), "Roberta is on the way to the cafe"),
    (dict(name="Roberta", asleep=False, here=False, location="in transit", in_transit=True,
          destination="home", activity=""), "Roberta is on the way home"),
])
def test_a_housemate_is_described_as_she_is(view, line):
    from aura_life.social.household import describe_housemate

    assert describe_housemate(view) == line


@pytest.mark.parametrize("text,out", [
    ("She cooked", "She cooked. Roberta joined her."),
    ("She cooked!", "She cooked! Roberta joined her."),
    ("She cooked. ", "She cooked. Roberta joined her."),
    ("", "Roberta joined her."),
])
def test_the_line_that_says_who_she_did_it_with_is_its_own_sentence(text, out):
    from aura_life.life_service import _add_sentence

    assert _add_sentence(text, "Roberta joined her") == out


def _lives_together(home: Household) -> list:
    def persona(pid, name, entry, other):
        return SimPersona(pid, service_kwargs=dict(
            definition=PersonalityDefinition(id=pid, name=name, appearance_details={"gender": "female"},
                                             household=[other]),
            social_circle=[entry, FARID_ENTRY], household=home))
    return [persona("lina", "Lina", ROBERTA_ENTRY, "roberta"), persona("roberta", "Roberta", LINA_ENTRY, "lina")]


def _joint_entries(db_path, other: str) -> dict:
    """(instant, activity, place) -> narrative, for every row naming ``other``."""
    return {row[:3]: row[3] for row in _rows(db_path) if other in row[3]}


@pytest.fixture(scope="module")
def two_days_together(tmp_path_factory):
    """Lina and Roberta, two simulated days at the production cadence, twice
    over on the same seed."""
    runs = []
    for attempt in range(2):
        data_dir = tmp_path_factory.mktemp(f"together{attempt}")
        trace = run_days(_lives_together(Household()), days=2, cadence=PRODUCTION, seed=5, data_dir=data_dir)
        runs.append((trace, data_dir))
    return runs


def test_two_lives_under_one_roof_write_each_joint_activity_into_both_logs(two_days_together):
    """The acceptance, over two simulated days: every entry of Lina's that
    names Roberta is an entry of Roberta's at the same instant and place that
    names Lina, and back; one side is worded as the one who started it, the
    other as the one who joined; neither log holds two entries at one
    instant."""
    from aura_life.personas.pronoun_render import render_line
    from aura_life.social.household import JOINT_LINES

    trace, data_dir = two_days_together[0]
    assert trace.errors == []
    lina = _joint_entries(data_dir / "lina" / "life.db", "Roberta")
    roberta = _joint_entries(data_dir / "roberta" / "life.db", "Lina")
    assert len(lina) >= 3, lina
    assert set(lina) == set(roberta)

    def worded(narrative: str, role: str, name: str) -> bool:
        return any(render_line(line, gender="female", name=name) + "." in narrative for line in JOINT_LINES[role])

    for key in lina:
        started = worded(lina[key], "initiator", "Roberta") and worded(roberta[key], "joiner", "Lina")
        joined = worded(lina[key], "joiner", "Roberta") and worded(roberta[key], "initiator", "Lina")
        assert started != joined, (key, lina[key], roberta[key])
    for pid in ("lina", "roberta"):
        instants = [row[0] for row in _rows(data_dir / pid / "life.db")]
        assert len(instants) == len(set(instants)), pid


def test_the_one_who_joined_is_recorded_doing_it_in_the_simulation(two_days_together):
    """tests/sim_helpers.py records a step's activity for the one who joined,
    though it was her housemate's tick that wrote it."""
    trace, data_dir = two_days_together[0]
    for pid, other in (("lina", "Roberta"), ("roberta", "Lina")):
        joint = _joint_entries(data_dir / pid / "life.db", other)
        assert joint, pid
        recorded = {(r.t.isoformat(), r.activity) for r in trace.records[pid] if r.activity}
        assert {(instant, activity) for instant, activity, _ in joint} <= recorded, pid


def test_the_same_seed_gives_the_same_joint_activities(two_days_together):
    (_, first), (_, second) = two_days_together
    for pid, other in (("lina", "Roberta"), ("roberta", "Lina")):
        joint = _joint_entries(first / pid / "life.db", other)
        assert joint, pid
        assert joint == _joint_entries(second / pid / "life.db", other)
