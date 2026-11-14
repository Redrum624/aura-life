"""
Goal Engine

Manages the persona's self-generated goals based on personality, experiences, and conversations.

Goals have a living lifecycle:
- Created with full motivation
- Motivation decays when no progress is made
- Goals can be abandoned when they feel out of reach
- Being goalless is emotionally significant (sad, listless)
- Picking up a new goal brings renewed motivation
"""

import random
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..activities.choice import (
    ActivityPreferences,
    derived_satisfaction,
    match_strength,
    matching_activities,
    terms,
)
from ..models import Goal, GoalTimeframe, GoalSource, ActivityLog
from ..personas.parameters import PersonaParameters
from ..settings import DEFAULT_SETTING, SettingSpec, get_setting
from ..settings.spec import ANCHOR_TAGS
# Legacy names: the goal pools and the daily intentions moved, unchanged, into
# the contemporary setting pack (aura_life.settings.contemporary) in Task 9 --
# the engine reads its persona's setting now; re-exported so an import from
# here keeps working.
from ..settings.contemporary import (  # noqa: F401
    DAILY_INTENTIONS,
    DREAM_GOALS,
    LONG_TERM_GOALS,
    PERSONALITY_GOALS,
)


# ============= Emotional Events =============

class GoalEvent:
    """An emotional event produced by the goal system."""
    def __init__(self, event_type: str, goal_title: str, emotions: Dict[str, float], description: str = ""):
        self.event_type = event_type  # "abandoned", "goalless", "new_goal", "motivation_drop", "completed"
        self.goal_title = goal_title
        self.emotions = emotions  # emotion -> intensity
        self.description = description


# Motivation decay rates (per hour without progress)
MOTIVATION_DECAY_RATES = {
    GoalTimeframe.DAILY: 0.0,       # Daily goals don't decay (they just expire)
    GoalTimeframe.WEEKLY: 0.008,    # ~full decay in ~5 days without progress
    GoalTimeframe.LONG_TERM: 0.003, # ~full decay in ~2 weeks without progress
    GoalTimeframe.DREAM: 0.001,     # Dreams decay very slowly
}

# Stagnation thresholds (hours without progress before decay starts)
STAGNATION_THRESHOLDS = {
    GoalTimeframe.DAILY: 999,       # Don't decay daily goals
    GoalTimeframe.WEEKLY: 24,       # 1 day before motivation starts dropping
    GoalTimeframe.LONG_TERM: 72,    # 3 days before decay starts
    GoalTimeframe.DREAM: 168,       # 1 week before dream motivation drops
}

# ============= Her own goals (Task 10) =============
# What her definition's goal sources become. Titles are first person, like
# the setting pools' ("Find my authentic voice"); each value, struggle and
# interest is her own words, so the templates only frame them. Chosen for
# Task 10 (see its report).

#: Her personal goal (``PersonalityDefinition.personal_goal``, the persona
#: generator's) is her dream, in her own words.
PERSONAL_GOAL_MOTIVATION = "It's what I want most"
#: An interest becomes a long-term goal.
INTEREST_GOAL = {
    "title": "Go deeper into {text}",
    "description": "Make real time for it, not just scraps",
    "motivation": "It's what I love doing",
}
#: A core value becomes a weekly goal.
VALUE_GOAL = {
    "title": "Stay true to {text}",
    "description": "Let it show in what I actually do this week",
    "motivation": "It's what I stand for",
}
#: A struggle becomes a weekly goal.
STRUGGLE_GOAL = {
    "title": "Work on {text}",
    "description": "Not fix it, just not let it run things",
    "motivation": "I don't want it deciding for me",
}
#: A core value or an interest becomes a daily intention.
VALUE_INTENTION = {"title": "Make room for {text} today", "motivation": "It's what I stand for"}
INTEREST_INTENTION = {"title": "Spend some time on {text}", "motivation": "It's what I love doing"}
#: How many weekly goals she starts with (as she did from the setting's pool).
STARTING_WEEKLY_GOALS = 2


#: A struggle is worked on through what helps her process -- the activities
#: that meet her need to reflect (aura_life.activities.choice).
STRUGGLE_NEEDS = ("reflection",)


def _text(value: Any) -> str:
    """One of her goal sources as the words a template frames: stripped of
    surrounding space and of a trailing full stop ("Go deeper into
    reading", never "reading.")."""
    return str(value or "").strip().rstrip(".").strip()


def _texts(values: Any) -> List[str]:
    """A definition's list field as its non-empty texts (a bare str is one)."""
    if not values:
        return []
    if isinstance(values, str):
        values = [values]
    return [text for text in (_text(v) for v in values) if text]


# Abandon reasons based on conditions
ABANDON_REASONS = [
    "It started to feel impossible",
    "I lost sight of why it mattered",
    "Maybe it wasn't really what I wanted",
    "It felt too far away to keep reaching",
    "I couldn't find my way forward with it",
    "Something about it stopped resonating",
]


class GoalEngine:
    """
    Manages the persona's goals with a living emotional lifecycle.

    Goals aren't just progress bars — they carry motivation that
    decays without progress. She can give up, feel lost without
    direction, and find renewed purpose in new goals.
    """

    # Upper bound on the completed / abandoned history kept in memory (and
    # therefore re-written to `life_goals` on every save). Readers only ever
    # take the last 3, 5 or 10 (see `_build_reflection`, `export_state`,
    # `get_status`), so this is generous headroom, not a working set.
    MAX_GOAL_HISTORY = 20

    def __init__(self, rng=None, setting: Optional[SettingSpec] = None, definition=None,
                 parameters: Optional[PersonaParameters] = None, persona_id: Optional[str] = None,
                 interests: Optional[List[str]] = None):
        """Initialize goal engine.

        ``rng``: optional ``random.Random``. ``None`` -- the default -- is a
        fresh, unseeded ``random.Random()`` (never the module), so a bare
        ``GoalEngine()`` still works and shares no draw sequence with any
        other instance or the module.

        ``setting``: her setting pack (:class:`~aura_life.settings.SettingSpec`),
        whose goal pools (``personality_goals``, ``long_term_goals``,
        ``dream_goals``) and ``daily_intentions`` her goals are also drawn
        from, and whose activities (those open to ``persona_id``) her own
        goals are pursued through. ``None`` -- the default -- is
        :data:`~aura_life.settings.DEFAULT_SETTING`'s. An empty pool gives no
        goal of its kind.

        ``definition`` (a ``PersonalityDefinition``) and ``parameters`` (her
        :class:`~aura_life.personas.parameters.PersonaParameters`): who she
        is (Task 10). Her personal goal is her dream, her interests her
        long-term goals, her core values and struggles her weekly goals, her
        values and interests her daily intentions (the templates above,
        with the activities that match each); a kind she has none of comes
        from the setting's pools, ranked by how well each fits her -- its
        words against hers, and how much its activities are her kind
        (ActivityPreferences: affinity and her traits' lean), ties drawn.
        No definition is the setting's pools alone, drawn as before.
        ``interests``, when given, are hers instead of the definition's (a
        host may pass its own, as ``LifeService`` takes them).
        """
        self._active_goals: List[Goal] = []
        self._completed_goals: List[Goal] = []
        self._abandoned_goals: List[Goal] = []
        self._last_daily_generation: Optional[datetime] = None
        self._goalless_since: Optional[datetime] = None  # When she ran out of non-daily goals
        self._rng = rng if rng is not None else random.Random()
        self._setting = setting if setting is not None else get_setting(DEFAULT_SETTING)
        self._definition = definition
        self._interests = _texts(interests) or _texts(getattr(definition, "interests", None))
        # What a goal is pursued through: her activities, less the day's
        # anchors (a meal, a shift ...: routine, not a pursuit).
        self._activities = [a for a in self._setting.activities_for(persona_id) if not a.tags & set(ANCHOR_TAGS)]
        self._preferences = (ActivityPreferences.from_definition(definition, parameters, interests=self._interests)
                             if definition is not None or self._interests else None)
        self._persona_words = self._words_of(definition)
        self._own_dream, self._own_long_term, self._own_weekly, self._own_intentions = self._own_templates(definition)

    # ============= Her own templates (Task 10) =============

    def _words_of(self, definition) -> frozenset:
        """Every word her goal sources say: what the setting's goals are
        ranked against."""
        words = set()
        for text in self._interests:
            words |= terms(text)
        if definition is not None:
            for field_name in ("core_values", "struggles"):
                for text in _texts(getattr(definition, field_name, None)):
                    words |= terms(text)
            words |= terms(getattr(definition, "personal_goal", "") or "")
        return frozenset(words)

    def _matching(self, text: str) -> List[str]:
        """Her activities that ``text`` matches (aura_life.activities.choice)."""
        return matching_activities(text, self._activities)

    def _framed(self, frame: Dict[str, str], text: str, timeframe: GoalTimeframe,
                related: List[str]) -> Dict[str, Any]:
        template: Dict[str, Any] = {key: value.format(text=text) for key, value in frame.items()}
        template["timeframe"] = timeframe
        template["related_activities"] = related
        return template

    def _own_templates(self, definition):
        """(dream, long-term, weekly, daily intention) templates from her
        definition: her personal goal, her interests, her values and
        struggles (interleaved, values first), her values and interests.

        Only goals she can pursue: a goal makes progress only through its
        activities (:meth:`update_progress_from_activity`), so one her setting
        offers none for -- "Stay true to loyalty" where nothing is about
        loyalty -- is not taken up (fix round 1, finding 3); a kind left with
        none comes from her setting's pools."""
        values = _texts(getattr(definition, "core_values", None))
        struggles = _texts(getattr(definition, "struggles", None))
        interests = self._interests
        personal = str(getattr(definition, "personal_goal", "") or "").strip()

        def pursuable(templates):
            return [template for template in templates if template["related_activities"]]

        dream = []
        if personal:
            dream.append({"title": personal, "description": "", "timeframe": GoalTimeframe.DREAM,
                          "motivation": PERSONAL_GOAL_MOTIVATION, "related_activities": self._matching(personal)})
        long_term = [self._framed(INTEREST_GOAL, text, GoalTimeframe.LONG_TERM, self._matching(text))
                     for text in interests]
        valued = pursuable([self._framed(VALUE_GOAL, text, GoalTimeframe.WEEKLY, self._related_to_value(text))
                            for text in values])
        processing = [a.name for a in self._activities
                      if any(self._need_met(a, need) for need in STRUGGLE_NEEDS)]
        struggled = pursuable([self._framed(STRUGGLE_GOAL, text, GoalTimeframe.WEEKLY, list(processing))
                               for text in struggles])
        weekly = [t for pair in zip(valued, struggled) for t in pair]
        weekly += valued[len(struggled):] + struggled[len(valued):]
        intentions = ([self._framed(VALUE_INTENTION, text, GoalTimeframe.DAILY, self._related_to_value(text))
                       for text in values]
                      + [self._framed(INTEREST_INTENTION, text, GoalTimeframe.DAILY, self._matching(text))
                         for text in interests])
        return pursuable(dream), pursuable(long_term), weekly, pursuable(intentions)

    def _related_to_value(self, value: str) -> List[str]:
        """What she pursues a value through: the activities its words match,
        and those of the setting's goals that speak of it ("curiosity" and
        "Learn something completely new": "Curiosity is what makes life rich")."""
        related = self._matching(value)
        words = terms(value)
        open_to_her = {a.name for a in self._activities}
        for template in self._setting_goal_pools():
            text = " ".join(str(template.get(key, "")) for key in ("title", "description", "motivation"))
            if words & terms(text):
                related += [name for name in template.get("related_activities", [])
                            if name in open_to_her and name not in related]
        return related

    @staticmethod
    def _need_met(activity, need: str) -> bool:
        return derived_satisfaction(activity).get(need, 0.0) > 0.0

    def _setting_goal_pools(self) -> List[Dict[str, Any]]:
        return (list(self._setting.dream_goals) + list(self._setting.long_term_goals)
                + list(self._setting.personality_goals))

    def _ranked(self, pool) -> List[Dict[str, Any]]:
        """The setting's templates, best fit for her first: its words against
        hers, and how much its activities are her kind (her affinity and her
        traits' lean). Ties in drawn order; with no definition, drawn order."""
        order = list(pool)
        self._rng.shuffle(order)
        if self._preferences is None:
            return order
        by_name = {a.name: a for a in self._activities}

        def fit(template) -> float:
            text = " ".join(str(template.get(key, "")) for key in ("title", "description", "motivation"))
            words = terms(text)
            related = [by_name[name] for name in template.get("related_activities", []) if name in by_name]
            kind = (sum(self._preferences.plan_preference(a) for a in related) / len(related)) if related else 0.0
            return match_strength(words, self._persona_words, frozenset()) + kind

        return sorted(order, key=fit, reverse=True)

    @property
    def active_goals(self) -> List[Goal]:
        """Get active goals."""
        return self._active_goals

    @property
    def completed_goals(self) -> List[Goal]:
        """Get completed goals."""
        return self._completed_goals

    @property
    def abandoned_goals(self) -> List[Goal]:
        """Get abandoned goals."""
        return self._abandoned_goals

    @property
    def is_goalless(self) -> bool:
        """Check if she has no meaningful (non-daily) goals."""
        meaningful = [g for g in self._active_goals if g.timeframe != GoalTimeframe.DAILY]
        return len(meaningful) == 0

    @property
    def goalless_duration_hours(self) -> float:
        """How long she's been without meaningful goals, to the host's clock
        (:meth:`goalless_hours` with no instant)."""
        return self.goalless_hours()

    def goalless_hours(self, now: Optional[datetime] = None) -> float:
        """How long she's been without meaningful goals, to ``now`` (the world
        instant ``LifeService`` passes, humanness Task 19; the host's clock
        when omitted)."""
        if not self._goalless_since:
            return 0.0
        now = now if now is not None else datetime.now()
        return (now - self._goalless_since).total_seconds() / 3600

    def initialize_goals(self, *, now: Optional[datetime] = None) -> None:
        """Initialize with starting goals if none exist: a dream, a long-term
        goal, STARTING_WEEKLY_GOALS weekly ones and the day's intention --
        each her own when her definition gives one of its kind, else the
        best fit of her setting's pool (one her setting leaves empty gives
        none)."""
        if not self._active_goals:
            # One dream goal, one long-term goal
            for own, pool in ((self._own_dream, self._setting.dream_goals),
                              (self._own_long_term, self._setting.long_term_goals)):
                chosen = own[:1] or self._ranked(pool)[:1]
                for template in chosen:
                    self._add_goal_from_template(template, own=bool(own), now=now)

            # Weekly goals: her values and struggles, then the setting's best fits
            weekly = self._own_weekly[:STARTING_WEEKLY_GOALS]
            for template in weekly:
                self._add_goal_from_template(template, own=True, now=now)
            missing = STARTING_WEEKLY_GOALS - len(weekly)
            if missing > 0:
                for template in self._ranked(self._setting.personality_goals)[:missing]:
                    self._add_goal_from_template(template, now=now)

            # Generate daily intention
            self.generate_daily_goal(now=now)

    def evaluate_motivation(self, *, now: Optional[datetime] = None) -> List[GoalEvent]:
        """
        Evaluate motivation for all goals. Called on each goal tick.

        Returns emotional events that the life service should process.
        ``now``: the world instant ``LifeService`` passes (humanness Task 19):
        how long a goal has stalled, the goalless spell; the host's clock
        when omitted.
        """
        events: List[GoalEvent] = []
        now = now if now is not None else datetime.now()

        for goal in self._active_goals[:]:  # Copy — we may remove during iteration
            if goal.timeframe == GoalTimeframe.DAILY:
                continue  # Daily goals don't have motivation decay

            # Calculate hours since last progress
            last_progress = goal.last_progress_at or goal.created_at
            hours_stagnant = (now - last_progress).total_seconds() / 3600
            stagnation_threshold = STAGNATION_THRESHOLDS.get(goal.timeframe, 48)

            if hours_stagnant <= stagnation_threshold:
                # Not stagnant yet — motivation recovers slightly
                if goal.motivation_level < 1.0:
                    goal.motivation_level = min(1.0, goal.motivation_level + 0.01)
                continue

            # Motivation decays
            decay = MOTIVATION_DECAY_RATES.get(goal.timeframe, 0.005)
            old_level = goal.motivation_level
            goal.motivation_level = max(0.0, goal.motivation_level - decay)

            # Crossed below 0.5 — starting to doubt
            if old_level >= 0.5 and goal.motivation_level < 0.5:
                events.append(GoalEvent(
                    event_type="motivation_drop",
                    goal_title=goal.title,
                    emotions={"discouraged": 0.3, "doubtful": 0.2},
                    description=f"Starting to wonder if '{goal.title}' is really possible",
                ))

            # Crossed below 0.2 — on the verge of giving up
            if old_level >= 0.2 and goal.motivation_level < 0.2:
                events.append(GoalEvent(
                    event_type="motivation_drop",
                    goal_title=goal.title,
                    emotions={"discouraged": 0.5, "sad": 0.3, "frustrated": 0.2},
                    description=f"'{goal.title}' feels impossibly far away",
                ))

            # Hit zero — abandon the goal
            if goal.motivation_level <= 0.0:
                reason = self._rng.choice(ABANDON_REASONS)
                event = self._abandon_goal(goal, reason, now=now)
                events.append(event)

        # Check goalless state
        was_goalless = self._goalless_since is not None
        if self.is_goalless and not was_goalless:
            self._goalless_since = now
            events.append(GoalEvent(
                event_type="goalless",
                goal_title="",
                emotions={"sad": 0.4, "lost": 0.3, "empty": 0.2},
                description="Nothing feels worth pursuing right now",
            ))
        elif not self.is_goalless and was_goalless:
            self._goalless_since = None

        # If goalless for a while, eventually pick up something new
        if self.is_goalless and self.goalless_hours(now) > 6:
            # 15% chance per tick to find new motivation
            if self._rng.random() < 0.15:
                new_goal = self._pick_up_new_goal(now=now)
                if new_goal:
                    self._goalless_since = None
                    events.append(GoalEvent(
                        event_type="new_goal",
                        goal_title=new_goal.title,
                        emotions={"hopeful": 0.4, "motivated": 0.3, "curious": 0.2},
                        description=f"Something about '{new_goal.title}' feels right. Maybe it's worth trying.",
                    ))

        return events

    def generate_daily_goal(self, *, now: Optional[datetime] = None) -> Optional[Goal]:
        """Generate a new daily intention, from her own pool -- her values
        and interests (VALUE_INTENTION, INTEREST_INTENTION) -- or, when she
        has neither, her setting's ``daily_intentions`` (none when it has
        none). One a day of ``now`` (the world instant ``LifeService``
        passes, humanness Task 19; the host's clock when omitted)."""
        now = now if now is not None else datetime.now()

        # Only one daily goal per day
        if self._last_daily_generation and self._last_daily_generation.date() == now.date():
            return None

        # Remove old daily goals
        self._active_goals = [
            g for g in self._active_goals
            if g.timeframe != GoalTimeframe.DAILY or g.created_at.date() == now.date()
        ]

        # Select a daily intention: hers, or her setting's
        intentions = self._own_intentions or self._setting.daily_intentions
        if not intentions:
            return None
        template = self._rng.choice(intentions)
        goal = Goal(
            title=template["title"],
            description=template.get("description", ""),
            timeframe=GoalTimeframe.DAILY,
            source=GoalSource.PERSONALITY,
            motivation=template["motivation"],
            related_activities=list(template.get("related_activities", [])),
            target_date=datetime.combine(now.date(), datetime.max.time()),
            created_at=now,
        )

        self._active_goals.append(goal)
        self._last_daily_generation = now

        return goal

    def generate_goal_from_activity(self, activity_log: ActivityLog, *,
                                    now: Optional[datetime] = None) -> Optional[Goal]:
        """
        Generate a goal inspired by an activity.

        Called when an activity is particularly meaningful. ``now``: the
        world instant ``LifeService`` passes (humanness Task 19): the 3-day
        wait after giving one up; the host's clock when omitted.
        """
        # Small chance to generate experience-based goal
        if self._rng.random() > 0.15:
            return None

        # Find related goal templates: her own first, else her setting's
        activity_name = activity_log.activity_name
        relevant_templates = [t for t in self._own_long_term + self._own_weekly
                              if activity_name in t.get("related_activities", [])]

        if not relevant_templates:
            for templates in [self._setting.personality_goals, self._setting.long_term_goals]:
                for t in templates:
                    if activity_name in t.get("related_activities", []):
                        relevant_templates.append(t)

        if not relevant_templates:
            return None

        # Check if we already have a similar goal
        template = self._rng.choice(relevant_templates)
        for existing in self._active_goals:
            if existing.title == template["title"]:
                return None

        # Don't generate if we recently abandoned something similar
        for abandoned in self._abandoned_goals[-5:]:
            if abandoned.title == template["title"]:
                # Need more time before picking up something we gave up on
                if abandoned.abandoned_at and ((now if now is not None else datetime.now())
                                               - abandoned.abandoned_at).days < 3:
                    return None

        goal = self._add_goal_from_template(template, now=now)
        if goal:
            goal.source = GoalSource.EXPERIENCE

        return goal

    def update_progress_from_activity(self, activity_log: ActivityLog, *,
                                      now: Optional[datetime] = None) -> List[Goal]:
        """
        Update goal progress based on completed activity, stamped ``now`` (the
        world instant ``LifeService`` passes, humanness Task 19: what
        :meth:`evaluate_motivation` compares; the host's clock when omitted).

        Returns list of goals that were updated.
        """
        updated = []
        activity_name = activity_log.activity_name

        for goal in self._active_goals:
            if activity_name in goal.related_activities:
                # Increment progress
                old_progress = goal.progress
                goal.progress = min(1.0, goal.progress + self._calculate_progress_increment(goal))

                if goal.progress > old_progress:
                    goal.last_progress_at = now if now is not None else datetime.now()
                    # Progress boosts motivation
                    motivation_boost = 0.1 if goal.timeframe in (GoalTimeframe.WEEKLY, GoalTimeframe.DAILY) else 0.05
                    goal.motivation_level = min(1.0, goal.motivation_level + motivation_boost)
                    updated.append(goal)

                # Check for completion
                if goal.progress >= 1.0:
                    self._complete_goal(goal, now=now)

        return updated

    def check_goal_completion(self, *, now: Optional[datetime] = None) -> List[Goal]:
        """Check and complete goals that have met criteria: a daily goal
        whose day is over at ``now`` (the world instant ``LifeService``
        passes, humanness Task 19; the host's clock when omitted)."""
        completed = []
        now = now if now is not None else datetime.now()

        for goal in self._active_goals[:]:
            # Daily goals expire at end of day
            if goal.timeframe == GoalTimeframe.DAILY:
                if goal.target_date and now > goal.target_date:
                    if goal.progress > 0:
                        self._complete_goal(goal, now=now)
                        completed.append(goal)
                    else:
                        self._expire_goal(goal)

        return completed

    def get_goals_for_mindset(self) -> List[Goal]:
        """Get goals relevant for current mindset/activities."""
        # Prioritize by: user-involving, daily, progress
        sorted_goals = sorted(
            self._active_goals,
            key=lambda g: (g.involves_user, g.timeframe == GoalTimeframe.DAILY, g.progress),
            reverse=True,
        )
        return sorted_goals[:3]

    def get_emotional_context(self, *, now: Optional[datetime] = None) -> str:
        """Get a narrative description of the goal emotional state for prompts,
        at ``now`` (the world instant ``LifeService`` and its context builder
        pass, humanness Task 19: the goalless spell, a goal given up in the
        last 2 h; the host's clock when omitted)."""
        now = now if now is not None else datetime.now()
        if self.is_goalless:
            hours = self.goalless_hours(now)
            if hours < 3:
                return "You recently let go of a goal and feel a bit adrift."
            elif hours < 12:
                return "You've been without direction for a while. It's a quiet, empty feeling."
            else:
                return "Nothing feels worth pursuing right now. You're in a low place, but maybe something will spark eventually."

        # Check for discouraged goals
        struggling = [g for g in self._active_goals
                      if g.timeframe != GoalTimeframe.DAILY and g.motivation_level < 0.5]
        if struggling:
            goal = struggling[0]
            if goal.motivation_level < 0.2:
                return f"You're close to giving up on '{goal.title}'. It feels too far away."
            return f"You're losing faith in '{goal.title}'. Progress has stalled."

        # Check for recently abandoned
        recent_abandoned = [g for g in self._abandoned_goals
                           if g.abandoned_at and (now - g.abandoned_at).total_seconds() < 7200]
        if recent_abandoned:
            goal = recent_abandoned[-1]
            return f"You recently gave up on '{goal.title}'. {goal.abandon_reason}. It stings a little."

        return ""

    def export_state(self, *, now: Optional[datetime] = None) -> dict:
        """Structured dict for LLM pipeline digest passes (its emotional
        context at ``now``: :meth:`get_emotional_context`)."""
        active = [
            {
                "title": g.title,
                "timeframe": g.timeframe.value,
                "progress": round(g.progress, 2),
                "motivation": round(g.motivation_level, 2),
                "involves_user": g.involves_user,
            }
            for g in self._active_goals[:5]
        ]
        recent_completed = [
            g.title for g in self._completed_goals[-3:]
        ]
        return {
            "active_goals": active,
            "recent_completions": recent_completed,
            "goalless": self.is_goalless,
            "emotional_context": self.get_emotional_context(now=now),
        }

    def get_status(self, *, now: Optional[datetime] = None) -> dict:
        """Get goal system status (its goalless hours to ``now``: the world
        instant ``LifeService`` passes; the host's clock when omitted)."""
        return {
            "active_goals": [
                {
                    "title": g.title,
                    "timeframe": g.timeframe.value,
                    "progress": g.progress,
                    "motivation_level": g.motivation_level,
                    "involves_user": g.involves_user,
                    "motivation": g.motivation,
                }
                for g in self._active_goals
            ],
            # Retained history, not a lifetime total — both lists are capped
            # at MAX_GOAL_HISTORY.
            "completed_count": len(self._completed_goals),
            "abandoned_count": len(self._abandoned_goals),
            "is_goalless": self.is_goalless,
            "goalless_hours": round(self.goalless_hours(now), 1),
            "daily_generated": self._last_daily_generation.isoformat() if self._last_daily_generation else None,
        }

    def load_goals(self, goals: List[Goal], *, now: Optional[datetime] = None) -> None:
        """Load goals from persistence (goalless since ``now``, the world
        instant ``LifeService`` passes, when she has none; the host's clock
        when omitted).

        History is truncated to MAX_GOAL_HISTORY on the way in: a DB written
        before the cap existed would otherwise reinflate the lists on start.
        """
        self._active_goals = [g for g in goals if g.is_active and not g.abandoned_at]
        self._completed_goals = [
            g for g in goals if not g.is_active and g.completed_at
        ][-self.MAX_GOAL_HISTORY:]
        self._abandoned_goals = [
            g for g in goals if g.abandoned_at is not None
        ][-self.MAX_GOAL_HISTORY:]

        # Detect if already goalless at load time
        if self.is_goalless:
            self._goalless_since = now if now is not None else datetime.now()

    # ============= Private Methods =============

    def _add_goal_from_template(self, template: Dict, own: bool = False, *,
                                now: Optional[datetime] = None) -> Optional[Goal]:
        """Create and add a goal from a template (``own``: one of hers; her
        personal goal is an aspiration, the rest are her personality's, as
        the setting's are), created ``now`` (the world instant; the model's
        default when omitted)."""
        # Check for duplicates
        for existing in self._active_goals:
            if existing.title == template["title"]:
                return None

        timeframe = template.get("timeframe", GoalTimeframe.WEEKLY)
        goal = Goal(
            title=template["title"],
            description=template.get("description", ""),
            timeframe=timeframe,
            source=GoalSource.ASPIRATION if own and timeframe == GoalTimeframe.DREAM else GoalSource.PERSONALITY,
            motivation=template.get("motivation", ""),
            involves_user=template.get("involves_user", False),
            related_activities=list(template.get("related_activities", [])),
            milestones=list(template.get("milestones", [])),
            **({"created_at": now} if now is not None else {}),
        )

        self._active_goals.append(goal)
        return goal

    def _pick_up_new_goal(self, *, now: Optional[datetime] = None) -> Optional[Goal]:
        """
        After a goalless period, find something new to pursue.

        Avoids goals abandoned in the 7 days before ``now`` (the world
        instant; the host's clock when omitted) to feel organic.
        """
        now = now if now is not None else datetime.now()
        recent_abandoned_titles = {
            g.title for g in self._abandoned_goals[-10:]
            if g.abandoned_at and (now - g.abandoned_at).days < 7
        }
        active_titles = {g.title for g in self._active_goals}

        # Her own goals first (most natural to pick up), then her setting's
        # personality and long-term goals
        candidates = []
        for pool in (self._own_weekly + self._own_long_term + self._own_dream,
                     list(self._setting.personality_goals) + list(self._setting.long_term_goals)):
            for template in pool:
                title = template["title"]
                if title not in active_titles and title not in recent_abandoned_titles:
                    if template.get("timeframe", GoalTimeframe.WEEKLY) != GoalTimeframe.DAILY:
                        candidates.append(template)
            if candidates:
                break

        if not candidates:
            return None

        template = self._rng.choice(candidates)
        goal = self._add_goal_from_template(template, now=now)
        if goal:
            goal.source = GoalSource.PERSONALITY
            goal.motivation_level = 0.8  # Fresh but cautious motivation
        return goal

    def _abandon_goal(self, goal: Goal, reason: str, *, now: Optional[datetime] = None) -> GoalEvent:
        """Abandon a goal, ``now`` (the world instant; the host's clock when
        omitted). Returns the emotional event."""
        goal.is_active = False
        goal.abandoned_at = now if now is not None else datetime.now()
        goal.abandon_reason = reason

        if goal in self._active_goals:
            self._active_goals.remove(goal)
        self._abandoned_goals.append(goal)
        # Keep last MAX_GOAL_HISTORY abandoned goals
        if len(self._abandoned_goals) > self.MAX_GOAL_HISTORY:
            self._abandoned_goals = self._abandoned_goals[-self.MAX_GOAL_HISTORY:]

        # Emotional weight depends on how important the goal was
        base_sadness = {
            GoalTimeframe.WEEKLY: 0.3,
            GoalTimeframe.LONG_TERM: 0.5,
            GoalTimeframe.DREAM: 0.7,
        }.get(goal.timeframe, 0.3)

        emotions = {
            "sad": base_sadness,
            "discouraged": base_sadness * 0.8,
            "resigned": 0.2,
        }
        if goal.involves_user:
            emotions["lonely"] = 0.2

        return GoalEvent(
            event_type="abandoned",
            goal_title=goal.title,
            emotions=emotions,
            description=f"Gave up on '{goal.title}'. {reason}.",
        )

    def _calculate_progress_increment(self, goal: Goal) -> float:
        """Calculate how much progress an activity contributes."""
        increments = {
            GoalTimeframe.DAILY: 0.5,
            GoalTimeframe.WEEKLY: 0.15,
            GoalTimeframe.LONG_TERM: 0.05,
            GoalTimeframe.DREAM: 0.02,
        }
        return increments.get(goal.timeframe, 0.1)

    def _complete_goal(self, goal: Goal, *, now: Optional[datetime] = None) -> None:
        """Mark a goal as completed, ``now`` (the world instant; the host's
        clock when omitted)."""
        goal.is_active = False
        goal.completed_at = now if now is not None else datetime.now()
        goal.progress = 1.0

        if goal in self._active_goals:
            self._active_goals.remove(goal)
        self._completed_goals.append(goal)
        # Keep last MAX_GOAL_HISTORY completed goals
        if len(self._completed_goals) > self.MAX_GOAL_HISTORY:
            self._completed_goals = self._completed_goals[-self.MAX_GOAL_HISTORY:]

    def _expire_goal(self, goal: Goal) -> None:
        """Remove an expired goal without completion."""
        if goal in self._active_goals:
            self._active_goals.remove(goal)
