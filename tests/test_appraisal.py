"""Appraisal, and outcomes that can go wrong (humanness program Task 14, spec
section 4.7).

Measured before this task: every activity succeeded, and every activity was
felt as the same fixed emotions every time -- ``ActivityEngine`` copied the
setting's ``emotion_effects`` onto the log -- never judged against what the
persona wanted, needed or valued. An appraisal step (Chain-of-Emotion, PLOS
ONE 2024) raised perceived naturalness (p = .008); human text carries more
negative emotion and more variation than LLM text.

Now an activity has an outcome -- success, mixed or fail -- rolled from her
skill at it, her energy for it and her mood, told in her setting's words
(the library's neutral words when it has none); and what she feels about it
is appraised (``aura_life.emotion.appraisal.appraise``) from its relevance to
her active goals, the needs it meets, the values it expresses, whose doing it
was and how expected the outcome was, scaled by her volatility. What went
wrong reaches her mood and her memory.

Sections: 1. ``appraise`` (pure); 2. the optional LLM appraisal's reply,
validated (pure); 3. what her setting says happened when it does not go
well; 4. how an activity goes (``ActivityEngine``); 5. mood takes an
appraised feeling as she felt it; 6. her life: how it went reaches her log,
her mood, her memory, her goals and the housemate who joins her; 7. the
optional LLM appraisal (``appraisal_llm``); 8. three simulated days
(acceptance); 9. the day's quality (fix round 1, ruling T14-R1).
"""

import contextlib
import dataclasses
import logging
import pathlib
import random
import sqlite3
from collections import Counter
from datetime import date, datetime

import pytest

from aura_life import hooks

from aura_life.activities.activity_engine import (
    NEUTRAL_OUTCOME_NARRATIVES,
    OUTCOME_BASE_RISK,
    OUTCOME_EFFORT_RISK,
    OUTCOME_FAIL_SHARE,
    OUTCOME_LOW_MOOD_RISK,
    OUTCOME_MAX_RISK,
    OUTCOME_UNSKILLED_RISK,
    ActivityEngine,
    outcome_chances,
)
from aura_life.affect.affect_system import DAY_QUALITY_PER_SLEEP_QUALITY, DAY_QUALITY_SD, AffectSystem
from aura_life.emotion.appraisal import (
    FAIL,
    FAILED_IMPOSED_EMOTION,
    FAILED_OWN_EMOTION,
    GOAL_EMOTIONS,
    LLM_APPRAISAL_MAX_EMOTIONS,
    MIXED,
    NEED_FEELINGS,
    OUTCOMES,
    RELIEF_EMOTION,
    RESIGNATION_EMOTION,
    SUCCESS,
    VALUE_EMOTIONS,
    AppraisalEvent,
    appraise,
    appraised_valence,
    emotions_of,
    llm_appraisal_prompt,
    parse_llm_appraisal,
)
from aura_life.activities.choice import ChoiceState
from aura_life.body.body_system import SLEEP_QUALITY_BASE
from aura_life.emotion.text_emotion_analyzer import EmotionSpike
from aura_life.emotion.vocabulary import EMOTION_VOCABULARY, valence_arousal
from aura_life.life_service import LifeService
from aura_life.models import (
    Activity,
    DailyPlan,
    Goal,
    GoalTimeframe,
    PlannedSlot,
    ShortTermDesire,
    SkillProgress,
    ValueBelief,
    Weather,
)
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.personas.parameters import PersonaParameters
from aura_life.settings import get_setting, register_setting, unregister_setting
from aura_life.settings.spec import NEED_KEYS, NON_SUCCESS_OUTCOMES
from aura_life.social import Household
from aura_life.world import WorldEnvironment

# ======================================================================
# 1. appraise
# ======================================================================

#: The contemporary "reading": what the setting says it feels like when it
#: goes well (stake 0.45), the needs it meets, and what a value can be
#: aligned with (its category and tags).
READING_EMOTIONS = {"curious": 0.1, "content": 0.15, "absorbed": 0.2}
READING_STAKE = 0.45
NEUTRAL = PersonaParameters()


def _event(outcome=SUCCESS, **fields) -> AppraisalEvent:
    values = dict(what="reading", outcome=outcome, emotions=dict(READING_EMOTIONS),
                  satisfies={"stimulation": 1.0, "solitude": 1.0, "calm": 1.0},
                  aligned_tags=frozenset({"mental", "flow", "focus", "quiet"}), success_chance=0.9)
    values.update(fields)
    return AppraisalEvent(**values)


def _felt(spikes) -> dict:
    return emotions_of(spikes)


def _negative(spikes) -> dict:
    return {name: x for name, x in _felt(spikes).items() if valence_arousal(name)[0] < 0}


def _positive(spikes) -> dict:
    return {name: x for name, x in _felt(spikes).items() if valence_arousal(name)[0] > 0}


def _goal(activity="reading", motivation=1.0, timeframe=GoalTimeframe.WEEKLY) -> Goal:
    return Goal(title="Read more", timeframe=timeframe, motivation_level=motivation,
                related_activities=[activity])


def test_the_same_failed_event_is_felt_more_strongly_by_a_volatile_persona():
    """The brief's acceptance: volatility 0.9 against 0.1, one failed event."""
    event = _event(FAIL)
    steady = _negative(appraise(event, PersonaParameters(volatility=0.1), [], {}, []))
    volatile = _negative(appraise(event, PersonaParameters(volatility=0.9), [], {}, []))
    assert steady and set(volatile) == set(steady)
    assert max(volatile.values()) > max(steady.values())
    for name, intensity in steady.items():
        assert volatile[name] > intensity, name
    # Volatility's own multiplier from the one table (Task 8, row 1): 1.5 / 0.5.
    assert max(volatile.values()) == pytest.approx(3 * max(steady.values()))


def test_failing_an_activity_tied_to_an_active_goal_yields_frustration_or_disappointment():
    """The brief's acceptance; and it is the goal that disappoints her: a
    goal that does not list the activity changes nothing."""
    felt = _felt(appraise(_event(FAIL), NEUTRAL, [_goal()], {}, []))
    assert {"frustrated", "disappointed"} <= set(felt)
    assert all(valence_arousal(name)[0] < 0 for name in felt), felt
    without = _felt(appraise(_event(FAIL), NEUTRAL, [], {}, []))
    assert "disappointed" not in without
    unrelated = _felt(appraise(_event(FAIL), NEUTRAL, [_goal(activity="going for a run")], {}, []))
    assert unrelated == without


def test_a_goal_s_pull_is_its_motivation():
    """Relevance to a goal is the strongest motivation among her goals that
    list the activity: a third of the stake at full motivation."""
    strong = _felt(appraise(_event(FAIL), NEUTRAL, [_goal(motivation=1.0), _goal(motivation=0.2)], {}, []))
    weak = _felt(appraise(_event(FAIL), NEUTRAL, [_goal(motivation=0.3)], {}, []))
    assert strong["disappointed"] == pytest.approx(READING_STAKE / 3)
    assert weak["disappointed"] == pytest.approx(READING_STAKE * 0.3 / 3)
    proud = _felt(appraise(_event(SUCCESS), NEUTRAL, [_goal(motivation=1.0)], {}, []))
    assert proud["proud"] == pytest.approx(READING_STAKE / 3)


def test_a_success_she_was_sure_of_serving_nothing_else_is_felt_as_the_setting_wrote_it():
    """The neutral persona's success with nothing at stake but the activity
    itself is exactly what the setting's table says -- what every activity
    felt like before this task."""
    felt = _felt(appraise(_event(SUCCESS, success_chance=1.0, satisfies={}), NEUTRAL, [], {}, []))
    assert felt == pytest.approx(READING_EMOTIONS)


def test_a_success_is_never_felt_as_a_negative_emotion_and_a_failure_never_as_a_positive_one():
    goals, needs = [_goal()], {"stimulation": 0.8, "calm": 0.5}
    values = [ValueBelief(name="knowledge", salience=0.9, aligned_tags=["mental"])]
    success = appraise(_event(SUCCESS, success_chance=0.6), NEUTRAL, goals, needs, values)
    fail = appraise(_event(FAIL, success_chance=0.6), NEUTRAL, goals, needs, values)
    assert _positive(success) and not _negative(success)
    assert _negative(fail) and not _positive(fail)


@pytest.mark.parametrize("need", sorted(NEED_KEYS))
def test_a_need_she_feels_is_met_by_a_success_and_left_unmet_by_a_failure(need):
    """Each need has its own feeling, met or not (NEED_FEELINGS), as strong
    as how unmet it was times how much the activity meets it."""
    met, unmet = NEED_FEELINGS[need]
    event = dict(satisfies={need: 1.0}, emotions={"content": 0.3})
    success = _felt(appraise(_event(SUCCESS, success_chance=1.0, **event), NEUTRAL, [], {need: 0.6}, []))
    fail = _felt(appraise(_event(FAIL, success_chance=1.0, **event), NEUTRAL, [], {need: 0.6}, []))
    assert success[met] == pytest.approx(0.3 * 0.6 / 3)
    # (Hunger's unmet feeling is also the failed attempt's own: frustration.)
    assert fail[unmet] == pytest.approx(0.3 * 0.6 / 3 + (0.3 if unmet == "frustrated" else 0.0))
    # Not felt when she did not need it, nor when the activity does not meet it.
    unneeded = _felt(appraise(_event(SUCCESS, success_chance=1.0, **event), NEUTRAL, [], {need: 0.0}, []))
    no_meet = _felt(appraise(_event(SUCCESS, success_chance=1.0, satisfies={}, emotions={"content": 0.3}),
                             NEUTRAL, [], {need: 0.6}, []))
    assert unneeded == no_meet == {"content": pytest.approx(0.3)}


def test_every_need_has_a_met_and_an_unmet_feeling_in_the_vocabulary():
    assert set(NEED_FEELINGS) == set(NEED_KEYS)
    for need, (met, unmet) in NEED_FEELINGS.items():
        assert met in EMOTION_VOCABULARY and unmet in EMOTION_VOCABULARY, need
        assert valence_arousal(met)[0] > 0 > valence_arousal(unmet)[0], need


def test_every_name_an_appraisal_gives_is_in_the_vocabulary_with_the_sign_of_its_outcome():
    good = [RELIEF_EMOTION, GOAL_EMOTIONS[0], VALUE_EMOTIONS[0]]
    bad = [FAILED_OWN_EMOTION, FAILED_IMPOSED_EMOTION, RESIGNATION_EMOTION, GOAL_EMOTIONS[1], VALUE_EMOTIONS[1]]
    for name in good + bad:
        assert name in EMOTION_VOCABULARY, name
    assert all(valence_arousal(name)[0] > 0 for name in good)
    assert all(valence_arousal(name)[0] < 0 for name in bad)


def test_hunger_met_by_a_meal_is_satisfaction_and_a_ruined_meal_is_frustration():
    meal = dict(what="cooking a meal", emotions={"creative": 0.1, "satisfied": 0.1, "content": 0.1},
                satisfies={"hunger": 1.0}, aligned_tags=frozenset({"creative", "meal"}))
    hungry = {"hunger": 0.9}
    ate = _felt(appraise(_event(SUCCESS, **meal), NEUTRAL, [], hungry, []))
    not_hungry = _felt(appraise(_event(SUCCESS, **meal), NEUTRAL, [], {"hunger": 0.0}, []))
    assert ate["satisfied"] > not_hungry["satisfied"]
    ruined = _felt(appraise(_event(FAIL, **meal), NEUTRAL, [], hungry, []))
    ruined_fed = _felt(appraise(_event(FAIL, **meal), NEUTRAL, [], {"hunger": 0.0}, []))
    assert ruined["frustrated"] > ruined_fed["frustrated"]


def test_her_traits_weigh_her_needs_as_they_do_when_she_chooses():
    """The need weights of Task 8's table (an extrovert's loneliness weighs
    1.5, an introvert's 0.5): the same company meets more of an extrovert's
    need."""
    event = _event(SUCCESS, what="video call with a friend", satisfies={"social": 1.0},
                   emotions={"connected": 0.2}, success_chance=1.0)
    extrovert = _felt(appraise(event, PersonaParameters(sociability=0.9), [], {"social": 0.4}, []))
    introvert = _felt(appraise(event, PersonaParameters(sociability=0.1), [], {"social": 0.4}, []))
    assert extrovert["connected"] > introvert["connected"]


def test_the_needs_an_activity_meets_count_at_most_as_one_fully_met_need():
    event = _event(SUCCESS, satisfies={"stimulation": 1.0, "calm": 1.0, "solitude": 1.0}, success_chance=1.0,
                   emotions={"content": 0.3})
    felt = _felt(appraise(event, NEUTRAL, [], {"stimulation": 1.0, "calm": 1.0, "solitude": 1.0}, []))
    met = {NEED_FEELINGS[n][0] for n in ("stimulation", "calm", "solitude")}
    assert sum(felt[name] for name in met) == pytest.approx(0.3 / 3)


def test_an_activity_that_expresses_a_value_she_holds_fulfils_her_and_failing_at_it_discourages_her():
    knowledge = ValueBelief(name="knowledge", salience=0.9, aligned_tags=["mental"])
    unrelated = ValueBelief(name="connection", salience=1.0, aligned_tags=["social"])
    success = _felt(appraise(_event(SUCCESS), NEUTRAL, [], {}, [knowledge, unrelated]))
    fail = _felt(appraise(_event(FAIL), NEUTRAL, [], {}, [knowledge, unrelated]))
    assert success["fulfilled"] == pytest.approx(READING_STAKE * 0.9 / 3)
    assert fail["discouraged"] == pytest.approx(READING_STAKE * 0.9 / 3)
    assert "fulfilled" not in _felt(appraise(_event(SUCCESS), NEUTRAL, [], {}, [unrelated]))
    # IdentitySystem's dict form (what LifeService hands ActivityEngine) reads the same.
    as_dict = _felt(appraise(_event(SUCCESS), NEUTRAL, [], {},
                             [{"name": "knowledge", "salience": 0.9, "aligned_tags": ["mental"]}]))
    assert as_dict == success


def test_whose_doing_a_failure_was_decides_its_feeling():
    """Agency: an attempt of her own that fails frustrates her; a commitment
    she had to keep that goes wrong annoys her."""
    own = _felt(appraise(_event(FAIL, chosen=True), NEUTRAL, [], {}, []))
    imposed = _felt(appraise(_event(FAIL, chosen=False), NEUTRAL, [], {}, []))
    assert "frustrated" in own and "annoyed" not in own
    assert "annoyed" in imposed and "frustrated" not in imposed
    assert own["frustrated"] == pytest.approx(imposed["annoyed"])


def test_how_expected_the_outcome_was_decides_how_it_is_felt_not_how_strongly():
    """Expectedness (OCC's prospect-based emotions): a failure she did not
    see coming is frustration, one she half expected resignation; a success
    she doubted brings relief. The event's share of the stake is the same
    either way."""
    sure = _felt(appraise(_event(FAIL, success_chance=0.95), NEUTRAL, [], {}, []))
    doubtful = _felt(appraise(_event(FAIL, success_chance=0.4), NEUTRAL, [], {}, []))
    assert sure["frustrated"] == pytest.approx(READING_STAKE * 0.95)
    assert sure["resigned"] == pytest.approx(READING_STAKE * 0.05)
    assert doubtful["resigned"] > doubtful["frustrated"]
    assert sum(sure.values()) == pytest.approx(sum(doubtful.values()))
    relieved = _felt(appraise(_event(SUCCESS, success_chance=0.5, satisfies={}), NEUTRAL, [], {}, []))
    assert relieved["relieved"] == pytest.approx(READING_STAKE * 0.5)
    assert sum(relieved.values()) == pytest.approx(READING_STAKE)
    certain = _felt(appraise(_event(SUCCESS, success_chance=1.0, satisfies={}), NEUTRAL, [], {}, []))
    assert "relieved" not in certain


def test_a_mixed_outcome_is_half_a_success_and_half_a_failure():
    goals, needs = [_goal()], {"stimulation": 0.6}
    values = [ValueBelief(name="knowledge", salience=0.8, aligned_tags=["mental"])]
    success = _felt(appraise(_event(SUCCESS), NEUTRAL, goals, needs, values))
    fail = _felt(appraise(_event(FAIL), NEUTRAL, goals, needs, values))
    mixed = _felt(appraise(_event(MIXED), NEUTRAL, goals, needs, values))
    expected = {}
    for felt in (success, fail):
        for name, x in felt.items():
            expected[name] = expected.get(name, 0.0) + x / 2
    assert mixed == pytest.approx(expected)
    assert _positive(appraise(_event(MIXED), NEUTRAL, goals, needs, values))
    assert _negative(appraise(_event(MIXED), NEUTRAL, goals, needs, values))


def test_an_activity_its_setting_gives_no_feeling_is_not_felt():
    assert appraise(_event(FAIL, emotions={}), NEUTRAL, [_goal()], {"stimulation": 1.0}, []) == []


def test_every_spike_is_a_vocabulary_name_with_an_intensity_in_0_1():
    """Whatever the outcome, stake, relevance, expectedness and volatility,
    including a stake past 1 and the most volatile persona."""
    values = [ValueBelief(name="knowledge", salience=1.0, aligned_tags=["mental"])]
    needs = {need: 1.0 for need in NEED_KEYS}
    heavy = {"curious": 0.9, "content": 0.9, "absorbed": 0.9}
    for outcome in OUTCOMES:
        for chance in (0.0, 0.5, 1.0):
            for volatility in (0.0, 0.5, 1.0):
                for emotions in (READING_EMOTIONS, heavy):
                    spikes = appraise(_event(outcome, success_chance=chance, emotions=emotions,
                                             satisfies={need: 1.0 for need in NEED_KEYS}),
                                      PersonaParameters(volatility=volatility), [_goal()], needs, values)
                    assert spikes
                    for spike in spikes:
                        assert spike.emotion in EMOTION_VOCABULARY, spike
                        assert 0.0 < spike.intensity <= 1.0, spike
                    assert len({s.emotion for s in spikes}) == len(spikes)  # merged, one spike a name


def test_no_parameters_is_the_neutral_persona():
    event = _event(FAIL)
    assert _felt(appraise(event, None, [], {}, [])) == _felt(appraise(event, NEUTRAL, [], {}, []))


def test_an_outcome_it_does_not_know_is_refused():
    with pytest.raises(ValueError):
        AppraisalEvent(what="reading", outcome="triumph")


def test_the_appraised_valence_is_how_the_event_felt():
    """The valence her memory keeps of it (Task 12's episode): the
    intensity-weighted valence of what she felt -- not her mood."""
    fail = appraise(_event(FAIL), NEUTRAL, [_goal()], {}, [])
    success = appraise(_event(SUCCESS), NEUTRAL, [_goal()], {}, [])
    assert appraised_valence(fail) < 0 < appraised_valence(success)
    frustrated_only = appraise(_event(FAIL, success_chance=1.0, satisfies={}), NEUTRAL, [], {}, [])
    assert appraised_valence(frustrated_only) == pytest.approx(valence_arousal("frustrated")[0])
    assert appraised_valence([]) is None


def test_the_spikes_say_which_check_made_them():
    """EmotionSpike's ``word``: the appraisal check a feeling came from."""
    spikes = appraise(_event(FAIL, success_chance=0.8), NEUTRAL, [_goal()], {"stimulation": 0.5},
                      [ValueBelief(name="knowledge", salience=0.9, aligned_tags=["mental"])])
    sources = {spike.emotion: spike.word for spike in spikes}
    assert sources["frustrated"] == "outcome"
    assert sources["resigned"] == "expectedness"
    assert sources["disappointed"] == "goal"
    assert sources[NEED_FEELINGS["stimulation"][1]] == "need:stimulation"
    assert sources["discouraged"] == "value"


def test_a_need_an_activity_costs_her_is_no_need_it_meets():
    """Company, to a drained introvert, is a cost (satisfies < 0): it is
    not felt as a need met, nor -- when it goes wrong -- as one left unmet."""
    event = dict(satisfies={"solitude": -1.0}, emotions={"connected": 0.3}, success_chance=1.0)
    for outcome in (SUCCESS, FAIL):
        felt = _felt(appraise(_event(outcome, **event), NEUTRAL, [], {"solitude": 0.9}, []))
        assert not {NEED_FEELINGS["solitude"][0], NEED_FEELINGS["solitude"][1]} & set(felt), outcome


# ======================================================================
# 2. The optional LLM appraisal's reply, validated
# ======================================================================

def test_the_llm_is_told_what_happened_what_it_was_for_and_how_to_answer():
    prompt = llm_appraisal_prompt(
        _event(MIXED, chosen=False, success_chance=0.75),
        goal_titles=["Read more"], needs={"stimulation": 0.6, "rest": 0.1},
        values=[ValueBelief(name="knowledge", salience=0.9, aligned_tags=["mental"])])
    for words in ("reading", "only half went well", "something they had to do", "75 in 100",
                  "Read more", "stimulation", "knowledge", "JSON"):
        assert words in prompt, words
    (needed,) = [line for line in prompt.splitlines() if line.startswith("They needed:")]
    assert "rest" not in needed  # a need barely felt is left out


def test_a_well_formed_llm_reply_is_read_as_vocabulary_names_and_intensities():
    assert parse_llm_appraisal('{"frustrated": 0.6, "disappointed": 0.3}') == {
        "frustrated": 0.6, "disappointed": 0.3}


def test_an_llm_reply_s_json_is_found_inside_prose():
    raw = 'Here is how she feels:\n{"Let Down": 0.4, "tired": 0.2}\nHope that helps.'
    assert parse_llm_appraisal(raw) == {"let_down": 0.4, "tired": 0.2}


def test_an_llm_reply_keeps_only_names_the_vocabulary_knows():
    assert parse_llm_appraisal('{"frustrated": 0.5, "schadenfreude-ish": 0.9}') == {"frustrated": 0.5}
    assert parse_llm_appraisal('{"flibbertigibbet": 0.9}') is None


def test_an_llm_reply_s_intensities_are_clamped_and_non_numbers_dropped():
    assert parse_llm_appraisal('{"frustrated": 1.7, "sad": -0.4, "tired": "a lot", "calm": true}') == {
        "frustrated": 1.0}


def test_an_llm_reply_gives_at_most_its_strongest_few_feelings():
    raw = '{"sad": 0.2, "tired": 0.9, "lonely": 0.5, "bored": 0.7, "frustrated": 0.3}'
    parsed = parse_llm_appraisal(raw)
    assert len(parsed) == LLM_APPRAISAL_MAX_EMOTIONS
    assert parsed == {"tired": 0.9, "bored": 0.7, "lonely": 0.5}


def test_a_malformed_object_in_an_llm_reply_is_passed_over_for_the_next_one():
    """Fix round 1, B2: the parser looks past an object it cannot read to the
    next flat object in the reply."""
    assert parse_llm_appraisal('{"frustrated": } and then {"sad": 0.4}') == {"sad": 0.4}


def test_an_llm_appraisal_of_a_failure_keeps_no_pleasant_feeling():
    """Fix round 1, C1: an LLM's feelings are checked against how it went --
    a failure keeps none the vocabulary calls pleasant, a success none it
    calls unpleasant; nothing left is no appraisal at all."""
    assert parse_llm_appraisal('{"joyful": 0.9}', outcome=FAIL) is None
    assert parse_llm_appraisal('{"frustrated": 0.6, "joyful": 0.9}', outcome=FAIL) == {"frustrated": 0.6}
    assert parse_llm_appraisal('{"frustrated": 0.6, "joyful": 0.9}', outcome=SUCCESS) == {"joyful": 0.9}


def test_an_llm_appraisal_of_a_mixed_outcome_keeps_both_kinds_and_a_neutral_name_always_stays():
    assert parse_llm_appraisal('{"frustrated": 0.6, "joyful": 0.9}', outcome=MIXED) == {
        "frustrated": 0.6, "joyful": 0.9}
    assert valence_arousal("neutral")[0] == 0.0
    for outcome in OUTCOMES:
        assert parse_llm_appraisal('{"neutral": 0.3}', outcome=outcome) == {"neutral": 0.3}, outcome
    # With no outcome to check it against, nothing is filtered.
    assert parse_llm_appraisal('{"frustrated": 0.6, "joyful": 0.9}') == {"frustrated": 0.6, "joyful": 0.9}


def test_the_strongest_few_are_chosen_after_the_check_against_the_outcome():
    raw = '{"joyful": 1.0, "delighted": 0.95, "proud": 0.9, "sad": 0.3, "tired": 0.2}'
    assert parse_llm_appraisal(raw, outcome=FAIL) == {"sad": 0.3, "tired": 0.2}


@pytest.mark.parametrize("raw", [None, "", "no json here", "[0.5, 0.3]", '{"frustrated": }', "{}",
                                 '{"frustrated": 0}'])
def test_an_unusable_llm_reply_is_none(raw):
    assert parse_llm_appraisal(raw) is None

# ======================================================================
# 3. What her setting says happened when it does not go well
# ======================================================================

def _performable(setting):
    """Every activity of ``setting`` she can do through her activity tick:
    all but the night's sleep (a state, never done as an activity)."""
    return [a for a in setting.resolved_activities() if "sleep" not in a.tags]


def test_the_outcomes_an_activity_tells_are_the_ones_that_are_not_success():
    """Success is told by the activity's own narratives (today's text); an
    activity's ``outcomes`` tell the rest."""
    assert NON_SUCCESS_OUTCOMES == (MIXED, FAIL)
    assert set(NON_SUCCESS_OUTCOMES) | {SUCCESS} == set(OUTCOMES)


def test_every_contemporary_activity_she_can_do_says_how_it_went_when_it_did_not_go_well():
    for activity in _performable(get_setting("contemporary")):
        for outcome in NON_SUCCESS_OUTCOMES:
            texts = activity.outcomes.get(outcome)
            assert texts and all(isinstance(t, str) and t.strip() for t in texts), (activity.name, outcome)
            assert not set(texts) & set(activity.narrative_templates), (activity.name, outcome)
        assert set(activity.outcomes) == set(NON_SUCCESS_OUTCOMES), activity.name


def test_an_activity_without_outcome_texts_is_still_an_activity():
    """The field defaults to none: a pack that writes no outcome texts is
    told in the library's neutral words (section 4)."""
    bare = Activity(name="x", category=get_setting().activities[0].category, energy_cost=0.1, min_energy=0.1,
                    duration_minutes=10, preferred_times=[], preferred_weather=[], suitable_locations=["home"],
                    narrative_templates=["Did x"], thought_possibilities=[], emotion_effects={})
    assert bare.outcomes == {}


@pytest.mark.parametrize("outcomes,why", [
    ({"success": ["It went well"]}, "success is told by narrative_templates"),
    ({"triumph": ["Won"]}, "an outcome that does not exist"),
    ({"fail": "It went wrong"}, "a str where a list belongs"),
    ({"fail": []}, "nothing to draw"),
    ({"fail": ["It went wrong", ""]}, "a blank text"),
    ({"fail": ["It went wrong", 3]}, "not text"),
    (["It went wrong"], "not a mapping"),
])
def test_register_setting_refuses_outcome_texts_the_engine_could_not_tell(outcomes, why):
    base = get_setting()
    reading = next(a for a in base.activities if a.name == "reading")
    broken = dataclasses.replace(reading, outcomes=outcomes)
    spec = dataclasses.replace(base, key="test-bad-outcomes",
                               activities=[broken if a is reading else a for a in base.activities])
    with pytest.raises(ValueError, match="outcomes"):
        register_setting(spec)
    assert unregister_setting("test-bad-outcomes") is False, why


def test_a_pack_can_leave_out_the_outcome_texts_of_any_activity():
    base = get_setting()
    plain = [dataclasses.replace(a, outcomes={}) for a in base.activities]
    register_setting(dataclasses.replace(base, key="test-no-outcomes", activities=plain))
    try:
        assert all(a.outcomes == {} for a in get_setting("test-no-outcomes").activities)
    finally:
        unregister_setting("test-no-outcomes")


# ======================================================================
# 4. How an activity goes (ActivityEngine)
# ======================================================================

def _activity(name: str) -> Activity:
    return next(a for a in get_setting().resolved_activities() if a.name == name)


class _Draws:
    """A stand-in rng: ``random()`` gives the values it was made with, in
    turn; ``choice`` the first item. Counts its calls."""

    def __init__(self, *values):
        self.values = list(values)
        self.calls = 0

    def random(self):
        self.calls += 1
        return self.values.pop(0)

    def choice(self, seq):
        self.calls += 1
        return list(seq)[0]


def test_the_chances_of_the_three_outcomes_add_up_to_one():
    for name in ("reading", "gym workout", "napping", "working"):
        for energy in (0.0, 0.4, 1.0):
            for valence in (-1.0, 0.0, 1.0):
                for skill in (None, 0.0, 1.0):
                    chances = outcome_chances(_activity(name), energy=energy, valence=valence, skill=skill)
                    assert set(chances) == set(OUTCOMES)
                    assert sum(chances.values()) == pytest.approx(1.0)
                    assert all(0.0 <= x <= 1.0 for x in chances.values())


def test_a_hobby_mostly_goes_fine():
    """Rested, in a good mood, at something she has mastered: little but the
    base risk -- and the same for something that trains no skill."""
    reading = _activity("reading")
    fine = outcome_chances(reading, energy=1.0, valence=0.3, skill=1.0)
    assert fine[SUCCESS] == pytest.approx(1 - OUTCOME_BASE_RISK - OUTCOME_EFFORT_RISK * reading.energy_cost)
    assert fine[SUCCESS] > 0.85
    music = _activity("listening to music")
    assert outcome_chances(music, energy=1.0, valence=0.3)[SUCCESS] > 0.85


def test_it_goes_wrong_more_often_when_she_is_tired_low_or_new_to_it():
    run = _activity("going for a run")
    base = outcome_chances(run, energy=1.0, valence=0.0, skill=1.0)[SUCCESS]
    tired = outcome_chances(run, energy=0.3, valence=0.0, skill=1.0)[SUCCESS]
    low = outcome_chances(run, energy=1.0, valence=-0.5, skill=1.0)[SUCCESS]
    new = outcome_chances(run, energy=1.0, valence=0.0, skill=0.0)[SUCCESS]
    assert base - tired == pytest.approx(OUTCOME_EFFORT_RISK * (min(1.0, run.energy_cost / 0.3) - run.energy_cost))
    assert base - low == pytest.approx(OUTCOME_LOW_MOOD_RISK * 0.5)
    assert base - new == pytest.approx(OUTCOME_UNSKILLED_RISK)
    # A good mood lowers no risk past neutral's, and one that trains no skill
    # has no beginner's risk.
    assert outcome_chances(run, energy=1.0, valence=0.8, skill=1.0)[SUCCESS] == pytest.approx(base)
    assert outcome_chances(run, energy=1.0, valence=0.0, skill=None)[SUCCESS] == pytest.approx(base)


def test_tiredness_never_spoils_a_restful_activity():
    nap = _activity("napping")
    assert outcome_chances(nap, energy=0.05, valence=0.0) == outcome_chances(nap, energy=1.0, valence=0.0)


def test_the_risk_is_capped_and_most_of_it_only_half_works_out():
    gym = _activity("gym workout")
    worst = outcome_chances(gym, energy=0.0, valence=-1.0, skill=0.0)
    assert worst[SUCCESS] == pytest.approx(1 - OUTCOME_MAX_RISK)
    assert worst[FAIL] == pytest.approx(OUTCOME_FAIL_SHARE * OUTCOME_MAX_RISK)
    assert worst[MIXED] == pytest.approx((1 - OUTCOME_FAIL_SHARE) * OUTCOME_MAX_RISK)
    assert worst[MIXED] > worst[FAIL]


def test_the_roll_is_one_draw_on_the_outcome_stream_never_the_engine_s_own():
    reading = _activity("reading")
    own = random.Random(5)
    before = own.getstate()
    outcome_rng = _Draws(0.0)
    outcome, chances = ActivityEngine(rng=own, outcome_rng=outcome_rng).roll_outcome(
        reading, energy=0.5, valence=0.0, skill=0.0)
    assert outcome == FAIL and outcome_rng.calls == 1
    assert own.getstate() == before
    assert chances == outcome_chances(reading, energy=0.5, valence=0.0, skill=0.0)


def test_the_draw_lands_on_the_outcome_whose_chance_it_falls_in():
    reading = _activity("reading")
    chances = outcome_chances(reading, energy=0.5, valence=0.0)
    for draw, expected in ((0.0, FAIL), (chances[FAIL] + chances[MIXED] / 2, MIXED), (0.999, SUCCESS)):
        engine = ActivityEngine(outcome_rng=_Draws(draw))
        assert engine.roll_outcome(reading, energy=0.5, valence=0.0)[0] == expected, draw


def test_what_went_wrong_is_told_in_its_setting_s_words_with_no_thought_and_nothing_to_share():
    reading = dataclasses.replace(_activity("reading"), share_worthy=True)
    for outcome in (MIXED, FAIL):
        log = ActivityEngine(rng=random.Random(3), outcome_rng=random.Random(4)).execute_activity(
            reading, "home", Weather.RAINY, 0.8, outcome=outcome)
        assert log.outcome == outcome
        assert log.narrative in reading.outcomes[outcome]
        assert log.thoughts_generated == [] and log.share_worthy is False


def test_a_success_is_told_as_it_always_was():
    reading = _activity("reading")
    before = ActivityEngine(rng=random.Random(3)).execute_activity(reading, "home", Weather.SUNNY, 0.8)
    now = ActivityEngine(rng=random.Random(3)).execute_activity(reading, "home", Weather.SUNNY, 0.8, outcome=SUCCESS)
    assert before.outcome == now.outcome == SUCCESS
    assert (before.narrative, before.thoughts_generated, before.share_worthy) == (
        now.narrative, now.thoughts_generated, now.share_worthy)
    assert any(now.narrative.startswith(t) for t in reading.narrative_templates)


def test_an_outcome_never_moves_the_engine_s_own_draws():
    """Its narrative, weather, thoughts and share draws are taken whatever
    the outcome, so how one activity went never moves the next one's."""
    reading = _activity("reading")
    states = {}
    for outcome in OUTCOMES:
        own = random.Random(3)
        ActivityEngine(rng=own, outcome_rng=random.Random(4)).execute_activity(
            reading, "home", Weather.SUNNY, 0.8, outcome=outcome)
        states[outcome] = own.getstate()
    assert states[SUCCESS] == states[MIXED] == states[FAIL]


def test_an_activity_without_outcome_texts_is_told_in_the_library_s_neutral_words():
    bare = dataclasses.replace(_activity("reading"), outcomes={})
    for outcome in (MIXED, FAIL):
        log = ActivityEngine(outcome_rng=random.Random(1)).execute_activity(
            bare, "home", Weather.SUNNY, 0.8, outcome=outcome)
        assert log.narrative in NEUTRAL_OUTCOME_NARRATIVES[outcome]


def test_an_outcome_the_engine_does_not_know_is_refused():
    with pytest.raises(ValueError):
        ActivityEngine().execute_activity(_activity("reading"), "home", Weather.SUNNY, 0.8, outcome="triumph")


def test_the_recent_activities_export_says_how_each_went():
    engine = ActivityEngine(outcome_rng=random.Random(1))
    logs = [engine.execute_activity(_activity("reading"), "home", Weather.SUNNY, 0.8, outcome=o) for o in OUTCOMES]
    exported = engine.export_recent_state(logs)["today_activities"]
    assert [entry["outcome"] for entry in exported] == list(OUTCOMES)


# ======================================================================
# 5. Mood takes an appraised feeling as she felt it
# ======================================================================

def test_an_appraised_feeling_moves_her_mood_by_her_volatility_once():
    """An appraisal already scaled a feeling by her volatility
    (PersonaParameters.affect_reactivity); AffectSystem, told so, does not
    scale its pull by the same multiplier again."""
    params = PersonaParameters(volatility=0.9)
    felt = 0.4 * params.affect_reactivity
    looked_up, appraised, twice = (AffectSystem(params=params) for _ in range(3))
    looked_up.on_emotion_event("frustrated", 0.4)
    appraised.on_emotion_event("frustrated", felt, reactivity_applied=True)
    twice.on_emotion_event("frustrated", felt)
    assert appraised.mood.valence == pytest.approx(looked_up.mood.valence)
    assert appraised.mood.arousal == pytest.approx(looked_up.mood.arousal)
    assert twice.mood.valence < appraised.mood.valence


def test_a_feeling_told_nothing_moves_her_mood_as_it_always_did():
    params = PersonaParameters(volatility=0.1)
    before, now = AffectSystem(params=params), AffectSystem(params=params)
    before.on_emotion_event("content", 0.3)
    now.on_emotion_event("content", 0.3, reactivity_applied=False)
    assert (now.mood.valence, now.mood.arousal) == (before.mood.valence, before.mood.arousal)


# ======================================================================
# 6. Her life: how it went reaches her log, her mood, her memory
# ======================================================================

#: A Tuesday afternoon: every default schedule is awake.
TUESDAY_1400 = datetime(2026, 10, 6, 14, 0)


class ScriptedClock:
    """A clock that moves only when told to."""

    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant


@pytest.fixture
def persona_clock():
    """Her local clock (the ``persona_now`` hook) on a scripted instant; the
    previous provider is put back afterwards."""
    saved = hooks.provider_for("persona_now")
    clock = ScriptedClock(TUESDAY_1400)
    hooks.configure(persona_now=lambda timezone=None: clock.instant)
    yield clock
    hooks.configure(persona_now=saved)


def _service(tmp_path, clock, name: str = "nora", seed: int = 11, **kwargs) -> LifeService:
    """A persona of a world on ``clock``, her draws seeded; no NPC event,
    chaos, micro-event or intimate interlude on her activity ticks."""
    pathlib.Path(tmp_path).mkdir(parents=True, exist_ok=True)
    svc = LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=name,
                      world_environment=WorldEnvironment(now=clock, seed=seed), rng=random.Random(seed), **kwargs)
    svc._desire_system.should_do_intimate_activity = lambda *args, **kw: False
    svc._social.tick = lambda *args, **kw: None
    svc._chaos.roll = lambda *args, **kw: None
    svc._micro_event_chance = 0.0
    return svc


def _force(svc: LifeService, outcome: str) -> list:
    """Her rolls land on ``outcome`` (the draw and its chances as they were);
    returns the keyword arguments of every roll, in order."""
    engine = svc._activity_engine
    real = engine.roll_outcome
    rolls = []

    def forced(activity, **kwargs):
        rolls.append(dict(kwargs, activity=activity.name))
        _, chances = real(activity, **kwargs)
        return outcome, chances

    engine.roll_outcome = forced
    return rolls


def _do(svc: LifeService, name: str):
    """She does ``name`` now, through her whole activity pipeline."""
    return svc._perform_activity(svc._activity_engine.get_activity(name), None)


def test_a_failure_brings_her_mood_down_where_a_success_lifts_it(tmp_path, persona_clock):
    """The brief: negative outcomes produce negative emotions that reach
    mood. Two of her, the same seed, the same activity; only the outcome
    differs."""
    failed = _service(tmp_path / "a", persona_clock)
    went_well = _service(tmp_path / "b", persona_clock)
    before = failed._affect.mood.valence
    assert went_well._affect.mood.valence == before
    _force(failed, FAIL)
    _force(went_well, SUCCESS)
    _do(failed, "reading")
    _do(went_well, "reading")
    assert failed._affect.mood.valence < before < went_well._affect.mood.valence


def test_how_it_went_is_in_her_log_on_disk_and_after_a_reload(tmp_path, persona_clock):
    svc = _service(tmp_path, persona_clock)
    _force(svc, MIXED)
    log = _do(svc, "reading")
    reading = svc._activity_engine.get_activity("reading")
    rendered = {svc._render_text(text) for text in reading.outcomes[MIXED]}
    assert log.outcome == MIXED and log.narrative in rendered
    with contextlib.closing(sqlite3.connect(svc._db_path)) as conn:
        assert conn.execute("SELECT outcome FROM activity_logs WHERE id = ?", (log.id,)).fetchone() == (MIXED,)
    again = _service(tmp_path, persona_clock)
    again._load_state()
    assert again.get_recent_activities(1)[0].outcome == MIXED


def test_an_activity_log_saved_before_outcomes_existed_reads_as_a_success(tmp_path, persona_clock):
    """A database from before Task 14 gains the column; its rows went well,
    as every activity did then."""
    path = tmp_path / "old.db"
    with contextlib.closing(sqlite3.connect(path)) as conn:
        conn.execute("""CREATE TABLE activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, activity_name TEXT NOT NULL, category TEXT NOT NULL,
            started_at TEXT NOT NULL, ended_at TEXT, location TEXT, weather TEXT, narrative TEXT,
            thoughts_generated TEXT, emotions_triggered TEXT, energy_before REAL, energy_after REAL,
            share_worthy INTEGER DEFAULT 0, shared_with_user INTEGER DEFAULT 0)""")
        # A row as _record_activity wrote one before Task 14.
        conn.execute("INSERT INTO activity_logs (activity_name, category, started_at, ended_at, location, "
                     "weather, narrative, thoughts_generated, emotions_triggered, energy_before, energy_after, "
                     "share_worthy, shared_with_user) VALUES ('reading', 'mental', '2026-10-06T13:00:00', "
                     "'2026-10-06T13:00:00', 'home', 'sunny', 'Read a few chapters', '', "
                     "'{\"content\": 0.15}', 0.8, 0.7, 0, 0)")
        conn.commit()
    svc = LifeService(db_path=str(path), persona_id="old",
                      world_environment=WorldEnvironment(now=persona_clock, seed=1), rng=random.Random(1))
    svc._load_state()
    (log,) = svc.get_recent_activities(5)
    assert (log.activity_name, log.outcome) == ("reading", SUCCESS)


def test_her_skill_energy_and_mood_are_what_the_roll_reads(tmp_path, persona_clock):
    svc = _service(tmp_path, persona_clock)
    svc._skills["knowledge"] = SkillProgress(skill_name="knowledge", level=0.6)
    svc._affect._set_mood(-0.4, 0.3)
    energy, valence = svc._energy.effective_level, svc._affect.mood.valence
    rolls = _force(svc, SUCCESS)
    _do(svc, "reading")              # trains "knowledge" (her setting's skill_mappings)
    _do(svc, "listening to music")   # trains none
    assert rolls[0] == {"activity": "reading", "energy": energy, "valence": valence, "skill": 0.6}
    assert rolls[1]["skill"] is None


def test_a_skill_she_has_never_practised_is_one_she_is_new_to(tmp_path, persona_clock):
    svc = _service(tmp_path, persona_clock)
    rolls = _force(svc, SUCCESS)
    _do(svc, "writing poetry")
    assert rolls[0]["skill"] == 0.0


def test_her_outcome_roll_draws_on_a_stream_of_its_own(tmp_path, persona_clock):
    """Task 26's pattern: the roll is on her "outcome" stream, never the
    service's or the activity engine's (tests/test_rng_streams.py proves
    the stream independent of every other)."""
    svc = _service(tmp_path, persona_clock)
    assert svc._activity_engine._outcome_rng is svc._outcome_rng
    assert svc._outcome_rng is not svc._service_rng and svc._outcome_rng is not svc._activity_rng
    service_state = svc._service_rng.getstate()
    activity_state = svc._activity_rng.getstate()
    outcome_state = svc._outcome_rng.getstate()
    svc._activity_engine.roll_outcome(svc._activity_engine.get_activity("reading"), energy=0.5, valence=0.0)
    assert svc._service_rng.getstate() == service_state
    assert svc._activity_rng.getstate() == activity_state
    assert svc._outcome_rng.getstate() != outcome_state


class _HostEngine:
    """A host's EmotionEngine: records what it is asked to feel."""

    def __init__(self):
        self.felt = []

    def add_emotion(self, emotion, intensity):
        self.felt.append((emotion, intensity))


def test_what_she_feels_about_it_is_her_appraisal_of_it(tmp_path, persona_clock):
    """Failing at something one of her goals is pursued through: her
    appraisal's feelings -- frustration, disappointment -- in her log, and
    the host's engine feels them too."""
    host = _HostEngine()
    svc = _service(tmp_path, persona_clock, emotion_engine=host)
    goal = Goal(title="Read more", related_activities=["reading"], motivation_level=1.0,
                timeframe=GoalTimeframe.WEEKLY)
    svc._goal_engine._active_goals = [goal]
    _force(svc, FAIL)
    log = _do(svc, "reading")
    assert {"frustrated", "disappointed"} <= set(log.emotions_triggered)
    assert all(valence_arousal(name)[0] < 0 for name in log.emotions_triggered)
    assert set(log.emotions_triggered.items()) <= set(host.felt)


def test_her_appraised_feelings_reach_mood_with_her_reactivity_applied_once(tmp_path, persona_clock):
    svc = _service(tmp_path, persona_clock)
    calls = []
    real = svc._affect.on_emotion_event

    def spy(emotion, intensity, **kwargs):
        calls.append((emotion, kwargs))
        return real(emotion, intensity, **kwargs)

    svc._affect.on_emotion_event = spy
    _force(svc, FAIL)
    log = _do(svc, "reading")
    appraised = [kwargs for emotion, kwargs in calls if emotion in log.emotions_triggered]
    assert appraised and all(kwargs == {"reactivity_applied": True} for kwargs in appraised)


def test_her_memory_of_a_failure_keeps_what_she_felt_not_her_mood(tmp_path, persona_clock):
    svc = _service(tmp_path, persona_clock)
    svc._affect._set_mood(0.6, 0.4)  # a good mood, and it must not colour the memory
    _force(svc, FAIL)
    log = _do(svc, "reading")
    (episode,) = [e for e in svc._memory.episodes if "activity" in e.tags]
    assert episode.what == "reading" and FAIL in episode.tags
    assert episode.emotion in log.emotions_triggered
    assert valence_arousal(episode.emotion)[0] < 0
    assert episode.valence < 0
    assert episode.valence == pytest.approx(appraised_valence(
        [EmotionSpike(0.0, name, x, "") for name, x in log.emotions_triggered.items()]))


def test_her_memory_of_a_success_is_tagged_with_no_outcome(tmp_path, persona_clock):
    svc = _service(tmp_path, persona_clock)
    _force(svc, SUCCESS)
    _do(svc, "reading")
    (episode,) = [e for e in svc._memory.episodes if "activity" in e.tags]
    assert not {MIXED, FAIL, SUCCESS} & set(episode.tags)
    assert episode.valence > 0


def test_a_failure_is_no_step_toward_her_goals_and_fulfils_no_want(tmp_path, persona_clock):
    for outcome, moves in ((FAIL, False), (MIXED, True), (SUCCESS, True)):
        svc = _service(tmp_path / outcome, persona_clock)
        goal = Goal(title="Read more", related_activities=["reading"], motivation_level=1.0,
                    timeframe=GoalTimeframe.WEEKLY)
        svc._goal_engine._active_goals = [goal]
        want = ShortTermDesire(title="Read tonight", related_activities=["reading"], urgency=0.8)
        svc._daily_planner._desires = [want]
        _force(svc, outcome)
        _do(svc, "reading")
        assert (goal.progress > 0) is moves, outcome
        assert want.fulfilled is moves, outcome


def test_what_went_wrong_makes_nothing_to_share_and_no_life_event(tmp_path, persona_clock):
    for outcome in (MIXED, FAIL):
        svc = _service(tmp_path / outcome, persona_clock)
        events, artifacts = [], []
        real_event, real_artifact = svc._life_events.on_activity, svc._behavior.on_creative_activity
        svc._life_events.on_activity = lambda **kw: events.append(kw) or real_event(**kw)
        svc._behavior.on_creative_activity = lambda *a, **kw: artifacts.append(a) or real_artifact(*a, **kw)
        _force(svc, outcome)
        log = _do(svc, "writing poetry")
        assert events == [], outcome
        assert log.share_worthy is False, outcome
        assert not [s for s in svc._shareable_queue if s.activity_log_id == log.id], outcome
        # Something only half done can still leave a poem behind; a failure makes nothing.
        assert (artifacts == []) is (outcome == FAIL), outcome


def test_a_neutral_persona_s_success_feels_as_her_setting_wrote_it_at_most_plus_relief(tmp_path, persona_clock):
    """Nothing at stake but the activity itself -- no goal lists it, no need
    it meets is felt, no value of hers aligns with it -- a success is its own
    emotions (and a little relief for the chance it had of going wrong)."""
    svc = _service(tmp_path, persona_clock)
    svc._goal_engine._active_goals = []
    svc._choice_state = lambda: ChoiceState(needs={}, valence=0.0, arousal=0.3, energy=0.9)
    _force(svc, SUCCESS)
    log = _do(svc, "puzzles and games")
    own = svc._activity_engine.get_activity("puzzles and games").emotion_effects
    assert set(log.emotions_triggered) <= set(own) | {RELIEF_EMOTION}
    for name, intensity in own.items():
        assert log.emotions_triggered[name] == pytest.approx(intensity, rel=0.25)


LINA_NIGHT = {"bedtime_hour": 4, "bedtime_minute": 0, "wake_hour": 12, "wake_minute": 0}
ROBERTA_NIGHT = {"bedtime_hour": 23, "bedtime_minute": 0, "wake_hour": 7, "wake_minute": 0}


class _Asks:
    """A household stream whose roll always passes and which takes the first
    of every choice."""

    def random(self) -> float:
        return 0.0

    def choice(self, seq):
        return list(seq)[0]


class _NoRoll:
    """An outcome stream that is never rolled: only a narrative is drawn."""

    def random(self):
        raise AssertionError("the one who joins takes the outcome she joins; she rolls none")

    def choice(self, seq):
        return list(seq)[0]


def test_a_housemate_who_joins_in_takes_how_it_went_and_feels_it_her_own_way(tmp_path, persona_clock):
    """One event, one outcome (Task 11's joint activities, written into both
    lives): she joins it as it went -- and appraises it herself."""
    world, home = WorldEnvironment(now=persona_clock, seed=3), Household()

    def member(pid, name, other, night, seed):
        definition = PersonalityDefinition(id=pid, name=name, appearance_details={"gender": "female"},
                                           household=[other.lower()])
        svc = LifeService(db_path=str(tmp_path / f"{pid}.db"), persona_id=pid, world_environment=world,
                          rng=random.Random(seed), definition=definition, sleep_schedule=night,
                          social_circle=[{"name": other, "kind": "co_resident"}], household=home)
        svc._desire_system.should_do_intimate_activity = lambda *args, **kw: False
        svc._social.tick = lambda *args, **kw: None
        svc._chaos.roll = lambda *args, **kw: None
        svc._micro_event_chance = 0.0
        return svc

    lina = member("lina", "Lina", "Roberta", LINA_NIGHT, 7)
    roberta = member("roberta", "Roberta", "Lina", ROBERTA_NIGHT, 8)
    lina._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=14, activity_name="cooking a meal", reason="routine", location="home")])
    roberta._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=14, activity_name="reading", reason="routine", location="home")])
    lina._household_rng = _Asks()
    _force(lina, FAIL)
    roberta._activity_engine._outcome_rng = _NoRoll()
    lina._on_activity_tick()
    hers, theirs = lina.get_recent_activities(1)[0], roberta.get_recent_activities(1)[0]
    assert hers.activity_name == theirs.activity_name == "cooking a meal"
    assert hers.outcome == theirs.outcome == FAIL
    assert all(valence_arousal(name)[0] < 0 for name in theirs.emotions_triggered)


def test_each_housemate_appraises_a_shared_failure_by_her_own_chance_of_it(tmp_path, persona_clock):
    """Fix round 1, B1: one outcome, two sides -- each one's expectedness is
    her own. The same failed meal, at the same energy and mood, leaves the
    one who has never cooked more resigned (she half expected it) and the
    practised cook more frustrated (she did not)."""
    world, home = WorldEnvironment(now=persona_clock, seed=3), Household()

    def member(pid, name, other, night, seed):
        definition = PersonalityDefinition(id=pid, name=name, appearance_details={"gender": "female"},
                                           household=[other.lower()])
        svc = LifeService(db_path=str(tmp_path / f"{pid}.db"), persona_id=pid, world_environment=world,
                          rng=random.Random(seed), definition=definition, sleep_schedule=night,
                          social_circle=[{"name": other, "kind": "co_resident"}], household=home)
        svc._desire_system.should_do_intimate_activity = lambda *args, **kw: False
        svc._social.tick = lambda *args, **kw: None
        svc._chaos.roll = lambda *args, **kw: None
        svc._micro_event_chance = 0.0
        # The same energy and mood for both: only their skill differs.
        svc._energy._state.level = 0.8
        svc._energy._state.caffeine_boost = svc._energy._state.inspiration_boost = 0.0
        svc._energy._state.social_boost = 0.0
        svc._affect._set_mood(0.1, 0.3)
        return svc

    lina = member("lina", "Lina", "Roberta", LINA_NIGHT, 7)
    roberta = member("roberta", "Roberta", "Lina", ROBERTA_NIGHT, 8)
    lina._skills["cooking"] = SkillProgress(skill_name="cooking", level=1.0)
    roberta._skills.pop("cooking", None)  # never practised
    lina._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=14, activity_name="cooking a meal", reason="routine", location="home")])
    roberta._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=14, activity_name="reading", reason="routine", location="home")])
    lina._household_rng = _Asks()
    _force(lina, FAIL)
    lina._on_activity_tick()
    cook, novice = lina.get_recent_activities(1)[0], roberta.get_recent_activities(1)[0]
    assert cook.activity_name == novice.activity_name == "cooking a meal"
    assert cook.outcome == novice.outcome == FAIL
    split = {name: (log.emotions_triggered[FAILED_OWN_EMOTION], log.emotions_triggered[RESIGNATION_EMOTION])
             for name, log in (("cook", cook), ("novice", novice))}
    assert split["novice"][1] > split["cook"][1], split
    assert split["novice"][0] < split["cook"][0], split


def test_reading_that_went_wrong_turns_no_page(tmp_path, persona_clock):
    for outcome, turns in ((FAIL, False), (MIXED, True), (SUCCESS, True)):
        svc = _service(tmp_path / outcome, persona_clock)
        svc._media.current_book, svc._media.book_progress = "Dune", 0.2
        _force(svc, outcome)
        _do(svc, "reading")
        assert (svc._media.book_progress > 0.2) is turns, outcome


def test_a_meal_that_went_wrong_still_feeds_her(tmp_path, persona_clock):
    """What went wrong was the cooking, not the eating: every contemporary
    meal's failure line has her eat something, and the meal tag feeds her."""
    svc = _service(tmp_path, persona_clock)
    svc._sustenance.state.hunger = 0.8
    _force(svc, FAIL)
    log = _do(svc, "cooking a meal")
    assert log.outcome == FAIL
    assert svc._sustenance.hunger < 0.8


def test_an_activity_its_setting_has_no_words_for_is_told_by_name(tmp_path, persona_clock):
    """The library's neutral words name the activity as she would: "thinking
    about user" as her user's name."""
    svc = _service(tmp_path, persona_clock, user_info={"name": "Robin"})
    engine = svc._activity_engine
    for name in ("reading", "thinking about user"):
        engine._activities[name] = dataclasses.replace(engine.get_activity(name), outcomes={})
    _force(svc, FAIL)
    assert _do(svc, "reading").narrative.startswith("Reading didn't work out")
    assert _do(svc, "thinking about user").narrative.startswith("Thinking about Robin didn't work out")


# ======================================================================
# 7. The optional LLM appraisal (appraisal_llm)
# ======================================================================

class _StubLLM:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return self.reply


@pytest.fixture
def llm_hook():
    """Set the ``get_llm_service`` hook for one test (``configure(stub)``,
    ``configure(None)`` to remove it); every hook is put back afterwards."""
    saved = {name: hooks.provider_for(name) for name in hooks.HOOK_NAMES}

    def configure(provider):
        hooks.reset()
        hooks.configure(**{name: p for name, p in saved.items() if p is not None and name != "get_llm_service"})
        if provider is not None:
            hooks.configure(get_llm_service=provider)

    yield configure
    hooks.reset()
    hooks.configure(**{name: p for name, p in saved.items() if p is not None})


def _deterministic(tmp_path, persona_clock, outcome=FAIL):
    """What the deterministic appraisal gives for this scenario."""
    svc = _service(tmp_path / "deterministic", persona_clock)
    _force(svc, outcome)
    return _do(svc, "reading").emotions_triggered


def test_the_llm_appraisal_is_off_by_default_and_never_asks(tmp_path, persona_clock, llm_hook):
    asked = []
    llm_hook(lambda: (asked.append(True), _StubLLM('{"joyful": 0.9}'))[1])
    svc = _service(tmp_path, persona_clock)
    _force(svc, FAIL)
    log = _do(svc, "reading")
    assert asked == []
    assert log.emotions_triggered == _deterministic(tmp_path, persona_clock)


def test_the_llm_appraisal_when_asked_for_names_what_she_feels_validated(tmp_path, persona_clock, llm_hook):
    llm = _StubLLM('Sure. {"frustrated": 0.6, "Tired": 0.2, "wibble": 0.9, "sad": 1.8}')
    llm_hook(lambda: llm)
    svc = _service(tmp_path, persona_clock, appraisal_llm=True)
    _force(svc, FAIL)
    log = _do(svc, "reading")
    assert log.emotions_triggered == {"sad": 1.0, "frustrated": 0.6, "tired": 0.2}
    assert len(llm.prompts) == 1 and "reading" in llm.prompts[0] and "went wrong" in llm.prompts[0]


def test_the_llm_appraisal_is_scaled_by_her_volatility(tmp_path, persona_clock, llm_hook):
    llm_hook(lambda: _StubLLM('{"frustrated": 0.4}'))
    volatile = PersonalityDefinition(traits={"volatility": 0.9})
    svc = _service(tmp_path, persona_clock, appraisal_llm=True, definition=volatile)
    _force(svc, FAIL)
    assert _do(svc, "reading").emotions_triggered == {"frustrated": pytest.approx(0.6)}


@pytest.mark.parametrize("reply", ['{"wibble": 0.5}', "no idea", '{"frustrated": "very"}', ""])
def test_an_unusable_llm_reply_leaves_the_deterministic_appraisal_with_a_warning_not_an_error(
    tmp_path, persona_clock, llm_hook, caplog, reply,
):
    llm_hook(lambda: _StubLLM(reply))
    svc = _service(tmp_path, persona_clock, appraisal_llm=True)
    _force(svc, FAIL)
    with caplog.at_level(logging.DEBUG, logger="aura_life"):
        log = _do(svc, "reading")
    assert log.emotions_triggered == _deterministic(tmp_path, persona_clock)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert [r for r in caplog.records if r.levelno == logging.WARNING and "appraisal" in r.getMessage()]


def test_an_llm_that_calls_a_failure_joy_leaves_the_deterministic_appraisal_with_a_warning(
    tmp_path, persona_clock, llm_hook, caplog,
):
    """Fix round 1, C1: a failure is never logged, felt and remembered as
    joy because a model said so."""
    llm_hook(lambda: _StubLLM('{"joyful": 0.9}'))
    svc = _service(tmp_path, persona_clock, appraisal_llm=True)
    _force(svc, FAIL)
    with caplog.at_level(logging.DEBUG, logger="aura_life"):
        log = _do(svc, "reading")
    assert log.emotions_triggered == _deterministic(tmp_path, persona_clock)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert [r for r in caplog.records if r.levelno == logging.WARNING and "appraisal" in r.getMessage()]


def test_an_llm_appraisal_keeps_only_the_feelings_that_fit_how_it_went(tmp_path, persona_clock, llm_hook):
    llm_hook(lambda: _StubLLM('{"frustrated": 0.6, "joyful": 0.9}'))
    failed = _service(tmp_path / "fail", persona_clock, appraisal_llm=True)
    _force(failed, FAIL)
    assert _do(failed, "reading").emotions_triggered == {"frustrated": 0.6}
    mixed = _service(tmp_path / "mixed", persona_clock, appraisal_llm=True)
    _force(mixed, MIXED)
    assert _do(mixed, "reading").emotions_triggered == {"joyful": 0.9, "frustrated": 0.6}


def test_a_raising_or_missing_llm_hook_leaves_the_deterministic_appraisal_with_no_error(
    tmp_path, persona_clock, llm_hook, caplog,
):
    def _raise():
        raise RuntimeError("the model is down")

    class _Broken:
        def generate(self, prompt):
            raise TimeoutError("no answer")

    for label, provider in (("raising hook", _raise), ("raising generate", lambda: _Broken()), ("no hook", None)):
        llm_hook(provider)
        svc = _service(tmp_path / label, persona_clock, appraisal_llm=True)
        _force(svc, FAIL)
        with caplog.at_level(logging.DEBUG, logger="aura_life"):
            log = _do(svc, "reading")
        assert log.emotions_triggered == _deterministic(tmp_path / label, persona_clock), label
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR], label


# ======================================================================
# 8. Three simulated days (acceptance)
# ======================================================================
# The cast of tests/test_mood_model.py's mood_trace -- a no-profile control
# and Lina's and Roberta's emotional baselines (their profiles' "Emotional
# Baseline" sections, copied so this library's tests do not depend on
# aura-personality) -- three days at the scheduler's own cadence (ruling
# T4-R3): the run rulings P1 and T4-R2 moved the "no mood label on more than
# 70% of her waking ticks" threshold to this task.

#: The mood_trace's seed. Over seeds 1-10 (the Task 14 report, fix round 1,
#: with the day's quality, ruling T14-R1): at least 10% of outcomes not plain
#: success on 10/10 runs (14.5% to 23.5%); a negative-valence period on 10/10
#: for every persona; no mood label on more than 70% of a persona's waking
#: ticks on 9/10 for the control and Lina (seed 7 is a run of bad days: the
#: lonely control reads "low" on 78%) and 10/10 for Roberta.
SIM_SEED = 9
SIM_DAYS = 3
LINA_BASELINE = {"calm": 0.6, "guarded": 0.7, "curious": 0.4, "grief": 0.3, "resolve": 0.6}
ROBERTA_BASELINE = {"joyful": 0.5, "affectionate": 0.6, "restless": 0.5, "curious": 0.4, "grief": 0.3}
SIM_IDS = ("control", "lina", "roberta")
#: A negative-valence mood period is at least this long, awake: an hour --
#: three of her activity ticks (LifeScheduler's 20 minutes), so one tick's
#: dip is not a period (chosen, the Task 14 report lists it).
NEGATIVE_PERIOD_MINUTES = 60
#: The humanness spec's section 6 thresholds (ruling R12: proposals encoded
#: as tests).
MIN_NOT_PLAIN_SUCCESS = 0.10
MAX_WAKING_LABEL_SHARE = 0.70


@pytest.fixture(scope="module")
def outcome_trace(tmp_path_factory):
    from sim_helpers import PRODUCTION, SimPersona, run_days

    personas = [
        SimPersona("control"),
        SimPersona("lina", service_kwargs={
            "definition": PersonalityDefinition(emotional_baseline=dict(LINA_BASELINE))}),
        SimPersona("roberta", service_kwargs={
            "definition": PersonalityDefinition(emotional_baseline=dict(ROBERTA_BASELINE))}),
    ]
    return run_days(personas, days=SIM_DAYS, seed=SIM_SEED, cadence=PRODUCTION,
                    data_dir=tmp_path_factory.mktemp("appraisal"))


def _rolled(trace, pid) -> list:
    """The outcomes of her activities that had one to roll: every activity
    she did but her sleep and her intimate activities (logged as a success,
    with no roll)."""
    svc = trace.services[pid]
    unrolled = set(svc._setting.names_tagged("sleep")) | {a.name for a in svc._setting.intimate_catalogue()}
    return [r.outcome for r in trace.records[pid] if r.activity and r.activity not in unrolled]


def test_the_three_day_run_is_clean(outcome_trace):
    assert outcome_trace.errors == []
    for pid in SIM_IDS:
        assert set(_rolled(outcome_trace, pid)) <= set(OUTCOMES), pid


def test_at_least_one_activity_in_ten_does_not_simply_go_well(outcome_trace):
    """The spec's section 6 row: activity outcomes that are not plain
    success, at least 10% of the run's -- and both ways of not going well
    happen, to every one of them."""
    pooled = [outcome for pid in SIM_IDS for outcome in _rolled(outcome_trace, pid)]
    share = sum(outcome != SUCCESS for outcome in pooled) / len(pooled)
    print(f"{len(pooled)} activities, {share:.1%} not plain success")
    assert share >= MIN_NOT_PLAIN_SUCCESS, share
    for pid in SIM_IDS:
        assert {MIXED, FAIL} <= set(_rolled(outcome_trace, pid)), pid


def _negative_periods(records, step_minutes: int) -> list:
    """Each unbroken stretch of waking steps whose mood valence is below 0,
    at least NEGATIVE_PERIOD_MINUTES long, as its length in steps. Sleep
    breaks a stretch."""
    need = NEGATIVE_PERIOD_MINUTES // step_minutes
    periods, run = [], 0
    for record in records:
        if not record.asleep and record.valence < 0:
            run += 1
            continue
        if run >= need:
            periods.append(run)
        run = 0
    if run >= need:
        periods.append(run)
    return periods


@pytest.mark.parametrize("pid", SIM_IDS)
def test_each_persona_has_a_negative_valence_mood_period(outcome_trace, pid):
    periods = _negative_periods(outcome_trace.records[pid], outcome_trace.step_minutes)
    print(f"{pid}: {len(periods)} negative-valence periods of an hour or more awake")
    assert periods, pid


def test_a_negative_period_needs_an_hour_awake_below_zero():
    """The measure above is not vacuous: shorter dips, and nights, are not
    periods."""
    from sim_helpers import StepRecord

    def steps(*valences, asleep=False):
        return [StepRecord(t=datetime(2026, 10, 5), asleep=asleep, activity=None, activity_energy_before=None,
                           energy=0.5, forced_rest=None, valence=v) for v in valences]

    assert _negative_periods(steps(*[-0.1] * 12), 5) == [12]
    assert _negative_periods(steps(*[-0.1] * 11, 0.0), 5) == []
    assert _negative_periods(steps(*[-0.1] * 12, asleep=True), 5) == []
    assert _negative_periods(steps(*[-0.1] * 6) + steps(0.1) + steps(*[-0.1] * 6), 5) == []


def _largest_waking_label(trace, pid):
    """(label, its share) of the mood label on most of her waking ticks."""
    waking = [r.mood for r in trace.records[pid] if not r.asleep]
    label, count = Counter(waking).most_common(1)[0]
    return label, count / len(waking)


def test_no_mood_label_on_more_than_70_percent_of_any_persona_s_waking_ticks(outcome_trace):
    """Rulings P1 and T4-R2: no single mood label on more than 70% of any
    persona's waking ticks (her mood asleep never reaches a conversation).
    Met with the day's quality (ruling T14-R1, section 9): before it, Lina's
    baseline read "neutral" on 74-88% of waking ticks and Roberta's on
    60-86% over seeds 1-10."""
    shares = {pid: _largest_waking_label(outcome_trace, pid) for pid in SIM_IDS}
    print("largest waking label: " + ", ".join(f"{pid} {label} {share:.0%}" for pid, (label, share) in shares.items()))
    over = {pid: (label, round(share, 3)) for pid, (label, share) in shares.items() if share > MAX_WAKING_LABEL_SHARE}
    assert not over, over


def test_the_waking_label_measure_is_the_share_of_her_most_frequent_label():
    """The threshold above measures what it says: the largest single
    label's share of her waking ticks only."""
    from types import SimpleNamespace

    from sim_helpers import StepRecord

    def step(mood, asleep=False):
        return StepRecord(t=datetime(2026, 10, 5), asleep=asleep, activity=None, activity_energy_before=None,
                          energy=0.5, forced_rest=None, mood=mood)

    trace = SimpleNamespace(records={"x": [step("neutral")] * 7 + [step("low")] * 3 + [step("calm", asleep=True)] * 9})
    assert _largest_waking_label(trace, "x") == ("neutral", pytest.approx(0.7))


# ======================================================================
# 9. The day's quality (ruling T14-R1)
# ======================================================================
# A valence offset on her mood's target, drawn once per persona-local date at
# her first waking tick outside her sleep window, on a "day_quality" stream of
# its own, scaled by her volatility and shifted by last night's sleep: some
# days are better than others, and the difference lasts the day.

TUESDAY = date(2026, 10, 6)


class _DayDraws:
    """A "day_quality" stream whose draws are the z-scores given, in turn
    (``gauss(mu, sigma)`` is ``mu + sigma * z``); counts them, and fails a
    draw it was given nothing for."""

    def __init__(self, *z):
        self.z = list(z)
        self.draws = 0

    def gauss(self, mu, sigma):
        self.draws += 1
        if not self.z:
            raise AssertionError("an unexpected draw of the day's quality")
        return mu + sigma * self.z.pop(0)


def _settle(affect: AffectSystem, hours: float) -> None:
    """Tick ``affect`` for ``hours`` of world time with no need pulling her
    mood (loneliness and stress held at 0) and no weather or season push."""
    for _ in range(int(hours * 4)):
        affect.loneliness.level = 0.0
        affect.stress.level = 0.0
        affect.tick(body_state={"hunger": 0.0, "hours_awake": 8.0, "sleep_pressure": 0.0, "illness": 0.0,
                                "asleep": False},
                    social_state={"recent_events": []}, weather="snowy", season="autumn", hours=0.25)


def test_a_day_s_quality_is_one_draw_scaled_by_her_volatility():
    offsets = {}
    for volatility in (0.1, 0.5, 0.9):
        affect = AffectSystem(params=PersonaParameters(volatility=volatility))
        stream = _DayDraws(1.0)
        offsets[volatility] = affect.new_day(TUESDAY, stream, sleep_quality=SLEEP_QUALITY_BASE)
        assert stream.draws == 1
        assert affect.day_quality == (TUESDAY, pytest.approx(offsets[volatility]))
    assert offsets[0.5] == pytest.approx(DAY_QUALITY_SD)
    for volatility in (0.1, 0.9):
        reactivity = PersonaParameters(volatility=volatility).affect_reactivity
        assert offsets[volatility] == pytest.approx(reactivity * offsets[0.5])
    assert offsets[0.9] == pytest.approx(3 * offsets[0.1])


def test_her_mood_settles_at_her_set_point_moved_by_the_day_s_quality_all_day():
    good, bad, plain = AffectSystem(), AffectSystem(), AffectSystem()
    lift = good.new_day(TUESDAY, _DayDraws(1.0), sleep_quality=SLEEP_QUALITY_BASE)
    drop = bad.new_day(TUESDAY, _DayDraws(-1.0), sleep_quality=SLEEP_QUALITY_BASE)
    for affect in (good, bad, plain):
        _settle(affect, hours=36)
    assert plain.mood.valence == pytest.approx(plain.setpoint[0], abs=1e-3)
    assert good.mood.valence == pytest.approx(good.setpoint[0] + lift, abs=1e-3)
    assert bad.mood.valence == pytest.approx(bad.setpoint[0] + drop, abs=1e-3)
    # Valence only: how keyed up she is stays the energy model's.
    assert good.mood.arousal == pytest.approx(plain.mood.arousal) == pytest.approx(bad.mood.arousal)
    # Kept, however many ticks the day has.
    assert good.day_quality == (TUESDAY, pytest.approx(lift))


def test_a_poor_night_lowers_the_next_day_and_a_good_one_lifts_it():
    offsets = {quality: AffectSystem().new_day(TUESDAY, _DayDraws(0.0), sleep_quality=quality)
               for quality in (0.3, SLEEP_QUALITY_BASE, 0.9)}
    assert offsets[SLEEP_QUALITY_BASE] == pytest.approx(0.0)
    assert offsets[0.3] == pytest.approx(DAY_QUALITY_PER_SLEEP_QUALITY * (0.3 - SLEEP_QUALITY_BASE))
    assert offsets[0.3] < 0 < offsets[0.9]
    # No night to go by (an AI, who does not sleep): no shift.
    assert AffectSystem().new_day(TUESDAY, _DayDraws(0.0), sleep_quality=None) == pytest.approx(0.0)
    # A volatile persona feels a poor night more.
    volatile = AffectSystem(params=PersonaParameters(volatility=0.9))
    assert volatile.new_day(TUESDAY, _DayDraws(0.0), sleep_quality=0.3) == pytest.approx(1.5 * offsets[0.3])


def test_the_day_s_quality_survives_a_save_and_a_load_and_an_old_save_has_none():
    affect = AffectSystem()
    offset = affect.new_day(TUESDAY, _DayDraws(-1.0), sleep_quality=SLEEP_QUALITY_BASE)
    assert AffectSystem.from_dict(affect.to_dict()).day_quality == (TUESDAY, pytest.approx(offset))
    old = {key: value for key, value in affect.to_dict().items() if not key.startswith("day_quality")}
    assert AffectSystem.from_dict(old).day_quality == (None, 0.0)
    assert AffectSystem().day_quality == (None, 0.0)


class _Night:
    """Her night, 23:00-07:00 on her local clock, for a service whose sleep
    state a test sets (``asleep``)."""

    def __init__(self, svc: LifeService, clock):
        self.asleep = False
        self._clock = clock
        svc._energy.in_sleep_window = self.in_window
        svc.is_asleep = lambda *args, **kwargs: self.asleep

    def in_window(self, local_now=None) -> bool:
        t = local_now or self._clock()
        return t.hour >= 23 or t.hour < 7


def _day_service(tmp_path, clock, name: str = "dana", **kwargs) -> LifeService:
    pathlib.Path(tmp_path).mkdir(parents=True, exist_ok=True)
    svc = LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=name,
                      world_environment=WorldEnvironment(now=clock, seed=5), rng=random.Random(5), **kwargs)
    svc._desire_system.should_do_intimate_activity = lambda *args, **kw: False
    return svc


def _tick_at(svc: LifeService, clock, when: datetime, night: _Night, asleep: bool = False) -> None:
    clock.instant = when
    night.asleep = asleep
    svc._on_energy_tick()


def test_she_draws_the_day_s_quality_once_a_date_at_her_first_waking_tick_outside_her_night(tmp_path):
    clock = ScriptedClock(datetime(2026, 10, 6, 14, 0))
    svc = _day_service(tmp_path, clock)
    night = _Night(svc, clock)
    stream = svc._day_quality_rng = _DayDraws(1.0, -1.0)
    # A service that starts awake draws at its first waking tick.
    _tick_at(svc, clock, datetime(2026, 10, 6, 14, 5), night)
    assert stream.draws == 1
    day, tuesday = svc._affect.day_quality
    assert day == TUESDAY and tuesday == pytest.approx(DAY_QUALITY_SD)
    for later in (datetime(2026, 10, 6, 18, 0), datetime(2026, 10, 6, 22, 55)):
        _tick_at(svc, clock, later, night)
    # Past midnight she sleeps, then wakes in the night: still her night.
    _tick_at(svc, clock, datetime(2026, 10, 7, 1, 0), night, asleep=True)
    _tick_at(svc, clock, datetime(2026, 10, 7, 3, 30), night)
    assert stream.draws == 1 and svc._affect.day_quality == (TUESDAY, pytest.approx(tuesday))
    # Up for the day: Wednesday's one draw.
    _tick_at(svc, clock, datetime(2026, 10, 7, 7, 30), night)
    assert stream.draws == 2
    assert svc._affect.day_quality == (date(2026, 10, 7), pytest.approx(-DAY_QUALITY_SD))
    # A nap is no new day.
    svc._perform_activity(svc._activity_engine.get_activity("napping"), None)
    _tick_at(svc, clock, datetime(2026, 10, 7, 15, 0), night)
    assert stream.draws == 2


def test_a_night_owl_s_day_starts_when_her_night_ends_not_at_midnight(tmp_path):
    """Her day is the one her last night ended (``EnergySystem.last_wake``),
    not the calendar's: up at half past midnight before a 02:00 bedtime is
    still Tuesday, and Wednesday's one draw waits until she is up after her
    10:00 wake -- after the night that shifts it."""
    clock = ScriptedClock(datetime(2026, 10, 6, 14, 0))
    owl = {"bedtime_hour": 2, "wake_hour": 10, "bedtime_variance": 0, "wake_variance": 0}
    svc = _day_service(tmp_path, clock, sleep_schedule=owl)
    asleep = [False]
    svc.is_asleep = lambda *args, **kwargs: asleep[0]
    stream = svc._day_quality_rng = _DayDraws(1.0, -1.0)
    for when, sleeping in ((datetime(2026, 10, 6, 14, 5), False),
                           (datetime(2026, 10, 7, 0, 30), False),
                           (datetime(2026, 10, 7, 4, 0), True)):
        clock.instant, asleep[0] = when, sleeping
        svc._on_energy_tick()
    assert stream.draws == 1 and svc._affect.day_quality[0] == TUESDAY
    clock.instant, asleep[0] = datetime(2026, 10, 7, 10, 30), False
    svc._on_energy_tick()
    assert stream.draws == 2 and svc._affect.day_quality[0] == date(2026, 10, 7)


def test_the_day_is_shifted_by_the_night_she_slept(tmp_path):
    offsets = {}
    for quality in (0.3, SLEEP_QUALITY_BASE):
        clock = ScriptedClock(datetime(2026, 10, 7, 7, 30))
        svc = _day_service(tmp_path / str(quality), clock)
        night = _Night(svc, clock)
        svc._day_quality_rng = _DayDraws(0.0)
        svc._body._sleep.last_quality = quality
        _tick_at(svc, clock, datetime(2026, 10, 7, 7, 35), night)
        offsets[quality] = svc._affect.day_quality[1]
    assert offsets[SLEEP_QUALITY_BASE] == pytest.approx(0.0)
    assert offsets[0.3] == pytest.approx(DAY_QUALITY_PER_SLEEP_QUALITY * (0.3 - SLEEP_QUALITY_BASE))


def test_the_day_s_quality_has_its_own_stream(tmp_path):
    """Task 26's pattern, label "day_quality" (tests/test_rng_streams.py
    proves it independent of every other stream)."""
    svc = _day_service(tmp_path, ScriptedClock(datetime(2026, 10, 6, 14, 0)))
    expected = LifeService._derive_stream(random.Random(5), "day_quality")
    assert svc._day_quality_rng.getstate() == expected.getstate()


def test_a_reload_mid_day_keeps_the_day_s_quality_and_draws_none(tmp_path):
    clock = ScriptedClock(datetime(2026, 10, 6, 14, 0))
    svc = _day_service(tmp_path, clock)
    svc._load_state()
    night = _Night(svc, clock)
    svc._day_quality_rng = _DayDraws(1.0)
    _tick_at(svc, clock, datetime(2026, 10, 6, 14, 5), night)
    kept = svc._affect.day_quality
    svc._save_state()

    again = _day_service(tmp_path, clock)
    again._load_state()
    assert again._affect.day_quality == (TUESDAY, pytest.approx(kept[1]))
    night_again = _Night(again, clock)
    again._day_quality_rng = _DayDraws()  # any draw fails
    _tick_at(again, clock, datetime(2026, 10, 6, 16, 0), night_again)
    assert again._affect.day_quality == (TUESDAY, pytest.approx(kept[1]))


def test_a_save_from_before_the_day_s_quality_loads_with_none_until_the_next_draw(tmp_path):
    """An affect row saved before ruling T14-R1: no offset, then her next
    waking tick outside her night draws one."""
    clock = ScriptedClock(datetime(2026, 10, 6, 14, 0))
    path = tmp_path / "elder.db"
    with contextlib.closing(sqlite3.connect(path)) as conn:
        conn.execute("""CREATE TABLE life_affect_state (
            id INTEGER PRIMARY KEY CHECK (id = 1), mood_current TEXT DEFAULT 'neutral',
            mood_intensity REAL DEFAULT 0.0, mood_since TEXT, stress_level REAL DEFAULT 0.0,
            stress_sources TEXT DEFAULT '[]', stress_coping_capacity REAL DEFAULT 0.7, stress_last_relief TEXT,
            loneliness_level REAL DEFAULT 0.0, loneliness_desired_baseline REAL DEFAULT 0.5,
            loneliness_last_meaningful TEXT, loneliness_lifetime_peak REAL DEFAULT 0.0,
            regulation_capacity REAL DEFAULT 0.7, regulation_baseline REAL DEFAULT 0.7, regulation_last_event TEXT,
            empathy_susceptibility REAL DEFAULT 0.5, empathy_absorbed_emotion TEXT,
            empathy_absorbed_intensity REAL DEFAULT 0.0, empathy_fatigue REAL DEFAULT 0.0,
            mood_valence REAL, mood_arousal REAL)""")
        conn.execute("INSERT INTO life_affect_state (id, mood_valence, mood_arousal) VALUES (1, 0.1, 0.3)")
        conn.commit()
    svc = LifeService(db_path=str(path), persona_id="elder",
                      world_environment=WorldEnvironment(now=clock, seed=5), rng=random.Random(5))
    svc._load_state()
    assert svc._affect.day_quality == (None, 0.0)
    assert svc._affect.mood.valence == pytest.approx(0.1)
    night = _Night(svc, clock)
    stream = svc._day_quality_rng = _DayDraws(1.0)
    _tick_at(svc, clock, datetime(2026, 10, 6, 14, 5), night)
    assert stream.draws == 1 and svc._affect.day_quality[0] == TUESDAY
