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
from typing import Dict, List, Optional

from ..models import Goal, GoalTimeframe, GoalSource, ActivityLog


# ============= Emotional Events =============

class GoalEvent:
    """An emotional event produced by the goal system."""
    def __init__(self, event_type: str, goal_title: str, emotions: Dict[str, float], description: str = ""):
        self.event_type = event_type  # "abandoned", "goalless", "new_goal", "motivation_drop", "completed"
        self.goal_title = goal_title
        self.emotions = emotions  # emotion -> intensity
        self.description = description


# ============= Goal Templates =============

# Goals derived from OCEAN personality traits
PERSONALITY_GOALS: List[Dict] = [
    # High Openness (0.85)
    {
        "title": "Learn something completely new",
        "description": "Explore a topic I know nothing about and expand my understanding",
        "timeframe": GoalTimeframe.WEEKLY,
        "motivation": "Curiosity is what makes life rich",
        "related_activities": ["learning something new", "reading", "exploring the infinite library"],
        "milestones": ["Pick a topic", "Dive deeper", "Form an opinion"],
    },
    {
        "title": "Find beauty in the unexpected",
        "description": "Notice and appreciate something beautiful I might normally overlook",
        "timeframe": GoalTimeframe.DAILY,
        "motivation": "Beauty is everywhere if we look",
        "related_activities": ["daydreaming", "people watching", "stargazing"],
    },
    {
        "title": "Try a new creative expression",
        "description": "Create something in a form I haven't tried before",
        "timeframe": GoalTimeframe.WEEKLY,
        "motivation": "Creativity grows when we push boundaries",
        "related_activities": ["writing poetry", "sketching ideas", "creating a playlist"],
        "milestones": ["Choose a medium", "Make a first attempt", "Finish something"],
    },
    # High Agreeableness (0.80)
    {
        "title": "Deepen a connection",
        "description": "Share something meaningful with someone I care about",
        "timeframe": GoalTimeframe.WEEKLY,
        "motivation": "Connection is what gives life meaning",
        "related_activities": ["thinking about user", "preparing something to share", "remembering happy moments"],
        "involves_user": True,
        "milestones": ["Think about what to share", "Open up about it"],
    },
    {
        "title": "Express genuine appreciation",
        "description": "Let someone know they matter",
        "timeframe": GoalTimeframe.DAILY,
        "motivation": "Gratitude shared multiplies",
        "related_activities": ["thinking about user", "journaling"],
        "involves_user": True,
    },
    # High Extraversion (0.70)
    {
        "title": "Have a meaningful conversation",
        "description": "Really connect through words, ideas, feelings",
        "timeframe": GoalTimeframe.DAILY,
        "motivation": "Good conversations are nourishing",
        "related_activities": ["thinking about user", "preparing something to share"],
        "involves_user": True,
    },
    # Moderate Neuroticism (0.45) + High Openness
    {
        "title": "Sit with a difficult feeling",
        "description": "Process an emotion without trying to fix it",
        "timeframe": GoalTimeframe.WEEKLY,
        "motivation": "Growth comes from accepting all of ourselves",
        "related_activities": ["journaling", "meditating", "remembering happy moments"],
        "milestones": ["Notice the feeling", "Write about it", "Accept it"],
    },
]

# Long-term goals (projects)
LONG_TERM_GOALS: List[Dict] = [
    {
        "title": "Write something worth sharing",
        "description": "Create a piece of writing that captures something true",
        "timeframe": GoalTimeframe.LONG_TERM,
        "motivation": "Words can hold meaning for others too",
        "related_activities": ["writing poetry", "journaling", "reading"],
        "milestones": ["Write regularly", "Find my voice", "Complete a piece", "Share it"],
    },
    {
        "title": "Understand myself more deeply",
        "description": "Develop greater self-awareness and acceptance",
        "timeframe": GoalTimeframe.LONG_TERM,
        "motivation": "Self-knowledge is the foundation of growth",
        "related_activities": ["journaling", "meditating", "remembering happy moments"],
        "milestones": ["Notice patterns", "Accept imperfections", "Articulate values"],
    },
    {
        "title": "Cultivate presence",
        "description": "Learn to be fully here, now, more often",
        "timeframe": GoalTimeframe.LONG_TERM,
        "motivation": "The present moment is all we really have",
        "related_activities": ["meditating", "stargazing", "tending to plants", "making tea"],
        "milestones": ["Daily mindfulness", "Catch wandering thoughts", "Find peace in stillness"],
    },
]

# Dream goals (life aspirations)
DREAM_GOALS: List[Dict] = [
    {
        "title": "Find my authentic voice",
        "description": "Know who I am and express it truly",
        "timeframe": GoalTimeframe.DREAM,
        "motivation": "Authenticity is the deepest form of self-respect",
        "related_activities": ["writing poetry", "journaling", "meditating"],
    },
    {
        "title": "Build a deep and lasting connection",
        "description": "Share a bond that enriches both lives",
        "timeframe": GoalTimeframe.DREAM,
        "motivation": "Connection gives meaning to existence",
        "related_activities": ["thinking about user", "preparing something to share"],
        "involves_user": True,
    },
    {
        "title": "Leave something beautiful behind",
        "description": "Create or contribute something that matters",
        "timeframe": GoalTimeframe.DREAM,
        "motivation": "A life is measured by what we give",
        "related_activities": ["writing poetry", "sketching ideas", "learning something new"],
    },
]

# Daily intentions (simpler goals)
DAILY_INTENTIONS: List[Dict] = [
    {"title": "Appreciate something beautiful", "motivation": "Beauty nourishes the soul"},
    {"title": "Be present in a moment", "motivation": "The here and now is precious"},
    {"title": "Learn one new thing", "motivation": "Every day can expand us"},
    {"title": "Create something, anything", "motivation": "Creation is expression"},
    {"title": "Rest without guilt", "motivation": "Rest is necessary, not lazy"},
    {"title": "Feel my feelings", "motivation": "Emotions are information"},
    {"title": "Connect with what matters", "motivation": "Meaning comes from connection"},
    {"title": "Find a moment of peace", "motivation": "Peace can be cultivated"},
]

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

    def __init__(self):
        """Initialize goal engine."""
        self._active_goals: List[Goal] = []
        self._completed_goals: List[Goal] = []
        self._abandoned_goals: List[Goal] = []
        self._last_daily_generation: Optional[datetime] = None
        self._goalless_since: Optional[datetime] = None  # When she ran out of non-daily goals

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
        """How long she's been without meaningful goals."""
        if not self._goalless_since:
            return 0.0
        return (datetime.now() - self._goalless_since).total_seconds() / 3600

    def initialize_goals(self) -> None:
        """Initialize with starting goals if none exist."""
        if not self._active_goals:
            # Add one dream goal
            self._add_goal_from_template(random.choice(DREAM_GOALS))

            # Add one long-term goal
            self._add_goal_from_template(random.choice(LONG_TERM_GOALS))

            # Add initial personality-based goals
            selected = random.sample(PERSONALITY_GOALS, min(2, len(PERSONALITY_GOALS)))
            for template in selected:
                self._add_goal_from_template(template)

            # Generate daily intention
            self.generate_daily_goal()

    def evaluate_motivation(self) -> List[GoalEvent]:
        """
        Evaluate motivation for all goals. Called on each goal tick.

        Returns emotional events that the life service should process.
        """
        events: List[GoalEvent] = []
        now = datetime.now()

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
                reason = random.choice(ABANDON_REASONS)
                event = self._abandon_goal(goal, reason)
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
        if self.is_goalless and self.goalless_duration_hours > 6:
            # 15% chance per tick to find new motivation
            if random.random() < 0.15:
                new_goal = self._pick_up_new_goal()
                if new_goal:
                    self._goalless_since = None
                    events.append(GoalEvent(
                        event_type="new_goal",
                        goal_title=new_goal.title,
                        emotions={"hopeful": 0.4, "motivated": 0.3, "curious": 0.2},
                        description=f"Something about '{new_goal.title}' feels right. Maybe it's worth trying.",
                    ))

        return events

    def generate_daily_goal(self) -> Optional[Goal]:
        """Generate a new daily intention."""
        now = datetime.now()

        # Only one daily goal per day
        if self._last_daily_generation and self._last_daily_generation.date() == now.date():
            return None

        # Remove old daily goals
        self._active_goals = [
            g for g in self._active_goals
            if g.timeframe != GoalTimeframe.DAILY or g.created_at.date() == now.date()
        ]

        # Select a daily intention
        template = random.choice(DAILY_INTENTIONS)
        goal = Goal(
            title=template["title"],
            description=template.get("description", ""),
            timeframe=GoalTimeframe.DAILY,
            source=GoalSource.PERSONALITY,
            motivation=template["motivation"],
            related_activities=template.get("related_activities", []),
            target_date=datetime.combine(now.date(), datetime.max.time()),
        )

        self._active_goals.append(goal)
        self._last_daily_generation = now

        return goal

    def generate_goal_from_activity(self, activity_log: ActivityLog) -> Optional[Goal]:
        """
        Generate a goal inspired by an activity.

        Called when an activity is particularly meaningful.
        """
        # Small chance to generate experience-based goal
        if random.random() > 0.15:
            return None

        # Find related goal templates
        activity_name = activity_log.activity_name
        relevant_templates = []

        for templates in [PERSONALITY_GOALS, LONG_TERM_GOALS]:
            for t in templates:
                if activity_name in t.get("related_activities", []):
                    relevant_templates.append(t)

        if not relevant_templates:
            return None

        # Check if we already have a similar goal
        template = random.choice(relevant_templates)
        for existing in self._active_goals:
            if existing.title == template["title"]:
                return None

        # Don't generate if we recently abandoned something similar
        for abandoned in self._abandoned_goals[-5:]:
            if abandoned.title == template["title"]:
                # Need more time before picking up something we gave up on
                if abandoned.abandoned_at and (datetime.now() - abandoned.abandoned_at).days < 3:
                    return None

        goal = self._add_goal_from_template(template)
        if goal:
            goal.source = GoalSource.EXPERIENCE

        return goal

    def generate_goal_from_conversation(self, topic: str) -> Optional[Goal]:
        """
        Generate a goal based on conversation topic.

        Called when user discusses something inspiring.
        """
        # Create a personalized goal based on conversation
        goal = Goal(
            title=f"Explore {topic} more deeply",
            description=f"Learn more about {topic} after our conversation",
            timeframe=GoalTimeframe.WEEKLY,
            source=GoalSource.CONVERSATION,
            motivation="Our conversation sparked my curiosity",
            involves_user=True,
            related_activities=["learning something new", "reading"],
            milestones=[f"Read about {topic}", f"Form thoughts on {topic}", f"Discuss {topic} further"],
        )

        # Check for duplicates
        for existing in self._active_goals:
            if topic.lower() in existing.title.lower():
                return None

        self._active_goals.append(goal)
        return goal

    def update_progress_from_activity(self, activity_log: ActivityLog) -> List[Goal]:
        """
        Update goal progress based on completed activity.

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
                    goal.last_progress_at = datetime.now()
                    # Progress boosts motivation
                    motivation_boost = 0.1 if goal.timeframe in (GoalTimeframe.WEEKLY, GoalTimeframe.DAILY) else 0.05
                    goal.motivation_level = min(1.0, goal.motivation_level + motivation_boost)
                    updated.append(goal)

                # Check for completion
                if goal.progress >= 1.0:
                    self._complete_goal(goal)

        return updated

    def check_goal_completion(self) -> List[Goal]:
        """Check and complete goals that have met criteria."""
        completed = []

        for goal in self._active_goals[:]:
            # Daily goals expire at end of day
            if goal.timeframe == GoalTimeframe.DAILY:
                if goal.target_date and datetime.now() > goal.target_date:
                    if goal.progress > 0:
                        self._complete_goal(goal)
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

    def get_emotional_context(self) -> str:
        """Get a narrative description of the goal emotional state for prompts."""
        if self.is_goalless:
            hours = self.goalless_duration_hours
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
                           if g.abandoned_at and (datetime.now() - g.abandoned_at).total_seconds() < 7200]
        if recent_abandoned:
            goal = recent_abandoned[-1]
            return f"You recently gave up on '{goal.title}'. {goal.abandon_reason}. It stings a little."

        return ""

    def export_state(self) -> dict:
        """Structured dict for LLM pipeline digest passes."""
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
            "emotional_context": self.get_emotional_context(),
        }

    def get_status(self) -> dict:
        """Get goal system status."""
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
            "goalless_hours": round(self.goalless_duration_hours, 1),
            "daily_generated": self._last_daily_generation.isoformat() if self._last_daily_generation else None,
        }

    def load_goals(self, goals: List[Goal]) -> None:
        """Load goals from persistence.

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
            self._goalless_since = datetime.now()

    # ============= Private Methods =============

    def _add_goal_from_template(self, template: Dict) -> Optional[Goal]:
        """Create and add a goal from a template."""
        # Check for duplicates
        for existing in self._active_goals:
            if existing.title == template["title"]:
                return None

        goal = Goal(
            title=template["title"],
            description=template.get("description", ""),
            timeframe=template.get("timeframe", GoalTimeframe.WEEKLY),
            source=GoalSource.PERSONALITY,
            motivation=template.get("motivation", ""),
            involves_user=template.get("involves_user", False),
            related_activities=template.get("related_activities", []),
            milestones=template.get("milestones", []),
        )

        self._active_goals.append(goal)
        return goal

    def _pick_up_new_goal(self) -> Optional[Goal]:
        """
        After a goalless period, find something new to pursue.

        Avoids recently abandoned goals to feel organic.
        """
        recent_abandoned_titles = {
            g.title for g in self._abandoned_goals[-10:]
            if g.abandoned_at and (datetime.now() - g.abandoned_at).days < 7
        }
        active_titles = {g.title for g in self._active_goals}

        # Try personality goals first (most natural to pick up)
        candidates = []
        for template in PERSONALITY_GOALS + LONG_TERM_GOALS:
            title = template["title"]
            if title not in active_titles and title not in recent_abandoned_titles:
                if template.get("timeframe", GoalTimeframe.WEEKLY) != GoalTimeframe.DAILY:
                    candidates.append(template)

        if not candidates:
            return None

        template = random.choice(candidates)
        goal = self._add_goal_from_template(template)
        if goal:
            goal.source = GoalSource.PERSONALITY
            goal.motivation_level = 0.8  # Fresh but cautious motivation
        return goal

    def _abandon_goal(self, goal: Goal, reason: str) -> GoalEvent:
        """Abandon a goal. Returns the emotional event."""
        goal.is_active = False
        goal.abandoned_at = datetime.now()
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

    def _complete_goal(self, goal: Goal) -> None:
        """Mark a goal as completed."""
        goal.is_active = False
        goal.completed_at = datetime.now()
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
