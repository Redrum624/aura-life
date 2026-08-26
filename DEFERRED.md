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
