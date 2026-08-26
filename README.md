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
`HookNotConfigured`, a subclass of `ImportError`, and the engine's existing
guards turn that into a `WARNING` and a disabled feature. Running with no host at
all is therefore supported: you get a simulation with no LLM narration, no real
weather and no place lookups.

**`persona_now` is the exception: the library supplies its own.** It is the
clock rather than a host resource, and `LifeService.persona_local_now()` is the
one call site with no `except ImportError` around it — without a default, every
`activity` tick of a host-free `LifeService` dies inside the scheduler, which
swallows the exception and logs it at `ERROR`. `aura_life/defaults.py` registers
a standard-library implementation at import time (`zoneinfo` when a timezone is
supplied, `datetime.now()` otherwise); a host bridge installed afterwards
overwrites it, and `hooks.reset()` drops it. See `DEFERRED.md` for the follow-up.

`tests/test_multi_instance.py` is the standalone guarantee: three `LifeService`
instances sharing one `WorldEnvironment`, in a process with no Aura on
`sys.path`, ticking without a single `ERROR` and keeping their databases to
themselves.

