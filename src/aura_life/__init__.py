"""
aura-life: agent life-simulation engine

A rich world simulation giving an autonomous persona their own inner life:
- Virtual home with rooms, weather, time progression
- Self-generated goals based on personality/experiences
- Energy/fatigue cycles with natural rhythms
- Mental, creative, skill-building activities
- Intimate desires and private pleasures
- Shareable experiences to discuss with the user

This is the library's curated public surface -- everything listed in
``__all__`` is stable. For anything not exported here, see
``aura_life.internals`` (unstable; may change in a minor release).
"""

__version__ = "0.1.0"

from aura_life.life_service import LifeService
from aura_life.models import (
    # Place / location identity
    PlaceLocationState,
    # Location
    LocationProfile,
    LOCATION_TYPE_EFFECTS,
    COMMUTE_ENERGY_COST,
    # World
    Location,
    Weather,
    TimeOfDay,
    Season,
    CherishedObject,
    WorldState,
    # Energy
    EnergyState,
    EnergyLevel,
    # Activities
    ActivityCategory,
    Activity,
    ActivityLog,
    # Goals
    GoalTimeframe,
    GoalSource,
    Goal,
    # Transit
    TransitPhase,
    TransitState,
    # Desires & Planning
    DesireSource,
    ShortTermDesire,
    PlannedSlot,
    DailyPlan,
    # Shareable
    ShareableExperience,
    # Life Events
    LifeEvent,
    # Needs & Room
    BasicNeedsState,
    RoomState,
    FinancialState,
    CareerState,
    # Media & Skills
    MediaState,
    SkillProgress,
    # Social
    NPC,
    SocialEvent,
    RelationshipArc,
    SocialObligation,
    SocialConflict,
    FriendGroup,
    SocialBatteryState,
    # Identity
    IdentityFacet,
    PersonPerception,
    # Affect
    MoodState,
    StressState,
    LonelinessState,
    RegulationState,
    EmpathyState,
    # Body
    PhysicalHealthState,
    HormonalCycleState,
    PhysicalComfortState,
    AppearanceState,
    SleepQualityState,
    FitnessState,
    # Cognitive
    FocusState,
    RuminationLoop,
    InnerMonologueEntry,
    DreamFragment,
    Opinion,
    # Drive
    CuriosityQuestion,
    AvoidanceItem,
    ComfortZoneBoundary,
    # Identity expansion
    ValueBelief,
    SelfEsteemState,
    IdealSelfTrait,
    TasteProfile,
    InsideJoke,
    HumorProfileState,
    # Expression & Perception
    ConnectionState,
    CommunicationStyleState,
    # Continuity
    Anniversary,
    GrowthSnapshot,
    RelationshipMilestone,
    # Memory & Time
    TimePerceptionState,
    SeasonalConsciousnessState,
    NostalgiaEvent,
    LifeChapter,
    TemporalRhythm,
    Anticipation,
    CalendarEntry,
    # World / Behavior
    RoutinePattern,
    CreativeArtifact,
    AmbientSenseSnapshot,
    Possession,
    NeighborhoodPlace,
    # Shadow
    ShadowState,
)
from aura_life.planner import DailyPlanner
from aura_life.intimacy import DesireSystem, DesireState, ArousalLevel
from aura_life.social import SocialSystem
from aura_life.identity import IdentitySystem
from aura_life.affect import AffectSystem
from aura_life.body import BodySystem
from aura_life.cognitive import CognitiveSystem
from aura_life.drive import DriveSystem
from aura_life.behavior import BehaviorSystem
from aura_life.memory_time import MemoryTimeSystem
from aura_life.expression import ExpressionSystem
from aura_life.continuity import ContinuitySystem
from aura_life.persona_evolution import CharacterEvolution
from aura_life.chaos import ChaosEngine
from aura_life.life_events import LifeEventSystem
from aura_life.money import FinanceSystem
from aura_life.job import CareerSystem
from aura_life.habitation import HabitationSystem
from aura_life.sustenance import SustenanceSystem
from aura_life.skills import SkillsSystem
from aura_life.errands import ErrandsSystem
from aura_life.location import LocationSystem
from aura_life.transportation import TransportSystem
from aura_life.shadow import ShadowSystem
from aura_life.schedule import (
    EventType,
    ScheduledEvent,
    UpcomingEvent,
    PersonaSchedule,
    get_persona_schedule,
    clear_persona_schedule,
)
from aura_life import hooks
from aura_life.hooks import HookNotConfigured

# Register the library's own hook defaults. Only ``persona_now`` has one, and
# without it every activity tick of a host-free LifeService dies silently --
# see aura_life/defaults.py. A host bridge installed later overwrites it.
from aura_life import defaults as _defaults

_defaults.install()

__all__ = [
    "LifeService",
    # Location
    "LocationProfile",
    "LOCATION_TYPE_EFFECTS",
    "COMMUTE_ENERGY_COST",
    # World
    "Location",
    "Weather",
    "TimeOfDay",
    "Season",
    "CherishedObject",
    "WorldState",
    # Energy
    "EnergyState",
    "EnergyLevel",
    # Activities
    "ActivityCategory",
    "Activity",
    "ActivityLog",
    # Goals
    "GoalTimeframe",
    "GoalSource",
    "Goal",
    # Transit
    "TransitPhase",
    "TransitState",
    # Desires & Planning
    "DesireSource",
    "ShortTermDesire",
    "PlannedSlot",
    "DailyPlan",
    "DailyPlanner",
    # Shareable
    "ShareableExperience",
    # Life Events
    "LifeEvent",
    "LifeEventSystem",
    # Needs & Room
    "BasicNeedsState",
    "RoomState",
    "FinancialState",
    # Money
    "FinanceSystem",
    # Job
    "CareerSystem",
    "CareerState",
    # Habitation
    "HabitationSystem",
    # Sustenance
    "SustenanceSystem",
    # Skills
    "SkillsSystem",
    # Errands
    "ErrandsSystem",
    # Location
    "LocationSystem",
    # Transportation
    "TransportSystem",
    # Media & Skills
    "MediaState",
    "SkillProgress",
    # Social
    "NPC",
    "SocialEvent",
    "SocialSystem",
    "RelationshipArc",
    "SocialObligation",
    "SocialConflict",
    "FriendGroup",
    "SocialBatteryState",
    # Identity
    "IdentitySystem",
    "IdentityFacet",
    "PersonPerception",
    # Affect
    "AffectSystem",
    "MoodState",
    "StressState",
    "LonelinessState",
    "RegulationState",
    "EmpathyState",
    # Body
    "BodySystem",
    "PhysicalHealthState",
    "HormonalCycleState",
    "PhysicalComfortState",
    "AppearanceState",
    "SleepQualityState",
    "FitnessState",
    # Cognitive
    "CognitiveSystem",
    "FocusState",
    "RuminationLoop",
    "InnerMonologueEntry",
    "DreamFragment",
    "Opinion",
    # Drive
    "DriveSystem",
    "CuriosityQuestion",
    "AvoidanceItem",
    "ComfortZoneBoundary",
    # Identity expansion
    "ValueBelief",
    "SelfEsteemState",
    "IdealSelfTrait",
    "TasteProfile",
    "InsideJoke",
    "HumorProfileState",
    # Memory & Time
    "MemoryTimeSystem",
    "TimePerceptionState",
    "SeasonalConsciousnessState",
    "NostalgiaEvent",
    "LifeChapter",
    "TemporalRhythm",
    "Anticipation",
    # Persona Evolution
    "CharacterEvolution",
    # Chaos
    "ChaosEngine",
    # Expression
    "ExpressionSystem",
    # Continuity
    "ContinuitySystem",
    "Anniversary",
    "GrowthSnapshot",
    "RelationshipMilestone",
    "ConnectionState",
    "CommunicationStyleState",
    # Behavior
    "BehaviorSystem",
    "RoutinePattern",
    "CreativeArtifact",
    "AmbientSenseSnapshot",
    "Possession",
    "NeighborhoodPlace",
    # Shadow
    "ShadowSystem",
    "ShadowState",
    # Intimacy
    "DesireSystem",
    "DesireState",
    "ArousalLevel",
    # Schedule
    "EventType",
    "ScheduledEvent",
    "UpcomingEvent",
    "PersonaSchedule",
    "get_persona_schedule",
    "clear_persona_schedule",
    # Hooks
    "hooks",
    "HookNotConfigured",
]
