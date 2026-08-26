# aura-life

aura-life is the life-simulation engine and persona pipeline extracted from
Aura — mood, energy, goals, identity, planning, and daily life for
autonomous personas. Licensed under Apache-2.0. Currently in extraction;
this package is not yet functional (see `docs/superpowers/plans/` for the
extraction plan).

## Host hooks, and the one library default

Host services — config, the persona datastore, the LLM client, weather,
geocoding, images — reach the engine through `aura_life.hooks`, a registry the
embedding application fills once at startup (Aura does it in
`server/aura_life_bridge.py`). A hook that no host registered raises
`HookNotConfigured`, a subclass of `ImportError`. **Most** call sites wrap that in
a `try/except` and degrade the feature to "unavailable"; running with no host is
therefore supported, and you get a simulation with no LLM narration, no real
weather and no place lookups.

**`persona_now` is the one hook the library implements itself.** It is the clock
rather than a host resource, and `LifeService.persona_local_now()` calls it with no
guard — without a default, every `activity` tick of a host-free `LifeService` dies
inside the scheduler, which swallows the exception and logs it at `ERROR`.
`aura_life/defaults.py` registers a standard-library implementation when the
package is imported (`zoneinfo` when a timezone is supplied, `datetime.now()`
otherwise). A host bridge installed afterwards overwrites it; `defaults.install()`
never overwrites a provider that is already registered; `hooks.reset()` drops it.

Because a library default *is* a registration, `hooks.is_configured("persona_now")`
is `True` with no host installed. Use `hooks.provider_for(name)` to see which
implementation a hook actually resolves to:

```python
from aura_life import defaults, hooks
hooks.provider_for("persona_now") is defaults.DEFAULT_PROVIDERS["persona_now"]
# True  -> the library's own clock; False -> the host's
```

⚠️ **`persona_now` is not the only unguarded hook call site — it is the only one a
bare tick reaches today.** Twelve others are unguarded at the call site — thirteen
in total — and two of them (`life_service.py:1842`, weather;
`life_service.py:1920`, trip geocoding) sit on the `world` tick path, held off
only by early returns. An agent that owns its own `WorldEnvironment` and has a
resolved lat/lon, or one given a `trip_llm`, would hit the same silent tick
failure. `DEFERRED.md` has the analysis and the follow-up.

`tests/test_hook_call_sites.py` is the authority for that count, not this file:
it walks the AST for every hook call site, pins the thirteen as an explicit
allowlist, and fails when a new unguarded one appears. Adding a hook call
without a guard is a test failure, not a silent regression.

`tests/test_multi_instance.py` is the standalone guarantee: three `LifeService`
instances sharing one `WorldEnvironment`, in a process with no Aura on
`sys.path`, ticking without a single `ERROR` and keeping their databases to
themselves.
