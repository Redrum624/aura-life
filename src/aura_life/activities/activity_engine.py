"""
Activity Engine

Manages the persona's activities: selection, execution, how each one goes, and
narrative generation.
"""

import random
from datetime import datetime
from typing import Collection, Dict, List, Optional, Tuple

from ..emotion.appraisal import FAIL, MIXED, OUTCOMES, SUCCESS
from ..models import (
    Activity,
    ActivityCategory,
    ActivityLog,
    Weather,
    TimeOfDay,
    Season,
    Goal,
)
from ..settings import DEFAULT_SETTING, SettingSpec, get_setting
from ..settings.spec import PLAN_ONLY_TAGS
from .choice import TOP_CANDIDATES, ActivityPreferences, ChoiceState, choice_weight, effort
# Legacy name: the activity catalogue moved, unchanged, into the contemporary
# setting pack (aura_life.settings.contemporary) in Task 9 -- the engine reads
# its persona's setting now; re-exported so an import from here keeps working.
from ..settings.contemporary import ACTIVITIES  # noqa: F401

# ============= How an activity goes (Task 14): every number =============
# Before Task 14 every activity went well. Now each one she does goes well,
# only half well ("mixed") or wrong ("fail") -- aura_life.emotion.appraisal
# .OUTCOMES -- and humanely: a hobby mostly goes fine, and something goes
# wrong more often when she is tired, low or new to it. The chance it does not
# go well:
#
#     risk = OUTCOME_BASE_RISK
#          + OUTCOME_EFFORT_RISK    x effort     its energy cost against the energy she
#                                                has (aura_life.activities.choice.effort),
#                                                at most 1: a demanding one, tired, goes
#                                                wrong more often; a restful one is never
#                                                spoiled by her being tired
#          + OUTCOME_LOW_MOOD_RISK  x low        how far her mood's valence is below 0
#          + OUTCOME_UNSKILLED_RISK x unskilled  1 - her level at the skill it trains (her
#                                                setting's skill_mappings; SkillsSystem),
#                                                0 for one that trains none
#
# at most OUTCOME_MAX_RISK; OUTCOME_FAIL_SHARE of it goes wrong outright, the
# rest only half well. Each number is chosen (the Task 14 report lists them).
# What they give, measured over three simulated days at the scheduler's own
# cadence (tests/sim_helpers.py), the no-profile control and Lina's and
# Roberta's emotional baselines, seeds 1-10 (3,593 activities): 84.9% went
# well, 10.2% only half well, 5.0% wrong -- 11.9% to 18.5% not plain success
# per run, 9% to 22% per persona. (A base risk of 0.06 gave 12.7% -- 10.6%
# to 15.2% per run -- too close to the humanness spec's 10% threshold, section
# 6, to hold it; 0.08 is chosen for that margin.)

#: The risk on a good day: rested, in no low mood, at something she has
#: mastered or that trains no skill.
OUTCOME_BASE_RISK = 0.08
#: Added at the most demanding activity for the energy she has (effort 1).
OUTCOME_EFFORT_RISK = 0.2
#: Added at the lowest mood (valence -1); nothing is added at or above 0.
OUTCOME_LOW_MOOD_RISK = 0.3
#: Added for a beginner (level 0) at the skill it trains.
OUTCOME_UNSKILLED_RISK = 0.1
#: Never likelier to go wrong than right.
OUTCOME_MAX_RISK = 0.5
#: Of the risk, the share that goes wrong outright; the rest only half works
#: out -- most of what does not go well is only a little off.
OUTCOME_FAIL_SHARE = 1.0 / 3.0

#: What she says happened when an activity did not go well and its setting
#: has no words for it (``Activity.outcomes``): the library's neutral words,
#: the activity named as she would name it -- ``{Activity}`` /
#: ``{activity}``, which ``LifeService`` fills when it renders the narrative.
NEUTRAL_OUTCOME_NARRATIVES: Dict[str, List[str]] = {
    MIXED: ["{Activity} only half worked out"],
    FAIL: ["{Activity} didn't work out"],
}


def outcome_chances(activity: Activity, *, energy: float, valence: float,
                    skill: Optional[float] = None) -> Dict[str, float]:
    """The chance of each outcome of ``activity`` (the block above), adding
    up to 1: ``energy`` her effective energy, ``valence`` her mood's, and
    ``skill`` her level at the skill it trains (``None``: it trains none)."""
    unskilled = 0.0 if skill is None else 1.0 - max(0.0, min(1.0, skill))
    risk = (OUTCOME_BASE_RISK
            + OUTCOME_EFFORT_RISK * min(1.0, effort(activity, energy))
            + OUTCOME_LOW_MOOD_RISK * max(0.0, min(1.0, -valence))
            + OUTCOME_UNSKILLED_RISK * unskilled)
    risk = max(0.0, min(OUTCOME_MAX_RISK, risk))
    fail = OUTCOME_FAIL_SHARE * risk
    return {SUCCESS: 1.0 - risk, MIXED: risk - fail, FAIL: fail}


class ActivityEngine:
    """
    Manages activity selection and execution.

    Selects what serves her best right now (Task 10,
    :mod:`aura_life.activities.choice`): her needs weighed by her traits,
    what she is into, her habits, her goals and wants, her mood and the
    effort -- within what suits the time of day, the weather, the place,
    some variety and her values. Each one she does goes well, only half
    well or wrong (Task 14, :meth:`roll_outcome`), and is told accordingly
    (:meth:`execute_activity`).
    """

    def __init__(self, rng=None, setting: Optional[SettingSpec] = None,
                 persona_id: Optional[str] = None,
                 preferences: Optional[ActivityPreferences] = None,
                 outcome_rng=None):
        """Initialize activity engine.

        Args:
            rng: Optional ``random.Random`` for activity selection and every
                other draw this engine makes but its outcomes'. ``None`` --
                the default -- is a fresh, unseeded ``random.Random()``
                (never the module), so a bare ``ActivityEngine()`` still
                works and does not share a draw sequence with any other
                instance or the module.
            outcome_rng: Optional ``random.Random`` for how each activity
                goes (:meth:`roll_outcome`) and the words for one that did
                not go well (Task 14) -- a stream of their own
                (``LifeService`` derives it, label "outcome"), so an outcome
                never moves the activity choice's draws. ``None``: a fresh,
                unseeded ``random.Random()``, as for ``rng``.
            setting: The setting pack (:class:`~aura_life.settings.SettingSpec`)
                whose activities this engine offers, in its catalogue order,
                and whose weather suffixes it narrates with. ``None`` -- the
                default -- is :data:`~aura_life.settings.DEFAULT_SETTING`'s.
            persona_id: Whose engine this is: an activity restricted to other
                personas (``Activity.persona_ids``) is not offered to her
                (:meth:`~aura_life.settings.SettingSpec.activities_for`).
                ``None`` offers the unrestricted ones only.
            preferences: Hers (:class:`~aura_life.activities.choice.ActivityPreferences`:
                what her traits make of each need, what she is into).
                ``None`` -- the default -- is the neutral persona's.
        """
        setting = setting if setting is not None else get_setting(DEFAULT_SETTING)
        self._activities = {a.name: a for a in setting.activities_for(persona_id)}
        self._preferences = preferences if preferences is not None else ActivityPreferences()
        self._plan_only = frozenset(PLAN_ONLY_TAGS)
        self._weather_flavors = setting.weather_flavors
        self._recent_activities: List[str] = []
        self._max_recent = 5
        self._rng = rng if rng is not None else random.Random()
        self._outcome_rng = outcome_rng if outcome_rng is not None else random.Random()

    def get_activity(self, name: str) -> Optional[Activity]:
        """Get activity by name."""
        return self._activities.get(name)

    def export_recent_state(self, recent_activities: list) -> dict:
        """Structured dict for LLM pipeline digest passes; each activity with
        how it went (``outcome``, Task 14)."""
        activities = []
        for log in recent_activities[:5]:
            activities.append({
                "name": log.activity_name,
                "narrative": log.narrative[:100] if log.narrative else "",
                "category": log.category.value if hasattr(log.category, 'value') else str(log.category),
                "outcome": getattr(log, "outcome", SUCCESS),
            })
        return {
            "today_activities": activities,
        }

    def get_all_activities(self) -> List[Activity]:
        """Get all defined activities."""
        return list(self._activities.values())

    def select_activity(
        self,
        energy_level: float,
        time_of_day: TimeOfDay,
        weather: Weather,
        current_location: str,
        active_goals: Optional[List[Goal]] = None,
        force_rest: bool = False,
        season: Optional[Season] = None,
        salient_values: Optional[List[dict]] = None,
        exclude: Optional[Collection[str]] = None,
        state: Optional[ChoiceState] = None,
        habit: Optional[Dict[str, Tuple[float, float]]] = None,
    ) -> Optional[Activity]:
        """
        Select what serves her best right now (the utility of
        :mod:`aura_life.activities.choice`), among what suits the moment.

        Args:
            salient_values: Optional list of {"name", "salience", "aligned_tags"} dicts
                from IdentitySystem for value-influenced scoring.
            exclude: Activity names never to pick. ``LifeService`` excludes
                "sleeping" (sleep is her sleep state, not a choice) and
                "napping" unless a nap is open to her.
            state: What she needs and feels now
                (:class:`~aura_life.activities.choice.ChoiceState`;
                ``LifeService`` reads it every activity tick). ``None`` -- or
                a state that leaves them out -- reads her need for rest from
                ``energy_level`` and her goals' pull from ``active_goals``.
            habit: Optional {activity: (raise, damp)} for this part of her day
                (BehaviorSystem.habit_factors), as the planner uses it: the raise
                multiplies the score -- her choice weight, context times
                exp(utility / TEMPERATURE) -- before the cut to the best
                TOP_CANDIDATES, the damp the weight after it (staleness never
                takes one out). Her habits count only here: the utility has no
                habit term of its own.

        One of the day's anchors that happens only when her plan says so
        (:data:`~aura_life.settings.spec.PLAN_ONLY_TAGS`: waking up, bedtime,
        a shift, a commute, a class, study, a meetup) is never picked.

        Returns None if no suitable activity found.
        """
        state = self._complete_state(state, energy_level, active_goals)
        candidates: List[Tuple[Activity, float]] = []

        for activity in self._activities.values():
            if exclude and activity.name in exclude:
                continue
            if activity.tags & self._plan_only:
                continue
            context = self._score_activity(
                activity,
                energy_level,
                time_of_day,
                weather,
                current_location,
                active_goals,
                force_rest,
                season,
                salient_values,
            )
            if context > 0:
                candidates.append((activity, choice_weight(context, self._preferences.utility(activity, state))))

        if not candidates:
            return None

        # The best TOP_CANDIDATES, one drawn in proportion to its weight; her habits as the planner uses them: comfort
        # raises the score before the cut, staleness lowers the weight after it, and a damped one of the best keeps
        # its place.
        candidates.sort(key=lambda x: x[1], reverse=True)
        if habit:
            kept = {a.name for a, _ in candidates[:TOP_CANDIDATES] if habit.get(a.name, (1.0, 1.0))[1] < 1.0}
            candidates = sorted(((a, s * habit.get(a.name, (1.0, 1.0))[0]) for a, s in candidates),
                                key=lambda x: x[1], reverse=True)
            rest = [c for c in candidates if c[0].name not in kept][:TOP_CANDIDATES - len(kept)]
            top_candidates = sorted([c for c in candidates if c[0].name in kept] + rest, key=lambda x: x[1], reverse=True)
        else:
            top_candidates = candidates[:TOP_CANDIDATES]
        total_score = sum(s for _, s in top_candidates)
        weights = [s / total_score for _, s in top_candidates]
        if habit:
            weights = [w * habit.get(a.name, (1.0, 1.0))[1] for w, (a, _) in zip(weights, top_candidates)]

        selected = self._rng.choices([a for a, _ in top_candidates], weights=weights)[0]
        return selected

    @staticmethod
    def _complete_state(state: Optional[ChoiceState], energy_level: float,
                        active_goals: Optional[List[Goal]]) -> ChoiceState:
        """``state`` with what a caller that gave none still tells us: her
        need for rest from her energy, her goals' pull from their motivation."""
        state = state if state is not None else ChoiceState(energy=energy_level)
        needs = state.needs if "rest" in state.needs else {**state.needs, "rest": max(0.0, 1.0 - energy_level)}
        pulls = state.pulls
        if not pulls and active_goals:
            pulls = {}
            for goal in active_goals:
                for name in goal.related_activities:
                    pulls[name] = max(pulls.get(name, 0.0), goal.motivation_level)
        if needs is state.needs and pulls is state.pulls:
            return state
        return ChoiceState(needs=needs, valence=state.valence, arousal=state.arousal, energy=state.energy,
                           history=state.history, pulls=pulls, resolving=state.resolving)

    def roll_outcome(self, activity: Activity, *, energy: float, valence: float,
                     skill: Optional[float] = None) -> Tuple[str, Dict[str, float]]:
        """How ``activity`` goes (Task 14): one draw on the outcome stream
        against :func:`outcome_chances` -- a failure below its chance, a
        mixed outcome in the band above it, else a success -- and the
        chances it was drawn from (what her appraisal reads as how expected
        it was)."""
        chances = outcome_chances(activity, energy=energy, valence=valence, skill=skill)
        draw = self._outcome_rng.random()
        if draw < chances[FAIL]:
            return FAIL, chances
        if draw < chances[FAIL] + chances[MIXED]:
            return MIXED, chances
        return SUCCESS, chances

    def outcome_narrative(self, activity: Activity, outcome: str) -> Optional[str]:
        """What she says happened when ``activity`` did not go well: one of
        its setting's ``outcomes[outcome]`` -- or, when it has none, of the
        library's NEUTRAL_OUTCOME_NARRATIVES -- drawn on the outcome stream.
        ``None`` for a success, which its own narratives tell."""
        if outcome not in OUTCOMES:
            raise ValueError(f"an outcome is one of {OUTCOMES}, got {outcome!r}")
        if outcome == SUCCESS:
            return None
        texts = (activity.outcomes or {}).get(outcome) or NEUTRAL_OUTCOME_NARRATIVES[outcome]
        return self._outcome_rng.choice(texts)

    def execute_activity(
        self,
        activity: Activity,
        location: str,
        weather: Weather,
        energy_before: float,
        outcome: str = SUCCESS,
    ) -> ActivityLog:
        """
        Execute an activity and generate narrative.

        ``outcome`` (Task 14): how it went -- a success unless told otherwise,
        as every activity was before. One that did not go well is told in
        its setting's words for that (:meth:`outcome_narrative`, drawn on the
        outcome stream) instead of its own narratives, with no weather
        suffix and no thought (they tell of a success), and is nothing to
        share. This engine's own draws -- the narrative, the weather, the
        thoughts, the share -- are taken whatever the outcome, so how one
        activity went never moves the next one's. Its feelings are the
        activity's own ``emotion_effects``; ``LifeService`` replaces them
        with her appraisal of how it went.

        Returns an ActivityLog with all details.
        """
        told_otherwise = self.outcome_narrative(activity, outcome)

        # Generate narrative
        narrative = self._rng.choice(activity.narrative_templates)

        # Add weather flavor
        weather_flavor = self._get_weather_flavor(weather, activity)
        if weather_flavor:
            narrative += f" {weather_flavor}"

        # Select thoughts
        thoughts = []
        if activity.thought_possibilities:
            num_thoughts = self._rng.randint(1, min(2, len(activity.thought_possibilities)))
            thoughts = self._rng.sample(activity.thought_possibilities, num_thoughts)

        # Determine if share-worthy (base + random chance)
        share_worthy = activity.share_worthy and self._rng.random() < 0.7

        # What did not go well is told in its own words, with no thought of
        # a success's and nothing to share.
        if told_otherwise is not None:
            narrative, thoughts, share_worthy = told_otherwise, [], False

        # Calculate energy after
        energy_after = max(0.0, min(1.0, energy_before - activity.energy_cost))

        # Record in recent activities
        self._recent_activities.append(activity.name)
        if len(self._recent_activities) > self._max_recent:
            self._recent_activities.pop(0)

        return ActivityLog(
            activity_name=activity.name,
            category=activity.category,
            started_at=datetime.now(),
            ended_at=datetime.now(),  # Simplified - instant for simulation
            location=location,
            weather=weather,
            narrative=narrative,
            thoughts_generated=thoughts,
            emotions_triggered=activity.emotion_effects.copy(),
            energy_before=energy_before,
            energy_after=energy_after,
            share_worthy=share_worthy,
            outcome=outcome,
        )

    def _score_activity(
        self,
        activity: Activity,
        energy_level: float,
        time_of_day: TimeOfDay,
        weather: Weather,
        current_location: str,
        active_goals: Optional[List[Goal]],
        force_rest: bool,
        season: Optional[Season] = None,
        salient_values: Optional[List[dict]] = None,
    ) -> float:
        """How well an activity suits the moment -- time of day, weather,
        place, variety, her values -- 0 when it cannot happen at all (not
        rest when rest is forced, out of season, too little energy). What it
        does for her -- her goals, her need for rest -- is its utility now
        (:mod:`aura_life.activities.choice`), no longer a factor here.
        ``active_goals`` is kept for callers that pass it."""
        score = 1.0

        # Force rest check
        if force_rest and activity.category != ActivityCategory.REST:
            return 0.0

        # Season filter — if activity has preferred seasons and current season doesn't match, skip
        if activity.preferred_seasons and season and season not in activity.preferred_seasons:
            return 0.0

        # Energy check (hard requirement)
        if energy_level < activity.min_energy:
            return 0.0

        # Don't repeat recent activities
        if activity.name in self._recent_activities:
            score *= 0.3

        # Time preference
        if time_of_day in activity.preferred_times:
            score *= 1.5
        else:
            score *= 0.5

        # Weather preference
        if weather in activity.preferred_weather:
            score *= 1.3

        # Location suitability
        if current_location in activity.suitable_locations:
            score *= 1.5
        else:
            score *= 0.3

        # Value alignment bonus
        if salient_values:
            cat_tag = activity.category.value.lower()
            for val in salient_values:
                aligned_tags = val.get("aligned_tags", [])
                if cat_tag in aligned_tags:
                    score *= 1.4  # VALUE_ACTIVITY_SCORE_MULTIPLIER
                    break  # One match is enough

        return score

    def _get_weather_flavor(self, weather: Weather, activity: Activity) -> str:
        """Get weather-specific narrative flavor: her setting's suffix for
        this weather (``SettingSpec.weather_flavors``), none if it has none."""
        # Only add flavor sometimes
        if self._rng.random() < 0.6:
            return self._weather_flavors.get(weather, "")
        return ""

