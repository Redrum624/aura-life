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

### `LifeService.persona_local_now()` calls the `persona_now` hook unguarded

*Found: Task 6 (2026-08-26). Worked around in the library; the call site is untouched.*

Every other hook call site in the moved code sits inside a `try/except ImportError`
and degrades that feature to "unavailable" with a `WARNING`. One does not:

```python
# aura_life/life_service.py, persona_local_now()
from aura_life.hooks import persona_now
return persona_now(self._persona_timezone())
```

In Aura this can never fire — `aura_life_bridge` is installed at every entry point.
Standalone it fires on every `activity` tick, and `LifeScheduler.force_tick` catches
the exception and only `logger.error`s it. Task 6's first run of three host-free
agents produced **30 `ERROR` records in 10 rounds** (3 agents x 10 activity ticks),
`_last_ticks["activity"]` stuck at `None` throughout, and no activities, skills or
place visits ever recorded. The library imported cleanly, constructed cleanly,
ticked forever and simulated nothing.

**Worked around, not fixed:** `aura_life/defaults.py` now supplies a stdlib
`persona_now` (`zoneinfo` when a timezone is given, `datetime.now()` otherwise) and
`aura_life/__init__.py` registers it via the ordinary `hooks.configure` path. A host
bridge overwrites it; `hooks.reset()` drops it, which is what keeps the bare
raise-when-unconfigured contract that `test_host_hooks.py` asserts. The call site
itself was **not** modified — it is moved code under a verbatim contract, and adding
a `try/except` there would change behaviour Aura's parity golden pins.

Two consequences a maintainer needs to know:

* `hooks.is_configured("persona_now")` is `True` with no host installed.
  `aura_life.defaults.DEFAULT_PROVIDERS` is how you tell a library default from a
  host registration.
* This is the only hook with a default. Any *new* unguarded hook call site would
  fail the same silent way, and only `tests/test_multi_instance.py`'s
  "no `ERROR` records / all five `last_ticks` stamped" assertions would catch it.

**Follow-up:** decide whether `persona_local_now()` should carry its own guard like
every sibling call site (a behaviour change Aura's golden would have to be
re-captured for), and — separately — whether `persona_now` belongs in the host-hook
registry at all, given it is a clock rather than a host resource.
