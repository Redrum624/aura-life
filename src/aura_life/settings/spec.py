"""What a setting pack is -- :class:`SettingSpec` -- and the registry of packs
(spec section 4.4).

A setting is the world a persona lives in: what she can do and where, what
the people in her life do, what can happen to her, what she wants, aims at and
remembers, and which days are holidays. Before Task 9 every persona lived one
modern-suburban life, because each engine read these from module-level
catalogues; now each engine reads them from the persona's setting, which
``LifeService`` resolves once, at construction, from
``PersonalityDefinition.setting`` (empty means :data:`DEFAULT_SETTING`) and
hands to every engine. The default pack, ``contemporary``
(:mod:`aura_life.settings.contemporary`), holds today's catalogues, moved
unchanged.

Which engine reads which field:

- ``activities`` -- ``ActivityEngine`` (choice and narration; the daily
  planner plans from the engine's list). An activity whose ``persona_ids`` is
  not empty is open only to the personas it names
  (:meth:`SettingSpec.activities_for`). Its ``tags`` (:data:`ACTIVITY_TAGS`)
  are what the engines know it as instead of its name. Its ``outcomes``
  (Task 14) are what she says happened when it did not go well -- only half
  well, or wrong (:data:`NON_SUCCESS_OUTCOMES`); a success is told by its
  ``narrative_templates``, and an outcome it has no words for by the
  library's neutral ones. A setting none of whose own activities is tagged
  "sleep", "nap" or "meal" gets the library's universal one for it
  (:meth:`SettingSpec.resolved_activities`, :mod:`aura_life.settings.universal`;
  ruling T9-R6).
- ``weather_flavors`` -- ``ActivityEngine``: the weather suffix on an
  activity's narrative.
- ``places`` -- ``LifeService`` (the location registry every persona starts
  with) and ``DailyPlanner`` (the location keys it may plan): location key ->
  place type (``LOCATION_TYPE_EFFECTS``' keys).
- ``place_descriptions`` -- ``WorldEnvironment``: the description of a place
  the persona's own profile does not describe.
- ``npc_event_templates``, ``text_topics``, ``invite_activities`` --
  ``SocialSystem``: what the people in her life do, by NPC kind
  (``NPC_KINDS``) then event type. A kind with no templates uses
  :data:`DEFAULT_NPC_KIND`'s -- an unwelcome one
  (:data:`UNWELCOME_NPC_KINDS`) has none then
  (:meth:`SettingSpec.npc_event_templates_for`).
- ``activity_chaos`` (an activity's outcome texts: the twist it can take),
  ``universal_chaos``, ``universal_chaos_effects`` and ``serendipity`` (the
  life-event texts: what can happen to her whatever she is doing), and
  ``chaos_emotions`` (what those texts make her feel, matched by substring,
  first match in order) -- ``ChaosEngine``.
- ``micro_events``, ``skill_mappings`` (activity -> the skill it trains and
  by how much), ``skill_milestones``, ``dream_templates`` and ``catch_up``
  (:class:`CatchUpNarratives`) -- ``LifeService``.
- ``wants`` (the short-term desires she draws from) and ``want_follow_ups``
  (the one an activity can leave behind) -- ``DailyPlanner``.
- ``holidays`` -- ``DailyPlanner``: a callable ``(nationality, year) ->
  {(month, day): name}``; ``None`` means no holidays.
- ``personality_goals``, ``long_term_goals``, ``dream_goals`` and
  ``daily_intentions`` -- ``GoalEngine``.
- ``nostalgia_fragments`` and ``nostalgia_triggers`` (activity -> (trigger,
  chance)) -- ``MemoryTimeSystem``.

Every catalogue defaults to empty, so a pack states only what it has; an
engine given an empty catalogue simply does without it (no micro-events, no
chaos, no holidays ...). A pack that wants some of contemporary's texts
derives from it -- ``dataclasses.replace(get_setting("contemporary"),
key="mine", activities=[...])`` -- without mutating the lists it shares with
it. Text fields may carry the pronoun and user tokens
``aura_life.personas.pronoun_render`` fills (``{Subj}``, ``{poss}``,
``{user}`` ...); ``LifeService`` renders them for the persona at output time.

The registry follows :func:`~aura_life.personas.genre_randomizer.register_genre`:
:func:`register_setting` stores a deep copy and refuses a key already taken
unless ``replace=True``; :func:`unregister_setting` says whether the key was
there; :func:`get_setting` returns the registered spec -- treat it as
read-only.
"""

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional, Tuple

from ..emotion.appraisal import FAIL, MIXED
from ..models import Activity, CherishedObject, IntimateActivity, TimeOfDay, Weather
from ..personas.keys import NPC_KINDS

#: The setting a persona with no ``PersonalityDefinition.setting`` lives in.
DEFAULT_SETTING = "contemporary"

#: The NPC kind a social-circle entry has when it names none (spec section
#: 4.1; ``aura_life.personas.keys.NPC_KINDS``), and whose event templates a
#: kind without its own uses -- unless that kind is unwelcome.
DEFAULT_NPC_KIND = "friend"

#: The NPC kinds whose contact she does not want: someone she is estranged
#: from, someone she fears (``NPC_KINDS``). Another kind's lines are never
#: theirs -- a friend's "texted to check in" is not what a threat does -- so
#: a pack that gives one of these no lines of its own has none for it
#: (:meth:`SettingSpec.npc_event_templates_for`), and whatever they do is
#: unwelcome to her (``SocialSystem``, ``LifeService``; Task 11).
UNWELCOME_NPC_KINDS: Tuple[str, ...] = ("estranged", "threat")

#: ``(nationality, year) -> {(month, day): holiday name}``.
HolidayCalendar = Callable[[str, int], Dict[Tuple[int, int], str]]

#: The tags an activity may carry (``Activity.tags``) -- what the engines
#: know it as, instead of by its name -- and what reads each.
ACTIVITY_TAGS: Dict[str, str] = {
    "sleep": "the night's sleep: never an ordinary choice, and the sleep state's log entry "
             "(LifeService._on_activity_tick / _on_fell_asleep; DailyPlanner never plans it)",
    "nap": "a nap: open only when EnergySystem.can_nap says so, and it lowers sleep pressure "
           "(EnergySystem.nap); DailyPlanner never plans it",
    "meal": "a meal: relieves hunger (SustenanceSystem.on_activity), whatever its name",
    # Ruling T9-R5: the activity-name sets the engines used to read.
    "physical": "needs a body: an AI persona's plan leaves it out (DailyPlanner._generate_ai_plan) "
                "and an AI persona's moment-share never claims it (LifeService)",
    "outdoor": "outdoors: bad weather lowers its chance in a planned slot, fair weather raises it "
               "(DailyPlanner._select_activity_for_slot)",
    "flow": "time flies doing it (MemoryTimeSystem)",
    "focus": "sharpens focus, and can become a flow state (CognitiveSystem.tick)",
    "distracting": "scatters focus (CognitiveSystem.tick)",
    "quiet": "a calm activity for the quiet hours of an AI persona's plan (DailyPlanner._generate_ai_plan)",
    "fallback_rest": "what an empty slot, a quiet AI hour, a cancelled workday -- and, with a nap, a "
                     "slot swapped for being too tired -- becomes (DailyPlanner)",
    "restful": "already rest: never swapped away for being too tired (DailyPlanner.revise_upcoming)",
    "soothing": "already suits a low mood: never swapped for a gentle activity (DailyPlanner.revise_upcoming)",
    "gentle": "what a slot becomes when the mood is low (DailyPlanner.revise_upcoming)",
    "clear_sky": "needs a clear night sky: planned on a clear night, swapped for a rainy-day activity "
                 "when the sky clouds over (DailyPlanner)",
    "rained_off": "rain cancels it: swapped for a rainy-day activity when it rains (DailyPlanner.revise_upcoming)",
    "rainy_day": "what a rained-off or clouded-over slot becomes (DailyPlanner.revise_upcoming)",
    # Task 10: the slots DailyPlanner anchors a day with (ANCHOR_TAGS). A
    # slot is only planned when her setting has an activity for it -- the
    # first so tagged, in tag_order -- so every slot she is given is one she
    # can do.
    "wake_up": "the first slot of the day, at the wake hour (DailyPlanner)",
    "breakfast": "the morning meal slot (DailyPlanner); without one, the first 'meal' activity fills it",
    "lunch": "the midday meal slot (DailyPlanner); without one, the first 'meal' activity fills it",
    "dinner": "the evening meal slot (DailyPlanner); without one, the first 'meal' activity fills it",
    "bedtime": "winding down, the hour before bedtime (DailyPlanner)",
    "work": "a work shift's hours (DailyPlanner): a commitment -- never dropped on a whim or taken by an "
            "intimate activity (LifeService)",
    "commute": "the way to and from work or class (DailyPlanner): a commitment",
    "class": "a class in a student's day (DailyPlanner): a commitment",
    "study": "a study session in a student's day (DailyPlanner): a commitment",
    "meetup": "meeting someone somewhere agreed (DailyPlanner.schedule_rendezvous)",
    # Task 10: what a substance tendency draws her to, or keeps her from
    # (aura_life.activities.choice.SUBSTANCE_TAGS).
    "alcohol": "a drink: a persona who drinks is drawn to it by how often, one who avoids it kept from it "
               "(ActivityPreferences)",
    "smoking": "a smoke: likewise, for tobacco (ActivityPreferences)",
    # Task 11: what the people who live together do together.
    "joint": "something to do with the people who live together: a housemate who is free, awake and in the "
             "same place may join in, and it is in both their logs (LifeService, aura_life.social.household)",
}

#: The slots ``DailyPlanner`` anchors a day with -- waking, the three meals,
#: bedtime, a shift, the commute, a class, study, a meetup -- by the tag an
#: activity fills each with. Never a free hour's pick: a free hour is planned
#: from the rest (Task 10).
ANCHOR_TAGS: Tuple[str, ...] = (
    "wake_up", "breakfast", "lunch", "dinner", "bedtime", "work", "commute", "class", "study", "meetup",
)
#: Of the anchors, those that happen only when her plan says so: never an
#: ordinary choice (``ActivityEngine.select_activity``) -- unlike a meal,
#: which she may also eat because she is hungry.
PLAN_ONLY_TAGS: Tuple[str, ...] = ("wake_up", "bedtime", "work", "commute", "class", "study", "meetup")
#: Of the anchors, her commitments: a planned slot of one is never dropped on
#: a whim (``DailyPlanner.abandons_slot``) nor taken by an intimate activity
#: (``LifeService``), and cancelling the day's work cancels them.
COMMITMENT_TAGS: Tuple[str, ...] = ("work", "commute", "class", "study")

#: The needs she chooses what to do by (``aura_life.activities.choice``), and
#: the state each shortfall is read from (``LifeService``, every activity
#: tick; 0 = met, 1 = as unmet as it gets). ``Activity.needs`` may state how
#: much an activity meets each (-1..1: a negative value is a cost, as company
#: is to a drained introvert); a need it leaves out is derived from the
#: activity's category and tags (``aura_life.activities.choice.DERIVED_SATISFACTION``).
NEED_KEYS: Dict[str, str] = {
    "hunger": "SustenanceSystem.hunger (none for an AI persona)",
    "rest": "1 - effective energy (EnergySystem.effective_level)",
    "social": "loneliness (AffectSystem.loneliness.level)",
    "solitude": "how far the social battery is drained (1 - SocialSystem.social_battery charge / capacity)",
    "calm": "stress (AffectSystem.stress.level)",
    "stimulation": "the strongest unexplored curiosity (DriveSystem.get_active_curiosities)",
    "reflection": "the strongest rumination loop (CognitiveSystem)",
}

#: The outcomes an activity's ``outcomes`` tells (Task 14): how it went when
#: it did not go well, only half well or wrong
#: (:data:`aura_life.emotion.appraisal.OUTCOMES`). A success is told by its
#: ``narrative_templates``, as every activity was before.
NON_SUCCESS_OUTCOMES: Tuple[str, ...] = (MIXED, FAIL)

#: A setting none of whose own activities carries one of these tags gets the
#: library's universal activity for it
#: (:data:`aura_life.settings.universal.UNIVERSAL_ACTIVITIES`), so every
#: setting can sleep, nap and eat (ruling T9-R6).
UNIVERSAL_TAGS: Tuple[str, ...] = ("sleep", "nap", "meal")


def _universal_activities() -> Dict[str, Activity]:
    """Tag -> the library's universal activity for it. Imported on use:
    ``universal.py`` builds on ``contemporary.py``, which imports this
    module."""
    from .universal import UNIVERSAL_ACTIVITIES
    return UNIVERSAL_ACTIVITIES


@dataclass
class CatchUpNarratives:
    """What the persona did while the host was down, told afterwards.

    ``LifeService.catch_up_from_downtime`` tells each backfilled activity by
    ``by_activity`` (activity name -> narrative), with ``sleep`` for sleep and
    ``morning_routine`` for a morning routine; the rest are the lines its
    hour-of-day backfill and its long-absence summaries draw from
    (``gap_week``: a week or more; ``gap_days``: two days or more;
    ``gap_short``: less).
    """

    sleep: str = ""
    morning_routine: List[str] = field(default_factory=list)
    morning_activity: List[str] = field(default_factory=list)
    midday: List[str] = field(default_factory=list)
    afternoon: List[str] = field(default_factory=list)
    evening: List[str] = field(default_factory=list)
    late: str = ""
    by_activity: Dict[str, str] = field(default_factory=dict)
    gap_week: str = ""
    gap_days: str = ""
    gap_short: str = ""


@dataclass
class SettingSpec:
    """One setting pack: every catalogue the engines read for a persona who
    lives in it. See the module docstring for which engine reads which."""

    key: str
    activities: List[Activity] = field(default_factory=list)
    weather_flavors: Dict[Weather, str] = field(default_factory=dict)
    places: Dict[str, str] = field(default_factory=dict)
    place_descriptions: Dict[str, str] = field(default_factory=dict)
    npc_event_templates: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    text_topics: List[str] = field(default_factory=list)
    invite_activities: List[str] = field(default_factory=list)
    activity_chaos: Dict[str, List[str]] = field(default_factory=dict)
    universal_chaos: List[str] = field(default_factory=list)
    universal_chaos_effects: List[Dict[str, Any]] = field(default_factory=list)
    serendipity: List[str] = field(default_factory=list)
    chaos_emotions: Dict[str, Dict[str, float]] = field(default_factory=dict)
    micro_events: List[Dict[str, Any]] = field(default_factory=list)
    skill_mappings: Dict[str, Tuple[str, float]] = field(default_factory=dict)
    skill_milestones: Dict[str, List[Tuple[float, str]]] = field(default_factory=dict)
    dream_templates: List[str] = field(default_factory=list)
    catch_up: CatchUpNarratives = field(default_factory=CatchUpNarratives)
    wants: List[Dict[str, Any]] = field(default_factory=list)
    want_follow_ups: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    holidays: Optional[HolidayCalendar] = None
    personality_goals: List[Dict[str, Any]] = field(default_factory=list)
    long_term_goals: List[Dict[str, Any]] = field(default_factory=list)
    dream_goals: List[Dict[str, Any]] = field(default_factory=list)
    daily_intentions: List[Dict[str, Any]] = field(default_factory=list)
    nostalgia_fragments: List[str] = field(default_factory=list)
    nostalgia_triggers: Dict[str, Tuple[str, float]] = field(default_factory=dict)
    #: The intimate activities (``DesireSystem``). ``None`` -- left out --
    #: is the default setting's (ruling T9-R2: leaving it out never changes
    #: how often she does one, spec R6); an empty list is none.
    intimate_activities: Optional[List[IntimateActivity]] = None
    # Ruling T9-R5. Occupation / interest keyword -> the (location key, place
    # type) pairs it adds to her places (LifeService's location registry).
    occupation_places: Dict[str, List[Tuple[str, str]]] = field(default_factory=dict)
    interest_places: Dict[str, List[Tuple[str, str]]] = field(default_factory=dict)
    #: What CognitiveSystem.generate_dream tells a dream fragment with ({source}).
    dream_fragment_templates: List[str] = field(default_factory=list)
    #: A workday's notable events (CareerSystem.tick) and what each makes her
    #: feel (LifeService, keyed by the event's unrendered text).
    work_events_positive: List[str] = field(default_factory=list)
    work_events_negative: List[str] = field(default_factory=list)
    work_event_emotions: Dict[str, Dict[str, float]] = field(default_factory=dict)
    #: How the weather reads (WorldEnvironment), and the cherished objects in
    #: her home (WorldEnvironment.get_cherished_objects_at_location ...).
    weather_descriptions: Dict[Weather, str] = field(default_factory=dict)
    cherished_objects: List[CherishedObject] = field(default_factory=list)
    #: Life-event titles by event type ({context}; LifeEventSystem.on_activity
    #: reads "discovery").
    life_event_templates: Dict[str, List[str]] = field(default_factory=dict)
    #: Tags for names that are not activities of this setting but reach an
    #: engine as one -- the planner's routine slot names ("having lunch",
    #: "working" ...), or a name only free text produces (ruling T9-R5).
    name_tags: Dict[str, FrozenSet[str]] = field(default_factory=dict)
    #: The order a tag's activities are drawn in (an rng draws an index, so
    #: the order is the draw); a tag not listed, or an activity a list leaves
    #: out, goes in catalogue order (:meth:`tag_pool`).
    tag_order: Dict[str, List[str]] = field(default_factory=dict)

    def resolved_activities(self) -> List[Activity]:
        """The setting's activities as the engines see them: its own, in
        catalogue order, then the library's universal activity for each of
        :data:`UNIVERSAL_TAGS` that none of its own carries (ruling T9-R6).
        A setting that has its own sleep, nap and meal gets none."""
        own_tags = set()
        for activity in self.activities:
            own_tags |= activity.tags
        universal = [activity for tag, activity in _universal_activities().items() if tag not in own_tags]
        return list(self.activities) + universal

    def activities_for(self, persona_id: Optional[str]) -> List[Activity]:
        """The activities open to ``persona_id``, in catalogue order (the
        setting's own, then any universal ones): every activity with no
        persona restriction, and each one whose ``persona_ids`` names her.
        Ids compare lower-cased, the form
        ``aura_life._safe_ids.safe_persona_id`` gives them; no id (``None``)
        is open to the unrestricted ones only."""
        pid = (persona_id or "").lower()
        return [
            activity for activity in self.resolved_activities()
            if not activity.persona_ids or pid in {p.lower() for p in activity.persona_ids}
        ]

    def intimate_catalogue(self) -> List[IntimateActivity]:
        """The intimate activities ``DesireSystem`` draws from: this
        setting's, or -- when it leaves ``intimate_activities`` out (``None``)
        -- :data:`DEFAULT_SETTING`'s."""
        if self.intimate_activities is not None:
            return list(self.intimate_activities)
        default = _REGISTRY.get(DEFAULT_SETTING)
        return list(default.intimate_activities or []) if default is not None else []

    def names_tagged(self, tag: str) -> FrozenSet[str]:
        """The names carrying ``tag``: the setting's activities (universal ones
        included) and :attr:`name_tags` -- what an engine that only has a
        name checks it against."""
        names = {activity.name for activity in self.resolved_activities() if tag in activity.tags}
        names |= {name for name, tags in self.name_tags.items() if tag in tags}
        return frozenset(names)

    def tag_pool(self, tag: str, activities: Iterable[Activity]) -> List[str]:
        """The names of ``activities`` that carry ``tag``, in the order an
        engine draws from them: :attr:`tag_order`'s for ``tag`` first, then
        the rest in the order given."""
        named = [activity.name for activity in activities if tag in activity.tags]
        first = [name for name in self.tag_order.get(tag, []) if name in named]
        return first + [name for name in named if name not in first]

    def npc_event_templates_for(self, kind: Optional[str]) -> Dict[str, List[str]]:
        """Event type -> templates for an NPC of ``kind``: that kind's own, or
        :data:`DEFAULT_NPC_KIND`'s when the pack gives it none (or no kind is
        given); empty when the pack has neither. An unwelcome kind
        (:data:`UNWELCOME_NPC_KINDS`) never takes another kind's lines: with
        none of its own it has none."""
        own = self.npc_event_templates.get(kind or DEFAULT_NPC_KIND)
        if own or kind in UNWELCOME_NPC_KINDS:
            return own or {}
        return self.npc_event_templates.get(DEFAULT_NPC_KIND) or {}

    def holidays_for(self, nationality: str, year: int) -> Dict[Tuple[int, int], str]:
        """``{(month, day): name}`` for a persona of ``nationality`` in
        ``year`` -- empty when the pack has no holiday calendar."""
        return self.holidays(nationality, year) if self.holidays is not None else {}


# ======================================================================
# The registry
# ======================================================================

_REGISTRY: Dict[str, SettingSpec] = {}

#: Fields that hold a list (a str there would be read one character at a time).
_LIST_FIELDS = (
    "activities", "text_topics", "invite_activities", "universal_chaos", "universal_chaos_effects",
    "serendipity", "micro_events", "dream_templates", "wants", "personality_goals",
    "long_term_goals", "dream_goals", "daily_intentions", "nostalgia_fragments",
    "dream_fragment_templates", "work_events_positive", "work_events_negative", "cherished_objects",
)
#: Fields that hold a mapping.
_DICT_FIELDS = (
    "weather_flavors", "places", "place_descriptions", "npc_event_templates", "activity_chaos",
    "chaos_emotions", "skill_mappings", "skill_milestones", "want_follow_ups", "nostalgia_triggers",
    "occupation_places", "interest_places", "work_event_emotions", "weather_descriptions",
    "life_event_templates", "name_tags", "tag_order",
)
#: The keys every entry of these catalogues must have: the engine indexes
#: them directly (``LifeService``'s micro-event ``event["text"]``,
#: ``ChaosEngine._effectful_chaos``'s ``chosen["text"]``,
#: ``DailyPlanner._refresh_desires``' ``template["title"]``,
#: ``GoalEngine._add_goal_from_template``'s and
#: ``GoalEngine.generate_daily_goal``'s ``template["title"]`` /
#: ``template["motivation"]``). ``want_follow_ups`` values need a title too:
#: a follow-up want without one would be nameless.
_ENTRY_KEYS = {
    "micro_events": ("text",),
    "universal_chaos_effects": ("text",),
    "wants": ("title",),
    "personality_goals": ("title",),
    "long_term_goals": ("title",),
    "dream_goals": ("title",),
    "daily_intentions": ("title", "motivation"),
}
#: What an entry's optional fields must be when given: the goals' and wants'
#: activity names and milestones are lists of str (``GoalEngine`` tests
#: ``name in related_activities``, which a str answers by substring), and
#: the emotions and effects are mappings (``LifeService._feel``,
#: ``ChaosEngine._effectful_chaos``). ``None`` is "not given".
_ENTRY_LISTS = ("related_activities", "milestones")
_ENTRY_DICTS = ("emotion", "emotions", "effect")
#: Mappings whose values are lists of text an engine draws one from
#: (``ChaosEngine._activity_chaos``, ``LifeEventSystem.on_activity``).
_TEXT_LIST_DICT_FIELDS = ("activity_chaos", "life_event_templates")
#: Mappings whose values are what a text makes her feel (emotion ->
#: intensity; ``ChaosEngine._match_emotions``, ``LifeService``'s work events).
_EMOTION_DICT_FIELDS = ("chaos_emotions", "work_event_emotions")
#: Mappings whose values an engine unpacks as one pair, and its two types:
#: ``trigger, chance = ...`` (``MemoryTimeSystem``), ``skill, increment =
#: ...`` (``LifeService._on_activity_tick``).
_PAIR_FIELDS = {
    "nostalgia_triggers": (str, (int, float)),
    "skill_mappings": (str, (int, float)),
}
#: Mappings whose values are lists of such pairs: ``for level, text in ...``
#: (``SkillsSystem.practice``), ``for key, place_type in ...``
#: (``LifeService._build_location_registry``).
_PAIR_LIST_FIELDS = {
    "skill_milestones": ((int, float), str),
    "occupation_places": (str, str),
    "interest_places": (str, str),
}
#: Mappings keyed by the Weather member an engine looks them up by (a
#: ``"rainy"`` key never equals ``Weather.RAINY``, so it would never match).
_WEATHER_KEYED_FIELDS = ("weather_flavors", "weather_descriptions")
#: :class:`CatchUpNarratives` fields an engine draws one line from.
_CATCH_UP_LISTS = ("morning_routine", "morning_activity", "midday", "afternoon", "evening")


def _is_text_list(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value)


def _is_member_list(value: Any, enum: type) -> bool:
    return isinstance(value, (list, tuple)) and all(isinstance(item, enum) for item in value)


def _is_pair(value: Any, first: Any, second: Any) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and isinstance(value[0], first) and isinstance(value[1], second))


def _type_names(types: Any) -> str:
    return " or ".join(t.__name__ for t in (types if isinstance(types, tuple) else (types,)))


def _items(spec: "SettingSpec", name: str) -> List[Tuple[Any, Any]]:
    """The entries of mapping field ``name`` -- none when it is not a
    mapping, which ``_DICT_FIELDS`` already reports."""
    value = getattr(spec, name)
    return list(value.items()) if isinstance(value, dict) else []


def _activity_shape_errors(activity: Any, label: str, locations: str) -> List[str]:
    """What an engine reading ``activity`` would trip on, or never match:
    its narratives (one is drawn; ``ActivityEngine.execute_activity``,
    ``DesireSystem.execute_intimate_activity``), its thoughts and places
    (lists of str -- a str would be read a character at a time), its times
    (and, for an :class:`Activity`, its weather: enum members, compared by
    ``in``) and its emotions (a mapping)."""
    errors: List[str] = []
    if not _is_text_list(activity.narrative_templates) or not activity.narrative_templates:
        errors.append(f"{label}: narrative_templates must be a non-empty list of str (one is drawn), "
                      f"got {activity.narrative_templates!r}")
    for name in ("thought_possibilities", locations):
        if not _is_text_list(getattr(activity, name)):
            errors.append(f"{label}: {name} must be a list of str, got {getattr(activity, name)!r}")
    enums = {"preferred_times": TimeOfDay}
    if isinstance(activity, Activity):
        enums["preferred_weather"] = Weather
    for name, enum in enums.items():
        if not _is_member_list(getattr(activity, name), enum):
            errors.append(f"{label}: {name} must be a list of {enum.__name__} members, "
                          f"got {getattr(activity, name)!r}")
    if not isinstance(activity.emotion_effects, dict):
        errors.append(f"{label}: emotion_effects must map an emotion to its intensity, "
                      f"got {activity.emotion_effects!r}")
    return errors


def _outcomes_errors(activity: Activity) -> List[str]:
    """``Activity.outcomes`` must map NON_SUCCESS_OUTCOMES to non-empty
    lists of non-blank str: ``ActivityEngine`` draws one when the activity
    does not go well (a success is told by ``narrative_templates``)."""
    outcomes = activity.outcomes
    if not isinstance(outcomes, dict):
        return [f"activity {activity.name!r}: outcomes must map an outcome to its narratives, got {outcomes!r}"]
    errors = []
    unknown = sorted(str(key) for key in outcomes if key not in NON_SUCCESS_OUTCOMES)
    if unknown:
        errors.append(f"activity {activity.name!r}: outcomes has {unknown}, none of {list(NON_SUCCESS_OUTCOMES)} "
                      "(a success is told by narrative_templates)")
    for outcome, texts in outcomes.items():
        if not _is_text_list(texts) or not texts or not all(text.strip() for text in texts):
            errors.append(f"activity {activity.name!r}: outcomes[{outcome!r}] must be a non-empty list of "
                          f"non-blank str (one is drawn), got {texts!r}")
    return errors


def _needs_errors(activity: Activity) -> List[str]:
    """``Activity.needs`` must map NEED_KEYS to numbers in -1..1 (what
    ``aura_life.activities.choice`` weighs; a key it does not know would
    never count)."""
    needs = activity.needs
    if not isinstance(needs, dict):
        return [f"activity {activity.name!r}: needs must map a need to how much it meets it, got {needs!r}"]
    errors = []
    unknown = sorted(str(key) for key in needs if key not in NEED_KEYS)
    if unknown:
        errors.append(f"activity {activity.name!r}: unknown needs {unknown} (NEED_KEYS: {sorted(NEED_KEYS)})")
    for key, amount in needs.items():
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not -1.0 <= amount <= 1.0:
            errors.append(f"activity {activity.name!r}: needs[{key!r}] must be a number in -1..1, got {amount!r}")
    return errors


def _spec_errors(spec: SettingSpec) -> List[str]:
    """Every piece of ``spec`` an engine would otherwise trip on mid-tick,
    named."""
    errors: List[str] = []
    if not isinstance(spec.key, str) or not spec.key.strip():
        errors.append("key must be a non-empty str")
    elif spec.key != spec.key.strip():
        errors.append(f"key {spec.key!r} must not start or end with whitespace (get_setting strips it)")
    for name in _LIST_FIELDS:
        value = getattr(spec, name)
        if not isinstance(value, (list, tuple)):
            errors.append(f"{name} must be a list, got {type(value).__name__}")
    for name in _DICT_FIELDS:
        value = getattr(spec, name)
        if not isinstance(value, dict):
            errors.append(f"{name} must be a dict, got {type(value).__name__}")

    if isinstance(spec.activities, (list, tuple)):
        seen = set()
        own = [activity for activity in spec.activities if isinstance(activity, Activity)]
        for activity in spec.activities:
            if not isinstance(activity, Activity):
                errors.append(f"activities holds a {type(activity).__name__}, not an Activity")
                continue
            if activity.name in seen:
                errors.append(f"activities has two named {activity.name!r}")
            seen.add(activity.name)
            errors.extend(_activity_shape_errors(activity, f"activity {activity.name!r}", "suitable_locations"))
            ids = activity.persona_ids
            if not isinstance(ids, (list, tuple)) or not all(isinstance(i, str) and i for i in ids):
                errors.append(
                    f"activity {activity.name!r}: persona_ids must be a list of persona ids, got {ids!r}"
                )
            tags = activity.tags
            if not isinstance(tags, (set, frozenset)):
                errors.append(f"activity {activity.name!r}: tags must be a frozenset of tags, got {tags!r}")
            elif set(tags) - set(ACTIVITY_TAGS):
                errors.append(f"activity {activity.name!r}: unknown tags {sorted(set(tags) - set(ACTIVITY_TAGS))} "
                              f"(ACTIVITY_TAGS: {sorted(ACTIVITY_TAGS)})")
            errors.extend(_needs_errors(activity))
            errors.extend(_outcomes_errors(activity))
        own_tags = set()
        for activity in own:
            if isinstance(activity.tags, (set, frozenset)):
                own_tags |= activity.tags
        for tag, universal in _universal_activities().items():
            carriers = [activity for activity in own if tag in activity.tags]
            if tag not in own_tags and universal.name in seen:
                errors.append(f"activity {universal.name!r} lacks the {tag!r} tag: the universal "
                              f"{universal.name!r} the setting would get for it has the same name")
            if carriers and all(activity.persona_ids for activity in carriers):
                errors.append(f"every activity tagged {tag!r} is restricted to persona ids "
                              f"({[a.name for a in carriers]}): the setting then gets no universal one, "
                              "so a persona none of them names could never do it")

    if isinstance(spec.npc_event_templates, dict):
        unknown = [kind for kind in spec.npc_event_templates if kind not in NPC_KINDS]
        if unknown:
            errors.append(f"npc_event_templates has kinds outside NPC_KINDS {NPC_KINDS}: {unknown}")
        for kind, by_type in spec.npc_event_templates.items():
            if not isinstance(by_type, dict):
                errors.append(f"npc_event_templates[{kind!r}] must map an event type to its templates")
                continue
            for event_type, templates in by_type.items():
                if not _is_text_list(templates):
                    errors.append(f"npc_event_templates[{kind!r}][{event_type!r}] must be a list of str, "
                                  f"got {templates!r}")

    entries_to_shape = []
    for name, keys in _ENTRY_KEYS.items():
        entries = getattr(spec, name)
        if not isinstance(entries, (list, tuple)):
            continue  # already reported above
        for index, entry in enumerate(entries):
            missing = [key for key in keys if not isinstance(entry, dict) or key not in entry]
            if missing:
                errors.append(f"{name}[{index}] has no {', '.join(repr(k) for k in missing)}")
            entries_to_shape.append((f"{name}[{index}]", entry))
    if isinstance(spec.want_follow_ups, dict):
        for activity_name, want in spec.want_follow_ups.items():
            if not isinstance(want, dict) or "title" not in want:
                errors.append(f"want_follow_ups[{activity_name!r}] has no 'title'")
            entries_to_shape.append((f"want_follow_ups[{activity_name!r}]", want))
    for label, entry in entries_to_shape:
        if not isinstance(entry, dict):
            continue  # already reported above
        for key in _ENTRY_LISTS:
            if entry.get(key) is not None and not _is_text_list(entry[key]):
                errors.append(f"{label}[{key!r}] must be a list of str, got {entry[key]!r}")
        for key in _ENTRY_DICTS:
            if entry.get(key) is not None and not isinstance(entry[key], dict):
                errors.append(f"{label}[{key!r}] must be a mapping, got {entry[key]!r}")

    for name in _TEXT_LIST_DICT_FIELDS:
        for key, value in _items(spec, name):
            if not _is_text_list(value):
                errors.append(f"{name}[{key!r}] must be a list of str, got {value!r}")
    for name in _EMOTION_DICT_FIELDS:
        for key, value in _items(spec, name):
            if not isinstance(value, dict):
                errors.append(f"{name}[{key!r}] must map an emotion to its intensity, got {value!r}")
    for name, (first, second) in _PAIR_FIELDS.items():
        for key, value in _items(spec, name):
            if not _is_pair(value, first, second):
                errors.append(f"{name}[{key!r}] must be a ({_type_names(first)}, {_type_names(second)}) "
                              f"pair, got {value!r}")
    for name, (first, second) in _PAIR_LIST_FIELDS.items():
        for key, value in _items(spec, name):
            if not isinstance(value, (list, tuple)) or not all(_is_pair(pair, first, second) for pair in value):
                errors.append(f"{name}[{key!r}] must be a list of ({_type_names(first)}, "
                              f"{_type_names(second)}) pairs, got {value!r}")
    for name in _WEATHER_KEYED_FIELDS:
        strays = [key for key, _ in _items(spec, name) if not isinstance(key, Weather)]
        if strays:
            errors.append(f"{name} must be keyed by Weather members (Weather.RAINY, not 'rainy'), "
                          f"got {strays!r}")

    if isinstance(spec.name_tags, dict) and isinstance(spec.activities, (list, tuple)):
        own_names = {a.name for a in spec.activities if isinstance(a, Activity)}
        for name, tags in spec.name_tags.items():
            if name in own_names:
                errors.append(f"name_tags[{name!r}] names an activity: tag the activity itself")
            if not isinstance(tags, (set, frozenset)) or set(tags) - set(ACTIVITY_TAGS):
                errors.append(f"name_tags[{name!r}] must be a frozenset of ACTIVITY_TAGS, got {tags!r}")
    if isinstance(spec.tag_order, dict) and isinstance(spec.activities, (list, tuple)):
        tagged = {}
        for activity in spec.activities:
            if isinstance(activity, Activity) and isinstance(activity.tags, (set, frozenset)):
                for tag in activity.tags:
                    tagged.setdefault(tag, set()).add(activity.name)
        for tag, names in spec.tag_order.items():
            if tag not in ACTIVITY_TAGS:
                errors.append(f"tag_order has an unknown tag {tag!r}")
            elif not isinstance(names, (list, tuple)):
                errors.append(f"tag_order[{tag!r}] must be a list of activity names, got {names!r}")
            else:
                strays = [name for name in names if name not in tagged.get(tag, set())]
                if strays:
                    errors.append(f"tag_order[{tag!r}] lists {strays}: no activity of this setting "
                                  f"with that name carries {tag!r}")

    if spec.intimate_activities is not None:
        if not isinstance(spec.intimate_activities, (list, tuple)):
            errors.append(f"intimate_activities must be a list or None, got {type(spec.intimate_activities).__name__}")
        else:
            for activity in spec.intimate_activities:
                if not isinstance(activity, IntimateActivity):
                    errors.append(f"intimate_activities holds a {type(activity).__name__}, not an IntimateActivity")
                else:
                    errors.extend(_activity_shape_errors(
                        activity, f"intimate activity {activity.name!r}", "preferred_locations"))

    if spec.holidays is not None and not callable(spec.holidays):
        errors.append("holidays must be a callable (nationality, year) -> {(month, day): name}, or None")
    if not isinstance(spec.catch_up, CatchUpNarratives):
        errors.append(f"catch_up must be a CatchUpNarratives, got {type(spec.catch_up).__name__}")
    else:
        for name in _CATCH_UP_LISTS:
            if not _is_text_list(getattr(spec.catch_up, name)):
                errors.append(f"catch_up.{name} must be a list of str, got {getattr(spec.catch_up, name)!r}")
        if not isinstance(spec.catch_up.by_activity, dict):
            errors.append(f"catch_up.by_activity must map an activity to its line, got {spec.catch_up.by_activity!r}")
    return errors


def register_setting(spec: SettingSpec, *, replace: bool = False) -> None:
    """Register a deep copy of ``spec`` under ``spec.key``.

    A key already registered is refused unless ``replace=True`` -- a shipped
    pack must never be overwritten by accident. The copy is what makes a pack
    derived from another (``dataclasses.replace`` shares every list) safe:
    changing either object afterwards touches neither the registry nor the
    pack it came from. Raises ``TypeError`` for anything but a
    :class:`SettingSpec`, and ``ValueError`` naming every piece an engine
    would otherwise trip on or never match (a string where a list belongs, at
    any depth; an activity with no narrative; a trigger, skill mapping,
    milestone or derived place that is not a pair; a weather's name where its
    ``Weather`` member belongs; two activities with one name, a
    ``persona_ids`` that is not a list of ids, an NPC kind outside
    ``NPC_KINDS``, a holiday calendar that is not callable ...)."""
    if not isinstance(spec, SettingSpec):
        raise TypeError(f"register_setting expects a SettingSpec, got {type(spec).__name__}")
    if spec.key in _REGISTRY and not replace:
        raise ValueError(f"Setting {spec.key!r} is already registered; pass replace=True to overwrite it")
    errors = _spec_errors(spec)
    if errors:
        raise ValueError(f"SettingSpec {spec.key!r} is not usable: " + "; ".join(errors))
    _REGISTRY[spec.key] = copy.deepcopy(spec)


def unregister_setting(key: str) -> bool:
    """Drop ``key`` from the registry. True if it was registered.

    :data:`DEFAULT_SETTING` cannot be dropped -- every persona with no
    setting lives in it -- and raises ``ValueError``; replace it with
    ``register_setting(spec, replace=True)`` instead."""
    if key == DEFAULT_SETTING:
        raise ValueError(
            f"{DEFAULT_SETTING!r} is the default setting and cannot be unregistered; "
            "register a replacement with replace=True instead"
        )
    return _REGISTRY.pop(key, None) is not None


def get_setting(key: Optional[str] = None) -> SettingSpec:
    """The registered setting ``key`` names. ``None`` or blank means
    :data:`DEFAULT_SETTING` (as an empty ``PersonalityDefinition.setting``
    does); surrounding whitespace is ignored. An unknown key raises
    ``ValueError`` naming it and every registered key."""
    if key is not None and not isinstance(key, str):
        raise TypeError(f"a setting key is a str, got {type(key).__name__}")
    name = (key or "").strip() or DEFAULT_SETTING
    spec = _REGISTRY.get(name)
    if spec is None:
        raise ValueError(f"Unknown setting {name!r}; registered settings: {', '.join(sorted(_REGISTRY))}")
    return spec
