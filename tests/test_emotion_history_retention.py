"""`emotion_persistence`'s two unbounded collections stay bounded.

Both grew for the lifetime of the process and neither had any way to shrink:

* ``emotion_history`` — one row per ``save_emotion`` call, forever. The only
  reader asks for the newest 20; the only delete was the full-wipe ``reset()``.
* ``_persistence_managers`` — a process-global cache with no eviction, TTL or
  clear function, holding every persona ever touched along with its loaded
  ``_emotions`` dict and its datastore reference.
"""

import contextlib
import sqlite3

import pytest

import aura_life.emotion.emotion_persistence as ep_mod
from aura_life.emotion.emotion_persistence import (
    HISTORY_MAX_ROWS,
    _persistence_managers,
    clear_emotion_persistence,
    get_emotion_persistence,
)

#: The shipped cap is 500. Every `save_emotion` opens, commits and closes its own
#: connection (~7 ms), so exercising the real number would cost this file ten
#: seconds to prove something a small cap proves identically. The prune itself is
#: free -- measured at 600 saves, the difference with and against it is inside the
#: noise -- so shrinking the cap changes the runtime, not what is under test.
TEST_CAP = 25


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    monkeypatch.setattr(ep_mod, "HISTORY_MAX_ROWS", TEST_CAP)
    _persistence_managers.clear()
    yield
    _persistence_managers.clear()


def test_the_shipped_cap_is_a_real_bound():
    """Guards the constant itself, which every other test here monkeypatches."""
    assert isinstance(HISTORY_MAX_ROWS, int) and 0 < HISTORY_MAX_ROWS <= 10_000


def _history_rows(db_path) -> int:
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        return conn.execute("SELECT COUNT(*) FROM emotion_history").fetchone()[0]


def test_emotion_history_is_capped(tmp_path):
    ep = get_emotion_persistence("alice", db_dir=tmp_path)
    for i in range(TEST_CAP + 120):
        ep.save_emotion(f"joy_{i}", 0.5, f"event {i}")

    db_path = tmp_path / "alice_emotions.db"
    assert _history_rows(db_path) == TEST_CAP


def test_the_newest_rows_are_the_ones_kept(tmp_path):
    ep = get_emotion_persistence("alice", db_dir=tmp_path)
    for i in range(TEST_CAP + 5):
        ep.save_emotion(f"joy_{i}", 0.5, f"event {i}")

    newest = ep.get_emotional_history(limit=1)[0]
    assert newest["caused_by"] == f"event {TEST_CAP + 4}"

    with contextlib.closing(sqlite3.connect(tmp_path / "alice_emotions.db")) as conn:
        oldest_kept = conn.execute(
            "SELECT caused_by FROM emotion_history ORDER BY rowid ASC LIMIT 1"
        ).fetchone()[0]
    assert oldest_kept == "event 5", "prune dropped the wrong end of the table"


def test_pruning_does_not_disturb_current_emotions(tmp_path):
    ep = get_emotion_persistence("alice", db_dir=tmp_path)
    for i in range(TEST_CAP + 10):
        ep.save_emotion("joy", 0.8, f"event {i}")
    assert "joy" in ep.get_current_emotions()


def test_clear_drops_one_persona(tmp_path):
    get_emotion_persistence("alice", db_dir=tmp_path)
    get_emotion_persistence("bob", db_dir=tmp_path)
    assert set(_persistence_managers) == {"alice", "bob"}

    assert clear_emotion_persistence("Alice") == 1
    assert set(_persistence_managers) == {"bob"}
    assert clear_emotion_persistence("alice") == 0, "clearing twice must be a no-op"


def test_clear_drops_everything(tmp_path):
    get_emotion_persistence("alice", db_dir=tmp_path)
    get_emotion_persistence("bob", db_dir=tmp_path)

    assert clear_emotion_persistence() == 2
    assert _persistence_managers == {}


def test_clear_refuses_a_malformed_id():
    with pytest.raises(ValueError):
        clear_emotion_persistence("../../../../Windows/Temp/pwned")
