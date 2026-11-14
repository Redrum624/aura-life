"""The humanness program's regression test: every spec section 6 row that
applies to aura-life, measured on one run (humanness Task 19b, rulings R26,
T19b-R3 to T19b-R5).

The run: a no-profile control and two contrasting authored personas
(``tests/fixtures/humanness_a_profile.txt``, Inge, a solitary ruminative
night owl who illustrates from home; ``humanness_b_profile.txt``, Jojo, a
sociable impulsive early riser on cafe shifts; invented, their interests
share no word), parsed by ``ProfileParser`` the way a host reads a profile,
three simulated days from a Monday 15:00 at the PRODUCTION cadence (each tick
at ``LifeScheduler``'s own interval), one run per seed in ``SEEDS``. One
module-scoped run per seed serves every row (ruling T19b-R5).

The thresholds are the spec's (section 6, "Acceptance thresholds (R12)"):
proposals encoded as tests; recalibrating one needs a ledger ruling, never an
edit here. The measures are the ones the program's tests already use:

* the sleep row counts each night's effective window (her schedule's bedtime
  and wake time, with the weekend shifts: ``sim_helpers.effective_nights``,
  ruling T3-R1);
* the mood-label row counts her waking ticks only (ruling T4-R2);
* forced rest and the plan row count her waking activity ticks (the steps
  whose activity tick ran while she was awake);
* the templated-event row classifies every life event line the run recorded
  with ``tests/test_sharing.py``'s template pattern, per persona (ruling
  T5-R2: the multi-persona protocol is asserted here);
* the outcome row pools the run's rolled outcomes (her sleep and her intimate
  activities have no roll), as ``tests/test_appraisal.py`` does.

Rows asserted elsewhere (named, not re-run here; ruling T19b-R3): the moment's
two -- static lines across 12 captures
(``tests/test_moment.py::test_fewer_than_a_fifth_of_the_rendered_lines_are_static``)
and ``render()`` length (``tests/test_moment.py::test_twelve_captures_per_persona_render_clean``)
-- on their own three-day capture; the setting-pack row is aura-personality's
(``test_three_days_in_the_dustlands_are_lived_in_the_pack``). The runtime row
(this file at most 90 s) is measured alone, not asserted: a wall-clock bound
inside the suite would fail under another agent's load, not under a slower
engine.
"""

from __future__ import annotations

import math
import pathlib
from collections import Counter
from dataclasses import fields as dc_fields

import pytest

from aura_life.affect.affect_system import MOOD_LABELS
from aura_life.emotion.appraisal import SUCCESS
from aura_life.personas.parameters import PersonaParameters
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.personas.profile_parser import ProfileParser

from sim_helpers import PRODUCTION, SimPersona, effective_nights, in_windows, run_days
from test_sharing import _is_slot_leak

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
PROFILE_A = FIXTURES / "humanness_a_profile.txt"
PROFILE_B = FIXTURES / "humanness_b_profile.txt"

DAYS = 3
#: Fixed before any run was measured (section 3's interim runs used the same
#: three); never picked to pass (spec R12, the brief's acceptance 2).
SEEDS = (1, 2, 3)
CONTROL, A, B = "control", "inge", "jojo"
IDS = (CONTROL, A, B)

#: The spec's section 6 thresholds.
MAX_ERRORS = 0
MAX_WAKING_LABEL_SHARE = 0.70
MIN_ASLEEP_IN_WINDOW = 0.90
MAX_FORCED_REST = 0.25
MAX_TEMPLATED_EVENTS = 0.10          # strictly below
MIN_PLAN_FOLLOWED = 0.50
MAX_HUNGRY_TICKS = 0.25
HUNGRY = 0.7
MIN_NOT_PLAIN_SUCCESS = 0.10
MAX_ACTIVITY_MIX_COSINE = 0.90       # strictly below

#: The row that fails on this tree, held as a BLOCKED-ITEM (the brief's
#: acceptance 2: no threshold changed, no seed picked, no persona re-authored
#: to pass; ledger ruling T19b-R11). A held case is ONE measured failure -- a
#: persona on a seed of the label row -- with its number as the BLOCKED-ITEM
#: records it (three decimals): a case that passes is never inside a mark.
#: Two guards on a held case:
#:
#: * the mark is strict: the day the case passes, the mark fails and has to go
#:   (with its entry here);
#: * an expected failure passes on any failed assert, so a mark alone would
#:   hide the row getting worse (a mood that always says "content"): the
#:   case may not read worse than its
#:   recorded number (``test_a_held_case_is_no_worse_than_its_blocked_item``,
#:   never marked). The runs are seeded and repeat to the digit.
BLOCKED_LABEL = {(CONTROL, 1): 0.760}
#: The label row's BLOCKED-ITEM is the row's, not one persona's: which case
#: is over the bound moves with any change that reaches her mood. Before the
#: same event was looked forward to once (Task 40) it was jojo on seed 3
#: (0.709), with the control's seed 1 at 0.689; on seeds 4 and 5 of that tree
#: (measured once, not the test's) it was inge (0.721, 0.745).
LABEL_CAUSE = (
    "the control's seed 1 is 'low' on 0.760 of her waking ticks, the one case over 0.70 on seeds 1-3 (the others "
    "0.420 to 0.621); with a goal looked forward to five times over, as before Task 40, the same case read 0.689 and "
    "jojo's seed 3 0.709; the spread of a day's quality is the owner's knob (ledger R18)")


def _blocked(row: str, recorded: float, cause: str):
    return pytest.mark.xfail(strict=True, reason=(
        f"BLOCKED-ITEM (Task 19b), {row}: {recorded:.3f} on this case; {cause}"))

_DEF_FIELDS = {f.name for f in dc_fields(PersonalityDefinition)}
#: The control has no profile: every trait neutral.
CONTROL_PARAMS = PersonaParameters().traits()


def profile_persona(path: pathlib.Path) -> SimPersona:
    """A ``SimPersona`` built from a profile file as a host builds one: the
    parsed definition, and the sleep schedule the profile gives."""
    parsed = ProfileParser.parse_file(path).to_personality_definition()
    definition = PersonalityDefinition(**{k: v for k, v in parsed.items() if k in _DEF_FIELDS})
    return SimPersona(definition.id, sleep_schedule=dict(parsed["sleep_schedule"]),
                      service_kwargs={"definition": definition})


@pytest.fixture(scope="module")
def traces(tmp_path_factory):
    """One three-day PRODUCTION run per seed: the control and the two fixture
    personas, built afresh for each run."""
    return {
        seed: run_days([SimPersona(CONTROL), profile_persona(PROFILE_A), profile_persona(PROFILE_B)],
                       days=DAYS, seed=seed, cadence=PRODUCTION,
                       data_dir=tmp_path_factory.mktemp(f"humanness_{seed}"))
        for seed in SEEDS
    }


# ----------------------------------------------------------------------
# Measures (each the row's definition; see the module docstring)
# ----------------------------------------------------------------------

def waking_activity_ticks(records) -> list:
    """The steps whose activity tick ran while she was awake."""
    return [r for r in records if "activity" in r.ticks and not r.asleep]


def largest_waking_label(records) -> tuple:
    """(label, its share of her waking ticks) of her most frequent mood label."""
    waking = [r.mood for r in records if not r.asleep]
    label, count = Counter(waking).most_common(1)[0]
    return label, count / len(waking)


def asleep_in_her_windows(trace, pid) -> tuple:
    """(asleep ticks, ticks) inside her effective nights."""
    nights = effective_nights(trace, pid)
    in_window = [r for r in trace.records[pid] if in_windows(r.t, nights)]
    return sum(r.asleep for r in in_window), len(in_window)


def forced_rest(records) -> tuple:
    """(forced, decided) over her waking activity ticks."""
    waking = waking_activity_ticks(records)
    return sum(bool(r.forced_rest) for r in waking), len(waking)


def templated_lines(records) -> tuple:
    """(lines slotting a bare engine label or mood word, lines) over every
    life event the run recorded for her (titles, and descriptions that differ)."""
    bare = {label.lower() for label in MOOD_LABELS} | {r.activity.lower() for r in records if r.activity}
    lines = []
    for record in records:
        for title, description in record.new_life_events:
            lines.append(title)
            if description and description != title:
                lines.append(description)
    return sum(_is_slot_leak(line, bare) for line in lines), len(lines)


def plan_followed(records) -> tuple:
    """(waking activity ticks that did her plan's slot, waking activity ticks)."""
    waking = waking_activity_ticks(records)
    return sum(1 for r in waking if r.planned_activity is not None and r.activity == r.planned_activity), len(waking)


def hungry_ticks(records) -> tuple:
    """(ticks with hunger at or above HUNGRY, ticks)."""
    return sum(1 for r in records if r.hunger >= HUNGRY), len(records)


def rolled_outcomes(trace, pid) -> list:
    """The outcomes of the activities she did that had one to roll: all but
    her sleep and her intimate activities (logged as a success, no roll)."""
    svc = trace.services[pid]
    unrolled = set(svc._setting.names_tagged("sleep")) | {a.name for a in svc._setting.intimate_catalogue()}
    return [r.outcome for r in trace.records[pid] if r.activity and r.activity not in unrolled]


#: Every occupation's work carries this one activity name.
WORK = "working"


def raw_activity_mix(records) -> Counter:
    """What she did on her waking activity ticks, by the raw activity name."""
    return Counter(r.activity for r in waking_activity_ticks(records) if r.activity)


def activity_mix(records) -> Counter:
    """What she did on her waking activity ticks outside her work (ledger
    rulings T19b-R10 and T19b-R13, a measurement definition). Every job's
    work is the one activity name "working": a third of a working persona's
    waking activity ticks and 0.90 of the raw dot product (0.925 to 0.947),
    whatever her preferences. Counted as each persona's own occupation's work
    it is as blind the other way (0.086 to 0.099: two jobs always differ).
    The row asks whether two personas DO different things with the time that
    is theirs, so the work ticks are left out of both."""
    return Counter(r.activity for r in waking_activity_ticks(records) if r.activity and r.activity != WORK)


def occupation_activity_mix(records, occupation: str) -> Counter:
    """A work tick counted as her own occupation's work (printed, never asserted)."""
    return Counter((r.activity, occupation) if r.activity == WORK else r.activity
                   for r in waking_activity_ticks(records) if r.activity)


def cosine(a: Counter, b: Counter) -> float:
    dot = sum(a[name] * b[name] for name in set(a) | set(b))
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


def _share(part: int, whole: int) -> float:
    assert whole > 0, "the measure has nothing to count"
    return part / whole


# ----------------------------------------------------------------------
# The run is what the profiles say
# ----------------------------------------------------------------------

def test_the_fixture_personas_are_what_their_profiles_say(traces):
    """The contrast the rows rely on reaches the services: her own sleep
    schedule, her occupation, her authored traits."""
    for seed, trace in traces.items():
        assert set(trace.records) == set(IDS), seed
        assert (trace.schedules[A]["bedtime_hour"], trace.schedules[A]["wake_hour"]) == (1, 9)
        assert (trace.schedules[A]["bedtime_minute"], trace.schedules[A]["wake_minute"]) == (0, 0)
        assert (trace.schedules[B]["bedtime_hour"], trace.schedules[B]["wake_hour"]) == (22, 5)
        assert (trace.schedules[B]["bedtime_minute"], trace.schedules[B]["wake_minute"]) == (0, 30)
        assert trace.schedules[CONTROL]["bedtime_hour"] == 23
        inge, jojo = trace.services[A], trace.services[B]
        assert (inge._occupation, jojo._occupation) == ("Freelance illustrator", "Barista")
        assert inge._params.traits() == {
            "sociability": 0.15, "volatility": 0.3, "rumination": 0.8, "impulsivity": 0.2,
            "conscientiousness": 0.6, "openness": 0.8, "warmth": 0.45, "weather_sensitivity": 0.6}
        assert jojo._params.traits() == {
            "sociability": 0.9, "volatility": 0.6, "rumination": 0.2, "impulsivity": 0.7,
            "conscientiousness": 0.4, "openness": 0.5, "warmth": 0.85, "weather_sensitivity": 0.3}
        assert CONTROL_PARAMS == trace.services[CONTROL]._params.traits()
        for pid in IDS:
            assert len(trace.records[pid]) == DAYS * 24 * 60 // trace.step_minutes, (seed, pid)
            assert len(effective_nights(trace, pid)) == DAYS, (seed, pid)


# ----------------------------------------------------------------------
# The section 6 rows
# ----------------------------------------------------------------------

def test_no_error_is_logged(traces):
    """ERROR log records: 0."""
    for seed, trace in traces.items():
        assert len(trace.errors) <= MAX_ERRORS, (seed, trace.errors)


def _label_cases():
    for pid in IDS:
        for seed in SEEDS:
            held = BLOCKED_LABEL.get((pid, seed))
            marks = [] if held is None else [_blocked("mood label <= 0.70", held, LABEL_CAUSE)]
            yield pytest.param(pid, seed, marks=marks, id=f"{pid}-seed{seed}")


def mix_cosine(trace) -> float:
    """The row's measure: what each does outside her work."""
    return cosine(activity_mix(trace.records[A]), activity_mix(trace.records[B]))


def raw_mix_cosine(trace) -> float:
    """By raw activity names (printed beside the row, never asserted)."""
    return cosine(raw_activity_mix(trace.records[A]), raw_activity_mix(trace.records[B]))


def occupation_mix_cosine(trace) -> float:
    """With each work tick as her own occupation's (printed, never asserted)."""
    return cosine(occupation_activity_mix(trace.records[A], trace.services[A]._occupation),
                  occupation_activity_mix(trace.records[B], trace.services[B]._occupation))


@pytest.mark.parametrize("pid, seed", list(_label_cases()))
def test_no_mood_label_on_more_than_70_percent_of_her_waking_ticks(traces, pid, seed):
    """Any single mood label: at most 70% of her waking ticks (P1, T4-R2)."""
    label, share = largest_waking_label(traces[seed].records[pid])
    print(f"{pid} seed {seed}: largest waking label {label} {share:.3f}")
    assert share <= MAX_WAKING_LABEL_SHARE, (seed, label, round(share, 3))


@pytest.mark.parametrize("pid", IDS)
def test_asleep_on_at_least_90_percent_of_her_own_window(traces, pid):
    """Ticks inside her own (effective) sleep window spent asleep: >= 90% (T3-R1)."""
    for seed, trace in traces.items():
        asleep, in_window = asleep_in_her_windows(trace, pid)
        print(f"{pid} seed {seed}: asleep {asleep}/{in_window} in-window ticks")
        assert _share(asleep, in_window) >= MIN_ASLEEP_IN_WINDOW, (seed, asleep, in_window)


@pytest.mark.parametrize("pid", IDS)
def test_rest_is_forced_on_at_most_a_quarter_of_her_waking_ticks(traces, pid):
    """Waking ticks with forced rest: <= 25%. Every waking activity tick took
    the decision -- one with none would count as not forced and flatter it."""
    for seed, trace in traces.items():
        assert all(r.forced_rest is not None for r in waking_activity_ticks(trace.records[pid])), seed
        forced, waking = forced_rest(trace.records[pid])
        print(f"{pid} seed {seed}: rest forced on {forced}/{waking} waking ticks")
        assert _share(forced, waking) <= MAX_FORCED_REST, (seed, forced, waking)


@pytest.mark.parametrize("pid", IDS)
def test_fewer_than_a_tenth_of_her_life_events_slot_an_engine_label(traces, pid):
    """Life events produced by a template with an engine label: < 10% (T5-R2)."""
    for seed, trace in traces.items():
        leaks, lines = templated_lines(trace.records[pid])
        print(f"{pid} seed {seed}: {leaks}/{lines} life event lines slot a bare label")
        assert _share(leaks, lines) < MAX_TEMPLATED_EVENTS, (seed, leaks, lines)


@pytest.mark.parametrize("pid", IDS)
def test_her_planned_slot_runs_on_at_least_half_her_waking_ticks(traces, pid):
    """Planned slot actually executed (waking ticks): >= 50%."""
    for seed, trace in traces.items():
        followed, waking = plan_followed(trace.records[pid])
        print(f"{pid} seed {seed}: plan followed on {followed}/{waking} waking ticks")
        assert _share(followed, waking) >= MIN_PLAN_FOLLOWED, (seed, followed, waking)


@pytest.mark.parametrize("pid", IDS)
def test_she_is_hungry_on_at_most_a_quarter_of_ticks(traces, pid):
    """Ticks with hunger >= 0.7: <= 25%."""
    for seed, trace in traces.items():
        hungry, ticks = hungry_ticks(trace.records[pid])
        print(f"{pid} seed {seed}: hunger >= {HUNGRY} on {hungry}/{ticks} ticks")
        assert _share(hungry, ticks) <= MAX_HUNGRY_TICKS, (seed, hungry, ticks)


def test_at_least_one_activity_in_ten_does_not_simply_go_well(traces):
    """Activity outcomes that are not plain success: >= 10% of the run's."""
    for seed, trace in traces.items():
        pooled = [o for pid in IDS for o in rolled_outcomes(trace, pid)]
        per_persona = {pid: round(_share(sum(o != SUCCESS for o in rolled_outcomes(trace, pid)),
                                         len(rolled_outcomes(trace, pid))), 3) for pid in IDS}
        share = _share(sum(o != SUCCESS for o in pooled), len(pooled))
        print(f"seed {seed}: {share:.3f} of {len(pooled)} not plain success; per persona {per_persona}")
        assert share >= MIN_NOT_PLAIN_SUCCESS, (seed, share, per_persona)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_two_contrasting_personas_do_different_things(traces, seed):
    """Activity-mix cosine, the two contrasting personas: < 0.90, over what
    each does outside her work (T19b-R10, T19b-R13)."""
    trace = traces[seed]
    assert any(r.activity == WORK for r in waking_activity_ticks(trace.records[A])), seed
    assert any(r.activity == WORK for r in waking_activity_ticks(trace.records[B])), seed
    similarity = mix_cosine(trace)
    print(f"seed {seed}: {A} vs {B} activity-mix cosine {similarity:.3f} outside work "
          f"(by raw activity names {raw_mix_cosine(trace):.3f}, "
          f"work as her own occupation's {occupation_mix_cosine(trace):.3f})")
    assert similarity < MAX_ACTIVITY_MIX_COSINE, (seed, similarity)


def test_the_activity_mix_leaves_work_out_and_nothing_else():
    """The three readings on a day made by hand: work decides the raw one and
    the occupation one, and has no say in the row's."""
    class Tick:
        ticks, asleep = ("activity",), False

        def __init__(self, activity):
            self.activity = activity
    reader = [Tick(WORK)] * 3 + [Tick("reading")]
    walker = [Tick(WORK)] * 3 + [Tick("walking")]
    assert cosine(activity_mix(reader), activity_mix(walker)) == 0.0
    assert cosine(activity_mix(reader), activity_mix(reader)) == pytest.approx(1.0)
    assert cosine(raw_activity_mix(reader), raw_activity_mix(walker)) == pytest.approx(0.9)
    assert cosine(occupation_activity_mix(reader, "Barista"),
                  occupation_activity_mix(reader, "Nurse")) == pytest.approx(0.1)


# ----------------------------------------------------------------------
# The held cases do not get worse (never marked; see BLOCKED_LABEL)
# ----------------------------------------------------------------------

def _held_cases():
    for (pid, seed), recorded in BLOCKED_LABEL.items():
        yield pytest.param("label", pid, seed, recorded, id=f"label-{pid}-seed{seed}")


@pytest.mark.parametrize("row, pid, seed, recorded", list(_held_cases()))
def test_a_held_case_is_no_worse_than_its_blocked_item(traces, row, pid, seed, recorded):
    """A held case reads no worse than its BLOCKED-ITEM's number, at the three
    decimals it is recorded in: a regression goes red here, a fix shows as
    the strict mark failing."""
    trace = traces[seed]
    assert row == "label", row
    value = largest_waking_label(trace.records[pid])[1]
    print(f"{row} {pid} seed {seed}: {value:.3f} (BLOCKED-ITEM {recorded:.3f})")
    assert round(value, 3) <= recorded, (row, pid, seed, round(value, 3), recorded)
