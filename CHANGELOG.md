# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-26

First release. aura-life is the life-simulation engine and persona pipeline
extracted from [Aura](https://github.com/Redrum624/Aura) (private) at
commit `b9c92aff`, relicensed from PolyForm Noncommercial 1.0.0 to Apache-2.0 by
the copyright holder, who holds sole copyright in both projects.

### Added

- **The life engine** — 31 subpackages, plus the top-level `life_service.py`,
  `models.py`, `schedule.py` and `conversation_session.py`. Energy and fatigue, daily planning,
  goals, activities, affect and mood, identity and character evolution, drives,
  cognition, the body, habitation, money, career, errands, transport, social life,
  skills, chaos events, life events, memory of time, expression, continuity, shadow,
  intimacy, and a `WorldEnvironment` with weather, seasons, rooms and a clock.
- **The persona pipeline** — `aura_life.personas`: genre randomisation, personality
  configuration, profile storage, place generation and appearance generation.
- Together: **32,088 lines across 82 modules and 32 subpackages**, importing
  standalone with no Aura present.
- **A curated public facade.** `aura_life.__all__` exports **116 names**: the 114
  Aura's own `engine/__init__.py` exported, verified set-equal, plus `hooks` and
  `HookNotConfigured`. Everything else is re-exported from `aura_life.internals`,
  which is explicitly unstable.
- **`aura_life.hooks`** — a twelve-function registry that is the only seam between
  the engine and its host: `get_config`, `get_user_data_root`,
  `get_persona_datastore`, `get_image_service`, `resolve_outfit_for_context`,
  `get_schedule_phase`, `generate_and_update`, `get_weather_service`,
  `get_llm_service`, `geocode`, `resolve_timezone`, `persona_now`. The module
  imports `typing` and nothing else. An unconfigured hook raises
  `HookNotConfigured`, a subclass of `ImportError` — chosen so the `except
  ImportError` guards that already surrounded these call sites keep behaving
  exactly as they did.
- **`aura_life.defaults`** — a standard-library `persona_now`, installed on import.
  It is the only hook with a library default; without it every `activity` tick of a
  host-free `LifeService` died silently inside the scheduler. `install()` never
  overwrites an existing registration, so it cannot downgrade a host's clock.
  `hooks.provider_for(name)` was added so a consumer can tell a library default
  from a host registration (`is_configured` cannot).
- **Two per-persona providers** on `LifeService` — `user_model_provider` and
  `follow_up_provider`, both called as `provider(persona_id)` and both duck-typed.
  Omitting them is the supported standalone path; the engine skips adaptive
  cooldowns and proactive follow-up triggers.
- **A multi-instance guarantee.** `tests/test_multi_instance.py` runs three
  `LifeService` instances against one shared `WorldEnvironment`, in a process with
  no Aura on `sys.path`, and asserts on the *log stream* rather than on "did not
  raise" — because `LifeScheduler.force_tick` swallows handler exceptions and only
  logs them at `ERROR`. Zero `ERROR` records, all five tick handlers completing,
  private state advancing, and a sentinel written through the public API landing in
  exactly one agent's database.
- **Tests relocated from Aura**: `test_affect`, `test_behavior`, `test_chaos`,
  `test_character_evolution`, `test_continuity`, `test_expression`,
  `test_life_events`, `test_memory_time` — the eight that exercised only the moved
  subsystems — plus the persona-generation parity golden. New here:
  `test_multi_instance`, `test_hook_call_sites`, `test_api_surface`. 129 tests total.

### Behaviour

**Unchanged, and proven so.** A golden snapshot of twenty simulated ticks (inner
state, outer state and full status, clock frozen and RNG seeded) was captured
against Aura's pre-extraction code *before a single line moved*, and the extracted
library reproduces it byte for byte. The persona-generation golden made the same
trip and matched byte for byte on arrival. Aura keeps both goldens and runs them in
its own suite (`server/tests/test_life_parity.py`).

Nothing was refactored on the way out. Where the extraction found a defect it
recorded it in `DEFERRED.md` rather than fixing it, because a fix would have
invalidated the proof.

### Not extracted: `server/engine/relationship/`

Persona↔user relationship modelling — the user model, follow-up triggers,
conflict tracking, partner analysis, opinion evolution, conversation threads —
stayed in Aura. 11 modules, 6,428 lines.

It is not a packaging preference; the code is **single-user by construction** and
would have to be redesigned, not moved:

- **Zero `user_id` parameters.** There is not one occurrence of `user_id` anywhere
  under `server/engine/relationship/`. Every function signature assumes there is
  exactly one user and never says which.
- **A schema that enforces it.** `partner_analysis.py:199` creates its table as
  `id INTEGER PRIMARY KEY CHECK (id = 1)` — a single-row table. A second user is
  not a migration; it is a `CHECK` violation.
- **The only module-level singleton in the engine.**
  `partner_analysis.py:1576` holds `_instance: Optional[PartnerAnalysisService] =
  None`. It is the only `^_instance` anywhere under `server/engine/`, and there is
  no module-level singleton of that shape anywhere in the 32,088 extracted lines —
  which is precisely what lets N `LifeService` instances share one process.

aura-life's design target is N agents in one world. Shipping a subsystem whose
storage layer physically cannot hold a second relationship would have contradicted
that on day one. The seam is the two per-persona providers above: Aura passes its
relationship services in, and a consumer that has no such concept passes nothing.

### Known limitations

Carried into the release deliberately; see `README.md` and `DEFERRED.md`.

- No public `tick()`; driving the simulation uses `svc._scheduler.force_all_ticks()`
  and `WorldEnvironment` is not on the facade. Both are v0.2 candidates.
- Thirteen hook call sites are unguarded, two of them on the `world` tick path
  (`life_service.py:1813`, `:1919`). Unreachable today behind early returns;
  reachable by a consumer that owns its world or injects a `trip_llm`.
  `tests/test_hook_call_sites.py` is the authority for that census.
- `hooks.is_configured("persona_now")` is `True` with no host installed.
- `LifeService.start()` requires the `[scheduler]` extra and is a single-persona
  background-thread design.
