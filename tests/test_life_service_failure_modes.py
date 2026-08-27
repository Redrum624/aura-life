"""Failure modes that used to be invisible: fail-open gates and silent swallows.

Two shapes, both of which look fine in a passing test suite and only show up as
"the feature never worked in production":

1. **Fail-open kill switches.** ``if not get_config().place_enabled: return``
   sat *inside* a ``try`` whose ``except Exception`` was a bare ``pass``. For any
   host that never registered the ``get_config`` hook — the default state —
   ``HookNotConfigured`` was swallowed and execution fell straight through, so the
   feature ran exactly as if the flag had been **on**. A kill switch must fail
   closed.

2. **Silent swallows.** ``except Exception: pass`` with no log at any level around
   host-provider calls and around DB loads. A broken host provider degraded three
   behaviours forever with zero signal, and a broad catch on a load path made a
   genuine read failure indistinguishable from an empty first-run table.

Nothing here asserts an exception is raised: the point is precisely that these
paths do not raise. The assertions are on **what was called** and on **the log
stream**.
"""

import logging
import sqlite3
from datetime import datetime

import pytest

from aura_life import hooks
from aura_life.life_service import LifeService
from aura_life.models import LifeEvent


LOGGER_NAME = "aura_life.life_service"


@pytest.fixture
def restore_hooks():
    saved = dict(hooks._registry)
    yield
    hooks._registry.clear()
    hooks._registry.update(saved)


class _Config:
    def __init__(self, place_enabled):
        self.place_enabled = place_enabled
        self.data_dir = None


def _svc(tmp_path, **kwargs):
    return LifeService(
        db_path=str(tmp_path / "life.db"),
        persona_id="testpersona",
        **kwargs,
    )


class _RecordingWeather:
    def __init__(self):
        self.calls = 0

    def get_current(self, lat, lon):
        self.calls += 1
        return None


def _placeable(svc):
    """Put the service past every guard *after* the place_enabled gate."""
    svc._is_ai = False
    svc._shared_world = False
    svc._place_location.current_lat = 45.5
    svc._place_location.current_lon = -73.6
    return svc


# --------------------------------------------------------------------------
# 1. The kill switch must fail closed
# --------------------------------------------------------------------------

def test_weather_gate_fails_closed_when_config_is_unreadable(tmp_path, restore_hooks):
    """No host has registered ``get_config`` — the overwhelmingly common state for
    a library consumer. Weather must stay off, not switch itself on."""
    hooks._registry.pop("get_config", None)
    weather = _RecordingWeather()
    svc = _placeable(_svc(tmp_path, weather_service=weather))

    svc._update_weather()

    assert weather.calls == 0


def test_weather_gate_stays_closed_when_place_is_disabled(tmp_path, restore_hooks):
    hooks.configure(get_config=lambda: _Config(place_enabled=False))
    weather = _RecordingWeather()
    svc = _placeable(_svc(tmp_path, weather_service=weather))

    svc._update_weather()

    assert weather.calls == 0


def test_weather_runs_when_place_is_enabled(tmp_path, restore_hooks):
    """The other half of the gate: a configured host that says yes still gets
    weather. Failing closed must not mean failing always."""
    hooks.configure(get_config=lambda: _Config(place_enabled=True))
    weather = _RecordingWeather()
    svc = _placeable(_svc(tmp_path, weather_service=weather))

    svc._update_weather()

    assert weather.calls == 1


def test_trip_gate_fails_closed_when_config_is_unreadable(tmp_path, restore_hooks, monkeypatch):
    hooks._registry.pop("get_config", None)
    svc = _placeable(_svc(tmp_path))

    picked = []
    monkeypatch.setattr(
        svc, "_pick_trip_destination", lambda *a, **k: picked.append(1) or None
    )
    svc._update_trip()

    assert picked == []
    # The per-day roll bookkeeping must not advance either — a disabled feature
    # writes nothing.
    assert not svc._trip_last_roll_date


def test_trip_gate_stays_closed_when_place_is_disabled(tmp_path, restore_hooks, monkeypatch):
    hooks.configure(get_config=lambda: _Config(place_enabled=False))
    svc = _placeable(_svc(tmp_path))

    picked = []
    monkeypatch.setattr(
        svc, "_pick_trip_destination", lambda *a, **k: picked.append(1) or None
    )
    svc._update_trip()

    assert picked == []


# --------------------------------------------------------------------------
# 2a. A broken host user-model provider must leave a trace
# --------------------------------------------------------------------------

def _exploding_provider(_persona_id):
    raise RuntimeError("host user-model provider is broken")


def test_broken_user_model_provider_is_reported_on_message(tmp_path, caplog):
    svc = _svc(tmp_path, user_model_provider=_exploding_provider)
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        svc.on_user_message("hello there, something interesting")
    assert "user_model_provider" in caplog.text


def test_broken_user_model_provider_is_reported_for_quiet_windows(tmp_path, caplog):
    svc = _svc(tmp_path, user_model_provider=_exploding_provider)
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        svc._report_user_model_failure("quiet_windows", RuntimeError("boom"))
    assert "quiet_windows" in caplog.text


def test_user_model_failure_is_not_a_per_tick_log_storm(tmp_path, caplog):
    """These sites run on the message and tick paths. One WARNING per site, then
    quiet — a permanent per-call warning would be its own defect."""
    svc = _svc(tmp_path, user_model_provider=_exploding_provider)
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        for _ in range(20):
            svc._report_user_model_failure("observe_message", RuntimeError("boom"))
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


# --------------------------------------------------------------------------
# 2b. A dead life trigger must leave a trace
# --------------------------------------------------------------------------

def test_excitement_share_trigger_failure_is_logged(tmp_path, caplog):
    """This whole trigger was wrapped in ``except Exception: pass`` with no log,
    so it could be permanently dead in production with zero signal — the same
    swallow shape as the calendar-scan defect."""
    def _broken(_persona_id):
        raise RuntimeError("follow-up manager is broken")

    svc = _svc(tmp_path, follow_up_provider=_broken)
    event = LifeEvent(
        event_type="achievement",
        title="something good",
        description="it went well",
        share_urgency=0.9,
        emotional_impact={"proud": 0.6},
    )

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        svc._bridge_life_event(event)

    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "a dead EXCITEMENT_SHARE trigger left no trace at all"
    )


# --------------------------------------------------------------------------
# 2c. Load paths: a missing table is normal, a corrupt one is not
# --------------------------------------------------------------------------

def _corrupt(tmp_path, sql, params=()):
    with sqlite3.connect(str(tmp_path / "life.db")) as conn:
        conn.execute(sql, params)
        conn.commit()


def test_corrupt_identity_values_row_is_logged_not_swallowed(tmp_path, caplog):
    svc = _svc(tmp_path)
    _corrupt(
        tmp_path,
        "INSERT INTO life_values (name, salience, tested, formed_at) VALUES (?, ?, ?, ?)",
        ("curiosity", 0.5, 0, "not-a-timestamp"),
    )

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        svc._load_state()

    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "a corrupt life_values row was discarded with no log at any level"
    )


def test_corrupt_behavioral_tendencies_row_is_logged(tmp_path, caplog):
    svc = _svc(tmp_path)
    # This table is created lazily by _save_identity, not by _init_database.
    svc._save_identity()
    _corrupt(
        tmp_path,
        "INSERT OR REPLACE INTO life_behavioral_tendencies (id, data) VALUES (1, ?)",
        ("{not valid json",),
    )

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        svc._load_state()

    assert any(r.levelno >= logging.WARNING for r in caplog.records)


def test_a_missing_table_is_still_silent(tmp_path, caplog):
    """The rationale for the broad catch was real — a first run has no table. That
    case must stay quiet, or the narrowing just trades one defect for noise."""
    svc = _svc(tmp_path)
    with sqlite3.connect(str(tmp_path / "life.db")) as conn:
        conn.execute("DROP TABLE life_values")
        conn.execute("DROP TABLE life_locations")
        conn.commit()

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        svc._load_state()

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_corrupt_location_row_does_not_truncate_the_rest(tmp_path, caplog):
    """A broad catch around the whole row loop meant one malformed row silently
    cut the persona's known places short mid-load."""
    svc = _svc(tmp_path)
    with sqlite3.connect(str(tmp_path / "life.db")) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO life_locations "
            "(key, name, place_type, description, source, familiarity, visit_count, last_visit) "
            "VALUES ('broken_place', 'Broken', 'other', '', 'user', NULL, NULL, NULL)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO life_locations "
            "(key, name, place_type, description, source, familiarity, visit_count, last_visit) "
            "VALUES ('zzz_good_place', 'Good', 'cafe', '', 'user', 0.4, 2, NULL)"
        )
        conn.commit()

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        svc._load_state()

    assert "zzz_good_place" in svc._location_registry, (
        "a bad row earlier in the result set swallowed every row after it"
    )


# --------------------------------------------------------------------------
# 3. No invented persona id
# --------------------------------------------------------------------------

def test_emotion_persistence_does_not_invent_a_persona_id(tmp_path, monkeypatch, caplog):
    """With a bare db_path and no persona_id there is no id to write under. The
    old code substituted a hardcoded persona name and wrote there silently."""
    monkeypatch.chdir(tmp_path)
    svc = LifeService(db_path="life.db", persona_id=None)

    calls = []
    import aura_life.emotion.emotion_persistence as ep
    monkeypatch.setattr(
        ep, "get_emotion_persistence",
        lambda *a, **k: calls.append(a) or pytest.fail("resolved a persona id from nothing"),
    )

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        svc._persist_activity_emotions("reading", {"content": 0.5})

    assert calls == []


# --------------------------------------------------------------------------
# 4. No invented database path
# --------------------------------------------------------------------------

def test_no_db_path_and_no_persona_id_is_refused(tmp_path, monkeypatch, restore_hooks):
    """``db_path`` used to default to the bare relative name ``"life.db"``, so a
    service built with no arguments wrote its database into whatever directory
    the host process happened to be in — and two personas started from the same
    CWD silently shared one file."""
    monkeypatch.chdir(tmp_path)
    hooks._registry.pop("get_config", None)

    with pytest.raises(ValueError):
        LifeService()

    assert not (tmp_path / "life.db").exists(), "a database was created anyway"


def test_persona_id_without_a_configured_data_dir_is_refused(tmp_path, monkeypatch, restore_hooks):
    monkeypatch.chdir(tmp_path)
    hooks._registry.pop("get_config", None)

    with pytest.raises(ValueError):
        LifeService(persona_id="mara")

    assert not (tmp_path / "life.db").exists()


def test_db_path_resolves_under_the_host_data_dir(tmp_path, restore_hooks):
    class _Cfg:
        data_dir = None
        place_enabled = False

    _Cfg.data_dir = str(tmp_path / "hostdata")
    hooks.configure(get_config=lambda: _Cfg())

    svc = LifeService(persona_id="mara")

    assert svc._db_path == str(tmp_path / "hostdata" / "mara" / "life.db")
    assert (tmp_path / "hostdata" / "mara" / "life.db").exists()


def test_an_explicit_db_path_still_wins(tmp_path, restore_hooks):
    explicit = str(tmp_path / "explicit.db")
    svc = LifeService(db_path=explicit, persona_id="mara")
    assert svc._db_path == explicit
