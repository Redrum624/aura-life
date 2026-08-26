# Deferred

Things found during the extraction and deliberately **not** fixed, because the
extraction is a pure move. Each needs its own follow-up.

## Pre-existing Aura bugs surfaced by the extraction

### `LifeService._datastore` is never assigned — calendar triggers have never run

*Found: Task 2b (2026-08-26). Belongs to Aura, not to this library.*

`server/engine/life_service.py` reads `self._datastore` at `:6492`, `:6533` and
`:6567`, but `LifeService` never assigns it. Every `self._datastore =` in the
repository belongs to a different class (`engine/emotion/emotion_persistence.py:45`,
the `engine/relationship/*` services, `memory/memory_service.py:37`).

Consequence: `_scan_calendar_for_triggers` and its two sibling methods raise
`AttributeError` on every call. The caller at ~`:2656` swallows it with a bare
`except Exception` and a DEBUG-level log, so the failure has been silent. Calendar
`UPCOMING_EVENT` triggers, post-event `EMOTIONAL_CHECK_IN` check-ins, and
anniversary promotion have therefore never actually fired in production.

Not fixed here: this is pre-existing behaviour, and the extraction's contract is
that behaviour does not change. Fixing it would alter the parity golden.

**Follow-up:** decide whether `_datastore` should be constructor-injected (like
`memory_service`) or resolved from the persona datastore hook, then fix, and add a
regression test that calls `_scan_calendar_for_triggers` without a shim.

## Extraction artefacts to consolidate

### Most `FREEZE_PREFIXES` entries in the parity driver are inert but must not be removed

*Found: Task 2c review (2026-08-26).*

`server/tests/parity_driver.py` freezes the clock in modules matching a list that
now includes `context`, `services`, `data`, `memory`, `config`, `prompt` and
`pipeline` alongside `engine`/`aura_life`/`personas`. On the current tree most of
those are **inert**: once `life_service.py`'s module-level `services.image_service`
import was removed, nothing outside `engine` is imported before the freeze runs, so
late-imported modules pick up the faked stdlib `datetime` automatically.

They are load-bearing only for reproducing the baseline golden captured at
`a26d46cd`, and — critically — **no test fails if one is deleted**. A future
maintainer tidying the list would silently reintroduce wall-clock dependence, which
manifests as a parity test that fails only at certain hours of the day.

**Follow-up:** state this directly in the comment block above `FREEZE_PREFIXES`, so
the warning lives in the code rather than in a review artefact.


### The parity driver carries its own copy of the follow-up adapter

*Found: Task 2b (2026-08-26).*

`server/tests/parity_driver.py` defines a private ~20-line copy of the
`FollowUpType` name→enum adapter rather than importing Aura's from
`routers/_shared.py`, because importing that module would drag the whole router
stack into the clock-frozen subprocess. Two copies can drift, and if the driver's
copy stops matching Aura's the golden silently stops meaning "Aura's real
behaviour".

**Follow-up:** when Task 5 introduces `server/aura_life_bridge.py`, make it the
single canonical home for both the user-model and follow-up adapters, and have the
parity driver import from there (the bridge has no router dependencies, so it is
safe to import in the subprocess).

## Library-side workarounds that should become real fixes

### Unguarded host-hook call sites — one worked around, the rest still live

*Found: Task 6 (2026-08-26). Corrected after review: an earlier version of this
entry claimed every other call site was guarded. It is not true. No call site has
been modified — they are moved code under a verbatim contract, and adding a guard
would change behaviour Aura's parity golden pins. **This is a recording entry, not
a repair one.***

Most hook call sites in the moved code sit inside a `try/except`, so an
unconfigured hook degrades that feature to "unavailable". **Thirteen do not.**

The list below is from an AST walk of `src/aura_life/` that checks whether the
*import* and the *call* have a `Try` at any ancestor level; the reachability notes
are from reading each caller. **How to re-derive the count without redoing the
walk:** the walk reports 14 unguarded `from aura_life.hooks import ...` sites, but
`__init__.py:162` is not one of them — it imports `HookNotConfigured`, the
exception type, not a hook. 14 - 1 = **13**, which is also 3 (on a tick path) + 1
(covered by a caller) + 9 (untraced), the three groups below.

Why this matters: `LifeScheduler.force_tick` wraps every tick handler in
`except Exception: logger.error(...)`. An unguarded hook on a tick path does not
crash — it makes that tick silently do nothing, forever, while the process looks
healthy. That is not a hypothetical; it is what Task 6 found.

#### On a tick path, unguarded at the call site

| Site | Function | Tick | Status |
|---|---|---|---|
| `life_service.py:6189-6190` | `persona_local_now()` | `activity` (via `force_tick`) | **was silently failing 100% of the time** — worked around, see below |
| `life_service.py:1813-1814` | `_get_weather_service()`, called unguarded from `_update_weather()` at **`life_service.py:1842`** | `world` (`_on_world_tick` -> `:2476`) | **live hazard, one early-return away** |
| `life_service.py:1919-1920` | `_geocode_trip()`, called from `_pick_trip_destination()` at `:1963` | `world` (`_update_trip` at `:2478`) | **live hazard behind an LLM** |

**`life_service.py:1842` is the nearest neighbour of the bug that was found, and it
is not guarded by anything deliberate.** `_update_weather()` reaches
`svc = self._get_weather_service()` only if it survives three early returns:

* `:1832-1834` — `if getattr(self, "_shared_world", False): return`
* `:1835-1836` — `if self._is_ai: return`
* `:1837-1840` — `if lat is None or lon is None: return`

(The `get_config().place_enabled` check just above at `:1825-1829` *is* guarded, and
host-free it falls through rather than returning — it does not stop anything.)

`tests/test_multi_instance.py` passes only because of the first of those: all three
agents share one `WorldEnvironment`, so `_shared_world` is set and
`_update_weather()` returns at `:1834`. **A sandbox agent that owns its own world,
is not an AI persona, and has a resolved lat/lon in its place state would have its
`world` tick start dying silently — the identical failure, in the library's intended
second consumer, with no test covering it.**

`life_service.py:1920` is the same shape with an LLM in front of it:
`_pick_trip_destination()` calls the *guarded* `_get_trip_llm()` first, which returns
`None` host-free and bails at `:1935-1936`, so `geocode` is unreachable today. **A
sandbox that injects its own `trip_llm` — and the sandbox is an LLM overseer, so it
plausibly would — walks straight into it.**

#### Unguarded at the call site, but covered by a caller's guard

| Site | Covered by |
|---|---|
| `emotion_persistence.py:297-298` (`get_emotion_persistence`, legacy-mode branch) | `life_service.py:3788` `try:` / `:3816-3817` `except Exception: logger.warning("Failed to persist activity emotions: ...")` |

That WARNING is the single message a host-free tick emits, and it is expected
degradation rather than a bug — but note the guard belongs to the *caller*, so any
new caller of `get_emotion_persistence()` inherits the hazard, not the protection.

#### Unguarded at the call site, not on any tick path exercised by the tests

`place_service.py:167-168` (`_get_llm`), `:173` (`_get_geocode`), `:177-178`
(`_get_config`); `personality_config.py:266,269` (`get_personality`);
`profile_db.py:1099-1100` (`get_profile_db`), `:1108-1109` (`get_owner_device_id`);
`place_generation.py:150-151` (`generate_cultural_stance`), `:378-379`
(`generate_appearance`); `device_location.py:27-28` (`_store_path`).

These are on persona-creation and place-resolution paths rather than the tick loop.
Their reachability from a host-free consumer has **not** been traced — say so rather
than assuming they are safe.

#### The one that was worked around

```python
# aura_life/life_service.py:6189, persona_local_now()
from aura_life.hooks import persona_now
return persona_now(self._persona_timezone())
```

In Aura this can never fire — `aura_life_bridge` is installed at every entry point.
Standalone it fired on every `activity` tick. Task 6's first run of three host-free
agents produced **30 `ERROR` records in 10 rounds** (3 agents x 10 activity ticks),
`_last_ticks["activity"]` stuck at `None` throughout, and no activities, skills or
place visits ever recorded. The library imported cleanly, constructed cleanly,
ticked forever and simulated nothing.

**Worked around, not fixed:** `aura_life/defaults.py` supplies a stdlib `persona_now`
(`zoneinfo` when a timezone is given, `datetime.now()` otherwise) and
`aura_life/__init__.py` registers it through the ordinary `hooks.configure` path.
`defaults.install()` is non-clobbering, so it can never downgrade a host's clock.
`hooks.reset()` drops it, which is what keeps the bare raise-when-unconfigured
contract that Aura's `test_host_hooks.py` asserts.

Two consequences a maintainer needs to know:

* `hooks.is_configured("persona_now")` is `True` with no host installed, because a
  library default *is* a registration. `hooks.provider_for(name)` — added in Task 6
  — is the accessor that tells which implementation a hook resolves to; compare it
  against `aura_life.defaults.DEFAULT_PROVIDERS[name]`. (`DEFAULT_PROVIDERS` alone
  only says which hooks *have* a default, which is why the accessor exists.)
* This is the **only** hook with a default, and the other twelve unguarded sites above
  are unchanged. Any of them that becomes reachable fails the same silent way, and
  only `tests/test_multi_instance.py`'s "no `ERROR` records / all five `last_ticks`
  stamped" assertions would notice.

**Follow-up, in priority order:**

1. **`life_service.py:1842` and `:1920`** — cover the self-owned-world path with a
   test that gives an agent a resolved lat/lon (and one that injects a `trip_llm`)
   and asserts the `world` tick still logs no `ERROR`. Expect it to fail today.
   Decide the fix: a library default for `get_weather_service`/`geocode` in the same
   "feature unavailable" shape (returning something whose `get_current()` yields
   `None`, which `_update_weather` already handles at `:1843-1850`), or a guard at
   the call site — the latter is a behaviour change Aura's golden must be re-captured
   for.
2. Decide whether `persona_local_now()` should carry its own guard like its guarded
   siblings, and — separately — whether `persona_now` belongs in the host-hook
   registry at all, given it is a clock rather than a host resource.
3. Trace the nine untraced sites and record which are reachable host-free.
