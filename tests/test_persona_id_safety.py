"""Persona ids reach the filesystem and the SQL text — prove they cannot escape.

Four sinks are covered:

* ``get_profile_db(persona_id)``             → ``<data_dir>/<persona_id>/profile.db``
* ``get_owner_device_id(persona_id, ...)``   → ``<data_dir>/<persona_id>/profile.db``
* ``get_emotion_persistence(persona_id, …)`` → ``<db_dir>/<persona_id>_emotions.db``
* ``ProfileDatabase.update_field(field, …)`` → ``UPDATE profile_core SET {field} = ?``

The first three built a path out of a caller-supplied id with no validation at
all, so ``../../../../Windows/Temp/pwned`` walked out of ``data_dir``; the first
two then *created* the traversed directory tree (``ProfileDatabase.__init__``
does ``parent.mkdir(parents=True)``) and the second opened whatever ``profile.db``
it landed on — the file that holds ``owner_device_id``, the multi-user isolation
key. The fourth interpolated the caller's column name straight into SQL.

The traversal tests deliberately nest ``data_dir`` several levels below
``tmp_path`` so that an *unfixed* run escapes into pytest's own temp tree rather
than into the real filesystem, and then assert the escaped location was never
touched.
"""

import contextlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from aura_life._safe_ids import safe_persona_id
from aura_life.emotion.emotion_persistence import (
    _persistence_managers,
    get_emotion_persistence,
)
from aura_life.personas.profile_db import (
    ProfileDatabase,
    get_owner_device_id,
    get_profile_db,
)


#: Ids that must be refused outright: traversal, absolute paths, drive letters,
#: UNC roots, separators, empties, and over-long ids.
HOSTILE_IDS = [
    "../../../../Windows/Temp/pwned",
    "..\\..\\..\\..\\Windows\\Temp\\pwned",
    "..",
    ".",
    "a/../../b",
    "sub/dir",
    "sub\\dir",
    "/etc/passwd",
    "\\etc\\passwd",
    "C:\\Windows\\Temp\\pwned",
    "c:pwned",
    "\\\\server\\share\\pwned",
    "",
    " ",
    "alice ",
    "alice.bak",
    "alice\x00",
    "x" * 65,
]

#: The proof-of-concept id from the audit.
TRAVERSAL_ID = "../../../../Windows/Temp/pwned"


@pytest.fixture
def data_dir(tmp_path):
    """A data_dir nested deep enough that a 4-level traversal stays in tmp_path."""
    d = tmp_path / "lvl1" / "lvl2" / "lvl3" / "lvl4" / "data"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def escape_target(tmp_path):
    """Where ``TRAVERSAL_ID`` lands when ``data_dir`` fails to contain it."""
    return tmp_path / "lvl1" / "Windows" / "Temp"


@contextlib.contextmanager
def host_config(data_dir):
    """Register a ``get_config`` hook, then restore the pristine hook state.

    Teardown is the recovery path the hooks docs describe (``reset()`` then
    ``defaults.install()``), so ``test_multi_instance``'s assertion that no hook
    but ``persona_now`` has a provider still holds however the suite is ordered.
    """
    from aura_life import defaults, hooks

    hooks.configure(get_config=lambda: SimpleNamespace(data_dir=data_dir))
    try:
        yield
    finally:
        hooks.reset()
        defaults.install()


@pytest.fixture(autouse=True)
def _clear_emotion_cache():
    """``get_emotion_persistence`` memoizes per persona id in a process global."""
    _persistence_managers.clear()
    yield
    _persistence_managers.clear()


# ----------------------------------------------------------------------
# The helper itself
# ----------------------------------------------------------------------

@pytest.mark.parametrize("pid", HOSTILE_IDS)
def test_safe_persona_id_rejects_rather_than_strips(pid):
    with pytest.raises(ValueError):
        safe_persona_id(pid)


@pytest.mark.parametrize("pid,expected", [
    ("alice", "alice"),
    ("Alice", "alice"),
    ("alice_2", "alice_2"),
    ("alice-2", "alice-2"),
    ("x" * 64, "x" * 64),
])
def test_safe_persona_id_accepts_and_lowercases_real_ids(pid, expected):
    assert safe_persona_id(pid) == expected


@pytest.mark.parametrize("bad", [None, 3, b"alice", Path("alice")])
def test_safe_persona_id_rejects_non_strings(bad):
    with pytest.raises(ValueError):
        safe_persona_id(bad)


# ----------------------------------------------------------------------
# Sink 1 — get_profile_db (creates the traversed tree: arbitrary write)
# ----------------------------------------------------------------------

def test_get_profile_db_refuses_to_escape_data_dir(data_dir, escape_target):
    with host_config(data_dir):
        with pytest.raises(ValueError):
            get_profile_db(TRAVERSAL_ID)
    assert not escape_target.exists(), (
        f"traversal created {escape_target}, outside data_dir {data_dir}"
    )


@pytest.mark.parametrize("pid", HOSTILE_IDS)
def test_get_profile_db_rejects_every_hostile_id(data_dir, pid):
    with host_config(data_dir):
        with pytest.raises(ValueError):
            get_profile_db(pid)


def test_get_profile_db_still_works_for_a_real_id(data_dir):
    with host_config(data_dir):
        db = get_profile_db("alice")
    assert (data_dir / "alice" / "profile.db").exists()
    assert db.get_name() is None


# ----------------------------------------------------------------------
# Sink 2 — get_owner_device_id (arbitrary read of the isolation key)
# ----------------------------------------------------------------------

def test_get_owner_device_id_refuses_to_escape_data_dir(data_dir, escape_target):
    # Plant a victim profile.db exactly where the traversal would land.
    victim = escape_target / "pwned"
    victim.mkdir(parents=True)
    _seed_profile(victim / "profile.db", owner_device_id="VICTIM-DEVICE")

    with pytest.raises(ValueError):
        get_owner_device_id(TRAVERSAL_ID, data_dir=data_dir)


@pytest.mark.parametrize("pid", HOSTILE_IDS)
def test_get_owner_device_id_rejects_every_hostile_id(data_dir, pid):
    with pytest.raises(ValueError):
        get_owner_device_id(pid, data_dir=data_dir)


def test_get_owner_device_id_still_reads_a_real_persona(data_dir):
    (data_dir / "alice").mkdir()
    _seed_profile(data_dir / "alice" / "profile.db", owner_device_id="DEV-1")
    assert get_owner_device_id("Alice", data_dir=data_dir) == "DEV-1"
    assert get_owner_device_id("nobody", data_dir=data_dir) == ""


# ----------------------------------------------------------------------
# Sink 3 — get_emotion_persistence (arbitrary *_emotions.db write)
# ----------------------------------------------------------------------

def test_get_emotion_persistence_refuses_to_escape_db_dir(data_dir, escape_target):
    with pytest.raises(ValueError):
        get_emotion_persistence(TRAVERSAL_ID, db_dir=data_dir)
    stray = escape_target / "pwned_emotions.db"
    assert not stray.exists(), f"traversal wrote {stray}, outside db_dir {data_dir}"
    assert TRAVERSAL_ID not in _persistence_managers


@pytest.mark.parametrize("pid", HOSTILE_IDS)
def test_get_emotion_persistence_rejects_every_hostile_id(data_dir, pid):
    with pytest.raises(ValueError):
        get_emotion_persistence(pid, db_dir=data_dir)


def test_get_emotion_persistence_still_works_for_a_real_id(data_dir):
    ep = get_emotion_persistence("alice", db_dir=data_dir)
    ep.save_emotion("joy", 0.9, "a real id still persists")
    assert (data_dir / "alice_emotions.db").exists()
    assert "joy" in ep.get_current_emotions()


# ----------------------------------------------------------------------
# Sink 4 — update_field (SQL identifier injection)
# ----------------------------------------------------------------------

@pytest.mark.parametrize("field", [
    "name = 'x', owner_device_id",            # rewrites the isolation column
    "owner_device_id = 'ATTACKER', name",
    "name = ?, owner_device_id",
    "name; DROP TABLE profile_core; --",
    "name = 'x' WHERE 1=1 --",
    "no_such_column",
    "",
    "1",
])
def test_update_field_rejects_crafted_field_names(tmp_path, field):
    path = tmp_path / "profile.db"
    db = ProfileDatabase(str(path))
    _seed_row(path, name="Alice", owner_device_id="OWNER-1")

    with pytest.raises(ValueError):
        db.update_field(field, "pwned")

    assert _read(path, "owner_device_id") == "OWNER-1"
    assert _read(path, "name") == "Alice"


def test_update_field_still_writes_a_real_column(tmp_path):
    path = tmp_path / "profile.db"
    db = ProfileDatabase(str(path))
    _seed_row(path, name="Alice", owner_device_id="OWNER-1")

    db.update_field("name", "Bob")

    assert _read(path, "name") == "Bob"
    assert _read(path, "owner_device_id") == "OWNER-1"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _seed_profile(path: Path, owner_device_id: str) -> None:
    ProfileDatabase(str(path))
    _seed_row(path, name="Victim", owner_device_id=owner_device_id)


def _seed_row(path: Path, name: str, owner_device_id: str) -> None:
    with contextlib.closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO profile_core (id, name, owner_device_id) "
            "VALUES (1, ?, ?)",
            (name, owner_device_id),
        )
        conn.commit()


def _read(path: Path, column: str):
    with contextlib.closing(sqlite3.connect(path)) as conn:
        return conn.execute(
            f"SELECT {column} FROM profile_core WHERE id = 1"
        ).fetchone()[0]
