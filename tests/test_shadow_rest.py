"""The shadow engine has a rest, and she comes back to it (humanness Task 36, ruling T18-R10).

Measured before this task, on 0.5.0 and on the branch alike: a fresh
``ShadowSystem`` ticked with nothing driving it -- no stress, no loneliness, a
neutral mood, no conflict -- lost its felt safety from 0.7 to 0.0 within 24
ticks and never got it back, with a perfect mood too. Its unease then sat at
0.45 to 0.55, so every persona read as unsafe, uneasy, doubting and putting on
a front for good: the moment's first line was "Something has you on edge" in
every capture of every persona.

The cause was where the engine measured from: the unease target counted the
whole distance of felt safety from 1 and of mood from its best, so at rest it
sat above the resting floor, and felt safety was worn down by all of her
unease, its resting floor included, faster than it could ever recover. Both
are measured from rest now: felt safety below ``SAFETY_REST``, a mood below
neutral, unease above ``UNEASE_REST``.
"""

import pytest

from aura_life.models import ShadowState
from aura_life.shadow.shadow_system import SAFETY_REST, UNEASE_REST, ShadowSystem

#: What ``export_state`` gives when she is insecure or hiding behind a front.
INSECURE = {"felt_unsafe", "unease", "doubt", "masking"}
#: Three simulated days of five-minute ticks, and fifty hours of them.
THREE_DAYS = 864
FIFTY_HOURS = 600
REST = {"stress": 0.0, "loneliness": 0.0, "mood": 0.5}
WORST = {"stress": 1.0, "loneliness": 1.0, "mood": 0.0}


def _held(shadow: ShadowSystem, ticks: int, **inputs) -> ShadowState:
    for _ in range(ticks):
        shadow.tick(**inputs)
    return shadow._state


def _at_rest(state: ShadowState) -> bool:
    return abs(state.felt_safety - SAFETY_REST) < 0.01 and abs(state.unease - UNEASE_REST) < 0.01


@pytest.mark.parametrize("mood", [0.5, 0.75, 1.0])
def test_with_nothing_driving_it_she_stays_at_rest(mood):
    shadow = ShadowSystem()
    for tick in range(THREE_DAYS):
        shadow.tick(stress=0.0, loneliness=0.0, mood=mood)
        shown = INSECURE & shadow.export_state().keys()
        assert not shown, f"tick {tick}: at rest she shows {sorted(shown)}"
    assert _at_rest(shadow._state), (shadow._state.felt_safety, shadow._state.unease)


def test_she_comes_back_to_rest_when_the_pressure_ends():
    shadow = ShadowSystem()
    hard = _held(shadow, FIFTY_HOURS, **WORST)
    assert hard.felt_safety < 0.01 and hard.unease > 0.99, (hard.felt_safety, hard.unease)
    after = _held(shadow, FIFTY_HOURS, **REST)
    assert _at_rest(after), (after.felt_safety, after.unease)
    assert not INSECURE & shadow.export_state().keys()


def test_a_state_the_old_engine_saved_comes_back_to_rest():
    """Where every saved persona stands: the level the old engine settled
    at with nothing driving it."""
    saved = ShadowState(felt_safety=0.0, unease=0.55, doubt=0.47, masking=0.425, shame=0.172)
    shadow = ShadowSystem(initial_state=saved)
    assert INSECURE <= shadow.export_state().keys()
    after = _held(shadow, FIFTY_HOURS, **REST)
    assert _at_rest(after), (after.felt_safety, after.unease)
    assert not INSECURE & shadow.export_state().keys()


def test_pressure_lowers_her_felt_safety_by_degrees():
    """More of it, less safety, and none of these alone takes all of it."""
    levels = [_held(ShadowSystem(), FIFTY_HOURS, stress=0.0, loneliness=lonely, mood=0.5).felt_safety
              for lonely in (0.25, 0.5, 0.75, 1.0)]
    assert all(0.05 < level < SAFETY_REST - 0.05 for level in levels), levels
    assert all(more < less - 0.02 for less, more in zip(levels, levels[1:])), levels


def test_only_unease_at_its_maximum_takes_all_her_felt_safety():
    """Unease held at its maximum wears felt safety down exactly as fast as
    it can recover from nothing (``SAFETY_EROSION``); unease held under it --
    the most stress alone gives -- leaves her some."""
    worst = _held(ShadowSystem(), FIFTY_HOURS, **WORST)
    assert worst.unease > 0.99 and worst.felt_safety < 0.01, (worst.unease, worst.felt_safety)
    spared = _held(ShadowSystem(), FIFTY_HOURS, stress=1.0, loneliness=0.0, mood=0.5)
    assert spared.unease < 0.9 and spared.felt_safety > 0.1, (spared.unease, spared.felt_safety)


def test_a_low_mood_unsettles_her_and_a_neutral_one_does_not():
    neutral = _held(ShadowSystem(), FIFTY_HOURS, stress=0.0, loneliness=0.0, mood=0.5)
    low = _held(ShadowSystem(), FIFTY_HOURS, stress=0.0, loneliness=0.0, mood=0.0)
    assert _at_rest(neutral), (neutral.unease, neutral.felt_safety)
    assert low.unease > UNEASE_REST + 0.15 and low.felt_safety < SAFETY_REST - 0.05, (low.unease, low.felt_safety)


def test_a_conflict_still_shakes_her_at_once():
    shadow = ShadowSystem()
    _held(shadow, 100, **REST)
    before = shadow._state.felt_safety
    shadow.tick(conflict=1.0, **REST)
    assert shadow._state.felt_safety < before - 0.2, (before, shadow._state.felt_safety)


@pytest.mark.parametrize("seeded", [None, 0.6], ids=["no-shame-seed", "a-shame-seed"])
def test_her_shame_rests_at_her_own_baseline(seeded):
    """Review of Task 36, Important 1: shame's relief counted ALL her felt
    safety, so once felt safety rested at 0.7 her shame rested 0.245 under
    its baseline -- at zero for a persona with no shame seed. The relief
    counts felt safety above her rest now (as the unease target and the wear
    do): with nothing driving it her shame is her seeded, chronic level."""
    shadow = ShadowSystem() if seeded is None else ShadowSystem(initial_state=ShadowState(shame=seeded))
    baseline = shadow._shame_baseline
    assert baseline == pytest.approx(0.15 if seeded is None else seeded)
    after = _held(shadow, THREE_DAYS, **REST)
    assert after.shame == pytest.approx(baseline, abs=0.005), (after.shame, baseline)
    hard = _held(shadow, FIFTY_HOURS, **WORST)
    assert hard.shame >= baseline - 0.005, (hard.shame, baseline)
    assert _held(shadow, FIFTY_HOURS, **REST).shame == pytest.approx(baseline, abs=0.005)


@pytest.mark.parametrize("held,unease,felt_safety", [
    ({"stress": 0.25, "loneliness": 0.0, "mood": 0.5}, 0.3045, 0.5727),
    ({"stress": 0.0, "loneliness": 1.0, "mood": 0.5}, 0.6136, 0.3182),
    ({"stress": 0.0, "loneliness": 0.0, "mood": 0.45}, 0.1809, 0.6745),
    ({"stress": 0.0, "loneliness": 0.0, "mood": 0.25}, 0.3045, 0.5727),
], ids=["a-quarter-stress", "all-lonely", "a-touch-low", "half-low"])
def test_held_pressure_settles_her_where_the_two_rests_say(held, unease, felt_safety):
    """Review of Task 36, Minor 4: the constants are pinned by where a held
    pressure settles her, not only by its direction. With the pressure
    X = 0.4 stress + 0.3 loneliness + 0.2 (mood below neutral, 0 to 1) and
    the loop returning g = 0.3 / (1 - UNEASE_REST) of a change, her unease
    settles at UNEASE_REST + X / (1 - g) and her felt safety at
    SAFETY_REST (1 - (unease - UNEASE_REST) / (1 - UNEASE_REST)). The four
    values are the reviewer's and the controller's runs of the engine; the
    test also computes them from the constants."""
    below = max(0.0, 0.5 - held["mood"]) / 0.5
    pressure = 0.4 * held["stress"] + 0.3 * held["loneliness"] + 0.2 * below
    gain = 0.3 / (1.0 - UNEASE_REST)
    expected_unease = UNEASE_REST + pressure / (1.0 - gain)
    expected_safety = SAFETY_REST * (1.0 - (expected_unease - UNEASE_REST) / (1.0 - UNEASE_REST))
    assert (expected_unease, expected_safety) == pytest.approx((unease, felt_safety), abs=5e-4)
    state = _held(ShadowSystem(), 2000, **held)
    assert (state.unease, state.felt_safety) == pytest.approx((unease, felt_safety), abs=5e-4)


def test_her_unease_comes_down_to_what_still_drives_it_and_never_under_it():
    """Review of Task 36, Minor 4: when the pressure eases her unease decays
    toward what is left of it, never toward the bare floor (which undershot
    the level a quarter of stress still holds)."""
    shadow = ShadowSystem()
    _held(shadow, 200, stress=1.0, loneliness=0.0, mood=0.5)
    lows = []
    for _ in range(400):
        shadow.tick(stress=0.25, loneliness=0.0, mood=0.5)
        lows.append(shadow._state.unease)
    assert min(lows) > 0.3045 - 5e-4, min(lows)
    assert lows[-1] == pytest.approx(0.3045, abs=5e-3)


def test_a_shaken_felt_safety_unsettles_her_until_it_is_back():
    """The felt safety she is short of raises her unease with nothing else
    wrong; both are back at rest once it has recovered."""
    shadow = ShadowSystem()
    _held(shadow, 100, **REST)
    _held(shadow, 2, conflict=1.0, **REST)
    shaken = _held(shadow, 5, **REST)
    assert shaken.felt_safety < SAFETY_REST - 0.3 and shaken.unease > UNEASE_REST + 0.05, \
        (shaken.felt_safety, shaken.unease)
    assert _at_rest(_held(shadow, FIFTY_HOURS, **REST))
