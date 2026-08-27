"""What the library does when no host application has registered a hook.

:mod:`aura_life.hooks` is the seam between this library and whatever application
embeds it. Almost every hook is a *host resource* -- config, the persona
datastore, the LLM client, weather, images -- with no sensible library-level
implementation, so calling one without a host raises
:class:`~aura_life.hooks.HookNotConfigured` and the engine's ``except ImportError``
guards degrade that feature to "unavailable" with a ``WARNING``.

``persona_now`` is the one exception, and this module is why.

**Why it needs a default.** ``LifeService.persona_local_now()`` calls the
``persona_now`` hook *unguarded* -- it is the single hook call site in the moved
code with no ``try/except ImportError`` around it, because in the origin host it
replaced a ``from context.time_context import persona_now`` that could not fail.
That host always installs its bridge, so that site never fires there. A bare
library consumer has no bridge: every ``activity`` tick then dies inside
``LifeScheduler.force_tick``, which catches the exception and only
``logger.error``s it. The library would import cleanly, construct a
``LifeService`` cleanly, tick forever and simulate nothing. Three agents in a
sandbox would look alive and never do anything.

**Why a default is safe here.** ``persona_now`` is not a host resource, it is the
clock, and the standard library already has one. The default reproduces the
hook's documented contract exactly: a timezone-aware ``datetime`` in the
requested IANA zone, or a naive server-local ``datetime.now()`` when no timezone
is given or the zone cannot be resolved. It never guesses a timezone.

**Why this lives here and not in hooks.py.** ``hooks.py`` is required to import
``typing`` and nothing else -- that is its guarantee that the seam itself can
never drag anything in. The default needs ``datetime``, so it lives in its own
module and is registered from ``aura_life/__init__.py``.

**How it interacts with a host.** :func:`install` uses the ordinary
``hooks.configure`` path, so a host bridge that registers ``persona_now``
afterwards overwrites it, and ``hooks.reset()`` drops it along with every host
provider -- which is what leaves the bare raise-when-unconfigured contract intact
for the hook tests that assert it.

:func:`install` **never overwrites a provider that is already registered**. It is
safe to call at any point, including after a host bridge has installed its own
clock: a host that has registered ``persona_now`` keeps it. Without that rule, the
documented "call ``install()`` again after a ``reset()``" recovery would silently
replace a host's clock -- a virtual or frozen one, say -- with the system clock,
and nothing would report it.

Consequence worth knowing: ``hooks.is_configured("persona_now")`` is ``True`` with
no host installed, because a library default *is* a registration. To tell which
implementation a hook currently resolves to, use ``hooks.provider_for(name)`` and
compare it against :data:`DEFAULT_PROVIDERS`::

    from aura_life import defaults, hooks
    hooks.provider_for("persona_now") is defaults.DEFAULT_PROVIDERS["persona_now"]
    # True  -> the library's own clock; False -> the host's
"""

from typing import Any, Callable, Dict, Optional

from aura_life import hooks

__all__ = ["DEFAULT_PROVIDERS", "install", "persona_now"]


def persona_now(timezone: Optional[str] = None) -> Any:
    """The system clock, in *timezone* when one is given and resolvable.

    Args:
        timezone: IANA timezone string (e.g. ``"Europe/Lisbon"``). When falsy,
            unresolvable, or when ``zoneinfo`` is unavailable, falls back to a
            naive server-local ``datetime.now()``.

    ``datetime`` and ``zoneinfo`` are imported at call time, not at module
    import, so a host or test that fakes the ``datetime`` module still gets its
    fake -- the same late-binding property the origin host's bridge relies on.
    """
    from datetime import datetime

    if timezone:
        try:
            from zoneinfo import ZoneInfo

            return datetime.now(ZoneInfo(timezone))
        except Exception:
            # Unknown zone, or no tzdata on this machine. The hook's contract is
            # to fall back to server-local time rather than fail the caller.
            pass
    return datetime.now()


#: Hooks the library implements itself. Only ``persona_now`` has a default; see
#: the module docstring for why it is the sole exception.
DEFAULT_PROVIDERS: Dict[str, Callable[..., Any]] = {
    "persona_now": persona_now,
}


def install() -> None:
    """Register :data:`DEFAULT_PROVIDERS` for any hook that has no provider yet.

    Called once from ``aura_life/__init__.py``, so any consumer that imports the
    package -- or any module in it -- gets the defaults. Idempotent.

    **Non-clobbering by design.** A hook that already has a provider is left
    alone, so calling this after a host bridge has installed its own
    ``persona_now`` cannot silently downgrade the host's clock to the system one.
    A host that genuinely wants the library default back can ask for it
    explicitly: ``hooks.configure(**DEFAULT_PROVIDERS)``.
    """
    missing = {
        name: provider
        for name, provider in DEFAULT_PROVIDERS.items()
        if not hooks.is_configured(name)
    }
    if missing:
        hooks.configure(**missing)
