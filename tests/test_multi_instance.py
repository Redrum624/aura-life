"""Task 6 — many ``LifeService`` instances in one process, no host application.

The origin host runs exactly one persona per process, behind a bridge that fills
every host hook. The second consumer of this library is a **sandbox**: N agents
living in one shared world under an LLM overseer, with no host anywhere. Nothing in the
extraction so far has exercised that shape, so this module is where the library
is driven purely as a library for the first time.

The property under test, in one sentence: *three ``LifeService`` instances,
sharing one ``WorldEnvironment``, tick to completion without a host and keep
their state to themselves.*

Two traps this file is built around:

1. ``LifeScheduler.force_tick`` catches every exception a tick handler raises and
   only ``logger.error``s it. A test that asserted "did not raise" would pass
   while all five ticks failed on every round. So the assertions are on the
   **log stream** (no ``ERROR`` records) and on **evidence of work** (all five
   ``last_ticks`` stamped, private state moved, rows on disk) — never on the
   absence of an exception.
2. An injected ``WorldEnvironment`` is never ticked by ``LifeService``
   (``life_service.py`` skips its own ``self._world.tick()`` when
   ``_shared_world`` is set). The caller owns the shared clock, so the rounds
   below tick the world themselves.

``svc.start()`` is deliberately never called: it spawns an APScheduler thread and
a daemon tick loop. ``_init_database()`` runs inside ``__init__``, so forced ticks
work on a freshly constructed service. ``db_path`` is a real temp file per agent —
``:memory:`` cannot work here, because the schema is created on a connection that
is then closed and every later connection would see an empty database.
"""

import copy
import logging
import sqlite3
import sys

import pytest

from aura_life.life_service import LifeService
from aura_life.world import WorldEnvironment

#: The origin host's top-level packages. If any of these are importable in the
#: test process, the library is not actually being exercised standalone.
HOST_PACKAGES = ("config", "services", "data", "engine")

AGENT_COUNT = 3

#: Ten rounds is enough for every subsystem to tick several times (energy decay,
#: a plan generation, goal evaluation, activity selection) while keeping the
#: whole module under a couple of seconds.
ROUNDS = 10


def _make(tmp_path, pid, world):
    """A sandbox agent: its own database, its own id, the shared world.

    No ``user_model_provider``, no ``follow_up_provider``, no configured hooks —
    this is exactly the construction path the sandbox will use. Every argument is
    passed by keyword: ``LifeService.__init__`` takes 18 positional parameters and
    ``persona_id`` is the ninth.
    """
    return LifeService(
        db_path=str(tmp_path / f"{pid}.db"),
        persona_id=pid,
        world_environment=world,
        occupation="baker",
    )


def _errors(caplog):
    """Every ``ERROR``-or-worse record captured so far, formatted for a failure."""
    return [
        f"{r.name}: {r.getMessage()}"
        for r in caplog.records
        if r.levelno >= logging.ERROR
    ]


def _private_state(status):
    """``get_status()`` minus the two parts that are not agent-private.

    ``world`` is the shared environment (identical across agents by design) and
    ``scheduler`` is tick bookkeeping stamped with wall-clock times. Dropping both
    means a before/after difference in what remains can only come from the agent's
    own simulation advancing.
    """
    return {k: v for k, v in status.items() if k not in ("world", "scheduler")}


def _dump(db_file):
    """Every row of every table in *db_file*, as one string, plus the row count."""
    con = sqlite3.connect(str(db_file))
    try:
        tables = [
            name
            for (name,) in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]
        blob = []
        rows = 0
        for table in tables:
            data = con.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
            rows += len(data)
            blob.append(repr(data))
        return "".join(blob), rows
    finally:
        con.close()


# ----------------------------------------------------------------------
# The environment really is host-free
# ----------------------------------------------------------------------

def test_the_test_process_has_no_host_in_it():
    """Guards every other assertion in this file.

    If a host application ever leaked onto ``sys.path`` — a stray ``.pth``, a
    developer running this suite from a host's venv — the hooks would be
    configurable and the tests below would prove nothing about standalone use.
    """
    leaked = [name for name in HOST_PACKAGES if name in sys.modules]
    assert leaked == [], f"Host packages already imported: {leaked}"

    import importlib.util

    found = [name for name in HOST_PACKAGES if importlib.util.find_spec(name)]
    assert found == [], f"A host application is importable from this environment: {found}"


# ----------------------------------------------------------------------
# Three agents, one world
# ----------------------------------------------------------------------

def test_three_agents_share_one_world_without_cross_contamination(tmp_path, caplog):
    world = WorldEnvironment()
    agents = [_make(tmp_path, f"agent{i}", world) for i in range(AGENT_COUNT)]

    # All three hold the *same* world object, and nothing else is shared.
    assert all(a._world is world for a in agents)
    assert len({id(a._energy) for a in agents}) == AGENT_COUNT

    before = [copy.deepcopy(a.get_status()) for a in agents]

    caplog.set_level(logging.WARNING)
    for _ in range(ROUNDS):
        world.tick()  # the caller owns the shared clock; LifeService will not tick it
        for a in agents:
            a._scheduler.force_all_ticks()

    # -- 1. No tick failed. force_tick swallows handler exceptions and logs them
    #       at ERROR, so this is the only assertion that can see a broken tick.
    assert _errors(caplog) == [], _errors(caplog)

    # -- 2. Every tick handler actually ran to completion. force_tick only stamps
    #       _last_ticks *after* the callback returns, so a None here is a tick that
    #       raised. This is the assertion that catches "all five ticks failed
    #       silently" independently of the log stream.
    for a, pid in zip(agents, [f"agent{i}" for i in range(AGENT_COUNT)]):
        last = a._scheduler.get_status()["last_ticks"]
        never_ran = sorted(k for k, v in last.items() if v is None)
        assert never_ran == [], f"{pid}: tick handlers that never completed: {never_ran}"

    # -- 3. Private state advanced. Compared with the shared world and the tick
    #       bookkeeping removed, so this can only be the agent's own simulation.
    after = [copy.deepcopy(a.get_status()) for a in agents]
    for i, (b, a_) in enumerate(zip(before, after)):
        assert _private_state(b) != _private_state(a_), f"agent{i} state did not advance"
        assert isinstance(a_, dict)

    # -- 4. The shared world advanced, and all three agents observe the same one.
    assert before[0]["world"] != after[0]["world"], "the shared world did not advance"
    assert all(s["world"] == after[0]["world"] for s in after)

    # -- 5. Each agent has its own database file, and it has been written to.
    for i in range(AGENT_COUNT):
        db_file = tmp_path / f"agent{i}.db"
        assert db_file.exists()
        _, rows = _dump(db_file)
        assert rows > 0, f"agent{i} persisted nothing — its ticks did no work"

    # -- 6. A write aimed at one agent lands in that agent's store and nowhere
    #       else. A plain scan for other agents' persona_ids is vacuous today (the
    #       schema is per-persona, so no table carries a persona id at all), which
    #       is exactly why the sentinel below exists: it is a value this test puts
    #       into one agent, through the library's own API, that must be findable in
    #       exactly one file.
    for i, a in enumerate(agents):
        a.add_conversation_plan(f"21:00 sentinel-agent{i}-only")
        a._save_plan()

    for i in range(AGENT_COUNT):
        blob, _ = _dump(tmp_path / f"agent{i}.db")
        found = [j for j in range(AGENT_COUNT) if f"sentinel-agent{j}-only" in blob]
        assert found == [i], f"agent{i}'s database holds sentinels from agents {found}"

        # Kept as a forward guard: if a future schema change starts stamping rows
        # with the persona id, a leak between agents fails here.
        for j in range(AGENT_COUNT):
            if j != i:
                assert f"agent{j}" not in blob, f"agent{i}'s database leaked agent{j}"


# ----------------------------------------------------------------------
# The sandbox's construction path
# ----------------------------------------------------------------------

def test_a_bare_agent_survives_a_user_message_and_a_tick(tmp_path, caplog):
    """No user model, no follow-up provider, no host services — must still work.

    This is how the sandbox will build an agent, and how an overseer will speak to
    one. It must not raise, and — since the tick path swallows exceptions — it
    must not log an error either.
    """
    assert not any(m in sys.modules for m in HOST_PACKAGES), (
        "A host application leaked into the library test process"
    )

    caplog.set_level(logging.WARNING)
    agent = _make(tmp_path, "solo", WorldEnvironment())

    agent.on_user_message("hello", "neutral", 0.5)
    agent._scheduler.force_all_ticks()

    assert _errors(caplog) == [], _errors(caplog)

    last = agent._scheduler.get_status()["last_ticks"]
    assert sorted(k for k, v in last.items() if v is None) == []

    # The two exports the sandbox reads back are plain JSON-able dicts.
    assert isinstance(agent.get_status(), dict)
    assert isinstance(agent.export_inner_state(), dict)
    assert isinstance(agent.export_outer_state(), dict)


# ----------------------------------------------------------------------
# What the library degrades on without a host — documented, not asserted away
# ----------------------------------------------------------------------

def test_missing_host_hooks_degrade_at_warning_never_at_error(tmp_path, caplog):
    """Unconfigured hooks are a *feature-unavailable* condition, not a failure.

    Every hook call site inside a tick is wrapped in ``except ImportError``
    (``HookNotConfigured`` subclasses it) and logs at ``WARNING``. The one
    exception is ``LifeService.persona_local_now()``, which calls the
    ``persona_now`` hook unguarded — hence the library default in
    ``aura_life.defaults``. Without it every ``activity`` tick dies inside
    ``force_tick`` and is only visible as an ``ERROR`` log.
    """
    from aura_life import defaults, hooks

    assert list(defaults.DEFAULT_PROVIDERS) == ["persona_now"]
    assert hooks.is_configured("persona_now"), "aura_life/__init__.py did not install it"
    # is_configured() cannot distinguish a library default from a host registration;
    # provider_for() is the accessor that can, and this is the claim the docs make.
    assert hooks.provider_for("persona_now") is defaults.persona_now
    for name in hooks.HOOK_NAMES:
        if name not in defaults.DEFAULT_PROVIDERS:
            assert not hooks.is_configured(name), f"{name} unexpectedly has a provider"

    caplog.set_level(logging.WARNING)
    agent = _make(tmp_path, "degraded", WorldEnvironment())
    for _ in range(3):
        agent._scheduler.force_all_ticks()

    assert _errors(caplog) == [], _errors(caplog)

    # Every hook that degraded did so at WARNING, and none of them was
    # persona_now — if the default were missing or were being reached through a
    # guard rather than the registry, it would show up here.
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert [w for w in warnings if "persona_now" in w] == []


@pytest.mark.parametrize("hook_name", ["get_config", "get_llm_service", "geocode"])
def test_hooks_without_a_library_default_still_raise(hook_name):
    """The raise-when-unconfigured contract survived adding one default."""
    from aura_life import hooks

    args = {"get_config": (), "get_llm_service": (), "geocode": ("Lyon",)}[hook_name]
    with pytest.raises(hooks.HookNotConfigured):
        getattr(hooks, hook_name)(*args)


def test_installing_defaults_never_clobbers_a_host_provider():
    """``defaults.install()`` must not downgrade a host's clock to the system one.

    The recovery path the docs describe — ``hooks.reset()``, then put things back —
    would otherwise silently replace a host's ``persona_now`` (a virtual or frozen
    clock, in the origin host's parity driver's case) with ``datetime.now()``, and
    nothing
    anywhere would report it.
    """
    from aura_life import defaults, hooks

    def host_clock(timezone=None):
        return "HOST-CLOCK"

    assert hooks.provider_for("persona_now") is defaults.persona_now
    try:
        hooks.configure(persona_now=host_clock)
        assert hooks.provider_for("persona_now") is host_clock

        defaults.install()

        assert hooks.provider_for("persona_now") is host_clock, (
            "install() overwrote the host's provider"
        )
        assert hooks.persona_now() == "HOST-CLOCK"
    finally:
        hooks.configure(**defaults.DEFAULT_PROVIDERS)

    # ...and it does still fill an empty slot.
    assert hooks.provider_for("persona_now") is defaults.persona_now
