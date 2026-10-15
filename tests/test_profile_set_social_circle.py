"""``ProfileDatabase.set_social_circle`` replaces ONLY the circle rows.

The only other writers of ``profile_social_circle`` are the two full-profile saves,
which rewrite every column; a host that wants to add people to an existing persona
must not have to round-trip the whole profile (that corrupts sleep times,
languages and the TTS profile).
"""

import sqlite3

import pytest

from aura_life.personas.profile_db import ProfileDatabase

CREATE = {
    "name": "Zed", "age": 31, "occupation": "nurse", "tts_profile": "x",
    "voice_profile": "vp", "bedtime": "22:30", "wake_time": "6:15",
    "persona_type": "ai", "core_traits": ["a", "b"], "interests": ["x"],
    "social_circle": [{"name": "Old", "relationship": "cousin"}],
}

NEW = [
    {"name": "Maya", "relationship": "best friend", "personality_brief": "bubbly",
     "shared_interests": "hiking, film", "contact_frequency": "daily"},
    {"name": "Jo", "relationship": "sister", "personality": "dry", "shared_interests": ["chess", "tea"]},
]


@pytest.fixture
def db(tmp_path):
    d = ProfileDatabase(str(tmp_path / "profile.db"))
    d.save_from_create_request(CREATE)
    return d


def _dump(path, skip="profile_social_circle"):
    conn = sqlite3.connect(path)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: conn.execute(f"SELECT * FROM {t}").fetchall() for t in tables if t not in (skip, "sqlite_sequence")}
    finally:
        conn.close()


def test_replaces_circle_and_reads_back(db):
    db.set_social_circle(NEW)
    for data in (db.load(), db.load_raw()):
        assert data["social_circle"] == [
            {"name": "Maya", "relationship": "best friend", "personality": "bubbly", "shared_interests": "hiking, film"},
            {"name": "Jo", "relationship": "sister", "personality": "dry", "shared_interests": "chess, tea"},
        ]


def test_nothing_else_changes(db):
    before = _dump(db._db_path)
    db.set_social_circle(NEW)
    assert _dump(db._db_path) == before


def test_rollback_on_failure_keeps_old_circle(db):
    bad = [NEW[0], {"relationship": "no name"}]
    with pytest.raises(ValueError):
        db.set_social_circle(bad)
    assert [n["name"] for n in db.load_raw()["social_circle"]] == ["Old"]


def test_failure_mid_write_rolls_back(db, monkeypatch):
    conn = sqlite3.connect(db._db_path)
    conn.execute("CREATE TRIGGER boom BEFORE INSERT ON profile_social_circle WHEN NEW.name = 'Boom' "
                 "BEGIN SELECT RAISE(ABORT, 'boom'); END")
    conn.commit(); conn.close()
    with pytest.raises(sqlite3.DatabaseError):
        db.set_social_circle([NEW[0], {"name": "Boom"}])
    assert [n["name"] for n in db.load_raw()["social_circle"]] == ["Old"]


def test_empty_list_clears(db):
    db.set_social_circle([])
    assert db.load_raw()["social_circle"] == []
