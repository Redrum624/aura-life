"""A seeded service's private world is reproducible (Task 26 re-review note).

When a LifeService builds its own world (no ``world_environment=``) and the
host injected an rng, the world draws from its own stream derived from that
rng (label "world"), so two services built with the same seed see the same
weather. Without an injected rng the world draws from module ``random``, as
every engine does then (ruling T35-R1; its test is
``tests/test_rng_streams.py::test_a_service_without_an_rng_keeps_its_private_world_on_the_module_random``).
"""

import random
from datetime import datetime, timedelta

from aura_life import LifeService


def _weather_sequence(tmp_path, name, seed, steps=40):
    clock = {"now": datetime(2026, 10, 6, 9, 0)}
    svc = LifeService(
        db_path=str(tmp_path / f"{name}.db"),
        persona_id=name,
        rng=random.Random(seed),
    )
    svc._world.now = lambda: clock["now"]
    seen = []
    for _ in range(steps):
        clock["now"] += timedelta(hours=1)
        svc._world.tick()
        seen.append(svc._world.weather)
    return seen


def test_same_seed_same_private_world_weather(tmp_path):
    a = _weather_sequence(tmp_path, "a", seed=7)
    b = _weather_sequence(tmp_path, "b", seed=7)
    assert a == b


def test_the_private_world_draws_from_its_own_stream_not_the_service_rng(tmp_path):
    svc = LifeService(
        db_path=str(tmp_path / "c.db"), persona_id="c", rng=random.Random(7),
    )
    assert svc._world._rng is not svc._service_rng
    assert isinstance(svc._world._rng, random.Random)
