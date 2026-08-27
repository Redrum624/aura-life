"""The unguarded-hook-call-site census, as an executable check rather than prose.

`DEFERRED.md` and `README.md` both state how many hook call sites in this library
are **unguarded** — reached with no `try/except` around them, so an unconfigured
hook raises `HookNotConfigured` straight into the caller. On a tick path that is
invisible: `LifeScheduler.force_tick` wraps every handler in
``except Exception: logger.error(...)``, so the tick stops doing anything at all
while the process looks healthy. Task 6 found exactly that — `persona_now` had
been failing 100% of `activity` ticks with nothing but an ERROR line to show for
it.

That number reached the documentation as prose derived from a throwaway script,
and it drifted within one review round (it was written as "eleven" against a table
that listed thirteen). This module is the fix: the census is **computed**, and a
new unguarded call site fails the suite instead of quietly enlarging a number
nobody re-derives.

What is pinned is the *set of sites*, keyed by module + enclosing function + hook
name — deliberately **not** line numbers, which churn on every edit above them.
The point is that a new unguarded site is caught, not that the file never moves.

None of the thirteen may be "fixed" here: they are moved code under a verbatim
contract, and adding a guard would change behaviour the origin host's parity
golden pins. See
`DEFERRED.md` for the follow-up and for which two are live hazards.
"""

import ast
import pathlib
from functools import lru_cache

import aura_life
from aura_life.hooks import HOOK_NAMES

LIBRARY_DIR = pathlib.Path(aura_life.__file__).resolve().parent

#: Every hook call site in the library that is **not** wrapped in a `try`, keyed by
#: ``(module, enclosing function, hook)``. Thirteen entries.
#:
#: Line numbers are deliberately absent — they churn. The enclosing function is in
#: the key so that two unguarded uses of the same hook in one module (as in
#: ``profile_db`` and ``place_generation``) stay distinguishable instead of
#: collapsing into one entry and hiding a site.
#:
#: `DEFERRED.md` carries the analysis: which are on a tick path, which are covered
#: by a caller's guard, and which have not been traced.
UNGUARDED_CALL_SITES = frozenset({
    # -- On a tick path. force_tick swallows these; see DEFERRED.md.
    ("aura_life.life_service", "persona_local_now", "persona_now"),
    ("aura_life.life_service", "_get_weather_service", "get_weather_service"),
    ("aura_life.life_service", "_geocode_trip", "geocode"),
    # -- Unguarded at the site, but covered by a caller's guard.
    ("aura_life.emotion.emotion_persistence", "get_emotion_persistence", "get_config"),
    # -- Off the tested tick paths; host-free reachability NOT traced.
    ("aura_life.location.device_location", "_store_path", "get_user_data_root"),
    ("aura_life.location.place_service", "_get_llm", "get_llm_service"),
    ("aura_life.location.place_service", "_get_geocode", "geocode"),
    ("aura_life.location.place_service", "_get_config", "get_config"),
    ("aura_life.personas.personality_config", "get_personality", "get_config"),
    ("aura_life.personas.place_generation", "generate_cultural_stance", "get_llm_service"),
    ("aura_life.personas.place_generation", "generate_appearance", "get_llm_service"),
    ("aura_life.personas.profile_db", "get_profile_db", "get_config"),
    ("aura_life.personas.profile_db", "get_owner_device_id", "get_config"),
})

#: Modules allowed to touch the hook registry by attribute (``hooks.configure``,
#: ``hooks.is_configured``). Everything else must use the
#: ``from aura_life.hooks import <hook>`` idiom the census walk understands.
_REGISTRY_MODULES = {"aura_life.defaults", "aura_life.hooks"}

_FAILURE_HELP = """
A hook call site's guard status changed.

Why this test exists: an unconfigured hook raises HookNotConfigured. On a tick
path, LifeScheduler.force_tick catches it and only logger.error()s it, so the
tick silently stops doing any work while the process looks healthy. That is a
real bug this library shipped (persona_now, Task 6), not a hypothetical.

If you ADDED an unguarded call site, pick one:
  * wrap it in `try: ... except ImportError:` and degrade the feature, logging at
    WARNING (what most sites do); or
  * give the hook a library default in aura_life/defaults.py, if it has a sane
    standard-library implementation the way `persona_now` does; or
  * add it to UNGUARDED_CALL_SITES **with a written reason**, and record it in
    DEFERRED.md alongside the other thirteen. Do not add it silently.

If you GUARDED one of the listed sites, remove it from UNGUARDED_CALL_SITES and
update the counts in DEFERRED.md and README.md, which cite this test.
"""


def _guarding_tries(node, parents):
    """Every enclosing `Try` that would actually catch *node* raising.

    Walks the full ancestor chain, so a call nested inside `if`/`for`/`with`
    blocks under a `try` still counts as guarded. A node reached from a `Try`'s
    *handlers* or *orelse* is NOT protected by that `Try`, so only membership in
    its `body` counts.
    """
    found = []
    prev, cur = node, parents.get(node)
    while cur is not None:
        if isinstance(cur, ast.Try) and any(prev is stmt for stmt in cur.body):
            found.append(cur)
        prev, cur = cur, parents.get(cur)
    return found


def _enclosing_function(node, parents):
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur.name
        cur = parents.get(cur)
    return "<module>"


def _parent_map(tree):
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _module_name(path):
    rel = path.relative_to(LIBRARY_DIR).with_suffix("")
    parts = [p for p in rel.parts if p != "__init__"]
    return ".".join(["aura_life", *parts])


def _library_modules():
    return [
        p for p in sorted(LIBRARY_DIR.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


def _census(sources):
    """Split every ``from aura_life.hooks import <hook>`` site into guarded/unguarded.

    *sources* is an iterable of ``(module_name, source_text)``.

    Only names in :data:`HOOK_NAMES` are counted. That is what excludes
    ``aura_life/__init__.py``'s ``from aura_life.hooks import HookNotConfigured``:
    it imports the *exception type*, not a hook, so it is not a call site at all.
    Keying off HOOK_NAMES rather than off a filename means the exclusion stays
    correct as the registry changes — and it is why the raw walk finds fourteen
    sites while the census is thirteen.
    """
    unguarded, guarded = set(), set()
    for module, source in sources:
        tree = ast.parse(source)
        parents = _parent_map(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "aura_life.hooks":
                continue
            for alias in node.names:
                if alias.name not in HOOK_NAMES:
                    continue
                key = (module, _enclosing_function(node, parents), alias.name)
                if _guarding_tries(node, parents):
                    guarded.add(key)
                else:
                    unguarded.add(key)
    return unguarded, guarded


@lru_cache(maxsize=1)
def _library_census():
    """Cached: five tests share one walk over ~80 modules."""
    unguarded, guarded = _census(
        (_module_name(p), p.read_text(encoding="utf-8")) for p in _library_modules()
    )
    return frozenset(unguarded), frozenset(guarded)


# ----------------------------------------------------------------------
# Guard for the guard: the walk must actually be able to tell the two apart
# ----------------------------------------------------------------------

_DETECTOR_SAMPLE = '''
def unguarded():
    from aura_life.hooks import get_config
    return get_config()

def guarded():
    try:
        from aura_life.hooks import get_llm_service
        return get_llm_service()
    except ImportError:
        return None

def guarded_at_depth():
    try:
        if True:
            for _ in range(1):
                from aura_life.hooks import geocode
                return geocode("x")
    except Exception:
        return None

def guarded_only_in_the_handler():
    try:
        pass
    except Exception:
        from aura_life.hooks import get_image_service
        return get_image_service()

def not_a_hook():
    from aura_life.hooks import HookNotConfigured
    return HookNotConfigured
'''


def test_the_detector_distinguishes_guarded_from_unguarded():
    """Without this, the census could pass by finding nothing, or everything."""
    unguarded, guarded = _census([("sample", _DETECTOR_SAMPLE)])

    assert {name for _, _, name in unguarded} == {"get_config", "get_image_service"}, (
        "a bare import must count as unguarded, and one reached only from a Try's "
        "*handler* is not protected by that Try"
    )
    assert {name for _, _, name in guarded} == {"get_llm_service", "geocode"}, (
        "a Try at any ancestor depth must count as guarding"
    )
    # HookNotConfigured is an exception type, not a hook: it appears in neither set.
    assert "HookNotConfigured" not in {n for _, _, n in unguarded | guarded}


# ----------------------------------------------------------------------
# The census cannot rot into a vacuous pass
# ----------------------------------------------------------------------

def test_the_walk_actually_scanned_the_library():
    """A census over an empty file set would agree with an empty allowlist."""
    modules = _library_modules()
    assert len(modules) > 50, f"only {len(modules)} modules scanned — wrong directory?"
    assert (LIBRARY_DIR / "life_service.py").exists()

    unguarded, guarded = _library_census()
    assert unguarded, "the walk found no unguarded sites at all — it is not working"
    assert guarded, "the walk found no guarded sites at all — it is not working"
    assert len(UNGUARDED_CALL_SITES) == 13


# ----------------------------------------------------------------------
# The census itself
# ----------------------------------------------------------------------

def test_no_new_unguarded_hook_call_sites():
    """The authority for the count quoted in DEFERRED.md and README.md."""
    unguarded, _ = _library_census()

    added = sorted(unguarded - UNGUARDED_CALL_SITES)
    removed = sorted(UNGUARDED_CALL_SITES - unguarded)

    detail = ""
    if added:
        detail += "\nNEW unguarded hook call sites:\n" + "\n".join(
            f"  {m}.{fn}() -> {hook}()" for m, fn, hook in added
        )
    if removed:
        detail += "\nNo longer unguarded (allowlist is stale):\n" + "\n".join(
            f"  {m}.{fn}() -> {hook}()" for m, fn, hook in removed
        )
    assert unguarded == set(UNGUARDED_CALL_SITES), detail + "\n" + _FAILURE_HELP


def test_the_site_count_matches_the_documented_thirteen():
    """Pins the raw site count too, so two unguarded uses of one hook in one
    function cannot collapse into a single allowlist entry and hide a site."""
    sites = 0
    for path in _library_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "aura_life.hooks":
                parents = _parent_map(tree)
                if not _guarding_tries(node, parents):
                    sites += sum(1 for a in node.names if a.name in HOOK_NAMES)
    assert sites == 13, (
        f"the walk found {sites} unguarded hook call sites, not the 13 that "
        "DEFERRED.md and README.md document" + _FAILURE_HELP
    )


def _hooks_module_bindings(tree):
    """Every local name in *tree* bound to the ``aura_life.hooks`` module.

    Covers the four import forms that can produce an attribute-style hook call::

        from aura_life import hooks           -> {"hooks"}
        from aura_life import hooks as _x     -> {"_x"}
        import aura_life.hooks as h           -> {"h"}
        import aura_life.hooks                -> {"aura_life.hooks"}  (dotted access)

    Bounded on purpose: it resolves bindings from the module's own import
    statements only. It still cannot see a binding laundered through an
    assignment (``h = hooks``), a dynamic lookup (``getattr(hooks, name)()``), or
    ``importlib.import_module("aura_life.hooks")``. None of those are idioms this
    codebase uses; if one appears the census goes blind to it, and this comment is
    the record of that limit.
    """
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "aura_life":
            for alias in node.names:
                if alias.name == "hooks":
                    bound.add(alias.asname or "hooks")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "aura_life.hooks":
                    # `import a.b` binds `a`; the call then reads `a.b.hook()`.
                    bound.add(alias.asname or "aura_life.hooks")
    return bound


def _attribute_call_offenders(module, source):
    """Attribute-style hook calls in *source*, e.g. ``hooks.get_config()``.

    Returns ``(offenders, saw_binding)``. The second value lets a caller prove the
    scan actually looked at code that binds the hooks module, rather than at
    nothing.
    """
    tree = ast.parse(source)
    bound = _hooks_module_bindings(tree)
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in HOOK_NAMES:
            continue
        # Match against what this module actually bound, not the literal name
        # "hooks" -- an alias would otherwise slip straight past.
        base = ast.unparse(node.func.value)
        if base in bound:
            offenders.append(f"{module}:{node.lineno} {base}.{node.func.attr}()")
    return offenders, bool(bound)


def test_the_census_idiom_cannot_be_bypassed():
    """No module may call a hook by attribute (``hooks.get_config()``).

    The census only understands ``from aura_life.hooks import <hook>``. A module
    that did ``from aura_life import hooks`` -- or ``as _x`` -- and then called
    ``hooks.get_config()`` would be an unguarded call site the walk cannot see, so
    the idiom itself is pinned. ``aura_life.defaults`` and ``aura_life.hooks`` are
    exempt: they use the registry API (``configure`` / ``is_configured``), not the
    hooks.
    """
    modules = _library_modules()
    # Intrinsic non-emptiness guard. Without it a misconfigured LIBRARY_DIR makes
    # the loop below never run and `offenders == []` pass vacuously -- a false
    # clean on the very property this test is the authority for. Deliberately not
    # delegated to test_the_walk_actually_scanned_the_library: this test must hold
    # when run alone (`pytest -k idiom_cannot_be_bypassed`).
    assert len(modules) > 50, f"only {len(modules)} modules scanned -- wrong directory?"

    offenders = []
    scanned = 0
    for path in modules:
        module = _module_name(path)
        if module in _REGISTRY_MODULES:
            continue
        found, _ = _attribute_call_offenders(module, path.read_text(encoding="utf-8"))
        offenders.extend(found)
        scanned += 1

    assert scanned > 50, f"only {scanned} non-exempt modules scanned"
    assert offenders == [], (
        "hook called by attribute, which the census walk cannot see:\n  "
        + "\n  ".join(offenders)
        + "\nUse `from aura_life.hooks import <hook>` so this test can audit it."
    )


_IDIOM_SAMPLE = """
from aura_life import hooks
from aura_life import hooks as _aliased
import aura_life.hooks as _dotted_alias
import aura_life.hooks

def plain():
    return hooks.get_config()

def aliased():
    return _aliased.get_llm_service()

def dotted_alias():
    return _dotted_alias.geocode("x")

def fully_dotted():
    return aura_life.hooks.persona_now()

def registry_api_is_not_a_hook_call():
    hooks.configure(persona_now=None)
    return hooks.is_configured("persona_now")
"""


def test_the_idiom_guard_sees_through_aliases():
    """Guard for the guard: matching the literal name ``hooks`` is one rename away
    from blind, so the binding is resolved from the module's own imports."""
    offenders, saw_binding = _attribute_call_offenders("sample", _IDIOM_SAMPLE)

    assert saw_binding
    assert sorted(o.split()[-1] for o in offenders) == [
        "_aliased.get_llm_service()",
        "_dotted_alias.geocode()",
        "aura_life.hooks.persona_now()",
        "hooks.get_config()",
    ], offenders
    # configure/is_configured are registry API, not hooks -- never offenders.
    assert not any("configure" in o or "is_configured" in o for o in offenders)


def test_the_idiom_guard_cannot_report_clean_on_nothing():
    """A source with no hooks binding must not look like a scanned, clean module."""
    assert _attribute_call_offenders("sample", "x = 1") == ([], False)
    modules = _library_modules()
    assert len(modules) > 50, (
        f"only {len(modules)} modules enumerated -- the idiom scan would have "
        "reported clean by looking at nothing"
    )
