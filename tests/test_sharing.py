"""Task 5 (aura humanness program): life events recorded once, and every
unshared life event / shareable experience carrying a stable id that
LifeService.mark_shared() can act on.

Measured before this task (task brief; see also
docs/analyses/aura-life-humanness_2026-09-25_harness/analyze.py): a persona
logged about 380 life events over a 3-simulated-day run, 72-76% of them a
template slotted with a bare engine label or mood word as its noun (e.g.
"Felt genuinely proud of content", "Couldn't stop thinking about reading");
tests/test_life_events.py covers that fix directly. And nothing ever marked
an event or shareable as shared -- mark_shared had no caller anywhere, so the
"eager to share" queue only ever grew. This file covers the stable-id /
mark_shared half, plus the 3-day acceptance measure for the templating fix
(the < 10% threshold needs a real run to sample against).
"""

import re
import sqlite3
from datetime import datetime

import pytest

from aura_life.affect.affect_system import MOOD_LABELS
from aura_life.life_events.life_event_system import MOOD_EVENT_MIN_HOURS
from aura_life.life_service import LifeService

from sim_helpers import PRODUCTION, SimPersona, run_days

#: Copied from the measurement harness's SLOT_TEMPLATE_RE (a script kept
#: outside this repository; the regex is copied, never imported). There, `leakage()` matches a context line
#: against this, then checks the matched filler against a set of bare
#: emotion words / activity names seen in the run -- this test does the same,
#: against aura_life.affect.affect_system.MOOD_LABELS (the canonical mood
#: vocabulary Task 5 is about) union the activity names the run actually used.
SLOT_TEMPLATE_RE = re.compile(
    r"^(Felt genuinely proud of|Couldn't stop thinking about|Got a little emotional about"
    r"|Something shifted while|Didn't see this coming —|A strong wave of|While) (.+)$"
)


def _svc(tmp_path, **kwargs) -> LifeService:
    return LifeService(db_path=str(tmp_path / "life.db"), persona_id="testpersona", **kwargs)


def _is_slot_leak(text: str, bare_labels: set) -> bool:
    """True when ``text`` is a template slotted with a bare engine label or
    activity name as its noun -- the defect this task removes."""
    match = SLOT_TEMPLATE_RE.match(text)
    if not match:
        return False
    filler = match.group(2).strip().rstrip(".").lower()
    return filler in bare_labels


# ---------------------------------------------------------------------------
# Stable ids (spec Sec 4.9): every unshared life event and shareable carries
# "event:<n>" / "share:<n>".
# ---------------------------------------------------------------------------

class TestStableIds:
    def test_life_event_gets_a_stable_id_immediately(self, tmp_path):
        svc = _svc(tmp_path)
        event = svc._life_events.record_event(event_type="achievement", title="Finished the sketch")
        assert event.share_id == "event:1"

    def test_life_event_ids_are_sequential(self, tmp_path):
        svc = _svc(tmp_path)
        first = svc._life_events.record_event(event_type="achievement", title="One")
        second = svc._life_events.record_event(event_type="achievement", title="Two")
        assert (first.share_id, second.share_id) == ("event:1", "event:2")

    def test_shareable_gets_a_stable_id_immediately(self, tmp_path):
        svc = _svc(tmp_path)
        svc._create_shareable_from_text("Something nice happened")
        [experience] = svc._get_unshared_experiences()
        assert experience.share_id == "share:1"

    def test_unshared_getters_expose_the_id_as_a_new_field(self, tmp_path):
        """Host compatibility: the id rides along as a new field on the same
        objects get_unshared_events()/get_shareable_experiences() already
        returned -- no shape change to title/description/content."""
        svc = _svc(tmp_path)
        svc._life_events.record_event(event_type="achievement", title="Finished the sketch")
        svc._create_shareable_from_text("Something nice happened")

        [event] = svc._life_events.get_unshared_events()
        [experience] = svc.get_shareable_experiences()
        assert event.share_id.startswith("event:")
        assert experience.share_id.startswith("share:")
        # Untouched fields, unchanged shape.
        assert event.title == "Finished the sketch"
        assert experience.content == "Something nice happened"


# ---------------------------------------------------------------------------
# LifeService.mark_shared
# ---------------------------------------------------------------------------

class TestMarkShared:
    def test_marks_a_life_event_shared_and_excludes_it(self, tmp_path):
        svc = _svc(tmp_path)
        event = svc._life_events.record_event(event_type="achievement", title="Finished the sketch")
        assert event in svc._life_events.get_unshared_events()

        assert svc.mark_shared(event.share_id) is True

        assert event not in svc._life_events.get_unshared_events()
        assert event.shared is True

    def test_marks_a_shareable_shared_and_excludes_it(self, tmp_path):
        svc = _svc(tmp_path)
        svc._create_shareable_from_text("Something nice happened")
        [experience] = svc._get_unshared_experiences()

        assert svc.mark_shared(experience.share_id) is True

        assert experience not in svc._get_unshared_experiences()
        assert experience.shared is True

    @pytest.mark.parametrize(
        "bad_id", ["event:999", "share:999", "not-a-real-id", "", "event:", "event:abc"]
    )
    def test_returns_false_for_an_unknown_or_malformed_id(self, tmp_path, bad_id):
        svc = _svc(tmp_path)
        svc._life_events.record_event(event_type="achievement", title="Finished the sketch")
        svc._create_shareable_from_text("Something nice happened")
        assert svc.mark_shared(bad_id) is False

    def test_survives_a_restart(self, tmp_path):
        kwargs = dict(db_path=str(tmp_path / "life.db"), persona_id="testpersona")
        svc1 = LifeService(**kwargs)
        svc1._load_state()
        event = svc1._life_events.record_event(event_type="achievement", title="Finished the sketch")
        svc1._create_shareable_from_text("Something nice happened")
        [experience] = svc1._get_unshared_experiences()

        assert svc1.mark_shared(event.share_id) is True
        assert svc1.mark_shared(experience.share_id) is True

        svc2 = LifeService(**kwargs)
        svc2._load_state()

        # Shareables reload only their still-unshared rows -- a persisted
        # "shared" row simply does not come back as unshared.
        assert experience.share_id not in {e.share_id for e in svc2._get_unshared_experiences()}
        # Life events reload regardless of shared status, so the flag itself
        # is directly checkable after the reload.
        assert event.share_id not in {e.share_id for e in svc2._life_events.get_unshared_events()}
        reloaded = [e for e in svc2._life_events._events if e.share_id == event.share_id]
        assert reloaded and reloaded[0].shared is True

    def test_event_and_share_id_namespaces_are_isolated(self, tmp_path):
        """Both a fresh event and a fresh shareable get number 1 in their own
        namespace. Marking "event:1" must never touch the shareable that
        also happens to be numbered 1, and vice versa."""
        svc = _svc(tmp_path)
        event = svc._life_events.record_event(event_type="achievement", title="Finished the sketch")
        svc._create_shareable_from_text("Something nice happened")
        [experience] = svc._get_unshared_experiences()
        assert event.share_id == "event:1"
        assert experience.share_id == "share:1"

        assert svc.mark_shared("event:1") is True
        assert event.shared is True
        assert experience.shared is False
        assert experience in svc._get_unshared_experiences()

        assert svc.mark_shared("share:1") is True
        assert experience.shared is True

    def test_marking_a_share_first_never_touches_the_event_with_its_number(self, tmp_path):
        """The reverse direction: with both numbered 1 and neither shared,
        marking "share:1" leaves the life event "event:1" unshared."""
        svc = _svc(tmp_path)
        event = svc._life_events.record_event(event_type="achievement", title="Finished the sketch")
        svc._create_shareable_from_text("Something nice happened")
        [experience] = svc._get_unshared_experiences()
        assert (event.share_id, experience.share_id) == ("event:1", "share:1")

        assert svc.mark_shared("share:1") is True
        assert experience.shared is True
        assert event.shared is False
        assert event in svc._life_events.get_unshared_events()

    def test_ids_do_not_collide_after_a_restart(self, tmp_path):
        """A new id issued after a reload must exceed every id the persona
        ever issued before -- not restart the counter (which a naive
        "len(self._events) + 1" or "len(shareable rows) + 1" would)."""
        kwargs = dict(db_path=str(tmp_path / "life.db"), persona_id="testpersona")
        svc1 = LifeService(**kwargs)
        svc1._load_state()
        for i in range(3):
            svc1._life_events.record_event(event_type="achievement", title=f"event {i}")
            svc1._create_shareable_from_text(f"share {i}")
        svc1._save_life_events()

        svc2 = LifeService(**kwargs)
        svc2._load_state()
        prior_event_max = max(
            int(e.share_id.split(":", 1)[1]) for e in svc2._life_events._events
        )
        prior_share_max = max(
            int(e.share_id.split(":", 1)[1]) for e in svc2._get_unshared_experiences()
        )

        new_event = svc2._life_events.record_event(event_type="achievement", title="new one")
        svc2._create_shareable_from_text("new share")
        [new_experience] = [
            e for e in svc2._get_unshared_experiences() if e.content == "new share"
        ]

        assert int(new_event.share_id.split(":", 1)[1]) > prior_event_max
        assert int(new_experience.share_id.split(":", 1)[1]) > prior_share_max


class TestBackfillOnReload:
    """A row saved before the share_id column existed (any row from before
    this task shipped) has share_id NULL in the DB. On reload it must get a
    usable id, not a permanently blank one -- and mark_shared must accept it."""

    def test_a_pre_task_5_life_event_row_backfills_a_usable_id(self, tmp_path):
        kwargs = dict(db_path=str(tmp_path / "life.db"), persona_id="testpersona")
        svc = LifeService(**kwargs)
        svc._load_state()  # creates the schema, including the share_id column
        with sqlite3.connect(str(tmp_path / "life.db")) as conn:
            conn.execute(
                """
                INSERT INTO life_events
                (event_type, title, description, emotional_impact, share_urgency,
                 created_at, shared, shared_at, source, share_id)
                VALUES ('achievement', 'Old event', 'Old event', '{}', 0.7, ?, 0, NULL, '', NULL)
                """,
                (datetime.now().isoformat(),),
            )
            conn.commit()

        svc2 = LifeService(**kwargs)
        svc2._load_state()
        [old_event] = [e for e in svc2._life_events._events if e.title == "Old event"]

        assert old_event.share_id  # not blank
        assert old_event.share_id.startswith("event:")
        assert svc2.mark_shared(old_event.share_id) is True


# ---------------------------------------------------------------------------
# Acceptance: < 10% of life events over a 3-simulated-day run are a template
# slotted with a bare engine label or mood word (task brief Acceptance;
# spec Sec 6 "Life events produced by a template with an engine label").
# ---------------------------------------------------------------------------

SIM_SEED = 3
SIM_DAYS = 3


@pytest.fixture(scope="module")
def sample_trace(tmp_path_factory):
    """Production cadence (ruling T4-R3): each tick at LifeScheduler's own
    interval, the way a live service runs -- not every tick every step.
    Module-scoped: both tests below classify/measure the same run."""
    trace = run_days(
        [SimPersona("sample")],
        days=SIM_DAYS,
        seed=SIM_SEED,
        cadence=PRODUCTION,
        data_dir=tmp_path_factory.mktemp("sample_trace"),
    )
    assert trace.errors == []
    return trace


def test_three_day_run_rarely_slots_a_bare_label_into_a_life_event(sample_trace):
    records = sample_trace.records["sample"]

    bare_labels = {label.lower() for label in MOOD_LABELS}
    bare_labels |= {r.activity.lower() for r in records if r.activity}

    lines = []
    for record in records:
        for title, description in record.new_life_events:
            lines.append(title)
            if description and description != title:
                lines.append(description)

    assert lines, "the 3-day run produced no life events to classify"
    leaks = [line for line in lines if _is_slot_leak(line, bare_labels)]
    rate = len(leaks) / len(lines)
    assert rate < 0.10, (
        f"{len(leaks)}/{len(lines)} ({rate:.0%}) life event lines slot a bare "
        f"engine label or mood word as a noun: {leaks}"
    )


def test_mood_change_events_are_spaced_at_least_the_throttle_apart(sample_trace):
    """Also catches a wall-clock read at the life_service call site: if
    _on_energy_tick passed something other than the world-clock instant, a
    regression would either throttle every mood change forever (real time
    barely advances during a fast test run, so there would be at most one
    mood-change event total) or space them by something other than
    MOOD_EVENT_MIN_HOURS on the *simulated* clock this test measures against."""
    records = sample_trace.records["sample"]
    mood_change_times = [
        record.t
        for record in records
        if any(title.startswith("Mood shifted to") for title, _ in record.new_life_events)
    ]
    assert len(mood_change_times) >= 2, (
        "need at least two mood-change events in the 3-day run to check spacing "
        f"(got {len(mood_change_times)})"
    )
    for earlier, later in zip(mood_change_times, mood_change_times[1:]):
        gap_hours = (later - earlier).total_seconds() / 3600.0
        assert gap_hours >= MOOD_EVENT_MIN_HOURS, (
            f"{earlier} -> {later} is only {gap_hours:.2f}h apart, "
            f"under MOOD_EVENT_MIN_HOURS ({MOOD_EVENT_MIN_HOURS})"
        )


# ----------------------------------------------------------------------
# Task 42: what a caller written for 0.5.0 still gets
# ----------------------------------------------------------------------

def test_a_life_event_built_by_position_fills_the_fields_it_filled_in_0_5_0():
    """``share_id`` came second on the branch, so a positional caller's event
    type landed in it, its title in the type and its description in the
    title. It is the last field: the order 0.5.0 had stands."""
    from aura_life.models import LifeEvent, ShareableExperience

    event = LifeEvent(None, "achievement", "Finished the mural", "Three weeks of evenings.", {"joy": 0.5})
    assert (event.event_type, event.title, event.description, event.emotional_impact, event.share_id) == (
        "achievement", "Finished the mural", "Three weeks of evenings.", {"joy": 0.5}, "")
    experience = ShareableExperience(None, 7, "a fox on the fire escape", "it looked right at me")
    assert (experience.activity_log_id, experience.content, experience.thought, experience.share_id) == (
        7, "a fox on the fire escape", "it looked right at me", "")
    assert LifeEvent.from_dict(LifeEvent(share_id="event:3", title="t").to_dict()).share_id == "event:3"


def test_mark_shared_by_the_row_id_still_marks_as_in_0_5_0():
    """0.5.0's ``LifeEventSystem.mark_shared(event_id: int)`` marked the event
    with that row id. On the branch the same call compared the number with
    the stable string ids, marked nothing and said nothing."""
    from aura_life.life_events.life_event_system import LifeEventSystem
    from aura_life.models import LifeEvent

    system = LifeEventSystem()
    at = datetime(2026, 9, 21, 15, 0)
    system._events.extend([LifeEvent(id=7, share_id="event:1", title="first"),
                           LifeEvent(id=8, share_id="event:2", title="second")])
    assert system.mark_shared(8, now=at) is True
    assert [(e.shared, e.shared_at) for e in system._events] == [(False, None), (True, at)]
    assert system.mark_shared(99) is False
    assert system.mark_shared(True) is False            # a bool is no row id
    assert system.mark_shared("event:1", now=at) is True and system._events[0].shared
