"""SanitySystem -- the one interior number that integrates and can break.

Eight engines carry mood, stress, loneliness, unease, felt safety, doubt,
concealment and intrusive thought, and none of them reaches a terminal state.
`SanitySystem` is the seam that does: one scalar in [0, 1], read through a
closed graded vocabulary, driven down by blows the host reports and up by
recoveries the host reports, drifting slowly with the world clock in between.

The properties asserted here are the ones a consumer would build on:
  * severity is the blow's, intensity is the person's, and both are monotone;
  * the baseline is read from character, ordered by burden, never authored;
  * the only random draw is at construction, and only if an rng is given;
  * drift is clock-driven through an `hours` argument, reversible, and never
    reads a clock of its own;
  * `breaking` is an event, emitted once per downward entry; `broken` is a
    flag the host may lift through an explicit recovery;
  * a restarted host resumes the same number, state and pending events.
"""

import random

import pytest

from aura_life.sanity import SanitySystem
from aura_life.sanity.sanity_system import (
    BASELINE_MAX,
    BASELINE_MIN,
    BLOW_KINDS,
    BLOW_WEIGHT,
    BREAKING_ABOVE,
    FRAYING_ABOVE,
    INTENSITY_MAX,
    INTENSITY_MIN,
    RECOVERY_KINDS,
    SOUND_ABOVE,
    STATES,
    STRAINED_ABOVE,
    state_for,
)


class CountingRng:
    """Duck-typed rng that counts every draw the engine takes from it."""

    def __init__(self, seed: int = 7):
        self._r = random.Random(seed)
        self.calls = 0

    def random(self) -> float:
        self.calls += 1
        return self._r.random()

    def uniform(self, a: float, b: float) -> float:
        self.calls += 1
        return self._r.uniform(a, b)


def _at(value: float, **kwargs) -> SanitySystem:
    """A system parked at an exact value, so a threshold can be crossed from a
    known side. Goes through the public setter used by persistence."""
    s = SanitySystem(**kwargs)
    s.set_value(value)
    return s


HEAVY = dict(
    struggles=["hunger he has learned to hide", "debt", "a brother in prison"],
    character_defects=["envy", "cowardice"],
    intrusive_thought_themes=["being found out", "the river"],
)


# ============= Vocabulary and thresholds =============

class TestVocabulary:
    def test_states_closed_and_ordered(self):
        assert STATES == ("sound", "strained", "fraying", "breaking", "broken")

    def test_blow_and_recovery_kinds_closed(self):
        assert BLOW_KINDS == (
            "grief", "witnessed", "did_harm", "broke_value", "rejected", "neglect", "concealment",
        )
        assert set(BLOW_WEIGHT) == set(BLOW_KINDS)
        assert RECOVERY_KINDS == ("rest", "warmth", "relief", "answered", "achieved")

    @pytest.mark.parametrize("value,expected", [
        (1.0, "sound"), (0.76, "sound"), (0.75, "strained"), (0.50, "strained"),
        (0.49, "fraying"), (0.25, "fraying"), (0.24, "breaking"), (0.10, "breaking"),
        (0.099, "broken"), (0.0, "broken"),
    ])
    def test_state_for_bands(self, value, expected):
        assert state_for(value) == expected

    def test_thresholds_are_named_constants(self):
        assert (SOUND_ABOVE, STRAINED_ABOVE, FRAYING_ABOVE, BREAKING_ABOVE) == (0.75, 0.50, 0.25, 0.10)


class TestThresholdCrossings:
    """Every boundary, from both sides, through the engine rather than the
    helper: the state property must track the number after any move."""

    @pytest.mark.parametrize("above,below,upper,lower", [
        (0.80, 0.70, "sound", "strained"),
        (0.60, 0.40, "strained", "fraying"),
        (0.30, 0.20, "fraying", "breaking"),
        (0.15, 0.05, "breaking", "broken"),
    ])
    def test_down_then_up(self, above, below, upper, lower):
        s = _at(above)
        assert s.state == upper
        s.set_value(below)
        assert s.state == lower
        s.set_value(above)
        assert s.state == upper

    def test_blow_crosses_down_and_recovery_crosses_up(self):
        s = _at(0.78)
        assert s.state == "sound"
        s.on_blow("rejected", 1.0)          # -0.15 -> 0.63
        assert s.state == "strained"
        s.on_recovery("answered", 1.0)      # +0.15 -> 0.78
        assert s.state == "sound"


# ============= Severity and intensity =============

class TestBlowArithmetic:
    def test_loss_is_severity_times_weight_times_intensity(self):
        s = SanitySystem()
        before = s.value
        s.on_blow("grief", 0.5)
        assert s.value == pytest.approx(before - 0.5 * BLOW_WEIGHT["grief"] * s.intensity)

    def test_loss_monotone_in_severity(self):
        losses = []
        for sev in (0.1, 0.4, 0.7, 1.0):
            s = SanitySystem()
            before = s.value
            s.on_blow("witnessed", sev)
            losses.append(before - s.value)
        assert losses == sorted(losses) and len(set(losses)) == 4

    def test_loss_monotone_in_intensity_two_personas_same_blow(self):
        light = SanitySystem()
        heavy = SanitySystem(**HEAVY)
        assert heavy.intensity > light.intensity
        l0, h0 = light.value, heavy.value
        light.on_blow("did_harm", 0.6)
        heavy.on_blow("did_harm", 0.6)
        assert (h0 - heavy.value) > (l0 - light.value)

    def test_severity_clamped(self):
        s = SanitySystem()
        before = s.value
        s.on_blow("neglect", 5.0)
        assert s.value == pytest.approx(before - 1.0 * BLOW_WEIGHT["neglect"] * s.intensity)
        t = SanitySystem()
        before = t.value
        t.on_blow("neglect", -3.0)
        assert t.value == before

    def test_unknown_kind_raises_naming_kinds(self):
        s = SanitySystem()
        with pytest.raises(ValueError) as exc:
            s.on_blow("bad_hair_day", 0.5)
        for kind in BLOW_KINDS:
            assert kind in str(exc.value)
        with pytest.raises(ValueError) as exc:
            s.on_recovery("sandwich", 0.5)
        for kind in RECOVERY_KINDS:
            assert kind in str(exc.value)

    def test_value_floors_at_zero(self):
        s = SanitySystem(**HEAVY)
        for _ in range(20):
            s.on_blow("did_harm", 1.0)
        assert s.value == 0.0
        assert s.state == "broken"


class TestRecoveryArithmetic:
    def test_recovery_scaled_by_resilience(self):
        light = _at(0.30)
        heavy = _at(0.30, **HEAVY)
        assert heavy.resilience < light.resilience
        assert light.resilience == pytest.approx(1.0 / light.intensity)
        light.on_recovery("warmth", 0.8)
        heavy.on_recovery("warmth", 0.8)
        assert light.value > heavy.value

    def test_recovery_amount_clamped_and_capped_at_one(self):
        s = _at(0.98)
        s.on_recovery("achieved", 40.0)
        assert s.value == 1.0
        t = _at(0.5)
        t.on_recovery("rest", -1.0)
        assert t.value == 0.5


# ============= Baseline, intensity, jitter =============

class TestBaselineFromCharacter:
    def test_nothing_starts_sound_with_neutral_intensity(self):
        s = SanitySystem()
        assert s.state == "sound"
        assert s.intensity == 1.0
        assert s.value == s.baseline

    def test_baseline_ordered_by_burden(self):
        none = SanitySystem()
        some = SanitySystem(struggles=["debt"])
        more = SanitySystem(struggles=["debt"], character_defects=["envy"])
        most = SanitySystem(**HEAVY)
        assert none.baseline > some.baseline > more.baseline > most.baseline
        assert none.intensity < some.intensity < more.intensity < most.intensity

    def test_documented_formula(self):
        s = SanitySystem(struggles=["a", "b"], character_defects=["c"], intrusive_thought_themes=["d", "e", "f"])
        assert s.baseline == pytest.approx(0.92 - 2 * 0.04 - 1 * 0.03 - 3 * 0.02)
        assert s.intensity == pytest.approx(1.0 + 2 * 0.10 + 1 * 0.08 + 3 * 0.06)

    def test_most_burdened_not_fraying_and_bands_hold(self):
        s = SanitySystem(
            struggles=["s"] * 12, character_defects=["d"] * 12, intrusive_thought_themes=["t"] * 12,
        )
        assert s.baseline == BASELINE_MIN
        assert s.intensity == INTENSITY_MAX
        assert s.state == "strained"          # burdened, but never starts fraying
        assert BASELINE_MIN <= SanitySystem().baseline <= BASELINE_MAX
        assert INTENSITY_MIN <= SanitySystem().intensity <= INTENSITY_MAX


class TestJitter:
    def test_no_rng_no_jitter_and_deterministic(self):
        a, b = SanitySystem(**HEAVY), SanitySystem(**HEAVY)
        assert a.baseline == b.baseline
        assert a.intensity == b.intensity
        assert a.baseline == pytest.approx(0.92 - 3 * 0.04 - 2 * 0.03 - 2 * 0.02)

    def test_rng_jitters_within_band_and_is_replayable(self):
        plain = SanitySystem()
        j1 = SanitySystem(rng=random.Random(11))
        j2 = SanitySystem(rng=random.Random(11))
        assert j1.baseline != plain.baseline
        assert j1.baseline == j2.baseline and j1.intensity == j2.intensity
        assert BASELINE_MIN <= j1.baseline <= BASELINE_MAX
        assert INTENSITY_MIN <= j1.intensity <= INTENSITY_MAX

    def test_exactly_one_draw_at_construction_and_zero_after(self):
        rng = CountingRng(3)
        s = SanitySystem(rng=rng, **HEAVY)
        assert rng.calls == 1
        for kind in BLOW_KINDS:
            s.on_blow(kind, 0.3)
        for kind in RECOVERY_KINDS:
            s.on_recovery(kind, 0.3)
        s.tick(5.0, stressed=True, concealment_load=0.5)
        s.tick(5.0, stressed=False, concealment_load=0.0)
        s.drain_events()
        SanitySystem.from_dict(s.to_dict())
        s.get_status(); s.export_state()
        assert rng.calls == 1

    def test_from_dict_never_draws(self):
        rng = CountingRng(5)
        s = SanitySystem(rng=rng)
        data = s.to_dict()
        rng2 = CountingRng(5)
        restored = SanitySystem.from_dict(data, rng=rng2)
        assert rng2.calls == 0
        assert restored.baseline == s.baseline


# ============= Drift =============

class TestDrift:
    def test_no_clock_read(self):
        import inspect
        from aura_life.sanity import sanity_system
        src = inspect.getsource(sanity_system)
        assert "datetime" not in src and "time.time" not in src

    def test_drift_down_under_stress(self):
        s = SanitySystem()
        before = s.value
        s.tick(6.0, stressed=True, concealment_load=0.0)
        assert s.value < before

    def test_drift_down_under_concealment_scaled_by_load(self):
        a, b = SanitySystem(), SanitySystem()
        a.tick(6.0, stressed=False, concealment_load=0.3)
        b.tick(6.0, stressed=False, concealment_load=0.9)
        assert a.value < a.baseline
        assert b.value < a.value

    def test_drift_is_linear_in_hours(self):
        a, b = SanitySystem(), SanitySystem()
        a.tick(2.0, stressed=True, concealment_load=0.0)
        b.tick(1.0, stressed=True, concealment_load=0.0)
        b.tick(1.0, stressed=True, concealment_load=0.0)
        assert a.value == pytest.approx(b.value)

    def test_drift_up_when_calm_reversible_and_stops_at_baseline(self):
        s = SanitySystem()
        s.tick(10.0, stressed=True, concealment_load=0.0)
        low = s.value
        assert low < s.baseline
        s.tick(5.0, stressed=False, concealment_load=0.0)
        assert low < s.value <= s.baseline
        s.tick(1000.0, stressed=False, concealment_load=0.0)
        assert s.value == pytest.approx(s.baseline)

    def test_calm_drift_never_pulls_down_from_above_baseline(self):
        s = SanitySystem()
        s.on_recovery("answered", 1.0)
        assert s.value > s.baseline
        high = s.value
        s.tick(48.0, stressed=False, concealment_load=0.0)
        assert s.value == high

    def test_nonpositive_hours_is_a_noop(self):
        s = SanitySystem()
        before = s.value
        s.tick(0.0, stressed=True, concealment_load=1.0)
        s.tick(-3.0, stressed=True, concealment_load=1.0)
        assert s.value == before

    def test_concealment_load_clamped(self):
        a, b = SanitySystem(), SanitySystem()
        a.tick(4.0, stressed=False, concealment_load=1.0)
        b.tick(4.0, stressed=False, concealment_load=7.0)
        assert a.value == pytest.approx(b.value)


# ============= Events and the terminal flag =============

class TestBreakingEvent:
    def test_emitted_once_on_entry_and_drained(self):
        s = _at(0.30)
        assert s.drain_events() == []
        s.set_value(0.20)
        assert s.state == "breaking"
        assert s.drain_events() == ["breaking"]
        assert s.drain_events() == []
        s.set_value(0.15)                       # still breaking: idempotent
        assert s.drain_events() == []

    def test_again_after_recovery_and_reentry(self):
        s = _at(0.30)
        s.set_value(0.20)
        assert s.drain_events() == ["breaking"]
        s.on_recovery("answered", 1.0)          # back up to fraying
        assert s.state == "fraying"
        s.on_blow("grief", 1.0)                 # down again
        assert s.state in ("breaking", "broken")
        assert s.drain_events() == ["breaking"]

    def test_skipping_straight_to_broken_still_emits(self):
        s = _at(0.60)
        s.set_value(0.05)
        assert s.state == "broken"
        assert s.drain_events() == ["breaking"]

    def test_climbing_out_of_broken_into_breaking_is_not_an_entry(self):
        s = _at(0.05)
        s.drain_events()
        s.set_value(0.15)
        assert s.state == "breaking"
        assert s.drain_events() == []

    def test_events_accumulate_until_drained(self):
        s = _at(0.30)
        s.set_value(0.20)
        s.set_value(0.30)
        s.set_value(0.20)
        assert s.drain_events() == ["breaking", "breaking"]


class TestBroken:
    def test_flag_set_on_entry_and_terminal_under_time(self):
        s = _at(0.12)
        assert not s.broken
        s.on_blow("grief", 0.2)
        assert s.state == "broken" and s.broken
        s.tick(500.0, stressed=False, concealment_load=0.0)
        assert s.broken and s.value < BREAKING_ABOVE   # time alone does not heal it

    def test_host_recovery_lifts_it(self):
        s = _at(0.05)
        assert s.broken
        s.on_recovery("answered", 1.0)
        assert s.value >= BREAKING_ABOVE
        assert not s.broken
        assert s.state != "broken"
        # once lifted, calm time works again
        v = s.value
        s.tick(10.0, stressed=False, concealment_load=0.0)
        assert s.value > v

    def test_blows_still_land_while_broken(self):
        s = _at(0.05)
        s.on_blow("neglect", 1.0)
        assert s.value < 0.05


# ============= Persistence =============

class TestPersistence:
    def test_round_trip_preserves_number_state_flag_and_pending_events(self):
        s = SanitySystem(rng=random.Random(2), **HEAVY)
        s.on_blow("grief", 1.0)
        s.on_blow("did_harm", 1.0)
        s.on_blow("broke_value", 1.0)
        assert s.state in ("breaking", "broken")
        data = s.to_dict()
        r = SanitySystem.from_dict(data)
        assert r.value == s.value
        assert r.state == s.state
        assert r.baseline == s.baseline
        assert r.intensity == s.intensity
        assert r.broken == s.broken
        assert r.drain_events() == ["breaking"]
        assert s.drain_events() == ["breaking"]

    def test_from_dict_empty_falls_back_to_fresh(self):
        r = SanitySystem.from_dict({}, **HEAVY)
        f = SanitySystem(**HEAVY)
        assert r.value == f.value and r.intensity == f.intensity

    def test_json_row_shape(self):
        import json
        s = SanitySystem()
        row = s.to_dict()
        json.dumps(row)     # every value is a JSON scalar or string
        assert {"sanity", "baseline", "intensity", "state", "broken", "pending_events"} <= set(row)

    def test_status_and_export(self):
        s = _at(0.30)
        st = s.get_status()
        assert st["state"] == "fraying" and st["sanity"] == 0.3
        assert st["broken"] is False
        assert "state" in s.export_state()
        assert s.export_state()["state"] == "fraying"
        b = _at(0.02)
        assert b.export_state()["broken"] is True
