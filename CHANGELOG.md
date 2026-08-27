# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) — with two extra
narrative sections under 0.1.0, *Behaviour* and *Not extracted*, that a
pure-extraction release needs and Keep a Changelog has no type for — and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-08-27 — pre-publication hardening

Everything below landed **after** the `v0.1.0` tag and before the repository was
made public. The tag therefore does not contain these changes.

0.1.0's contract was "behaviour identical to the origin repo, no refactoring, and
defects get recorded rather than fixed" — that is what made the parity proof
meaningful. **That contract ends here.** A first public release that knowingly
ships a traversal sink, an SQL-injection sink and a public method that raises
unconditionally is not defensible, so an audit was run across five dimensions
(privacy, security, memory leaks, mock data, docs accuracy) and the approved
findings were fixed test-first.

### Security

- **Persona ids are validated at every id → path boundary.** A new internal
  `aura_life._safe_ids` supplies `safe_persona_id()` and `safe_join()`: an id must
  match `[a-z0-9_-]{1,64}` after lowercasing and is **rejected** with `ValueError`,
  never stripped or repaired, and the joined path is re-proved to sit under the
  resolved base directory. Previously `get_profile_db()`, `get_emotion_persistence()`
  and `get_owner_device_id()` interpolated the caller's id into a path with no
  validation at all, so a `..` segment escaped `data_dir` — the first two *created*
  files and directories outside it, and `get_owner_device_id()` was an arbitrary-read
  primitive that returned the `owner_device_id` (the multi-user isolation key) out of
  whatever `profile.db` the traversal landed on. Covered by
  `tests/test_persona_id_safety.py`.
- **`ProfileDatabase.update_field()` no longer builds SQL from caller input.** It
  interpolated `field` straight into `UPDATE profile_core SET {field} = ?`, so
  `field="name = 'x', owner_device_id"` rewrote the isolation column. The name must
  now appear in `PRAGMA table_info(profile_core)` and is quoted as an identifier —
  the same whitelist boundary the neighbouring `update_appearance()` already used.
  It was gated rather than deleted because it is an exported method of an exported
  class and this library was just extracted from a host whose call sites are not
  visible here.
- **The place kill switch fails closed.** `place_enabled` was read inside a `try`
  whose `except Exception` was a bare `pass`, so `HookNotConfigured` — the state of
  every host that has not registered `get_config`, i.e. the default — fell through
  and ran weather fetching and trip rolling as though the flag were on. An
  unreadable config now means "off".
- **The device-location store enforces the contract its docstring advertises.**
  `save_device_location()` rounds to `STORED_PRECISION` (2 decimals) and rejects
  out-of-range coordinates instead of writing whatever float pair it was handed.
  The docstring now separates what this module guarantees (a precision floor, no
  reverse-geocode, nothing but the point and a timestamp) from what the client is
  responsible for (the ~40 km fuzz, which happens outside this repo and cannot be
  verified here).

### Fixed

- **`persona_id` was silently discarded for any relative `db_path`.**
  `_persist_activity_emotions` derived the id with
  `db_parent if db_parent != "." else self._persona_id`, but
  `Path("mara.db").parent.name` is the empty string, not `"."` — and so is
  `Path("./mara.db").parent.name`, because `Path` normalises `./x` to `x`. The
  `"."` branch was therefore dead code for every relative and drive-root path:
  the explicit `persona_id` a caller passed was never consulted, and the warning
  claimed "no persona_id" about a service that had one. Activity emotions stopped
  persisting for those callers. Now guarded with `not in ("", ".")`.

- **`LifeService._datastore` was read three times and never assigned.**
  `add_calendar_entry()` and `get_upcoming_calendar_entries()` are public methods
  and both raised `AttributeError` on a fresh instance; `_scan_calendar_for_triggers()`
  runs on a tick behind a bare `except Exception`, so it failed **silently** —
  calendar `UPCOMING_EVENT` triggers, post-event `EMOTIONAL_CHECK_IN` check-ins and
  anniversary promotion **had never fired at all**, in any deployment, for the whole
  life of the code. `datastore` is now an optional constructor argument, appended
  last so no positional caller shifts; with none supplied the calendar lives in
  `db_path`, where `_init_database()` already created the table. Full write-up in
  `DEFERRED.md`; regression coverage in `tests/test_calendar_datastore.py`.
- **Activity emotions are no longer persisted under an invented persona id.** The
  fallback was a hardcoded character name from the origin application, so a
  `LifeService` that could not derive an id silently wrote another persona's file.
  It now skips the write and logs at `WARNING`.
- **Silent swallows narrowed.** Several `except Exception: pass` blocks around DB
  loads (identity values, behavioural tendencies, world location, places) are now
  `except sqlite3.OperationalError` for the genuine first-run-empty-table case, with
  anything else logged at `WARNING` with `exc_info=True`. The excitement-share
  trigger and the three user-model provider call sites, all previously swallowed
  with no log at any level, now log too — a broken host provider degraded three
  behaviours invisibly and forever.
- **Unbounded collections capped.** Every one of these grew for the life of the
  persona and was serialized to disk on each save: stress sources (10, with the two
  internal stressors pinned so the cap cannot become a stress ramp), goal history
  (20), anniversaries (20), secrets (10), plan revision notes (20), finished books
  (200, now deduped — the re-read fallback re-appended the same title forever),
  user-registered locations (100), `emotion_history` rows (500 per persona DB),
  `activity_logs` rows (500), shared `shareable_experiences` rows (90 days), and
  non-recurring `user_calendar` rows (30 days past the event). Caps are module or
  class constants, applied on write **and** on load, so a database written before
  the cap does not reload the whole leak on restart.
- **Teardown paths that did not exist.** `LifeScheduler.stop()` now calls
  `shutdown(wait=True)` and drops its reference, so in-flight ticks settle and the
  dead scheduler plus everything its jobs closed over becomes collectable;
  `LifeService.stop()` joins its two background threads (10 s each) *before*
  `_save_state()`, because both mutate engine state and saving first persisted a
  snapshot they then moved past; and the visual-description thread, which was
  spawned unguarded on every activity tick, is now a single handle that is skipped
  while one is alive.
- Stale internal comments removed: a "NO logic yet, schema only" placeholder sitting
  directly above the fully-implemented methods it described, private tracker ticket
  ids across nine sites, and a docstring naming an environment variable this package
  never reads.

### Added

- **`clear_persona_schedule()` joins the public facade** — `aura_life.__all__`
  goes from 116 names to 117. The rest of `schedule`'s names were already
  exported, so the teardown for a cache the facade hands you belongs beside them.
  `clear_emotion_persistence()` deliberately does *not* join: the `emotion`
  subpackage exports nothing through the facade, and one leaf without a trunk
  would be worse than a consistent subpackage import. See `DEFERRED.md`.

- `emotion_persistence.clear_emotion_persistence(persona_id=None)`,
  `schedule.clear_persona_schedule(persona_id=None)` and
  `MultiPersonalityManager.remove_personality(personality_id)` — teardown for three
  process-global caches that previously only grew. `remove_personality` stops the
  persona's `LifeService` before evicting it, so switching personas in a long-running
  host no longer leaks a whole simulation and its live tick jobs. None of the three
  is on `aura_life.__all__`; see `DEFERRED.md` for the v0.2 decision.
- `EmotionEngine(ocean_traits=...)` and
  `personality_config.set_default_languages(...)` / `get_default_languages()` — two
  values that were hardcoded to the origin application's character and locale are now
  inputs.
- Six test modules: `test_persona_id_safety`, `test_calendar_datastore`,
  `test_collection_caps`, `test_life_service_retention`,
  `test_life_service_failure_modes`, `test_emotion_history_retention`. The suite is
  **319 tests across 21 modules**, up from 129 across 13; the original 129 still pass
  unchanged.

### Changed

- **BREAKING — `PersonaSchedule` no longer ships three hardcoded characters.**
  The module previously dispatched on `persona_id == "florence" / "samantha" /
  "alice"` and carried those three characters' full authored weekly schedules —
  content belonging to the private application this library was extracted from,
  and dead weight for everyone else, since every other `persona_id` silently got
  an empty schedule. The dispatch and all three schedules are removed.
  `PersonaSchedule(persona_id, events=None)` is now a host-populated container
  with `add_event()`; empty is the documented default for every id. The module
  went from 355 lines to 218. Exported names are unchanged.

These are visible to a caller. None was avoidable while fixing the row above it.

- **`LifeService(db_path=...)` is effectively required.** The default was the
  relative string `"life.db"`, which put a SQLite file in whatever the process CWD
  happened to be and silently made two personas started from one directory share a
  database. It now defaults to `None` and resolves to
  `get_config().data_dir / <persona_id> / "life.db"`; with no host configured and no
  `db_path`, the constructor raises `ValueError` naming both options rather than
  scattering a file.
- **`LifeService.__init__` takes 19 parameters, not 18** — `datastore` is appended
  last, so every existing positional index is unchanged and `persona_id` is still
  the ninth.
- **`emotion_engine.TRAITS` is renamed `DEFAULT_OCEAN_TRAITS` and revalued** to a
  neutral 0.5-across profile. It was one specific character's OCEAN scores and it was
  the production default for every persona that omitted a baseline. A host that
  imported `TRAITS` breaks; a host that relied on the implicit baseline now gets a
  flat one.
- **`MultiPersonalityManager.current_id` returns `Optional[str]`**, initially `None`.
  It was initialized to a hardcoded persona id from the origin application, so a
  fresh manager resolved to a persona nobody had registered.
- **`GoalEngine.to_dict()["completed_count"]` / `["abandoned_count"]` are
  retained-history counts, not lifetime totals** — an unavoidable consequence of
  capping the history. A host displaying them as lifetime stats needs its own
  counter.
- **`ProfileDatabase.update_field()` raises `ValueError` on an unknown field**, where
  it previously raised `sqlite3.OperationalError`. A caller catching only
  `OperationalError` no longer catches.
- **Persona-id case is uniform.** `get_profile_db()` and `get_emotion_persistence()`
  now lowercase as `get_owner_device_id()` always did; the three previously
  disagreed, so `get_profile_db("Alice")` wrote `data/Alice/profile.db` while
  `get_owner_device_id("Alice")` read `data/alice/profile.db`. Ids generated inside
  the library were already lowercase, so real ids are unaffected.
- User-derived content is out of the logs. Calendar event names (documented as
  "extracted from conversation") were logged at `INFO` on add, on anniversary
  promotion and on post-event check-in; coordinates were logged at `INFO` and
  `WARNING` at three sites. Both now log an id, or nothing, at `DEBUG`.

## [0.1.0] - 2026-08-26

First release. aura-life is the life-simulation engine and persona pipeline
extracted from a larger private application by the same author, relicensed from
PolyForm Noncommercial 1.0.0 to Apache-2.0 by the copyright holder, who holds
sole copyright in both projects.

### Added

- **The life engine** — 31 subpackages, plus the top-level `life_service.py`,
  `models.py`, `schedule.py` and `conversation_session.py`. Energy and fatigue,
  daily planning, goals, activities, affect and mood, identity and character
  evolution, drives, cognition, behaviour and creative output, the body,
  habitation, money, career, errands, sustenance, transport, social life, skills,
  chaos events, life events, memory of time, expression, continuity, shadow,
  intimacy, location and places, prompt-context assembly, the tick scheduler, and a
  `WorldEnvironment` with weather, seasons, rooms and a clock. `README.md` carries
  the exhaustive one-line-per-subpackage index.
- **The persona pipeline** — `aura_life.personas`: genre randomisation, personality
  configuration, profile storage, place generation and appearance generation.
- Together: **32,088 lines across 82 modules and 32 subpackages**, importing
  standalone with no host application present.
- **A curated public facade.** `aura_life.__all__` exported **116 names** at 0.1.0 (117 as of 0.2.0): the 114
  the origin repo's own engine package exported — verified set-equal at extraction
  time, against a repository that is not published, so that half of the claim is not
  checkable here — plus `hooks` and `HookNotConfigured`. Everything else is
  re-exported from `aura_life.internals`, which is explicitly unstable.
- **`aura_life.hooks`** — a twelve-function registry that is the only seam between
  the engine and its host: `get_config`, `get_user_data_root`,
  `get_persona_datastore`, `get_image_service`, `resolve_outfit_for_context`,
  `get_schedule_phase`, `generate_and_update`, `get_weather_service`,
  `get_llm_service`, `geocode`, `resolve_timezone`, `persona_now`. The module
  imports `typing` and nothing else. An unconfigured hook raises
  `HookNotConfigured`, a subclass of `ImportError` — chosen so the `except
  ImportError` guards that already surrounded these call sites keep behaving exactly
  as they did.
- **`aura_life.defaults`** — a standard-library `persona_now`, installed on import.
  It is the only hook with a library default; without it every `activity` tick of a
  host-free `LifeService` died silently inside the scheduler. `install()` never
  overwrites an existing registration, so it cannot downgrade a host's clock.
  `hooks.provider_for(name)` was added so a consumer can tell a library default from
  a host registration (`is_configured` cannot).
- **Two per-persona providers** on `LifeService` — `user_model_provider` and
  `follow_up_provider`, both called as `provider(persona_id)` and both duck-typed.
  Omitting them is the supported standalone path; the engine skips adaptive
  cooldowns and proactive follow-up triggers.
- **A multi-instance guarantee.** `tests/test_multi_instance.py` runs three
  `LifeService` instances against one shared `WorldEnvironment`, in a process with no
  host application on `sys.path`, and asserts on the *log stream* rather than on "did not raise"
  — because `LifeScheduler.force_tick` swallows handler exceptions and only logs them
  at `ERROR`. Zero `ERROR` records, all five tick handlers completing, private state
  advancing, and a sentinel written through the public API landing in exactly one
  agent's database.
- **Tests relocated from the origin repo**: `test_affect`, `test_behavior`, `test_chaos`,
  `test_character_evolution`, `test_continuity`, `test_expression`,
  `test_life_events`, `test_memory_time` — the eight that exercised only the moved
  subsystems — plus `test_persona_parity` and its golden. New here:
  `test_multi_instance`, `test_hook_call_sites`, `test_api_surface`, `test_smoke`.
  13 modules, 129 tests.

### Behaviour

**Unchanged, and proven so.** A golden snapshot of twenty simulated ticks (inner
state, outer state and full status, clock frozen and RNG seeded) was captured
against the pre-extraction code *before a single line moved*, and the extracted
library reproduces it byte for byte. The persona-generation golden made the same
trip and matched byte for byte on arrival. Measured at extraction: **70 of the 78
moved modules are line-for-line identical to their originals**, the remainder
differing where imports had to be rewritten. Exactly one departure from byte
identity was made deliberately, in a `place_service.py` docstring, with parity
re-run immediately afterwards.

The two goldens then parted ways, and each is guarded by exactly one suite:

| Golden | Lives in | Run by |
|---|---|---|
| Life simulation (20 ticks) | the origin repo's test fixtures | the origin repo's parity suite |
| Persona generation | `tests/fixtures/persona_parity_golden.json` | this library — `tests/test_persona_parity.py` |

The persona golden moved here with the persona pipeline; it is **not** in the
origin repo's fixtures, and that suite does not guard persona generation.

Nothing was refactored on the way out. Where the extraction found a defect it
recorded it in `DEFERRED.md` rather than fixing it, because a fix would have
invalidated the proof. (The Unreleased section above is where that policy ends.)

### Not extracted: relationship modelling

Persona↔user relationship modelling — the user model, follow-up triggers, conflict
tracking, partner analysis, opinion evolution, conversation threads — stayed in the
origin application. 11 modules, 6,428 lines.

It is not a packaging preference; the code is **single-user by construction** and
would have to be redesigned, not moved. Three measurements, the last two quoted in
full so the argument does not depend on reading a private repository:

- **Zero `user_id` parameters.** Not one occurrence anywhere in that package. Every
  function signature assumes there is exactly one user and never says which.
- **A schema that enforces it.** The partner-analysis table is created as
  `id INTEGER PRIMARY KEY CHECK (id = 1)` — a single-row table. A second user is not
  a migration; it is a `CHECK` violation.
- **The only module-level singleton in the engine.** That same module holds
  `_instance: Optional[PartnerAnalysisService] = None`. It is the only `^_instance`
  anywhere in the origin engine, and there is no module-level singleton of that
  shape anywhere in the 32,088 extracted lines — which is precisely what lets N
  `LifeService` instances share one process.

aura-life's design target is N agents in one world. Shipping a subsystem whose
storage layer physically cannot hold a second relationship would have contradicted
that on day one. The seam is the two per-persona providers above: the host passes
its relationship services in, and a consumer that has no such concept passes
nothing.

### Known limitations

Carried into the release deliberately; see `README.md` and `DEFERRED.md`.

- No public `tick()`; driving the simulation uses `svc._scheduler.force_all_ticks()`
  and `WorldEnvironment` is not on the facade. Both are v0.2 candidates.
- Thirteen hook call sites are unguarded, two of them on the `world` tick path.
  `tests/test_hook_call_sites.py` is the authority for that census.
- `hooks.is_configured("persona_now")` is `True` with no host installed.
- `LifeService.start()` requires the `[scheduler]` extra and is a single-persona
  background-thread design.

[0.2.0]: https://github.com/Redrum624/aura-life/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Redrum624/aura-life/releases/tag/v0.1.0
