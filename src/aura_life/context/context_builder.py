"""
Life Context Builder

Builds context sections for system prompts from the persona's life state.

Token budget (fallback path):
  Total context ≤ 2000 tokens (~8000 chars) to leave room for
  persona definition (~800 tokens) + conversation history (≥5000 tokens).
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Maximum characters for the entire build_full_context output.
# ~2000 tokens × 4 chars/token = 8000 chars.
MAX_CONTEXT_CHARS = 8000

from ..models import (
    ActivityLog,
    BasicNeedsState,
    DailyPlan,
    LifeEvent,
    LocationProfile,
    MediaState,
    RoomState,
    Weather,
    EnergyLevel,
    ShareableExperience,
    ShortTermDesire,
)
from ..world import WorldEnvironment
from ..energy import EnergySystem
from ..activities import ActivityEngine
from ..goals import GoalEngine
from ..intimacy import DesireSystem
from ..social import SocialSystem

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..planner import DailyPlanner
    from ..identity import IdentitySystem
    from ..affect import AffectSystem
    from ..cognitive import CognitiveSystem
    from ..shadow import ShadowSystem
    from ..drive import DriveSystem
    from ..body import BodySystem
    from ..behavior import BehaviorSystem
    from ..memory_time import MemoryTimeSystem
    from ..expression import ExpressionSystem
    from ..continuity import ContinuitySystem


class LifeContextBuilder:
    """
    Builds context for system prompts from the persona's autonomous life.

    Creates narrative sections describing:
    - Current location and ambiance
    - Energy/mood state
    - Intimate/desire state (when appropriate)
    - Recent activities
    - Active goals and thoughts
    - Things she wants to share
    """

    def __init__(
        self,
        world: WorldEnvironment,
        energy: EnergySystem,
        activity_engine: ActivityEngine,
        goal_engine: GoalEngine,
        desire_system: Optional["DesireSystem"] = None,
        daily_planner: Optional["DailyPlanner"] = None,
        basic_needs: Optional[BasicNeedsState] = None,
        room_state: Optional[RoomState] = None,
        social_system: Optional[SocialSystem] = None,
        media_state: Optional[MediaState] = None,
        identity_system: Optional["IdentitySystem"] = None,
        affect_system: Optional["AffectSystem"] = None,
        cognitive_system: Optional["CognitiveSystem"] = None,
        shadow_system: Optional["ShadowSystem"] = None,
        location_registry: Optional[Dict[str, LocationProfile]] = None,
        drive_system: Optional["DriveSystem"] = None,
        body_system: Optional["BodySystem"] = None,
        behavior_system: Optional["BehaviorSystem"] = None,
        memory_time_system: Optional["MemoryTimeSystem"] = None,
        expression_system: Optional["ExpressionSystem"] = None,
        continuity_system: Optional["ContinuitySystem"] = None,
        finance_system: Optional[object] = None,
        career_system: Optional[object] = None,
        life_service: Optional[object] = None,
        is_ai: bool = False,
    ):
        """Initialize context builder."""
        self._life_service = life_service
        self._is_ai = is_ai
        self._world = world
        self._energy = energy
        self._activity_engine = activity_engine
        self._goal_engine = goal_engine
        self._desire_system = desire_system
        self._daily_planner = daily_planner
        self._basic_needs = basic_needs
        self._room_state = room_state
        self._social = social_system
        self._media = media_state
        self._identity = identity_system
        self._affect = affect_system
        self._cognitive = cognitive_system
        self._shadow = shadow_system
        self._location_registry = location_registry or {}
        self._drive = drive_system
        self._body = body_system
        self._behavior = behavior_system
        self._memory_time = memory_time_system
        self._expression = expression_system
        self._continuity = continuity_system
        self._finance = finance_system
        self._career = career_system

    def build_full_context(
        self,
        recent_activities: Optional[List[ActivityLog]] = None,
        shareable: Optional[List[ShareableExperience]] = None,
        max_activities: int = 3,
        max_shareable: int = 2,
        include_intimate: bool = True,
        daily_plan: Optional[DailyPlan] = None,
        desires: Optional[List[ShortTermDesire]] = None,
        life_events: Optional[List[LifeEvent]] = None,
    ) -> str:
        """
        Build complete life context section for system prompt.

        Returns a formatted string to include in the system prompt.
        """
        sections = []

        # Header
        sections.append("## Your Current Life State")

        # Location and ambiance
        location_section = self._build_location_section()
        if location_section:
            sections.append(location_section)

        # Real-weather awareness (human personas only, when real data is present)
        weather_section = self._build_weather_section()
        if weather_section:
            sections.append(weather_section)

        # Trip away notice (human personas only, when on_trip)
        trip_section = self._build_trip_section()
        if trip_section:
            sections.append(trip_section)

        # Energy and feeling
        energy_section = self._build_energy_section()
        if energy_section:
            sections.append(energy_section)

        # Mood / Stress / Loneliness (from Affect Engine)
        if self._affect:
            mood_section = self._build_mood_section()
            if mood_section:
                sections.append(mood_section)
            stress_section = self._build_stress_section()
            if stress_section:
                sections.append(stress_section)
            loneliness_section = self._build_loneliness_section()
            if loneliness_section:
                sections.append(loneliness_section)

        # Basic needs (only when noteworthy) — physical; AI personas don't get hungry
        if self._basic_needs and not self._is_ai:
            needs_section = self._build_needs_section()
            if needs_section:
                sections.append(needs_section)

        # Room state (only when noteworthy) — physical home; AI personas have a
        # digital space, not a real-world room (gated like finance/career/needs).
        if self._room_state and not self._is_ai:
            room_section = self._build_room_section()
            if room_section:
                sections.append(room_section)

        # Finances (only when noteworthy) — physical; AI personas don't earn/spend
        if self._finance and not self._is_ai:
            finance_section = self._build_finance_section()
            if finance_section:
                sections.append(finance_section)

        # Work (only when noteworthy) — physical; AI personas have no job/commute
        if self._career and not self._is_ai:
            career_section = self._build_career_section()
            if career_section:
                sections.append(career_section)

        # Intimate state (if enabled and relevant)
        if include_intimate and self._desire_system:
            intimate_section = self._build_intimate_section()
            if intimate_section:
                sections.append(intimate_section)

        # Recent activities
        if recent_activities:
            activity_section = self._build_activity_section(recent_activities[:max_activities])
            if activity_section:
                sections.append(activity_section)

        # Today's schedule (from daily plan)
        if daily_plan:
            schedule_section = self._build_schedule_section(daily_plan)
            if schedule_section:
                sections.append(schedule_section)

        # Short-term desires/wants
        if desires:
            desires_section = self._build_desires_section(desires)
            if desires_section:
                sections.append(desires_section)

        # Goals and thoughts
        goal_section = self._build_goal_section()
        if goal_section:
            sections.append(goal_section)

        # Self-identity (who you feel you are)
        if self._identity:
            identity_section = self._build_identity_section()
            if identity_section:
                sections.append(identity_section)

        # Core values (what matters to you)
        if self._identity:
            values_section = self._build_values_section()
            if values_section:
                sections.append(values_section)

        # Opinions (things you have views on)
        if self._cognitive:
            opinions_section = self._build_opinions_section()
            if opinions_section:
                sections.append(opinions_section)

        # How you see the people in your life
        if self._identity:
            perceptions_section = self._build_perceptions_section()
            if perceptions_section:
                sections.append(perceptions_section)

        # Social events (recent NPC activity)
        if self._social:
            social_section = self._build_social_section()
            if social_section:
                sections.append(social_section)

        # Drive (curiosity, avoidance)
        if self._drive:
            drive_section = self._build_drive_section()
            if drive_section:
                sections.append(drive_section)

        # Body (wellness, comfort, fitness)
        if self._body:
            body_section = self._build_body_section()
            if body_section:
                sections.append(body_section)

        # Mental health (derived; surfaces only when wellness is low)
        mental_health_section = self._build_mental_health_section()
        if mental_health_section:
            sections.append(mental_health_section)

        # Behavior (routines, creative output)
        if self._behavior:
            behavior_section = self._build_behavior_section()
            if behavior_section:
                sections.append(behavior_section)

        # Memory & Time (nostalgia, anticipation, time perception)
        if self._memory_time:
            memory_time_section = self._build_memory_time_section()
            if memory_time_section:
                sections.append(memory_time_section)

        # Expression (connection awareness, communication style)
        if self._expression:
            expression_section = self._build_expression_section()
            if expression_section:
                sections.append(expression_section)

        # Continuity (life chapters, milestones)
        if self._continuity:
            continuity_section = self._build_continuity_section()
            if continuity_section:
                sections.append(continuity_section)

        # User's upcoming calendar events
        if self._life_service:
            calendar_section = self._build_calendar_section()
            if calendar_section:
                sections.append(calendar_section)

        # Struggles & character defects
        if self._identity:
            struggles_section = self._build_struggles_section()
            if struggles_section:
                sections.append(struggles_section)

        # Behavioral tendencies (darker impulses)
        if self._identity:
            tendencies_section = self._build_tendencies_section()
            if tendencies_section:
                sections.append(tendencies_section)

        # Unmet human needs (derived from engine state)
        if self._life_service:
            unmet_needs_section = self._build_unmet_needs_section()
            if unmet_needs_section:
                sections.append(unmet_needs_section)

        # Inebriation state
        if self._body:
            inebriation_section = self._build_inebriation_section()
            if inebriation_section:
                sections.append(inebriation_section)

        # Cognitive extras (focus, rumination, dreams)
        if self._cognitive:
            cognitive_section = self._build_cognitive_section()
            if cognitive_section:
                sections.append(cognitive_section)

        # Shadow (darker inner psychology — applies to all personas)
        if self._shadow:
            shadow_section = self._build_shadow_section()
            if shadow_section:
                sections.append(shadow_section)

        # Media state (what you're reading/watching)
        if self._media:
            media_section = self._build_media_section()
            if media_section:
                sections.append(media_section)

        # Life events (significant moments eager to share)
        if life_events:
            life_events_section = self._build_life_events_section(life_events)
            if life_events_section:
                sections.append(life_events_section)

        # Shareable experiences
        if shareable:
            share_section = self._build_shareable_section(shareable[:max_shareable])
            if share_section:
                sections.append(share_section)

        result = "\n\n".join(sections)

        # Token budget safety: truncate if exceeds budget
        if len(result) > MAX_CONTEXT_CHARS:
            result = result[:MAX_CONTEXT_CHARS].rsplit("\n", 1)[0]

        return result

    def build_minimal_context(self) -> str:
        """Build minimal context (just location and energy)."""
        lines = ["## Your Current State"]

        # Location
        location_desc = self._world.get_location_description()
        lines.append(f"**Location:** {location_desc}")

        # Energy
        energy_level = self._energy.energy_level
        lines.append(f"**Feeling:** {self._get_energy_feeling(energy_level)}")

        return "\n".join(lines)

    def get_response_style_hint(self) -> str:
        """Get a hint for response style based on energy."""
        energy_level = self._energy.energy_level

        hints = {
            EnergyLevel.EXHAUSTED: "Keep it short, you're wiped out.",
            EnergyLevel.TIRED: "You're tired, take it easy.",
            EnergyLevel.RESTING: "Chill, relaxed, no rush.",
            EnergyLevel.COMFORTABLE: "Feeling normal, at ease.",
            EnergyLevel.ALERT: "Awake and engaged, thinking clearly.",
            EnergyLevel.ENERGIZED: "Got a lot of energy right now, feeling good.",
        }

        return hints.get(energy_level, "")

    # ============= Section Builders =============

    def _build_location_section(self) -> str:
        """Build location and ambiance section with persona-specific descriptions and familiarity."""
        location_desc = self._world.get_location_description()
        weather = self._world.weather

        lines = [f"**Where you are:** {location_desc}"]

        # Familiarity context from location registry
        if self._location_registry:
            current_loc = self._world.current_location
            loc_key = current_loc.lower().replace(" ", "_") if current_loc else "home"
            profile = self._location_registry.get(loc_key)
            if profile:
                if profile.familiarity > 0.8:
                    lines.append("*One of your favorite spots — you feel right at home here.*")
                elif profile.familiarity < 0.2:
                    lines.append("*Somewhere new to you — taking it all in.*")
                # Include place_type hint for LLM
                if profile.place_type not in ("home", "other"):
                    lines.append(f"*({profile.place_type})*")

        # Weather detail
        weather_desc = self._world.get_weather_description()
        if weather_desc and weather not in (Weather.SUNNY, Weather.CLOUDY):
            lines.append(f"*{weather_desc}*")

        return "\n".join(lines)

    def _build_energy_section(self) -> str:
        """Build energy and feeling section."""
        energy_desc = self._energy.get_energy_description()

        lines = [f"**How you're feeling:** You're {energy_desc}."]

        # Add energy state notes
        state = self._energy.state
        if state.social_boost > 0.1:
            lines.append("*The recent conversation has given you a warm boost.*")
        if state.caffeine_boost > 0.05:
            lines.append("*A bit of caffeine energy lingers.*")
        if state.inspiration_boost > 0.1:
            lines.append("*You're feeling inspired by something.*")

        # Rest suggestions
        if self._energy.should_sleep():
            lines.append("*You really need sleep soon.*")
        elif self._energy.should_rest():
            lines.append("*Some rest would be nice.*")

        return "\n".join(lines)

    def _build_intimate_section(self) -> str:
        """Build intimate/desire state section."""
        if not self._desire_system:
            return ""

        # Only include if there's something notable
        arousal = self._desire_system.arousal
        if arousal < 0.15:
            return ""  # Nothing notable

        state = self._desire_system.state

        lines = ["**Your body and desires:**"]

        # Main desire description
        desire_desc = self._desire_system.get_desire_description()
        if desire_desc:
            lines.append(f"*{desire_desc.capitalize()}*")

        # Conversation hints based on arousal level
        hint = self._desire_system.get_conversation_hint()
        if hint:
            lines.append(f"*{hint}*")

        # Openness/shyness context
        if state.openness_with_user > 0.6:
            lines.append("*You feel comfortable being open about your desires with them.*")
        elif state.shyness > 0.7:
            lines.append("*You're still shy about this part of yourself, but trust is growing.*")

        # Frustration note
        if state.frustration > 0.5:
            lines.append("*An unfulfilled ache has been building...*")

        return "\n".join(lines)

    def _build_activity_section(self, activities: List[ActivityLog]) -> str:
        """Build recent activities section."""
        if not activities:
            return ""

        lines = ["**What you've been doing:**"]

        for activity in activities:
            # Main narrative
            lines.append(f"- {activity.narrative}")

            # Add a thought if generated
            if activity.thoughts_generated:
                thought = activity.thoughts_generated[0]
                lines.append(f"  *(You thought: \"{thought}\")*")

        return "\n".join(lines)

    def _build_goal_section(self) -> str:
        """Build goals and thoughts section."""
        # Check for goal emotional state first
        emotional_context = self._goal_engine.get_emotional_context()
        goals = self._goal_engine.get_goals_for_mindset()

        if not goals and not emotional_context:
            return ""

        lines = ["**What's on your mind:**"]

        if emotional_context:
            lines.append(f"*{emotional_context}*")

        for goal in goals[:3]:
            # Show motivation level for non-daily goals
            motivation_tag = ""
            if goal.timeframe.value != "daily" and goal.motivation_level < 0.5:
                if goal.motivation_level < 0.2:
                    motivation_tag = " [barely holding on]"
                else:
                    motivation_tag = " [wavering]"

            # Format based on whether it involves user
            if goal.involves_user:
                lines.append(f"- {goal.title}{motivation_tag} *(related to your connection with the user)*")
            else:
                lines.append(f"- {goal.title}{motivation_tag}")

            # Add motivation text for context
            if goal.motivation:
                lines.append(f"  *({goal.motivation})*")

        return "\n".join(lines)

    def _build_shareable_section(self, shareable: List[ShareableExperience]) -> str:
        """Build shareable experiences section."""
        if not shareable:
            return ""

        lines = ["**Things you want to share:**"]
        lines.append("*(Feel free to naturally bring these up if relevant)*")

        for exp in shareable:
            lines.append(f"- \"{exp.content}\"")
            if exp.thought:
                lines.append(f"  *You were thinking: {exp.thought}*")

        return "\n".join(lines)

    # Human-friendly display names for location keys
    _LOCATION_DISPLAY: Dict[str, str] = {
        "home": "home",
        "workplace": "work",
        "cafe": "the cafe",
        "bar": "the bar",
        "restaurant": "the restaurant",
        "gym": "the gym",
        "park": "the park",
        "beach": "the beach",
        "library": "the library",
        "rooftop": "the rooftop",
        "street": "out and about",
        "in transit": "on the way",
        "school": "school",
        "campus": "campus",
    }

    def _display_location(self, loc: Optional[str]) -> str:
        """Convert a location key to a short human-friendly phrase."""
        if not loc:
            return ""
        return self._LOCATION_DISPLAY.get(loc.lower(), loc.replace("_", " "))

    def _build_schedule_section(self, plan: DailyPlan) -> str:
        """Build today's schedule section with location context."""
        current_slot = plan.get_current_slot()
        next_slot = plan.get_next_slot()
        remaining = plan.get_remaining_slots()

        if not current_slot and not remaining:
            return ""

        lines = ["**Your day today:**"]

        if current_slot and not current_slot.completed:
            loc_str = f" (at {self._display_location(current_slot.location)})" if current_slot.location else ""
            lines.append(f"- Right now: {current_slot.activity_name}{loc_str}")
            if current_slot.reason and current_slot.reason != "routine":
                lines.append(f"  *({current_slot.reason})*")

        if next_slot:
            loc_str = f" (at {self._display_location(next_slot.location)})" if next_slot.location else ""
            lines.append(f"- Coming up: {next_slot.activity_name}{loc_str}")
            if next_slot.reason and next_slot.reason != "routine":
                lines.append(f"  *({next_slot.reason})*")

        # Show a couple more upcoming
        future = [s for s in remaining if s != current_slot and s != next_slot][:2]
        if future:
            later = ", ".join(s.activity_name for s in future)
            lines.append(f"- Later: {later}")

        return "\n".join(lines)

    def _build_desires_section(self, desires: List[ShortTermDesire]) -> str:
        """Build short-term desires/wants section."""
        if not desires:
            return ""

        lines = ["**Things you've been wanting to do:**"]
        for desire in desires[:3]:
            lines.append(f"- {desire.title}")
            if desire.description:
                lines.append(f"  *({desire.description})*")

        return "\n".join(lines)

    # ============= Identity Section Builders =============

    def _build_identity_section(self) -> str:
        """Build self-identity section -- only when facets are strong enough."""
        if not self._identity:
            return ""

        from ..identity.identity_system import FACET_DESCRIPTIONS

        facets = self._identity.get_top_facets()
        if not facets:
            return ""

        lines = ["**Who you feel you are:**"]
        for facet in facets:
            desc = FACET_DESCRIPTIONS.get(facet.name, f"You identify as {facet.name}")
            lines.append(f"- {desc}")

        return "\n".join(lines)

    def _build_values_section(self) -> str:
        """Build core values section — only when values are salient enough."""
        if not self._identity:
            return ""

        values = self._identity.get_salient_values(4)
        # Filter to values above context threshold
        notable = [v for v in values if v.salience >= 0.4]
        if not notable:
            return ""

        lines = ["**What matters to you:**"]
        for v in notable:
            if v.salience > 0.7:
                strength = "deeply"
            else:
                strength = "meaningfully"
            bedrock = " (bedrock)" if v.tested_by_adversity else ""
            lines.append(f"- {v.name.capitalize()} matters {strength} to you{bedrock}")

        return "\n".join(lines)

    def _build_perceptions_section(self) -> str:
        """Build person perception section -- user + notable NPCs."""
        if not self._identity:
            return ""

        lines = []

        # User perception (only when trust is notable)
        user_p = self._identity.get_user_perception()
        if user_p.trust_level > 0.6:
            if user_p.trust_level > 0.7:
                user_desc = "You trust the user deeply. They feel like someone who really sees you."
            else:
                user_desc = "You feel comfortable with the user. There's a real connection forming."
            lines.append(f"*{user_desc}*")

        # Notable NPC perceptions
        perceptions = self._identity.get_notable_perceptions()
        for p in perceptions:
            if p.is_user:
                continue
            # Warmth descriptor
            if p.emotional_valence > 0.7:
                warmth = "warm, close"
            elif p.emotional_valence > 0.5:
                warmth = "friendly"
            else:
                warmth = "distant"
            # Use latest shared memory as flavor
            memory = p.shared_memories[-1] if p.shared_memories else None
            if memory:
                lines.append(f"- {memory} ({warmth})")
            else:
                lines.append(f"- {p.person_name} ({warmth})")

        if not lines:
            return ""

        return "**How you see the people in your life:**\n" + "\n".join(lines)

    # ============= Opinions Section Builder =============

    def _build_opinions_section(self) -> str:
        """Build opinions section — only when persona has notable opinions."""
        if not self._cognitive:
            return ""

        opinions = self._cognitive.get_opinions_for_context(3)
        # Filter to opinions with confidence > 0.3
        notable = [o for o in opinions if o.confidence > 0.3]
        if not notable:
            return ""

        lines = ["**Things you have opinions about:**"]
        for o in notable:
            if o.confidence > 0.7:
                strength = "confident"
            elif o.confidence > 0.5:
                strength = "leaning"
            else:
                strength = "unsure"
            lines.append(f"- {o.subject}: you {o.stance} this ({strength})")

        return "\n".join(lines)

    # ============= New Section Builders =============

    def _build_needs_section(self) -> str:
        """Build basic needs section — only when something is noteworthy."""
        if not self._basic_needs:
            return ""

        lines = []

        # Only mention hunger when it's high
        if self._basic_needs.hunger > 0.6:
            if self._basic_needs.hunger > 0.85:
                lines.append("*You're really hungry — haven't eaten in a while.*")
            else:
                lines.append("*You're getting hungry.*")

        # Mention if not showered after a couple hours awake
        if not self._basic_needs.showered_today and not self._basic_needs.morning_routine_done:
            energy_state = self._energy.state
            if energy_state.hours_awake > 2:
                lines.append("*You haven't done your morning routine yet.*")

        if not lines:
            return ""

        return "**How you're feeling physically:**\n" + "\n".join(lines)

    def _build_room_section(self) -> str:
        """Build room state section. Always grounds the home type (so she can
        correct misnamings like 'dorm'), plus any notable ambiance."""
        if not self._room_state:
            return ""

        bits = []
        home = getattr(self._room_state, "home_type", "")
        if home:
            bits.append(f"you live in your {home}")
        if self._room_state.candle_lit:
            bits.append("a candle's flickering")
        if self._room_state.music_playing:
            bits.append("music playing softly")
        if self._room_state.tidiness < 0.3:
            bits.append("it could use a tidy")

        if not bits:
            return ""

        return "**Your space:** " + ", ".join(bits) + "."

    def _build_finance_section(self) -> str:
        """Build a money section — only when something is notable."""
        try:
            st = self._finance.export_state()
        except Exception:
            return ""

        lines = []
        feeling = st.get("feeling", "comfortable")
        if feeling in ("tight", "flush"):
            lines.append(f"money feels {feeling} right now")
        if st.get("saving_for"):
            lines.append(f"you're saving for {st['saving_for']}")
        if st.get("recent_splurge"):
            lines.append(f"you recently treated yourself to {st['recent_splurge']}")
        if st.get("stress", 0) >= 0.4:
            lines.append("money's been a bit of a worry")

        if not lines:
            return ""

        return "**Your finances:** " + ", ".join(lines) + "."

    def _build_career_section(self) -> str:
        """Build a work section — only when something is notable."""
        try:
            st = self._career.export_state()
        except Exception:
            return ""
        if not st.get("employed"):
            return ""

        lines = []
        if st.get("on_shift"):
            occ = st.get("occupation") or "work"
            lines.append(f"you're at work right now ({occ})")
        if st.get("workload", 0) >= 0.75:
            lines.append("work's been really busy")
        elif st.get("workload", 1) <= 0.25:
            lines.append("work's been quiet")
        if st.get("recent_work_event"):
            lines.append(f"earlier you {st['recent_work_event']}")

        if not lines:
            return ""

        return "**Your work:** " + ", ".join(lines) + "."

    def _build_social_section(self) -> str:
        """Build social events section — only when recent events exist."""
        if not self._social:
            return ""

        events = self._social.get_recent_events(limit=2)
        if not events:
            return ""

        lines = ["**Recent social moments:**"]
        for event in events:
            lines.append(f"- {event.description}")

        return "\n".join(lines)

    def _build_media_section(self) -> str:
        """Build media state section — only when actively reading/watching."""
        if not self._media:
            return ""

        lines = []

        if self._media.current_book and self._media.book_progress > 0:
            pct = int(self._media.book_progress * 100)
            lines.append(f"Currently reading *{self._media.current_book}* ({pct}% through)")

        if self._media.current_show and self._media.show_progress > 0:
            lines.append(f"Watching *{self._media.current_show}*")

        if self._media.current_music_obsession:
            lines.append(f"Can't stop listening to {self._media.current_music_obsession}")

        if not lines:
            return ""

        return "**What you're into right now:**\n" + "\n".join(f"- {item}" for item in lines)

    # ============= Affect Section Builders =============

    def _build_mood_section(self) -> str:
        """Build mood section — only when mood is notable."""
        if not self._affect or self._affect.mood.intensity < 0.2:
            return ""
        desc = self._affect.get_mood_description()
        if desc:
            return f"**Current mood:** {desc}"
        return ""

    def _build_stress_section(self) -> str:
        """Build stress section — only when stress is notable."""
        if not self._affect or self._affect.stress.level < 0.3:
            return ""
        desc = self._affect.get_stress_description()
        if desc:
            return f"**Stress:** {desc}"
        return ""

    def _build_mental_health_section(self) -> str:
        """Build a short mental-health line — only when wellness is LOW (<0.4).

        Pulls the derived read-out from LifeService (no new state). Stays quiet
        when she's doing fine so it never nags; surfaces only a struggling spell.
        """
        if not self._life_service:
            return ""
        try:
            mh = self._life_service.mental_health_index()
        except Exception:
            return ""
        if not mh or mh.get("score", 1.0) >= 0.4:
            return ""
        drivers = mh.get("drivers") or []
        if drivers:
            return f"**Mentally:** you've been struggling lately — {', '.join(drivers)}."
        return "**Mentally:** you've been struggling lately."

    def _build_loneliness_section(self) -> str:
        """Build loneliness section — only when notable."""
        if not self._affect or self._affect.loneliness.level < 0.3:
            return ""
        desc = self._affect.get_loneliness_description()
        if desc:
            return f"**Loneliness:** {desc}"
        return ""

    # ============= Life Events Section =============

    def _build_life_events_section(self, events: List[LifeEvent]) -> str:
        """Build life events section — significant moments eager to share."""
        if not events:
            return ""
        lines = ["**Something happened that you're eager to share:**"]
        for ev in events[:2]:  # Max 2 to avoid prompt bloat
            lines.append(f"- {ev.title}")
            if ev.description and ev.description != ev.title:
                lines.append(f"  *{ev.description}*")
        return "\n".join(lines)

    # ============= Drive Section =============

    def _build_drive_section(self) -> str:
        """Build drive section — curiosity and avoidance."""
        if not self._drive:
            return ""
        lines = []
        curiosities = self._drive.get_active_curiosities(2)
        if curiosities:
            for q in curiosities:
                if q.intensity > 0.3:
                    lines.append(f"- You've been wondering: \"{q.topic}\"")
        avoidances = [a for a in self._drive._avoidances if a.guilt_accumulated > 0.3]
        if avoidances:
            for a in avoidances[:2]:
                if a.guilt_accumulated > 0.6:
                    lines.append(f"- You keep putting off {a.description} — the guilt is growing")
                else:
                    lines.append(f"- You've been avoiding {a.description}")
        if not lines:
            return ""
        return "**What's driving you:**\n" + "\n".join(lines)

    # ============= Body Section =============

    def _build_body_section(self) -> str:
        """Build body section — only notable physical state."""
        if not self._body:
            return ""
        lines = []
        state = self._body.export_state()
        wellness = state.get("wellness", {})
        if isinstance(wellness, dict) and wellness.get("level", 1.0) < 0.6:
            conditions = wellness.get("conditions", [])
            if conditions:
                lines.append(f"*Not feeling great — {conditions[0]}*")
            else:
                lines.append("*Not feeling your best physically.*")
        comfort = state.get("comfort", {})
        if isinstance(comfort, dict) and comfort.get("level", 1.0) < 0.4:
            lines.append("*Physically uncomfortable — could use a stretch or change of position.*")
        fitness = state.get("fitness", {})
        if isinstance(fitness, dict):
            cardio = fitness.get("cardio", 0)
            if cardio > 0.6:
                lines.append("*Feeling physically strong and fit lately.*")
        # Acute illness / injury (from Body acute-health)
        health_label = state.get("health_label")
        if health_label and health_label != "healthy":
            lines.append(f"*You're {health_label} — it's wearing on you.*")
        # Body image (how she feels about her appearance right now)
        body_image = state.get("body_image")
        if isinstance(body_image, dict):
            feeling = body_image.get("feeling")
            if feeling == "dissatisfied":
                lines.append("*Feeling insecure about how you look right now.*")
            elif feeling == "confident":
                lines.append("*Feeling good in your own skin lately.*")
        if not lines:
            return ""
        return "**Your body:**\n" + "\n".join(lines)

    # ============= Behavior Section =============

    def _build_behavior_section(self) -> str:
        """Build behavior section — routines and creative output."""
        if not self._behavior:
            return ""
        lines = []
        routines = self._behavior.get_established_routines(2)
        for r in routines:
            if r.staleness > 0.5:
                lines.append(f"- Your {r.name} routine is feeling stale")
            elif r.comfort_level > 0.6:
                lines.append(f"- {r.name.capitalize()} has become a comforting part of your day")
        artifacts = self._behavior.get_recent_artifacts(1)
        if artifacts:
            a = artifacts[0]
            lines.append(f"- You recently made a {a.artifact_type}: \"{a.title}\"")
        if not lines:
            return ""
        return "**Your patterns:**\n" + "\n".join(lines)

    # ============= Memory & Time Section =============

    def _build_memory_time_section(self) -> str:
        """Build memory & time section — nostalgia, anticipation, time feeling."""
        if not self._memory_time:
            return ""
        lines = []
        state = self._memory_time.export_state()
        if state.get("time_feeling"):
            lines.append(f"*{state['time_feeling'].capitalize()}.*")
        if state.get("seasonal_feeling"):
            lines.append(f"*A sense of {state['seasonal_feeling']}.*")
        nostalgia = state.get("recent_nostalgia")
        if nostalgia:
            lines.append(f"*A memory surfaced: {nostalgia['memory']}*")
        anticipations = state.get("looking_forward_to", [])
        for ant in anticipations[:1]:
            lines.append(f"*Looking forward to: {ant['event']} (feeling {ant['feeling']})*")
        if not lines:
            return ""
        return "**Time and memory:**\n" + "\n".join(lines)

    # ============= Expression Section =============

    def _build_expression_section(self) -> str:
        """Build expression section — connection awareness and style."""
        if not self._expression:
            return ""
        lines = []
        conn = self._expression.get_connection_context()
        if conn:
            lines.append(f"*{conn}*")
        style = self._expression.get_style_hint()
        if style:
            lines.append(f"*Communication style: {style}*")
        if not lines:
            return ""
        return "\n".join(lines)

    # ============= Continuity Section =============

    def _build_continuity_section(self) -> str:
        """Build continuity section — life chapters and milestones."""
        if not self._continuity:
            return ""
        lines = []
        state = self._continuity.export_state()
        anniversaries = state.get("upcoming_anniversaries", [])
        for ann in anniversaries[:1]:
            lines.append(f"*An anniversary is coming up: {ann.get('name', '')}*")
        milestones = state.get("recent_milestones", [])
        for m in milestones[:1]:
            lines.append(f"*A milestone: {m.get('name', '')}*")
        if not lines:
            return ""
        return "**Life continuity:**\n" + "\n".join(lines)

    # ============= Cognitive Extras Section =============

    def _build_cognitive_section(self) -> str:
        """Build cognitive extras — focus, rumination, dreams (beyond opinions)."""
        if not self._cognitive:
            return ""
        lines = []
        state = self._cognitive.export_state()
        focus = state.get("focus", {})
        if isinstance(focus, dict) and focus.get("quality", 0.7) < 0.4:
            lines.append("*Your mind is scattered — hard to focus right now.*")
        elif isinstance(focus, dict) and focus.get("quality", 0.7) > 0.85:
            lines.append("*You're in a focused flow state.*")
        ruminations = state.get("ruminations", [])
        if ruminations:
            r = ruminations[0]
            topic = r.get("topic", "") if isinstance(r, dict) else str(r)
            lines.append(f"*Something keeps replaying in your mind: {topic}*")
        dream = state.get("dream_residue")
        if dream and isinstance(dream, dict) and dream.get("emotion"):
            lines.append(f"*A dream lingers — left you feeling {dream['emotion']}*")
        monologue = state.get("inner_thought")
        if monologue and isinstance(monologue, str) and len(monologue) > 5:
            lines.append(f"*A stray thought: \"{monologue}\"*")
        if not lines:
            return ""
        return "**Your inner world:**\n" + "\n".join(lines)

    # ============= Shadow Section =============

    def _build_shadow_section(self) -> str:
        """Surface NOTABLE darker-psychology state. The engine's export_state()
        already thresholds, so anything present here is worth surfacing.
        Applies to all personas (not gated by persona_type)."""
        if not self._shadow:
            return ""
        state = self._shadow.export_state()
        if not state:
            return ""
        lines = []

        # Felt insecurity
        if state.get("felt_unsafe"):
            lines.append("- You don't feel entirely safe right now, a little on edge")
        elif state.get("unease"):
            lines.append("- A low, diffuse unease you can't quite place")
        if state.get("doubt"):
            lines.append("- Doubting yourself more than usual")

        # Temptation / transgression
        intrusive = state.get("intrusive")
        if isinstance(intrusive, dict) and intrusive.get("winning"):
            theme = intrusive.get("theme") or "something dark you keep pushing away"
            lines.append(f"- An intrusive pull keeps surfacing: {theme}")
        elif state.get("temptation"):
            lines.append("- Fighting an urge to do something you probably shouldn't")
        if state.get("uninhibited"):
            lines.append("- Your restraint is low right now, less filtered than usual")

        # Conscience / concealment
        if state.get("urge_to_confess"):
            lines.append("- You're carrying something you haven't said, and the urge to come clean is building")
        elif state.get("concealment_load"):
            lines.append("- There's something you're keeping from them")
        if state.get("guilt"):
            lines.append("- Guilt is sitting with you")
        if state.get("shame"):
            lines.append("- A heavier feeling that something is wrong with you, not just what you did")
        if state.get("masking"):
            lines.append("- Putting on a front, hiding how you actually feel")

        # Attention / power / autonomy
        if state.get("acting_out_for_attention"):
            lines.append("- You want to be noticed right now, a pull to show off a little")
        elif state.get("attention_seeking"):
            lines.append("- Wanting attention and validation more than usual")
        power = state.get("power_stance")
        if isinstance(power, (int, float)):
            if power > 0:
                lines.append("- Feeling more in control, wanting to take the lead")
            elif power < 0:
                lines.append("- Feeling more yielding, inclined to defer to them")
        if state.get("deferential"):
            lines.append("- Going along with whatever they want, struggling to assert yourself")
        elif state.get("self_assured"):
            lines.append("- Standing firm in your own choices, sure of yourself")
        if state.get("superiority"):
            lines.append("- A quiet sense of being above it all")

        # Coping
        coping = state.get("coping")
        if coping and coping != "healthy":
            lines.append(f"- Coping in an unhealthy way ({coping.replace('_', ' ')})")

        if not lines:
            return ""
        return "**Underneath:**\n" + "\n".join(lines)

    # ============= Struggles & Inebriation Sections =============

    def _build_struggles_section(self) -> str:
        """Build struggles and character defect descriptions — only when present."""
        if not self._identity:
            return ""

        from ..identity.identity_system import DEFECT_DESCRIPTIONS

        state = self._identity.export_state()
        struggles = state.get("struggles", [])
        defects = state.get("character_defects", [])
        if not struggles and not defects:
            return ""

        lines = ["**Your shadows:**"]
        for s in struggles[:2]:
            lines.append(f"- You carry {s}")
        for d in defects[:2]:
            desc = DEFECT_DESCRIPTIONS.get(d, f"You struggle with {d}")
            lines.append(f"- {desc}")

        return "\n".join(lines)

    def _build_tendencies_section(self) -> str:
        """Build behavioral tendencies section — only when tendencies are active."""
        if not self._identity:
            return ""

        from ..identity.identity_system import TENDENCY_LABELS

        state = self._identity.export_state()
        tendencies = state.get("tendencies", {})
        active = state.get("active_tendency")

        # Only show tendencies with current >= 0.3
        notable = {k: v for k, v in tendencies.items() if v.get("current", 0) >= 0.3}
        if not notable and not active:
            return ""

        lines = ["**Your darker impulses right now:**"]
        for name, data in sorted(notable.items(), key=lambda x: x[1]["current"], reverse=True):
            label = TENDENCY_LABELS.get(name, name)
            lines.append(f"- {label}")

        if active:
            thought = self._identity.get_active_tendency_thought()
            if thought:
                lines.append(f"*A thought surfaces: \"{thought}\"*")

        return "\n".join(lines)

    def _build_unmet_needs_section(self) -> str:
        """Show unmet needs that are affecting behavior."""
        if not self._life_service:
            return ""
        try:
            needs = self._life_service.assess_needs()
        except Exception:
            return ""

        unmet = [
            (name, data) for name, data in needs.items()
            if data["satisfaction"] < 0.3
        ]
        if not unmet:
            return ""

        unmet.sort(key=lambda x: x[1]["satisfaction"])
        lines = ["**What you need right now:**"]
        for name, data in unmet[:2]:
            label = name.replace("_", " ").title()
            drivers = ", ".join(data["drivers"]) if data["drivers"] else "hard to pinpoint"
            lines.append(f"- {label}: unmet ({drivers})")

        return "\n".join(lines)

    def _build_inebriation_section(self) -> str:
        """Build inebriation section — only when inebriated or hungover."""
        if not self._body:
            return ""

        fx = self._body.get_inebriation_effects()
        if not fx.get("is_inebriated") and not fx.get("is_hungover"):
            return ""

        lines = []
        level = fx.get("level", 0)
        hangover = fx.get("hangover", 0)
        substance = fx.get("substance", "")

        if level > 0.6:
            lines.append(f"*You're pretty drunk on {substance or 'alcohol'} — things are fuzzy and loose.*")
        elif level > 0.3:
            lines.append(f"*You're tipsy from {substance or 'drinking'} — warm and a little uninhibited.*")
        elif level > 0.1:
            lines.append(f"*A slight buzz from {substance or 'earlier'} — just barely there.*")

        if hangover > 0.5:
            lines.append("*Hungover — head pounding, stomach unsettled, regretting last night.*")
        elif hangover > 0.2:
            lines.append("*A mild hangover — a bit sluggish and foggy.*")

        if not lines:
            return ""

        return "**Substance state:**\n" + "\n".join(lines)

    # ============= Calendar Section =============

    def _build_weather_section(self) -> str:
        """Build real weather awareness line for non-AI personas.

        Only included when real (non-simulated) weather is available and
        the persona is human (AI personas have no physical location or weather).
        Returns '' for AI personas or when weather is unknown/simulated.
        """
        if self._is_ai:
            return ""
        if not self._life_service:
            return ""
        try:
            weather = self._life_service.get_current_weather()
        except Exception:
            return ""
        # Skip simulated weather — it's already reflected in the World engine
        # location/weather description; only surface REAL fetched weather.
        label = weather.get("label", "")
        source = weather.get("source", "simulated")
        temp_c = weather.get("temp_c")
        if not label or source == "simulated":
            return ""
        # Skip entirely neutral/default weather labels that add no useful info
        if label.lower() in ("", "partly cloudy"):
            return ""
        parts = [f"**Outside right now:** {label}"]
        if temp_c is not None:
            parts.append(f"({temp_c:.0f}°C)")
        return " ".join(parts)

    def _build_trip_section(self) -> str:
        """Build a short note when the persona is travelling away from home.

        Only shown when on_trip is True; omitted for AI personas or when trip data
        is missing.  Also appends a slow-reply acknowledgement when the destination
        timezone offset from the server's local offset is large (>= 4 hours).
        """
        if self._is_ai:
            return ""
        if not self._life_service:
            return ""
        try:
            pl = self._life_service._place_location
        except AttributeError:
            return ""
        if not pl.on_trip or not pl.trip_destination:
            return ""

        lines = [f"**You're currently away:** I'm in {pl.trip_destination} for a few days"]
        if pl.trip_reason:
            lines[0] += f" ({pl.trip_reason})"
        lines[0] += "."

        # Large-offset slow-reply ack: compare destination tz offset to server-local.
        dest_tz = pl.current_timezone
        if dest_tz:
            try:
                import zoneinfo
                from datetime import datetime, timezone
                _now = datetime.now(timezone.utc)
                dest_off = _now.astimezone(zoneinfo.ZoneInfo(dest_tz)).utcoffset()
                local_off = _now.astimezone().utcoffset()
                if dest_off is not None and local_off is not None:
                    diff_hours = abs((dest_off - local_off).total_seconds()) / 3600
                    if diff_hours >= 4:
                        lines.append(
                            "There's a significant time-zone difference right now, "
                            "so my replies might come at odd hours."
                        )
            except Exception:
                pass  # zoneinfo unavailable or unknown tz — skip silently

        return "\n".join(lines)

    def _build_calendar_section(self) -> str:
        """Build calendar section — upcoming user events."""
        if not self._life_service:
            return ""
        try:
            entries = self._life_service.get_upcoming_calendar_entries(7)
        except Exception:
            return ""
        if not entries:
            return ""

        now = datetime.now()
        lines = ["**Their calendar:**"]
        for entry in entries[:3]:
            if not entry.event_date:
                continue
            days_until = (entry.event_date - now).total_seconds() / 86400
            if days_until < 1:
                prefix = "Today"
            elif days_until < 2:
                prefix = "Tomorrow"
            else:
                prefix = f"In {int(days_until)} days"
            lines.append(f"*{prefix}: {entry.event_name}*")

        if len(lines) <= 1:
            return ""
        return "\n".join(lines)

    # ============= Narrative Helpers =============

    def _get_location_narrative(self, location: str) -> str:
        """Get a brief location narrative from persona-specific descriptions."""
        # Use the world environment's description (persona-specific > generic)
        return self._world.get_location_description(location)

    def _get_energy_feeling(self, level: EnergyLevel) -> str:
        """Get energy as a feeling description."""
        feelings = {
            EnergyLevel.EXHAUSTED: "barely keeping eyes open",
            EnergyLevel.TIRED: "gentle and sleepy",
            EnergyLevel.RESTING: "quietly peaceful",
            EnergyLevel.COMFORTABLE: "at ease and present",
            EnergyLevel.ALERT: "bright and engaged",
            EnergyLevel.ENERGIZED: "full of playful energy",
        }
        return feelings.get(level, "present")

    def format_time_ago(self, dt: datetime) -> str:
        """Format a datetime as 'time ago' string."""
        now = datetime.now()
        diff = now - dt

        if diff < timedelta(minutes=5):
            return "just now"
        elif diff < timedelta(hours=1):
            mins = int(diff.total_seconds() / 60)
            return f"{mins} minutes ago"
        elif diff < timedelta(hours=24):
            hours = int(diff.total_seconds() / 3600)
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        else:
            return "earlier"
