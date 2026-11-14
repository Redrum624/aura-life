"""The memory stream (humanness program Task 12, spec section 4.6).

Measured before this task: there was no episodic memory. ``LifeService``
accepted a ``memory_service`` and only assigned it, nostalgia was ten generic
templates, and nothing the persona lived could be recalled.

Now ``aura_life.memory`` keeps a stream of episodes -- when, where, with whom,
what happened, what she felt, how important it was -- recorded from the
significant events of her life, recalled by recency (0.995 per hour since she
last recalled it), importance, relevance (keyword overlap, or the optional
``embed`` hook) and mood congruence, each on 0..1. Each episode has a
strength S: its retention decays as exp(-t/S), t in days, and recalling it
adds 1 to S. Recall hands back the gist -- one plain sentence -- never a
transcript.

Sections: 1. an episode; 2. the stream; 3. the embed hook; 4. her life,
remembered (``LifeService``); 5. the words an episode is told in, and three
simulated days.
"""

import contextlib
import itertools
import json
import logging
import math
import random
import re
import sqlite3
import statistics
from dataclasses import fields, replace
from datetime import datetime, timedelta

import pytest

from aura_life import hooks
from aura_life.emotion.appraisal import appraised_valence
from aura_life.emotion.text_emotion_analyzer import EmotionSpike
from aura_life.goals.goal_engine import GoalEvent
from aura_life.life_service import LifeService
from aura_life.memory import (
    EMOTION_WEIGHT,
    EPISODE_CAP,
    IMPORTANCE_FLOOR,
    INITIAL_STRENGTH,
    NOVELTY_WEIGHT,
    NOVELTY_WINDOW_DAYS,
    PEOPLE_WEIGHT,
    RECENCY_PER_HOUR,
    Episode,
    MemoryStream,
    importance_of,
)
from aura_life.memory.store import retrieval_score
from aura_life.models import DailyPlan, Goal, GoalTimeframe, PlannedSlot, SocialEvent
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.personas.pronoun_render import SECOND_PERSON, render_second_person
from aura_life.settings import get_setting
from aura_life.social import Household
from aura_life.social.social_system import UNWELCOME_KIND_EMOTIONS
from aura_life.world import WorldEnvironment

from sim_helpers import PRODUCTION, SimPersona, run_days

#: A Tuesday afternoon: every default schedule is awake, the night far off.
TUESDAY_1400 = datetime(2026, 10, 6, 14, 0)
T0 = datetime(2026, 10, 5, 12, 0)

#: The render lint's checks (tests/test_render_lint.py), applied to what is
#: quoted to her in the second person (the moment, spec section 4.10).
BARE_PRONOUN_RE = re.compile(r"\b(she|her|hers|herself|he|him|his|himself)\b", re.IGNORECASE)
DOUBLED_WORD_RE = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)
THE_USER_RE = re.compile(r"\bthe user\b", re.IGNORECASE)
#: "you" with a singular verb: the second-person form of the they-lint.
YOU_SINGULAR_RE = re.compile(r"\byou (?:was|has|is|does)(?:n['’]t)?\b", re.IGNORECASE)
#: The word after "you" (past one adverb), to catch a hard-coded third-person
#: verb ("you never visits") that the they-lint's four verbs do not cover.
YOU_THEN_WORD_RE = re.compile(r"\byou (?:(?:\w+ly|never|always|still|also|just) )?([a-z]+)\b")


def _assert_prompt_safe(gist: str) -> None:
    """One plain sentence, fit to quote to her: capitalised, one closing stop
    and no other sentence break, no digit, no brace, no snake_case, no
    he/she/him/her, never "the user", no doubled word."""
    assert gist[:1].isupper(), gist
    assert gist.endswith("."), gist
    assert not re.search(r"[.!?]\s", gist), gist
    assert not re.search(r"\d", gist), gist
    assert not re.search(r"[{}_]", gist), gist
    assert not BARE_PRONOUN_RE.search(gist), gist
    assert not THE_USER_RE.search(gist), gist
    assert not DOUBLED_WORD_RE.search(gist), gist
    assert not YOU_SINGULAR_RE.search(gist), gist


# ======================================================================
# 1. An episode
# ======================================================================

def _episode(**values) -> Episode:
    base = dict(id=1, at=T0, place="home", people=(), what="reading", emotion="", valence=0.0,
                importance=0.3, strength=INITIAL_STRENGTH, last_recalled=None, tags=())
    base.update(values)
    return Episode(**base)


def test_an_episode_has_the_fields_the_spec_names():
    """spec 4.6: Episode(id, at, place, people, what, emotion, valence,
    importance, strength, last_recalled, tags)."""
    assert [f.name for f in fields(Episode)] == [
        "id", "at", "place", "people", "what", "emotion", "valence", "importance", "strength",
        "last_recalled", "tags"]


def test_recency_decays_0_995_per_hour_since_she_last_recalled_it():
    episode = _episode()
    assert RECENCY_PER_HOUR == 0.995
    assert episode.recency(T0 + timedelta(hours=10)) == pytest.approx(0.995 ** 10)
    # Never recalled: since it happened. Recalled: since then.
    recalled = replace(episode, last_recalled=T0 + timedelta(hours=8))
    assert recalled.recency(T0 + timedelta(hours=10)) == pytest.approx(0.995 ** 2)
    assert episode.recency(T0) == pytest.approx(1.0)


def test_retention_is_exp_minus_t_over_s_with_t_in_days():
    episode = _episode(strength=2.0)
    assert episode.retention(T0 + timedelta(days=3)) == pytest.approx(math.exp(-3 / 2))
    assert episode.retention(T0 + timedelta(hours=12)) == pytest.approx(math.exp(-0.5 / 2))


def test_recalling_an_episode_adds_one_to_its_strength_and_starts_its_clock_again():
    episode = _episode()
    later = T0 + timedelta(days=2)
    recalled = episode.recalled(later)
    assert recalled.strength == episode.strength + 1
    assert recalled.last_recalled == later
    assert recalled.retention(later) == pytest.approx(1.0)
    assert (recalled.id, recalled.what, recalled.importance) == (episode.id, episode.what, episode.importance)


@pytest.mark.parametrize("intensity, novel, people, expected", [
    (0.0, False, 0, IMPORTANCE_FLOOR),
    (1.0, True, 2, 1.0),
    (0.25, False, 0, IMPORTANCE_FLOOR + (1 - IMPORTANCE_FLOOR) * EMOTION_WEIGHT * 0.25),
    (0.0, False, 1, IMPORTANCE_FLOOR + (1 - IMPORTANCE_FLOOR) * PEOPLE_WEIGHT),
    (0.0, True, 0, IMPORTANCE_FLOOR + (1 - IMPORTANCE_FLOOR) * NOVELTY_WEIGHT),
    (3.0, False, 0, IMPORTANCE_FLOOR + (1 - IMPORTANCE_FLOOR) * EMOTION_WEIGHT),  # felt intensity caps at 1
])
def test_importance_is_the_documented_formula(intensity, novel, people, expected):
    """importance = FLOOR + (1 - FLOOR) x (EMOTION x felt + NOVELTY x novel +
    PEOPLE x anyone there), each term 0..1: 0.1 (Generative Agents' 1 of 10,
    "purely mundane", on the spec's 0..1 mapping of their scale) to 1.0."""
    assert EMOTION_WEIGHT + NOVELTY_WEIGHT + PEOPLE_WEIGHT == pytest.approx(1.0)
    assert IMPORTANCE_FLOOR == 0.1
    assert importance_of(intensity, novel, people) == pytest.approx(expected)


@pytest.mark.parametrize("episode, gist", [
    (_episode(what="reading", place="cafe", emotion="curious"), "Reading at the cafe, feeling curious."),
    (_episode(what="cooking a meal", place="home", people=("Roberta",), emotion="warm"),
     "Cooking a meal at home with Roberta, feeling warm."),
    (_episode(what="a text from Mara", place="park", people=("Mara",)), "A text from Mara at the park."),
    (_episode(what="You spilled coffee on your shirt", place="cafe", emotion="annoyed"),
     "You spilled coffee on your shirt at the cafe, feeling annoyed."),
    (_episode(what="finishing “Run 5 miles”", place="", emotion="proud"),
     "Finishing “Run five miles”, feeling proud."),
    (_episode(what="walking", place="in transit", emotion="let_down"), "Walking on the way, feeling let down."),
    (_episode(what="got praised by your boss", place="workplace", emotion="proud"),
     "Got praised by your boss at work, feeling proud."),
    (_episode(what="gym workout", place="yoga_studio", people=("Ada", "Farid"), emotion="neutral"),
     "Gym workout at the yoga studio with Ada and Farid."),
    (_episode(what="people watching", place="street"), "People watching out on the street."),
    (_episode(what="a quiet drink", place="the_rusty_anchor"), "A quiet drink at the rusty anchor."),
    (_episode(what="Found a coin. It was shiny!", place="home"), "Found a coin at home."),
    (_episode(what="reading chapter 12 of 20", place="apartment_4b"),
     "Reading chapter twelve of twenty at the apartment four b."),
])
def test_the_gist_is_one_plain_sentence(episode, gist):
    """What happened, where, with whom, and what she felt -- one sentence, no
    number, no snake_case: a gist, never a transcript."""
    assert episode.gist() == gist
    _assert_prompt_safe(episode.gist())


# ======================================================================
# 2. The stream
# ======================================================================

def test_with_equal_importance_and_relevance_the_more_recent_episode_ranks_first():
    """The acceptance: two episodes alike in everything but when -- the one
    written first happened later -- rank by when they happened, not by the
    order they were written, unprompted and for a query both match."""
    stream = MemoryStream()
    later = stream.record(at=T0 + timedelta(hours=5), what="reading", place="home",
                          emotions={"content": 0.2}, valence=0.1)
    earlier = stream.record(at=T0, what="reading", place="home", emotions={"content": 0.2}, valence=0.1)
    assert later.importance == earlier.importance
    now = T0 + timedelta(hours=6)
    assert [e.id for e in stream.retrieve(now=now, k=2)] == [later.id, earlier.id]
    assert [e.id for e in stream.retrieve(now=now, query="reading at home", k=2)] == [later.id, earlier.id]


def test_when_every_term_is_equal_the_episode_written_later_comes_first():
    """Ties go to the episode written later: three episodes alike in every
    term -- instant, importance, mood, retention, relevance -- come back
    newest-written first, unprompted and for a query all three match."""
    stream = MemoryStream()
    written = [stream.record(at=T0, what="reading", place="home", valence=0.0) for _ in range(3)]
    now = T0 + timedelta(hours=2)
    assert len({retrieval_score(e, now) for e in written}) == 1
    newest_first = [e.id for e in reversed(written)]
    assert [e.id for e in stream.retrieve(now=now, k=3)] == newest_first
    assert [e.id for e in stream.retrieve(now=now, query="reading", k=3)] == newest_first


def test_importance_can_outrank_recency():
    """Not recency alone: a hard hour a few hours back comes to mind before a
    mundane minute ago."""
    stream = MemoryStream()
    strong = stream.record(at=T0, what="a fight with Mara", people=("Mara",),
                           emotions={"angry": 0.6, "hurt": 0.4}, valence=0.0)
    stream.record(at=T0 + timedelta(hours=3), what="brushing teeth", valence=0.0)
    assert [e.id for e in stream.retrieve(now=T0 + timedelta(hours=3), k=1)] == [strong.id]


def test_relevance_brings_up_what_the_query_names():
    """A query naming a place brings up the episode there, over a more recent
    one elsewhere."""
    stream = MemoryStream()
    cafe = stream.record(at=T0, what="reading", place="cafe", valence=0.0)
    stream.record(at=T0 + timedelta(hours=2), what="a walk", place="park", valence=0.0)
    assert stream.retrieve(now=T0 + timedelta(hours=3), query="How was that cafe?", k=1) == [cafe]


def test_mood_congruence_brings_up_what_was_lived_in_a_like_mood():
    """Remembered in the mood it was lived in: with everything else equal, a
    low mood recalls the episode lived low, a bright one the bright one."""
    stream = MemoryStream()
    low = stream.record(at=T0, what="waiting in the rain", valence=-0.6)
    bright = stream.record(at=T0, what="waiting for friends", valence=0.6)
    now = T0 + timedelta(hours=1)
    assert stream.retrieve(now=now, k=1, mood_valence=-0.5) == [low]
    assert stream.retrieve(now=now, k=1, mood_valence=0.5) == [bright]


def test_retrieving_changes_nothing_and_recalling_strengthens_what_it_returns(tmp_path):
    stream = MemoryStream(str(tmp_path / "life.db"))
    stream.load()
    first = stream.record(at=T0, what="reading", valence=0.0)
    second = stream.record(at=T0 + timedelta(hours=1), what="a walk", valence=0.0)
    now = T0 + timedelta(hours=2)
    assert [e.strength for e in stream.retrieve(now=now, k=2)] == [1.0, 1.0]
    assert [e.strength for e in stream.episodes] == [1.0, 1.0]
    (recalled,) = stream.recall(now=now, k=1)
    assert recalled.id == second.id and recalled.strength == 2.0 and recalled.last_recalled == now
    assert stream.get(first.id).strength == 1.0
    assert stream.recall(now=now, k=0) == []
    assert len(stream.recall(now=now, k=10)) == 2


def test_a_recalled_episode_s_strength_grows_and_it_decays_slower_afterwards(tmp_path):
    """The acceptance: recall adds 1 to S -- saved at once -- and the same two
    days cost the recalled episode less retention than they did before."""
    db = str(tmp_path / "life.db")
    stream = MemoryStream(db)
    stream.load()
    episode = stream.record(at=T0, what="a call from Mara", people=("Mara",), valence=0.2)
    assert episode.strength == INITIAL_STRENGTH == 1.0
    two_days = T0 + timedelta(days=2)
    before = episode.retention(two_days)
    assert before == pytest.approx(math.exp(-2.0))
    (recalled,) = stream.recall(now=two_days, k=1)
    assert recalled.strength == 2.0
    after = recalled.retention(two_days + timedelta(days=2))
    assert after == pytest.approx(math.exp(-1.0))
    assert after > before
    reloaded = MemoryStream(db)
    reloaded.load()
    assert reloaded.get(episode.id).strength == 2.0
    assert reloaded.get(episode.id).last_recalled == two_days


def test_retention_weights_recall_so_what_she_holds_less_of_ranks_lower():
    """Ruling T12-R1: an episode's score is (recency + importance + relevance
    + mood congruence) x its retention. Two episodes alike in everything but
    strength -- one recalled twice at the instant it happened, so its recency
    is the other's -- rank by how much of each she still holds: the stronger
    first, though written first (unweighted they tie, and the later-written
    would come first)."""
    stream = MemoryStream()
    held = stream.record(at=T0, what="a walk", place="park", valence=0.0)
    faded = stream.record(at=T0, what="a walk", place="park", valence=0.0)
    stream.reinforce([held], now=T0)
    stream.reinforce([held], now=T0)
    held = stream.get(held.id)
    now = T0 + timedelta(days=1)
    assert held.strength == 3.0 and held.recency(now) == faded.recency(now)
    assert held.retention(now) > faded.retention(now)
    assert [e.id for e in stream.retrieve(now=now, k=2)] == [held.id, faded.id]


def test_an_old_memory_she_keeps_recalling_can_outrank_a_newer_one_she_never_has():
    """Ruling T12-R1: rehearsal keeps a memory: equal in weight, the old one
    recalled four times comes to mind before a newer one never recalled, whose
    recency is higher."""
    stream = MemoryStream()
    old = stream.record(at=T0, what="the night at the lake", place="lake", valence=0.0)
    for _ in range(4):
        stream.reinforce([old], now=T0 + timedelta(days=1))
    newer = stream.record(at=T0 + timedelta(days=1, hours=12), what="a walk", place="park", valence=0.0)
    now = T0 + timedelta(days=3)
    old = stream.get(old.id)
    assert old.importance == newer.importance and old.recency(now) < newer.recency(now)
    assert [e.id for e in stream.retrieve(now=now, k=1)] == [old.id]


def test_a_cue_brings_back_a_memory_that_has_faded():
    """Ruling T12-R5 (cue-dependent recall): asked about her reading, she
    remembers yesterday's reading though three unrelated things happened in
    the last hour; unprompted, the fresh ones come to mind first."""
    stream = MemoryStream()
    reading = stream.record(at=T0, what="reading a paperback on the balcony", place="home", valence=0.0)
    now = T0 + timedelta(days=2)
    recent = [stream.record(at=now - timedelta(minutes=m), what=what, place="home", valence=0.0)
              for m, what in ((50, "fixing the sink"), (30, "a phone call"), (10, "doing the dishes"))]
    assert reading.retention(now) < 0.2
    assert [e.id for e in stream.retrieve(now=now, query="What were you reading?", k=1)] == [reading.id]
    unprompted = [e.id for e in stream.retrieve(now=now, k=3)]
    assert reading.id not in unprompted and set(unprompted) == {e.id for e in recent}


@pytest.mark.parametrize("episode", [
    _episode(at=T0 - timedelta(days=36500)),
    _episode(strength=0.0),
    _episode(strength=-5.0),
    _episode(strength=float("nan")),
    _episode(strength=float("inf")),
    _episode(at=T0 + timedelta(days=3)),
    _episode(last_recalled=T0 + timedelta(days=3)),
    _episode(valence=-1.0, importance=1.0),
], ids=["a-century-old", "no-strength", "negative-strength", "nan-strength", "endless-strength",
        "stamped-after-now", "recalled-after-now", "extremes"])
def test_retention_never_makes_a_score_negative_or_not_a_number(episode):
    """Retention is exp(-t/S) with t never negative and S at least a sane
    one: 0..1, so a score stays 0..4 -- a century-old episode scores 0, not
    NaN, and no strength or clock reading turns one negative."""
    now = T0 + timedelta(hours=1)
    assert 0.0 <= episode.retention(now) <= 1.0
    for relevance in (0.0, 1.0):
        for mood in (-1.0, 0.0, 1.0):
            score = retrieval_score(episode, now, relevance=relevance, mood_valence=mood)
            assert math.isfinite(score) and 0.0 <= score <= 4.0, (relevance, mood, score)


def test_what_she_felt_sets_the_emotion_and_how_strongly_she_felt_it_the_importance():
    """Her strongest feeling is the episode's emotion, and how strongly she
    felt it -- not the sum of the mild feelings an activity blends into her
    mood, which would put reading above a call from a friend."""
    stream = MemoryStream()
    episode = stream.record(at=T0, what="finishing “Learn to swim”",
                            emotions={"proud": 0.4, "satisfied": 0.3}, valence=0.4)
    assert episode.emotion == "proud"
    assert episode.importance == pytest.approx(importance_of(0.4, False, 0))
    reading = stream.record(at=T0, what="reading", emotions={"curious": 0.1, "content": 0.15, "absorbed": 0.2})
    call = stream.record(at=T0, what="a call from Ada", people=("Ada",))
    assert reading.importance == pytest.approx(importance_of(0.2, False, 0))
    assert reading.importance < call.importance
    # An appraisal (Task 14, Task 16) names the emotion, its strength and its valence itself.
    appraised = stream.record(at=T0, what="a hard talk", emotions={"content": 0.1}, emotion="relieved",
                              intensity=0.8, valence=0.45)
    assert (appraised.emotion, appraised.valence) == ("relieved", 0.45)
    assert appraised.importance == pytest.approx(importance_of(0.8, False, 0))
    # Nothing felt: no emotion.
    assert stream.record(at=T0, what="a quiet minute", emotions={"calm": 0.0}).emotion == ""


def test_nothing_is_new_to_her_before_her_memory_spans_its_window():
    """Her first days of memory are not her first days of life: a place her
    memory has not seen yet is only unrecorded, not new to her, until the
    stream spans NOVELTY_WINDOW_DAYS -- or her whole routine would be
    "novel", and kept as her most important memories for good."""
    assert NOVELTY_WINDOW_DAYS == 7
    stream = MemoryStream()
    routine = stream.record(at=T0, what="reading", place="home", activity="reading")
    elsewhere = stream.record(at=T0 + timedelta(days=1), what="visiting the museum", place="museum",
                              activity="visiting the museum")
    assert elsewhere.importance == routine.importance == importance_of(0.0, False, 0)


def test_an_activity_place_or_person_unseen_for_the_window_is_novel():
    stream = MemoryStream()
    for day in range(8):
        stream.record(at=T0 + timedelta(days=day), what="reading", place="home", activity="reading")
    day8 = T0 + timedelta(days=8)
    assert stream.record(at=day8, what="reading", place="home", activity="reading").importance \
        == importance_of(0.0, False, 0)
    assert stream.record(at=day8, what="reading", place="museum", activity="reading").importance \
        == importance_of(0.0, True, 0)
    assert stream.record(at=day8, what="painting", place="home", activity="painting").importance \
        == importance_of(0.0, True, 0)
    assert stream.record(at=day8, what="a call from Mara", place="home", people=("Mara",)).importance \
        == importance_of(0.0, True, 1)
    # Seen three days ago: nothing new. Unseen for more than the window: new again.
    assert stream.record(at=day8 + timedelta(days=3), what="a call from Mara", place="home",
                         people=("Mara",)).importance == importance_of(0.0, False, 1)
    assert stream.record(at=day8 + timedelta(days=11), what="a text from Mara", place="home",
                         people=("mara",)).importance == importance_of(0.0, True, 1)


def test_the_retention_cap_keeps_the_most_important_episodes(tmp_path):
    """Keep the ``cap`` most important, pruned when one is written; among
    equals the older goes first. The database holds exactly what is kept."""
    db = str(tmp_path / "life.db")
    stream = MemoryStream(db, cap=4)
    stream.load()
    felt = [0.1, 0.9, 0.3, 0.5, 0.2, 0.7]
    written = [stream.record(at=T0 + timedelta(hours=i), what=f"moment {'abcdef'[i]}", emotions={"content": x})
               for i, x in enumerate(felt)]
    fourth_best = sorted(w.importance for w in written)[-4]
    kept = sorted(e.id for e in written if e.importance >= fourth_best)
    assert sorted(e.id for e in stream.episodes) == kept
    assert len(stream.episodes) == 4
    reloaded = MemoryStream(db, cap=4)
    reloaded.load()
    assert sorted(e.id for e in reloaded.episodes) == kept
    # Equally important: the newest are kept.
    ties = MemoryStream(cap=2)
    same = [ties.record(at=T0 + timedelta(hours=i), what="reading", place="home") for i in range(3)]
    assert [e.id for e in ties.episodes] == [same[1].id, same[2].id]


def test_the_stream_keeps_the_two_thousand_most_important_by_default():
    stream = MemoryStream()
    assert EPISODE_CAP == 2000 and stream.cap == 2000
    for i in range(EPISODE_CAP):
        stream.record(at=T0 + timedelta(minutes=i), what="reading", emotions={"content": 0.2})
    assert len(stream.episodes) == EPISODE_CAP
    mundane = stream.record(at=T0 + timedelta(days=5), what="standing around")
    assert len(stream.episodes) == EPISODE_CAP
    assert stream.get(mundane.id) is None
    vivid = stream.record(at=T0 + timedelta(days=5), what="a storm", emotions={"awed": 0.9})
    assert len(stream.episodes) == EPISODE_CAP
    assert stream.get(vivid.id) == vivid
    assert stream.get(1) is None  # the oldest of the equally important went


def test_the_stream_survives_a_reload_whole(tmp_path):
    """Save on write: every episode, its recall state, the next id and the
    novelty clock are read back as they were; ids never repeat, even when the
    newest episode was pruned."""
    db = str(tmp_path / "life.db")
    stream = MemoryStream(db, cap=3)
    stream.load()
    cooking = stream.record(at=T0, what="cooking a meal", place="home", people=("Roberta", "Farid"),
                            emotions={"warm": 0.15, "connected": 0.15}, valence=0.3,
                            tags=("activity", "joint", "event:3"), activity="cooking a meal")
    stream.record(at=T0 + timedelta(hours=1), what="a text from Mara", place="cafe", people=("Mara",),
                  emotions={"anxious": 0.1, "unsettled": 0.1}, valence=-0.2, tags=("social", "threat"))
    stream.record(at=T0 + timedelta(hours=2), what="You spilled coffee on your shirt", place="cafe",
                  emotions={"annoyed": 0.3}, valence=-0.1, tags=("chaos", "share:9"))
    assert [e.id for e in stream.recall(now=T0 + timedelta(hours=3), query="cooking", k=1)] == [cooking.id]
    pruned = stream.record(at=T0 + timedelta(hours=4), what="standing around", valence=0.0)
    assert stream.get(pruned.id) is None

    reloaded = MemoryStream(db, cap=3)
    reloaded.load()
    assert reloaded.episodes == stream.episodes
    assert reloaded.get(cooking.id).strength == 2.0
    assert reloaded.record(at=T0 + timedelta(hours=5), what="reading", valence=0.0).id == pruned.id + 1


def test_the_novelty_clock_survives_a_reload(tmp_path):
    db = str(tmp_path / "life.db")
    stream = MemoryStream(db)
    stream.load()
    for day in range(8):
        stream.record(at=T0 + timedelta(days=day), what="reading", place="home", activity="reading")
    reloaded = MemoryStream(db)
    reloaded.load()
    day8 = T0 + timedelta(days=8)
    assert reloaded.record(at=day8, what="reading", place="home", activity="reading").importance \
        == importance_of(0.0, False, 0)
    assert reloaded.record(at=day8, what="reading", place="pier", activity="reading").importance \
        == importance_of(0.0, True, 0)


def test_clearing_the_stream_forgets_everything_on_disk_too(tmp_path):
    db = str(tmp_path / "life.db")
    stream = MemoryStream(db)
    stream.load()
    last = stream.record(at=T0, what="reading", valence=0.0)
    stream.clear()
    assert stream.episodes == ()
    reloaded = MemoryStream(db)
    reloaded.load()
    assert reloaded.episodes == ()
    assert reloaded.record(at=T0, what="a walk", valence=0.0).id > last.id


def test_the_tables_are_created_in_a_database_that_has_none(tmp_path):
    """A migration-safe CREATE: an existing life.db (other tables, rows) gains
    the memory tables and keeps what it had; creating them twice is harmless."""
    db = tmp_path / "life.db"
    with contextlib.closing(sqlite3.connect(db)) as conn:
        conn.execute("CREATE TABLE activity_logs (id INTEGER PRIMARY KEY, activity_name TEXT)")
        conn.execute("INSERT INTO activity_logs (activity_name) VALUES ('reading')")
        conn.commit()
        MemoryStream.create_schema(conn.cursor())
        MemoryStream.create_schema(conn.cursor())
        conn.commit()
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert list(conn.execute("SELECT activity_name FROM activity_logs")) == [("reading",)]
    assert {"life_memory_episodes", "life_memory_facets", "life_memory_state"} <= tables


# ======================================================================
# 3. The embed hook
# ======================================================================

@pytest.fixture
def hook_registry():
    """The hook registry for one test; every provider is put back afterwards."""
    saved = {name: hooks.provider_for(name) for name in hooks.HOOK_NAMES}
    yield hooks
    hooks.reset()
    hooks.configure(**{name: provider for name, provider in saved.items() if provider is not None})


def test_embed_is_an_optional_hook_the_host_can_register(hook_registry):
    assert "embed" in hooks.HOOK_NAMES and "embed" in hooks.__all__
    hooks.reset()
    with pytest.raises(hooks.HookNotConfigured):
        hooks.embed(["a text"])
    hooks.configure(embed=lambda texts: [[1.0] for _ in texts])
    assert hooks.embed(["a", "b"]) == [[1.0], [1.0]]


def _two_moments() -> tuple:
    stream = MemoryStream()
    beach = stream.record(at=T0, what="a swim", place="beach", valence=0.0)
    cafe = stream.record(at=T0 + timedelta(hours=2), what="reading", place="cafe", valence=0.0)
    return stream, beach, cafe


def test_without_an_embed_hook_relevance_is_keyword_overlap_and_nothing_is_logged_above_debug(
        hook_registry, caplog):
    hooks.reset()
    caplog.set_level(logging.DEBUG, logger="aura_life")
    stream, beach, cafe = _two_moments()
    assert stream.retrieve(now=T0 + timedelta(hours=3), query="the cafe", k=1) == [cafe]
    assert stream.retrieve(now=T0 + timedelta(hours=3), query="the beach", k=1) == [beach]
    assert [r for r in caplog.records if r.levelno > logging.DEBUG] == []
    assert any("embed" in r.getMessage() for r in caplog.records)


def test_an_embed_hook_decides_relevance_when_the_host_has_one(hook_registry):
    """"The sea" shares no word with "a swim at the beach"; the host's vectors
    say they are close. The query is embedded first, and an episode once."""
    calls = []

    def embed(texts):
        calls.append(list(texts))
        return [[1.0, 0.0] if ("sea" in t.lower() or "beach" in t.lower()) else [0.0, 1.0] for t in texts]

    hooks.configure(embed=embed)
    stream, beach, cafe = _two_moments()
    now = T0 + timedelta(hours=3)
    assert stream.retrieve(now=now, query="the sea", k=1) == [beach]
    assert calls[0][0] == "the sea" and len(calls[0]) == 3
    assert stream.retrieve(now=now, query="the sea again", k=1) == [beach]
    assert calls[1] == ["the sea again"]


def test_an_embed_hook_that_changes_its_model_is_asked_again_and_relevance_stays_in_range(hook_registry, caplog):
    """A host that switches models answers vectors of another length: the
    kept vectors are dropped and every episode is embedded again, once, at
    the new length -- no crash, no warning, relevance still 0..1."""
    width = {"now": 2}
    calls = []

    def embed(texts):
        calls.append((width["now"], len(texts)))
        n = width["now"]
        return [[1.0] + [0.0] * (n - 1) if ("sea" in t.lower() or "beach" in t.lower()) else [0.0] * (n - 1) + [1.0]
                for t in texts]

    hooks.configure(embed=embed)
    caplog.set_level(logging.DEBUG, logger="aura_life")
    stream, beach, cafe = _two_moments()
    now = T0 + timedelta(hours=3)
    assert stream.retrieve(now=now, query="the sea", k=1) == [beach]
    width["now"] = 3
    assert stream.retrieve(now=now, query="the sea", k=1) == [beach]
    # The query at the new length, then the query and both episodes again at it.
    assert calls == [(2, 3), (3, 1), (3, 3)]
    assert sorted(len(vector) for vector in stream._vectors.values()) == [3, 3]
    relevance = stream._relevance("the sea", list(stream.episodes))
    assert relevance == [1.0, 0.0]
    assert all(0.0 <= r <= 1.0 for r in relevance)
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


@pytest.mark.parametrize("provider", [
    lambda texts: (_ for _ in ()).throw(RuntimeError("the embedding service is down")),
    lambda texts: [[1.0]],                                    # one vector for three texts
    lambda texts: [[1.0, 0.0]] + [[1.0] for _ in texts[1:]],  # vectors of two lengths
    lambda texts: [[float("nan"), 1.0] for _ in texts],       # not a number
    lambda texts: None,
], ids=["raises", "too-few", "ragged", "nan", "none"])
def test_an_embed_hook_that_fails_is_not_used_and_says_so_once(hook_registry, caplog, provider):
    hooks.configure(embed=provider)
    caplog.set_level(logging.DEBUG, logger="aura_life")
    stream, beach, cafe = _two_moments()
    now = T0 + timedelta(hours=3)
    assert stream.retrieve(now=now, query="the cafe", k=1) == [cafe]
    assert stream.retrieve(now=now, query="the beach", k=1) == [beach]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "embed" in warnings[0].getMessage()


# ======================================================================
# 4. Her life, remembered
# ======================================================================

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


def _service(tmp_path, clock, name: str = "mara", seed: int = 7, **kwargs) -> LifeService:
    """A persona of a world on ``clock`` (its ``now``), her draws seeded."""
    svc = LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=name,
                      world_environment=WorldEnvironment(now=clock, seed=seed), rng=random.Random(seed), **kwargs)
    svc._desire_system.should_do_intimate_activity = lambda *args, **kw: False
    return svc


def _quiet(svc: LifeService) -> LifeService:
    """No NPC event, chaos or micro-event on her activity ticks unless a test
    brings one."""
    svc._social.tick = lambda *args, **kw: None
    svc._chaos.roll = lambda *args, **kw: None
    svc._micro_event_chance = 0.0
    return svc


def _tagged(svc: LifeService, tag: str) -> list:
    return [e for e in svc._memory.episodes if tag in e.tags]


def _shared(svc: LifeService, content: str) -> str:
    """The share id of her shareable with this content."""
    (share_id,) = [exp.share_id for exp in svc._shareable_queue if exp.content == content]
    return share_id


def _life_event(svc: LifeService, source: str) -> str:
    """The share id of her one life event from ``source``."""
    (share_id,) = [event.share_id for event in svc._life_events._events if event.source == source]
    return share_id


def test_what_she_does_is_remembered_on_the_world_clock(tmp_path, persona_clock):
    world_clock = ScriptedClock(datetime(2031, 3, 4, 14, 0))
    svc = _quiet(_service(tmp_path, world_clock))
    activity = svc._activity_engine.get_activity("reading")
    log = svc._perform_activity(activity, None)
    (episode,) = _tagged(svc, "activity")
    assert episode.what == "reading"
    assert episode.at == datetime(2031, 3, 4, 14, 0)
    assert episode.place == log.location == svc._current_location
    assert episode.emotion == "absorbed"
    # Task 14: the valence of how it felt -- her appraisal of how it went
    # (aura_life.emotion.appraisal) -- not of her mood at the time.
    felt = [EmotionSpike(0.0, name, x, "") for name, x in log.emotions_triggered.items()]
    assert episode.valence == pytest.approx(appraised_valence(felt))
    assert activity.category.value in episode.tags and set(activity.tags) <= set(episode.tags)
    assert episode.people == ()
    # Her strongest feeling there is 0.2: a life event of the activity itself, tagged on it.
    assert _life_event(svc, "activity") in episode.tags


def test_thinking_about_the_user_is_remembered_by_the_user_s_name(tmp_path, persona_clock):
    svc = _quiet(_service(tmp_path, persona_clock, user_info={"name": "Robin"}))
    svc._perform_activity(svc._activity_engine.get_activity("thinking about user"), None)
    (episode,) = _tagged(svc, "activity")
    assert episode.what == "thinking about Robin"


def test_an_activity_s_shareable_is_tagged_on_its_episode(tmp_path, persona_clock):
    svc = _quiet(_service(tmp_path, persona_clock))
    execute = svc._activity_engine.execute_activity

    def share_worthy(*args, **kwargs):
        log = execute(*args, **kwargs)
        log.share_worthy = True
        return log

    svc._activity_engine.execute_activity = share_worthy
    log = svc._perform_activity(svc._activity_engine.get_activity("stargazing"), None)
    (episode,) = _tagged(svc, "activity")
    (share_id,) = [exp.share_id for exp in svc._shareable_queue if exp.activity_log_id == log.id]
    assert share_id in episode.tags
    assert _life_event(svc, "activity") in episode.tags


def test_what_her_people_do_is_remembered_with_them(tmp_path, persona_clock):
    svc = _quiet(_service(tmp_path, persona_clock))
    event = SocialEvent(npc_name="Mara", event_type="call", description="Mara called to catch up",
                        kind="friend", valence=1.0, share_worthy=True)
    svc._social.tick = lambda *args, **kw: event
    svc._perform_activity(svc._activity_engine.get_activity("reading"), None)
    (episode,) = _tagged(svc, "social")
    assert (episode.what, episode.people) == ("a call from Mara", ("Mara",))
    assert {"call", "friend"} <= set(episode.tags)
    assert _shared(svc, "Mara called to catch up") in episode.tags
    assert episode.importance >= importance_of(0.0, False, 1)


def test_unwelcome_contact_is_remembered_as_what_it_made_her_feel(tmp_path, persona_clock):
    svc = _quiet(_service(tmp_path, persona_clock))
    event = SocialEvent(npc_name="Shirley", event_type="text_received", description="Shirley texted",
                        kind="threat", valence=-1.0, share_worthy=False)
    svc._social.tick = lambda *args, **kw: event
    svc._perform_activity(svc._activity_engine.get_activity("reading"), None)
    (episode,) = _tagged(svc, "social")
    assert episode.what == "a text from Shirley"
    assert episode.emotion in UNWELCOME_KIND_EMOTIONS["threat"]
    assert "threat" in episode.tags
    assert episode.importance == pytest.approx(importance_of(
        max(UNWELCOME_KIND_EMOTIONS["threat"].values()), False, 1))


def test_what_goes_wrong_is_remembered_addressed_to_her(tmp_path, persona_clock):
    svc = _quiet(_service(tmp_path, persona_clock, definition=PersonalityDefinition(
        name="Mara", appearance_details={"gender": "female"})))
    svc._chaos.roll = lambda *args, **kw: {
        "type": "universal", "text": "{Subj} spilled coffee on {poss} shirt",
        "emotions": {"annoyed": 0.2}, "share_worthy": True}
    svc._perform_activity(svc._activity_engine.get_activity("reading"), None)
    (episode,) = _tagged(svc, "chaos")
    assert episode.what == "You spilled coffee on your shirt"
    assert episode.emotion == "annoyed"
    assert "universal" in episode.tags
    assert _shared(svc, "She spilled coffee on her shirt") in episode.tags
    # Her log keeps its own words (third person), as before.
    assert "She spilled coffee on her shirt" in svc._recent_activities[0].narrative


def test_a_lucky_break_is_remembered_with_its_life_event(tmp_path, persona_clock):
    svc = _quiet(_service(tmp_path, persona_clock))
    svc._chaos.roll = lambda *args, **kw: {
        "type": "serendipity", "text": "found a bookshop {subj} didn't know existed",
        "emotions": {"delighted": 0.3}, "share_worthy": False}
    svc._perform_activity(svc._activity_engine.get_activity("reading"), None)
    (episode,) = _tagged(svc, "chaos")
    assert episode.what == "found a bookshop you didn't know existed"
    assert "serendipity" in episode.tags
    assert _life_event(svc, "chaos_serendipity") in episode.tags


class _FirstDraws:
    """A service stream whose rolls always pass and which takes the first of
    every choice."""

    def random(self) -> float:
        return 0.0

    def choice(self, seq):
        return list(seq)[0]

    def uniform(self, low, high):
        return low


def test_a_small_moment_is_remembered(tmp_path, persona_clock):
    svc = _quiet(_service(tmp_path, persona_clock))
    svc._micro_event_chance = 1.0
    svc._service_rng = _FirstDraws()
    moment = svc._setting.micro_events[0]
    svc._perform_activity(svc._activity_engine.get_activity("reading"), None)
    (episode,) = _tagged(svc, "moment")
    assert episode.what == render_second_person(moment["text"])


def test_a_finished_book_is_remembered(tmp_path, persona_clock):
    svc = _quiet(_service(tmp_path, persona_clock))
    svc._media.current_book = "Piranesi 2"
    svc._media.book_progress = 0.999
    svc._perform_activity(svc._activity_engine.get_activity("reading"), None)
    (episode,) = _tagged(svc, "book")
    assert episode.what == "finishing “Piranesi 2”"
    assert episode.gist().startswith("Finishing “Piranesi two”")
    assert episode.emotion == "satisfied"
    assert _life_event(svc, "book_completion") in episode.tags
    assert _shared(svc, "Just finished reading Piranesi 2!") in episode.tags


def test_a_skill_milestone_is_remembered(tmp_path, persona_clock):
    svc = _quiet(_service(tmp_path, persona_clock))
    log = svc._perform_activity(svc._activity_engine.get_activity("cooking a meal"), None)
    svc._update_skill("cooking", 1.0, log)
    milestones = _tagged(svc, "milestone")
    texts = [text for _, text in svc._setting.skill_milestones["cooking"]]
    assert [e.what for e in milestones] == [render_second_person(t) for t in texts]
    assert all("cooking" in e.tags and e.emotion == "proud" for e in milestones)
    assert all(e.place == log.location for e in milestones)


def _goal(title: str) -> Goal:
    return Goal(title=title, description="", timeframe=GoalTimeframe.WEEKLY)


def test_a_goal_reached_and_a_goal_given_up_are_remembered(tmp_path, persona_clock):
    svc = _quiet(_service(tmp_path, persona_clock))
    svc._goal_engine.check_goal_completion = lambda **kw: [_goal("Learn to swim")]
    svc._goal_engine.evaluate_motivation = lambda **kw: [
        GoalEvent("abandoned", "Find my authentic voice", {"sad": 0.3, "discouraged": 0.24, "resigned": 0.2},
                  "Gave up on 'Find my authentic voice'. Life got busy."),
        GoalEvent("motivation_drop", "Run a marathon", {"discouraged": 0.3}, "Starting to wonder"),
    ]
    svc._on_goal_tick()
    (reached,) = [e for e in _tagged(svc, "goal") if "completed" in e.tags]
    (given_up,) = [e for e in _tagged(svc, "goal") if "abandoned" in e.tags]
    assert reached.what == "finishing “Learn to swim”" and reached.emotion == "proud"
    assert _life_event(svc, "goal_completion") in reached.tags
    assert given_up.what == "giving up on “Find my authentic voice”" and given_up.emotion == "sad"
    assert reached.place == given_up.place == ""
    assert len(_tagged(svc, "goal")) == 2  # a motivation drop is no episode


def test_a_day_at_work_is_remembered(tmp_path, persona_clock):
    svc = _quiet(_service(tmp_path, persona_clock))
    event = svc._setting.work_events_positive[0]
    svc._career.tick = lambda now=None: event
    svc._on_energy_tick()
    (episode,) = _tagged(svc, "work")
    assert episode.what == render_second_person(event)
    felt = svc._setting.work_event_emotions[event]
    assert episode.emotion == max(felt, key=felt.get)


def test_what_she_does_in_private_is_not_in_her_memory_stream(tmp_path, persona_clock):
    """What her memory keeps is quoted back to her in the host's prompt, and
    an intimate activity -- several a day, as strongly felt as the library
    makes them -- would outrank the rest of her life and outlast it under the
    cap: it is in her log, never an episode."""
    svc = _quiet(_service(tmp_path, persona_clock))
    svc._desire_system.should_do_intimate_activity = lambda *args, **kw: True
    svc._desire_system._state.arousal = 1.0
    svc._energy.update_sleep = lambda *args, **kw: None
    svc._energy.in_sleep_window = lambda *args, **kw: False
    svc._daily_planner.get_planned_activity = lambda hour: None
    svc._activity_tick()
    private = {activity.name for activity in svc._setting.intimate_catalogue()}
    assert svc._recent_activities[0].activity_name in private
    assert svc._memory.episodes == ()


LINA_NIGHT = {"bedtime_hour": 4, "bedtime_minute": 0, "wake_hour": 12, "wake_minute": 0}
ROBERTA_NIGHT = {"bedtime_hour": 23, "bedtime_minute": 0, "wake_hour": 7, "wake_minute": 0}


class _Asks:
    """A household stream whose roll always passes and which takes the first
    of every choice."""

    def random(self) -> float:
        return 0.0

    def choice(self, seq):
        return list(seq)[0]


def test_what_housemates_do_together_each_remembers_with_the_other(tmp_path, persona_clock):
    world, home = WorldEnvironment(now=persona_clock, seed=3), Household()

    def member(pid, name, other, night, seed):
        definition = PersonalityDefinition(id=pid, name=name, appearance_details={"gender": "female"},
                                           household=[other.lower()])
        svc = LifeService(db_path=str(tmp_path / f"{pid}.db"), persona_id=pid, world_environment=world,
                          rng=random.Random(seed), definition=definition, sleep_schedule=night,
                          social_circle=[{"name": other, "kind": "co_resident"}], household=home)
        svc._desire_system.should_do_intimate_activity = lambda *args, **kw: False
        return _quiet(svc)

    lina = member("lina", "Lina", "Roberta", LINA_NIGHT, 7)
    roberta = member("roberta", "Roberta", "Lina", ROBERTA_NIGHT, 8)
    lina._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=14, activity_name="cooking a meal", reason="routine", location="home")])
    roberta._daily_planner._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=14, activity_name="reading", reason="routine", location="home")])
    lina._household_rng = _Asks()
    lina._on_activity_tick()
    (hers,) = _tagged(lina, "together")
    (theirs,) = _tagged(roberta, "together")
    assert (hers.what, hers.people) == ("cooking a meal", ("Roberta",))
    assert (theirs.what, theirs.people) == ("cooking a meal", ("Lina",))
    assert hers.at == theirs.at == persona_clock.instant
    assert hers.importance >= importance_of(0.0, False, 1)


def test_recall_hands_back_her_episodes_and_strengthens_them_on_disk(tmp_path, persona_clock):
    svc = _service(tmp_path, persona_clock)
    walk = svc._remember("a walk", place="park", emotions={"calm": 0.2})
    persona_clock.instant += timedelta(hours=2)
    call = svc._remember("a call from Mara", people=("Mara",), emotions={"connected": 0.3})
    persona_clock.instant += timedelta(hours=1)
    recalled = svc.recall(k=2)
    assert [e.id for e in recalled] == [call.id, walk.id]
    assert all(isinstance(e, Episode) and e.strength == 2.0 for e in recalled)
    assert [e.id for e in svc.recall("the park", k=1)] == [walk.id]
    again = _service(tmp_path, persona_clock)
    assert again._memory.get(walk.id).strength == 3.0
    assert again._memory.get(call.id).strength == 2.0
    assert svc.recall(k=0) == []


def test_recall_can_read_her_memories_without_strengthening_them(tmp_path, persona_clock):
    """Ruling T12-R2: ``recall(reinforce=False)`` reads what comes to mind --
    the episodes ``recall()`` would return, in its order -- and changes
    nothing: no strength gained, no recency or retention restarted, nothing
    saved. The default still strengthens them."""
    svc = _service(tmp_path, persona_clock)
    walk = svc._remember("a walk", place="park", emotions={"calm": 0.2})
    persona_clock.instant += timedelta(hours=2)
    call = svc._remember("a call from Mara", people=("Mara",), emotions={"connected": 0.3})
    persona_clock.instant += timedelta(hours=1)
    kept = svc._memory.episodes
    shown = svc.recall(k=2, reinforce=False)
    assert shown == [svc._memory.get(call.id), svc._memory.get(walk.id)]
    assert svc.recall("the park", k=1, reinforce=False) == [svc._memory.get(walk.id)]
    assert svc._memory.episodes == kept
    assert _service(tmp_path, persona_clock)._memory.episodes == kept
    recalled = svc.recall(k=2)
    assert [e.id for e in recalled] == [call.id, walk.id]
    assert [(e.strength, e.last_recalled) for e in recalled] == [(2.0, persona_clock.instant)] * 2


def test_recall_follows_her_mood(tmp_path, persona_clock):
    svc = _service(tmp_path, persona_clock)
    low = svc._remember("waiting in the rain", valence=-0.6)
    bright = svc._remember("waiting for friends", valence=0.6)
    svc._affect.mood.valence = -0.5
    assert [e.id for e in svc.recall(k=1)] == [low.id]
    svc._affect.mood.valence = 0.5
    assert [e.id for e in svc.recall(k=1)] == [bright.id]


def test_an_episode_takes_her_mood_unless_it_is_given_a_valence(tmp_path, persona_clock):
    svc = _service(tmp_path, persona_clock)
    svc._affect.mood.valence = -0.35
    assert svc._remember("a grey afternoon").valence == pytest.approx(-0.35)
    assert svc._remember("a good talk", valence=0.6, emotion="relieved").valence == pytest.approx(0.6)


def test_a_new_service_reads_the_saved_stream_before_it_writes(tmp_path, persona_clock):
    """Save on write, read when built: a service built on a saved life --
    started or not -- continues the saved ids and never writes over them."""
    first = _service(tmp_path, persona_clock)
    saved = [first._remember("reading"), first._remember("a walk", place="park")]
    second = _service(tmp_path, persona_clock)
    assert second._memory.episodes == first._memory.episodes
    added = second._remember("a nap")
    assert added.id == saved[-1].id + 1
    third = _service(tmp_path, persona_clock)
    assert [e.id for e in third._memory.episodes] == [e.id for e in saved] + [added.id]


def test_reset_state_forgets_her_episodes(tmp_path, persona_clock):
    """``reset_state()`` is what a host calls to clear a persona's memory."""
    svc = _service(tmp_path, persona_clock)
    svc._remember("reading")
    svc.reset_state()
    assert svc._memory.episodes == ()
    assert _service(tmp_path, persona_clock)._memory.episodes == ()


def test_a_failing_memory_never_takes_her_tick_down(tmp_path, persona_clock, caplog):
    svc = _quiet(_service(tmp_path, persona_clock))

    def broken(**kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    svc._memory.record = broken
    caplog.set_level(logging.WARNING, logger="aura_life")
    log = svc._perform_activity(svc._activity_engine.get_activity("reading"), None)
    assert log.activity_name == "reading" and svc._recent_activities[0] is log
    assert any("remember" in r.getMessage().lower() for r in caplog.records if r.levelno == logging.WARNING)


# ======================================================================
# 5. The words an episode is told in, and three simulated days
# ======================================================================

def test_second_person_is_you():
    assert render_second_person("{Subj} spilled coffee on {poss} shirt") == "You spilled coffee on your shirt"
    assert render_second_person("a memory {subj}'d been avoiding, about {refl}") \
        == "a memory you'd been avoiding, about yourself"
    assert render_second_person("{Subj} {was}n't sure {subj} know{s} {user}", user={"name": "Robin"}) \
        == "You weren't sure you know Robin"
    assert render_second_person("{Poss} pen, {poss_pron}, {obj}, {user_poss} desk") \
        == "Your pen, yours, you, their desk"
    assert render_second_person("{unknown} stays") == "{unknown} stays"
    assert not any(BARE_PRONOUN_RE.search(form) for form in SECOND_PERSON.values())


def _episode_word_pools(setting) -> dict:
    """Every line of a setting an episode's ``what`` can be made of: the rest
    are activity names, contact lines and goal or book titles."""
    return {
        "activity_chaos": list(itertools.chain.from_iterable(setting.activity_chaos.values())),
        "universal_chaos": list(setting.universal_chaos),
        "universal_chaos_effects": [e["text"] for e in setting.universal_chaos_effects],
        "serendipity": list(setting.serendipity),
        "micro_events": [e["text"] for e in setting.micro_events],
        "skill_milestones": [text for entries in setting.skill_milestones.values() for _, text in entries],
        "work_events": list(setting.work_events_positive) + list(setting.work_events_negative),
    }


@pytest.mark.parametrize("user", [{"name": "Robin"}, None], ids=["named-user", "unnamed-user"])
def test_every_line_an_episode_can_be_told_in_reads_right_addressed_to_her(user):
    """Chaos, small moments, lucky breaks, milestones and work days are kept
    in her setting's own words, addressed to her: each renders with no
    he/she, no "the user", no unfilled token, no "you" with a singular verb
    -- a hard-coded "-s" after the pronoun included (ruling T12-R4 reworded
    the two lines that had one) -- and so does every gist made of one."""
    pools = _episode_word_pools(get_setting("contemporary"))
    assert all(pools.values())
    for name, texts in pools.items():
        for raw in texts:
            rendered = render_second_person(raw, user=user)
            assert "{" not in rendered and "}" not in rendered, (name, raw)
            assert not BARE_PRONOUN_RE.search(rendered), (name, raw)
            assert not THE_USER_RE.search(rendered), (name, raw)
            assert not YOU_SINGULAR_RE.search(rendered), (name, raw)
            assert not DOUBLED_WORD_RE.search(rendered), (name, raw)
            for match in YOU_THEN_WORD_RE.finditer(rendered):
                word = match.group(1)
                assert not (word.endswith("s") and not word.endswith("ss") and word != "always"), (
                    name, raw, rendered)
            _assert_prompt_safe(_episode(what=rendered, place="cafe", emotion="annoyed").gist())


SIM_SEED = 9
SIM_DAYS = 3
MARA_CIRCLE = [
    {"name": "Ada", "relationship": "best friend", "contact_frequency": "daily"},
    {"name": "Farid", "relationship": "old friend"},
    {"name": "Shirley", "kind": "threat", "relationship": "a mother hunting her"},
]


@pytest.fixture(scope="module")
def memory_trace(tmp_path_factory):
    """Three simulated days at the scheduler's own cadence (ruling T4-R3): a
    no-profile control and a persona with people in her life."""
    personas = [
        SimPersona("control"),
        SimPersona("mara", service_kwargs={
            "definition": PersonalityDefinition(name="Mara", appearance_details={"gender": "female"},
                                                emotional_baseline={"calm": 0.4, "curious": 0.5}),
            "social_circle": [dict(entry) for entry in MARA_CIRCLE],
        }),
    ]
    return run_days(personas, days=SIM_DAYS, seed=SIM_SEED, cadence=PRODUCTION,
                    data_dir=tmp_path_factory.mktemp("memory_stream"))


def _saved_ids(svc: LifeService) -> list:
    with contextlib.closing(sqlite3.connect(svc._db_path)) as conn:
        return [row[0] for row in conn.execute("SELECT id FROM life_memory_episodes ORDER BY id")]


def test_three_simulated_days_record_episodes_of_unequal_importance(memory_trace):
    """The acceptance: a 3-day production-cadence run records episodes, and
    their importance is not one value. Every one is on disk as it is written."""
    assert memory_trace.errors == []
    for pid, svc in memory_trace.services.items():
        episodes = svc._memory.episodes
        assert len(episodes) >= 3 * 30, pid
        assert len({e.importance for e in episodes}) > 1, pid
        assert _saved_ids(svc) == [e.id for e in episodes], pid


def _felt_by_activity(svc: LifeService) -> dict:
    """(activity name, the world instant it was done at) -> the strongest
    feeling in its log entry (``activity_logs.emotions_triggered``): what she
    felt doing it."""
    with contextlib.closing(sqlite3.connect(svc._db_path)) as conn:
        rows = conn.execute("SELECT activity_name, started_at, emotions_triggered FROM activity_logs").fetchall()
    return {(name, datetime.fromisoformat(at)): max(json.loads(felt or "{}").values(), default=0.0)
            for name, at, felt in rows}


def test_in_the_simulated_days_what_she_felt_more_strongly_mattered_more(memory_trace):
    """Unequal is not enough -- a constant importance plus noise is unequal
    too. Her activities (alone, as the run has no housemates) whose strongest
    feeling was 0.2 or more are more important, on average, than those whose
    strongest was 0.1 or less -- and each of them more than any of those: in
    three days nothing is new to her yet (the stream spans less than
    NOVELTY_WINDOW_DAYS) and no one was there, so how strongly she felt it is
    all that sets these episodes' importance. What she felt is her log's:
    since Task 14 an activity is felt as she appraised how it went
    (aura_life.emotion.appraisal) -- a failure of something mild can hurt
    more than a success of something she loves pleases -- not as its
    setting's table alone says."""
    for pid, svc in memory_trace.services.items():
        felt_by = _felt_by_activity(svc)
        felt_weakly, felt_strongly = [], []
        for e in svc._memory.episodes:
            if "activity" not in e.tags or e.people:
                continue
            peak = felt_by.get((e.what, e.at))
            if peak is None:
                continue
            if peak <= 0.1:
                felt_weakly.append(e.importance)
            elif peak >= 0.2:
                felt_strongly.append(e.importance)
        assert felt_weakly and felt_strongly, pid
        assert statistics.mean(felt_strongly) > statistics.mean(felt_weakly), (
            pid, statistics.mean(felt_weakly), statistics.mean(felt_strongly))
        assert min(felt_strongly) > max(felt_weakly), (pid, max(felt_weakly), min(felt_strongly))


def test_the_days_she_lived_are_the_days_she_remembers(memory_trace):
    """Every episode is stamped on the simulated world clock, inside the run;
    what she did, small moments and her people are all there; every gist is
    fit to quote to her."""
    start = memory_trace.start
    end = start + timedelta(days=SIM_DAYS)
    for pid, svc in memory_trace.services.items():
        episodes = svc._memory.episodes
        assert all(start <= e.at <= end for e in episodes), pid
        kinds = {tag for e in episodes for tag in e.tags}
        assert {"activity", "moment"} <= kinds, (pid, kinds)
        for e in episodes:
            _assert_prompt_safe(e.gist())
        private = {activity.name for activity in svc._setting.intimate_catalogue()}
        assert not [e for e in episodes if e.what in private], pid
    mara = memory_trace.services["mara"]._memory.episodes
    assert "social" in {tag for e in mara for tag in e.tags}
    assert {p for e in mara for p in e.people} <= {"Ada", "Farid", "Shirley"}
