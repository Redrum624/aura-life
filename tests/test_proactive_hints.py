"""Proactive hints only with concrete detail (humanness Task 17).

Every follow-up trigger the service creates carries what moved her -- what,
where, who, when -- taken from an episode of her memory stream, a life event,
a plan slot or a calendar row; a trigger with no such detail is not created
(rulings T17-R2, T17-R3). Its hint is worded to her, in the second person,
with no number and no engine label (T17-R4; the Task 6 lint). The share id of
what the hint is about travels only to a host that says it takes one
(T17-R1), and marking a life event shared stamps the world clock's instant
(T17-R5).

Each type gets a golden example: the trigger the evaluator creates from one
concrete detail, checked word for word where the wording is the point.
``_only(svc, kind)`` lets one type through the cooldown gate the evaluator
asks before each candidate, so the others cannot win the pick.
"""

import random
import re
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from aura_life.life_service import LifeService
from aura_life.models import ActivityLog, CalendarEntry, LifeEvent, NostalgiaEvent, SocialEvent
from aura_life.world import WorldEnvironment

from conftest import freeze_host_clock
from test_render_lint import _check_rendered, _stress_words_problem

#: A Monday noon on the world clock.
T0 = datetime(2026, 10, 5, 12, 0)
#: The words a hint had before Task 17 that it must never carry again.
ENGINE_WORDS_RE = re.compile(r"\bintensity\b|\bweird/vivid\b|\(\s*\w+\s*\)", re.IGNORECASE)


class _Clock:
    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant


class _Host:
    """A host's follow-up manager that takes no share id (aura's and
    aura-desk's today): every ``create_trigger`` call, as keywords."""

    def __init__(self):
        self.calls = []

    def create_trigger(self, *args, **kwargs):
        if args:
            kwargs["trigger_type"] = args[0]
        self.calls.append(kwargs)

    def of(self, trigger_type: str) -> list:
        return [c for c in self.calls if c["trigger_type"] == trigger_type]


class _ShareIdHost(_Host):
    """A host that declares it takes the share id (ruling T17-R1)."""

    accepts_share_id = True


def _svc(tmp_path, *, host=None, name="nora", user_info=None, clock=None) -> LifeService:
    host = host if host is not None else _Host()
    clock = clock or _Clock(T0)
    svc = LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=name,
                      world_environment=WorldEnvironment(now=clock, seed=13),
                      rng=random.Random(13), follow_up_provider=lambda pid: host,
                      user_info=user_info if user_info is not None else {"name": "Robin"})
    svc._desire_system.should_do_intimate_activity = lambda *a, **k: False
    svc._test_host = host
    svc._test_clock = clock
    return svc


def _only(svc: LifeService, kind: str) -> None:
    """Let only ``kind`` through the evaluator's cooldown gate."""
    svc._life_trigger_cooled_down = lambda trigger_type, now: trigger_type == kind


def _assert_clean(hint: str) -> None:
    """The Task 6 lint over a hint addressed to her, and ruling T17-R4: no
    number, no engine label or snake_case key."""
    _check_rendered(hint, hint, is_second_person=True)
    assert _stress_words_problem(hint) is None, hint
    assert not re.search(r"\d", hint), hint
    assert not ENGINE_WORDS_RE.search(hint), hint


def _episode(svc, what, *, at=None, place="home", people=(), tags=("activity",), emotion=None):
    return svc._memory.record(at=at or svc._test_clock(), what=what, place=place, people=people,
                              emotion=emotion, tags=tags)


# ---------------------------------------------------------------- MOOD_SHIFT

def _mood_moved(svc) -> str:
    svc._affect._set_mood(0.8, 0.0)
    cur = svc._affect.mood.current_mood
    svc._prev_mood = "low" if cur != "low" else "calm"
    svc._prev_mood_intensity = 0.0
    assert svc._affect.mood.intensity >= 0.3
    return cur


def test_mood_shift_golden_carries_what_moved_her(tmp_path):
    svc = _svc(tmp_path)
    _episode(svc, "cooking a meal", people=("Roberta",), at=T0 - timedelta(days=1), emotion="warm")
    cur = _mood_moved(svc)
    _only(svc, "mood_shift")
    svc._evaluate_life_triggers()
    (call,) = svc._test_host.of("MOOD_SHIFT")
    assert call["prompt_hint"] == (
        f"You're feeling {cur} now. On your mind, from yesterday: cooking a meal at home with "
        f"Roberta, feeling warm. Reach out naturally — share how you're feeling or let it color "
        f"what you say."
    )
    assert call["context"] == "life_trigger:mood_shift" and call["topic"] == cur
    _assert_clean(call["prompt_hint"])


def test_what_a_hint_reads_of_her_mind_is_not_reinforced(tmp_path):
    """The episode a hint is made of is read, not recalled (rulings T17-R2,
    T12-R2; fix round 1, T17-RV4 a): its strength and last recall stay."""
    svc = _svc(tmp_path)
    _episode(svc, "cooking a meal", at=T0 - timedelta(days=1))
    before = [(e.id, e.strength, e.last_recalled) for e in svc._memory.episodes]
    _mood_moved(svc)
    _only(svc, "mood_shift")
    svc._evaluate_life_triggers()
    assert svc._test_host.of("MOOD_SHIFT")
    assert [(e.id, e.strength, e.last_recalled) for e in svc._memory.episodes] == before


def test_a_mood_shift_with_nothing_behind_it_is_not_a_trigger(tmp_path):
    svc = _svc(tmp_path)
    _mood_moved(svc)
    _only(svc, "mood_shift")
    svc._evaluate_life_triggers()
    assert svc._test_host.of("MOOD_SHIFT") == []


# ---------------------------------------------------------- LONELINESS_SPIKE

def _lonely(svc) -> None:
    svc._prev_loneliness = 0.0
    svc._affect.loneliness.level = 0.7


def test_loneliness_spike_golden_says_when_they_last_spoke(tmp_path):
    svc = _svc(tmp_path)
    svc._identity.note_user_turn(T0 - timedelta(days=3))
    _lonely(svc)
    _only(svc, "loneliness_spike")
    svc._evaluate_life_triggers()
    (call,) = svc._test_host.of("LONELINESS_SPIKE")
    assert call["prompt_hint"] == (
        "The last time you talked with Robin was three days ago, and you've been feeling really "
        "lonely. You want to hear from them — ask how their day is going, or share something to "
        "start a conversation."
    )
    _assert_clean(call["prompt_hint"])


def test_loneliness_with_no_last_turn_and_no_episode_is_not_a_trigger(tmp_path):
    svc = _svc(tmp_path)
    _lonely(svc)
    _only(svc, "loneliness_spike")
    svc._evaluate_life_triggers()
    assert svc._test_host.of("LONELINESS_SPIKE") == []


# --------------------------------------------------------------- DREAM_SHARE

def _dreamt(svc) -> None:
    """She wakes with a dream (``_generate_dream``'s draws forced: a dream
    is made, from her two last activities)."""
    svc._recent_activities = [ActivityLog(activity_name="reading"), ActivityLog(activity_name="yoga")]
    svc._service_rng.random = lambda: 0.0
    svc._on_woke()


def test_a_dream_is_an_episode_and_its_share_golden(tmp_path):
    host = _ShareIdHost()
    svc = _svc(tmp_path, host=host)
    _dreamt(svc)
    (dream,) = [e for e in svc._memory.episodes if "dream" in e.tags]
    (shared,) = svc.get_shareable_experiences()
    assert shared.share_id in dream.tags
    assert dream.what.startswith(("Dreamed you", "Had a", "Your dream")), dream.what
    _only(svc, "dream_share")
    svc._evaluate_life_triggers()
    (call,) = host.of("DREAM_SHARE")
    gist = dream.gist()
    assert call["prompt_hint"] == (
        f"A dream from earlier today is still with you: {gist} Share it casually, like "
        f"'I had the strangest dream last night...'"
    )
    assert call["share_id"] == shared.share_id
    _assert_clean(call["prompt_hint"])


def test_a_dream_residue_alone_is_not_a_dream_share(tmp_path):
    svc = _svc(tmp_path)
    svc._cognitive._dream_residue_emotion = "uneasy"
    svc._cognitive._dream_residue_intensity = 0.9
    _only(svc, "dream_share")
    svc._evaluate_life_triggers()
    assert svc._test_host.of("DREAM_SHARE") == []


def test_a_dream_of_thinking_about_them_names_them(tmp_path):
    """A dream of her activity "thinking about user" names the user, in the
    episode, the shareable and the hint (fix round 1, T17-RV2): the raw id
    is said as :meth:`LifeService._activity_for_display` says it."""
    svc = _svc(tmp_path)
    svc._recent_activities = [ActivityLog(activity_name="thinking about user"),
                              ActivityLog(activity_name="reading")]
    svc._service_rng.random = lambda: 0.0
    svc._service_rng.sample = lambda population, k: list(population)[:k]
    svc._service_rng.choice = lambda seq: seq[0]  # "Dreamed {subj} {was} {a} in some place made of {b}"
    svc._on_woke()
    (dream,) = [e for e in svc._memory.episodes if "dream" in e.tags]
    assert dream.what == "Dreamed you were thinking about Robin in some place made of reading"
    (shared,) = svc.get_shareable_experiences()
    assert "thinking about Robin" in shared.content and " user " not in f" {shared.content} "
    _only(svc, "dream_share")
    svc._evaluate_life_triggers()
    (call,) = svc._test_host.of("DREAM_SHARE")
    assert "thinking about Robin" in call["prompt_hint"]
    _assert_clean(call["prompt_hint"])


#: The dream template that puts an activity after "were"/"was" (her setting's
#: ``dream_templates``).
_WAS_TEMPLATE = "Dreamed {subj} {was} {a} in some place made of {b}"


def _dream_of(svc, activity, template=_WAS_TEMPLATE):
    """``_draw_dream``'s draws forced: a dream made of ``activity`` and
    reading, told by ``template``."""
    svc._recent_activities = [ActivityLog(activity_name=activity), ActivityLog(activity_name="reading")]
    svc._service_rng.random = lambda: 0.0
    svc._service_rng.sample = lambda population, k: list(population)[:k]
    svc._service_rng.choice = lambda seq: next(t for t in seq if t == template)
    return svc._draw_dream()


def test_a_dream_of_a_noun_named_activity_is_phrased(tmp_path):
    """Ruling T18-R8: an activity named by a thing is said by ``_doing``'s
    rule after "were" -- in the episode (second person) and the shareable
    (her pronouns) alike; was "Dreamed you were yoga"."""
    svc = _svc(tmp_path)
    _dream_of(svc, "yoga")  # the forced draws stay set for _on_woke
    svc._on_woke()
    (dream,) = [e for e in svc._memory.episodes if "dream" in e.tags]
    assert dream.what == "Dreamed you were in the middle of your yoga in some place made of reading"
    (shared,) = svc.get_shareable_experiences()
    assert shared.content == "Dreamed they were in the middle of their yoga in some place made of reading"


#: A dream's activity after "were" that is not phrased: a time of day or a
#: season said as if it were a verb, "your" before an article, or a word that
#: is no verb in -ing and no "in the middle of".
_DREAM_UNPHRASED_RE = re.compile(
    r"\bwere (?:dawn|morning|afternoon|evening|night|spring|summer|autumn|winter)\b|\byour (?:a|an|the) "
    r"|\bwere (?!in the middle of )(?!\w+ing\b)", re.IGNORECASE)


def test_every_activity_name_her_settings_know_is_phrased_in_a_dream(tmp_path):
    """Every activity name a registered setting knows (its activities and the
    universal ones, its routine slot names, its invitations), dreamt after
    "were", reads as something she was doing (ruling T18-R8)."""
    from aura_life.personas.pronoun_render import render_second_person
    from aura_life.settings import spec

    svc = _svc(tmp_path)
    checked = set()
    for setting in spec._REGISTRY.values():
        names = {a.name for a in setting.resolved_activities()}
        names |= set(setting.name_tags) | set(setting.invite_activities or ())
        for name in sorted(names):
            template, fields = _dream_of(svc, name)
            told = render_second_person(template, user=svc._user_info, **fields)
            assert not _DREAM_UNPHRASED_RE.search(told), (name, told)
            _check_rendered(told, told, is_second_person=True)
            checked.add(name)
    assert {"yoga", "morning shower", "a concert", "reading"} <= checked  # the catalogue was read


def test_a_fired_dream_is_not_offered_again(tmp_path):
    """Once a DREAM_SHARE fired, the same unshared dream is not offered again
    when the gate opens (fix round 1, T17-RV4 b)."""
    svc = _svc(tmp_path)
    _dreamt(svc)
    _only(svc, "dream_share")
    svc._evaluate_life_triggers()
    svc._evaluate_life_triggers()
    assert len(svc._test_host.of("DREAM_SHARE")) == 1, svc._test_host.calls


def test_a_dream_that_lost_the_pick_is_offered_later(tmp_path):
    """A dream that was only a candidate -- another trigger won the pick -- is
    still offered later (fix round 1, T17-RV4 c)."""
    svc = _svc(tmp_path)
    _dreamt(svc)
    svc._life_trigger_cooled_down = lambda trigger_type, now: trigger_type in ("dream_share", "chaos_event")
    _chaos(svc)
    _episode(svc, "You found a twenty on the sidewalk", tags=("chaos", "serendipity"))
    real_choices = svc._service_rng.choices
    svc._service_rng.choices = lambda population, weights=None, k=1: [
        c for c in population if c[0] == "chaos_event"][:1]
    svc._evaluate_life_triggers()
    assert svc._test_host.of("CHAOS_EVENT") and not svc._test_host.of("DREAM_SHARE")
    svc._service_rng.choices = real_choices
    _only(svc, "dream_share")
    svc._evaluate_life_triggers()
    assert len(svc._test_host.of("DREAM_SHARE")) == 1, svc._test_host.calls


def test_a_fired_dream_is_not_offered_again_after_a_restart(tmp_path):
    """What fired stays fired across a restart (fix round 1, T17-RV3): the
    hosts never mark a dream's shareable shared."""
    svc = _svc(tmp_path)
    _dreamt(svc)
    _only(svc, "dream_share")
    svc._evaluate_life_triggers()
    assert len(svc._test_host.of("DREAM_SHARE")) == 1
    again = _svc(tmp_path)
    again._load_state()  # what start() reads
    assert again._newest_episode("dream") is not None and again.get_shareable_experiences()
    _only(again, "dream_share")
    again._evaluate_life_triggers()
    assert again._test_host.of("DREAM_SHARE") == [], again._test_host.calls


def test_a_dream_already_shared_is_not_shared_again(tmp_path):
    svc = _svc(tmp_path)
    _dreamt(svc)
    (shared,) = svc.get_shareable_experiences()
    assert svc.mark_shared(shared.share_id)
    _only(svc, "dream_share")
    svc._evaluate_life_triggers()
    assert svc._test_host.of("DREAM_SHARE") == []


# --------------------------------------------------------------- CHAOS_EVENT

def _chaos(svc, text="Found a twenty on the sidewalk", kind="serendipity") -> None:
    svc._chaos.export_state = lambda: {"last_chaos_event": text, "last_chaos_type": kind}


def test_chaos_event_golden_is_its_episode(tmp_path):
    host = _ShareIdHost()
    svc = _svc(tmp_path, host=host)
    _chaos(svc)
    _episode(svc, "You found a twenty on the sidewalk", place="park",
             tags=("chaos", "serendipity", "share:4", "event:2"))
    _only(svc, "chaos_event")
    svc._evaluate_life_triggers()
    (call,) = host.of("CHAOS_EVENT")
    assert call["prompt_hint"] == (
        "Something happened earlier today: You found a twenty on the sidewalk at the park. "
        "Share it like you'd tell a friend about your day."
    )
    assert call["share_id"] == "share:4"
    _assert_clean(call["prompt_hint"])


def test_a_chaos_event_she_has_no_memory_of_is_not_a_trigger(tmp_path):
    svc = _svc(tmp_path)
    _chaos(svc)
    _only(svc, "chaos_event")
    svc._evaluate_life_triggers()
    assert svc._test_host.of("CHAOS_EVENT") == []


# ----------------------------------------------------------------- NOSTALGIA

def test_nostalgia_golden(tmp_path):
    svc = _svc(tmp_path)
    svc._memory_time._nostalgia_log.append(NostalgiaEvent(
        trigger="smell", memory_reference="the smell of {poss} mom's kitchen on a Sunday",
        intensity=0.6, timestamp=T0))
    _only(svc, "nostalgia")
    svc._evaluate_life_triggers()
    (call,) = svc._test_host.of("NOSTALGIA")
    assert call["prompt_hint"] == (
        "A memory hit you — the smell of your mom's kitchen on a Sunday. Share the feeling with "
        "them, maybe ask if they've had moments like that."
    )
    _assert_clean(call["prompt_hint"])


# ------------------------------------------------------------ GOAL_MILESTONE

def test_goal_milestone_golden_on_a_completion(tmp_path):
    host = _ShareIdHost()
    svc = _svc(tmp_path, host=host)
    event = svc._life_events.record_event(event_type="achievement", title="Completed: Learn the chords",
                                          description="Every open chord, cleanly", share_urgency=0.8)
    svc._remember("finishing “Learn the chords”", place="", emotions={"proud": 0.6},
                  tags=("goal", "completed", event.share_id))
    _only(svc, "goal_milestone")
    svc._evaluate_life_triggers()
    (call,) = host.of("GOAL_MILESTONE")
    assert call["prompt_hint"] == (
        "You reached a goal earlier today: finishing “Learn the chords”, feeling proud. You had set "
        "out to do this: Every open chord, cleanly. Name the ONE concrete thing that actually moved "
        "it (a specific step you took, a real obstacle you got past) — never a vague 'epiphany' or "
        "'I cracked the code'."
    )
    assert call["share_id"] == event.share_id
    _assert_clean(call["prompt_hint"])


def test_a_fired_goal_completion_is_not_offered_again_after_a_restart(tmp_path):
    """The completion fired once; the service restarts on the same database
    days later (neither host marks the life event shared): it is not offered
    again (fix round 1, T17-RV3)."""
    clock = _Clock(T0)
    svc = _svc(tmp_path, clock=clock)
    event = svc._life_events.record_event(event_type="achievement", title="Completed: Learn the chords",
                                          description="Every open chord, cleanly", share_urgency=0.8)
    svc._remember("finishing “Learn the chords”", place="", emotions={"proud": 0.6},
                  tags=("goal", "completed", event.share_id))
    svc._save_life_events()
    _only(svc, "goal_milestone")
    svc._evaluate_life_triggers()
    svc._evaluate_life_triggers()
    assert len(svc._test_host.of("GOAL_MILESTONE")) == 1
    clock.instant = T0 + timedelta(days=4)
    again = _svc(tmp_path, clock=clock)
    again._load_state()  # what start() reads
    assert again._newest_episode("goal", "completed") is not None
    assert [e.share_id for e in again._life_events.get_unshared_events()] == [event.share_id]
    _only(again, "goal_milestone")
    again._evaluate_life_triggers()
    assert again._test_host.of("GOAL_MILESTONE") == [], again._test_host.calls


def test_goal_milestone_names_the_goal_she_is_losing_faith_in(tmp_path):
    from aura_life.models import Goal, GoalTimeframe
    svc = _svc(tmp_path)
    svc._goal_engine._active_goals = [Goal(title="Run a half marathon", timeframe=GoalTimeframe.WEEKLY,
                                           motivation_level=0.4)]
    _only(svc, "goal_milestone")
    svc._evaluate_life_triggers()
    (call,) = svc._test_host.of("GOAL_MILESTONE")
    assert "'Run a half marathon'" in call["prompt_hint"], call["prompt_hint"]
    _assert_clean(call["prompt_hint"])


def test_no_goal_at_all_is_not_a_goal_milestone(tmp_path):
    svc = _svc(tmp_path)
    svc._goal_engine._active_goals = []
    assert svc._goal_engine.get_emotional_context()  # the goalless line, which names nothing
    _only(svc, "goal_milestone")
    svc._evaluate_life_triggers()
    assert svc._test_host.of("GOAL_MILESTONE") == []


# -------------------------------------------------------------- SOCIAL_EVENT

def test_social_event_golden_is_its_episode(tmp_path):
    host = _ShareIdHost()
    svc = _svc(tmp_path, host=host)
    event = SocialEvent(npc_name="Mara", event_type="call", description="Mara called her with news",
                        share_worthy=True, kind="friend", valence=1.0)
    svc._on_social_event(event, ActivityLog(activity_name="reading", location="home"), "reading")
    svc._social._recent_events.append(event)
    _only(svc, "social_event")
    svc._evaluate_life_triggers()
    (call,) = host.of("SOCIAL_EVENT")
    (shared,) = svc.get_shareable_experiences()
    assert call["prompt_hint"] == (
        "Something happened with Mara earlier today: a call from Mara at home. Share it naturally."
    )
    assert call["share_id"] == shared.share_id
    _assert_clean(call["prompt_hint"])


def test_a_social_event_she_has_no_memory_of_is_not_a_trigger(tmp_path):
    svc = _svc(tmp_path)
    svc._social._recent_events.append(SocialEvent(npc_name="Mara", event_type="call",
                                                  description="Mara called", share_worthy=True,
                                                  kind="friend", valence=1.0))
    _only(svc, "social_event")
    svc._evaluate_life_triggers()
    assert svc._test_host.of("SOCIAL_EVENT") == []


# --------------------------------------------------------------- NEED_DRIVEN

def test_need_driven_golden_carries_what_moved_her(tmp_path):
    svc = _svc(tmp_path)
    _episode(svc, "reading", at=T0 - timedelta(hours=2))
    svc.assess_needs = lambda: {"stimulation": {"satisfaction": 0.1}}
    _only(svc, "need_driven")
    svc._evaluate_life_triggers()
    (call,) = svc._test_host.of("NEED_DRIVEN")
    assert call["prompt_hint"] == (
        "You're bored and restless. On your mind, from earlier today: reading at home. Start an "
        "interesting conversation or ask them something thought-provoking."
    )
    _assert_clean(call["prompt_hint"])


def test_a_need_for_connection_says_when_they_last_spoke(tmp_path):
    svc = _svc(tmp_path)
    svc._identity.note_user_turn(T0 - timedelta(days=1))
    svc.assess_needs = lambda: {"connection": {"satisfaction": 0.1}}
    _only(svc, "need_driven")
    svc._evaluate_life_triggers()
    (call,) = svc._test_host.of("NEED_DRIVEN")
    assert call["prompt_hint"] == (
        "You're craving connection. The last time you talked with Robin was yesterday. Reach out warmly."
    )
    _assert_clean(call["prompt_hint"])


def test_a_need_with_nothing_behind_it_is_not_a_trigger(tmp_path):
    svc = _svc(tmp_path)
    svc.assess_needs = lambda: {"stimulation": {"satisfaction": 0.1}}
    _only(svc, "need_driven")
    svc._evaluate_life_triggers()
    assert svc._test_host.of("NEED_DRIVEN") == []


# ------------------------------------------------------------- LIFE_QUESTION

def _quiet_mind(svc) -> None:
    svc._cognitive._ruminations = []
    svc._cognitive.get_opinions_for_context = lambda n: []
    svc._cognitive.get_inner_monologue = lambda **kw: None
    svc._drive.get_active_curiosities = lambda n: []
    svc._affect.loneliness.level = 0.0


def test_life_question_golden_on_a_curiosity(tmp_path):
    svc = _svc(tmp_path)
    _quiet_mind(svc)
    svc._drive.get_active_curiosities = lambda n: [SimpleNamespace(topic="the deep sea", intensity=0.8)]
    _only(svc, "life_question")
    svc._evaluate_life_triggers()
    (call,) = svc._test_host.of("LIFE_QUESTION")
    assert call["prompt_hint"] == (
        "You've gotten curious about 'the deep sea'. Ask if they know anything about it or have thoughts."
    )
    _assert_clean(call["prompt_hint"])


def test_life_question_self_doubt_carries_what_moved_her(tmp_path):
    svc = _svc(tmp_path)
    _quiet_mind(svc)
    svc._identity.self_esteem.level = 0.2
    _episode(svc, "botching the presentation", place="office", at=T0 - timedelta(days=1))
    _only(svc, "life_question")
    svc._evaluate_life_triggers()
    (call,) = svc._test_host.of("LIFE_QUESTION")
    assert call["prompt_hint"] == (
        "You've been second-guessing yourself. On your mind, from yesterday: botching the "
        "presentation at the office. Ask for their honest perspective on something you're unsure about."
    )
    _assert_clean(call["prompt_hint"])


def test_life_question_with_no_detail_is_not_a_trigger(tmp_path):
    svc = _svc(tmp_path)
    _quiet_mind(svc)
    svc._identity.self_esteem.level = 0.2
    svc._affect.loneliness.level = 0.6
    _only(svc, "life_question")
    svc._evaluate_life_triggers()
    assert svc._test_host.of("LIFE_QUESTION") == []


# -------------------------------------------------------------- MOMENT_SHARE

def _slot(svc, activity, location) -> None:
    slot = SimpleNamespace(activity_name=activity, location=location)
    svc._daily_planner._current_plan = SimpleNamespace(get_current_slot=lambda now=None: slot, slots=[],
                                                        date="today")
    _chaos(svc, text="A rainbow over the gym")  # a new chaos text: worth a moment share
    svc._last_user_message_at = None


@pytest.mark.parametrize("activity,location,doing", [
    ("yoga", "gym", "You're in the middle of your yoga at the gym"),
    ("reading", "home", "You're reading at home"),
    ("picnic in the park", "", "You're in the middle of your picnic in the park"),
    # Fix round 1 (T17-RV1): a first word in -ing that names a time of day
    # is not a verb, and a name with its own article takes no "your".
    ("morning shower", "home", "You're in the middle of your morning shower at home"),
    ("a concert", "", "You're in the middle of a concert"),
])
def test_moment_share_golden_phrases_the_activity(tmp_path, activity, location, doing):
    svc = _svc(tmp_path)
    _slot(svc, activity, location)
    _only(svc, "moment_share")
    svc._evaluate_life_triggers()
    (call,) = svc._test_host.of("MOMENT_SHARE")
    assert call["prompt_hint"] == (
        f"{doing} right now and it feels worth sharing. Send a short excited message about it, "
        f"like texting a photo to someone you like."
    )
    assert call["topic"] == activity
    _assert_clean(call["prompt_hint"])


def test_moment_share_attention_golden_phrases_the_activity(tmp_path):
    """The attention flavour says the slot the same way (fix round 1, T17-RV1)."""
    svc = _svc(tmp_path)
    _slot(svc, "morning shower", "home")
    svc._shadow.get_status = lambda: {"attention_seeking": 0.9}
    _only(svc, "moment_share")
    svc._evaluate_life_triggers()
    (call,) = svc._test_host.of("MOMENT_SHARE")
    assert call["prompt_hint"].startswith(
        "You're feeling a pull to be noticed right now. You're in the middle of your morning shower "
        "at home, and you want a little attention — "
    ), call["prompt_hint"]


#: What a slot's name must never read as after ``_doing`` (T17-R4): a time of
#: day or a season said as if it were a verb, or "your" before an article.
_UNPHRASED_RE = re.compile(
    r"^You're (?:dawn|morning|afternoon|evening|night|spring|summer|autumn|winter)\b|\byour (?:a|an|the) ",
    re.IGNORECASE)


def test_every_name_her_settings_know_is_phrased():
    """Every name a plan slot can carry that a registered setting knows -- its
    activities and the universal ones, its routine slot names (``name_tags``)
    and its invitations -- reads as something she does (fix round 1,
    T17-RV1: "morning shower" read "You're morning shower")."""
    from aura_life.life_service import _doing
    from aura_life.settings import spec

    checked = set()
    for setting in spec._REGISTRY.values():
        names = {a.name for a in setting.resolved_activities()}
        names |= set(setting.name_tags) | set(setting.invite_activities or ())
        for name in sorted(names):
            phrase = _doing(name)
            assert not _UNPHRASED_RE.search(phrase), (name, phrase)
            checked.add(name)
    assert {"morning shower", "a concert", "reading"} <= checked  # the catalogue was read


# ---------------------------------------------------------- EXCITEMENT_SHARE

def test_excitement_share_golden_is_the_event_s_episode(tmp_path):
    host = _ShareIdHost()
    svc = _svc(tmp_path, host=host)
    event = svc._life_events.record_event(event_type="achievement", title="Finished reading Dune",
                                          description="Just finished the last page of Dune",
                                          emotional_impact={"satisfied": 0.3}, share_urgency=0.7)
    svc._bridge_life_event(event)
    assert host.of("EXCITEMENT_SHARE") == []  # not before her memory of it
    svc._remember("finishing “Dune”", place="home", emotions={"satisfied": 0.3},
                  tags=("book", event.share_id))
    (call,) = host.of("EXCITEMENT_SHARE")
    assert call["prompt_hint"] == (
        "Something happened earlier today that you're excited about: finishing “Dune” at home, "
        "feeling satisfied. Share the concrete detail — what actually happened — not a vague "
        "'I had an epiphany' or 'I cracked the code'."
    )
    assert call["share_id"] == event.share_id
    assert call["topic"] == "Finished reading Dune"
    _assert_clean(call["prompt_hint"])


def test_an_excitement_share_starts_its_cooldown(tmp_path):
    """The EXCITEMENT_SHARE made when her memory of the event comes records
    the cooldown (fix round 1, T17-RV4: the record moved into
    ``_share_excitement``): a second event inside it makes none."""
    svc = _svc(tmp_path)
    for title in ("Finished reading Dune", "Baked the first loaf"):
        event = svc._life_events.record_event(event_type="achievement", title=title,
                                              description=title, share_urgency=0.7)
        svc._bridge_life_event(event)
        svc._remember(title.lower(), place="home", tags=("book", event.share_id))
    assert [c["topic"] for c in svc._test_host.of("EXCITEMENT_SHARE")] == ["Finished reading Dune"]


def test_a_mood_change_event_is_not_an_excitement_share(tmp_path):
    svc = _svc(tmp_path)
    event = svc._life_events.record_event(event_type="emotional", title="Mood shifted to happy",
                                          share_urgency=0.7, source="mood_change")
    svc._bridge_life_event(event)
    svc._remember("reading", tags=("activity",))
    assert svc._test_host.of("EXCITEMENT_SHARE") == []


def _completes(svc, title="Learn the chords") -> None:
    """Her goal tick finds one goal completed (the goal engine's own draws
    held still: no new daily goal, no motivation event)."""
    from aura_life.models import Goal, GoalTimeframe
    goal = Goal(title=title, description="Every open chord, cleanly", timeframe=GoalTimeframe.WEEKLY)
    # Each stand-in takes the world's instant the goal tick hands the engine
    # (``now=``, Task 19a's sweep): a stand-in without it fails the tick.
    svc._goal_engine.generate_daily_goal = lambda **kw: None
    svc._goal_engine.check_goal_completion = lambda **kw: [goal]
    svc._goal_engine.evaluate_motivation = lambda **kw: []
    svc._on_goal_tick()


def test_one_goal_completion_gives_one_trigger(tmp_path):
    """Ruling T17-R6: a completion is told once -- its GOAL_MILESTONE, never an
    EXCITEMENT_SHARE of its life event as well (a host dedups only on type and
    topic, so she would tell the same news twice)."""
    svc = _svc(tmp_path)
    svc._life_trigger_cooled_down = lambda trigger_type, now: trigger_type in (
        "excitement_share", "goal_milestone")
    _completes(svc)
    svc._evaluate_life_triggers()
    assert [c["trigger_type"] for c in svc._test_host.calls] == ["GOAL_MILESTONE"], svc._test_host.calls


def test_another_life_event_of_a_completion_s_urgency_is_still_an_excitement_share(tmp_path):
    """The other side of T17-R6: a life event that is not a goal completion,
    at the completion's urgency (``_on_goal_tick``'s 0.8), still waits for
    her memory of it and is an EXCITEMENT_SHARE."""
    svc = _svc(tmp_path)
    svc._life_trigger_cooled_down = lambda trigger_type, now: trigger_type in (
        "excitement_share", "goal_milestone")
    event = svc._life_events.record_event(event_type="achievement", title="Baked the first loaf",
                                          description="Baked the first loaf", share_urgency=0.8,
                                          source="skill_milestone")
    svc._bridge_life_event(event)
    svc._remember("baking the first loaf", place="home", tags=("milestone", event.share_id))
    assert [c["topic"] for c in svc._test_host.of("EXCITEMENT_SHARE")] == ["Baked the first loaf"]


def test_with_no_episode_and_no_event_no_excitement_or_dream_share(tmp_path):
    """The acceptance: an empty episode store and no events -- whatever her
    residue, mood or plan -- never an EXCITEMENT_SHARE or a DREAM_SHARE."""
    svc = _svc(tmp_path)
    svc._cognitive._dream_residue_emotion = "uneasy"
    svc._cognitive._dream_residue_intensity = 0.9
    svc._bridge_life_event(LifeEvent(event_type="achievement", title="something good",
                                     description="it went well", share_urgency=0.9))
    assert len(svc._memory) == 0 and svc._life_events.get_unshared_events() == []
    for _ in range(5):
        svc._life_trigger_cooldowns.clear()
        svc._evaluate_life_triggers()
    kinds = {c["trigger_type"] for c in svc._test_host.calls}
    assert not kinds & {"EXCITEMENT_SHARE", "DREAM_SHARE"}, svc._test_host.calls


# ------------------------------------------------- UPCOMING_EVENT and check-in

@pytest.mark.parametrize("host_now,event_at,when", [
    (datetime(2026, 11, 13, 9, 0), datetime(2026, 11, 13, 18, 0), "today"),
    (datetime(2026, 11, 13, 20, 0), datetime(2026, 11, 14, 16, 0), "tomorrow"),
    (datetime(2026, 11, 13, 9, 0), datetime(2026, 11, 15, 18, 0), "in two days"),
])
def test_upcoming_event_golden_says_the_day_in_words(tmp_path, monkeypatch, host_now, event_at, when):
    freeze_host_clock(monkeypatch, host_now)
    svc = _svc(tmp_path)
    svc.add_calendar_entry(CalendarEntry(event_name="the recital", event_date=event_at,
                                         date_str=event_at.strftime("%Y-%m-%d"), feeling="nervous",
                                         importance=0.8))
    svc._scan_calendar_for_triggers()
    (call,) = svc._test_host.of("UPCOMING_EVENT")
    assert call["prompt_hint"] == (
        f"Robin's event 'the recital' is {when}. Bring it up naturally — ask them about it or wish "
        f"them well."
    )
    _assert_clean(call["prompt_hint"])


def test_emotional_check_in_golden(tmp_path):
    svc = _svc(tmp_path)
    when = datetime.now() - timedelta(hours=5)
    svc.add_calendar_entry(CalendarEntry(event_name="the recital", event_date=when,
                                         date_str=when.strftime("%Y-%m-%d")))
    svc._scan_calendar_for_triggers()
    (call,) = svc._test_host.of("EMOTIONAL_CHECK_IN")
    assert call["prompt_hint"] == (
        "Robin's event 'the recital' just happened. Ask warmly how it went — you remembered it "
        "mattered to them."
    )
    _assert_clean(call["prompt_hint"])


# ------------------------------------------------------- DEPARTURE, ARRIVAL

def test_departure_and_arrival_golden_name_the_place(tmp_path):
    svc = _svc(tmp_path)
    svc._current_location = "home"
    svc.begin_transit("cafe", reason="coffee", total_minutes=60)
    (departure,) = svc._test_host.of("DEPARTURE")
    assert departure["topic"] == "cafe" and departure["context"] == "transit_depart:cafe"
    svc._trigger_arrival_message("home")
    (arrival,) = svc._test_host.of("ARRIVAL")
    assert arrival["topic"] == "home" and arrival["context"] == "Just arrived at home after being out."
    assert "prompt_hint" not in departure and "prompt_hint" not in arrival


# ---------------------------------------------------- the share id (T17-R1)

def test_a_host_that_takes_no_share_id_is_called_as_before(tmp_path):
    svc = _svc(tmp_path)
    _chaos(svc)
    _episode(svc, "You found a twenty on the sidewalk", tags=("chaos", "serendipity", "share:4"))
    _only(svc, "chaos_event")
    svc._evaluate_life_triggers()
    (call,) = svc._test_host.of("CHAOS_EVENT")
    assert set(call) == {"trigger_type", "topic", "context", "urgency", "prompt_hint", "quiet_windows"}


def test_a_host_must_say_true_to_get_the_share_id(tmp_path):
    host = _Host()
    host.accepts_share_id = "yes"
    svc = _svc(tmp_path, host=host)
    _chaos(svc)
    _episode(svc, "You found a twenty on the sidewalk", tags=("chaos", "serendipity", "share:4"))
    _only(svc, "chaos_event")
    svc._evaluate_life_triggers()
    (call,) = host.of("CHAOS_EVENT")
    assert "share_id" not in call


# --------------------------------------------- mark_shared's instant (T17-R5)

def test_marking_a_life_event_shared_stamps_the_world_instant(tmp_path):
    svc = _svc(tmp_path)
    event = svc._life_events.record_event(event_type="achievement", title="Finished reading Dune")
    assert svc.mark_shared(event.share_id)
    assert event.shared_at == T0
