"""Render-lint for Task 6 (pronouns, grammatical person, the user's name).

Renders every prompt-bound / user-visible template pool this task converted
with a male, female and nonbinary persona, and a named and unnamed user (the
brief's own words), and checks the OUTPUT for every failure mode the brief
names:

* an unfilled ``{`` / ``}``
* a doubled word
* a sentence starting lowercase (only for a pool whose own template already
  signals a capital start -- a literal capital letter, or a capitalized
  token like ``{Subj}``/``{Poss}``/``{User}``; a pool that is a lowercase
  fragment by design, e.g. chaos_engine's activity-chaos lines, is exempt)
* "the user" surviving anywhere in the rendered text
* he/she/him/her surviving in a line addressed to the persona in second
  person (``ENERGY_DESCRIPTIONS`` / ``LOCATION_DESCRIPTIONS``)
* "they" followed by a singular verb ("they was", "they hasn't", "they
  is" ...): a line that hard-codes a verb after ``{subj}`` reads right for
  a woman or a man and wrong for a nonbinary persona (Task 9 fix round,
  ruling T9-R4); the tokens ``{was}``, ``{have}`` and ``{be}`` agree

It also scans every pool's RAW (unrendered) template for a bare he/she/him/her
pronoun -- the direct check for "no hard-coded she/her/he/him", stronger than
sampling one rendering, and immune to a template that would only leak the
word for a gender combination this test happens not to try.
"""
import ast
import pathlib
import re
from datetime import datetime, timedelta

import pytest

from aura_life.affect.affect_system import AffectSystem
from aura_life.chaos.chaos_engine import ChaosEngine, MESSAGE_DELAYS
from aura_life.continuity.continuity_system import MILESTONE_PATTERNS
from aura_life.context.context_builder import LifeContextBuilder
from aura_life.identity.identity_system import IdentitySystem, TENDENCY_THOUGHTS
from aura_life.intimacy.desire_system import DesireSystem
from aura_life.life_events.life_event_system import _ACTIVITY_LINGERING_TITLES
from aura_life.energy.energy_system import ENERGY_DESCRIPTIONS
from aura_life.personas.genre_randomizer import GENDERS
from aura_life.personas.pronoun_render import render_line
# Task 9 and its fix round moved these pools, unchanged, into the
# contemporary setting pack -- what the engines now read for a persona with
# no setting -- so they are linted there (their old module names are legacy
# re-exports of the same objects).
from aura_life.settings.contemporary import (
    ACTIVITIES,
    ACTIVITY_CHAOS,
    CATCHUP_ACTIVITY_NARRATIVES,
    CATCHUP_AFTERNOON_NARRATIVES,
    CATCHUP_EVENING_NARRATIVES,
    CATCHUP_LATE_NARRATIVE,
    CATCHUP_MIDDAY_NARRATIVES,
    CATCHUP_MORNING_ACTIVITY_NARRATIVES,
    CATCHUP_MORNING_ROUTINE_NARRATIVES,
    CATCHUP_SLEEP_NARRATIVE,
    CHAOS_EMOTIONS,
    CHERISHED_OBJECTS,
    DESIRE_TEMPLATES,
    DREAM_FRAGMENT_TEMPLATES as COGNITIVE_DREAM_TEMPLATES,
    DREAM_TEMPLATES as LIFE_SERVICE_DREAM_TEMPLATES,
    ESTRANGED_EVENT_TEMPLATES,
    EVENT_TEMPLATES,
    GAP_NARRATIVE_SHORT,
    GAP_NARRATIVE_WEEK,
    INTIMATE_ACTIVITIES,
    LIFE_EVENT_TEMPLATES,
    LOCATION_DESCRIPTIONS,
    MICRO_EVENTS,
    NEGATIVE_EVENTS,
    NOSTALGIA_MEMORIES,
    POSITIVE_EVENTS,
    SERENDIPITY,
    SKILL_MILESTONES,
    TEXT_TOPICS,
    THREAT_EVENT_TEMPLATES,
    UNIVERSAL_CHAOS,
    UNIVERSAL_CHAOS_EFFECTS,
    WANT_FOLLOW_UPS,
    WEATHER_DESCRIPTIONS,
    WEATHER_FLAVORS,
)

# ---------------------------------------------------------------------------
# Renderings to try: every gender the brief asks for, PLUS an unresolved one
# (no profile / no definition -- must render as they/them, never raise);
# a named user and an unnamed one.
# ---------------------------------------------------------------------------
GENDERS_TO_TRY = (*GENDERS, None, "unknown-gender")
USERS_TO_TRY = ({"name": "Robin"}, None)

BARE_PRONOUN_RE = re.compile(r"\b(she|her|hers|herself|he|him|his|himself)\b", re.IGNORECASE)
DOUBLED_WORD_RE = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)
THE_USER_RE = re.compile(r"\bthe user\b", re.IGNORECASE)
#: "they" and a singular verb: "they was", "they wasn't", "they has", "they
#: hasn't", "they is", "they isn't", "they does", "they doesn't".
THEY_SINGULAR_RE = re.compile(r"\bthey (?:was|has|is|does)(?:n['\u2019]t)?\b", re.IGNORECASE)


def _starts_upper_by_design(raw: str) -> bool:
    """Whether `raw` signals a capitalized start: a literal capital letter,
    or a capitalized token (`{Subj}`, `{Poss}`, `{User}`, ...). A lowercase
    literal or a lowercase token (`{subj}`, `{poss}`, `{user}`, ...) means the
    pool is a fragment by design -- the sentence-case check does not apply."""
    if raw.startswith("{"):
        name = raw[1:].split("}", 1)[0]
        return name[:1].isupper()
    return raw[:1].isupper()


def _check_rendered(raw: str, rendered: str, *, is_second_person: bool = False) -> None:
    assert "{" not in rendered and "}" not in rendered, (raw, rendered)
    assert not DOUBLED_WORD_RE.search(rendered), (raw, rendered)
    assert not THE_USER_RE.search(rendered), (raw, rendered)
    assert not THEY_SINGULAR_RE.search(rendered), (raw, rendered)
    if _starts_upper_by_design(raw):
        assert rendered[:1].isupper(), (raw, rendered)
    if is_second_person:
        assert not BARE_PRONOUN_RE.search(rendered), (raw, rendered)


def _assert_pool_clean(texts, **extra):
    """The full brief-mandated sweep for one pool: a raw-template scan for a
    hardcoded pronoun, then every (gender, user) combination rendered and
    checked."""
    texts = list(texts)
    for raw in texts:
        assert not BARE_PRONOUN_RE.search(raw), f"hardcoded pronoun in template: {raw!r}"
    for raw in texts:
        for gender in GENDERS_TO_TRY:
            for user in USERS_TO_TRY:
                rendered = render_line(raw, gender=gender, user=user, **extra)
                _check_rendered(raw, rendered)


def _assert_second_person_pool_clean(texts):
    texts = list(texts)
    for raw in texts:
        assert not BARE_PRONOUN_RE.search(raw), f"hardcoded pronoun in template: {raw!r}"
    for raw in texts:
        for gender in GENDERS_TO_TRY:
            for user in USERS_TO_TRY:
                rendered = render_line(raw, gender=gender, user=user)
                _check_rendered(raw, rendered, is_second_person=True)


# ---------------------------------------------------------------------------
# Pools that need no extra template fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pool_name,texts", [
    ("MICRO_EVENTS", [e["text"] for e in MICRO_EVENTS]),
    ("SKILL_MILESTONES", [text for entries in SKILL_MILESTONES.values() for _, text in entries]),
    ("CATCHUP_SLEEP_NARRATIVE", [CATCHUP_SLEEP_NARRATIVE]),
    ("CATCHUP_MORNING_ROUTINE_NARRATIVES", CATCHUP_MORNING_ROUTINE_NARRATIVES),
    ("CATCHUP_MORNING_ACTIVITY_NARRATIVES", CATCHUP_MORNING_ACTIVITY_NARRATIVES),
    ("CATCHUP_MIDDAY_NARRATIVES", CATCHUP_MIDDAY_NARRATIVES),
    ("CATCHUP_AFTERNOON_NARRATIVES", CATCHUP_AFTERNOON_NARRATIVES),
    ("CATCHUP_EVENING_NARRATIVES", CATCHUP_EVENING_NARRATIVES),
    ("CATCHUP_LATE_NARRATIVE", [CATCHUP_LATE_NARRATIVE]),
    ("GAP_NARRATIVE_WEEK", [GAP_NARRATIVE_WEEK]),
    ("GAP_NARRATIVE_SHORT", [GAP_NARRATIVE_SHORT]),
    ("POSITIVE_EVENTS", POSITIVE_EVENTS),
    ("NEGATIVE_EVENTS", NEGATIVE_EVENTS),
    ("UNIVERSAL_CHAOS", UNIVERSAL_CHAOS),
    ("SERENDIPITY", SERENDIPITY),
    ("UNIVERSAL_CHAOS_EFFECTS", [e["text"] for e in UNIVERSAL_CHAOS_EFFECTS]),
    ("CHAOS_EMOTIONS keys", list(CHAOS_EMOTIONS.keys())),
    ("TEXT_TOPICS", TEXT_TOPICS),
    ("NOSTALGIA fragments (memory_time)", NOSTALGIA_MEMORIES),
    # Literals inside a method until Task 9 named them in the contemporary
    # pack (the AST scan below covered them there; now the render does too).
    ("CATCHUP_ACTIVITY_NARRATIVES", list(CATCHUP_ACTIVITY_NARRATIVES.values())),
    ("WEATHER_FLAVORS", list(WEATHER_FLAVORS.values())),
    ("WEATHER_DESCRIPTIONS", list(WEATHER_DESCRIPTIONS.values())),
    ("WANT_FOLLOW_UPS titles", [want["title"] for want in WANT_FOLLOW_UPS.values()]),
    ("WANT_FOLLOW_UPS descriptions", [want["description"] for want in WANT_FOLLOW_UPS.values()]),
])
def test_pool_renders_clean(pool_name, texts):
    _assert_pool_clean(texts)


@pytest.mark.parametrize("raw", [
    "{Subj} was late", "{Subj} wasn't late", "{Subj} has one", "a laugh {subj} hasn't heard",
    "{Subj} is here", "{Subj} isn\u2019t here", "{Subj} does mind", "{Subj} doesn't mind",
])
def test_the_lint_fails_they_with_a_singular_verb(raw):
    """Rendered for a nonbinary persona each of these reads "they was",
    "they hasn't" ... -- the render lint must fail it."""
    with pytest.raises(AssertionError):
        _assert_pool_clean([raw])


def test_the_lint_passes_the_tokens_that_agree_with_they():
    _assert_pool_clean(["{Subj} {was} late", "{Subj} {was}n't late", "{Subj} {have} one",
                        "a laugh {subj} {have}n't heard", "{Subj} {be} here", "They said it was late"])


@pytest.mark.parametrize("activity_key,texts", [
    (key, texts) for key, texts in ACTIVITY_CHAOS.items()
])
def test_activity_chaos_pool_renders_clean(activity_key, texts):
    _assert_pool_clean(texts)


def test_activity_engine_narrative_templates_render_clean():
    for activity in ACTIVITIES:
        _assert_pool_clean(activity.narrative_templates)


def test_activity_outcome_narratives_render_clean():
    """Task 14: what each activity's setting says happened when it only half
    went well or went wrong -- the contemporary pack's and the universal
    activities' (the universal meal's are the library's own)."""
    from aura_life.settings.universal import UNIVERSAL_ACTIVITIES

    told = 0
    for activity in list(ACTIVITIES) + list(UNIVERSAL_ACTIVITIES.values()):
        for texts in activity.outcomes.values():
            _assert_pool_clean(texts)
            told += len(texts)
    assert told >= 4 * (len(ACTIVITIES) - 1)  # every activity but sleeping: two lines per outcome


def test_the_library_s_neutral_outcome_words_render_clean():
    """Task 14: an activity whose setting has no words for how it went is
    told in these, the activity named as she would name it."""
    from aura_life.activities.activity_engine import NEUTRAL_OUTCOME_NARRATIVES

    for texts in NEUTRAL_OUTCOME_NARRATIVES.values():
        _assert_pool_clean(texts, activity="going for a run", Activity="Going for a run")


def test_intimate_activity_pools_render_clean():
    for activity in INTIMATE_ACTIVITIES:
        _assert_pool_clean([activity.description])
        _assert_pool_clean(activity.narrative_templates)


def test_cherished_objects_render_clean():
    for obj in CHERISHED_OBJECTS:
        _assert_pool_clean([obj.name, obj.description, obj.associated_memory])


def test_milestone_pattern_descriptions_render_clean():
    _assert_pool_clean([p["description"] for p in MILESTONE_PATTERNS.values()])


def test_desire_template_titles_and_descriptions_render_clean():
    _assert_pool_clean([d["title"] for d in DESIRE_TEMPLATES])
    _assert_pool_clean([d["description"] for d in DESIRE_TEMPLATES])


# ---------------------------------------------------------------------------
# Pools that need a caller-supplied field (matching each template's own
# non-pronoun placeholder, e.g. {context}, {source}, {name}/{topic}/{activity})
# ---------------------------------------------------------------------------

def test_life_service_dream_templates_render_clean():
    _assert_pool_clean(LIFE_SERVICE_DREAM_TEMPLATES, a="a floating city", b="glass")


def test_cognitive_dream_templates_render_clean():
    _assert_pool_clean(COGNITIVE_DREAM_TEMPLATES, source="reading")


def test_life_event_templates_render_clean():
    for pool in LIFE_EVENT_TEMPLATES.values():
        _assert_pool_clean(pool, context="finishing the mural")
    _assert_pool_clean(_ACTIVITY_LINGERING_TITLES, activity="reading")


def test_social_event_templates_render_clean():
    for pool in EVENT_TEMPLATES.values():
        _assert_pool_clean(pool, name="Sam", topic="a new show", activity="a movie")


@pytest.mark.parametrize("kind,templates", [
    ("estranged", ESTRANGED_EVENT_TEMPLATES), ("threat", THREAT_EVENT_TEMPLATES),
])
def test_unwelcome_kinds_event_templates_render_clean(kind, templates):
    """Task 11's lines for the two unwelcome NPC kinds."""
    for pool in templates.values():
        _assert_pool_clean(pool, name="Sam", topic="a new show", activity="a movie")


@pytest.mark.parametrize("side", ["initiator", "joiner"])
def test_joint_activity_lines_render_clean(side):
    """Task 11: the line a joint activity adds to each housemate's log, from
    her own side -- her pronouns, the other named ({name})."""
    from aura_life.social.household import JOINT_LINES

    _assert_pool_clean(JOINT_LINES[side], name="Sam")


def test_identity_tendency_thoughts_render_clean():
    for pool in TENDENCY_THOUGHTS.values():
        _assert_pool_clean(pool, npc="Sam")


# ---------------------------------------------------------------------------
# "Addressed to the persona in second person" pools: he/she/him/her must
# never survive rendering, for ANY gender -- these describe "you", not "her".
# ---------------------------------------------------------------------------

def test_energy_descriptions_are_second_person_clean():
    _assert_second_person_pool_clean(list(ENERGY_DESCRIPTIONS.values()))


def test_conversation_phrases_are_second_person_clean():
    """What a user's turn was to her, as her memory keeps it (Task 16b step 0,
    ruling T16a-R2): addressed to her, the user named or "they"."""
    from aura_life.memory.episodes import CONVERSATION_PHRASES

    _assert_second_person_pool_clean(list(CONVERSATION_PHRASES.values()))


def test_location_descriptions_are_second_person_clean():
    _assert_second_person_pool_clean(list(LOCATION_DESCRIPTIONS.values()))


# ---------------------------------------------------------------------------
# Method-based pools: the templates are inline (not module constants) because
# the method itself is the render call site (career/chaos's emotion-matching
# needs the unrendered text; cognitive/desire/chaos's delay explanation have
# no LifeService call site yet). Exercised through the method, across every
# branch, with every gender.
# ---------------------------------------------------------------------------

def test_loneliness_description_renders_clean():
    affect = AffectSystem()
    for level in (0.3, 0.6, 0.8):
        affect._loneliness.level = level
        raw = affect.get_loneliness_description()
        if not raw:
            continue
        assert not BARE_PRONOUN_RE.search(raw), raw
        for gender in GENDERS_TO_TRY:
            for user in USERS_TO_TRY:
                rendered = render_line(raw, gender=gender, user=user)
                _check_rendered(raw, rendered)


#: Task 15: what a person would never say about what weighs on her -- a
#: snake_case key ("money_worries", "sleep_deprivation") or an engine label's
#: "key:" prefix ("struggle:...", "avoiding: ...", "value conflict: ...").
STRESS_KEY_RE = re.compile(r"[a-z]_[a-z]|^[a-z ]+:")
#: What the stressor kinds' templates name, filled for the lint.
STRESSOR_FIELDS = {"what": "finishing that project", "name": "Robin", "value": "honesty"}


def _stress_words_problem(text: str):
    """Why ``text`` is not what a person would say she is stressed about --
    a key, an engine label's prefix, or the bare name of one of the
    library's engines (its subpackages: "sanity", "affect" ...) -- or None."""
    if STRESS_KEY_RE.search(text):
        return "a key or an engine label"
    engines = {p.name for p in SRC_ROOT.iterdir() if p.is_dir() and not p.name.startswith("_")}
    if text.strip().lower() in engines:
        return "an engine's name"
    return None


def test_the_stress_words_lint_flags_every_label_from_before_task_15():
    """The check below is not vacuous: every raw label the library listed
    before Task 15 fails it."""
    for label in ("sleep_deprivation", "struggle:self-doubt", "avoiding: finishing that project",
                  "overdue: call Mo back", "value conflict: honesty vs social", "sanity"):
        assert _stress_words_problem(label), label


def test_every_stressor_the_library_raises_is_worded_for_a_person():
    """Task 15: each kind of stressor's words (affect's STRESSOR_KINDS) --
    what stress.sources lists and a host quotes ("You're stressed about
    ...") -- render clean for every persona and user, and carry no key or
    engine label."""
    from aura_life.affect.affect_system import STRESSOR_KINDS

    words = [spec.words for spec in STRESSOR_KINDS.values()]
    _assert_pool_clean(words, **STRESSOR_FIELDS)
    for raw in words:
        assert _stress_words_problem(raw.format(**STRESSOR_FIELDS)) is None, raw


def test_the_stress_description_names_what_weighs_on_her_in_words():
    """Task 15: "Stressed about ..." names her heaviest stressors in their
    words, for each kind the library raises -- never a key."""
    from aura_life.affect.affect_system import STRESSOR_KINDS

    for kind, spec in STRESSOR_KINDS.items():
        affect = AffectSystem()
        affect.raise_stressor(kind, **{k: v for k, v in STRESSOR_FIELDS.items() if "{" + k + "}" in spec.words})
        affect._stress.level = 0.5  # the band that names them
        raw = affect.get_stress_description()
        assert raw == "Stressed about " + spec.words.format(**STRESSOR_FIELDS), (kind, raw)
        assert _stress_words_problem(raw[len("Stressed about "):]) is None, (kind, raw)
        for gender in GENDERS_TO_TRY:
            for user in USERS_TO_TRY:
                _check_rendered(raw, render_line(raw, gender=gender, user=user))


def test_desire_description_renders_clean():
    """DesireSystem renders itself (Task 6 fix round), so each gender gets its
    own instance: the description must carry that gender's pronouns, never a
    raw token."""
    for gender in GENDERS_TO_TRY:
        poss, obj = render_line("{poss}|{obj}", gender=gender).split("|")
        ds = DesireSystem(gender=gender)
        for arousal in (0.05, 0.2, 0.35, 0.55, 0.75, 0.95):
            ds._state.arousal = arousal
            rendered = ds.get_desire_description()
            if not rendered:
                continue
            assert "{" not in rendered, rendered
            assert not THEY_SINGULAR_RE.search(rendered), rendered
        ds._state.arousal = 0.2   # SUBTLE: "... aware of {poss} body ..."
        assert f" {poss} body" in ds.get_desire_description(), (gender, ds.get_desire_description())
        ds._state.arousal = 0.95  # ACHING: "... won't let {obj} think ..."
        assert f"let {obj} think" in ds.get_desire_description(), (gender, ds.get_desire_description())


def test_conversation_hint_renders_clean():
    ds = DesireSystem()
    for arousal in (0.3, 0.5, 0.7):
        ds._state.arousal = arousal
        for gender in GENDERS_TO_TRY:
            seen = set()
            for _ in range(30):
                hint = ds.get_conversation_hint(gender=gender)
                if hint:
                    seen.add(hint)
                    assert "{" not in hint and "}" not in hint, hint
                    assert not DOUBLED_WORD_RE.search(hint), hint
                    assert not THE_USER_RE.search(hint), hint
                    assert not THEY_SINGULAR_RE.search(hint), hint
            # At least one hint was produced for every arousal band tried.
            assert seen or arousal < 0.2


def test_chaos_delay_explanation_renders_clean():
    ce = ChaosEngine()
    for reason in (*MESSAGE_DELAYS.keys(), "an-unknown-reason"):
        for gender in GENDERS_TO_TRY:
            rendered = ce._delay_explanation(reason, gender)
            _check_rendered("{Subj}", rendered)  # every branch opens on {Subj}/{Poss}


def test_chaos_roll_message_delay_gender_param_renders_clean():
    ce = ChaosEngine()
    for gender in GENDERS_TO_TRY:
        for _ in range(50):
            delay = ce.roll_message_delay("reading", energy=0.1, regulation=0.1, gender=gender)
            if delay:
                explanation = delay["explanation"]
                assert "{" not in explanation and "}" not in explanation
                assert not THE_USER_RE.search(explanation)
                assert not THEY_SINGULAR_RE.search(explanation), explanation


def test_cognitive_generate_dream_gender_param_renders_clean():
    from aura_life.cognitive.cognitive_system import CognitiveSystem

    cog = CognitiveSystem()
    for gender in (*GENDERS, None):
        dream = cog.generate_dream(["reading", "a road trip"], sleep_quality=0.8, gender=gender)
        assert dream is not None
        assert "{" not in dream.description and "}" not in dream.description
        assert not THEY_SINGULAR_RE.search(dream.description), dream.description
        assert not BARE_PRONOUN_RE.search(dream.description) or gender in ("female", "male")


# ---------------------------------------------------------------------------
# "the user" must never appear -- the identity/context-builder defaults this
# task fixed directly (not template pools, so not covered above).
# ---------------------------------------------------------------------------

def test_identity_system_never_defaults_the_user():
    identity = IdentitySystem(user_info=None)
    assert identity.get_user_perception().person_name == "them"

    named = IdentitySystem(user_info={"name": "Robin"})
    assert named.get_user_perception().person_name == "Robin"


def test_context_builder_perceptions_section_never_says_the_user():
    identity = IdentitySystem(user_info=None)
    identity._perceptions["__user__"].trust_level = 0.9
    builder = LifeContextBuilder(
        world=None, energy=None, activity_engine=None, goal_engine=None,
        identity_system=identity,
    )
    section = builder._build_perceptions_section()
    assert not THE_USER_RE.search(section)
    assert "them" in section


# ---------------------------------------------------------------------------
# Fix round 1 (review): DesireSystem must render itself for a caller that
# never passes gender (the aura host calls `.desire.get_status()` and
# `.desire.get_desire_description()` directly and pastes the result into a
# prompt) -- LifeService._render_desire_status alone could not cover that.
# ---------------------------------------------------------------------------

def test_desire_system_renders_itself_with_no_caller_supplied_gender():
    """A direct caller (no `gender` argument at all) must still see the
    persona's real pronouns, at SUBTLE and ACHING arousal, for both
    `get_desire_description()` and `get_status()["description"]`."""
    for gender in GENDERS:
        ds = DesireSystem(gender=gender)
        for arousal in (0.2, 0.95):  # SUBTLE, ACHING
            ds._state.arousal = arousal
            desc = ds.get_desire_description()
            assert "{" not in desc and "}" not in desc, (gender, arousal, desc)
            status_desc = ds.get_status()["description"]
            assert "{" not in status_desc and "}" not in status_desc, (gender, arousal, status_desc)
            assert not THEY_SINGULAR_RE.search(desc + " " + status_desc), (gender, arousal, desc, status_desc)
            if gender == "male":
                assert re.search(r"\b(he|him|his)\b", desc, re.IGNORECASE) or desc == "", desc
            elif gender == "female":
                assert re.search(r"\b(she|her)\b", desc, re.IGNORECASE) or desc == "", desc


def test_desire_system_with_no_gender_on_record_renders_they_them():
    ds = DesireSystem()  # no gender given at all -- direct construction
    ds._state.arousal = 0.95  # ACHING
    desc = ds.get_desire_description()
    assert "{" not in desc and "}" not in desc
    assert re.search(r"\bthem\b", desc, re.IGNORECASE)
    assert not THEY_SINGULAR_RE.search(desc), desc


def test_life_service_desire_property_reflects_persona_gender_with_no_argument():
    """`svc.desire` is the exact object the aura host reaches through
    (`LifeService.desire`, read by aura's `prompt/sections/inner_life.py`,
    `routers/life.py`, `routers/health.py`): constructing it must already
    carry the persona's gender, so a direct call with NO argument -- exactly
    what those callers make -- still gets the right pronouns."""
    from datetime import datetime

    from aura_life.life_service import LifeService
    from aura_life.personas.personality_config import PersonalityDefinition
    from aura_life.world import WorldEnvironment

    class _Clock:
        def __init__(self, t):
            self._t = t

        def __call__(self):
            return self._t

    for gender, pronoun_re in (
        ("male", re.compile(r"\b(he|him|his)\b", re.IGNORECASE)),
        ("female", re.compile(r"\b(she|her)\b", re.IGNORECASE)),
    ):
        defn = PersonalityDefinition(id="p", name="T", appearance_details={"gender": gender})
        svc = LifeService(
            db_path=str(_tmp_db_path()), persona_id=f"lint-{gender}",
            world_environment=WorldEnvironment(now=_Clock(datetime(2026, 10, 6, 7, 0))),
            definition=defn,
        )
        for arousal in (0.2, 0.95):  # SUBTLE, ACHING
            svc.desire._state.arousal = arousal
            desc = svc.desire.get_desire_description()
            status_desc = svc.desire.get_status()["description"]
            assert "{" not in desc and "}" not in desc, desc
            assert "{" not in status_desc and "}" not in status_desc, status_desc
            assert pronoun_re.search(desc), (gender, arousal, desc)
            assert pronoun_re.search(status_desc), (gender, arousal, status_desc)


# ---------------------------------------------------------------------------
# Fix round 1 (review): the calendar post-event check-in hint said "The
# user's event" literally, regardless of user_info.
# ---------------------------------------------------------------------------

def test_calendar_check_in_hint_never_says_the_user():
    from aura_life.life_service import LifeService
    from aura_life.models import CalendarEntry

    class _FakeTrigger:
        def __init__(self):
            self.triggers = []

        def create_trigger(self, **kwargs):
            self.triggers.append(kwargs)

    def _past_entry(name="the recital", days=-1):
        when = datetime.now() + timedelta(days=days)
        return CalendarEntry(
            event_name=name, event_date=when, date_str=when.strftime("%Y-%m-%d"),
            feeling="nervous", importance=0.8,
        )

    for user_info, expect in (({"name": "Robin"}, "Robin's"), (None, "Their")):
        fake = _FakeTrigger()
        svc = LifeService(
            db_path=str(_tmp_db_path()), persona_id="calpersona",
            follow_up_provider=lambda pid: fake, user_info=user_info,
        )
        svc.add_calendar_entry(_past_entry())
        svc._scan_calendar_for_triggers()

        hints = [t["prompt_hint"] for t in fake.triggers if t.get("trigger_type") == "EMOTIONAL_CHECK_IN"]
        assert hints, "no EMOTIONAL_CHECK_IN trigger fired"
        for hint in hints:
            assert not THE_USER_RE.search(hint), hint
            assert not THEY_SINGULAR_RE.search(hint), hint
            assert hint.startswith(expect), hint


def _tmp_db_path():
    import tempfile
    import uuid

    return __import__("pathlib").Path(tempfile.gettempdir()) / f"render_lint_cal_{uuid.uuid4().hex}.db"


# ---------------------------------------------------------------------------
# Fix round 1 (review): str.capitalize() on the status-bar text lowercased a
# substituted user name ("Thinking about Sarah" -> "Thinking about sarah").
# ---------------------------------------------------------------------------

def test_status_bar_thinking_about_user_keeps_name_case():
    from datetime import datetime

    from aura_life.life_service import LifeService
    from aura_life.world import WorldEnvironment

    class _Clock:
        def __init__(self, t):
            self._t = t

        def __call__(self):
            return self._t

    for user_info, expected in (({"name": "Sarah"}, "Thinking about Sarah"), (None, "Thinking about them")):
        svc = LifeService(
            db_path=str(_tmp_db_path()), persona_id="statusbar",
            world_environment=WorldEnvironment(now=_Clock(datetime(2026, 10, 6, 7, 0))),
            user_info=user_info,
        )
        svc.effective_current_activity = lambda scheduled: "thinking about user"
        assert svc.get_status()["current_activity"] == expected


# ===========================================================================
# Fix round 1 (review): a static source-scan, independent of the hand-picked
# pool imports above. The dynamic tests only look at what got imported into
# this file; this walks every module under src/aura_life with `ast`, so a
# converted-but-not-imported pool, or a brand new one added later, is caught
# without anyone remembering to add it to the import list above (exactly the
# gap that let the calendar hint through in the first review round).
#
# Every string literal in the tree is checked -- including each literal
# segment of an f-string (`ast.JoinedStr`'s `ast.Constant` children; the
# `{expr}` parts are a different node type and are never string literals
# themselves). A module/class/function's docstring (its body's first
# statement, if a bare string expression -- the only thing "docstring" means
# to `ast`) is excluded, matching the brief's "docstrings/comments" carve-out;
# a `#` comment is not part of the AST at all, so it is excluded for free.
#
# The remaining, explicit ALLOWLIST below covers the six pools/spots the
# report lists under "deliberately left" -- a matcher over the persona's own
# authored text, not generated output, or (place_generation.py) a
# generation-time LLM prompt for the persona's own profile. Each entry names
# the file and the enclosing top-level symbol (a module-level Assign/
# AnnAssign target, or a function/class name) and carries its own reason, so
# an allowlist entry is exactly as visible in review as a code change.
# ===========================================================================

SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "aura_life"

_SCAN_PRONOUN_RE = re.compile(r"\b(she|her|hers|herself|he|him|his|himself)\b", re.IGNORECASE)
_SCAN_THE_USER_RE = re.compile(r"\bthe user\b", re.IGNORECASE)
_SCAN_FOR_HIM_RE = re.compile(r"\bfor him\b", re.IGNORECASE)
_SCAN_THINKING_ABOUT_USER = "Thinking about user"  # case-sensitive: the bug's exact display shape

#: (path relative to src/aura_life, enclosing symbol name or None for the
#: whole file) -> why it is not prompt-bound / user-visible generated text.
ALLOWLIST = {
    ("personas/parameters.py", "BODY_IMAGE_STRUGGLE_MARKERS"):
        "matcher over the persona's own authored struggles/character_defects "
        "text, not generated output (task-6 report, Pools deliberately left; "
        "moved from body/body_system.py with the other trait keyword tables, "
        "Task 8)",
    ("planner/daily_planner.py", "_OCC_NONE_KEYWORDS"):
        "classifier over the persona's own authored occupation text, not "
        "generated output",
    ("personas/personality_config.py", "age_speech_register"):
        "persona communication-style guidance (system_prompt material, the "
        "brief's own carve-out); also unreachable from inside aura-life "
        "itself (no internal caller)",
    ("personas/place_generation.py", None):
        "generation-time LLM prompts for a NEW persona's own appearance/"
        "cultural summary -- the persona's own profile, out of scope, and "
        "gated behind the optional-LLM ruling (R4)",
    ("personas/genre_randomizer.py", "PRONOUNS"):
        "the pronoun-token definition table itself (this task's own "
        "render_line reuses it) -- the values ARE the pronoun words by "
        "design, pinned by tests/test_gender_contract.py, not a template "
        "hardcoding one",
    ("memory/reflection.py", "_BARE_PRONOUN_RE"):
        "validate_llm_belief's own pronoun-detection pattern (Task 13 fix "
        "round 1, Important 2) -- the words are what it matches to REJECT an "
        "LLM reply that uses them, never template text this module emits",
}


def _build_parent_map(tree: ast.AST) -> dict:
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _docstring_constant_ids(tree: ast.AST) -> set:
    """id()s of every Constant that IS a module/class/function docstring --
    the only meaning `ast` gives that word: the first statement of the body,
    if it is a bare string-literal expression."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                ids.add(id(body[0].value))
    return ids


def _enclosing_symbol(node: ast.AST, parents: dict) -> "str | None":
    """The nearest enclosing function/class name, or the target name of the
    nearest enclosing module-level (or any-level) Assign/AnnAssign -- e.g. the
    Constant inside `ACTIVITY_CHAOS: Dict[...] = {"reading": ["...", ...]}`
    resolves to `"ACTIVITY_CHAOS"` regardless of how many list/dict layers
    sit between the string and the assignment."""
    current = parents.get(id(node))
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return current.name
        if isinstance(current, ast.Assign) and current.targets and isinstance(current.targets[0], ast.Name):
            return current.targets[0].id
        if isinstance(current, ast.AnnAssign) and isinstance(current.target, ast.Name):
            return current.target.id
        current = parents.get(id(current))
    return None


def _is_allowlisted(rel_path: str, symbol) -> bool:
    return (rel_path, symbol) in ALLOWLIST or (rel_path, None) in ALLOWLIST


def _scan_file_violations(source: str, rel_path: str, *, apply_allowlist: bool = True) -> list:
    """Every ALLOWLIST-uncovered banned-phrase hit in one module's source.
    `rel_path` is only a label (used as the ALLOWLIST key and in the message);
    the source itself is never re-read from disk, so this also works on a
    string that was never written to `SRC_ROOT` (see the "as it was before
    the fix" regression test below)."""
    violations = []
    tree = ast.parse(source, filename=rel_path)
    parents = _build_parent_map(tree)
    doc_ids = _docstring_constant_ids(tree)

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in doc_ids:
            continue
        text = node.value

        reasons = []
        m = _SCAN_PRONOUN_RE.search(text)
        if m:
            reasons.append(f"pronoun {m.group(0)!r}")
        if _SCAN_THE_USER_RE.search(text):
            reasons.append('"the user"')
        if _SCAN_FOR_HIM_RE.search(text):
            reasons.append('"for him"')
        if _SCAN_THINKING_ABOUT_USER in text:
            reasons.append('"Thinking about user"')
        if not reasons:
            continue

        symbol = _enclosing_symbol(node, parents)
        if apply_allowlist and _is_allowlisted(rel_path, symbol):
            continue
        violations.append(
            f"{rel_path}:{node.lineno} (in {symbol!r}): {', '.join(reasons)} -- {text!r}"
        )
    return violations


def _scan_violations():
    violations = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        rel_path = path.relative_to(SRC_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        violations.extend(_scan_file_violations(source, rel_path))
    return violations


def test_no_hardcoded_pronoun_or_the_user_anywhere_in_src():
    """Static scan, independent of every dynamic test above: every string
    literal (including each f-string's literal segments) in every module
    under src/aura_life, minus docstrings and the explicit ALLOWLIST."""
    violations = _scan_violations()
    assert violations == [], "\n" + "\n".join(violations)


def test_scanner_flags_the_calendar_hint_as_it_was_before_the_fix():
    """The regression this fix round exists for: `f"The user's event..."`,
    verbatim as it read in `_scan_calendar_for_triggers` before this round's
    fix. Runs it through the REAL scan function (`_scan_file_violations`,
    the same one `test_no_hardcoded_pronoun_or_the_user_anywhere_in_src`
    calls) rather than a hand-rolled regex check, and never writes it to a
    real file -- it is parsed as a source string with a fake label."""
    pre_fix_source = (
        "class _C:\n"
        "    def _scan_calendar_for_triggers(self):\n"
        "        prompt_hint = (\n"
        "            f\"The user's event '{row['event_name']}' just happened.\"\n"
        "            f' Ask warmly how it went - you remembered it mattered to them.'\n"
        "        )\n"
    )
    violations = _scan_file_violations(pre_fix_source, "life_service.py (pre-fix snippet)")
    assert violations, "the scanner did not flag the pre-fix calendar hint"
    assert any('"the user"' in v for v in violations), violations


def test_allowlist_entries_still_exist_and_still_need_it():
    """Every ALLOWLIST entry names a real file, and (symbol given) a real
    top-level function/class/assignment in it -- an entry for code that was
    since removed, or renamed, is dead weight that silently widens the scan."""
    for rel_path, symbol in ALLOWLIST:
        path = SRC_ROOT / rel_path
        assert path.is_file(), f"allowlisted file does not exist: {rel_path}"
        if symbol is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names = {
            n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        } | {
            t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
            for t in n.targets if isinstance(t, ast.Name)
        } | {
            n.target.id for n in ast.walk(tree)
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
        }
        assert symbol in names, f"allowlisted symbol {symbol!r} not found in {rel_path}"
