"""Host-service hooks for the life engine.

The engine simulates a life; it does not own the machine it runs on. Config,
the LLM, weather, geocoding, image and visual-description services, the persona
datastore and the persona clock all belong to the **host application**. This
module is the single seam between the two: the engine calls the plain functions
below, and the host registers implementations once at startup with
:func:`configure`.

The origin host registers them in a small bridge module of its own; a different
host would write its own five-line bridge.

Nothing here imports the host — that is the point. This file must keep importing
only the standard library so ``import aura_life`` works with no host present.

When a hook has not been configured it raises :class:`HookNotConfigured`, a
subclass of :class:`ImportError`. That inheritance is load-bearing: these calls
replaced function-local ``from config import get_config`` statements whose
failure mode was ``ModuleNotFoundError`` (itself an ``ImportError``), and every
``except ImportError`` guard already written around those call sites must keep
behaving exactly as it did.

One hook is an exception: ``persona_now`` is the clock, not a host resource, and
the library ships its own implementation for it in :mod:`aura_life.defaults`,
registered when ``aura_life`` is imported. Nothing is imported here to make that
happen -- this module still imports ``typing`` and nothing else -- and
:func:`reset` drops it along with everything else. See that module for why the
default exists at all.
"""

from typing import Any, Callable, Dict, Optional

__all__ = [
    "HookNotConfigured",
    "HOOK_NAMES",
    "configure",
    "reset",
    "is_configured",
    "provider_for",
    # hooks
    "get_config",
    "get_user_data_root",
    "get_persona_datastore",
    "get_image_service",
    "resolve_outfit_for_context",
    "get_schedule_phase",
    "generate_and_update",
    "get_weather_service",
    "get_llm_service",
    "geocode",
    "resolve_timezone",
    "persona_now",
]


class HookNotConfigured(ImportError):
    """Raised when the engine calls a hook the host never registered.

    Subclasses ``ImportError`` so existing ``except ImportError`` guards around
    the call sites keep catching it.
    """


#: Every hook this module exposes. ``configure()`` refuses anything else, so a
#: typo in a host bridge fails loudly at startup instead of silently at the
#: first call months later.
HOOK_NAMES = (
    "get_config",
    "get_user_data_root",
    "get_persona_datastore",
    "get_image_service",
    "resolve_outfit_for_context",
    "get_schedule_phase",
    "generate_and_update",
    "get_weather_service",
    "get_llm_service",
    "geocode",
    "resolve_timezone",
    "persona_now",
)

_NOT_CONFIGURED = (
    "aura_life hook {name!r} is not configured; the host application must call "
    "aura_life.hooks.configure({name}=...)"
)

_registry: Dict[str, Callable[..., Any]] = {}


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------

def configure(**providers: Callable[..., Any]) -> None:
    """Register host implementations. Idempotent — re-registering overwrites.

    Raises:
        ValueError: if a name is not one of :data:`HOOK_NAMES`, or a provider
            is not callable.
    """
    for name, provider in providers.items():
        if name not in HOOK_NAMES:
            raise ValueError(
                f"unknown aura_life hook {name!r}; known hooks: {', '.join(HOOK_NAMES)}"
            )
        if not callable(provider):
            raise ValueError(f"provider for aura_life hook {name!r} is not callable")
    _registry.update(providers)


def reset() -> None:
    """Forget every registered provider (tests, and host teardown).

    This drops the library's own defaults too (see :mod:`aura_life.defaults`),
    leaving *every* hook in the raise-when-unconfigured state. Call
    ``aura_life.defaults.install()`` to put them back.
    """
    _registry.clear()


def is_configured(name: str) -> bool:
    """Whether *name* currently has a provider registered.

    True for a library default as well as a host registration -- use
    :func:`provider_for` to tell the two apart.
    """
    return name in _registry


def provider_for(name: str) -> Optional[Callable[..., Any]]:
    """The provider currently registered for *name*, or ``None`` if there is none.

    The only supported way to see *which* implementation a hook resolves to.
    ``aura_life.defaults`` ships a default for ``persona_now``, so
    ``is_configured("persona_now")`` is ``True`` even with no host installed;
    comparing against ``aura_life.defaults.DEFAULT_PROVIDERS[name]`` is how a
    consumer distinguishes "the library's own" from "the host's".

    Raises:
        ValueError: if *name* is not one of :data:`HOOK_NAMES`.
    """
    if name not in HOOK_NAMES:
        raise ValueError(
            f"unknown aura_life hook {name!r}; known hooks: {', '.join(HOOK_NAMES)}"
        )
    return _registry.get(name)


def _call(name: str, *args: Any, **kwargs: Any) -> Any:
    try:
        provider = _registry[name]
    except KeyError:
        raise HookNotConfigured(_NOT_CONFIGURED.format(name=name)) from None
    return provider(*args, **kwargs)


# ----------------------------------------------------------------------
# The hooks
# ----------------------------------------------------------------------

def get_config() -> Any:
    """Host configuration object (``.data_dir``, ``.place_enabled``, ...)."""
    return _call("get_config")


def get_user_data_root() -> Any:
    """Root directory the host keeps per-user data under."""
    return _call("get_user_data_root")


def get_persona_datastore(
    persona_id: str,
    data_dir: Any = None,
    device_id: Optional[str] = None,
) -> Any:
    """The persona's consolidated datastore."""
    return _call("get_persona_datastore", persona_id, data_dir, device_id)


def get_image_service() -> Any:
    """Host image/self-photo service."""
    return _call("get_image_service")


def resolve_outfit_for_context(
    activity: str,
    location: str,
    time_of_day: str,
    outfits: dict,
    default_outfit: str,
) -> Any:
    """Pick the outfit that fits the current schedule context."""
    return _call(
        "resolve_outfit_for_context",
        activity=activity,
        location=location,
        time_of_day=time_of_day,
        outfits=outfits,
        default_outfit=default_outfit,
    )


def get_schedule_phase(life_service: Any = None, sleep_schedule: Any = None) -> Any:
    """Coarse phase of the persona's day ('morning', 'evening', ...)."""
    return _call("get_schedule_phase", life_service, sleep_schedule)


def generate_and_update(
    persona_id: str,
    definition: Any,
    life_service: Any = None,
    world: Any = None,
    image_dir: Optional[str] = None,
) -> Any:
    """Regenerate the persona's visual description and persist it."""
    return _call(
        "generate_and_update", persona_id, definition, life_service, world, image_dir
    )


def get_weather_service() -> Any:
    """Host weather service (real observations, not the world sim)."""
    return _call("get_weather_service")


def get_llm_service() -> Any:
    """Host LLM client."""
    return _call("get_llm_service")


def geocode(name: str, count: int = 1, **kwargs: Any) -> Any:
    """Geocode a place name to ``{city, country, lat, lon, timezone}`` or None."""
    return _call("geocode", name, count, **kwargs)


def resolve_timezone(lat: float, lon: float, **kwargs: Any) -> Any:
    """IANA timezone string for a coordinate, or None."""
    return _call("resolve_timezone", lat, lon, **kwargs)


def persona_now(timezone: Optional[str] = None) -> Any:
    """'Now' in the persona's timezone (server-local when *timezone* is falsy)."""
    return _call("persona_now", timezone)
