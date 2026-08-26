# aura-life

An agent life-simulation engine. Give a persona a `LifeService` and it acquires an
inner life that keeps running whether or not anyone is talking to it: energy and
fatigue cycles, a self-generated daily plan, goals it invents and abandons, moods
that drift, a home with rooms and weather, a job, money, errands, skills,
friendships, and experiences worth mentioning next time you speak.

It is a **library, not an application**. It owns the simulation and nothing else —
no LLM, no HTTP layer, no user accounts, no storage beyond one SQLite file per
persona. Everything that belongs to the surrounding application reaches the engine
through a twelve-function hook registry the host fills in at startup, and a
host-free process still runs: you get a life with no narration, no real weather and
no place lookups.

- 32,088 lines across 82 modules and 32 subpackages
- Python 3.11+; the only required third-party dependency is `tzdata`, and only on Windows
- Apache-2.0

## Where this came from

aura-life was extracted on 2026-08-26 from [Aura](https://github.com/Redrum624/Aura)
(private), at commit `b9c92aff`, by the copyright holder — who relicensed the
extracted subset under Apache-2.0. See `NOTICE`.

The extraction was a **pure move**: a golden snapshot of twenty simulated ticks was
captured against the pre-extraction code, and the post-extraction library reproduces
it byte for byte. `CHANGELOG.md` records what moved and what deliberately did not.

There is no published package and no public repository yet. Aura consumes this
library as an **editable local path dependency**, which is also how you should
consume it today.

## Install

There is nothing to download — point pip at the checkout you already have. From the
directory that contains it:

```bash
python -m pip install -e ./aura-life
python -m pip install -e "./aura-life[scheduler]"    # ...or with the optional extra
```

(Aura installs it exactly this way: `server/venv/Scripts/python.exe -m pip install -e
../aura-life`, run from the Aura repo root with the two checkouts side by side.)

- **`[scheduler]`** installs `apscheduler`. Only `LifeService.start()` needs it —
  that is the background thread that ticks the simulation on real-world intervals.
  Without it `start()` logs `APScheduler not installed. Life simulation will run
  manually.` and returns; **you drive the ticks yourself, which is what the
  quickstart below does.** The quickstart's output was produced in an environment
  where `HAS_APSCHEDULER` is `False`.
- **`tzdata`** is a hard dependency on Windows only (`sys_platform == "win32"`), and
  is installed for you. Windows ships no system IANA timezone database, and without
  it every persona timezone silently falls back to server-local time.

## Quickstart

Two personas living in one shared world, with no host application at all.

```python
"""Two personas, one shared world, no host application."""
import logging

from aura_life import LifeService
from aura_life.world import WorldEnvironment

# One WARNING per activity tick is expected with no host -- see "Limitations".
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

world = WorldEnvironment()           # one world...

agents = [                           # ...two lives in it, one SQLite file each
    LifeService(
        db_path=f"{name}.db",
        persona_id=name,
        world_environment=world,
        occupation=occupation,
        interests=interests,
    )
    for name, occupation, interests in [
        ("mara", "baker", ["bread", "weather"]),
        ("theo", "nurse", ["running", "jazz"]),
    ]
]

# There is no public tick(): the caller owns the clock. LifeService never ticks a
# world it was handed -- a shared clock belongs to whoever created it.
for _ in range(20):
    world.tick()
    for agent in agents:
        agent._scheduler.force_all_ticks()

for agent in agents:
    s = agent.get_status()
    goal = (s["goals"]["active_goals"] or [{"title": "-"}])[0]["title"]
    print(f"{agent._persona_id:5} mood={s['affect']['mood']:9} "
          f"energy={s['energy_level']:9} "
          f"activities={s['recent_activities_count']:3} goal={goal!r}")

w = agents[0].get_status()["world"]
print(f"world {w['time_of_day']}, {w['weather']}, {w['season']} - both agents see this one")
```

What it actually prints (exit code 0, `mara.db` and `theo.db` created):

```text
WARNING Failed to persist activity emotions: aura_life hook 'get_config' is not configured; the host application must call aura_life.hooks.configure(get_config=...)
    ... that same WARNING 40 times in total — once per activity tick per agent.
    Not an error; see Limitations. Elided here only for readability.
mara  mood=content   energy=high      activities= 20 goal='Appreciate something beautiful'
theo  mood=content   energy=high      activities= 20 goal='Learn one new thing'
world dawn, cloudy, summer - both agents see this one
```

The last three lines differ from run to run: `WorldEnvironment` starts from the wall
clock, weather is random, and goals are generated. What is stable is the shape —
both agents advance, both keep their own database, and both read the same world.

Three things in that snippet are load-bearing and easy to get wrong:

1. **`world_environment=` makes the world shared, and shared means yours.**
   `LifeService` skips its own `self._world.tick()` when it was handed a world, so
   nothing advances until *you* call `world.tick()`. Omit the argument and each
   service builds and ticks a private world instead.
2. **`agent._scheduler.force_all_ticks()` runs the five internal ticks**
   (`world`, `energy`, `plan`, `activity`, `goal`) once each, synchronously. This
   reaches through a private attribute because there is no public equivalent —
   see [Limitations](#limitations).
3. **Pass everything by keyword.** `LifeService.__init__` takes 18 positional
   parameters and `persona_id` is the ninth.

`tests/test_multi_instance.py` is the executable version of this quickstart, with
assertions: three agents, one world, no `ERROR` records, no state leaking between
databases.

## The public surface

`aura_life` exports **116 names** and that is the stable API. 114 of them are
inherited verbatim from Aura's own engine package; `hooks` and `HookNotConfigured`
were added by the extraction.

```python
from aura_life import LifeService, Weather, Goal, hooks   # stable
```

### `aura_life.internals` — what it actually is

`internals.py` is eight lines. It re-exports **`LifeService`, all of `models`, and
all of `context`** — and nothing else:

```python
from aura_life.life_service import LifeService
from aura_life.models import *
from aura_life.context import *
```

Measured against the facade, it adds **15 names** beyond the 116 — and **8 of those
are leaked stdlib/typing symbols** (`Dict`, `List`, `Optional`, `Enum`, `dataclass`,
`field`, `datetime`, `json`) that the wildcard imports dragged in. The 7 real
additions are `BehavioralTendency`, `CalendarEntry`, `ErrandsState`,
`InebriationState`, `LOCATION_ENUM_TO_KEY`, `LifeContextBuilder` and
`PlaceLocationState`. **It is explicitly not stable and may change in a minor
release.** It exists so Aura could finish migrating without being blocked on the
facade; treat an import from it as a to-do, not an API.

**It does not re-export the subsystem classes.** `EmotionEngine`,
`TextEmotionAnalyzer`, `WorldEnvironment`, `EnergySystem`, `GoalEngine`,
`ActivityEngine`, `LifeScheduler`, `get_emotion_persistence`, the `personas`
entry points and 13 more — **27 names declared in submodule `__all__`s** — are on
neither `aura_life` nor `aura_life.internals`.

**Everything else is reached by its real module path**, which is a supported,
working import — just not a stable one:

```python
from aura_life.world import WorldEnvironment
from aura_life.emotion import EmotionEngine, TextEmotionAnalyzer
from aura_life.energy import EnergySystem
from aura_life.personas import get_personality
```

(`aura_life.hooks` is the exception among submodules: it *is* exported by the
facade, so its 16 names are reachable as `aura_life.hooks.configure` and friends.)

A public home for the subsystem classes is a **v0.2** decision, not a bug — nothing
here is broken, the paths above are how consumers import them today.

`tests/test_api_surface.py` pins `__all__` against a committed snapshot
(`tests/api_surface.json`), so the public surface cannot change without the diff
saying so. Regenerating that snapshot is opt-in: `API_SURFACE_WRITE_SNAPSHOT=1`.

## The hooks contract

The engine simulates a life; it does not own the machine it runs on. Config, the
LLM, weather, geocoding, images, the persona datastore and the persona clock all
belong to the host. `aura_life.hooks` is the single seam between the two, and it
imports nothing but `typing` — that is its guarantee that the seam can never drag
the host in.

A host registers implementations once, at startup:

```python
from aura_life import hooks

def _get_config():
    from myapp.config import get_config        # imported at CALL time, not install time
    return get_config()

hooks.configure(get_config=_get_config, get_llm_service=..., ...)
```

`configure()` refuses a name that is not a known hook, so a typo in a bridge fails
loudly at startup instead of silently at the first call months later. Aura's own
bridge is `server/aura_life_bridge.py` — 156 lines, one thin wrapper per hook, each
performing its import lazily so monkeypatching in tests still works.

The twelve hooks:

| Hook | What the host supplies |
|---|---|
| `get_config` | the configuration object (`.data_dir`, `.place_enabled`, …) |
| `get_user_data_root` | root directory for per-user data |
| `get_persona_datastore` | the persona's consolidated datastore |
| `get_image_service` | image / self-photo service |
| `resolve_outfit_for_context` | which outfit fits the current schedule context |
| `get_schedule_phase` | coarse phase of the persona's day (`"morning"`, `"evening"`, …) |
| `generate_and_update` | regenerate and persist the persona's visual description |
| `get_weather_service` | real weather observations (distinct from the world sim) |
| `get_llm_service` | the LLM client |
| `geocode` | place name → `{city, country, lat, lon, timezone}` |
| `resolve_timezone` | coordinate → IANA timezone string |
| `persona_now` | "now" in the persona's timezone — **the one hook with a library default** |

**An unconfigured hook raises `HookNotConfigured`, a subclass of `ImportError`.**
That inheritance is deliberate and load-bearing: these calls replaced function-local
`from config import get_config` statements whose failure mode was
`ModuleNotFoundError` (itself an `ImportError`), so every `except ImportError` guard
already written around those call sites keeps behaving exactly as it did. Most call
sites catch it, log a `WARNING`, and degrade that one feature to "unavailable".

Registry helpers:

- `hooks.configure(**providers)` — register; idempotent, re-registering overwrites.
- `hooks.reset()` — forget everything, including the library's own default.
- `hooks.is_configured(name)` — is there *a* provider?
- `hooks.provider_for(name)` — *which* provider? (the only way to tell a library
  default from a host registration; see Limitations)

### `persona_now`, the one library default

`persona_now` is a clock, not a host resource, and the standard library already has
one. `aura_life/defaults.py` registers a `zoneinfo`-based implementation when the
package is imported. It exists because `LifeService.persona_local_now()` calls that
hook **unguarded**: without a default, every `activity` tick of a host-free
`LifeService` dies inside the scheduler, which swallows the exception and logs it at
`ERROR`. The library would import cleanly, construct cleanly, tick forever and
simulate nothing.

`defaults.install()` never overwrites a provider that is already registered, so a
host bridge that registers its own `persona_now` — a virtual or frozen clock, say —
cannot be silently downgraded to the system clock. `hooks.reset()` drops it along
with everything else.

## The two per-persona providers

Two host behaviours are per-persona rather than per-process, so they are constructor
arguments on `LifeService` rather than hooks:

| Argument | Called as | The engine then uses |
|---|---|---|
| `user_model_provider` | `provider(persona_id)` | `.bid_response_rate`, `.quiet_windows`, `.observe_message(...)`, `.get_engaged_topics(n)`, `.get_disengaged_topics(n)` |
| `follow_up_provider` | `provider(persona_id)` | `.create_trigger(trigger_type, topic=…, context=…, urgency=…, …)` |

Both are duck-typed — the engine never imports a class or an enum for either. Where
a follow-up type is needed it passes the enum member's **name** as a plain string
(`"MOOD_SHIFT"`, `"DEPARTURE"`, …) and the host adapter turns it back into whatever
type it uses.

**Omitting both is the supported standalone path.** Every call site is guarded by an
`is None` check; the engine simply skips adaptive cooldowns and proactive follow-up
triggers. The quickstart above passes neither.

## Limitations

Honest list. None of these are theoretical.

**There is no public `tick()`.** Driving the simulation means
`svc._scheduler.force_all_ticks()`, which is a private attribute, and constructing a
shared world means `from aura_life.world import WorldEnvironment`, which is not in
the facade. Both are the documented way to do it today and both are v0.2 candidates
(recorded in `DEFERRED.md`).

**`hooks.is_configured("persona_now")` is `True` with no host installed**, because a
library default *is* a registration. Use `provider_for` to tell them apart:

```python
from aura_life import defaults, hooks
hooks.provider_for("persona_now") is defaults.DEFAULT_PROVIDERS["persona_now"]
# True  -> the library's own clock; False -> the host's
```

**The `WARNING` a host-free tick emits is expected degradation, not a bug.**

```text
Failed to persist activity emotions: aura_life hook 'get_config' is not configured; …
```

It appears once per `activity` tick. `get_emotion_persistence()` calls `get_config`
unguarded, but its caller in `life_service.py` wraps the whole thing — so the feature
degrades and the tick completes. Note that the guard belongs to the *caller*: a new
caller of `get_emotion_persistence()` inherits the hazard, not the protection.

**Thirteen hook call sites are unguarded, and two of them sit on the `world` tick
path.** `_get_weather_service` (`life_service.py:1813`) and `_geocode_trip`
(`life_service.py:1919`) both import their hook with no `try/except`. Today nothing
reaches them: `_update_weather` returns early for a shared world, for AI personas,
and when lat/lon is unresolved, and `_pick_trip_destination` bails when the
(guarded) trip LLM is absent. **A consumer that gives an agent its own
`WorldEnvironment` with a resolved lat/lon, or that injects a `trip_llm`, walks
straight into them** — and the failure is silent, because `LifeScheduler.force_tick`
catches every handler exception and only logs it at `ERROR`.

No call site was modified during the extraction: they are moved code under a
verbatim-behaviour contract, and adding a guard would change behaviour the parity
golden pins. `tests/test_hook_call_sites.py` is the authority for the census — it
walks the AST, pins the thirteen as an explicit allowlist, and fails when a new
unguarded site appears. `DEFERRED.md` carries the analysis and the ranked follow-ups.

**`LifeService.start()` needs `apscheduler`** (the `[scheduler]` extra) and is a
single-persona, background-thread design. For N agents in one process, drive the
ticks yourself as the quickstart does.

**Relationship modelling is not here.** Persona↔user relationship state stayed in
Aura on purpose — see `CHANGELOG.md`.

## Tests

```bash
python -m pytest tests -q          # 129 tests
```

The suite must be run in an environment with **no Aura on `sys.path`**;
`tests/test_multi_instance.py` asserts that explicitly, because otherwise every
"works standalone" claim in it would be vacuous. The notable files:

| File | What it protects |
|---|---|
| `test_multi_instance.py` | three agents, one world, no host — no `ERROR` records, no cross-contamination |
| `test_hook_call_sites.py` | the unguarded-hook census; fails on a new unguarded site |
| `test_api_surface.py` | `__all__` cannot change silently |
| `test_persona_parity.py` | persona generation still matches the pre-extraction golden |
| `test_smoke.py` | the package imports at all, and reports a version |

Nothing in the suite walks every module, so the "everything under `aura_life`
imports with no Aura present" check is a manual one (it reports 81 — the 82 files
minus `aura_life/__init__.py`, which is the package being walked):

```bash
python -c "import pkgutil, importlib, aura_life; \
mods=[m.name for m in pkgutil.walk_packages(aura_life.__path__,'aura_life.')]; \
[importlib.import_module(m) for m in mods]; print(len(mods),'modules standalone')"
```

The parity golden and the API snapshot are committed fixtures. A missing one is a
**defect, not a fresh start**: both tests fail loudly rather than regenerating.
Regeneration is opt-in and requires the exact value `1`
(`PARITY_WRITE_GOLDEN=1`, `API_SURFACE_WRITE_SNAPSHOT=1`).

## License

Apache-2.0. See `LICENSE` and `NOTICE`.
