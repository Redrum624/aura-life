"""The user over time (humanness Task 16b, spec section 4.8): relationship
depth, the style hint, absence.

"Relationship depth comes from reciprocity and time and can regress. Absence
has a course by ``attachment_style``." Depth (0..1) grows on contact days and
on disclosures the other side answers, regresses after 7 days without a user
turn, and sets the relationship stage (ruling T16-R6: the names stay). The
style hint is the persona's own communication traits plus one distance line
by depth. ``LifeService.after_absence`` is her ``after_absence`` state, by
her attachment style (ruling T16-R7: computed, not rendered).
"""

import contextlib
import random
import sqlite3
from datetime import datetime, timedelta

import pytest

from aura_life import LifeService
from aura_life.expression import relationship as rel
from aura_life.expression.expression_system import DISTANCE_LINES, ExpressionSystem
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.world import WorldEnvironment

WORLD_NOW = datetime(2031, 3, 4, 9, 30)
BANNED = ("complete sentences", "lol", "emoji")
PLAIN_TRAITS = ["Natural and conversational", "Warm and engaging"]


def _service(tmp_path, name="ada", **definition) -> LifeService:
    clock = {"now": WORLD_NOW}
    svc = LifeService(
        db_path=str(tmp_path / f"{name}.db"), persona_id=name,
        definition=PersonalityDefinition(id=name, **definition) if definition else None,
        world_environment=WorldEnvironment(now=lambda: clock["now"], seed=5),
        rng=random.Random(5),
    )
    svc._test_clock = clock
    return svc


def _at(svc, **delta):
    svc._test_clock["now"] = WORLD_NOW + timedelta(**delta)


def _share(svc):
    """She tells the user something of her own life (``mark_shared``)."""
    svc._create_shareable_from_text("Something nice happened")
    experience = svc._get_unshared_experiences()[-1]
    assert svc.mark_shared(experience.share_id) is True


# ----------------------------------------------------------------------
# Depth: reciprocity and time, regressing in silence
# ----------------------------------------------------------------------

def test_ten_silent_days_lower_depth(tmp_path):
    svc = _service(tmp_path)
    for day in range(6):
        _at(svc, days=day)
        svc.observe_user_turn("ok", disclosure=1.0)
        _share(svc)
    built = svc.relationship_depth
    assert built > 0.0
    _at(svc, days=5 + 6.9)                   # under a week of silence: kept
    assert svc.relationship_depth == pytest.approx(built)
    _at(svc, days=5 + 10)                    # ten silent days: lower
    assert svc.relationship_depth < built
    assert svc.relationship_depth == pytest.approx(built * (1 - rel.REGRESSION_PER_DAY) ** 3)
    regressed = svc.relationship_depth
    svc.observe_user_turn("hey")             # her next turn keeps it, plus the day
    assert svc.relationship_depth == pytest.approx(regressed + rel.CONTACT_DAY_GAIN * (1 - regressed))


def test_depth_comes_from_reciprocity_and_contact_days_not_messages(tmp_path):
    chatty = _service(tmp_path, "chatty")
    for _ in range(60):
        chatty.observe_user_turn("ok")
    one_day = rel.CONTACT_DAY_GAIN
    assert chatty.relationship_depth == pytest.approx(one_day)          # one contact day
    one_sided = _service(tmp_path, "one-sided")
    for _ in range(5):
        one_sided.observe_user_turn("ok", disclosure=1.0)
    assert one_sided.relationship_depth == pytest.approx(one_day)       # nobody answered
    answered = _service(tmp_path, "answered")
    answered.observe_user_turn("ok", disclosure=1.0)
    _share(answered)                                                     # she answers theirs
    expected = one_day + rel.DISCLOSURE_GAIN * (1 - one_day)
    assert answered.relationship_depth == pytest.approx(expected)
    first = _service(tmp_path, "she-first")
    first.observe_user_turn("ok")
    _share(first)                                                        # hers, open
    first.observe_user_turn("ok", disclosure=0.5)                        # they answer half
    assert first.relationship_depth == pytest.approx(one_day + rel.DISCLOSURE_GAIN * 0.5 * (1 - one_day))
    days = _service(tmp_path, "days")
    for day in range(3):
        _at(days, days=day)
        days.observe_user_turn("ok")
    assert days.relationship_depth == pytest.approx(1 - (1 - one_day) ** 3)


def test_a_week_of_silence_can_lower_the_stage_before_the_next_turn(tmp_path):
    svc = _service(tmp_path)
    for day in range(8):
        _at(svc, days=day)
        svc.observe_user_turn("ok")
    assert svc.expression._style.relationship_stage == "comfortable"
    assert svc._relationship_is_close() is True
    _at(svc, days=7 + 20)
    svc._on_energy_tick()
    assert svc.relationship_depth < rel.STAGE_DEPTHS["comfortable"]
    assert svc.expression._style.relationship_stage == "early"
    assert svc._relationship_is_close() is False


def test_depth_is_saved_and_loaded(tmp_path):
    # Fix round 1 (G1): each open disclosure is saved while it is open (both
    # were 0 at the one save before, so a lost one passed).
    svc = _service(tmp_path)
    svc.observe_user_turn("ok", disclosure=1.0)
    _share(svc)
    _at(svc, days=3)
    svc.observe_user_turn("hello again", disclosure=0.6)      # theirs, still open at the save
    assert svc.expression._user_open == pytest.approx(0.6)
    svc._save_state()
    again = _service(tmp_path)
    again._load_state()
    _at(again, days=3)
    assert again.relationship_depth == pytest.approx(svc.relationship_depth)
    assert again.expression._user_open == pytest.approx(0.6)
    assert again.expression.reunion_hours == pytest.approx(72.0)
    _share(again)                                              # answers their 0.6; 0.4 of hers stays open
    assert again.expression._her_open == pytest.approx(0.4)
    again._save_state()
    third = _service(tmp_path)
    third._load_state()
    assert third.expression._her_open == pytest.approx(0.4)
    assert third.expression._user_open == 0.0


#: ``life_expression_state`` as Task 16b found it (976526b): no depth_state.
PRE_16B_EXPRESSION_TABLE = """
    CREATE TABLE life_expression_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        interaction_count INTEGER DEFAULT 0,
        formality REAL DEFAULT 0.7,
        avg_message_length TEXT DEFAULT 'measured',
        emoji_frequency REAL DEFAULT 0.2,
        humor_density REAL DEFAULT 0.2,
        vulnerability_openness REAL DEFAULT 0.2,
        relationship_stage TEXT DEFAULT 'early',
        last_message_at TEXT,
        avg_response_time REAL DEFAULT 0.0,
        response_times TEXT DEFAULT '[]'
    )
"""


def test_a_database_from_before_16b_is_migrated_and_saves(tmp_path):
    """Fix round 1 (G2), ruling T16-R6 on a real old table: a database whose
    ``life_expression_state`` has no ``depth_state`` column gains it at the
    next start, loads its stage's depth, saves (an INSERT naming the column
    raised before the migration) and loads that save again."""
    _service(tmp_path)._save_state()
    with contextlib.closing(sqlite3.connect(str(tmp_path / "ada.db"))) as conn:
        conn.execute("DROP TABLE life_expression_state")
        conn.execute(PRE_16B_EXPRESSION_TABLE)
        conn.execute("INSERT INTO life_expression_state (id, interaction_count, relationship_stage) "
                     "VALUES (1, 240, 'deep')")
        conn.commit()
    again = _service(tmp_path)                                 # its start migrates the table
    again._load_state()
    assert again.relationship_depth == pytest.approx(rel.STAGE_DEPTHS["deep"])
    again._save_state()
    with contextlib.closing(sqlite3.connect(str(tmp_path / "ada.db"))) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(life_expression_state)")}
    assert "depth_state" in columns
    third = _service(tmp_path)
    third._load_state()
    assert third.relationship_depth == pytest.approx(rel.STAGE_DEPTHS["deep"])
    assert third.expression._style.relationship_stage == "deep"
    assert third._relationship_is_close() is True


def test_her_status_gives_the_depth_now(tmp_path):
    """Fix round 1 (S1): ``get_status()["expression"]["depth"]`` is the depth
    now, regressed by the silence, as ``relationship_depth`` and the export
    give it (it gave the depth of the user's last turn)."""
    svc = _service(tmp_path)
    for day in range(10):
        _at(svc, days=day)
        svc.observe_user_turn("ok")
    _at(svc, days=9 + 20)
    svc._on_energy_tick()
    status = svc.get_status()["expression"]
    assert status["depth"] == pytest.approx(round(svc.relationship_depth, 3))
    assert status["depth"] == svc.export_outer_state()["expression"]["depth"]
    assert status["depth"] < round(svc.expression.depth, 3)    # the silence shows
    assert status["relationship_stage"] == rel.stage_for(svc.relationship_depth)


def test_a_stage_gained_never_moves_her_style_back():
    """Fix round 1 (C1): a stage gained moves formality down and emoji,
    humour and openness up, each toward its stage's bound and never back: a
    value already past the bound stays (openness 0.6 fell to comfortable's
    0.5; on a regain formality 0.2 rose to its 0.3)."""
    fresh = ExpressionSystem()
    fresh._set_stage("comfortable")                             # below the bounds: as before
    assert fresh._style.formality == pytest.approx(0.7 - 0.15)
    assert fresh._style.emoji_frequency == pytest.approx(0.3)
    assert fresh._style.humor_density == pytest.approx(0.3)
    assert fresh._style.vulnerability_openness == pytest.approx(0.3)
    for stage in ("comfortable", "deep"):
        past = ExpressionSystem()
        past._style.formality, past._style.emoji_frequency = 0.05, 0.65
        past._style.humor_density, past._style.vulnerability_openness = 0.75, 0.85
        before = (0.05, 0.65, 0.75, 0.85)
        past._set_stage(stage)
        style = past._style
        assert (style.formality, style.emoji_frequency, style.humor_density,
                style.vulnerability_openness) == before, stage


def test_the_disclosure_cap_and_the_hurt_point_are_in_the_constants_block(monkeypatch):
    """Fix round 1 (R3), ruling T16-R3: the open-disclosure cap and the point
    of the course where its second half begins are constants of the block,
    with their source in the module's table, and the code reads them."""
    from aura_life.expression import expression_system

    assert rel.OPEN_DISCLOSURE_CAP == 1.0 and rel.SECOND_HALF_FROM == 0.5
    assert "OPEN_DISCLOSURE_CAP" in rel.__doc__ and "SECOND_HALF_FROM" in rel.__doc__
    es = ExpressionSystem()
    for _ in range(3):
        es.note_user_turn(WORLD_NOW, WORLD_NOW, 1.0)            # one-sided: banked up to the cap
    assert es._user_open == rel.OPEN_DISCLOSURE_CAP
    assert rel.after_absence(48, "anxious", ongoing=True).feelings == ("worried",)   # course 0.25
    monkeypatch.setattr(rel, "SECOND_HALF_FROM", 0.2)
    assert rel.after_absence(48, "anxious", ongoing=True).feelings == ("hurt",)
    monkeypatch.setattr(expression_system, "OPEN_DISCLOSURE_CAP", 2.0)
    more = ExpressionSystem()
    for _ in range(3):
        more.note_user_turn(WORLD_NOW, WORLD_NOW, 1.0)
    assert more._user_open == 2.0
    for _ in range(4):
        more.note_her_disclosure(WORLD_NOW, WORLD_NOW)          # answers their 2, then banks 2 of hers
    assert more._her_open == 2.0


# ----------------------------------------------------------------------
# T16-R6: names kept; an old save maps its stage to a depth
# ----------------------------------------------------------------------

@pytest.mark.parametrize("stage", ["early", "comfortable", "deep"])
def test_an_old_save_loads_to_the_depth_its_stage_maps_to(tmp_path, stage):
    """Ruling T16-R6: a save from before Task 16b (a stage from a message
    count, no depth) loads to the depth its stage begins at --
    ``relationship.STAGE_DEPTHS``: early 0, comfortable 1/3, deep 2/3 -- with
    the same stage, and ``_relationship_is_close`` reads it as before."""
    es = ExpressionSystem.from_dict({"relationship_stage": stage, "interaction_count": 240})
    assert es.depth == rel.STAGE_DEPTHS[stage]
    assert es._style.relationship_stage == stage
    svc = _service(tmp_path)
    svc.observe_user_turn("ok")
    svc._save_state()
    with contextlib.closing(sqlite3.connect(str(tmp_path / "ada.db"))) as conn:
        conn.execute("UPDATE life_expression_state SET depth_state = NULL, relationship_stage = ?", (stage,))
        conn.commit()
    again = _service(tmp_path)
    again._load_state()
    assert again.relationship_depth == pytest.approx(rel.STAGE_DEPTHS[stage])
    assert again.expression._style.relationship_stage == stage
    # the stage read back from that depth is the same one
    again.expression.refresh_stage(again._world_clock()(), again.last_user_turn_at)
    assert again.expression._style.relationship_stage == stage
    assert again._relationship_is_close() is (stage in ("comfortable", "deep"))


def test_the_names_stay_and_the_stage_is_read_from_depth(tmp_path):
    svc = _service(tmp_path)
    exported = svc.export_outer_state()["expression"]
    assert {"style_hint", "relationship_stage"} <= set(exported)
    assert exported["style_hint"] == svc.expression.get_style_hint()
    seen = []
    for day in range(23):
        _at(svc, days=day)
        svc.observe_user_turn("ok")
        stage = svc.expression._style.relationship_stage
        assert stage == rel.stage_for(svc.relationship_depth)
        seen.append(stage)
    assert set(seen) == {"early", "comfortable", "deep"}
    assert seen == sorted(seen, key=rel.STAGES.index)
    assert svc.export_outer_state()["expression"]["depth"] == pytest.approx(round(svc.relationship_depth, 3))


# ----------------------------------------------------------------------
# The style hint: her own traits plus one distance line by depth
# ----------------------------------------------------------------------

@pytest.mark.parametrize("stage", ["early", "comfortable", "deep"])
def test_no_style_hint_has_the_banned_phrases_unless_her_traits_say_so(stage):
    plain = ExpressionSystem(communication_traits=PLAIN_TRAITS)
    plain._set_stage(stage)
    hint = plain.get_style_hint()
    assert not [phrase for phrase in BANNED if phrase in hint.lower()], hint
    assert hint.startswith("Natural and conversational. Warm and engaging. ")
    assert hint.endswith(DISTANCE_LINES[stage])
    hers = ExpressionSystem(communication_traits=["Uses emoji freely", "says lol a lot"])
    hers._set_stage(stage)
    assert "emoji" in hers.get_style_hint() and "Says lol a lot." in hers.get_style_hint()


def test_every_distance_line_is_free_of_register():
    for line in DISTANCE_LINES.values():
        assert not [phrase for phrase in BANNED if phrase in line.lower()], line
    assert "personal" in DISTANCE_LINES["early"]          # disclosure
    assert "tease" in DISTANCE_LINES["comfortable"]       # teasing
    assert "inside jokes" in DISTANCE_LINES["deep"]       # inside jokes


def test_the_service_hint_is_her_definitions_traits(tmp_path):
    svc = _service(tmp_path, communication_traits=PLAIN_TRAITS)
    assert svc.expression.get_style_hint() == "Natural and conversational. Warm and engaging. " + DISTANCE_LINES["early"]
    svc.observe_user_turn("ok")
    svc._save_state()
    again = _service(tmp_path, communication_traits=PLAIN_TRAITS)
    again._load_state()
    assert again.expression.get_style_hint().startswith("Natural and conversational.")


# ----------------------------------------------------------------------
# Absence, by attachment style
# ----------------------------------------------------------------------

def _away(tmp_path, style, hours, name=None):
    svc = _service(tmp_path, name or f"{style}-{hours}", attachment_style=style)
    svc.observe_user_turn("ok")
    _at(svc, hours=hours)
    return svc


def test_after_three_days_the_anxious_persona_feels_it_more_than_the_avoidant(tmp_path):
    anxious = _away(tmp_path, "anxious", 72).after_absence
    avoidant = _away(tmp_path, "avoidant", 72).after_absence
    secure = _away(tmp_path, "secure", 72).after_absence
    assert anxious.intensity > avoidant.intensity > 0.0
    assert anxious.feelings == ("worried",)
    assert avoidant.feelings == ("indifferent",)                  # notices, stays cool
    assert set(secure.feelings) == {"warm", "curious"}            # glad and curious
    assert anxious.ongoing and anxious.hours == pytest.approx(72.0)


def test_the_anxious_course_is_worry_then_hurt(tmp_path):
    states = [_away(tmp_path, "anxious", hours).after_absence for hours in (12, 48, 120, 160, 400)]
    assert [s.feelings for s in states] == [("worried",), ("worried",), ("hurt",), ("hurt",), ("hurt",)]
    intensities = [s.intensity for s in states]
    assert intensities == sorted(intensities) and intensities[-1] == pytest.approx(1.0)
    assert intensities[-2] < intensities[-1]


def test_no_absence_before_eight_hours_or_before_any_turn(tmp_path):
    assert _service(tmp_path, "new").after_absence is None
    assert _away(tmp_path, "anxious", 7.9).after_absence is None
    assert _away(tmp_path, "anxious", 8.1).after_absence is not None
    assert rel.after_absence(7.9, "anxious", ongoing=False) is None      # the function Task 18 may call
    assert rel.after_absence(8.0, "anxious", ongoing=False).intensity == 0.0
    assert _away(tmp_path, "", 72).after_absence.attachment_style == rel.DEFAULT_ATTACHMENT_STYLE


def test_the_absence_just_ended_is_her_state_in_that_conversation(tmp_path):
    svc = _away(tmp_path, "anxious", 72)
    svc.observe_user_turn("hey, I'm back")
    back = svc.after_absence
    assert back is not None and back.ongoing is False and back.hours == pytest.approx(72.0)
    _at(svc, hours=72, minutes=10)
    svc.observe_user_turn("how have you been?")
    assert svc.after_absence == back                          # the same conversation
    _at(svc, hours=72, minutes=45)
    assert svc.after_absence is None                          # that conversation is over
    svc.observe_user_turn("one more thing")
    assert svc.after_absence is None                          # a new one, after no absence


# ----------------------------------------------------------------------
# T16-R7: computed, not rendered
# ----------------------------------------------------------------------

def test_after_absence_is_a_read_only_accessor_and_an_export_key(tmp_path, monkeypatch):
    svc = _away(tmp_path, "anxious", 72)
    with pytest.raises(AttributeError):
        svc.after_absence = None
    assert svc.export_outer_state()["expression"]["after_absence"] == svc.after_absence.as_dict()
    assert _service(tmp_path, "none").export_outer_state()["expression"]["after_absence"] is None
    # nothing renders it: her context and style hint are the same without it
    context, hint = svc.get_life_context(), svc.expression.get_style_hint()
    monkeypatch.setattr(LifeService, "after_absence", property(lambda self: None))
    assert svc.get_life_context() == context
    assert svc.expression.get_style_hint() == hint
