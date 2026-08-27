# Deferred

Known defects and deliberate follow-ups, kept in the open. Two sections matter
most: what was **fixed before the first public release**, and what is **shipped
unfixed** and therefore something you can walk into.

Follow-ups that belong to the private host application this library was extracted
from are tracked there, not here.

---

## Fixed before the first public release

### `LifeService._datastore` was never assigned — the calendar API raised on first call

*Found during the extraction (2026-08-26). Fixed 2026-08-27, before publication.*

**What it was.** `LifeService` read `self._datastore` in three places — the two
public calendar methods and the internal calendar scan — and **never assigned
it**. Every `self._datastore =` in the library belonged to a different class
(`src/aura_life/emotion/emotion_persistence.py`). The attribute simply did not
exist on a `LifeService`.

Consequences, in order of how loudly they failed:

* `LifeService.add_calendar_entry()` and `LifeService.get_upcoming_calendar_entries()`
  are **public API**, and both raised
  `AttributeError: 'LifeService' object has no attribute '_datastore'` on a fresh
  instance. There was no way to use the documented calendar surface at all.
* `_scan_calendar_for_triggers()` runs on a tick, and its caller wraps it in a bare
  `except Exception` with a DEBUG log, so that one failed **silently**. Calendar
  `UPCOMING_EVENT` triggers, post-event `EMOTIONAL_CHECK_IN` check-ins and
  anniversary promotion never fired — not once, for the whole life of the code.

The extraction recorded this rather than fixing it, because 0.1.0's contract was
byte-identical behaviour and a fix would have moved the parity golden. That
contract ended at publication, and shipping a public method that raises
unconditionally was not defensible.

**What the fix is.** `datastore` is now an optional **constructor argument**,
appended last in `LifeService.__init__` so no existing positional caller shifts.
It is injected rather than resolved through the `get_persona_datastore` hook,
because every other collaborator on this class is injected and a hook lookup
would silently relocate an existing host's calendar rows out of `db_path`.

With no datastore supplied — the normal library shape — the calendar lives in
`db_path`, where `_init_database()` already created the `user_calendar` table.
With one supplied, the schema is created in it on first use. Regression coverage
is `tests/test_calendar_datastore.py`.

**Related change:** `user_calendar` rows had no delete path anywhere, so past,
already-followed-up events accumulated permanently and every scan re-queried the
whole table. Non-recurring rows are now pruned `CALENDAR_RETENTION_DAYS` (30)
past their event date — well beyond the 48-hour post-event check-in window, after
which a row can no longer trigger anything. Recurring rows are the anniversary
source and are kept.

---

## Shipped unfixed: unguarded host-hook call sites

*Found during the extraction (2026-08-26) and re-verified at publication. This is
a **recording** entry, not a repair one.*

Most hook call sites in this library sit inside a `try/except`, so an
unconfigured hook degrades that one feature to "unavailable". **Thirteen do
not** — they call the hook bare, and `HookNotConfigured` propagates into the
caller.

**The authority for that number is `tests/test_hook_call_sites.py`, not this
document.** The test does the AST walk (every `from aura_life.hooks import ...`,
checking for a `Try` at any ancestor level), pins the thirteen sites as an
explicit allowlist keyed by **module + enclosing function + hook** — no line
numbers, which churn — and fails when a new unguarded site appears or an existing
one becomes guarded. It carries a self-test proving the walk can tell guarded
from unguarded, and a non-emptiness guard so it cannot rot into a vacuous pass.
**If this list and that test disagree, the test is right.**

How the count is derived, so it need not become folklore: the raw walk reports 14
unguarded `from aura_life.hooks import ...` statements, but the one in
`aura_life/__init__.py` is not a call site — it imports `HookNotConfigured`, the
exception type, not a hook. The test excludes it by counting only names in
`hooks.HOOK_NAMES`, so the exclusion stays correct as the registry changes.
14 − 1 = **13**, which is also 3 (on a tick path) + 1 (covered by a caller) + 9
(untraced), the three groups below. The reachability notes come from reading each
caller by hand and are **not** enforced by the test.

Why it matters: `LifeScheduler.force_tick` wraps every tick handler in
`except Exception: logger.error(...)`. An unguarded hook on a tick path does not
crash — it makes that tick silently do nothing, forever, while the process looks
healthy. That is not hypothetical; see "the one that was worked around" below.

### On a tick path, unguarded at the call site

| Module · function | Hook | Tick | Status |
|---|---|---|---|
| `life_service.persona_local_now()` | `persona_now` | `activity` | **was failing 100% of the time** — worked around, see below |
| `life_service._get_weather_service()`, called from `_update_weather()` | `get_weather_service` | `world` | reachable only with a host config; see below |
| `life_service._geocode_trip()`, called from `_pick_trip_destination()` | `geocode` | `world` | reachable only with a host config *and* an injected `trip_llm` |

Both the weather and trip paths now begin with `_place_enabled()`, which **fails
closed**: an unreadable `get_config` means "place features off". A host-free
consumer therefore returns before reaching either hook. That is a change from
0.1.0, where the flag read sat inside a `try` whose `except` was a bare `pass`,
so an unconfigured host fell through and ran the feature as if the flag were on.

What remains reachable is narrower, but real: **a host that registers
`get_config` with `place_enabled` true and does not register
`get_weather_service`.** `_update_weather()` then has to survive three further
early returns — shared-world, AI-persona, unresolved lat/lon — and the call is
bare. The `geocode` site is the same shape with an LLM in front of it:
`_pick_trip_destination()` calls the *guarded* `_get_trip_llm()` first and bails
when it returns `None`, so a host must also inject a `trip_llm` to get there.

`tests/test_multi_instance.py` covers neither: its three agents share one
`WorldEnvironment`, so `_update_weather()` returns at the shared-world check.

### Unguarded at the call site, but covered by a caller's guard

`emotion_persistence.get_emotion_persistence()` calls `get_config` bare; its
caller in `life_service` wraps the whole thing in `try/except` and logs a
`WARNING`. That WARNING is the one message a host-free tick emits, and it is
expected degradation rather than a bug — but note the guard belongs to the
**caller**, so a new caller of `get_emotion_persistence()` inherits the hazard,
not the protection.

### Unguarded at the call site, not on any tick path exercised by the tests

`location/place_service.py` — `_get_llm`, `_get_geocode`, `_get_config`;
`personas/personality_config.py` — `get_personality`;
`personas/profile_db.py` — `get_profile_db`, `get_owner_device_id`;
`personas/place_generation.py` — `generate_cultural_stance`, `generate_appearance`;
`location/device_location.py` — `_store_path`.

These sit on persona-creation and place-resolution paths rather than the tick
loop. Their reachability from a host-free consumer has **not** been traced — said
plainly rather than assumed safe.

### The one that was worked around

```python
# aura_life/life_service.py, persona_local_now()
from aura_life.hooks import persona_now
return persona_now(self._persona_timezone())
```

In the host application this can never fire — its bridge is installed at every
entry point. Standalone it fired on **every** `activity` tick. The first run of
three host-free agents produced **30 `ERROR` records in 10 rounds** (3 agents x
10 activity ticks), `_last_ticks["activity"]` stuck at `None` throughout, and no
activities, skills or place visits ever recorded. The library imported cleanly,
constructed cleanly, ticked forever and simulated nothing.

**Worked around, not fixed:** `aura_life/defaults.py` supplies a stdlib
`persona_now` (`zoneinfo` when a timezone is given, `datetime.now()` otherwise)
and `aura_life/__init__.py` registers it through the ordinary `hooks.configure`
path. `defaults.install()` is non-clobbering, so it can never downgrade a host's
clock. `hooks.reset()` drops it, which is what preserves the bare
raise-when-unconfigured contract that the host application's own hook tests
assert.

Two consequences a maintainer needs to know:

* `hooks.is_configured("persona_now")` is `True` with no host installed, because
  a library default *is* a registration. `hooks.provider_for(name)` is the
  accessor that says which implementation a hook resolves to; compare it against
  `aura_life.defaults.DEFAULT_PROVIDERS[name]`. (`DEFAULT_PROVIDERS` alone only
  says which hooks *have* a default, which is why the accessor exists.)
* This is the **only** hook with a default. The other twelve unguarded sites are
  unchanged, any of them that becomes reachable fails the same silent way, and
  only `tests/test_multi_instance.py`'s "no `ERROR` records / all five
  `last_ticks` stamped" assertions would notice.

**Follow-up, in priority order:**

1. **`_update_weather` and `_pick_trip_destination`** — cover the host-configured
   path with a test that gives an agent a resolved lat/lon (and one that injects
   a `trip_llm`) and asserts the `world` tick still logs no `ERROR`. Expect it to
   fail today. Then decide the fix: a library default for
   `get_weather_service` / `geocode` in the same "feature unavailable" shape
   (returning something whose `get_current()` yields `None`, which
   `_update_weather` already handles), or a guard at the call site.
2. Decide whether `persona_local_now()` should carry its own guard like its
   guarded siblings, and — separately — whether `persona_now` belongs in the
   host-hook registry at all, given it is a clock rather than a host resource.
3. Trace the nine untraced sites and record which are reachable host-free.

---

## v0.2 API candidates

The shape of the public API as shipped, with the parts a second consumer trips
over. None of these are bugs.

### There is no public `tick()`

Driving the simulation requires `svc._scheduler.force_all_ticks()` — a private
attribute, reached through in this repo's own quickstart, in
`tests/test_multi_instance.py`, and in the host application's parity driver. The
only public entry point is `LifeService.start()`, which needs `apscheduler` and
spawns a background thread per persona: the wrong shape for N agents under an
overseer that owns the clock.

**Follow-up:** add `LifeService.tick()` delegating to
`self._scheduler.force_all_ticks()`. A private world is already handled —
`_on_world_tick` calls `self._world.tick()` whenever `_shared_world` is false — so
a public `tick()` would be complete for the single-agent case and would still
leave a shared clock with its owner.

### `WorldEnvironment` is not on the facade

The shared-world construction path needs
`from aura_life.world import WorldEnvironment`. It is in neither
`aura_life.__all__` nor `aura_life.internals`, so the library's headline use case
cannot be written against the stable surface.

**Follow-up:** export `WorldEnvironment` from `aura_life`. That moves `__all__`
from 117 names to 118 and requires regenerating `tests/api_surface.json` with
`API_SURFACE_WRITE_SNAPSHOT=1` — exactly the signal that test exists to produce.

### The teardown functions are only partly on the facade

`clear_emotion_persistence()`, `clear_persona_schedule()` and
`MultiPersonalityManager.remove_personality()` were added before publication to
close process-global caches that previously only grew.

Resolved for 0.2.0, deliberately asymmetrically:

- `clear_persona_schedule()` **is** on `aura_life.__all__` (name 117). Its module's
  other names — `PersonaSchedule`, `get_persona_schedule`, `ScheduledEvent`,
  `UpcomingEvent`, `EventType` — were already on the facade, so the teardown for a
  cache the facade hands you belongs beside them.
- `clear_emotion_persistence()` is **not**, and that is not an oversight. The
  `emotion` subpackage exports *nothing* through `aura_life.__all__`; adding one
  function from an otherwise-unexposed subsystem would put a single leaf on the
  curated surface with no trunk. It is exported from its own subpackage instead:
  `from aura_life.emotion import clear_emotion_persistence`.
- `remove_personality()` is a method on `MultiPersonalityManager`, which is already
  exported, so it needs nothing.

**Follow-up:** if `emotion` ever earns a facade presence, `clear_emotion_persistence`
should join it in the same pass. A single `aura_life.teardown_persona(persona_id)`
wrapping all three remains the tidier long-term shape.

### `LifeService.__init__` takes 19 positional parameters

`persona_id` is the ninth, `datastore` the nineteenth. Every caller in this repo
passes by keyword and the README says to, but the signature does not enforce it.

**Follow-up:** consider a `*` after `db_path`. This is a breaking change for any
positional caller, so it belongs in a major bump or in 0.x with a note.

### `persona_id` has no public accessor

The quickstart reads `agent._persona_id` to label its output.

**Follow-up:** add a read-only `persona_id` property.
