---
markmap:
  colorFreezeLevel: 2
  maxWidth: 320
  initialExpandLevel: 3
---

# aura-life

## The seam — *host ↔ engine*
### 🔌 `hooks` — *12 functions, imports `typing` only*
- `get_config`, `get_user_data_root`, `get_persona_datastore`
- `get_llm_service`, `get_weather_service`, `get_image_service`
- `geocode`, `resolve_timezone`, `persona_now`
- `get_schedule_phase`, `resolve_outfit_for_context`, `generate_and_update`
### ⚠️ `HookNotConfigured` — *subclasses `ImportError`*
- unconfigured hook → that feature degrades, the tick still completes
### 🔧 `defaults` — *`persona_now`, the one library default*
### Per-persona providers — *constructor args, duck-typed*
- `user_model_provider` — *response rate, quiet windows, topics*
- `follow_up_provider` — *proactive triggers*
- omitting both is the supported standalone path

## ⚙️ The clock — `scheduler`
### `LifeScheduler` — *APScheduler when installed*
- world tick — *5 min*
- energy tick — *5 min*
- activity tick — *20 min*
- plan tick — *30 min*
- goal tick — *60 min*
### `force_all_ticks()` — *manual drive, always available*
### No public `tick()` — *the caller owns the clock*

## `LifeService` — *the orchestrator*
### 7,077 lines, one instance per persona
### Engines never call each other — *every signal routes through here*
### No module-level singleton — *N agents, one process*

## The engines — *30 subpackages*
### Body & rhythm
- `energy` `body` `sustenance` `cognitive` `intimacy`
### Inner weather
- `emotion` `affect` `shadow` `drive` `chaos`
### Intent & action
- `planner` `activities` `goals` `skills` `errands` `behavior`
### Place & means
- `world` `location` `habitation` `transportation` `job` `money`
### Others & self
- `social` `identity` `expression` `personas` `persona_evolution`
### Time & meaning
- `continuity` `memory_time` `life_events`

## 🌍 `world` — *the shared world*
### `WorldEnvironment` — *weather, season, time of day, locations*
### Shared by every persona in the process
### Hand one in and you own its clock — *`LifeService` won't tick a world it was given*

## Readouts — *what the host consumes*
### `context` — `LifeContextBuilder`
- prompt sections under a token budget
- location · weather · energy · mood · stress · needs · room · finance · career
### `get_status()` — *one dict snapshot*
### `shareable_experiences` — *worth mentioning next time you speak*

## 💾 Persistence
### `life.db` — *SQLite, one file per persona*
### 35 tables — *`life_energy_state`, `life_goals`, `life_daily_plan`, `activity_logs`, …*

## Public surface
### 117 names — *pinned against `tests/api_surface.json`*
### Subsystem classes by module path — *`from aura_life.world import WorldEnvironment`*
### ~~`internals`~~ — *explicitly unstable; a to-do, not an API*

## Key flows
- host → `hooks.configure(...)` → engine
- `LifeScheduler` → 5 ticks → `LifeService`
- `WorldEnvironment` → read by every `LifeService`
- `LifeService` → engines → `LifeService` → `life.db`
- `LifeService` → `context` → host LLM system prompt
