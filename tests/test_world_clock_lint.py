"""No new wall-clock read in aura-life (humanness program Task 19, ruling
T19-R3: the spec's "no new ``datetime.now()``" as a test).

Her life is decided on the world clock (``LifeService._world_clock``; her
local world time, ``_local_world_now``, for her hours): an engine is handed
the instant (``now=``) and never reads a clock of its own. This scans the
syntax tree of every module in ``src/aura_life`` for a read of the host's
clock -- ``datetime.now``/``utcnow``/``today``, ``date.today``,
``time.time``/``monotonic``, called or passed as a value, under any name the
module imported them as -- and fails on a
function that reads one and is not in :data:`ALLOWED`, which names each
remaining function with its code and its one-line reason. An entry that no
longer reads the clock fails too: the list stays the tree's.

Codes (Task 28's audit, task-28-report.md; Task 19's rulings T19-R1/T19-R2):

* ``f`` -- the host's clock only when the caller passes no instant; every
  caller inside aura-life passes the world's (moved there by Task 19 where
  marked "T19").
* ``F`` -- a fallback with no in-library caller (a host-facing method).
* ``R`` -- real time by nature: the user's real conversation, calendar,
  device, a real timezone's offset.
* ``S`` -- a stamp on a tick path that no decision compares (out of Task
  19's scope, T19-R1).
* ``W`` -- her wants (the planner's desires), kept on the host's clock
  (task-28-report.md).
* ``X`` -- the transit machine: the host drives its phases on its own clock.
* ``C`` -- a construction or injected-clock default.
* ``E`` -- EmotionEngine's real-seconds clock (its public API is frozen).
* ``H`` -- the host's scheduler or its downtime.
* ``P`` -- a profile row's audit stamp.
"""

import ast
from pathlib import Path

import aura_life

SRC = Path(aura_life.__file__).parent

#: The reads: (the name the attribute is read on, the attribute).
CLOCK_READS = {("datetime", "now"), ("datetime", "utcnow"), ("datetime", "today"), ("date", "today"),
               ("time", "time"), ("time", "monotonic")}

T19 = "LifeService passes the world instant (T19); the host's clock only with none"
REAL_TALK = "real time by nature: the user's real conversation (messages arrive on the host's clock)"

#: "module:Qualname" -> (code, reason). Built from a scan of the tree at Task 19a's tip.
ALLOWED = {
    "activities.activity_engine:ActivityEngine.execute_activity": ("S", "an activity log's started_at/ended_at"),
    "affect.affect_system:AffectSystem._update_loneliness": ("f", "every caller passes the world instant"),
    "affect.affect_system:AffectSystem.on_social_interaction": ("f", "every caller passes the world instant"),
    "affect.affect_system:AffectSystem.on_stressor_resolved": ("S", "a resolved stressor's stamp"),
    "behavior.behavior_system:BehaviorSystem.add_possession": ("S", "a possession's acquired stamp"),
    "behavior.behavior_system:BehaviorSystem.export_state": ("f", "LifeService passes the world instant"),
    "behavior.behavior_system:BehaviorSystem.on_creative_activity": ("S", "an artifact's created stamp"),
    "behavior.behavior_system:BehaviorSystem.visit_place": ("S", "a place's last-visit stamp"),
    "body.body_system:BodySystem._decay_fitness": ("f", T19),
    "body.body_system:BodySystem._resolve_conditions": ("f", T19),
    "body.body_system:BodySystem.on_activity": ("f", T19 + " (a workout's stamp; the catch-up's passes none)"),
    "body.body_system:BodySystem.on_substance_activity": ("f", T19),
    "body.body_system:BodySystem.roll_daily_health": ("f", T19),
    "chaos.chaos_engine:ChaosEngine.roll": ("f", "LifeService passes her local world time (T19)"),
    "cognitive.cognitive_system:CognitiveSystem._add_rumination": ("S", "a rumination's started_at"),
    "cognitive.cognitive_system:CognitiveSystem._generate_monologue": ("f", T19),
    "cognitive.cognitive_system:CognitiveSystem.form_opinion": ("S", "an opinion's formed/reinforced stamps"),
    "cognitive.cognitive_system:CognitiveSystem.get_inner_monologue": ("f", T19 + "; a host caller should pass it"),
    "context.context_builder:LifeContextBuilder._build_behavior_section": (
        "f", "the service's world clock; the host's only for a builder with none"),
    "context.context_builder:LifeContextBuilder._build_calendar_section": ("R", "the user's own calendar"),
    "context.context_builder:LifeContextBuilder._build_trip_section": ("R", "a real timezone's offset"),
    "context.context_builder:LifeContextBuilder.format_time_ago": ("S", "'x minutes ago' against the logs' stamps"),
    "continuity.continuity_system:ContinuitySystem._record_milestone": ("S", "a milestone's date"),
    "continuity.continuity_system:ContinuitySystem.add_anniversary": ("S", "an anniversary's first occurrence"),
    "continuity.continuity_system:ContinuitySystem.daily_tick": ("f", "every caller passes the world instant"),
    "continuity.continuity_system:ContinuitySystem.get_upcoming_anniversaries": ("f", T19),
    "continuity.continuity_system:ContinuitySystem.monthly_tick": ("f", "every caller passes the world instant"),
    "continuity.continuity_system:ContinuitySystem.weekly_tick": ("f", "every caller passes the world instant"),
    "defaults:persona_now": ("C", "the persona_now hook's library default is the host's persona clock"),
    "drive.drive_system:DriveSystem.add_avoidance": ("S", "an avoidance's created_at"),
    "drive.drive_system:DriveSystem.on_activity": ("S", "a curiosity's created_at"),
    "drive.drive_system:DriveSystem.on_conversation_topic": ("R", REAL_TALK),
    "drive.drive_system:DriveSystem.process_conversation_trigger": ("R", REAL_TALK),
    "drive.drive_system:DriveSystem.tick": ("f", T19),
    "drive.drive_system:DriveSystem.track_activity_comfort": ("S", "a comfort zone's last attempt"),
    "emotion.emotion_engine:ActiveEmotion": ("E", "EmotionEngine's real seconds (LifeService decays by world seconds)"),
    "emotion.emotion_engine:EmotionEngine.__init__": ("E", "EmotionEngine's real seconds"),
    "emotion.emotion_engine:EmotionEngine._create_baseline": ("E", "EmotionEngine's real seconds"),
    "emotion.emotion_engine:EmotionEngine.add_emotion": ("E", "EmotionEngine's real seconds"),
    "emotion.emotion_engine:EmotionEngine.decay_tick": ("E", "EmotionEngine's real seconds"),
    "emotion.emotion_engine:EmotionEngine.reset_to_baseline": ("E", "EmotionEngine's real seconds"),
    "emotion.emotion_persistence:EmotionPersistence._load": ("f", T19),
    "emotion.emotion_persistence:EmotionPersistence.get_current_emotions": ("f", "a host caller should pass the world instant (T19)"),
    "emotion.emotion_persistence:EmotionPersistence.get_emotional_context": ("f", "a host caller should pass the world instant (T19)"),
    "emotion.emotion_persistence:EmotionPersistence.save_emotion": ("f", T19),
    "energy.energy_system:EnergySystem.__init__": ("C", "the default clock when none is injected (LifeService injects world.now)"),
    "energy.energy_system:EnergySystem.from_dict": ("C", "the default clock when none is injected"),
    "errands.errands_system:ErrandsSystem.tick": ("f", "every caller passes the world instant"),
    "expression.expression_system:ExpressionSystem.on_user_message": ("R", REAL_TALK),
    "expression.expression_system:ExpressionSystem.tick": ("R", "time since the user last wrote"),
    "goals.goal_engine:GoalEngine._abandon_goal": ("f", T19),
    "goals.goal_engine:GoalEngine._complete_goal": ("f", T19),
    "goals.goal_engine:GoalEngine._pick_up_new_goal": ("f", T19),
    "goals.goal_engine:GoalEngine.check_goal_completion": ("f", T19),
    "goals.goal_engine:GoalEngine.evaluate_motivation": ("f", T19),
    "goals.goal_engine:GoalEngine.generate_daily_goal": ("f", T19),
    "goals.goal_engine:GoalEngine.generate_goal_from_activity": ("f", T19),
    "goals.goal_engine:GoalEngine.get_emotional_context": ("f", T19 + "; a host caller should pass it"),
    "goals.goal_engine:GoalEngine.goalless_hours": ("f", T19 + " (the goalless_duration_hours property passes none)"),
    "goals.goal_engine:GoalEngine.load_goals": ("f", T19),
    "goals.goal_engine:GoalEngine.update_progress_from_activity": ("f", T19 + " (the catch-up's passes none)"),
    "identity.identity_system:IdentitySystem.__init__": ("S", "a value's formed_at, at construction"),
    "identity.identity_system:IdentitySystem.add_inside_joke": ("R", "an inside joke with the user"),
    "identity.identity_system:IdentitySystem.tick_tendencies": ("S", "a tendency's stamp"),
    "identity.identity_system:IdentitySystem.update_from_activity": ("S", "a facet's stamp"),
    "identity.identity_system:IdentitySystem.update_from_social_event": ("S", "a memory's stamp"),
    "identity.identity_system:IdentitySystem.update_from_user_message": ("R", REAL_TALK),
    "intimacy.desire_system:DesireSystem.add_arousal": ("S", "the last intimate thought's stamp"),
    "intimacy.desire_system:DesireSystem.execute_intimate_activity": ("f", T19),
    "intimacy.desire_system:DesireSystem.tick": ("f", T19),
    "job.career_system:CareerSystem.is_working_now": ("f", "every caller passes the world instant"),
    "job.career_system:CareerSystem.tick": ("f", "every caller passes the world instant"),
    "life_events.life_event_system:LifeEventSystem.mark_shared": ("f", "LifeService passes the instant (T17-R5)"),
    "life_events.life_event_system:LifeEventSystem.record_event": ("S", "a life event's created_at"),
    "life_service:LifeService._activity_tick": ("R", "the user-chat window; an intimate log's started_at (S)"),
    "life_service:LifeService._bridge_life_event": ("R", "paces proactive messages a real user receives"),
    "life_service:LifeService._create_shareable": ("S", "a shareable's created_at"),
    "life_service:LifeService._create_shareable_from_text": ("S", "a shareable's created_at"),
    "life_service:LifeService._evaluate_life_triggers": ("R", "paces proactive messages a real user receives"),
    "life_service:LifeService._load_state": ("C", "a first-load default row's last_update"),
    "life_service:LifeService._load_transit": ("X", "the transit's fast-forward on reload, on the clock its host drives"),
    "life_service:LifeService._save_shareable": (
        "R", "retention cutoff against shared_at, stamped when the user heard it (real time)"),
    "life_service:LifeService._scan_calendar_for_triggers": ("R", "the user's calendar"),
    "life_service:LifeService._share_excitement": ("R", "paces proactive messages a real user receives"),
    "life_service:LifeService._update_trip": ("f", "_on_world_tick passes the world instant (T19)"),
    "life_service:LifeService._world_clock": ("C", "a duck-typed world with no now(): the wall clock"),
    "life_service:LifeService.add_calendar_entry": ("R", "the user's own calendar"),
    "life_service:LifeService.advance_transit_phase": ("X", "the host drives the transit's phases on its clock"),
    "life_service:LifeService.begin_transit": ("X", "the host drives the transit's phases on its clock"),
    "life_service:LifeService.catch_up_from_downtime": ("H", "the host process's downtime (the gap)"),
    "life_service:LifeService.effective_current_activity": ("R", REAL_TALK),
    "life_service:LifeService.force_wake": ("R", "the wake button, pressed in real time"),
    "life_service:LifeService.get_upcoming_calendar_entries": ("R", "the user's own calendar"),
    "life_service:LifeService.is_asleep": ("R", "the wake button's window"),
    "life_service:LifeService.is_forced_wake_fresh": ("R", "the wake button's window"),
    "life_service:LifeService.mark_experience_shared": ("R", "the user heard it now"),
    "life_service:LifeService.observe_user_turn": ("R", REAL_TALK),
    "life_service:LifeService.set_conversation_activity": ("R", REAL_TALK),
    "life_service:LifeService.wrapup_due": ("R", "an active chat that went quiet"),
    "location.device_location:save_device_location": ("R", "the device's real location update"),
    "location.location_system:LocationSystem.record_visit": ("f", "its caller passes her local world time (T19)"),
    "location.place_service:PlaceService.server_local_offset_hours": ("R", "the server's real UTC offset"),
    "location.place_service:_tz_offset_hours": ("R", "a real timezone's current UTC offset"),
    "memory_time.memory_time_system:MemoryTimeSystem._check_nostalgia": ("f", "every caller passes the world instant"),
    "memory_time.memory_time_system:MemoryTimeSystem._detect_weekly_rhythm": ("f", "every caller passes the world instant"),
    "memory_time.memory_time_system:MemoryTimeSystem._update_time_perception": ("f", "every caller passes the world instant"),
    "memory_time.memory_time_system:MemoryTimeSystem.add_life_chapter": ("f", "every caller passes the world instant"),
    "memory_time.memory_time_system:MemoryTimeSystem.get_anticipations": ("f", T19),
    "memory_time.memory_time_system:MemoryTimeSystem.on_activity": ("S", "an activity's stamp"),
    "memory_time.memory_time_system:MemoryTimeSystem.on_user_message": ("R", REAL_TALK),
    "models:ActivityLog.from_dict": ("C", "a saved row with no stamp"),
    "models:DailyPlan.from_dict": ("C", "a saved row with no stamp (never read)"),
    "models:DailyPlan.get_current_slot": ("f", "every caller in aura-life passes her local world time (Task 28)"),
    "models:DailyPlan.get_next_slot": ("f", "every caller in aura-life passes her local world time (Task 28)"),
    "models:DailyPlan.get_remaining_slots": ("f", "every caller in aura-life passes her local world time (Task 28)"),
    "models:Goal.from_dict": ("C", "a saved row with no stamp"),
    "models:LifeEvent.from_dict": ("C", "a saved row with no stamp"),
    "models:ShareableExperience.from_dict": ("C", "a saved row with no stamp"),
    "models:ShortTermDesire.from_dict": ("C", "a saved row with no stamp"),
    "models:TransitState.minutes_until_arrival": ("X", "the transit machine, on the clock its host drives"),
    "models:_now": ("C", "a record made without a time: this module's datetime, as a simulation freezes it"),
    "money.finance_system:FinanceSystem.__init__": ("f", "every caller passes the world instant"),
    "money.finance_system:FinanceSystem.tick": ("f", "every caller passes the world instant"),
    "persona_evolution.character_evolution:CharacterEvolution.monthly_evolution": ("f", "every caller passes the world instant"),
    "personas.profile_db:ProfileDatabase.save_from_create_request": ("P", "a profile row's audit stamp"),
    "personas.profile_db:ProfileDatabase.save_from_parsed_profile": ("P", "a profile row's audit stamp"),
    "personas.profile_db:ProfileDatabase.update_appearance": ("P", "a profile row's audit stamp"),
    "personas.profile_db:ProfileDatabase.update_appearance_origin": ("P", "a profile row's audit stamp"),
    "personas.profile_db:ProfileDatabase.update_cultural_stance": ("P", "a profile row's audit stamp"),
    "personas.profile_db:ProfileDatabase.update_field": ("P", "a profile row's audit stamp"),
    "personas.profile_db:ProfileDatabase.update_home_location": ("P", "a profile row's audit stamp"),
    "planner.daily_planner:DailyPlanner._generate_ai_plan": ("f", "the plan's day (f) and created_at (S, never read)"),
    "planner.daily_planner:DailyPlanner._is_expired": ("W", "her wants stay on the host's clock"),
    "planner.daily_planner:DailyPlanner._refresh_desires": ("W", "her wants stay on the host's clock"),
    "planner.daily_planner:DailyPlanner.cancel_work_today": ("f", "LifeService passes her local world time"),
    "planner.daily_planner:DailyPlanner.export_state": ("f", "LifeService passes her local world time"),
    "planner.daily_planner:DailyPlanner.fulfill_desire": ("W", "her wants stay on the host's clock"),
    "planner.daily_planner:DailyPlanner.generate_daily_plan": ("f", "the plan's day (f) and created_at (S, never read)"),
    "planner.daily_planner:DailyPlanner.generate_desire_from_activity": ("W", "her wants stay on the host's clock"),
    "planner.daily_planner:DailyPlanner.needs_new_plan": ("f", "LifeService passes her local world time"),
    "planner.daily_planner:DailyPlanner.revise_upcoming": ("f", "LifeService passes her local world time"),
    "planner.daily_planner:DailyPlanner.schedule_rendezvous": ("f", "LifeService passes her local world time"),
    "planner.daily_planner:DailyPlanner.set_planned_activity": ("f", "LifeService passes her local world time"),
    "planner.daily_planner:DailyPlanner.stay_at_current_location": ("f", "LifeService passes her local world time"),
    "schedule:PersonaSchedule.get_upcoming_events": ("F", "host-facing PersonaSchedule, not reached from a tick"),
    "schedule:ScheduledEvent.get_next_occurrence": ("F", "host-facing PersonaSchedule, not reached from a tick"),
    "schedule:ScheduledEvent.should_share_now": ("F", "host-facing PersonaSchedule, not reached from a tick"),
    "scheduler.life_scheduler:LifeScheduler._activity_tick_wrapper": ("H", "host scheduler bookkeeping"),
    "scheduler.life_scheduler:LifeScheduler._energy_tick_wrapper": ("H", "host scheduler bookkeeping"),
    "scheduler.life_scheduler:LifeScheduler._goal_tick_wrapper": ("H", "host scheduler bookkeeping"),
    "scheduler.life_scheduler:LifeScheduler._plan_tick_wrapper": ("H", "host scheduler bookkeeping"),
    "scheduler.life_scheduler:LifeScheduler._world_tick_wrapper": ("H", "host scheduler bookkeeping"),
    "scheduler.life_scheduler:LifeScheduler.force_tick": ("H", "when the host's scheduler ran a tick"),
    "shadow.shadow_system:ShadowSystem.tick": ("S", "a shadow event's stamp"),
    "skills.skills_system:SkillsSystem.practice": ("S", "a practice's stamp"),
    "social.social_system:SocialSystem._generate_event": ("f", T19),
    "social.social_system:SocialSystem.add_obligation": ("f", "no caller in aura-life; a host passes the instant"),
    "social.social_system:SocialSystem.add_plan": ("f", T19),
    "social.social_system:SocialSystem.export_state": ("f", "LifeService passes the world instant"),
    "social.social_system:SocialSystem.resolve_conflict": ("f", "no caller in aura-life; a host passes the instant"),
    "social.social_system:SocialSystem.tick": ("f", T19),
    "social.social_system:SocialSystem.tick_arcs": ("f", T19),
    "social.social_system:SocialSystem.tick_conflicts": ("f", T19),
    "social.social_system:SocialSystem.tick_obligations": ("f", T19),
    "social.social_system:SocialSystem.trigger_conflict": ("f", "no caller in aura-life; a host passes the instant"),
    "social.social_system:SocialSystem.update_arc": ("f", T19),
    "sustenance.sustenance_system:SustenanceSystem.on_activity": ("f", "every caller passes the world instant"),
    "transportation.transport_system:TransportSystem.estimate": ("X", "its one caller, begin_transit, is the transit machine"),
    "world.environment:WorldEnvironment.__init__": ("C", "the default clock when none is injected"),
}

CODES = set("fFRSWXCEHPL")


def _aliases(tree: ast.AST) -> tuple:
    """The module's names for the clock's owners and functions (Task 19 fix
    round 1, M2): ``import time as _clock`` makes ``_clock`` "time",
    ``from datetime import datetime as _dt`` makes ``_dt`` "datetime"; and
    each name a clock function is imported under (``from time import
    monotonic``, ``... time as _now``) -> its read, a bare name being one."""
    owners, functions = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("time", "datetime") and alias.asname:
                    owners[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module in ("time", "datetime"):
            for alias in node.names:
                local = alias.asname or alias.name
                if node.module == "datetime" and alias.name in ("datetime", "date"):
                    owners[local] = alias.name
                elif (node.module, alias.name) in CLOCK_READS:
                    functions[local] = (node.module, alias.name)
    return owners, functions


def _reads(tree: ast.AST) -> dict:
    """Qualified function name -> how many wall-clock reads it holds, under
    whatever name the module imported the clock as (:func:`_aliases`)."""
    found = {}
    stack = []
    owners, functions = _aliases(tree)

    def count():
        key = ".".join(stack) or "<module>"
        found[key] = found.get(key, 0) + 1

    class Visitor(ast.NodeVisitor):
        def _scope(self, node):
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scope

        def visit_Attribute(self, node):
            base = node.value
            name = (owners.get(base.id, base.id) if isinstance(base, ast.Name)
                    else base.attr if isinstance(base, ast.Attribute) else None)
            if (name, node.attr) in CLOCK_READS:
                count()
            self.generic_visit(node)

        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load) and node.id in functions:
                count()

    Visitor().visit(tree)
    return found


def scan(src: Path = SRC) -> dict:
    """"module:Qualname" -> reads, for every module under ``src``."""
    result = {}
    for path in sorted(src.rglob("*.py")):
        module = ".".join(path.relative_to(src).with_suffix("").parts)
        for qualname, count in _reads(ast.parse(path.read_text(encoding="utf-8"))).items():
            result[f"{module}:{qualname}"] = count
    return result


def test_every_wall_clock_read_is_in_the_allow_list():
    """A function that reads the host's clock and is not in ALLOWED fails:
    an engine is handed the world's instant (T19-R2); a read that must stay
    is added to ALLOWED with its code and its reason."""
    unlisted = sorted(set(scan()) - set(ALLOWED))
    assert not unlisted, f"wall-clock reads outside the allow-list (pass the world's instant): {unlisted}"


def test_the_allow_list_is_the_tree_s():
    """An entry whose function no longer reads the clock leaves the list,
    and each names its code and a reason."""
    stale = sorted(set(ALLOWED) - set(scan()))
    assert not stale, f"allow-list entries that read no clock any more: {stale}"
    assert all(code in CODES and reason for code, reason in ALLOWED.values())


def test_the_scan_sees_every_form_of_a_read(tmp_path):
    """The scan finds a called read, one passed as a value, and each name."""
    (tmp_path / "m.py").write_text(
        "import time\nfrom datetime import date, datetime\n"
        "def a():\n    return datetime.now()\n"
        "class K:\n    def b(self, now=None):\n        return now or datetime.now\n"
        "    def c(self):\n        return time.time() + time.monotonic()\n"
        "def d():\n    return date.today(), datetime.utcnow(), datetime.today()\n"
        "def e(now):\n    return now\n", encoding="utf-8")
    # Under another name (Task 19 fix round 1, M2): an aliased module or
    # class, and a function imported from time.
    (tmp_path / "n.py").write_text(
        "import time as _clock\nimport datetime as _datetime_module\n"
        "from datetime import datetime as _dt, date as _d\nfrom time import monotonic, time as _now\n"
        "def f():\n    return _clock.time()\n"
        "def g():\n    return _dt.now(), _d.today(), _datetime_module.datetime.now()\n"
        "def h():\n    return monotonic() + _now()\n"
        "def i(monotonic_like):\n    return monotonic_like\n", encoding="utf-8")
    assert scan(tmp_path) == {"m:a": 1, "m:K.b": 1, "m:K.c": 2, "m:d": 3, "n:f": 1, "n:g": 3, "n:h": 2}
