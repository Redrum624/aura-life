"""
Sanity Engine

The one interior number that integrates and can break.

Affect carries mood, stress and loneliness; shadow carries unease, felt
safety, doubt, intrusive thought, concealment and masking; cognitive carries
focus. Eight engines of interior, and none of them reaches a terminal state:
a persona can be stressed, lonely, afraid and lying all at once, indefinitely,
and be the same persona tomorrow. `SanitySystem` is the trajectory those feed
into -- one scalar, `sanity` in [0, 1], that blows push down, recoveries push
up, time erodes or mends, and that can end.

Two axes, kept apart on purpose:

* **Severity is the blow's.** The host reports what happened and how grave
  it was, in [0, 1] -- a confidant's grave is graver than a stranger's, a
  killing graver than a lie. What a "grief" *is* is the host's business.
* **Intensity is the person's.** A multiplier read from what the persona
  already carries (`struggles`, `character_defects`,
  `intrusive_thought_themes`), never authored by hand. Two people at the same
  grave lose different amounts, and nobody wrote that rule into a wizard.

The number is only ever read through a closed, graded vocabulary (`STATES`),
so a consumer couples to the word, not the threshold, and a retune here does
not ripple outward.

Replayable by construction: the single random draw is the baseline jitter at
construction, and only when an rng is injected. The engine reads no clock;
`tick(hours, ...)` is told how much world time passed.
"""

import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ============= Vocabulary =============

#: The graded state, in order from whole to gone. Consumers couple to these
#: words, never to the numbers below.
STATES = ("sound", "strained", "fraying", "breaking", "broken")

#: Kinds of blow the host may report. Closed list; an unknown kind raises.
BLOW_KINDS = ("grief", "witnessed", "did_harm", "broke_value", "rejected", "neglect", "concealment")

#: How hard each kind lands at severity 1.0 on a person of intensity 1.0.
#: Ordered by what a mind least survives: doing harm and losing someone
#: outrank watching harm and being turned away; the small chronic kinds
#: (neglect, concealment) are meant to be reported often and add up.
BLOW_WEIGHT: Dict[str, float] = {
    "did_harm": 0.35,
    "grief": 0.30,
    "broke_value": 0.25,
    "witnessed": 0.20,
    "rejected": 0.15,
    "neglect": 0.10,
    "concealment": 0.08,
}

#: Kinds of recovery the host may report. Closed list; an unknown kind raises.
RECOVERY_KINDS = ("rest", "warmth", "relief", "answered", "achieved")

#: How much each kind restores at amount 1.0 on a person of resilience 1.0.
#: An answer to the thing that was gnawing outranks being held, which outranks
#: sleep; the way up is slower than the way down at every rung.
RECOVERY_WEIGHT: Dict[str, float] = {
    "answered": 0.15,
    "relief": 0.12,
    "warmth": 0.10,
    "achieved": 0.10,
    "rest": 0.05,
}


# ============= Thresholds =============
#
# `sound` is strictly above SOUND_ABOVE; every other band is closed at its
# floor and open at its ceiling, so 0.75 is strained, 0.50 strained, 0.25
# fraying, 0.10 breaking, and anything under 0.10 broken.

SOUND_ABOVE = 0.75
STRAINED_ABOVE = 0.50
FRAYING_ABOVE = 0.25
BREAKING_ABOVE = 0.10


def state_for(value: float) -> str:
    """Map a sanity value to its state word. The only place the thresholds live."""
    if value > SOUND_ABOVE:
        return "sound"
    if value >= STRAINED_ABOVE:
        return "strained"
    if value >= FRAYING_ABOVE:
        return "fraying"
    if value >= BREAKING_ABOVE:
        return "breaking"
    return "broken"


# ============= Baseline and intensity from character =============
#
# Each burden the persona carries lowers where it starts and raises how hard
# the world lands on it. The bands are chosen so that:
#   * a persona carrying nothing starts at 0.92 -- sound, with room above
#     for recovery and a jitter that cannot push it past BASELINE_MAX;
#   * the most burdened persona bottoms out at BASELINE_MIN = 0.55 -- strained,
#     one band below sound and never fraying: fragility is a starting *lean*,
#     and the first blow is still the host's to deal;
#   * intensity is 1.0 for a person carrying nothing (a blow lands at its
#     face weight) and caps at INTENSITY_MAX = 1.8, so the hardest single blow
#     (did_harm at severity 1.0) costs at most 0.63 and cannot take a sound
#     persona straight to broken in one stroke;
#   * INTENSITY_MIN = 0.6 bounds resilience (= 1 / intensity) at 1.67x, so a
#     jittered-light persona recovers faster but not absurdly so.

BASELINE_START = 0.92
BASELINE_PER_STRUGGLE = 0.04
BASELINE_PER_DEFECT = 0.03
BASELINE_PER_THEME = 0.02
BASELINE_MIN = 0.55
BASELINE_MAX = 0.95

INTENSITY_START = 1.0
INTENSITY_PER_STRUGGLE = 0.10
INTENSITY_PER_DEFECT = 0.08
INTENSITY_PER_THEME = 0.06
INTENSITY_MIN = 0.6
INTENSITY_MAX = 1.8

#: Half-width of the construction-time jitter: the one draw `u` in [-1, 1]
#: moves the baseline by `u * BASELINE_JITTER` and the intensity the other
#: way by `-u * INTENSITY_JITTER` (a person who starts lower also breaks
#: harder), then both are clamped to their bands.
BASELINE_JITTER = 0.03
INTENSITY_JITTER = 0.10


# ============= Drift =============
#
# Per world-hour. Erosion is scaled by intensity, mending by resilience, so
# the same day costs a burdened person more and gives back less -- the
# mask erodes through the library: `concealment_load` is shadow's number,
# and a person who keeps up a front pays for the performance without the
# host writing a rule about it.

DRIFT_DOWN_STRESSED_PER_HOUR = 0.004     # while any stressor is live
DRIFT_DOWN_CONCEALMENT_PER_HOUR = 0.006  # times concealment_load in [0, 1]
DRIFT_UP_PER_HOUR = 0.003                # calm; only up to the baseline


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _n(items) -> int:
    return len(items or [])


class SanitySystem:
    """One scalar interior that integrates the others and can break.

    Construction reads the persona's burdens and derives a baseline (where
    sanity starts and where calm drift returns it to) and an intensity (how
    hard a blow lands). If `rng` is given, exactly one `rng.random()` call
    jitters both; if not, there is no jitter and construction is fully
    deterministic. No draw is ever taken after construction.
    """

    def __init__(
        self,
        struggles: Optional[List[str]] = None,
        character_defects: Optional[List[str]] = None,
        intrusive_thought_themes: Optional[List[str]] = None,
        rng=None,
    ):
        n_struggles = _n(struggles)
        n_defects = _n(character_defects)
        n_themes = _n(intrusive_thought_themes)
        baseline = (
            BASELINE_START
            - BASELINE_PER_STRUGGLE * n_struggles
            - BASELINE_PER_DEFECT * n_defects
            - BASELINE_PER_THEME * n_themes
        )
        intensity = (
            INTENSITY_START
            + INTENSITY_PER_STRUGGLE * n_struggles
            + INTENSITY_PER_DEFECT * n_defects
            + INTENSITY_PER_THEME * n_themes
        )
        if rng is not None:
            u = rng.random() * 2.0 - 1.0          # the one draw
            baseline += u * BASELINE_JITTER
            intensity -= u * INTENSITY_JITTER
        self._baseline = max(BASELINE_MIN, min(BASELINE_MAX, baseline))
        self._intensity = max(INTENSITY_MIN, min(INTENSITY_MAX, intensity))
        self._value = self._baseline
        self._state = state_for(self._value)
        self._broken = self._state == "broken"
        self._events: List[str] = []

    # ============= Inputs =============

    def on_blow(self, kind: str, severity: float) -> float:
        """A blow landed. `kind` from BLOW_KINDS; `severity` in [0, 1] is
        clamped. Loss = severity x BLOW_WEIGHT[kind] x intensity.
        Returns the loss actually applied."""
        if kind not in BLOW_WEIGHT:
            raise ValueError(f"unknown blow kind {kind!r}; expected one of {BLOW_KINDS}")
        loss = _clamp01(severity) * BLOW_WEIGHT[kind] * self._intensity
        self._move(-loss)
        return loss

    def on_recovery(self, kind: str, amount: float) -> float:
        """Something mended. `kind` from RECOVERY_KINDS; `amount` in [0, 1] is
        clamped. Gain = amount x RECOVERY_WEIGHT[kind] x resilience, where
        resilience = 1 / intensity: the same burdens that make a blow land
        harder make rest count for less, so a person of intensity 1.0 mends
        at face value and the most burdened at roughly half. This is the only
        way out of `broken` -- time does not lift it, the host's report does.
        Returns the gain actually applied."""
        if kind not in RECOVERY_WEIGHT:
            raise ValueError(f"unknown recovery kind {kind!r}; expected one of {RECOVERY_KINDS}")
        gain = _clamp01(amount) * RECOVERY_WEIGHT[kind] * self.resilience
        self._move(gain)
        return gain

    def tick(self, hours: float, *, stressed: bool, concealment_load: float) -> None:
        """Advance `hours` of world time. The engine reads no clock: the host
        computes `hours` from its own world clock the way it does for energy.

        While `stressed` or `concealment_load > 0` sanity erodes, the
        concealment part scaled by the load; otherwise it mends toward the
        baseline and stops there (only `on_recovery` goes above it). While
        `broken`, calm time does nothing. Non-positive hours are a no-op.
        """
        if hours <= 0.0:
            return
        load = _clamp01(concealment_load)
        rate = 0.0
        if stressed:
            rate += DRIFT_DOWN_STRESSED_PER_HOUR
        if load > 0.0:
            rate += DRIFT_DOWN_CONCEALMENT_PER_HOUR * load
        if rate > 0.0:
            self._move(-hours * rate * self._intensity)
            return
        if self._broken or self._value >= self._baseline:
            return
        gain = hours * DRIFT_UP_PER_HOUR * self.resilience
        self._move(min(gain, self._baseline - self._value))

    def set_value(self, value: float) -> None:
        """Park sanity at an exact value (persistence, tests, host overrides).
        Goes through the same transition logic as every other move."""
        self._move(_clamp01(value) - self._value)

    def drain_events(self) -> List[str]:
        """Return and clear pending events. Currently only "breaking", appended
        once each time the state falls into `breaking` (or past it) from above."""
        out, self._events = self._events, []
        return out

    # ============= Transitions =============

    def _move(self, delta: float) -> None:
        self._value = _clamp01(self._value + delta)
        new = state_for(self._value)
        old = self._state
        if new == old:
            return
        old_i, new_i = STATES.index(old), STATES.index(new)
        breaking_i = STATES.index("breaking")
        if old_i < breaking_i <= new_i:
            self._events.append("breaking")
        if new == "broken":
            self._broken = True
        elif old == "broken":
            self._broken = False
        self._state = new

    # ============= Properties =============

    @property
    def value(self) -> float:
        return self._value

    @property
    def state(self) -> str:
        return self._state

    @property
    def baseline(self) -> float:
        return self._baseline

    @property
    def intensity(self) -> float:
        return self._intensity

    @property
    def resilience(self) -> float:
        """1 / intensity: how much a recovery or calm hour is worth to this person."""
        return 1.0 / self._intensity

    @property
    def broken(self) -> bool:
        """Terminal flag. Set on entry to `broken`; the engine never clears it
        on its own -- the host decides what broken means, and only a reported
        `on_recovery` that lifts the value back to `breaking` or above clears it."""
        return self._broken

    @property
    def pending_events(self) -> List[str]:
        return list(self._events)

    # ============= Export / Serialize =============

    def export_state(self) -> dict:
        """Structured export for pipeline digest: the word, the number, and the
        flag only when it is up."""
        out = {"state": self._state, "level": round(self._value, 2)}
        if self._broken:
            out["broken"] = True
        return out

    def get_status(self) -> dict:
        """Status for API/debugging."""
        return {
            "sanity": round(self._value, 3),
            "state": self._state,
            "baseline": round(self._baseline, 3),
            "intensity": round(self._intensity, 3),
            "broken": self._broken,
            "pending_events": len(self._events),
        }

    def to_dict(self) -> dict:
        """Serialize for DB storage. Baseline and intensity travel with the row
        so a restart never re-derives (or re-draws) them."""
        return {
            "sanity": self._value,
            "baseline": self._baseline,
            "intensity": self._intensity,
            "state": self._state,
            "broken": self._broken,
            "pending_events": json.dumps(self._events),
        }

    @classmethod
    def from_dict(
        cls,
        data: dict,
        struggles: Optional[List[str]] = None,
        character_defects: Optional[List[str]] = None,
        intrusive_thought_themes: Optional[List[str]] = None,
        rng=None,
    ) -> "SanitySystem":
        """Deserialize from DB. An empty row builds a fresh system from the
        burdens (and takes the one draw if `rng` is given); a stored row
        restores number, state, flag and pending events without any draw."""
        if not data:
            return cls(struggles, character_defects, intrusive_thought_themes, rng=rng)
        system = cls()
        system._baseline = float(data.get("baseline", system._baseline))
        system._intensity = float(data.get("intensity", system._intensity))
        system._value = _clamp01(float(data.get("sanity", system._baseline)))
        system._state = state_for(system._value)
        system._broken = bool(data.get("broken", system._state == "broken"))
        raw = data.get("pending_events", "[]")
        try:
            events = json.loads(raw) if isinstance(raw, str) else list(raw or [])
        except (json.JSONDecodeError, TypeError):
            events = []
        system._events = [str(e) for e in events]
        return system
