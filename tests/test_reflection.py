"""Reflection, nostalgia and chapters from real history (humanness program
Task 13, spec section 4.6).

Measured before this task: nostalgia was ten generic templates pinned in the
prompt ("that time we stayed up way too late", "the smell of her mom's
kitchen"), and monthly chapters recorded whatever the mood happened to be at
the moment of writing. Nothing reflected on the memory stream Task 12 gave
her.

Now: a reflection fires when the importance she has lived since her last one
sums to REFLECTION_THRESHOLD (15.0, spec 4.6) or more, and derives
deterministic beliefs -- a repeated activity with a person, a recurring
place, a mood trend -- from the window, each remembered as an episode of her
own (tags=("belief",)) with its grounding episodes reinforced (ruling
T12-R2). Nostalgia draws from a real episode at least
NOSTALGIA_MIN_EPISODE_AGE_DAYS (7) simulated days old when she has one,
falling back to the setting's ten templates otherwise. A life chapter
summarises the mean valence and dominant activities of the WHOLE period it
covers, read from her memory stream, not her mood at the instant it was
written.

Fix round 1 (review): a belief's PATTERN key (kind, discriminator) -- never
its sentence text -- already believed within BELIEF_REPEAT_COOLDOWN_DAYS (7)
simulated days is not believed again; the last reflection's world instant is
persisted explicitly, not derived from a belief episode MemoryStream's cap
could prune; an optional LLM belief is validated (a length cap, no digit, no
unfilled brace, no bare third-person pronoun, never "the user", one
sentence) before it is remembered, and takes the reflection window's mean
valence like every deterministic belief.

Sections: 1. the deterministic detectors (pure functions, no LifeService);
2. LifeService._reflect, including pattern-key dedup; 3. the optional LLM
hook (reflection_llm), including reply validation and its valence; 4.
nostalgia from real history; 5. a chapter's mood and activities read from
the window; 6. the two prompt-bound paths Task 9 found reading a nostalgia
memory_reference unrendered; 7. nine simulated days, including the real
_on_energy_tick reinforcing a surfaced nostalgic episode and the dedup
holding over the whole run.
"""

import logging
import random
import re
from datetime import datetime, timedelta

import pytest

from aura_life import hooks
from aura_life.affect.affect_system import MOOD_VALENCE_BAND
from aura_life.context.context_builder import LifeContextBuilder
from aura_life.life_service import LifeService, NOSTALGIA_MIN_EPISODE_AGE_DAYS
from aura_life.memory import (
    Episode,
    BELIEF_REPEAT_COOLDOWN_DAYS,
    INITIAL_STRENGTH,
    LLM_BELIEF_MAX_CHARS,
    MAX_BELIEFS_PER_REFLECTION,
    MIN_MOOD_SAMPLE,
    MIN_REPEAT_COUNT,
    REFLECTION_THRESHOLD,
    belief_key_from_tag,
    belief_key_tag,
    generate_beliefs,
    mean_valence,
    mood_trend,
    recurring_places,
    repeated_activity_partners,
    validate_llm_belief,
)
from aura_life.models import NostalgiaEvent
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.personas.pronoun_render import render_second_person as _render_second_person_line
from aura_life.world import WorldEnvironment

from sim_helpers import PRODUCTION, SimPersona, run_days

#: A Monday noon: every default schedule is awake, the night far off.
T0 = datetime(2026, 10, 5, 12, 0)

#: The render lint's checks (tests/test_render_lint.py, Task 6), applied to
#: belief text here since a belief is generated, never a static pool.
BARE_PRONOUN_RE = re.compile(r"\b(she|her|hers|herself|he|him|his|himself)\b", re.IGNORECASE)
DOUBLED_WORD_RE = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)
THE_USER_RE = re.compile(r"\bthe user\b", re.IGNORECASE)
YOU_SINGULAR_RE = re.compile(r"\byou (?:was|has|is|does)(?:n['’]t)?\b", re.IGNORECASE)


def _assert_belief_safe(text: str) -> None:
    """A belief sentence, fit to quote to her: no unfilled brace, no bare
    pronoun, never "the user", no doubled word, no "you" with a singular
    verb."""
    assert "{" not in text and "}" not in text, text
    assert not BARE_PRONOUN_RE.search(text), text
    assert not THE_USER_RE.search(text), text
    assert not DOUBLED_WORD_RE.search(text), text
    assert not YOU_SINGULAR_RE.search(text), text


def _ep(id, at, what="reading", place="", people=(), valence=0.0, importance=0.3,
        emotion="", tags=("activity",)) -> Episode:
    return Episode(id=id, at=at, place=place, people=people, what=what, valence=valence,
                   importance=importance, emotion=emotion, tags=tags)


class ScriptedClock:
    """A clock that moves only when told to (mirrors tests/test_memory_stream.py)."""

    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant


@pytest.fixture
def persona_clock():
    """Her local clock (the ``persona_now`` hook) on a scripted instant; the
    previous provider is put back afterwards."""
    saved = hooks.provider_for("persona_now")
    clock = ScriptedClock(T0)
    hooks.configure(persona_now=lambda timezone=None: clock.instant)
    yield clock
    hooks.configure(persona_now=saved)


def _service(tmp_path, clock, name: str = "nora", seed: int = 13, **kwargs) -> LifeService:
    svc = LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=name,
                      world_environment=WorldEnvironment(now=clock, seed=seed),
                      rng=random.Random(seed), **kwargs)
    svc._desire_system.should_do_intimate_activity = lambda *a, **k: False
    return svc


def _record(svc: LifeService, at: datetime, what: str, *, tags=("activity",), **kw) -> Episode:
    """An episode straight into her memory stream (activity=what, so it
    counts for novelty the same way a real activity would)."""
    return svc._memory.record(at=at, what=what, activity=what, tags=tags, **kw)


def _window_sum(svc: LifeService) -> float:
    """The summed importance of the CURRENT reflection window (every
    non-belief episode more recent than ``svc._last_reflection_at``, or
    every one she has with none yet) -- the same scope ``LifeService._reflect``
    itself checks against REFLECTION_THRESHOLD. Summing every non-belief
    episode ever (ignoring the anchor) would look already-crossed forever
    once one reflection has happened, and never add the filler a SECOND
    reflection in the same test needs."""
    anchor = svc._last_reflection_at
    return sum(e.importance for e in svc._memory.episodes
              if "belief" not in e.tags and (anchor is None or e.at > anchor))


def _cross_threshold(svc: LifeService, now: datetime) -> datetime:
    """Add ordinary, un-patterned filler episodes (distinct names, no
    people, neutral valence) until the current reflection window's summed
    importance reaches REFLECTION_THRESHOLD. Returns the last instant used."""
    filler_id = 0
    while _window_sum(svc) < REFLECTION_THRESHOLD:
        now = now + timedelta(hours=3)
        _record(svc, now, f"an ordinary moment {filler_id}", intensity=0.6)
        filler_id += 1
    return now


def _save_hooks() -> dict:
    return {name: hooks.provider_for(name) for name in hooks.HOOK_NAMES}


def _restore_hooks(saved: dict) -> None:
    hooks.reset()
    hooks.configure(**{name: provider for name, provider in saved.items() if provider is not None})


# ======================================================================
# 1. The deterministic detectors (pure functions)
# ======================================================================

def test_reflection_threshold_is_15_per_the_brief():
    assert REFLECTION_THRESHOLD == 15.0


def test_repeated_activity_partners_needs_min_repeat_count():
    episodes = [_ep(i, T0 + timedelta(days=i), what="climbing", people=("Ada",)) for i in range(MIN_REPEAT_COUNT - 1)]
    assert repeated_activity_partners(episodes) == []
    episodes.append(_ep(99, T0 + timedelta(days=99), what="climbing", people=("Ada",)))
    [(pair, grounds)] = repeated_activity_partners(episodes)
    assert pair == ("climbing", "Ada")
    assert len(grounds) == MIN_REPEAT_COUNT


def test_repeated_activity_partners_ignores_non_activity_and_solo_episodes():
    social = [_ep(i, T0 + timedelta(days=i), what="climbing", people=("Ada",), tags=("social",))
              for i in range(MIN_REPEAT_COUNT + 2)]
    solo = [_ep(50, T0, what="climbing", people=())]
    assert repeated_activity_partners(social + solo) == []


def test_recurring_places_needs_min_repeat_count():
    episodes = [_ep(i, T0 + timedelta(days=i), place="the range") for i in range(MIN_REPEAT_COUNT)]
    [(place, grounds)] = recurring_places(episodes)
    assert place == "the range"
    assert len(grounds) == MIN_REPEAT_COUNT


def test_mood_trend_needs_min_sample_and_a_clear_valence():
    few = [_ep(i, T0, valence=-0.9) for i in range(MIN_MOOD_SAMPLE - 1)]
    assert mood_trend(few, band=MOOD_VALENCE_BAND) is None  # too few

    neutral = [_ep(i, T0, valence=0.05) for i in range(MIN_MOOD_SAMPLE)]
    assert mood_trend(neutral, band=MOOD_VALENCE_BAND) is None  # inside the band

    down = [_ep(i, T0, valence=-0.9) for i in range(MIN_MOOD_SAMPLE)]
    assert mood_trend(down, band=MOOD_VALENCE_BAND) == "down"

    up = [_ep(i, T0, valence=0.9) for i in range(MIN_MOOD_SAMPLE)]
    assert mood_trend(up, band=MOOD_VALENCE_BAND) == "up"


def test_generate_beliefs_names_both_the_activity_and_the_person():
    episodes = [_ep(i, T0 + timedelta(days=i), what="going to the range", people=("Sam",))
                for i in range(MIN_REPEAT_COUNT + 1)]
    [(key, text, grounds)] = generate_beliefs(episodes, mood_band=MOOD_VALENCE_BAND)
    assert key == ("activity_partner", "going to the range:Sam")
    assert "Sam" in text and "the range" in text
    _assert_belief_safe(text)
    assert len(grounds) == MIN_REPEAT_COUNT + 1


def test_generate_beliefs_recurring_place_wording():
    episodes = [_ep(i, T0 + timedelta(days=i), place="the range") for i in range(MIN_REPEAT_COUNT)]
    [(key, text, grounds)] = generate_beliefs(episodes, mood_band=MOOD_VALENCE_BAND)
    assert key == ("place", "the range")
    assert "the range" in text
    _assert_belief_safe(text)
    assert len(grounds) == MIN_REPEAT_COUNT


def test_generate_beliefs_mood_trend_grounds_nothing_concrete():
    episodes = [_ep(i, T0, valence=-0.9) for i in range(MIN_MOOD_SAMPLE)]
    [(key, text, grounds)] = generate_beliefs(episodes, mood_band=MOOD_VALENCE_BAND)
    assert key == ("mood_trend", "down")
    assert "low" in text
    _assert_belief_safe(text)
    assert grounds == []  # a trend is a synthesis, not a recollection of any one episode


def test_generate_beliefs_falls_back_to_her_most_important_episode():
    episodes = [
        _ep(0, T0, what="reading", importance=0.2),
        _ep(1, T0 + timedelta(hours=1), what="a call from Mara", importance=0.9,
            emotion="warm", people=("Mara",), tags=("social",)),
    ]
    [(key, text, grounds)] = generate_beliefs(episodes, mood_band=MOOD_VALENCE_BAND)
    assert key == ("fallback", "1")
    assert grounds == [episodes[1]]
    assert episodes[1].gist() in text
    _assert_belief_safe(text)


def test_generate_beliefs_distinct_keys_for_distinct_patterns():
    """Two different (activity, person) pairs, or "up" vs "down" moods, are
    different conclusions and must not share a key."""
    partners = [_ep(i, T0 + timedelta(days=i), what="climbing", people=("Ada",))
                for i in range(MIN_REPEAT_COUNT)]
    places = [_ep(10 + i, T0 + timedelta(days=i), place="the cafe") for i in range(MIN_REPEAT_COUNT)]
    keys = [key for key, _, _ in generate_beliefs(partners + places, mood_band=MOOD_VALENCE_BAND)]
    assert len(keys) == len(set(keys)) == 2


def test_generate_beliefs_returns_nothing_for_an_empty_window():
    assert generate_beliefs([], mood_band=MOOD_VALENCE_BAND) == []


def test_generate_beliefs_caps_at_the_limit():
    episodes, eid = [], 0
    for i in range(MAX_BELIEFS_PER_REFLECTION + 1):
        for _ in range(MIN_REPEAT_COUNT):
            episodes.append(_ep(eid, T0 + timedelta(hours=eid), what=f"activity {i}", people=(f"Person{i}",)))
            eid += 1
    beliefs = generate_beliefs(episodes, mood_band=MOOD_VALENCE_BAND)
    assert len(beliefs) == MAX_BELIEFS_PER_REFLECTION


def test_belief_key_tag_round_trips():
    key = ("activity_partner", "going to the range:Sam")
    assert belief_key_from_tag(belief_key_tag(key)) == key


def test_belief_key_from_tag_ignores_every_other_tag():
    assert belief_key_from_tag("belief") is None
    assert belief_key_from_tag("activity") is None
    assert belief_key_from_tag("share:3") is None


def test_validate_llm_belief_accepts_a_good_reply():
    assert (validate_llm_belief("You seem drawn to the water lately.")
            == "You seem drawn to the water lately.")


def test_validate_llm_belief_normalises_whitespace():
    assert validate_llm_belief("  You   seem\n\ndrawn to the water  ") == "You seem drawn to the water"


@pytest.mark.parametrize("bad_reply,label", [
    ("You seem drawn to the water lately." + " and more" * 30, "too long"),
    ("You've called Sam 3 times this week.", "a digit"),
    ("You seem drawn to {something}.", "an unfilled brace"),
    ("She seems drawn to the water lately.", "a bare third-person pronoun"),
    ("Her fondness for the water is obvious.", "a bare third-person pronoun (poss.)"),
    ("The user seems to like the water.", '"the user"'),
    ("You seem drawn to the water. You should go more often.", "more than one sentence"),
    ("", "empty"),
    ("   ", "whitespace only"),
])
def test_validate_llm_belief_rejects_bad_replies(bad_reply, label):
    assert validate_llm_belief(bad_reply) is None, label


def test_validate_llm_belief_max_chars_is_the_stated_cap():
    at_cap = "a" * LLM_BELIEF_MAX_CHARS
    over_cap = "a" * (LLM_BELIEF_MAX_CHARS + 1)
    assert validate_llm_belief(at_cap) == at_cap
    assert validate_llm_belief(over_cap) is None


# ======================================================================
# 2. LifeService._reflect
# ======================================================================

def test_reflect_does_nothing_below_the_threshold(tmp_path, persona_clock):
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock)
    now = T0
    for day in range(2):
        now = T0 + timedelta(days=day, hours=1)
        _record(svc, now, f"a small thing {day}", intensity=0.2)
    assert sum(e.importance for e in svc._memory.episodes) < REFLECTION_THRESHOLD
    clock.instant = now  # _remember stamps a belief on the world clock, not this `now`
    svc._reflect(now)
    assert not [e for e in svc._memory.episodes if "belief" in e.tags]


def test_a_week_of_a_repeated_activity_with_the_same_npc_yields_a_belief_naming_both(tmp_path, persona_clock):
    """The acceptance: a simulated week with a repeated activity involving
    the same NPC yields a belief that names both."""
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock)
    now = T0
    for day in range(7):
        now = T0 + timedelta(days=day, hours=18)
        _record(svc, now, "going to the range", people=("Sam",), intensity=0.6)
    range_episodes = list(svc._memory.episodes)
    now = _cross_threshold(svc, now)
    clock.instant = now
    svc._reflect(now)

    beliefs = [e for e in svc._memory.episodes if "belief" in e.tags]
    assert beliefs
    named_both = [e for e in beliefs if "Sam" in e.what and "the range" in e.what]
    assert named_both, [e.what for e in beliefs]
    _assert_belief_safe(named_both[0].what)

    # The seven grounding episodes were reinforced (ruling T12-R2): reflection
    # that surfaces an episode reinforces it.
    reloaded = {e.id: e for e in svc._memory.episodes}
    for original in range_episodes:
        grounded = reloaded[original.id]
        assert grounded.last_recalled == now, grounded
        assert grounded.strength > INITIAL_STRENGTH, grounded


def test_a_mostly_negative_week_yields_a_low_mood_belief(tmp_path, persona_clock):
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock)
    now = T0
    filler_id = 0
    while (sum(e.importance for e in svc._memory.episodes) < REFLECTION_THRESHOLD
           or filler_id < MIN_MOOD_SAMPLE):
        now += timedelta(hours=6)
        _record(svc, now, f"a rough moment {filler_id}", intensity=0.8, valence=-0.9)
        filler_id += 1
    clock.instant = now
    svc._reflect(now)
    beliefs = [e.what for e in svc._memory.episodes if "belief" in e.tags]
    assert any("feeling low" in text for text in beliefs), beliefs


def test_reflect_resets_the_window_so_the_same_episodes_are_not_recounted(tmp_path, persona_clock):
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock)
    now = _cross_threshold(svc, T0)
    clock.instant = now
    svc._reflect(now)
    first_beliefs = [e.id for e in svc._memory.episodes if "belief" in e.tags]
    assert first_beliefs
    svc._reflect(now)  # nothing new happened -- must not reflect again on the same window
    second_beliefs = [e.id for e in svc._memory.episodes if "belief" in e.tags]
    assert second_beliefs == first_beliefs


def _reflect_on_a_repeated_place(svc: LifeService, clock: "ScriptedClock", start: datetime,
                                  place: str = "the cafe") -> datetime:
    """Cross the threshold with exactly the ``place`` pattern (>= MIN_REPEAT_COUNT
    visits) plus un-patterned filler, then reflect (with the service's own
    clock synced to ``now`` first, so the belief it may record is stamped
    correctly). Returns the instant used."""
    now = start
    for _ in range(MIN_REPEAT_COUNT):
        now += timedelta(hours=2)
        svc._memory.record(at=now, what="reading", activity="reading", place=place,
                           tags=("activity",), intensity=0.6)
    now = _cross_threshold(svc, now)
    clock.instant = now
    svc._reflect(now)
    return now


def test_reflect_does_not_repeat_a_belief_pattern_within_the_cooldown(tmp_path, persona_clock):
    """Fix round 1, Important 1: the same PATTERN (kind + place/partner/
    activity key), not just identical text, is not believed twice inside
    BELIEF_REPEAT_COOLDOWN_DAYS."""
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock)
    place_key = ("place", "the cafe")

    now = _reflect_on_a_repeated_place(svc, clock, T0)
    first = [e for e in svc._memory.episodes if belief_key_tag(place_key) in e.tags]
    assert len(first) == 1

    # Two simulated days later (inside the 7-day cooldown): the same place
    # pattern recurs. It must not be believed again.
    _reflect_on_a_repeated_place(svc, clock, now + timedelta(days=2))
    second = [e for e in svc._memory.episodes if belief_key_tag(place_key) in e.tags]
    assert len(second) == 1, "the cooldown must have blocked a second identical-pattern belief"


def test_reflect_repeats_a_belief_pattern_after_the_cooldown_expires(tmp_path, persona_clock):
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock)
    place_key = ("place", "the cafe")

    now = _reflect_on_a_repeated_place(svc, clock, T0)
    assert len([e for e in svc._memory.episodes if belief_key_tag(place_key) in e.tags]) == 1

    # BELIEF_REPEAT_COOLDOWN_DAYS (and a bit) later: the pattern is fresh again.
    later = now + timedelta(days=BELIEF_REPEAT_COOLDOWN_DAYS, hours=1)
    _reflect_on_a_repeated_place(svc, clock, later)
    assert len([e for e in svc._memory.episodes if belief_key_tag(place_key) in e.tags]) == 2


def test_reflect_records_nothing_when_the_only_pattern_is_already_believed(tmp_path, persona_clock):
    """The brief's own words: a reflection that finds nothing new records
    nothing -- but it still counts as having reflected (fix round 1,
    Minor 4: the anchor advances regardless)."""
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock)

    now = _reflect_on_a_repeated_place(svc, clock, T0)
    first_count = len([e for e in svc._memory.episodes if "belief" in e.tags])
    assert first_count >= 1

    now2 = _reflect_on_a_repeated_place(svc, clock, now + timedelta(days=2))
    second_count = len([e for e in svc._memory.episodes if "belief" in e.tags])
    assert second_count == first_count, "nothing new should have been recorded"
    assert svc._last_reflection_at == now2


def test_last_reflection_at_survives_a_save_and_reload(tmp_path, persona_clock):
    """Fix round 1, Minor 4: an explicit, persisted anchor, not one derived
    from a belief episode's own timestamp."""
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock, name="persisted")
    now = _cross_threshold(svc, T0)
    clock.instant = now
    svc._reflect(now)
    assert svc._last_reflection_at == now

    svc._save_state()

    reloaded = _service(tmp_path, ScriptedClock(now), name="persisted")
    assert reloaded._last_reflection_at is None  # not loaded until _load_state runs
    reloaded._load_state()
    assert reloaded._last_reflection_at == now


def test_last_reflection_at_round_trips_through_a_fresh_service_with_none_saved(tmp_path, persona_clock):
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock, name="never_reflected")
    svc._save_state()
    reloaded = _service(tmp_path, ScriptedClock(T0), name="never_reflected")
    reloaded._load_state()
    assert reloaded._last_reflection_at is None


# ======================================================================
# 3. The optional LLM hook (reflection_llm)
# ======================================================================

class _StubLLM:
    def __init__(self, reply):
        self.reply = reply

    def generate(self, prompt):
        return self.reply


def test_reflection_llm_defaults_off_and_never_calls_the_hook(tmp_path, persona_clock):
    saved = _save_hooks()
    called = []
    hooks.configure(get_llm_service=lambda: (called.append(True), _StubLLM("unused"))[1])
    try:
        clock = ScriptedClock(T0)
        svc = _service(tmp_path, clock)  # reflection_llm defaults False
        now = _cross_threshold(svc, T0)
        clock.instant = now
        svc._reflect(now)
    finally:
        _restore_hooks(saved)
    assert called == []
    assert not [e for e in svc._memory.episodes if "llm" in e.tags]
    assert [e for e in svc._memory.episodes if "belief" in e.tags]  # the deterministic ones still fire


def test_reflection_llm_true_adds_one_more_belief_from_a_working_hook(tmp_path, persona_clock):
    saved = _save_hooks()
    hooks.configure(get_llm_service=lambda: _StubLLM("You seem drawn to the water lately."))
    try:
        clock = ScriptedClock(T0)
        svc = _service(tmp_path, clock, reflection_llm=True)
        now = _cross_threshold(svc, T0)
        clock.instant = now
        svc._reflect(now)
    finally:
        _restore_hooks(saved)
    llm_beliefs = [e for e in svc._memory.episodes if "llm" in e.tags]
    assert len(llm_beliefs) == 1
    assert llm_beliefs[0].what == "You seem drawn to the water lately."
    assert "belief" in llm_beliefs[0].tags


def test_reflection_llm_belief_valence_is_the_window_mean_not_current_mood(tmp_path, persona_clock):
    """Fix round 1, Minor 5: the same source every deterministic belief's
    valence uses, not her mood at the moment this happens to run."""
    saved = _save_hooks()
    hooks.configure(get_llm_service=lambda: _StubLLM("You seem drawn to the water lately."))
    try:
        clock = ScriptedClock(T0)
        svc = _service(tmp_path, clock, reflection_llm=True)
        now = T0
        filler_id = 0
        while sum(e.importance for e in svc._memory.episodes) < REFLECTION_THRESHOLD:
            now += timedelta(hours=3)
            _record(svc, now, f"a rough moment {filler_id}", intensity=0.6, valence=-0.8)
            filler_id += 1
        clock.instant = now
        expected = mean_valence([e for e in svc._memory.episodes if "belief" not in e.tags])
        svc._affect.mood.valence = 0.9  # current mood: strongly positive, and must be ignored
        svc._reflect(now)
    finally:
        _restore_hooks(saved)
    llm_beliefs = [e for e in svc._memory.episodes if "llm" in e.tags]
    assert len(llm_beliefs) == 1
    assert llm_beliefs[0].valence == pytest.approx(expected)
    assert llm_beliefs[0].valence < 0  # the window's mood, not the positive current one


@pytest.mark.parametrize("bad_reply,label", [
    ("x" * (LLM_BELIEF_MAX_CHARS + 50), "too long"),
    ("You've called Sam 3 times this week.", "a digit"),
    ("You seem {drawn} to it.", "an unfilled brace"),
    ("The user seems happy about it.", '"the user"'),
    ("You went out. You liked it a lot.", "more than one sentence"),
])
def test_reflection_llm_records_nothing_from_a_bad_reply_and_logs_no_error(
    tmp_path, persona_clock, caplog, bad_reply, label,
):
    """Fix round 1, Important 2: a reply that fails validate_llm_belief is
    never remembered; the deterministic beliefs stand; nothing above
    WARNING is logged for it."""
    saved = _save_hooks()
    hooks.configure(get_llm_service=lambda: _StubLLM(bad_reply))
    try:
        clock = ScriptedClock(T0)
        svc = _service(tmp_path, clock, reflection_llm=True)
        now = _cross_threshold(svc, T0)
        clock.instant = now
        with caplog.at_level(logging.DEBUG, logger="aura_life"):
            svc._reflect(now)
    finally:
        _restore_hooks(saved)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], label
    assert not [e for e in svc._memory.episodes if "llm" in e.tags], label
    assert [e for e in svc._memory.episodes if "belief" in e.tags], label  # deterministic ones stand


def test_reflection_llm_logs_a_warning_not_only_debug_for_a_bad_reply(tmp_path, persona_clock, caplog):
    saved = _save_hooks()
    hooks.configure(get_llm_service=lambda: _StubLLM("The user seems happy about it."))
    try:
        clock = ScriptedClock(T0)
        svc = _service(tmp_path, clock, reflection_llm=True)
        now = _cross_threshold(svc, T0)
        clock.instant = now
        with caplog.at_level(logging.WARNING, logger="aura_life"):
            svc._reflect(now)
    finally:
        _restore_hooks(saved)
    assert [r for r in caplog.records if r.levelno == logging.WARNING], "a validation failure should log a WARNING"


def test_reflection_llm_true_with_a_raising_hook_keeps_the_deterministic_beliefs_no_error(
    tmp_path, persona_clock, caplog,
):
    saved = _save_hooks()

    def _raise():
        raise RuntimeError("the model is down")

    hooks.configure(get_llm_service=_raise)
    try:
        clock = ScriptedClock(T0)
        svc = _service(tmp_path, clock, reflection_llm=True)
        now = _cross_threshold(svc, T0)
        clock.instant = now
        with caplog.at_level(logging.DEBUG, logger="aura_life"):
            svc._reflect(now)
    finally:
        _restore_hooks(saved)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert [e for e in svc._memory.episodes if "belief" in e.tags]
    assert not [e for e in svc._memory.episodes if "llm" in e.tags]


def test_reflection_llm_true_with_no_hook_registered_keeps_the_deterministic_beliefs_no_error(
    tmp_path, persona_clock, caplog,
):
    saved = _save_hooks()
    hooks.reset()
    hooks.configure(**{name: p for name, p in saved.items() if p is not None and name != "get_llm_service"})
    try:
        assert not hooks.is_configured("get_llm_service")
        clock = ScriptedClock(T0)
        svc = _service(tmp_path, clock, reflection_llm=True)
        now = _cross_threshold(svc, T0)
        clock.instant = now
        with caplog.at_level(logging.DEBUG, logger="aura_life"):
            svc._reflect(now)
    finally:
        _restore_hooks(saved)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert [e for e in svc._memory.episodes if "belief" in e.tags]


# ======================================================================
# 4. Nostalgia from real history
# ======================================================================

def test_real_nostalgia_episode_is_none_before_any_episode_is_old_enough(tmp_path, persona_clock):
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock)
    _record(svc, T0, "reading")
    almost = T0 + timedelta(days=NOSTALGIA_MIN_EPISODE_AGE_DAYS) - timedelta(hours=1)
    assert svc._real_nostalgia_episode(almost) is None


def test_real_nostalgia_episode_picks_one_old_enough_without_reinforcing_it(tmp_path, persona_clock):
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock)
    old = _record(svc, T0, "a quiet morning")
    _record(svc, T0 + timedelta(days=NOSTALGIA_MIN_EPISODE_AGE_DAYS - 1), "yesterday, basically")
    now = T0 + timedelta(days=NOSTALGIA_MIN_EPISODE_AGE_DAYS, hours=1)
    chosen = svc._real_nostalgia_episode(now)
    assert chosen.id == old.id
    assert chosen.last_recalled is None  # picking alone does not reinforce


def test_real_nostalgia_episode_excludes_belief_episodes(tmp_path, persona_clock):
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock)
    svc._memory.record(at=T0, what="You've been reading a lot lately.", tags=("belief",))
    now = T0 + timedelta(days=NOSTALGIA_MIN_EPISODE_AGE_DAYS + 1)
    assert svc._real_nostalgia_episode(now) is None


def test_the_tick_pattern_swaps_a_template_for_a_real_gist_and_reinforces_it(tmp_path, persona_clock):
    """Mirrors exactly what `_on_energy_tick` does with `_real_nostalgia_episode`'s
    result and a `NostalgiaEvent`, without needing the whole tick."""
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock)
    old = _record(svc, T0, "a swim at dawn", place="the lake")
    now = T0 + timedelta(days=NOSTALGIA_MIN_EPISODE_AGE_DAYS + 1)
    event = NostalgiaEvent(trigger="season", memory_reference="{poss} mom's kitchen", intensity=0.5)

    remembered = svc._real_nostalgia_episode(now)
    if remembered is not None:
        event.memory_reference = remembered.gist()
        svc._memory.reinforce([remembered], now=now)

    assert event.memory_reference == old.gist()
    assert "{" not in event.memory_reference
    assert svc._memory.get(old.id).last_recalled == now


# ======================================================================
# 5. A chapter's mood and activities, read from the window
# ======================================================================

def test_chapter_window_stats_reads_mood_and_activities_from_the_window_not_the_instant(tmp_path, persona_clock):
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock)
    period_start = T0
    # Before the window: strongly positive -- must not leak into the chapter.
    _record(svc, T0 - timedelta(days=2), "a wonderful morning", valence=0.9, intensity=0.9)
    now = period_start
    for day in range(6):
        now = period_start + timedelta(days=day, hours=9)
        _record(svc, now, "grinding through chores", valence=-0.7, intensity=0.6)
    svc._affect.mood.arousal = 0.1  # quiet, so an unpleasant week reads as "low" specifically

    label, activity_counts = svc._chapter_window_stats(period_start, now)

    assert label == "low"
    assert activity_counts.get("grinding through chores") == 6
    assert "a wonderful morning" not in activity_counts


def test_a_chapter_over_that_negative_window_reads_negative(tmp_path, persona_clock):
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock)
    period_start = T0
    now = period_start
    for day in range(6):
        now = period_start + timedelta(days=day, hours=9)
        _record(svc, now, "grinding through chores", valence=-0.7, intensity=0.6)
    svc._affect.mood.arousal = 0.1

    label, activity_counts = svc._chapter_window_stats(period_start, now)
    chapter = svc._continuity.monthly_tick(
        activity_summary=activity_counts, dominant_mood=label, avg_energy=0.5,
        goals_completed=[], goals_abandoned=[], identity_shifts=[], now=now,
    )
    assert chapter is not None
    assert "heavy" in chapter.summary.lower()


def test_chapter_window_stats_is_neutral_with_no_episodes_in_the_window(tmp_path, persona_clock):
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock)
    label, activity_counts = svc._chapter_window_stats(T0, T0 + timedelta(hours=1))
    assert label in ("flat", "neutral")
    assert activity_counts == {}


# ======================================================================
# 6. The two prompt-bound paths Task 9 found reading a nostalgia
#    memory_reference unrendered.
# ======================================================================

class _FollowUpStub:
    def __init__(self):
        self.calls = []

    def create_trigger(self, **kwargs):
        self.calls.append(kwargs)


def test_life_trigger_nostalgia_hint_renders_pronoun_tokens(tmp_path, persona_clock):
    clock = ScriptedClock(T0)
    svc = _service(tmp_path, clock, user_info={"name": "Robin"})
    fm = _FollowUpStub()
    svc._follow_up_provider = lambda persona_id: fm
    svc._prev_loneliness = 1.0  # neutralize the loneliness_spike candidate
    svc._memory_time._nostalgia_log.append(NostalgiaEvent(
        trigger="smell", memory_reference="the smell of {poss} mom's kitchen on a Sunday",
        intensity=0.6, timestamp=T0,
    ))
    # Only which candidate is *chosen* is random; whether the nostalgia one
    # renders right is not, so make it the one chosen when it is a candidate.
    original_choices = svc._service_rng.choices

    def _prefer_nostalgia(population, weights=None, k=1):
        for candidate in population:
            if candidate[0] == "nostalgia":
                return [candidate]
        return original_choices(population, weights=weights, k=k)

    svc._service_rng.choices = _prefer_nostalgia

    svc._evaluate_life_triggers()

    assert len(fm.calls) == 1
    call = fm.calls[0]
    assert call["trigger_type"] == "NOSTALGIA"
    for text in (call["topic"], call["prompt_hint"]):
        assert "{" not in text and "}" not in text, text
        assert not BARE_PRONOUN_RE.search(text), text
    assert "your mom's kitchen" in call["prompt_hint"]


def test_context_builder_memory_time_section_renders_pronoun_and_user_tokens():
    class _StubMemoryTime:
        def export_state(self):
            return {"recent_nostalgia": {
                "trigger": "smell",
                "memory": "{poss} mom's kitchen, back when {user} would visit",
            }}

    class _StubLifeService:
        """Just enough of LifeService for `LifeContextBuilder._render_you`:
        the second-person render, with a named user on record."""

        def _addressed_to_her(self, text: str) -> str:
            return _render_second_person_line(text, user={"name": "Robin"})

    named = LifeContextBuilder(
        world=None, energy=None, activity_engine=None, goal_engine=None,
        memory_time_system=_StubMemoryTime(),
        life_service=_StubLifeService(),
    )
    section = named._build_memory_time_section()
    assert "{" not in section and "}" not in section
    assert not BARE_PRONOUN_RE.search(section)
    assert "your mom's kitchen" in section
    assert "Robin" in section

    unnamed = LifeContextBuilder(
        world=None, energy=None, activity_engine=None, goal_engine=None,
        memory_time_system=_StubMemoryTime(),
    )
    section = unnamed._build_memory_time_section()
    assert "{" not in section and "}" not in section
    assert not BARE_PRONOUN_RE.search(section)
    assert not THE_USER_RE.search(section)
    assert "your mom's kitchen" in section


# ======================================================================
# 7. Nine simulated days
# ======================================================================

REFLECTION_SIM_SEED = 17
REFLECTION_SIM_DAYS = 9


@pytest.fixture(scope="module")
def reflection_trace(tmp_path_factory):
    """Nine simulated days at the scheduler's own cadence (ruling T4-R3):
    long enough that by the end some episodes are more than
    NOSTALGIA_MIN_EPISODE_AGE_DAYS (7) simulated days old, so nostalgia has
    a real memory to quote instead of the setting's ten templates."""
    personas = [
        SimPersona("mara", service_kwargs={
            "definition": PersonalityDefinition(name="Mara", appearance_details={"gender": "female"},
                                                emotional_baseline={"calm": 0.4, "curious": 0.5}),
            "social_circle": [{"name": "Ada", "relationship": "best friend", "contact_frequency": "daily"}],
        }),
    ]
    return run_days(personas, days=REFLECTION_SIM_DAYS, seed=REFLECTION_SIM_SEED, cadence=PRODUCTION,
                    data_dir=tmp_path_factory.mktemp("reflection"))


def test_the_nine_simulated_days_run_clean(reflection_trace):
    assert reflection_trace.errors == []


def test_after_eight_simulated_days_nostalgia_can_quote_a_real_episodes_gist(reflection_trace):
    svc = reflection_trace.services["mara"]
    nostalgia_log = svc._memory_time._nostalgia_log
    assert nostalgia_log, "nine days should trigger nostalgia at least once"
    gists = {e.gist() for e in svc._memory.episodes}
    quoted_real = [n for n in nostalgia_log if n.memory_reference in gists]
    assert quoted_real, [n.memory_reference for n in nostalgia_log]
    cutoff = reflection_trace.start + timedelta(days=NOSTALGIA_MIN_EPISODE_AGE_DAYS)
    assert all(n.timestamp >= cutoff for n in quoted_real)


def test_reflection_fires_organically_over_nine_simulated_days(reflection_trace):
    svc = reflection_trace.services["mara"]
    assert [e for e in svc._memory.episodes if "belief" in e.tags]


def test_reflection_llm_stayed_off_through_the_whole_run(reflection_trace):
    """`reflection_llm` was never passed to this persona, so it defaults to
    False: no belief in the run is tagged "llm"."""
    svc = reflection_trace.services["mara"]
    assert not [e for e in svc._memory.episodes if "llm" in e.tags]


def test_nostalgias_real_episode_is_reinforced_by_the_real_tick(reflection_trace):
    """Fix round 1, Important 3: drives the real `_on_energy_tick` (via the
    nine-day trace, not a hand-rolled mirror of it) and fails if
    `self._memory.reinforce([remembered], now=now)` were removed from it.

    Checks that SOME episode sharing the quoted gist has
    `last_recalled == n.timestamp` -- the exact instant the nostalgia event
    itself fired -- rather than merely "is not None": reflection also
    reinforces episodes (its own grounding episodes), so an episode
    nostalgia happens to quote could otherwise show a *stale*
    `last_recalled` from a reflection that reinforced it at a different
    instant and still pass a looser check even with nostalgia's own
    reinforce call removed. Grouped by gist, not a single dict keyed by it,
    because two distinct episodes (different days) can share one gist
    verbatim ("Going for a walk out on the street, feeling peaceful." on
    more than one day) -- a plain `{gist: episode}` dict silently keeps only
    one and can check the wrong one. Verified against the real code twice:
    removing `reinforce(...)` made this fail; restoring it and fixing the
    first version's `{gist: episode}` collision (it can pick a DIFFERENT
    episode than the one nostalgia actually reinforced when two share a
    gist) made it pass again.

    Checked against each gist's LATEST quote (Task 15): nostalgia can quote
    the same episode twice -- the run after Task 15's stressors quotes
    "Creating a playlist at home, feeling frustrated." (episode 12) on the
    12th at 18:40 and again on the 14th at 08:40 -- and the second recall
    moves its `last_recalled` on, so the first quote's instant is no
    longer on any episode although both were reinforced."""
    svc = reflection_trace.services["mara"]
    episodes_by_gist = {}
    for episode in svc._memory.episodes:
        episodes_by_gist.setdefault(episode.gist(), []).append(episode)
    quoted_real = [n for n in svc._memory_time._nostalgia_log if n.memory_reference in episodes_by_gist]
    assert quoted_real, "the fixture must produce at least one real-episode nostalgia quote"
    latest = {}
    for n in quoted_real:
        if n.memory_reference not in latest or n.timestamp > latest[n.memory_reference]:
            latest[n.memory_reference] = n.timestamp
    for gist, quoted_at in latest.items():
        candidates = episodes_by_gist[gist]
        assert any(e.last_recalled == quoted_at for e in candidates), (gist, quoted_at, candidates)
        assert any(e.strength > INITIAL_STRENGTH for e in candidates), (gist, candidates)


def test_no_belief_pattern_key_repeats_within_seven_days(reflection_trace):
    """Fix round 1, Important 1, the review's own test: over the whole
    nine-day run, no belief pattern key recurs inside
    BELIEF_REPEAT_COOLDOWN_DAYS of an earlier belief with the same key."""
    svc = reflection_trace.services["mara"]
    beliefs = sorted((e for e in svc._memory.episodes if "belief" in e.tags), key=lambda e: e.at)
    seen_at: dict = {}
    for episode in beliefs:
        for tag in episode.tags:
            key = belief_key_from_tag(tag)
            if key is None:
                continue
            for prior_at in seen_at.get(key, []):
                assert (episode.at - prior_at) >= timedelta(days=BELIEF_REPEAT_COOLDOWN_DAYS), (
                    key, prior_at, episode.at)
            seen_at.setdefault(key, []).append(episode.at)


def test_beliefs_over_nine_days_cover_more_than_one_kind_or_key(reflection_trace):
    """Fix round 1, Important 1, the review's own test."""
    svc = reflection_trace.services["mara"]
    keys = set()
    for episode in svc._memory.episodes:
        if "belief" not in episode.tags:
            continue
        for tag in episode.tags:
            key = belief_key_from_tag(tag)
            if key is not None:
                keys.add(key)
    assert len(keys) > 1, keys
