"""Mood that can go down, and one emotion vocabulary.

Measured before this change (``docs/analyses/aura-life-humanness_2026-09-25.html``,
section 2): every persona's mood read "content" on 100% of ticks at ~0.98
intensity. Mood was one valence axis fed only by the activities' fixed emotions
(+7.30 positive weight, 0.00 negative across the catalogue); only 13 of the
names the library emits were in ``AffectSystem``'s positive/negative sets, the
feelings wheel sent every name it did not list to "happy" (so "discouraged",
"drained" and "restless" counted as happy), need shortfalls never touched mood,
and a negative ``emotional_baseline`` was ignored.

Now (``aura_life.emotion.vocabulary``, ``aura_life.affect.affect_system``):

* one vocabulary gives every emotion name the library emits a (valence,
  arousal); a name it does not know is neutral, never "happy", and the feelings
  wheel places names it does not list by that vocabulary;
* mood is a (valence, arousal) point pulled back to the persona's set-point
  (her ``emotional_baseline``, negative entries included) with half-lives in
  world hours, moved toward each emotion's point by emotion events and pulled
  down by need shortfalls, goal failure and bad work days;
* ``LifeService`` decays a host's ``EmotionEngine`` on the world clock and says
  so (``LifeService.decays_emotion_engine``).

Sections: 1. the vocabulary; 2. the mood model on ``AffectSystem``; 3. what
``LifeService`` feeds it; 4. three simulated days.
"""

import ast
import logging
import pathlib
from datetime import datetime, timedelta

import pytest

import aura_life
from aura_life.affect import affect_system as affect_module
from aura_life.affect.affect_system import (
    DEFAULT_TICK_HOURS,
    MOOD_AROUSAL_HALF_LIFE_HOURS,
    MOOD_LABELS,
    MOOD_VALENCE_HALF_LIFE_HOURS,
    AffectSystem,
    mood_intensity,
    mood_label,
)
from aura_life.emotion import text_emotion_analyzer
from aura_life.emotion import vocabulary
from aura_life.emotion.feelings_wheel import CORE_EMOTIONS, FeelingsWheel
from aura_life.models import MoodState

SRC = pathlib.Path(aura_life.__file__).parent

# ======================================================================
# 1. The vocabulary
# ======================================================================

#: Names (of keyword arguments, dict keys, variables and attributes) whose
#: value is an emotion name or a table of them. Any name ending in "_emotion"
#: or "_emotions", in any case, counts too (_is_slot).
EMOTION_SLOTS = {"emotion", "emotions", "emotion_effects", "emotional_impact", "feeling"}
#: Calls whose first argument is an emotion name.
EMITTING_CALLS = {"on_emotion_event", "add_emotion", "_create_baseline"}
#: Methods that put names into a slot's collection: dominant_emotions.append("growth").
COLLECTING_METHODS = {"append", "add", "extend", "insert", "update"}

#: Names the scan finds that are not emotions, and why: they are never felt --
#: nothing feeds them to mood or to an EmotionEngine -- so they need no point
#: in the vocabulary.
NOT_EMOTIONS = {
    # ContinuitySystem's first life chapter records it as that chapter's
    # dominant_emotions: the theme of where her story starts.
    "origin": "a life chapter's theme, not a feeling",
    # ContinuitySystem adds it to a month's dominant_emotions when her
    # identity shifted: a theme of the chapter, not something she feels.
    "growth": "a life chapter's theme, not a feeling",
    # FinanceSystem's word for how money stands, which the context builder
    # compares its local `feeling` against: a state of her finances.
    "tight": "how her money stands, not a feeling",
    "flush": "how her money stands, not a feeling",
}


def _is_slot(name) -> bool:
    lowered = str(name).lower()
    return lowered in EMOTION_SLOTS or lowered.endswith(("_emotion", "_emotions"))


def _slot_name(node):
    """The name a variable or attribute is known by, for _is_slot."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _names_in(node) -> set:
    """The emotion names a literal carries: a string; a dict's string keys --
    or, for a table of dicts ({text: {emotion: i}}), the inner dicts' keys; a
    collection of those; or any arm of a conditional or ``or``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Dict):
        inner = [v for v in node.values if isinstance(v, ast.Dict)]
        if inner:
            return set().union(*(_names_in(v) for v in inner))
        return {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return set().union(*(_names_in(e) for e in node.elts)) if node.elts else set()
    if isinstance(node, ast.IfExp):
        return _names_in(node.body) | _names_in(node.orelse)
    if isinstance(node, ast.BoolOp):
        return set().union(*(_names_in(v) for v in node.values))
    return set()


class _EmittedNames(ast.NodeVisitor):
    """Every literal emotion name in one module's source, by where it sits."""

    def __init__(self):
        self.names = set()

    def _add(self, names):
        self.names |= {n for n in names if n}

    def visit_Call(self, node):
        fn = node.func
        called = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if called in EMITTING_CALLS and node.args:
            self._add(_names_in(node.args[0]))
        # dream.get("emotion", "strange"): the default is a name too.
        if called == "get" and len(node.args) >= 2 and _is_slot(node.args[0].value if isinstance(node.args[0], ast.Constant) else ""):
            self._add(_names_in(node.args[1]))
        # dominant_emotions.append("growth"), emotions.update({...})
        if (called in COLLECTING_METHODS and isinstance(fn, ast.Attribute)
                and _is_slot(_slot_name(fn.value) or "")):
            for arg in node.args:
                self._add(_names_in(arg))
        for kw in node.keywords:
            if kw.arg and _is_slot(kw.arg):
                self._add(_names_in(kw.value))
        self.generic_visit(node)

    def visit_Dict(self, node):
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str) and _is_slot(key.value):
                self._add(_names_in(value))
        self.generic_visit(node)

    def _target(self, target, value):
        # A variable named as a slot (money's `self._state.feeling = "tight"`
        # is an attribute, not a variable, and is not an emotion).
        if isinstance(target, ast.Name) and _is_slot(target.id):
            self._add(_names_in(value))
        # emotions["lonely"] = 0.2
        elif isinstance(target, ast.Subscript) and _is_slot(_slot_name(target.value) or ""):
            self._add(_names_in(target.slice))

    def visit_Assign(self, node):
        for target in node.targets:
            self._target(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self._target(node.target, node.value)
        self.generic_visit(node)

    def visit_Compare(self, node):
        # ant.feeling == "dreading"
        if _is_slot(_slot_name(node.left) or ""):
            for comparator in node.comparators:
                self._add(_names_in(comparator))
        self.generic_visit(node)


def _scan(source: str) -> set:
    visitor = _EmittedNames()
    visitor.visit(ast.parse(source))
    return visitor.names


def emitted_emotion_names() -> set:
    """Every emotion name the library emits: the literals in its source (see
    :class:`_EmittedNames`), the text analyzer's labels, the feelings wheel,
    and the mood labels (``LifeService`` records a strong mood as a life event
    whose emotion is the label)."""
    names = set()
    for path in SRC.rglob("*.py"):
        names |= _scan(path.read_text(encoding="utf-8"))
    for table in (text_emotion_analyzer.EMOTION_KEYWORDS, text_emotion_analyzer.EMOTION_PHRASES):
        names |= {emotion for emotion, _intensity in table.values()}
    names |= FeelingsWheel.get_all_emotions()
    names |= set(MOOD_LABELS)
    return {n.strip().lower() for n in names}


@pytest.mark.parametrize("source", [
    'svc.on_emotion_event("zzz", 0.3)',
    'engine.add_emotion("zzz", 0.3)',
    'record(emotional_impact={"zzz": 0.3})',
    'Activity(emotion_effects={"zzz": 0.1})',
    'GoalEvent("x", "y", emotions={"zzz": 0.2})',
    'Chapter(dominant_emotions=["zzz"])',
    'Chapter(Dominant_Emotions=["zzz"])',
    'EVENTS = [{"text": "t", "emotion": {"zzz": 0.1}}]',
    'EFFECTS = [{"text": "t", "emotions": {"zzz": 0.1}}]',
    'emotions = {"zzz": 0.2}',
    'emotions["zzz"] = 0.2',
    'residue_emotion = "zzz"',
    'feeling = "zzz" if ok else "yyy"',
    'sticky_emotions = ["zzz", "yyy"]',
    'CHAOS_EMOTIONS = {"burned something": {"zzz": 0.05}}',
    'GOAL_COMPLETION_EMOTIONS = {"zzz": 0.4}',
    'HIGH_AROUSAL_EMOTIONS = {"zzz", "yyy"}',
    'dominant_emotions.append("zzz")',
    'self._x.dominant_emotions.append("zzz")',
    'emotions.update({"zzz": 0.1})',
    'dream.get("emotion", "zzz")',
    'if ant.feeling == "zzz": pass',
])
def test_the_scanner_reads_each_way_a_name_is_written(source):
    assert "zzz" in _scan(source)


@pytest.mark.parametrize("source, found", [
    ('self._state.feeling = "tight"', set()),                       # an attribute: money's state
    ('CHAOS_EMOTIONS = {"burned something": {"zzz": 0.05}}', {"zzz"}),  # the event text is not a name
    ('MAX_CONCURRENT_EMOTIONS = 6', set()),
    ('label = "zzz"', set()),
    ('names.append("zzz")', set()),
])
def test_the_scanner_does_not_read_what_is_not_an_emotion(source, found):
    assert _scan(source) == found


def test_the_scan_sees_every_way_the_library_emits_a_name():
    """The scan below is only as good as what it finds: one name from each
    place an emotion name is written, so a scan that silently stopped seeing
    one kind of literal fails here rather than passing vacuously."""
    names = emitted_emotion_names()
    assert len(names) > 150
    for name in (
        "rested",        # activity catalogue: emotion_effects=
        "ecstasy",       # intimate activities: emotion_effects=
        "amused",        # MICRO_EVENTS: {"emotion": {...}}
        "drained",       # CHAOS_EMOTIONS table
        "unsettled",     # UNIVERSAL_CHAOS_EFFECTS: {"emotions": {...}}
        "discouraged",   # goal events: emotions=
        "resigned",      # a local emotions = {...}
        "lonely",        # emotions["lonely"] = ...
        "uneasy",        # residue_emotion = "uneasy"
        "dreading",      # ant.feeling == "dreading"
        # ("strange", the dream residue's .get default, went with Task 17: a
        # DREAM_SHARE is made of a dream episode, never the residue -- ruling
        # T17-R3; the .get rule stays covered by the scanner's own case.)
        "nostalgic",    # on_emotion_event("nostalgic", ...)
        "trusting",      # EmotionEngine's OCEAN baseline: _create_baseline(...)
        "loving",        # text analyzer labels
        "let_down",      # the feelings wheel
        "irritable",     # the mood labels
        "origin",        # dominant_emotions=["origin"]
        "exhaustion",    # dominant_emotions.append("exhaustion")
    ):
        assert name in names, name


def test_every_emotion_name_the_library_emits_has_a_vocabulary_entry():
    missing = sorted(n for n in emitted_emotion_names()
                     if not vocabulary.is_known(n) and n not in NOT_EMOTIONS)
    assert missing == []


def test_the_names_left_out_of_the_vocabulary_are_really_emitted_and_really_absent():
    """The exclusion list cannot go stale: each entry is still something the
    scan finds, and still has no point in the vocabulary."""
    names = emitted_emotion_names()
    for name in NOT_EMOTIONS:
        assert name in names, name
        assert not vocabulary.is_known(name), name


def test_every_entry_is_a_valence_and_an_arousal_in_range():
    for name, (valence, arousal) in vocabulary.EMOTION_VOCABULARY.items():
        assert -1.0 <= valence <= 1.0, name
        assert 0.0 <= arousal <= 1.0, name
        assert name == name.strip().lower(), name


@pytest.mark.parametrize("name", ["discouraged", "drained", "restless"])
def test_names_that_counted_as_happy_now_read_negative(name):
    valence, _arousal = vocabulary.valence_arousal(name)
    assert valence < 0.0


def test_the_vocabulary_orders_what_it_knows():
    """Spot checks that a scrambled table would fail."""
    va = vocabulary.valence_arousal
    assert va("joyful")[0] > va("content")[0] > 0 > va("sad")[0] > va("despair")[0]
    assert va("excited")[1] > va("content")[1] > va("sleepy")[1]
    assert va("anxious")[1] > va("sad")[1]


def test_an_unknown_name_is_neutral_and_logged_at_debug(caplog):
    with caplog.at_level(logging.DEBUG, logger="aura_life.emotion.vocabulary"):
        assert vocabulary.valence_arousal("glorptastic") == vocabulary.NEUTRAL_POINT == (0.0, 0.3)
    assert vocabulary.is_known("glorptastic") is False
    assert any("glorptastic" in r.getMessage() and r.levelno == logging.DEBUG for r in caplog.records)


def test_lookup_ignores_case_surrounding_space_and_word_spacing():
    assert vocabulary.valence_arousal("  Discouraged ") == vocabulary.valence_arousal("discouraged")
    assert vocabulary.valence_arousal("let down") == vocabulary.valence_arousal("let_down")


# ---- The feelings wheel's fallback ------------------------------------

def test_the_wheel_places_a_name_it_does_not_list_by_the_vocabulary():
    assert FeelingsWheel.get_core_emotion("discouraged") == "sad"
    for name in ("discouraged", "drained", "restless", "uneasy", "resigned", "wistful"):
        assert FeelingsWheel.get_core_emotion(name) != "happy", name
    for name in ("delighted", "grateful", "relieved", "cozy"):
        assert FeelingsWheel.get_core_emotion(name) == "happy", name


def test_the_wheel_never_sends_an_unknown_name_to_happy():
    assert FeelingsWheel.get_core_emotion("glorptastic") != "happy"


def test_the_wheel_s_family_cache_is_built_whole_or_not_at_all(monkeypatch):
    """A first call that fails part-way through the build must not leave a
    half-built cache for the next caller (or a concurrent one) to trust."""
    monkeypatch.setattr(FeelingsWheel, "_family_centroids", {})
    real = vocabulary.valence_arousal
    calls = []

    def flaky(name):
        calls.append(name)
        if len(calls) == 40:
            raise RuntimeError("interrupted mid-build")
        return real(name)

    monkeypatch.setattr(vocabulary, "valence_arousal", flaky)
    with pytest.raises(RuntimeError):
        FeelingsWheel.get_core_emotion("discouraged")
    assert FeelingsWheel._family_centroids == {}
    monkeypatch.setattr(vocabulary, "valence_arousal", real)
    assert FeelingsWheel.get_core_emotion("discouraged") == "sad"
    assert set(FeelingsWheel._family_centroids) == set(CORE_EMOTIONS)


def test_the_wheel_keeps_the_names_it_lists():
    assert FeelingsWheel.get_core_emotion("content") == "happy"
    assert FeelingsWheel.get_core_emotion("lonely") == "sad"
    assert FeelingsWheel.get_core_emotion("annoyed") == "angry"
    assert FeelingsWheel.get_core_emotion("tired") == "bad"
    assert FeelingsWheel.get_core_emotion("fearful") == "fearful"


# ======================================================================
# 2. The mood model on AffectSystem
# ======================================================================

#: Weather and season with no mood push of their own
#: (WEATHER_MOOD_MAP["snowy"] and SEASON_MOOD_MAP["autumn"] are 0.0).
STILL = dict(weather="snowy", season="autumn")
NO_SOCIAL = {"recent_events": []}


def _body(hunger=0.0, sleep_pressure=0.0, illness=0.0, hours_awake=8.0, asleep=False):
    return {"hunger": hunger, "hours_awake": hours_awake,
            "sleep_pressure": sleep_pressure, "illness": illness, "asleep": asleep}


def _live(affect, hours, step=0.25, body=None, loneliness=None, stress=None):
    """Tick ``affect`` through ``hours`` of world time in ``step``-hour ticks,
    holding loneliness and stress where given (both drift by themselves)."""
    for _ in range(int(round(hours / step))):
        if loneliness is not None:
            affect.loneliness.level = loneliness
        if stress is not None:
            affect.stress.level = stress
        affect.tick(body_state=body or _body(), social_state=NO_SOCIAL, hours=step, **STILL)


def _lift(affect, times=20, emotion="joyful"):
    for _ in range(times):
        affect.on_emotion_event(emotion, 1.0)


def _at(valence, arousal, **kwargs):
    """An AffectSystem whose mood sits at (valence, arousal), through the
    public load path."""
    return AffectSystem.from_dict({"mood_valence": valence, "mood_arousal": arousal}, **kwargs)


# ---- Labels and intensity ---------------------------------------------

def test_the_labels_include_the_eight_the_brief_names():
    assert {"content", "happy", "calm", "restless", "irritable", "anxious", "low", "flat"} <= set(MOOD_LABELS)


@pytest.mark.parametrize("valence, arousal, label", [
    (0.5, 0.35, "content"), (0.6, 0.75, "happy"), (0.4, 0.1, "calm"),
    (0.0, 0.8, "restless"), (0.0, 0.35, "neutral"), (0.0, 0.1, "flat"),
    (-0.5, 0.4, "irritable"), (-0.5, 0.8, "anxious"), (-0.5, 0.1, "low"),
])
def test_the_label_is_read_from_the_pair(valence, arousal, label):
    assert mood_label(valence, arousal) == label


@pytest.mark.parametrize("valence, arousal, label", [
    (-0.5, 0.29, "low"), (-0.5, 0.3, "low"), (-0.5, 0.31, "irritable"), (-0.5, 0.54, "irritable"),
])
def test_unpleasant_and_no_more_aroused_than_rest_reads_low(valence, arousal, label):
    """An unpleasant mood at or below neutral arousal is low, not irritable:
    irritable needs arousal raised above rest."""
    assert mood_label(valence, arousal) == label


@pytest.mark.parametrize("baseline", [{"sad": 0.6}, {"grief": 0.9}, {"lonely": 0.8}])
def test_a_sad_grieving_or_lonely_baseline_reads_low(baseline):
    affect = AffectSystem(emotional_baseline=baseline)
    assert affect.setpoint[0] <= -affect_module.MOOD_VALENCE_BAND
    assert affect.mood.current_mood == "low"


def test_loneliness_held_for_a_day_reads_low_and_quiets_her():
    lonely, twin = AffectSystem(), AffectSystem()
    _live(lonely, 24, loneliness=0.9, stress=0.0)
    _live(twin, 24, loneliness=0.0, stress=0.0)
    assert lonely.mood.current_mood == "low"
    assert lonely.mood.arousal < twin.mood.arousal
    assert affect_module.NEED_AROUSAL_PULLS["loneliness"] == pytest.approx(
        vocabulary.valence_arousal("lonely")[1] - vocabulary.NEUTRAL_POINT[1])


@pytest.mark.parametrize("emotion", ["frustrated", "angry"])
def test_a_frustrated_or_angry_spike_reads_irritable(emotion):
    """Hit by it until her mood first turns unpleasant, she reads irritable."""
    affect = AffectSystem()
    for _ in range(200):
        affect.on_emotion_event(emotion, 0.5)
        if affect.mood.current_mood != "neutral":
            break
    assert affect.mood.current_mood == "irritable"


def test_each_label_word_sits_in_its_own_region_of_the_vocabulary():
    for label in MOOD_LABELS:
        assert mood_label(*vocabulary.valence_arousal(label)) == label, label


def test_intensity_is_zero_at_the_neutral_point_and_grows_away_from_it():
    assert mood_intensity(*vocabulary.NEUTRAL_POINT) == 0.0
    assert mood_intensity(-0.6, vocabulary.NEUTRAL_POINT[1]) == pytest.approx(0.6)
    assert mood_intensity(0.2, 0.3) < mood_intensity(0.7, 0.3)
    assert 0.0 < mood_intensity(0.0, 0.9) <= 1.0
    # Sleepy is not a strong mood: arousal below neutral counts on the same
    # scale as above it, so an equal distance either side reads the same, and
    # the quietest mood is milder than the most keyed-up.
    assert mood_intensity(0.0, 0.0) == pytest.approx(mood_intensity(0.0, 0.6))
    assert mood_intensity(0.0, 0.0) < mood_intensity(0.0, 1.0)


# ---- The set-point ----------------------------------------------------

def test_with_no_baseline_the_setpoint_is_the_neutral_point():
    affect = AffectSystem()
    assert affect.setpoint == vocabulary.NEUTRAL_POINT
    assert (affect.mood.valence, affect.mood.arousal) == vocabulary.NEUTRAL_POINT
    assert affect.mood.current_mood == "neutral"
    assert affect.mood.intensity == 0.0
    assert (MoodState().valence, MoodState().arousal) == vocabulary.NEUTRAL_POINT


def test_a_negative_baseline_gives_a_setpoint_below_zero():
    affect = AffectSystem(emotional_baseline={"sad": 0.6, "anxious": 0.4})
    assert affect.setpoint[0] < 0.0
    # She starts there, and it reads as a negative mood.
    assert affect.mood.valence == pytest.approx(affect.setpoint[0])
    assert affect.mood.current_mood in ("irritable", "anxious", "low")


def test_negative_entries_count_even_beside_positive_ones():
    """The old seeding summed the positive entries only, and only to decide
    whether to start "content": a baseline weighed down by grief read the same
    as one without it, and a mostly-sad one read neutral."""
    bright = AffectSystem(emotional_baseline={"joyful": 0.5, "curious": 0.4})
    grieving = AffectSystem(emotional_baseline={"joyful": 0.5, "curious": 0.4, "grief": 0.9})
    assert grieving.setpoint[0] < bright.setpoint[0]
    assert AffectSystem(emotional_baseline={"content": 0.3, "sad": 0.7}).setpoint[0] < 0.0


def test_a_positive_baseline_gives_a_setpoint_above_zero():
    affect = AffectSystem(emotional_baseline={"content": 0.5, "joyful": 0.4})
    assert affect.setpoint[0] > 0.0
    assert affect.mood.current_mood in ("content", "happy", "calm")


# ---- Pulled back to the set-point in world hours ----------------------

def test_mood_returns_to_the_setpoint_by_its_half_lives_in_world_hours():
    affect = AffectSystem()
    _lift(affect)
    v0, a0 = affect.setpoint
    gap_v, gap_a = affect.mood.valence - v0, affect.mood.arousal - a0
    assert gap_v > 0.3 and gap_a > 0.1
    _live(affect, MOOD_AROUSAL_HALF_LIFE_HOURS, loneliness=0.0, stress=0.0)
    assert affect.mood.arousal - a0 == pytest.approx(gap_a / 2, abs=1e-9)
    _live(affect, MOOD_VALENCE_HALF_LIFE_HOURS - MOOD_AROUSAL_HALF_LIFE_HOURS, loneliness=0.0, stress=0.0)
    assert affect.mood.valence - v0 == pytest.approx(gap_v / 2, abs=1e-9)


def test_the_pull_back_is_the_same_whatever_the_tick_cadence():
    fine, coarse = AffectSystem(), AffectSystem()
    _lift(fine)
    _lift(coarse)
    _live(fine, 6.0, step=5 / 60, loneliness=0.0, stress=0.0)
    _live(coarse, 6.0, step=3.0, loneliness=0.0, stress=0.0)
    assert fine.mood.valence == pytest.approx(coarse.mood.valence, abs=1e-9)
    assert fine.mood.arousal == pytest.approx(coarse.mood.arousal, abs=1e-9)


def test_a_tick_without_hours_counts_as_one_energy_tick():
    legacy, timed = AffectSystem(), AffectSystem()
    _lift(legacy)
    _lift(timed)
    legacy.tick(body_state=_body(), social_state=NO_SOCIAL, **STILL)
    timed.tick(body_state=_body(), social_state=NO_SOCIAL, hours=DEFAULT_TICK_HOURS, **STILL)
    assert legacy.mood.valence == timed.mood.valence
    from aura_life.scheduler.life_scheduler import LifeScheduler
    assert DEFAULT_TICK_HOURS == pytest.approx(LifeScheduler.TICK_INTERVAL_MINUTES["energy"] / 60)


# ---- Needs pull it down -----------------------------------------------

def test_loneliness_held_at_0_9_for_24_hours_drives_valence_below_the_setpoint():
    lonely, twin = AffectSystem(), AffectSystem()
    _live(lonely, 24, loneliness=0.9, stress=0.0)
    _live(twin, 24, loneliness=0.0, stress=0.0)
    assert lonely.mood.valence < lonely.setpoint[0]
    assert twin.mood.valence == pytest.approx(twin.setpoint[0], abs=1e-9)


@pytest.mark.parametrize("need", ["loneliness", "stress", "hunger", "sleep_pressure", "illness"])
def test_each_need_shortfall_pulls_valence_down(need):
    calm = dict(loneliness=0.0, stress=0.0)
    if need in calm:
        needy_kwargs = dict(calm, **{need: 1.0})
    else:
        needy_kwargs = dict(calm, body=_body(**{need: 1.0}))
    needy, twin = AffectSystem(), AffectSystem()
    _live(needy, 24, **needy_kwargs)
    _live(twin, 24, **calm)
    assert needy.mood.valence < twin.mood.valence - 0.05


def test_needs_below_their_floors_leave_mood_at_the_setpoint():
    floors = affect_module.NEED_FLOORS
    below = {need: floor - 0.01 for need, floor in floors.items()}
    affect = AffectSystem()
    _live(affect, 24,
          body=_body(hunger=below["hunger"], sleep_pressure=below["sleep_pressure"], illness=below["illness"]),
          loneliness=below["loneliness"], stress=below["stress"])
    assert affect.mood.valence == pytest.approx(affect.setpoint[0], abs=1e-9)


def test_sleep_pressure_lowers_arousal_and_stress_raises_it():
    sleepy, tense, twin = AffectSystem(), AffectSystem(), AffectSystem()
    _live(sleepy, 12, body=_body(sleep_pressure=1.0), loneliness=0.0, stress=0.0)
    _live(tense, 12, loneliness=0.0, stress=1.0)
    _live(twin, 12, loneliness=0.0, stress=0.0)
    assert sleepy.mood.arousal < twin.mood.arousal < tense.mood.arousal


def test_asleep_her_arousal_settles_at_sleeps_own_level():
    """Her sleep pressure falls while she sleeps; without this her mood would
    grow more keyed-up the longer she slept."""
    energetic = AffectSystem(emotional_baseline={"excited": 0.8, "joyful": 0.6})
    start = energetic.mood.arousal
    assert start > affect_module.MOOD_AROUSAL_LOW
    asleep = affect_module.ASLEEP_AROUSAL
    _live(energetic, 8, body=_body(asleep=True), loneliness=0.0, stress=0.0)
    assert energetic.mood.arousal == pytest.approx(
        asleep + (start - asleep) * 0.5 ** (8 / MOOD_AROUSAL_HALF_LIFE_HOURS))
    assert asleep == vocabulary.valence_arousal("sleepy")[1]
    assert energetic.mood.current_mood in ("calm", "flat", "low")
    # Awake again, it climbs back toward her set-point by its half-life.
    _live(energetic, MOOD_AROUSAL_HALF_LIFE_HOURS, loneliness=0.0, stress=0.0)
    assert energetic.mood.arousal > affect_module.ASLEEP_AROUSAL + 0.1


# ---- Emotion events move it toward each emotion's point ----------------

def test_an_emotion_moves_mood_toward_its_own_point():
    sad, excited = AffectSystem(), AffectSystem()
    v0, a0 = sad.setpoint
    sad.on_emotion_event("sad", 0.6)
    excited.on_emotion_event("excited", 0.6)
    assert sad.mood.valence < v0
    assert excited.mood.valence > v0 and excited.mood.arousal > a0


def test_names_that_used_to_miss_mood_now_reach_it():
    """In neither of the old positive/negative sets, these did nothing."""
    for name in ("discouraged", "drained", "resigned", "uncomfortable"):
        affect = AffectSystem()
        affect.on_emotion_event(name, 0.5)
        assert affect.mood.valence < affect.setpoint[0], name


def test_negative_events_can_take_a_bright_persona_negative():
    affect = AffectSystem(emotional_baseline={"content": 0.5})
    assert affect.mood.valence > 0.0
    for _ in range(50):
        affect.on_emotion_event("discouraged", 0.5)
        affect.on_emotion_event("sad", 0.3)
    assert affect.mood.valence < 0.0
    assert affect.mood.current_mood in ("low", "irritable", "anxious")


def test_repeated_pleasant_emotions_never_carry_mood_past_their_own_point():
    """The old accumulator only ever added: a stream of mild positive activity
    emotions pinned every persona at "content", intensity ~0.98."""
    affect = AffectSystem()
    for _ in range(500):
        affect.on_emotion_event("content", 0.2)
    assert affect.mood.valence <= vocabulary.valence_arousal("content")[0] + 1e-9


def test_only_the_five_high_arousal_names_drain_regulation():
    """The drain keeps the names it always had; the vocabulary did not widen
    it to every aroused name."""
    from aura_life.affect.affect_system import HIGH_AROUSAL_EMOTIONS

    assert HIGH_AROUSAL_EMOTIONS == {"excited", "anxious", "angry", "startled", "restless"}
    for name in sorted(HIGH_AROUSAL_EMOTIONS):
        affect = AffectSystem()
        before = affect.regulation.capacity
        affect.on_emotion_event(name, 0.8)
        assert affect.regulation.capacity < before, name
    for name in ("energized", "aroused", "desire", "ecstasy", "flustered"):
        assert vocabulary.valence_arousal(name)[1] >= 0.7, name  # aroused, but not listed
        affect = AffectSystem()
        before = affect.regulation.capacity
        affect.on_emotion_event(name, 0.8)
        assert affect.regulation.capacity == before, name


def test_criticism_lowers_valence_and_encouragement_raises_it():
    critic, cheer = AffectSystem(), AffectSystem()
    critic.process_conversation_trigger("criticism")
    cheer.process_conversation_trigger("encouragement")
    assert critic.mood.valence < 0.0 < cheer.mood.valence


# ---- What it shows, and what it keeps ---------------------------------

def test_the_export_keeps_current_and_intensity_and_adds_valence_and_arousal():
    affect = AffectSystem(emotional_baseline={"sad": 0.6})
    mood = affect.export_state()["mood"]
    assert set(mood) >= {"current", "intensity", "valence", "arousal"}
    assert mood["current"] == affect.mood.current_mood
    assert mood["intensity"] == round(affect.mood.intensity, 2)
    assert mood["valence"] == round(affect.mood.valence, 2)
    assert mood["arousal"] == round(affect.mood.arousal, 2)


def test_valence_and_arousal_survive_a_save_and_a_load():
    affect = AffectSystem()
    affect.on_emotion_event("anxious", 0.8)
    restored = AffectSystem.from_dict(affect.to_dict())
    assert (restored.mood.valence, restored.mood.arousal) == (affect.mood.valence, affect.mood.arousal)
    assert restored.mood.current_mood == affect.mood.current_mood


def test_a_row_saved_before_valence_existed_starts_at_her_setpoint():
    old_row = {"mood_current": "content", "mood_intensity": 0.98}
    restored = AffectSystem.from_dict(old_row, emotional_baseline={"sad": 0.6})
    assert restored.mood.valence == pytest.approx(restored.setpoint[0])
    assert restored.mood.current_mood == mood_label(*restored.setpoint)


@pytest.mark.parametrize("label", [label for label in MOOD_LABELS if label != "neutral"])
def test_every_mood_but_neutral_is_described_in_its_own_words(label):
    desc = _at(*vocabulary.valence_arousal(label)).get_mood_description()
    assert desc and desc != f"You're feeling {label}"


def test_a_negative_mood_makes_her_more_irritable():
    assert _at(-0.6, 0.5).get_irritability_level() > _at(0.0, 0.3).get_irritability_level()


def test_the_shadow_and_mental_health_read_the_mood_valence(tmp_path):
    """Both read mood through LifeService._mood_to_valence, which mapped labels
    only -- a label it did not list read as neutral."""
    from aura_life.life_service import LifeService
    from aura_life.personas.personality_config import PersonalityDefinition

    svc = LifeService(db_path=str(tmp_path / "life.db"), persona_id="grey",
                      definition=PersonalityDefinition(emotional_baseline={"despair": 1.0, "grief": 1.0}))
    assert svc._affect.mood.current_mood == "low"
    assert "low mood" in svc.mental_health_index()["drivers"]
    # The label-only form a host calls stays as it was.
    assert LifeService._mood_to_valence("content", 1.0) == pytest.approx(1.0)
    assert LifeService._mood_to_valence("blue", 1.0) == pytest.approx(0.0)
    assert LifeService._mood_to_valence("unknown_label", 0.7) == pytest.approx(0.5)
    assert LifeService._mood_to_valence("low", 0.9, valence=-0.5) == pytest.approx(0.25)


# ======================================================================
# 3. What LifeService feeds it
# ======================================================================

EPOCH = datetime(2026, 10, 6, 12, 0)  # a Tuesday noon


class ScriptedClock:
    """A world clock that advances only when told to."""

    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant

    def advance(self, hours: float) -> None:
        self.instant += timedelta(hours=hours)


def _service(tmp_path, name="moody", clock=None, **kwargs):
    from aura_life.life_service import LifeService
    from aura_life.world import WorldEnvironment

    clock = clock or ScriptedClock(EPOCH)
    svc = LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=name,
                      world_environment=WorldEnvironment(now=clock), **kwargs)
    return svc, clock


def test_the_affect_tick_runs_on_world_hours(tmp_path):
    svc, clock = _service(tmp_path)
    seen = []
    real_tick = svc._affect.tick

    def spy(*args, **kwargs):
        seen.append((kwargs["hours"], kwargs["now"]))
        return real_tick(*args, **kwargs)

    svc._affect.tick = spy
    clock.advance(1.5)
    svc._on_energy_tick()
    clock.advance(0.25)
    svc._on_energy_tick()
    assert seen == [(pytest.approx(1.5), EPOCH + timedelta(hours=1.5)),
                    (pytest.approx(0.25), EPOCH + timedelta(hours=1.75))]


def test_mood_survives_a_save_and_a_reload_of_the_service(tmp_path):
    svc, clock = _service(tmp_path, name="keeper")
    svc._load_state()  # inserts the rows, as start() does
    for _ in range(10):
        svc._affect.on_emotion_event("anxious", 0.9)
    assert svc._affect.mood.current_mood != "neutral"
    svc._save_state()

    again, _ = _service(tmp_path, name="keeper", clock=clock)
    again._load_state()
    assert (again._affect.mood.valence, again._affect.mood.arousal) == pytest.approx(
        (svc._affect.mood.valence, svc._affect.mood.arousal))
    assert again._affect.mood.current_mood == svc._affect.mood.current_mood


def test_a_database_saved_before_the_mood_pair_existed_starts_her_at_her_setpoint(tmp_path):
    """The columns are added in place; the old row's saturated "content" is
    not carried over, since it came from the retired one-axis model."""
    import sqlite3
    from aura_life.personas.personality_config import PersonalityDefinition

    db = tmp_path / "elder.db"
    with sqlite3.connect(db) as conn:
        # life_affect_state exactly as _init_database created it before the pair.
        conn.execute("""
            CREATE TABLE life_affect_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                mood_current TEXT DEFAULT 'neutral',
                mood_intensity REAL DEFAULT 0.0,
                mood_since TEXT,
                stress_level REAL DEFAULT 0.0,
                stress_sources TEXT DEFAULT '[]',
                stress_coping_capacity REAL DEFAULT 0.7,
                stress_last_relief TEXT,
                loneliness_level REAL DEFAULT 0.0,
                loneliness_desired_baseline REAL DEFAULT 0.5,
                loneliness_last_meaningful TEXT,
                loneliness_lifetime_peak REAL DEFAULT 0.0,
                regulation_capacity REAL DEFAULT 0.7,
                regulation_baseline REAL DEFAULT 0.7,
                regulation_last_event TEXT,
                empathy_susceptibility REAL DEFAULT 0.5,
                empathy_absorbed_emotion TEXT,
                empathy_absorbed_intensity REAL DEFAULT 0.0,
                empathy_fatigue REAL DEFAULT 0.0
            )
        """)
        conn.execute("INSERT INTO life_affect_state (id, mood_current, mood_intensity) VALUES (1, 'content', 0.98)")
    definition = PersonalityDefinition(emotional_baseline={"sad": 0.6, "tired": 0.4})
    svc, clock = _service(tmp_path, name="elder", definition=definition)
    svc._load_state()
    assert svc._affect.mood.valence == pytest.approx(svc._affect.setpoint[0])
    assert svc._affect.mood.valence < 0.0
    assert svc._affect.mood.current_mood != "content"

    # The migrated table takes the pair from here on.
    svc._affect.on_emotion_event("joyful", 1.0)
    svc._save_state()
    again, _ = _service(tmp_path, name="elder", clock=clock, definition=definition)
    again._load_state()
    assert (again._affect.mood.valence, again._affect.mood.arousal) == pytest.approx(
        (svc._affect.mood.valence, svc._affect.mood.arousal))


def test_the_life_context_shows_the_mood_of_the_loaded_persona(tmp_path):
    """The context builder was handed the affect engine the service had at
    construction; loading a saved row replaced the service's engine, so after
    any restart get_life_context() showed a mood that was never ticked."""
    svc, clock = _service(tmp_path, name="restarted")
    svc._load_state()
    svc._save_state()

    again, _ = _service(tmp_path, name="restarted", clock=clock)
    again._load_state()
    again._affect._set_mood(-0.8, 0.2)  # a mood change after the reload
    assert again._affect.mood.current_mood == "low"
    assert again._affect.MOOD_DESCRIPTIONS["low"] in again.get_life_context()


def test_the_life_context_shows_the_mood_after_a_reset(tmp_path):
    svc, _ = _service(tmp_path, name="reset")
    svc.reset_state()
    svc._affect._set_mood(-0.8, 0.2)
    assert svc._affect.MOOD_DESCRIPTIONS["low"] in svc.get_life_context()


# ---- Sleep pressure and illness reach mood -----------------------------

def _spy_affect_ticks(svc) -> list:
    """Record every body_state the service hands its affect tick."""
    seen = []
    real_tick = svc._affect.tick

    def spy(*args, **kwargs):
        seen.append(dict(kwargs["body_state"]))
        return real_tick(*args, **kwargs)

    svc._affect.tick = spy
    return seen


def test_the_affect_tick_gets_sleep_pressure_and_the_worst_of_illness_injury_and_pain(tmp_path):
    svc, _ = _service(tmp_path)
    seen = _spy_affect_ticks(svc)
    svc.energy.state.fatigue = 0.8
    svc._body.fall_ill("a cold", 0.6)
    svc._body.comfort.pain_level = 0.3
    svc._on_energy_tick()
    body = seen[-1]
    assert body["sleep_pressure"] == pytest.approx(svc.energy.sleep_pressure) == pytest.approx(0.8)
    health, comfort = svc._body.health, svc._body.comfort
    assert body["illness"] == pytest.approx(
        max(health.illness_severity, health.injury_severity, comfort.pain_level))
    assert body["illness"] > 0.5


def test_an_ai_persona_has_no_body_to_pull_its_mood(tmp_path):
    from aura_life.personas.personality_config import PersonalityDefinition

    svc, _ = _service(tmp_path, definition=PersonalityDefinition(persona_type="ai"))
    seen = _spy_affect_ticks(svc)
    svc.energy.state.fatigue = 0.9
    svc._on_energy_tick()
    assert seen[-1]["sleep_pressure"] == 0.0
    assert seen[-1]["illness"] == 0.0
    assert seen[-1]["asleep"] is False


def test_the_affect_tick_knows_whether_she_is_asleep(tmp_path):
    awake, _ = _service(tmp_path, name="noon")                     # Tuesday 12:00
    night, _ = _service(tmp_path, name="night", clock=ScriptedClock(datetime(2026, 10, 7, 2, 0)))
    assert night.energy.is_asleep() and not awake.energy.is_asleep()
    seen_awake, seen_night = _spy_affect_ticks(awake), _spy_affect_ticks(night)
    awake._on_energy_tick()
    night._on_energy_tick()
    assert seen_awake[-1]["asleep"] is False
    assert seen_night[-1]["asleep"] is True


def test_an_anticipation_is_felt_per_world_hour_not_per_tick(tmp_path):
    """It was fed at 0.1 x its intensity every energy tick, so a host ticking
    every 5 minutes felt it twelve times an hour and a 15-minute sim four."""
    from aura_life.affect.affect_system import ANTICIPATION_MOOD_PER_HOUR

    totals = {}
    for name, step_minutes in (("fine", 5), ("coarse", 60)):
        svc, clock = _service(tmp_path, name=name)
        svc._memory_time.add_anticipation(event="the concert", feeling="excited", intensity=0.6)
        felt = _spy_feelings(svc)
        for _ in range(60 // step_minutes):
            clock.advance(step_minutes / 60)
            svc._on_energy_tick()
        totals[name] = sum(i for emotion, i in felt if emotion == "excited")
    assert totals["fine"] == pytest.approx(totals["coarse"])
    assert totals["coarse"] == pytest.approx(0.6 * ANTICIPATION_MOOD_PER_HOUR)


def test_a_force_woken_persona_is_awake_to_her_mood(tmp_path):
    """The wake button wakes her through LifeService.is_asleep() (the energy
    system's own flag stays set until her night ends); mood must not keep
    reading her as asleep while she chats."""
    svc, _ = _service(tmp_path, name="woken", clock=ScriptedClock(datetime(2026, 10, 7, 2, 0)))
    assert svc.energy.is_asleep()
    seen = _spy_affect_ticks(svc)
    svc.force_wake()
    svc._on_energy_tick()
    assert svc.energy.is_asleep()  # the energy flag is untouched...
    assert seen[-1]["asleep"] is False  # ...but she is awake


# ---- Nature lifts her on arrival, whatever the tick cadence ------------

def test_nature_lifts_her_mood_when_she_arrives_not_on_every_tick(tmp_path):
    """The lift used to come on every activity tick spent there, so how high it
    carried her depended on how often the host ticked."""
    settled = {}
    for ticks in (1, 3, 12):
        svc, _ = _service(tmp_path, name=f"walker{ticks}")
        before = svc._affect.mood.valence
        for _ in range(ticks):
            svc._apply_location_effects("park")
        settled[ticks] = svc._affect.mood.valence
        assert settled[ticks] > before
    assert settled[1] == settled[3] == settled[12]

    svc, _ = _service(tmp_path, name="returner")
    svc._apply_location_effects("park")
    first = svc._affect.mood.valence
    svc._apply_location_effects("home")
    svc._apply_location_effects("park")  # a second arrival lifts her again
    assert svc._affect.mood.valence > first


# ---- The moment-share "mood lifted" signal -----------------------------

def _offered_life_triggers(svc) -> list:
    """Run the life-trigger evaluation once with a spy on its final pick, and
    return every trigger type that pick was offered."""
    import random as _random
    from types import SimpleNamespace

    offered = []

    class SpyPick(_random.Random):
        def choices(self, population, weights=None, k=1, **kwargs):
            offered.extend(c[0] for c in population if len(c) == 4)
            return [population[0]]

    svc._follow_up_provider = lambda pid: SimpleNamespace(create_trigger=lambda **kw: None)
    svc._service_rng = SpyPick(1)
    slot = SimpleNamespace(activity_name="reading", location="home")
    # A plan is read at an instant (Task 28): the stub takes it.
    svc._daily_planner._current_plan = SimpleNamespace(get_current_slot=lambda now=None: slot, slots=[],
                                                        date="today")
    svc._life_trigger_cooldowns.clear()
    svc._evaluate_life_triggers()
    return offered


def test_only_a_pleasant_intense_mood_reads_as_worth_a_moment_share(tmp_path):
    """"Mood clearly lifted" read intensity alone; intensity is now distance
    from neutral in any direction, so it fired at her lowest."""
    low, _ = _service(tmp_path, name="lowest")
    low._affect._set_mood(-0.8, 0.2)
    assert low._affect.mood.current_mood == "low" and low._affect.mood.intensity >= 0.7
    assert "moment_share" not in _offered_life_triggers(low)

    elated, _ = _service(tmp_path, name="elated")
    elated._affect._set_mood(0.8, 0.7)
    assert elated._affect.mood.current_mood == "happy" and elated._affect.mood.intensity >= 0.7
    assert "moment_share" in _offered_life_triggers(elated)


# ---- Events that used to miss mood -------------------------------------

def _spy_feelings(svc) -> list:
    """Record every (emotion, intensity) the service feeds its mood (an
    activity's appraised feelings come told ``reactivity_applied``, Task
    14)."""
    felt = []
    real = svc._affect.on_emotion_event

    def spy(emotion, intensity, **kwargs):
        felt.append((emotion, intensity))
        return real(emotion, intensity, **kwargs)

    svc._affect.on_emotion_event = spy
    return felt


def _awake_activity_tick(svc):
    """One activity tick at Tuesday noon, awake, with no intimate interlude."""
    svc._desire_system.should_do_intimate_activity = lambda *a, **k: False
    svc._on_activity_tick()


def test_chaos_emotions_reach_mood_without_a_host_engine(tmp_path):
    """They were fed to mood only inside the host-engine branch, so a service
    with no EmotionEngine never felt a chaos event."""
    svc, _ = _service(tmp_path)
    assert svc._emotion_engine is None
    felt = _spy_feelings(svc)
    svc._chaos.roll = lambda **kwargs: {
        "type": "universal", "text": "took a bad fall and twisted something",
        "emotions": {"frustrated": 0.12, "uncomfortable": 0.12}, "share_worthy": False,
    }
    _awake_activity_tick(svc)
    assert ("frustrated", 0.12) in felt and ("uncomfortable", 0.12) in felt


def test_micro_event_emotions_reach_mood(tmp_path, monkeypatch):
    import dataclasses
    from types import SimpleNamespace

    svc, _ = _service(tmp_path)
    felt = _spy_feelings(svc)
    svc._chaos.roll = lambda **kwargs: None
    # The pool is her setting's (Task 9 moved MICRO_EVENTS into the
    # contemporary pack), so it is patched there.
    monkeypatch.setattr(svc, "_setting", dataclasses.replace(
        svc._setting,
        micro_events=[{"text": "The kettle clicked off", "emotion": {"wistful": 0.1}, "share_worthy": False}]))
    # The service's own draws (ruling T5-R1: self._service_rng, not module
    # random any more): the micro-event roll always hits.
    monkeypatch.setattr(svc, "_service_rng", SimpleNamespace(
        random=lambda: 0.0, choice=lambda seq: list(seq)[0], uniform=lambda a, b: a,
        sample=lambda seq, k: list(seq)[:k]))
    _awake_activity_tick(svc)
    assert ("wistful", 0.1) in felt


def test_intimate_activity_emotions_reach_mood(tmp_path):
    from aura_life.intimacy.desire_system import INTIMATE_ACTIVITIES

    svc, _ = _service(tmp_path)
    felt = _spy_feelings(svc)
    activity = INTIMATE_ACTIVITIES[0]
    svc._desire_system.should_do_intimate_activity = lambda *a, **k: True
    svc._desire_system.select_intimate_activity = lambda: activity
    svc._on_activity_tick()
    assert set(activity.emotion_effects.items()) <= set(felt)


def _quiet_goal_engine(svc, completed=(), events=()):
    engine = svc._goal_engine
    engine.generate_daily_goal = lambda **kw: None
    engine.check_goal_completion = lambda **kw: list(completed)
    engine.evaluate_motivation = lambda **kw: list(events)


def test_goal_failure_lowers_mood(tmp_path):
    """Goal events went to the host engine only."""
    from aura_life.goals.goal_engine import GoalEvent

    svc, _ = _service(tmp_path)
    before = svc._affect.mood.valence
    _quiet_goal_engine(svc, events=[GoalEvent(
        "abandoned", "Learn the guitar", {"sad": 0.5, "discouraged": 0.4, "resigned": 0.2})])
    svc._on_goal_tick()
    assert svc._affect.mood.valence < before


def test_goal_completion_lifts_mood(tmp_path):
    """A completed goal was a life event only."""
    from aura_life.affect.affect_system import GOAL_COMPLETION_EMOTIONS
    from aura_life.models import Goal

    svc, _ = _service(tmp_path)
    before = svc._affect.mood.valence
    felt = _spy_feelings(svc)
    _quiet_goal_engine(svc, completed=[Goal(title="Finish the sketch")])
    svc._on_goal_tick()
    assert svc._affect.mood.valence > before
    assert set(GOAL_COMPLETION_EMOTIONS.items()) <= set(felt)
    assert svc._life_events._events[-1].emotional_impact == GOAL_COMPLETION_EMOTIONS


def test_a_work_day_returns_its_event_once():
    from types import SimpleNamespace
    from aura_life.job.career_system import CareerSystem, POSITIVE_EVENTS

    always = SimpleNamespace(random=lambda: 0.0, uniform=lambda a, b: a, choice=lambda seq: list(seq)[0])
    career = CareerSystem(occupation="nurse", rng=always)
    monday_morning = datetime(2026, 10, 5, 10, 0)
    assert career.tick(now=monday_morning) == POSITIVE_EVENTS[0]
    assert career.tick(now=monday_morning + timedelta(hours=1)) is None  # one workday, one roll


def test_every_work_event_has_emotions_that_match_its_sign():
    from aura_life.affect.affect_system import WORK_EVENT_EMOTIONS
    from aura_life.job.career_system import NEGATIVE_EVENTS, POSITIVE_EVENTS

    for events, sign in ((POSITIVE_EVENTS, 1), (NEGATIVE_EVENTS, -1)):
        for event in events:
            emotions = WORK_EVENT_EMOTIONS[event]
            weighted = sum(vocabulary.valence_arousal(n)[0] * i for n, i in emotions.items())
            assert weighted * sign > 0, event
            assert all(vocabulary.is_known(n) for n in emotions), event


def test_a_bad_work_day_reaches_mood(tmp_path):
    from aura_life.affect.affect_system import WORK_EVENT_EMOTIONS

    svc, _ = _service(tmp_path)
    felt = _spy_feelings(svc)
    svc._career.tick = lambda now=None: "had a frustrating day"
    svc._on_energy_tick()
    assert set(WORK_EVENT_EMOTIONS["had a frustrating day"].items()) <= set(felt)


# ---- LifeService decays the host's EmotionEngine -----------------------

def test_lifeservice_says_it_decays_the_host_emotion_engine():
    from aura_life.life_service import LifeService

    assert LifeService.decays_emotion_engine is True


def test_the_energy_tick_decays_the_host_engine_by_world_time(tmp_path):
    """Sixty simulated seconds decay it by sixty seconds' worth
    (EmotionEngine.BASE_DECAY_RATE per second), however little wall time the
    test itself takes."""
    from aura_life.emotion import EmotionEngine

    engine = EmotionEngine()
    svc, clock = _service(tmp_path, emotion_engine=engine)
    engine.add_emotion("excited", 0.9)
    clock.advance(60 / 3600)
    svc._on_energy_tick()
    excited = {e.emotion: e.intensity for e in engine.state.active_emotions}["excited"]
    assert excited == pytest.approx(0.9 - EmotionEngine.BASE_DECAY_RATE * 60)


def test_decay_tick_keeps_its_own_wall_clock(monkeypatch):
    """The public API is unchanged: a host calling decay_tick() decays by the
    wall time since its own last call, as before."""
    from aura_life.emotion import emotion_engine
    from aura_life.emotion.emotion_engine import EmotionEngine

    now = [1_000_000.0]
    monkeypatch.setattr(emotion_engine.time, "time", lambda: now[0])
    engine = EmotionEngine()
    engine.add_emotion("excited", 0.9)
    now[0] += 60
    engine.decay_tick()
    excited = {e.emotion: e.intensity for e in engine.state.active_emotions}["excited"]
    assert excited == pytest.approx(0.9 - EmotionEngine.BASE_DECAY_RATE * 60)


def test_a_host_engine_without_the_world_clock_hook_decays_on_its_own(tmp_path):
    """A host may inject its own engine: one with only decay_tick() is decayed
    through it, and one with neither is left alone."""
    from types import SimpleNamespace

    calls = []
    duck = SimpleNamespace(add_emotion=lambda *a, **k: None, decay_tick=lambda: calls.append(1))
    svc, _ = _service(tmp_path, emotion_engine=duck)
    svc._on_energy_tick()
    assert calls == [1]

    bare, _ = _service(tmp_path, name="bare", emotion_engine=object())
    bare._on_energy_tick()  # no error


# ======================================================================
# 4. Three simulated days
# ======================================================================
# Two contrasting authored personas plus a no-profile control (the humanness
# spec's section 6), at production cadence -- each tick at LifeScheduler's own
# interval (ruling T4-R3). The two baselines are the "Emotional Baseline"
# sections of aura-personality's lina/profile.txt and roberta/profile.txt,
# copied here so this library's tests do not depend on that package.

#: Ruling T26-R1 (Task 26 fix round 1): re-pinned from 3 to 1. The controller
#: swept seeds 1-10 at production cadence for "mood goes down as well as up"
#: (test_each_persona_s_mood_goes_down_as_well_as_up, below) across all three
#: personas: the property held on 29/30 persona-seeds; seed 3 was the lone
#: outlier (roberta's max valence landed just under her setpoint -- 0.182 vs
#: 0.209 -- once desire/habitation/cognitive/drive/... stopped sharing one
#: draw sequence, per Task 26's per-engine rng streams). Seed 1 is clean.
#: Task 10 re-pinned from 1 to 9 by the same rule: once her activities were
#: chosen by utility, the sweep of seeds 1-10 held on 28/30 persona-seeds --
#: control and lina 10/10, roberta 8/10 -- and roberta's peak valence
#: averaged 0.235 as before (0.233 on the tree before the change, which held
#: on 29/30), but seed 1 landed exactly on her set-point (0.209, not above)
#: and seed 8 under it (0.199). Seed 9 has the widest margin on both trees
#: (0.259 and 0.250 against 0.209).
SIM_SEED = 9
SIM_DAYS = 3
LINA_BASELINE = {"calm": 0.6, "guarded": 0.7, "curious": 0.4, "grief": 0.3, "resolve": 0.6}
ROBERTA_BASELINE = {"joyful": 0.5, "affectionate": 0.6, "restless": 0.5, "curious": 0.4, "grief": 0.3}


@pytest.fixture(scope="module")
def mood_trace(tmp_path_factory):
    from aura_life.personas.personality_config import PersonalityDefinition
    from sim_helpers import PRODUCTION, SimPersona, run_days

    personas = [
        SimPersona("control"),
        SimPersona("lina", service_kwargs={
            "definition": PersonalityDefinition(emotional_baseline=dict(LINA_BASELINE))}),
        SimPersona("roberta", service_kwargs={
            "definition": PersonalityDefinition(emotional_baseline=dict(ROBERTA_BASELINE))}),
    ]
    return run_days(personas, days=SIM_DAYS, seed=SIM_SEED, cadence=PRODUCTION,
                    data_dir=tmp_path_factory.mktemp("mood_model"))


SIM_IDS = ["control", "lina", "roberta"]


def test_the_production_cadence_runs_each_tick_at_the_scheduler_s_interval(tmp_path):
    """Ruling T4-R3: tests/sim_helpers.py can drive a service the way
    LifeScheduler does -- each tick at its own interval, the clock stepping at
    the smallest -- as well as the legacy every-tick-every-step mode."""
    from aura_life.scheduler.life_scheduler import LifeScheduler
    from sim_helpers import LEGACY, PRODUCTION, SimPersona, run_days

    intervals = LifeScheduler.TICK_INTERVAL_MINUTES
    assert set(intervals) == set(LifeScheduler.TICK_ORDER) == {"world", "energy", "plan", "activity", "goal"}
    trace = run_days([SimPersona("clockwork")], days=1, seed=1, cadence=PRODUCTION, data_dir=tmp_path / "prod")
    assert trace.cadence == PRODUCTION
    assert trace.step_minutes == min(intervals.values())
    records = trace.records["clockwork"]
    assert len(records) == 24 * 60 // trace.step_minutes
    for tick, minutes in intervals.items():
        fired = [r.t for r in records if tick in r.ticks]
        assert len(fired) == 24 * 60 // minutes, tick
        assert all((t - trace.start).total_seconds() % (minutes * 60) == 0 for t in fired), tick

    legacy = run_days([SimPersona("clockwork")], days=1, step_minutes=30, seed=1, data_dir=tmp_path / "legacy")
    assert legacy.cadence == LEGACY
    assert all(r.ticks == LifeScheduler.TICK_ORDER for r in legacy.records["clockwork"])


def test_the_three_day_run_is_clean(mood_trace):
    from sim_helpers import PRODUCTION

    assert mood_trace.cadence == PRODUCTION
    assert mood_trace.errors == []
    for pid in SIM_IDS:
        assert len(mood_trace.records[pid]) == SIM_DAYS * 24 * 60 // mood_trace.step_minutes
        assert all(r.mood in MOOD_LABELS for r in mood_trace.records[pid])


@pytest.mark.parametrize("pid", SIM_IDS)
def test_each_persona_shows_at_least_three_mood_labels_over_three_days(mood_trace, pid):
    """Ruling P1: at least three distinct labels per persona. The "no label
    over 70% of waking ticks" threshold (ruling T4-R2) waits for Tasks 14 and
    19, after needs drive what she does."""
    labels = {r.mood for r in mood_trace.records[pid]}
    assert len(labels) >= 3, labels


@pytest.mark.parametrize("pid", SIM_IDS)
def test_each_persona_shows_at_least_two_mood_labels_while_awake(mood_trace, pid):
    """The three labels above could all come from her nights (asleep, her
    mood quiets to calm, flat or low): her waking ticks alone must show two."""
    waking = {r.mood for r in mood_trace.records[pid] if not r.asleep}
    assert len(waking) >= 2, waking


@pytest.mark.parametrize("pid", SIM_IDS)
def test_each_persona_s_mood_goes_down_as_well_as_up(mood_trace, pid):
    """Before, every persona's mood only ever rose: "content" on every tick."""
    setpoint = mood_trace.services[pid]._affect.setpoint[0]
    valences = [r.valence for r in mood_trace.records[pid]]
    assert min(valences) < setpoint - 0.1
    assert max(valences) > setpoint
