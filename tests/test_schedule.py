"""Tests for aura_life.schedule — the host-populated schedule container.

`PersonaSchedule` used to dispatch on hardcoded persona ids and ship three
named characters' authored weekly schedules. That was the private app's
content living in a general-purpose library, and it was broken by design:
every id outside the hardcoded three silently got an empty schedule with no
way to fill it.

These tests pin the replacement contract: an empty schedule is the documented
default for EVERY id, the host supplies the events, and no character content
can creep back in.
"""
import inspect
import re
from datetime import datetime, time, timedelta

import pytest

from aura_life import schedule as schedule_mod
from aura_life.schedule import (
    EventType,
    PersonaSchedule,
    ScheduledEvent,
    UpcomingEvent,
    get_persona_schedule,
)


# Names of the private app's characters whose schedules used to be hardcoded
# here. None of them may appear in the module again.
FORBIDDEN_CHARACTER_NAMES = ("florence", "samantha", "alice")


def _make_event(**overrides) -> ScheduledEvent:
    """A daily event, so `get_next_occurrence` always resolves within 24h."""
    kwargs = dict(
        event_type=EventType.PERSONAL,
        title="Host supplied event",
        description="Provided by the host application",
        scheduled_time=time(12, 0),
        days_of_week=[],          # daily
        share_before_minutes=30,
        share_probability=0.0,    # deterministic: never randomly notifies
    )
    kwargs.update(overrides)
    return ScheduledEvent(**kwargs)


# --------------------------------------------------------------------------
# An empty schedule is the documented default for every id
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "persona_id",
    ["florence", "samantha", "alice", "ada", "grace", "", "Anyone-Else"],
)
def test_fresh_schedule_is_empty_for_any_persona_id(persona_id):
    """No id is special. A fresh schedule holds nothing until the host fills it."""
    sched = PersonaSchedule(persona_id)
    assert sched.persona_id == persona_id
    assert sched.events == []
    assert sched.get_upcoming_events(within_minutes=10_000) == []
    assert sched.get_events_to_share() == []


def test_no_persona_id_dispatch_remains():
    """The id-keyed loader methods are gone, not merely unreferenced."""
    for gone in (
        "_load_default_schedule",
        "_load_florence_schedule",
        "_load_samantha_schedule",
        "_load_alice_schedule",
    ):
        assert not hasattr(PersonaSchedule, gone), f"{gone} should no longer exist"


# --------------------------------------------------------------------------
# Host-supplied events are stored and queryable
# --------------------------------------------------------------------------

def test_events_supplied_at_construction_are_stored():
    ev1 = _make_event(title="First")
    ev2 = _make_event(title="Second")
    sched = PersonaSchedule("any-host-id", events=[ev1, ev2])
    assert sched.events == [ev1, ev2]


def test_constructor_copies_the_caller_list():
    """Mutating the list the host passed in must not reach into the schedule."""
    supplied = [_make_event(title="Only one")]
    sched = PersonaSchedule("any-host-id", events=supplied)
    supplied.append(_make_event(title="Sneaked in"))
    assert [e.title for e in sched.events] == ["Only one"]


def test_add_event_appends():
    sched = PersonaSchedule("any-host-id")
    ev = _make_event(title="Added later")
    sched.add_event(ev)
    assert sched.events == [ev]

    ev2 = _make_event(title="Added after that")
    sched.add_event(ev2)
    assert sched.events == [ev, ev2]


def test_host_supplied_events_are_queryable_through_upcoming():
    """A stored event actually flows through the query API."""
    ev = _make_event(title="Queryable")
    sched = PersonaSchedule("any-host-id", events=[ev])

    upcoming = sched.get_upcoming_events(within_minutes=24 * 60 + 1)
    assert len(upcoming) == 1
    assert isinstance(upcoming[0], UpcomingEvent)
    assert upcoming[0].event is ev
    assert upcoming[0].should_notify is False   # share_probability=0.0


def test_get_events_to_share_returns_events_inside_the_share_window():
    """share_probability=1.0 inside the window is a deterministic notify."""
    soon = (datetime.now() + timedelta(minutes=10)).time()
    ev = _make_event(
        title="Imminent",
        scheduled_time=time(soon.hour, soon.minute),
        share_before_minutes=30,
        share_probability=1.0,
    )
    sched = PersonaSchedule("any-host-id", events=[ev])
    to_share = sched.get_events_to_share()
    assert [u.event.title for u in to_share] == ["Imminent"]


def test_upcoming_events_are_sorted_by_proximity():
    now = datetime.now()
    later = (now + timedelta(minutes=200)).time()
    sooner = (now + timedelta(minutes=100)).time()
    far = _make_event(title="Later", scheduled_time=time(later.hour, later.minute))
    near = _make_event(title="Sooner", scheduled_time=time(sooner.hour, sooner.minute))
    sched = PersonaSchedule("any-host-id", events=[far, near])

    titles = [u.event.title for u in sched.get_upcoming_events(within_minutes=24 * 60 + 1)]
    assert titles == ["Sooner", "Later"]


# --------------------------------------------------------------------------
# get_persona_schedule keeps working
# --------------------------------------------------------------------------

def test_get_persona_schedule_signature_and_caching():
    schedule_mod.clear_persona_schedule()
    try:
        sched = get_persona_schedule("some-host-persona")
        assert isinstance(sched, PersonaSchedule)
        assert sched.persona_id == "some-host-persona"
        assert sched.events == []
        assert get_persona_schedule("some-host-persona") is sched
    finally:
        schedule_mod.clear_persona_schedule()


def test_get_persona_schedule_returns_a_container_the_host_can_fill():
    schedule_mod.clear_persona_schedule()
    try:
        get_persona_schedule("some-host-persona").add_event(_make_event(title="Filled"))
        assert [e.title for e in get_persona_schedule("some-host-persona").events] == ["Filled"]
    finally:
        schedule_mod.clear_persona_schedule()


# --------------------------------------------------------------------------
# Regression guard: no character content, ever again
# --------------------------------------------------------------------------

def test_module_source_contains_no_character_names():
    """Hard guard so the private app's characters cannot be reintroduced."""
    source = inspect.getsource(schedule_mod).lower()
    for name in FORBIDDEN_CHARACTER_NAMES:
        assert not re.search(rf"\b{name}\b", source), (
            f"character name {name!r} is back in aura_life/schedule.py — "
            "this module must stay free of the host app's persona content"
        )


def test_module_source_contains_no_authored_prompt_content():
    """The authored pre-event lines went with the characters."""
    source = inspect.getsource(schedule_mod).lower()
    for phrase in (
        "indie singer",
        "psychologist",
        "photographer",
        "dr. chen",
        "band rehearsal",
        "darkroom",
        "yoga mat",
    ):
        assert phrase not in source, f"authored persona content {phrase!r} is back"
