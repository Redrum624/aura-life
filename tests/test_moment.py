"""The moment (humanness Task 18, spec section 4.10).

``LifeService.get_moment(user_text=None)`` builds a :class:`Moment` from her
live state -- situation, undercurrent, what is on her mind, at most one thing
to share with its id, how to speak, what she keeps to herself -- and
``render()`` gives it as text for her prompt: second person, no digit, no
snake_case, no engine label, at most 1,000 characters. It changes only the
novelty of the cues it rendered (saved) and the strength of the memory cues
it rendered (rulings T18-R2, T12-R2).
"""

import random
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta

import pytest

from aura_life import hooks
from aura_life.context.moment import (
    AI_STATE_KEYS, DEFAULT_LENGTH, MAX_RENDER_CHARS, NEUTRAL_EXPRESSIONS, LengthTarget, Moment, Share,
    expression_for, length_target,
)
from aura_life.expression.expression_system import DISTANCE_LINES
from aura_life.life_service import LifeService
from aura_life.memory.store import MemoryStream
from aura_life.models import Goal, GoalTimeframe
from aura_life.personas.keys import STATE_KEYS
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.world import WorldEnvironment

from test_render_lint import _check_rendered, _stress_words_problem

#: A Monday noon on the world clock.
T0 = datetime(2026, 10, 5, 12, 0)
#: snake_case, as spec section 4.10 forbids it.
SNAKE_RE = re.compile(r"[A-Za-z]_[A-Za-z]")
#: The words of an engine's labels that must never reach her (spec 4.10).
ENGINE_LABEL_RE = re.compile(r"\b(?:intensity|salience|novelty|undercurrent|on_mind|to_share|unspoken|"
                             r"state_expressions|after_absence|just_woke)\b", re.IGNORECASE)
HUNGRY_TEXT = "I'm starving, what are you eating?"


class _Clock:
    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant


def _svc(tmp_path, name="nora", *, clock=None, user_info=None, **definition) -> LifeService:
    clock = clock or _Clock(T0)
    fields = {"id": name, "name": name.title(), "appearance_details": {"gender": "female"}, **definition}
    svc = LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=name,
                      definition=PersonalityDefinition(**fields),
                      occupation=definition.get("occupation", ""),
                      world_environment=WorldEnvironment(now=clock, seed=13), rng=random.Random(13),
                      user_info=user_info if user_info is not None else {"name": "Robin"})
    svc._test_clock = clock
    return svc


def assert_moment_clean(text: str) -> None:
    """The Task 6 lint over a render addressed to her, plus spec 4.10: no
    digit, no snake_case, no engine label, at most 1,000 characters."""
    _check_rendered(text, text, is_second_person=True)
    assert not re.search(r"\d", text), text
    assert not SNAKE_RE.search(text), text
    assert not ENGINE_LABEL_RE.search(text), text
    assert len(text) <= MAX_RENDER_CHARS, len(text)
    for line in text.splitlines():
        assert _stress_words_problem(line) is None, line


def _tired(svc) -> None:
    """Her energy nearly gone (EnergyLevel.EXHAUSTED)."""
    state = svc._energy._state
    state.level, state.fatigue = 0.05, 0.9
    state.caffeine_boost = state.inspiration_boost = state.social_boost = 0.0
    assert svc._energy.energy_level.value == "exhausted"


def _episode(svc, what, *, at=None, place="home", tags=("activity",)):
    return svc._memory.record(at=at or svc._test_clock(), what=what, place=place, tags=tags)


# ======================================================================
# 1. The shape (spec section 4.10)
# ======================================================================

def test_a_moment_has_the_spec_fields_and_its_limits(tmp_path):
    svc = _svc(tmp_path)
    for n in range(4):
        _episode(svc, f"You walked to the market, time {n}", place="market")
    svc._goal_engine._active_goals = [Goal(title="Learn the chords", timeframe=GoalTimeframe.WEEKLY)]
    moment = svc.get_moment()
    assert isinstance(moment, Moment)
    assert isinstance(moment.situation, str) and moment.situation
    assert isinstance(moment.undercurrent, str)
    assert isinstance(moment.on_mind, tuple) and len(moment.on_mind) <= 2
    assert moment.to_share is None or isinstance(moment.to_share, Share)
    assert isinstance(moment.speech, tuple) and 2 <= len(moment.speech) <= 4
    assert isinstance(moment.unspoken, tuple) and len(moment.unspoken) <= 1
    # Ruling T18-R1: the length target is data a host reads, integers.
    assert isinstance(moment.length, LengthTarget)
    assert all(isinstance(n, int) for n in moment.length)
    with pytest.raises(Exception):
        moment.situation = "changed"  # frozen
    assert_moment_clean(moment.render())


def test_a_render_too_long_is_fitted_under_the_cap(tmp_path):
    """Long parts are left out, least needed first, until the render fits;
    what is kept is what was rendered (spec 4.10: at most 1,000 characters)."""
    long_line = "You keep thinking about " + "the long road home and the rain on it, " * 6 + "and the lights"
    svc = _svc(tmp_path, state_expressions={"tired": "keep it short; " + "let the silence hang there, " * 8 + "and wait"})
    _tired(svc)
    for n, what in enumerate((long_line, long_line + " again", long_line + " once more")):
        _episode(svc, what, at=T0 - timedelta(minutes=n))
    svc._shadow._state.secrets = [long_line]
    moment = svc.get_moment()
    text = moment.render()
    assert len(text) <= MAX_RENDER_CHARS
    assert text == "\n".join(moment.lines())  # fitted by the builder, not cut by render()
    assert moment.speech[0].startswith("Keep it to")


# ======================================================================
# 2. The undercurrent: her own expressions, else the neutral table
# ======================================================================

def test_a_persona_with_a_tired_expression_renders_it_when_tired(tmp_path):
    """The Task 18 acceptance: her state_expressions["tired"] as written."""
    mine = "go quiet; one word where a sentence would do"
    svc = _svc(tmp_path, state_expressions={"tired": mine})
    _tired(svc)
    moment = svc.get_moment()
    assert mine in moment.undercurrent, moment.undercurrent
    assert moment.undercurrent.startswith("You're exhausted — " + mine)
    assert_moment_clean(moment.render())


def test_a_persona_without_expressions_renders_the_neutral_table(tmp_path):
    svc = _svc(tmp_path)
    assert svc._definition.state_expressions == {}
    _tired(svc)
    assert NEUTRAL_EXPRESSIONS["tired"] in svc.get_moment().undercurrent


def test_the_neutral_table_covers_every_state_key_in_her_form():
    """Ruling T18-R4: one entry per STATE_KEYS key, lowercase fragments with
    no pronoun of hers (so no slot and no allow-list entry)."""
    assert set(NEUTRAL_EXPRESSIONS) == set(STATE_KEYS)
    for key, text in NEUTRAL_EXPRESSIONS.items():
        assert text and text[0].islower(), key
        assert not re.search(r"\b(she|her|hers|herself|he|him|his|himself)\b", text), key
        assert not re.search(r"[{}\d]", text), key


def test_an_ai_persona_reaches_only_the_keys_without_a_body(tmp_path):
    assert set(AI_STATE_KEYS) < set(STATE_KEYS)
    assert not {"hungry", "drinking", "hungover", "sick", "just_woke"} & set(AI_STATE_KEYS)
    assert expression_for("hungry", {}, is_ai=True) == ""
    assert expression_for("tired", {}, is_ai=True) == NEUTRAL_EXPRESSIONS["tired"]
    svc = _svc(tmp_path, persona_type="ai")
    svc._basic_needs.hunger = 0.95
    text = svc.get_moment(HUNGRY_TEXT).render()
    assert NEUTRAL_EXPRESSIONS["hungry"] not in text and "starving" not in text, text


def test_her_mood_leads_with_its_own_line(tmp_path):
    from aura_life.affect.affect_system import AffectSystem
    svc = _svc(tmp_path, state_expressions={"low": "keep the curtains closed; say less"})
    svc._affect._set_mood(-0.8, 0.1)
    mood = svc._affect.mood
    assert mood.current_mood in ("low", "flat") and mood.intensity >= 0.1
    under = svc.get_moment().undercurrent
    assert under.startswith(AffectSystem.MOOD_DESCRIPTIONS[mood.current_mood] + " — keep the curtains closed")


def test_after_an_absence_her_expression_is_rendered_with_a_plain_lead(tmp_path):
    """Ruling T18-R5: LifeService.after_absence, rendered with her
    after_absence expression; the user named, never "the user"."""
    mine = "act like the gap was nothing; it was not"
    svc = _svc(tmp_path, state_expressions={"after_absence": mine}, attachment_style="anxious")
    svc.observe_user_turn("hello")
    svc._test_clock.instant = T0 + timedelta(days=3)
    assert svc.after_absence is not None and svc.after_absence.intensity > 0
    under = svc.get_moment().undercurrent
    assert "It's been a long while since you heard from Robin — " + mine in under, under


def _just_woke(svc):
    svc._energy._state.hours_awake = 0.25


def _drunk(svc):
    svc._body._inebriation.level = 0.5


def _hungover(svc):
    svc._body._inebriation.hangover_severity = 0.6


def _sick(svc):
    svc._body._health.illness, svc._body._health.illness_severity = "a cold", 0.7


def _lonely(svc):
    svc._affect._loneliness.level = 0.6


def _on_edge(svc):
    svc._shadow._state.unease = 0.9


def _heavy(svc):
    svc._shadow._state.guilt = 0.9


@pytest.mark.parametrize("make,key,lead", [
    (_just_woke, "just_woke", "You've only just woken up"),
    (_drunk, "drinking", "You've been drinking"),
    (_hungover, "hungover", "You're hungover"),
    (_sick, "sick", "You're down with a cold"),
    (_lonely, "lonely", "You're lonely"),
    (_on_edge, "stressed", "Something has you on edge"),
    (_heavy, "low", "Something you did sits heavy with you"),
], ids=["just_woke", "drunk", "hungover", "sick", "lonely", "on_edge", "heavy"])
def test_each_state_is_led_plainly_and_said_through_her_expression(tmp_path, make, key, lead):
    mine = f"the {key.replace('_', ' ')} way, as written"
    svc = _svc(tmp_path, state_expressions={key: mine})
    make(svc)
    under = svc.get_moment().undercurrent
    assert f"{lead} — {mine}." in under, under


def _uneasy(svc, unease=0.6, felt_safety=0.3) -> None:
    """Her shadow as days of loneliness or stress leave it: uneasy, unsafe."""
    svc._shadow._state.unease, svc._shadow._state.felt_safety = unease, felt_safety


def _stressed(svc) -> None:
    svc._affect._stress.level = 0.6


def _low_mood(svc) -> None:
    svc._affect._set_mood(-0.6, 0.3)


@pytest.mark.parametrize("cause,lead", [
    (_lonely, "You're lonely"),
    (_stressed, "You're stressed"),
    (_low_mood, None),
], ids=["lonely", "stressed", "a-low-mood"])
def test_her_unease_is_not_said_beside_the_state_that_causes_it(tmp_path, cause, lead):
    """Review of Task 36, Important 2: her shadow's unease rises with her
    loneliness, her stress and a low mood. While one of them is in her
    undercurrent it says the unease too -- "on edge" beside it was one cause
    told as two states, in every capture of a persona nobody spoke to, and
    under the neutral table the pair contradicted itself ("lean into the
    talk", "get to the point")."""
    from aura_life.affect.affect_system import AffectSystem
    svc = _svc(tmp_path)
    cause(svc)
    _uneasy(svc)
    assert {"unease", "felt_unsafe"} <= svc._shadow.export_state().keys()
    under = svc.get_moment().undercurrent
    lead = lead or AffectSystem.MOOD_DESCRIPTIONS[svc._affect.mood.current_mood]
    assert lead in under and "on edge" not in under, under


def test_her_unease_is_said_when_no_one_cause_of_it_is(tmp_path):
    """A little lonely and a little stressed, each under the bar at which it
    is said itself: what they add up to is her unease, and it is said. So is
    an unease that outlives its cause (she is no longer lonely, still
    unsettled)."""
    svc = _svc(tmp_path)
    svc._affect._loneliness.level = svc._affect._stress.level = 0.19
    _uneasy(svc, unease=0.4, felt_safety=0.6)
    under = svc.get_moment().undercurrent
    assert "Something has you on edge" in under and "lonely" not in under and "stressed" not in under, under


def test_a_good_mood_does_not_say_her_unease_for_her(tmp_path):
    """Only a mood under neutral raises her unease: in a good mood, what has
    her on edge is something else, and it is said."""
    svc = _svc(tmp_path)
    svc._affect._set_mood(0.6, 0.3)
    _uneasy(svc)
    under = svc.get_moment().undercurrent
    assert "Something has you on edge" in under and "good mood" in under, under


def _a_little_lonely(svc) -> None:
    svc._affect._loneliness.level = 0.25


def _a_little_stressed(svc) -> None:
    svc._affect._stress.level = 0.25


def _a_little_low(svc) -> None:
    svc._affect._set_mood(-0.3, 0.3)


@pytest.mark.parametrize("cause,lead", [
    (_a_little_lonely, "You're lonely"),
    (_a_little_stressed, "You're stressed"),
    (_a_little_low, None),
], ids=["a-little-lonely", "a-little-stressed", "a-little-low"])
def test_a_cause_just_over_its_own_bar_already_says_her_unease(tmp_path, cause, lead):
    """Re-check of Task 36 (ruling T36-R6): the bar at which a cause says her
    unease for her is the bar at which it is said itself -- her loneliness
    or her stress at 0.2, any said mood under neutral -- not a higher one."""
    from aura_life.affect.affect_system import AffectSystem
    svc = _svc(tmp_path)
    cause(svc)
    _uneasy(svc)
    under = svc.get_moment().undercurrent
    lead = lead or AffectSystem.MOOD_DESCRIPTIONS[svc._affect.mood.current_mood]
    assert lead in under and "on edge" not in under, under


def test_being_tired_does_not_say_her_unease_for_her(tmp_path):
    """Tiredness is no cause of her unease (ruling T36-R6): tired and on
    edge are two states, and both are said."""
    svc = _svc(tmp_path)
    _tired(svc)
    _uneasy(svc)
    under = svc.get_moment().undercurrent
    assert "Something has you on edge" in under and ("exhausted" in under or "tired" in under), under


def test_lost_felt_safety_alone_is_her_being_on_edge(tmp_path):
    """Her felt safety can be gone while her unease is under its own bar (a
    conflict shakes it at once): that alone has her on edge (ruling T36-R6)."""
    svc = _svc(tmp_path)
    _uneasy(svc, unease=0.2, felt_safety=0.2)
    exported = svc._shadow.export_state()
    assert "felt_unsafe" in exported and "unease" not in exported, exported
    assert "Something has you on edge" in svc.get_moment().undercurrent


def test_her_self_doubt_alone_is_not_her_being_on_edge(tmp_path):
    """Doubt follows her mood and her unease (a mood a little under neutral
    exports it by itself); it is not what "on edge" says."""
    svc = _svc(tmp_path)
    svc._shadow._state.doubt = 0.6
    assert "doubt" in svc._shadow.export_state()
    assert "on edge" not in svc.get_moment().undercurrent


# ======================================================================
# 3. What the user says: relevance (ruling T18-R3)
# ======================================================================

def test_a_hungry_question_surfaces_her_hunger_over_a_stronger_state(tmp_path):
    """The acceptance: "I'm starving, what are you eating?" surfaces a hunger
    or meal cue when her hunger is at least 0.5 -- even when she is also
    exhausted and stressed, which outweigh it without the question."""
    svc = _svc(tmp_path)
    _tired(svc)
    svc._affect._stress.level = 0.9
    svc._basic_needs.hunger = 0.5
    quiet = svc.get_moment().render()
    assert "peckish" not in quiet and NEUTRAL_EXPRESSIONS["hungry"] not in quiet, quiet
    asked = svc.get_moment(HUNGRY_TEXT).render()
    assert "You're peckish — " + NEUTRAL_EXPRESSIONS["hungry"] in asked, asked
    assert_moment_clean(asked)


@pytest.fixture
def no_hooks():
    """No hook registered for one test; every provider is put back after."""
    saved = {name: hooks.provider_for(name) for name in hooks.HOOK_NAMES}
    hooks.reset()
    yield
    hooks.reset()
    hooks.configure(**{name: provider for name, provider in saved.items() if provider is not None})


def test_the_stream_s_relevance_is_keyword_overlap_without_a_hook(no_hooks):
    stream = MemoryStream()
    assert stream.relevance("what are you eating", ["having lunch", "eating lunch", ""]) == [0.0, 1.0, 0.0]
    assert stream.relevance(None, ["eating"]) == [0.0]


def test_the_stream_s_relevance_takes_the_host_s_vectors(monkeypatch):
    """With an embed hook the cosine of the host's vectors decides, through
    the stream's one guarded call site (tests/test_hook_call_sites.py)."""
    saved = {name: hooks.provider_for(name) for name in hooks.HOOK_NAMES}
    try:
        hooks.configure(embed=lambda texts: [[1.0, 0.0] if "food" in t or "eat" in t else [0.0, 1.0]
                                             for t in texts])
        stream = MemoryStream()
        assert stream.relevance("eat", ["food", "rain"]) == [1.0, 0.0]
    finally:
        hooks.reset()
        hooks.configure(**{n: p for n, p in saved.items() if p is not None})


def test_a_failing_hook_falls_back_to_overlap_and_is_reported_once(caplog):
    import logging
    saved = {name: hooks.provider_for(name) for name in hooks.HOOK_NAMES}

    def broken(texts):
        raise RuntimeError("model offline")
    try:
        hooks.configure(embed=broken)
        stream = MemoryStream()
        caplog.set_level(logging.DEBUG, logger="aura_life")
        assert stream.relevance("eating lunch", ["eating", "rain"]) == [0.5, 0.0]
        assert stream.relevance("eating lunch", ["eating", "rain"]) == [0.5, 0.0]
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "embed hook failed" in r.getMessage()]
        assert len(warnings) == 1
    finally:
        hooks.reset()
        hooks.configure(**{n: p for n, p in saved.items() if p is not None})


def test_an_engine_that_cannot_answer_leaves_the_rest_of_the_moment(tmp_path):
    svc = _svc(tmp_path)
    _tired(svc)

    def broken():
        raise RuntimeError("goal store gone")
    svc._goal_engine.get_goals_for_mindset = broken
    svc._shadow.export_state = broken
    moment = svc.get_moment()
    assert moment.undercurrent.startswith("You're exhausted") and moment.situation
    assert_moment_clean(moment.render())


# ======================================================================
# 4. To share: its id, and the host marks it
# ======================================================================

def test_marking_to_share_removes_it_from_the_next_moment(tmp_path):
    """The acceptance: marking to_share.id removes it from the next moment;
    get_moment itself marks nothing (ruling T18-R2)."""
    svc = _svc(tmp_path)
    shared = svc._create_shareable_from_text("She found a twenty on the sidewalk")
    event = svc._life_events.record_event(event_type="serendipity", title="Found a twenty",
                                          description="Found a twenty", share_urgency=0.7)
    svc._remember("You found a twenty on the sidewalk", place="park", tags=("chaos", shared.share_id, event.share_id))
    first = svc.get_moment()
    assert first.to_share is not None and first.to_share.id == shared.share_id
    assert first.to_share.text == "You found a twenty on the sidewalk at the park."
    assert svc.get_moment().to_share == first.to_share  # not marked by being shown
    assert svc.mark_shared(first.to_share.id)
    after = svc.get_moment()
    assert after.to_share is None, after.to_share
    assert "haven't shared" not in after.render()


@pytest.mark.parametrize("marked", ["share", "event"])
def test_marking_one_id_of_an_item_marks_the_ids_told_with_it(tmp_path, marked):
    """One episode tells a shareable and its life event (a chaos event, a
    finished book, a skill milestone): they are one piece of news. The
    moment offers one id of it; marking either marks both, so neither getter
    nor her life context offers it again (fix round 1, C3)."""
    svc = _svc(tmp_path)
    shared = svc._create_shareable_from_text("She found a twenty on the sidewalk")
    event = svc._life_events.record_event(event_type="serendipity", title="Found a twenty",
                                          description="Found a twenty", share_urgency=0.7)
    other = svc._life_events.record_event(event_type="serendipity", title="Saw a heron",
                                          description="Saw a heron", share_urgency=0.4)
    svc._remember("You found a twenty on the sidewalk", place="park", tags=("chaos", shared.share_id, event.share_id))
    assert svc.mark_shared(shared.share_id if marked == "share" else event.share_id)
    assert [e.share_id for e in svc._life_events.get_unshared_events()] == [other.share_id]
    assert svc.get_shareable_experiences() == []
    assert "Found a twenty" not in svc.get_life_context()


def test_only_an_item_with_a_memory_of_it_is_offered(tmp_path):
    """What she could share is told from her memory of it, in the second
    person; a shareable no episode tells is not offered."""
    svc = _svc(tmp_path)
    svc._create_shareable_from_text("She saw a heron")
    assert svc.get_moment().to_share is None


# ======================================================================
# 5. What it changes: novelty and reinforcement, nothing else (T18-R2)
# ======================================================================

def _goals(svc, *titles_and_motivation) -> None:
    svc._goal_engine._active_goals = [Goal(title=t, timeframe=GoalTimeframe.WEEKLY, motivation_level=m)
                                      for t, m in titles_and_motivation]


GOAL_LINE = "You've been working on “Learn the chords”."
CURIOUS_LINE = "A question keeps coming back to you: how do bees find their way home?"
RUMINATION_LINE = "Something keeps replaying in your mind: the meeting that went wrong."


def _three_thoughts(svc) -> None:
    """A goal, a curiosity and a rumination of fixed salience (1.0, 0.9,
    0.8): nothing in her memory stream."""
    from aura_life.models import CuriosityQuestion
    _goals(svc, ("Learn the chords", 1.0))
    svc._drive._curiosities = [CuriosityQuestion(topic="how do bees find their way home?", intensity=0.9)]
    svc._cognitive._ruminations = []
    svc._cognitive._add_rumination("the meeting that went wrong", "failure", 0.8)


def test_a_rendered_cue_loses_salience_and_recovers_over_hours(tmp_path):
    from aura_life.context.moment import novelty
    svc = _svc(tmp_path)
    _three_thoughts(svc)
    assert svc.get_moment().on_mind == (GOAL_LINE, CURIOUS_LINE)
    assert svc.get_moment().on_mind[0] == RUMINATION_LINE  # the two rendered are passed over
    svc._test_clock.instant = T0 + timedelta(hours=1)
    key = "goal:Learn the chords"
    assert 0.5 < novelty(svc._moment_novelty, key, svc._test_clock.instant) < 0.6  # an hour is not enough
    svc._test_clock.instant = T0 + timedelta(days=2)
    assert novelty(svc._moment_novelty, key, svc._test_clock.instant) == 1.0
    assert svc.get_moment().on_mind == (GOAL_LINE, CURIOUS_LINE)  # fresh again


# ----------------------------------------------------------------------
# 5b. Across the turns of one conversation (Task 38)
# ----------------------------------------------------------------------

def test_within_one_conversation_a_thought_comes_to_mind_once(tmp_path):
    """Task 38: a host asks for her moment at every turn, minutes apart.
    Novelty alone only reorders what is left, so with a handful of thoughts
    the same two came back turn after turn (one line in five of eight
    turns of a measured conversation). A thought the moment rendered is not
    rendered again in the same conversation -- turns less than
    CONVERSATION_ACTIVITY_WINDOW_MINUTES apart -- and her mind may be empty;
    in a later conversation it can come back, as its novelty ranks it."""
    from aura_life.life_service import CONVERSATION_ACTIVITY_WINDOW_MINUTES
    svc = _svc(tmp_path)
    _three_thoughts(svc)
    assert svc.get_moment().on_mind == (GOAL_LINE, CURIOUS_LINE)
    svc._test_clock.instant = T0 + timedelta(minutes=5)
    assert svc.get_moment().on_mind == (RUMINATION_LINE,)
    svc._test_clock.instant = T0 + timedelta(minutes=10)
    assert svc.get_moment().on_mind == ()
    svc._test_clock.instant = T0 + timedelta(minutes=10 + CONVERSATION_ACTIVITY_WINDOW_MINUTES - 1)
    assert svc.get_moment().on_mind == ()  # still the same conversation
    svc._test_clock.instant += timedelta(minutes=CONVERSATION_ACTIVITY_WINDOW_MINUTES + 1)
    assert svc.get_moment().on_mind == (GOAL_LINE, CURIOUS_LINE)  # a new one


def test_what_the_user_asks_about_comes_back_to_mind(tmp_path):
    """The user's own words bring a thought back in the same conversation:
    she was asked about it."""
    svc = _svc(tmp_path)
    _three_thoughts(svc)
    assert GOAL_LINE in svc.get_moment().on_mind
    svc._test_clock.instant = T0 + timedelta(minutes=5)
    assert GOAL_LINE not in svc.get_moment("what a grey day").on_mind
    svc._test_clock.instant = T0 + timedelta(minutes=10)
    assert GOAL_LINE in svc.get_moment("how are the chords coming along?").on_mind


def test_after_an_absence_she_is_told_once_in_a_conversation(tmp_path):
    """Her after_absence expression says how to meet the user's return
    ("say so once"); told at every turn of the reunion (six of six in a
    measured conversation) the reply would remark on the absence each time."""
    mine = "notice how long it was and say so once; never ask for the reason"
    svc = _svc(tmp_path, state_expressions={"after_absence": mine}, attachment_style="avoidant")
    svc.observe_user_turn("hello")
    svc._test_clock.instant = T0 + timedelta(days=3)
    svc.observe_user_turn("sorry I disappeared")
    assert svc.after_absence is not None and svc.after_absence.intensity > 0
    assert mine in svc.get_moment("sorry I disappeared").undercurrent
    for minutes in (5, 10):
        svc._test_clock.instant = T0 + timedelta(days=3, minutes=minutes)
        svc.observe_user_turn("how have you been?")
        assert svc.after_absence is not None and svc.after_absence.intensity > 0
        assert mine not in svc.get_moment("how have you been?").undercurrent


def test_what_she_just_told_is_not_on_her_mind_at_the_next_turn(tmp_path):
    """What the moment offered her to share is the same memory as its
    episode: offered at one turn, it was "on your mind" at the next (told,
    then brought up again)."""
    svc = _svc(tmp_path)
    shared = svc._create_shareable_from_text("She found a twenty on the sidewalk")
    svc._remember("You found a twenty on the sidewalk", place="park", tags=("chaos", shared.share_id))
    first = svc.get_moment()
    assert first.to_share is not None and "found a twenty" in first.to_share.text
    assert svc.mark_shared(first.to_share.id)
    svc._test_clock.instant = T0 + timedelta(minutes=5)
    after = svc.get_moment()
    assert not any("found a twenty" in line for line in after.on_mind), after.on_mind


def test_her_memory_offers_its_next_thoughts_once_the_first_were_said(tmp_path):
    """The moment weighs her three foremost memories each turn; passing over
    what the conversation already had must not leave her with nothing while
    she remembers more: her memory is asked for the next ones."""
    places = ("market", "harbour", "library", "bakery", "station", "museum", "garden", "river")
    svc = _svc(tmp_path)
    for place in places:
        _episode(svc, f"You walked to the {place}", place="town")
    seen = []
    for turn in range(4):
        svc._test_clock.instant = T0 + timedelta(minutes=5 * turn)
        walks = [line for line in svc.get_moment().on_mind if "You walked to the" in line]
        assert walks, (turn, seen)
        seen += walks
    assert len(seen) == len(set(seen)) >= 6, seen


def test_memories_about_what_was_said_do_not_stop_her_memory_from_going_on(tmp_path):
    """Review of Task 38, Important 1: her memory was asked for three beyond
    the memories said by key; five memories of one thing took those places
    once the first was said, and her mind stayed empty while forty other
    things had never come up (measured over forty turns). Her memory is
    walked until three of it are fresh, or it is exhausted."""
    places = ("harbour", "library", "bakery", "station", "museum")
    svc = _svc(tmp_path)
    for place in places:
        _episode(svc, f"You walked to the {place}", place="town")
    for _ in range(5):  # the newest: they come to mind first
        _episode(svc, "You waited for the ferry", place="town")
    seen = []
    for turn in range(6):
        svc._test_clock.instant = T0 + timedelta(minutes=5 * turn)
        seen += [line for line in svc.get_moment().on_mind if "On your mind" in line]
    assert sum("ferry" in line for line in seen) == 1, seen
    assert all(any(place in line for line in seen) for place in places), seen


def test_a_broad_word_does_not_keep_her_on_what_was_said(tmp_path):
    """"Are you home?" names every memory of home. The ones already said
    stay candidates beside the memories never said, never instead of them:
    asked the same thing turn after turn, she still gets to all of it (a
    first form of the walk counted the named ones as fresh, and ten such
    turns brought said memories back eleven times)."""
    svc = _svc(tmp_path)
    at_home = ("made tea", "watered the plants", "fixed the lamp", "sorted the books")
    elsewhere = ("crossed the bridge", "fed the ducks", "climbed the tower", "missed the tram")
    for what in at_home:
        _episode(svc, f"You {what}", place="home")
    for what in elsewhere:
        _episode(svc, f"You {what}", place="town")
    seen = []
    for turn in range(6):
        svc._test_clock.instant = T0 + timedelta(minutes=5 * turn)
        seen += [line for line in svc.get_moment("are you home?").on_mind if "On your mind" in line]
    for what in at_home + elsewhere:
        assert any(what in line for line in seen), (what, seen)


def test_a_moment_built_while_the_user_is_away_does_not_use_up_the_line_on_the_return(tmp_path):
    """Review of Task 38, Important 2: the "said once" note was taken for the
    line of the absence itself too, so a moment a host built while the user
    was away (for a message of her own) left her untold how to meet the
    return ten minutes later."""
    mine = "notice how long it was and say so once; never ask for the reason"
    svc = _svc(tmp_path, state_expressions={"after_absence": mine}, attachment_style="avoidant")
    svc.observe_user_turn("hello")
    svc._test_clock.instant = T0 + timedelta(days=3)
    assert "It's been a long while since you heard from Robin" in svc.get_moment().undercurrent
    svc._test_clock.instant = T0 + timedelta(days=3, minutes=5)
    assert "It's been a long while since you heard from Robin" in svc.get_moment().undercurrent  # still away: still true
    svc._test_clock.instant = T0 + timedelta(days=3, minutes=10)
    svc.observe_user_turn("I'm back")
    back = svc.get_moment("I'm back").undercurrent
    assert "again after a long while" in back and mine in back, back


def test_news_she_never_told_is_not_held_back_by_its_words(tmp_path):
    """Review of Task 38, Important 3: an item that left her queue of ten
    without being told counted as told, and held back a later item in the
    same words (three of ten offerable items, in a measured run). Only what
    she told does."""
    from aura_life.life_service import SHAREABLE_QUEUE_MAX
    svc = _svc(tmp_path)

    def reads():
        item = svc._create_shareable_from_text("She read at the cafe")
        svc._remember("You read a chapter of the new book", place="cafe", tags=("activity", item.share_id))
        return item

    first = reads()
    for n in range(SHAREABLE_QUEUE_MAX):  # ten newer items push the first one out, untold
        svc._create_shareable_from_text(f"She noticed thing number {n}")
    assert first.share_id not in {item.share_id for item in svc._shareable_queue}
    second = reads()
    offered = svc.get_moment().to_share
    assert offered is not None and offered.id == second.share_id, offered


def test_a_clock_that_went_back_starts_a_new_conversation(tmp_path):
    """A moment before the last one (a host that set its clock back) is not
    "less than the window after it": the conversation starts anew."""
    svc = _svc(tmp_path)
    _three_thoughts(svc)
    svc._test_clock.instant = T0 + timedelta(minutes=10)
    assert svc.get_moment().on_mind == (GOAL_LINE, CURIOUS_LINE)
    svc._test_clock.instant = T0
    # In the same conversation the goal would be passed over; in a new one
    # it is weighed again (behind the thought that was never rendered).
    assert svc.get_moment().on_mind == (RUMINATION_LINE, GOAL_LINE)


def test_the_lead_of_a_goal_line_is_not_what_the_user_named(tmp_path):
    """"What have you been working on?" shares "working" with the lead of
    every goal line, not with the goal: it does not bring a said goal back."""
    svc = _svc(tmp_path)
    _three_thoughts(svc)
    assert GOAL_LINE in svc.get_moment().on_mind
    svc._test_clock.instant = T0 + timedelta(minutes=5)
    assert GOAL_LINE not in svc.get_moment("what have you been working on lately?").on_mind


def test_the_same_thing_somewhere_else_is_not_its_twin(tmp_path):
    """Twins are told in the very same words: the same activity at another
    place is other news, and telling one leaves the other to tell."""
    svc = _svc(tmp_path)
    items = []
    for place in ("cafe", "park"):
        item = svc._create_shareable_from_text("She read a chapter")
        svc._remember("You read a chapter of the new book", place=place, tags=("activity", item.share_id))
        items.append(item)
    assert svc.mark_shared(items[0].share_id)
    assert [item.share_id for item in svc.get_shareable_experiences()] == [items[1].share_id]


def test_a_word_for_how_she_felt_is_not_what_a_memory_is_about(tmp_path):
    """A memory is about what happened, where and with whom. The user's
    "you're so annoying" shares a stem with a memory she was annoyed in,
    not with what it is of: it does not bring it back (it did, in a
    measured conversation)."""
    svc = _svc(tmp_path)
    svc._memory.record(at=T0, what="You sorted the mail", place="work", emotion="annoyed", tags=("activity",))
    assert any("sorted the mail" in text for text in svc.get_moment().on_mind)
    svc._test_clock.instant = T0 + timedelta(minutes=5)
    assert not any("sorted the mail" in text for text in svc.get_moment("you're so annoying today").on_mind)
    svc._test_clock.instant = T0 + timedelta(minutes=10)
    assert any("sorted the mail" in text for text in svc.get_moment("was there a lot of mail?").on_mind)


def test_two_memories_told_in_the_same_words_come_to_mind_once(tmp_path):
    """Two afternoons of the same work are two memories with one line:
    said once, in one moment and in one conversation."""
    svc = _svc(tmp_path)
    for _ in range(2):
        _episode(svc, "You worked through the backlog", place="work")
    line = [text for text in svc.get_moment().on_mind if "backlog" in text]
    assert len(line) == 1, line
    svc._test_clock.instant = T0 + timedelta(minutes=5)
    assert not any("backlog" in text for text in svc.get_moment().on_mind)


def test_one_topic_through_two_sources_is_one_thought(tmp_path):
    """What she keeps turning over and the stressor it comes from name the
    same thing: one of them in a conversation, not one after the other."""
    svc = _svc(tmp_path)
    svc._cognitive._ruminations = []
    svc._cognitive._add_rumination("money worries", "worry", 0.8)
    svc._affect.raise_stressor("money", now=T0)
    seen = []
    for minutes in (0, 5, 10):
        svc._test_clock.instant = T0 + timedelta(minutes=minutes)
        seen += [text for text in svc.get_moment().on_mind if "money worries" in text]
    assert len(seen) == 1, seen


def test_the_lead_of_a_line_is_not_what_the_user_named(tmp_path):
    """"What's on your mind?" shares its words with the lead of every
    memory line ("On your mind, from earlier today: ..."), not with what any
    of them is about: it brings none of them back."""
    svc = _svc(tmp_path)
    _episode(svc, "You walked to the market", place="market")
    assert any("market" in text for text in svc.get_moment().on_mind)
    svc._test_clock.instant = T0 + timedelta(minutes=5)
    assert not any("market" in text for text in svc.get_moment("what's on your mind today?").on_mind)
    svc._test_clock.instant = T0 + timedelta(minutes=10)
    assert any("market" in text for text in svc.get_moment("did you go to the market?").on_mind)


def test_news_made_later_in_the_same_words_is_not_offered(tmp_path):
    """She told the user she read at the cafe; another hour of reading
    makes the same news again (a new item, the same words): not offered."""
    svc = _svc(tmp_path)

    def reads():
        item = svc._create_shareable_from_text("She read at the cafe")
        svc._remember("You read a chapter of the new book", place="cafe", tags=("activity", item.share_id))

    reads()
    first = svc.get_moment()
    assert first.to_share is not None and svc.mark_shared(first.to_share.id)
    reads()  # after she told it
    assert len(svc.get_shareable_experiences()) == 1  # the new item exists, unshared
    svc._test_clock.instant = T0 + timedelta(hours=3)  # another conversation
    assert svc.get_moment().to_share is None


def test_telling_one_thing_tells_its_twin(tmp_path):
    """Two unshared items her memory tells in the same words (two evenings
    of the same activity) are one piece of news: once she told one, the
    other is not offered (it was, at the very next turn)."""
    svc = _svc(tmp_path)
    for _ in range(2):
        item = svc._create_shareable_from_text("She read at the cafe")
        svc._remember("You read a chapter of the new book", place="cafe", tags=("activity", item.share_id))
    first = svc.get_moment()
    assert first.to_share is not None
    assert svc.mark_shared(first.to_share.id)
    assert svc.get_shareable_experiences() == []
    svc._test_clock.instant = T0 + timedelta(minutes=5)
    assert svc.get_moment().to_share is None


def test_her_plan_her_stressors_and_what_she_puts_off_are_cues(tmp_path):
    from types import SimpleNamespace
    svc = _svc(tmp_path)
    slot = SimpleNamespace(hour=18, activity_name="yoga", location="gym", completed=False)
    svc._daily_planner._current_plan = SimpleNamespace(get_current_slot=lambda now=None: None,
                                                       get_next_slot=lambda now=None: slot, slots=[slot])
    svc._affect.raise_stressor("money", now=T0)
    svc._drive.add_avoidance("calling the landlord")
    svc._drive._avoidances[0].guilt_accumulated = 0.9
    lines = set()
    for hour in range(4):  # novelty brings each forward in turn
        svc._test_clock.instant = T0 + timedelta(minutes=hour)
        lines.update(svc.get_moment().on_mind)
    assert {"Coming up later: yoga at the gym.", "You keep coming back to money worries.",
            "You keep putting off calling the landlord."} <= lines, lines


def test_a_cue_in_the_third_person_is_passed_over_for_one_addressed_to_her(tmp_path):
    """A profile's struggles are written about her ("guilt over the friend
    she let down"); a goal or a rumination made of one would read "she"
    inside a moment addressed to her (fix round 1, C2). Each source gives
    its first item said to her instead."""
    svc = _svc(tmp_path)
    _goals(svc, ("Work on guilt over the friend she let down", 1.0), ("Learn the chords", 0.6))
    svc._cognitive._ruminations = []
    svc._cognitive._add_rumination("the meeting that went wrong", "failure", 0.5)
    svc._cognitive._add_rumination("the friend she let down", "failure", 0.9)
    seen = set()
    for minute in range(4):  # novelty brings each forward in turn
        svc._test_clock.instant = T0 + timedelta(minutes=minute)
        moment = svc.get_moment()
        assert_moment_clean(moment.render())
        seen.update(moment.on_mind)
    assert {GOAL_LINE, RUMINATION_LINE} <= seen, seen


def test_what_her_shadow_hides_is_her_unspoken_line(tmp_path):
    svc = _svc(tmp_path)
    svc._shadow._state.masking = 0.9
    assert svc.get_moment().unspoken == ("You're putting on a front.",)


def test_the_situation_says_where_what_and_when(tmp_path):
    from types import SimpleNamespace
    svc = _svc(tmp_path)
    slot = SimpleNamespace(hour=12, activity_name="reading", location="home", completed=False)
    svc._daily_planner._current_plan = SimpleNamespace(get_current_slot=lambda now=None: slot,
                                                       get_next_slot=lambda now=None: None, slots=[slot])
    weather = svc._world.weather.value.replace("_", " ")
    phase = svc._persona_time_of_day.value.replace("_", " ")
    situation = svc.get_moment().situation
    assert situation.startswith("You're reading at home. It's a "), situation
    assert weather in situation and (phase in situation or "night" in situation), situation
    svc.is_asleep = lambda: True
    assert svc.get_moment().situation.startswith("You're asleep at home.")


def test_novelty_is_saved_and_read_back_after_a_restart(tmp_path):
    svc = _svc(tmp_path)
    _three_thoughts(svc)
    svc.get_moment()
    again = _svc(tmp_path, clock=svc._test_clock)
    again._load_state()  # what start() reads
    assert again._moment_novelty == svc._moment_novelty and set(again._moment_novelty) == {
        "goal:Learn the chords", "curiosity:how do bees find their way home?"}
    _three_thoughts(again)
    assert again.get_moment().on_mind[0] == RUMINATION_LINE


def test_a_database_from_before_task_18_loads_with_every_cue_fresh(tmp_path):
    """Ruling T18-R6: a real database without the moment's table (as every
    one before Task 18) loads, every cue fresh, and the next moment saves."""
    svc = _svc(tmp_path)
    _goals(svc, ("Learn the chords", 1.0))
    svc.get_moment()
    with sqlite3.connect(svc._db_path) as conn:
        conn.execute("DROP TABLE life_moment_state")
    old = _svc(tmp_path, clock=svc._test_clock)
    with sqlite3.connect(old._db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS life_moment_state")  # as before Task 18, after __init__
    old._load_state()
    assert old._moment_novelty == {}
    _goals(old, ("Learn the chords", 1.0))
    assert old.get_moment().on_mind[0] == "You've been working on “Learn the chords”."
    with sqlite3.connect(old._db_path) as conn:
        assert conn.execute("SELECT cues FROM life_moment_state WHERE id = 1").fetchone()[0] != "{}"


def test_only_the_memory_cues_rendered_are_reinforced(tmp_path):
    """Ruling T12-R2: retrieval is side-effect free; only the at most two
    episodes rendered gain strength."""
    svc = _svc(tmp_path)
    for n, what in enumerate(("You swam at the lake", "You baked bread", "You fixed the bike", "You read Emma")):
        _episode(svc, what, at=T0 - timedelta(hours=n))
    before = {e.id: e.strength for e in svc._memory.episodes}
    moment = svc.get_moment()
    after = {e.id: e.strength for e in svc._memory.episodes}
    rendered = {e.id for e in svc._memory.episodes if any(e.what in line for line in moment.on_mind)}
    assert rendered and len(rendered) <= 2
    assert {i for i in after if after[i] != before[i]} == rendered
    assert all(after[i] == before[i] + 1 for i in rendered)


def test_get_moment_consumes_no_latch_and_marks_nothing(tmp_path):
    """Ruling T18-R2: the moment reads. Here it renders no memory cue (the
    one episode is the shareable's, offered, never reinforced), so nothing of
    her state changes but the novelty it saves: not her place -- though her
    plan's slot is at the gym and ``get_current_location`` moves her there --
    not her mood, not a life event's or a shareable's shared flag, not the
    just-woke latch (fix round 1, C1)."""
    from aura_life.models import DailyPlan, PlannedSlot
    svc = _svc(tmp_path)
    svc._daily_planner._current_plan = DailyPlan(date=T0.date().isoformat(), slots=[
        PlannedSlot(hour=T0.hour, activity_name="yoga", reason="routine", location="gym")])
    svc._woke_pending = True
    shared = svc._create_shareable_from_text("She found a twenty")
    event = svc._life_events.record_event(event_type="serendipity", title="Saw a heron",
                                          description="Saw a heron", share_urgency=0.4)
    svc._remember("You found a twenty", place="park", tags=("chaos", shared.share_id))

    def state():
        return (svc._current_location, svc.export_inner_state(), svc.export_outer_state(),
                [e.share_id for e in svc._life_events.get_unshared_events()])

    before = state()
    assert before[0] == "home" and before[3] == [event.share_id]
    svc.get_moment()
    assert state() == before
    assert svc.consume_just_woke() is True
    assert [e.share_id for e in svc.get_shareable_experiences()] == [shared.share_id]


# ======================================================================
# 6. Speech: length, questions, naming, disclosure by depth
# ======================================================================

@pytest.mark.parametrize("traits,target", [
    ([], DEFAULT_LENGTH),
    (["Short sentences, one at a time"], DEFAULT_LENGTH),
    (["Answers in one or two sentences"], LengthTarget(1, 2)),
    (["never more than a single sentence"], LengthTarget(1, 1)),
    (["Talks in three to five sentences"], LengthTarget(3, 5)),
])
def test_the_length_target_comes_from_her_traits(traits, target):
    assert length_target(traits) == target


def test_the_speech_lines_say_the_target_in_words_and_shorten_when_tired(tmp_path):
    svc = _svc(tmp_path)
    rested = svc.get_moment()
    assert rested.length == LengthTarget(2, 3)
    assert rested.speech[:3] == ("Keep it to two or three sentences.", "Ask at most one question.",
                                 "Don't name your feelings or these notes.")
    _tired(svc)
    tired = svc.get_moment()
    assert tired.length == LengthTarget(1, 2) and tired.speech[0] == "Keep it to one or two sentences."
    assert LengthTarget(1, 1).words() == "Keep it to one sentence."


def test_the_disclosure_line_is_the_one_of_her_depth(tmp_path):
    svc = _svc(tmp_path)
    assert svc.get_moment().speech[-1] == DISTANCE_LINES["early"]
    svc._expression._depth = 0.9
    svc._expression._style.relationship_stage = "deep"
    assert svc.get_moment().speech[-1] == DISTANCE_LINES["deep"]


def test_what_she_keeps_to_herself_is_one_line_of_her_secrets(tmp_path):
    svc = _svc(tmp_path)
    svc._shadow._state.secrets = ["you read {user_poss} messages", "you lied about the money"]
    (line,) = svc.get_moment().unspoken
    assert line == "You haven't told anyone: you lied about the money."
    svc._shadow._state.secrets = ["you read {user_poss} messages"]
    assert svc.get_moment().unspoken == ("You haven't told anyone: you read Robin's messages.",)


# ======================================================================
# 7. Three simulated days, twelve captures per persona (acceptance)
# ======================================================================

#: Two contrasting authored personas: every STATE_KEYS key in the form an
#: authored profile writes them (lowercase fragments addressed to her).
WREN_EXPRESSIONS = {
    "tired": "talk slower and laugh at your own yawns",
    "hungry": "bring up food every other line; get a little bossy about lunch",
    "lonely": "text first and keep the conversation going past its end",
    "stressed": "talk fast, list things, apologise for listing things",
    "low": "go gentle and small; ask for nothing",
    "restless": "suggest three plans at once and commit to none",
    "excited": "exclamation marks everywhere; start with the good part",
    "just_woke": "mumble; promise coffee before anything real",
    "drinking": "too honest and too fond; say the warm thing out loud",
    "hungover": "swear off drinking forever, dramatically",
    "sick": "croak and make a joke of the croaking",
    "after_absence": "act casual and fail; ask about everything at once",
}
MOSS_EXPRESSIONS = {
    "tired": "answer in fragments; leave the rest unsaid",
    "hungry": "get short and sharp; no patience for small talk",
    "lonely": "hint at it sideways; never say it straight",
    "stressed": "go very precise and very quiet",
    "low": "say less; let the pauses carry it",
    "restless": "pick at the conversation; change the subject twice",
    "excited": "allow one real smile into the words, then pull it back",
    "just_woke": "two words at a time; the world can wait",
    "drinking": "softer edges; say something true by accident",
    "hungover": "flat and dry; the light is too loud",
    "sick": "brush it off; admit nothing",
    "after_absence": "cool at first; warm up only if they notice",
}
#: Twelve captures over three simulated days: every six hours.
CAPTURE_EVERY = timedelta(hours=6)
CAPTURES = 12
SIM_DAYS = 3
SIM_SEED = 18
#: The spec section 6 row: fewer than a fifth of the rendered lines in six or
#: more of the twelve captures.
STATIC_IN = 6
STATIC_SHARE = 0.20


@pytest.fixture(scope="module")
def captured(tmp_path_factory):
    """Each persona's twelve renders over a three-day run at the production
    cadence: the moment is built at every sixth hour, as a host would on a
    user turn then."""
    return _capture(tmp_path_factory.mktemp("moment"))


@pytest.fixture(scope="module")
def captured_without_novelty(tmp_path_factory):
    """The same run with every cue's novelty held at 1 (the counterfactual
    ruling T18-R6 measures novelty's effect against)."""
    from aura_life.context import moment as moment_module
    real = moment_module.novelty
    moment_module.novelty = lambda store, key, now: 1.0
    try:
        return _capture(tmp_path_factory.mktemp("moment-no-novelty"))
    finally:
        moment_module.novelty = real


def _capture(data_dir):
    import sim_helpers
    from sim_helpers import PRODUCTION, SimPersona, run_days

    def authored(pid, expressions, speech_traits, **fields):
        return SimPersona(pid, service_kwargs={"definition": PersonalityDefinition(
            id=pid, name=pid.title(), appearance_details={"gender": "female"},
            state_expressions=dict(expressions), communication_traits=list(speech_traits), **fields)})

    personas = [
        SimPersona("control"),
        authored("wren", WREN_EXPRESSIONS, ["Talks in two or three sentences, warm and quick"],
                 traits={"sociability": 0.9, "rumination": 0.2}),
        authored("moss", MOSS_EXPRESSIONS, ["Answers in one or two sentences"],
                 traits={"sociability": 0.1, "rumination": 0.8}, struggles=["self-doubt"]),
    ]
    start = sim_helpers.DEFAULT_START
    renders = {p.persona_id: [] for p in personas}
    moments = {p.persona_id: [] for p in personas}
    original = sim_helpers._record_step

    def recording(t, svc, probe, ticks):
        record = original(t, svc, probe, ticks)
        if (t - start) % CAPTURE_EVERY == timedelta(0):
            moment = svc.get_moment()
            moments[svc._persona_id].append(moment)
            renders[svc._persona_id].append(moment.render())
        return record

    sim_helpers._record_step = recording
    try:
        trace = run_days(personas, days=SIM_DAYS, seed=SIM_SEED, cadence=PRODUCTION, data_dir=data_dir)
    finally:
        sim_helpers._record_step = original
    assert trace.errors == []
    return renders, moments


def _static_share(renders):
    """(distinct lines, the share of them in STATIC_IN or more captures, the
    share of all rendered lines that are such a line)."""
    seen = Counter(line for text in renders for line in set(text.splitlines()))
    static = {line for line, n in seen.items() if n >= STATIC_IN}
    total = sum(len(text.splitlines()) for text in renders)
    weighted = sum(1 for text in renders for line in text.splitlines() if line in static)
    return len(seen), len(static) / len(seen), weighted / total


def test_twelve_captures_per_persona_render_clean(captured):
    renders, _ = captured
    for pid, texts in renders.items():
        assert len(texts) == CAPTURES, (pid, len(texts))
        for text in texts:
            assert_moment_clean(text)


def _her_lines(moment):
    """The rendered lines that describe her: all but the speech line, the
    instruction block the design keeps the same on purpose (ruling T18-R9)."""
    speech = " ".join(" ".join(part for part in moment.speech if part).split())
    return [line for line in moment.lines() if line != speech]


def _static_share_of_her_lines(moments):
    """The row as its source measured it (the 2026-09-25 report's "share of
    each capture that is static (in 6 or more of 12)"): of ALL the lines
    that describe her in the twelve captures, the share whose line is in
    STATIC_IN or more of them."""
    captures = [_her_lines(moment) for moment in moments]
    seen = Counter(line for lines in captures for line in set(lines))
    total = sum(len(lines) for lines in captures)
    return sum(1 for lines in captures for line in lines if seen[line] >= STATIC_IN) / total


def test_fewer_than_a_fifth_of_the_rendered_lines_are_static(captured):
    """Spec section 6: "Moment lines static across 12 captures < 20%", read
    as its source measured it (ruling T18-R9): of all the lines that describe
    her, fewer than a fifth are a line that is in six or more of the twelve
    captures. A line said in every capture counts twelve times, so one
    frozen line of her six is most of the row. (Printed for the report: the
    share of the distinct lines, and of all rendered lines with the speech
    line counted.)"""
    renders, moments = captured
    for pid, texts in renders.items():
        distinct, of_distinct, with_speech = _static_share(texts)
        share = _static_share_of_her_lines(moments[pid])
        print(f"{pid}: static {share:.3f} of the lines that describe her; {of_distinct:.3f} of the {distinct} "
              f"distinct lines; {with_speech:.3f} of all rendered lines, the speech line counted")
        assert share < STATIC_SHARE, (pid, share)


def test_her_situation_line_is_never_static(captured):
    """Fix round 2, C4: the distinct-line reading above tolerates several
    more frozen lines (a situation frozen to one sentence stayed green), so
    the situation is held to the row line by line: it says the time of day
    and the weather, and captures six hours apart fall in different parts of
    the day, so no situation line is in six or more of the twelve captures.
    Novelty's cues are held by test_novelty_makes_her_moments_less_static;
    which reading the section-6 row means is the controller's."""
    _, moments = captured
    for pid, ms in moments.items():
        seen = Counter(m.situation for m in ms)
        assert [(n, line) for line, n in seen.items() if n >= STATIC_IN] == [], (pid, seen.most_common(3))


def test_novelty_makes_her_moments_less_static(captured, captured_without_novelty):
    """Ruling T18-R6: novelty's effect on the section-6 row, per persona --
    the same run with novelty held at 1 has more static lines, by both
    measures (printed for the report)."""
    with_novelty, _ = captured
    without, _ = captured_without_novelty
    for pid in with_novelty:
        _, share, weighted = _static_share(with_novelty[pid])
        _, share_off, weighted_off = _static_share(without[pid])
        print(f"{pid}: static {share:.3f} of distinct lines ({share_off:.3f} without novelty), "
              f"{weighted:.3f} of all lines ({weighted_off:.3f} without)")
        assert share < share_off and weighted < weighted_off, pid


def test_an_authored_persona_s_own_expressions_reach_her_moments(captured):
    renders, moments = captured
    for pid, expressions in (("wren", WREN_EXPRESSIONS), ("moss", MOSS_EXPRESSIONS)):
        undercurrents = " ".join(m.undercurrent for m in moments[pid])
        assert any(text in undercurrents for text in expressions.values()), (pid, undercurrents)
        assert not any(text in undercurrents for text in NEUTRAL_EXPRESSIONS.values()), pid
    # Her traits' target: moss's "one or two sentences" in every capture,
    # tired or not; wren's "two or three" when she is not tired.
    assert {m.length for m in moments["moss"]} <= {LengthTarget(1, 2), LengthTarget(1, 1)}
    assert LengthTarget(2, 3) in {m.length for m in moments["wren"]}


# ======================================================================
# 8. Ruling T18-R7: the work line's slot is rendered
# ======================================================================

def test_her_context_renders_the_work_line_s_slot(tmp_path):
    """The career section read the career engine's raw text: "earlier you
    got praised by {poss} boss" reached her context unrendered."""
    svc = _svc(tmp_path, occupation="nurse")
    svc._career._state.employed = True
    svc._career._state.recent_work_event = "got praised by {poss} boss"
    section = svc._context_builder._build_career_section()
    assert "earlier you got praised by your boss" in section, section
    _check_rendered(section, section, is_second_person=True)
