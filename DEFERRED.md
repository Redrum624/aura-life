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

## Fixed by the humanness program (0.6.0)

*Found by the program's first three-day measurement (2026-09-25) or by its
tasks. Fixed on the way to 0.6.0; each line names its `CHANGELOG.md` entry
under 0.6.0, which holds the numbers before and after. `tests/test_humanness.py`
holds the spec's rows at the production cadence.*

- **Her mood read "content" on 100% of ticks**, at about 0.98 intensity, and
  could only go up (*Mood can go down*, Task 4).
- **She "slept" about ten times a day at any hour**, awake on 83-84% of the
  ticks inside her own sleep window (*Sleep is a state with a duration*, Task 3).
- **72-76% of her life events were a template slotted with a bare engine
  label** ("Felt genuinely proud of content"), and nothing ever marked a share
  as shared (*Life events are recorded once*, Task 5).
- **Every activity succeeded**, felt as the same fixed emotions every time
  (*Appraisal, and outcomes that can go wrong*, Task 14).
- **An introvert and an extrovert did the same things**, and her interests
  were stored and never read (*What she does is chosen from who she is*, Task 10).
- **Hunger ran per tick**, drained her energy asleep and fed her on any
  activity whose name held an eating word (*Hunger runs per world hour*,
  Task 10).
- **There was no episodic memory**: nothing she lived could be recalled
  (*A memory stream*, Task 12).
- **What decides her life read the host's clock**, so a host whose world
  clock is not its wall clock saw her days at the host's hours (*What decides
  her life reads the world clock*, Task 19).
- **Her shadow's felt safety fell to 0 within 24 ticks and never came back**,
  in 0.5.0 too (*Her shadow has a rest*, Task 36).

---

## Known limits after the humanness program (0.6.0)

*Found during the program (2026-09-25 to 2026-11-13) and left as they are,
each for the reason given. The ledger's ruling is in brackets.*

### A joint activity across midnight shows the new day's plan

[T19a-R2] Joining a housemate holds her at the joint place until the window
ends, and every read of what she is doing says the joint activity while she
is held. A join in the last minutes of a day is the exception: the reads then
show the new day's plan at the joined hour, because they re-read the plan by
hour. **Fix:** hold the joined slot itself instead of re-reading the plan by
hour.

### No tick lock for hunger and `on_activity`

[T34b-R3] `LifeService` has no tick lock: `start()` runs the ticks on its own
thread while a host may run the downtime catch-up on another. Her affect tick
has a lock (`_affect_tick_lock`, in `_tick_affect`); her hunger, its stamp and the engines'
`on_activity` follow the same read-modify-write pattern without one, older
than this program (reproduced only by injection).

### The other engines' rates are still per tick

Her affect, her hunger and her money run on the hours scale; the other
engines' per-tick rates were not converted in this program -- no measured
harm at the app's cadence, and each conversion is a design value per engine.
The shadow engine is among them: Task 36 changed what it measures from (her
rests), not its rates. What a long host downtime does to each of them is not
measured.

### The downtime catch-up reads the host's clock for its span

`catch_up_from_downtime` starts from the host's clock (`now = datetime.now()`,
listed in `tests/test_world_clock_lint.py` as a host scheduler read): the gap's
start, its slot instants, which slots are sleep hours and the backfilled
stamps follow it. Where the world clock is not the wall clock, the slots
follow the host's hours, and her money may read a new month (analysis, not
measured).

### After days away her mood is lower than a host that stayed on would have it

Measured after Task 41 (72 hours down, Monday 22:00 to Thursday 22:00, a
default persona): her mood valence is -0.866 after the catch-up where the host
that stayed on has +0.264; -0.31 twelve hours later, -0.08 a day later. Two
causes, neither fixed: her loneliness is at its top through the gap and the
catch-up's long ticks weigh it for every hour (its growth is the owner's open
question), and nothing of the gap is felt as lived -- the catch-up's
`AffectSystem.on_activity` moves no mood, where a live activity is appraised
and lifts or lowers her. Her `meals_today` after a catch-up counts the meals
of the whole gap (9 after three days; it is a counter no engine reads and the
next day's rollover clears it).

### A live meal between the wake and the catch-up; a restart differs by one tick

A gap the process lived through charges her hunger once whichever of the
host's first tick and its catch-up runs first -- except when a live meal falls
between the wake and the catch-up, which falls back to the earlier order
dependence. And a restart differs by one tick's hunger (0.004) between the two
orders.

### The old path's `mark_experience_shared(int)` marks no paired life event

[T18 parked] `mark_shared(id)` marks an item and the life event told with it;
the older `mark_experience_shared(int)` marks only the shareable. A host
should move to `mark_shared(id)` (`README.md`, "The moment").

### A stressor and a setting item that never happen

- [T15-R4] The stressor "the mess at home" is defined but never raised: her
  home comfort never falls below `COMFORT_BLEAK` (`_recompute_comfort` is
  0.35 + 0.4 x tidiness).
- [T20-R1] aura-life cannot let a housemate join an activity she may not
  start herself, so in a setting pack whose activity is one persona's alone
  (a dive), her housemate never does it with her.

### `topics=` and `disclosure=` have no source in a host yet

`observe_user_turn(topics=, disclosure=)` takes both, and what she remembers
of a turn's content now comes only through `topics`; no host computes either
yet (where they could come from was read, not built).

### The moment's `unspoken` line is empty for a persona with no secret

Found by the whole-branch review, not fixed: over three days, 36 captures
each, `Moment.unspoken` was empty in 36 of 36 for the no-profile control and
both test personas. Its shadow sources (`urge_to_confess`, `concealment_load`,
`masking`) rest under their export bar since Task 36, and the shadow states
that do cross theirs (`unease`, `felt_unsafe`, `deferential`, in 16 to 33 of
36 captures) are not among its keys. A persona with a secret gets her newest
one.

### A host turn writes to her database on the host's thread

Found by the whole-branch review, not fixed: `observe_user_turn` and
`get_moment` write to `life.db` on the caller's thread (an episode, the
user-turn state, the moment's novelty, a memory's reinforcement) with no lock
against the tick's saves, on sqlite's default five-second busy timeout. One
"database is locked" ERROR cut an energy tick short in one of four runs of a
tick thread against two host threads (none in three later runs, none on
0.5.0): heavier contention than one host makes, and the next tick goes on.
The pair costs a median of about 110 ms a turn of synchronous database work
(52 ms and 57 ms), against about 2 ms in 0.5.0.

### The moment's `to_share` offers only what an episode tells

[T18-R12] `Moment.to_share` is chosen among the unshared items an episode of
her memory tells; a shareable or a life event with no episode is never
offered there.

### Her shadow after Task 36

- [T36-R1] Her shame is eased by her felt safety above its rest, but nothing
  lifts felt safety above its rest today, and `LifeService` hands the shadow
  tick neither `intimacy` nor `conflict`: this relief waits for a caller.
- [T36-R5] Her attention-seeking and her autonomy rest near, not at, their
  seeded baselines (default 0.269 against 0.2, 0.59 against 0.5): their terms
  still measure mood from its best and felt safety from 1. Neither crosses an
  export bar at rest for a default persona.

### What she puts off is never done

Found by Task 19b's review, not fixed. Nothing ends an avoidance, and its
guilt has no rest (`DriveSystem.tick`, +0.003 a tick): two things at guilt
1.0 for every persona from her second day; a relief takes one to 0.95 and it
is back within the hour. It holds the "put off" stressor, keeps her need for
autonomy low ("things feel forced") in 10 to 12 of 12 captures over three
days, and shows as one recurring thought ("You keep putting off ..."). It
needs what the shadow engine needed in Task 36: a rest, and something that
ends an avoidance.

### Seen in a measured conversation, not fixed

- The built-in weather changes about 31 times a day at a five-minute world
  tick (a 20% chance per tick; a spell lasts a median of 30 minutes): the
  moment's situation line said rainy, foggy, cloudy at three turns five
  minutes apart. The same in 0.5.0. A host with real weather
  (`get_weather_service`, when the place feature is on) does not use it.
- `TextEmotionAnalyzer` reads the user's words from a word list: a plain
  "thank you", "my boss tore into me" and an insult aimed at her read as
  nothing (valence 0, no feeling of hers). Greetings are read first since
  Task 39; the rest is as it was.
- A life event's words are joined to the place she is in whatever they say
  ("A cute cat appeared on the windowsill at the beach").
- Her hunger comes down slowly without extra meals: three meals take 1.2
  off, a day adds 1.15.
- [T37-R1] A persona a released version wrote opens lonely and hungry at
  their tops and unsafe for about a day, with an empty memory stream: each
  comes down or fills by itself, none is migrated. Her balance alone is
  raised, once.

### `personas/profile_db.py` still calls `datetime.utcnow()`

Deprecated since Python 3.12; the suite shows it as 15 deprecation warnings
on Python 3.14. Not on a tick path.

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
from 128 names (0.6.0) to 129 and requires regenerating `tests/api_surface.json` with
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

### `LifeService.__init__` takes 24 positional parameters

(19 at publication; 24 at 0.6.0.) `persona_id` is the ninth, `datastore` the
nineteenth, `appraisal_llm` the last. Every caller in this repo
passes by keyword and the README says to, but the signature does not enforce it.

**Follow-up:** consider a `*` after `db_path`. This is a breaking change for any
positional caller, so it belongs in a major bump or in 0.x with a note.

### `persona_id` has no public accessor

The quickstart reads `agent._persona_id` to label its output.

**Follow-up:** add a read-only `persona_id` property.
