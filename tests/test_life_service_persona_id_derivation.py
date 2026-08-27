"""Deriving a persona id from ``db_path`` must not shadow an explicit one.

``_persist_activity_emotions`` derives the persona id from the *parent
directory* of ``db_path`` (the ``data/<persona>/life.db`` layout), and falls
back to the explicitly-passed ``persona_id`` when there is no such directory.

The fallback was written as ``if db_parent != "."``. For a bare relative
filename ``Path("mara.db").parent.name`` is the **empty string**, not ``"."`` —
so the guard passed, ``persona_id`` became ``""``, the explicit id was never
consulted, and every caller using a relative ``db_path`` (the README quickstart
among them) silently stopped persisting activity emotions while being told it
had "no persona_id".
"""

import logging

import pytest

from aura_life.life_service import LifeService


LOGGER_NAME = "aura_life.life_service"


def test_relative_db_path_falls_back_to_the_explicit_persona_id(
    tmp_path, monkeypatch, caplog
):
    """A bare relative db_path has no persona directory, so the explicitly
    supplied persona_id is the id to write under."""
    monkeypatch.chdir(tmp_path)
    svc = LifeService(db_path="mara.db", persona_id="mara")

    seen = []

    class _Recorder:
        def save_emotion(self, **kwargs):
            pass

    import aura_life.emotion.emotion_persistence as ep

    def _fake_get_emotion_persistence(persona_id, datastore=None):
        seen.append(persona_id)
        return _Recorder()

    monkeypatch.setattr(ep, "get_emotion_persistence", _fake_get_emotion_persistence)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        svc._persist_activity_emotions("reading", {"content": 0.5})

    assert seen == ["mara"], (
        "explicit persona_id was ignored for a relative db_path; "
        f"emotion persistence saw {seen!r}"
    )
    assert "no persona_id" not in caplog.text, (
        "warned about a missing persona_id on a service that was given one:\n"
        + caplog.text
    )


def test_dot_prefixed_relative_db_path_also_falls_back(tmp_path, monkeypatch):
    """``./mara.db`` yields a parent name of ``"."`` — the case the original
    guard did handle. Keep it handled."""
    monkeypatch.chdir(tmp_path)
    svc = LifeService(db_path="./mara.db", persona_id="mara")

    seen = []

    class _Recorder:
        def save_emotion(self, **kwargs):
            pass

    import aura_life.emotion.emotion_persistence as ep
    monkeypatch.setattr(
        ep,
        "get_emotion_persistence",
        lambda persona_id, datastore=None: seen.append(persona_id) or _Recorder(),
    )

    svc._persist_activity_emotions("reading", {"content": 0.5})

    assert seen == ["mara"]


def test_nested_db_path_still_derives_from_the_parent_directory(
    tmp_path, monkeypatch
):
    """The ``data/<persona>/life.db`` layout keeps deriving from the directory,
    which stays authoritative over the constructor argument."""
    db = tmp_path / "data" / "mara" / "life.db"
    db.parent.mkdir(parents=True)
    svc = LifeService(db_path=str(db), persona_id="mara")

    seen = []

    class _Recorder:
        def save_emotion(self, **kwargs):
            pass

    import aura_life.emotion.emotion_persistence as ep
    monkeypatch.setattr(
        ep,
        "get_emotion_persistence",
        lambda persona_id, datastore=None: seen.append(persona_id) or _Recorder(),
    )

    svc._persist_activity_emotions("reading", {"content": 0.5})

    assert seen == ["mara"]
