"""Tests for the curated public facade: aura_life/__init__.py and aura_life/internals.py.

Also proves that aura_life.life_service's module-level absolute self-imports
(`from aura_life.conversation_session import ConversationSession`) do not
break under partial-initialization, regardless of which import order a
consumer uses. That must be demonstrated in a fresh interpreter (subprocess),
not assumed or inferred from other tests having already imported aura_life.

The last section pins a SECOND surface: aura_life.personas.genre_randomizer.
That module is not re-exported by the facade and so api_surface.json never
covered it -- yet it is imported directly by downstream consumers (Hollow's
hollow/sim/agents.py) and its names are documented in CHANGELOG.md as public.
An unpinned de-facto public surface is how a breaking change ships unnoticed.
"""
import json
import os
import pathlib
import subprocess
import sys

import aura_life

SNAPSHOT = pathlib.Path(__file__).parent / "api_surface.json"


def _snapshot(got, path: pathlib.Path = SNAPSHOT):
    """Load the snapshot for comparison — or fail loudly if it is missing.

    A MISSING SNAPSHOT IS A DEFECT, NOT A FRESH START. If it were regenerated
    silently (write-if-missing), a deleted, un-checked-out, or gitignored
    snapshot file would make this test pass green while blessing whatever
    __all__ currently is -- the public API could be re-baselined with zero
    signal. Regeneration is opt-in only: set API_SURFACE_WRITE_SNAPSHOT=1. Only the
    exact value "1" opts in -- API_SURFACE_WRITE_SNAPSHOT=0 does not.
    (Same convention as PARITY_WRITE_GOLDEN in tests/test_persona_parity.py.)
    """
    if not path.exists():
        if os.environ.get("API_SURFACE_WRITE_SNAPSHOT") != "1":
            raise AssertionError(
                f"API surface snapshot is missing: {path}\n"
                "This is a DEFECT, not a fresh start -- the snapshot is committed and should "
                "always be present.\n"
                f"Restore it from git (git checkout -- tests/{path.name}).\n"
                "To regenerate it deliberately, re-run with API_SURFACE_WRITE_SNAPSHOT=1."
            )
        path.write_text(json.dumps(got, indent=2))
    return json.loads(path.read_text())


def test_public_surface_is_stable():
    """Fails when __all__ changes. If intentional: delete the snapshot, re-run with
    API_SURFACE_WRITE_SNAPSHOT=1, explain in the commit."""
    got = sorted(aura_life.__all__)
    assert got == _snapshot(got)


def test_every_exported_name_actually_resolves():
    missing = [n for n in aura_life.__all__ if not hasattr(aura_life, n)]
    assert missing == [], f"__all__ lists names that do not exist: {missing}"


def test_surface_size_is_the_seeded_one():
    # 114 from the origin engine package's __init__.py + hooks + HookNotConfigured = 116 at extraction (0.1.0);
    # + clear_persona_schedule, the teardown for the schedule cache, added in 0.2.0 = 117.
    assert len(aura_life.__all__) == 117


def test_internals_exposes_life_service():
    from aura_life import internals
    assert hasattr(internals, "LifeService")


def _run_fresh(code: str) -> subprocess.CompletedProcess:
    """Run `code` in a brand-new interpreter subprocess so no other test's
    imports (or this test module's own `import aura_life` above) can mask a
    partial-initialization problem."""
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=pathlib.Path(__file__).resolve().parents[1] / "src",
        capture_output=True,
        text=True,
    )


def test_partial_init_import_order_package_first():
    """Entry order 1: `import aura_life` first, then touch aura_life.LifeService.

    This triggers aura_life/__init__.py, which does `from aura_life.life_service
    import LifeService`. life_service.py itself does
    `from aura_life.conversation_session import ConversationSession` at module
    level -- an absolute self-import re-entering the (still-executing) aura_life
    package. Must not raise.
    """
    result = _run_fresh(
        "import aura_life\n"
        "assert aura_life.LifeService is not None\n"
        "print('OK', aura_life.LifeService)\n"
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_partial_init_import_order_submodule_first():
    """Entry order 2: `import aura_life.life_service` first (which also
    triggers the parent package's __init__.py before the submodule import
    completes), then `import aura_life`. Must not raise.
    """
    result = _run_fresh(
        "import aura_life.life_service\n"
        "import aura_life\n"
        "assert aura_life.life_service.LifeService is not None\n"
        "assert aura_life.LifeService is aura_life.life_service.LifeService\n"
        "print('OK', aura_life.LifeService)\n"
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# Second pinned surface: aura_life.personas.genre_randomizer
# ---------------------------------------------------------------------------

GENRE_SNAPSHOT = pathlib.Path(__file__).parent / "genre_randomizer_surface.json"


def _param_spec(fn) -> list:
    """Parameter names, with `name=<default repr>` where a default exists.

    Deliberately NOT str(inspect.signature(fn)): the module uses
    `from __future__ import annotations`, so signature rendering quotes the
    annotations and the exact text drifts between Python versions. Parameter
    names and defaults are the part callers actually bind against.
    """
    import inspect
    prefix = {inspect.Parameter.VAR_POSITIONAL: "*", inspect.Parameter.VAR_KEYWORD: "**"}
    out = []
    for p in inspect.signature(fn).parameters.values():
        name = prefix.get(p.kind, "") + p.name
        out.append(name if p.default is inspect.Parameter.empty else f"{name}={p.default!r}")
    return out


def _genre_surface() -> dict:
    from aura_life.personas import genre_randomizer as gr
    return {
        "module": "aura_life.personas.genre_randomizer",
        "public_names": sorted(n for n in dir(gr) if not n.startswith("_")),
        "signatures": {
            name: _param_spec(getattr(gr, name))
            for name in ("build_genre_concept", "build_blended_concept",
                         "select_blend_genres", "render")
        },
        "GENDERS": list(gr.GENDERS),
        "PRONOUNS_keys": {g: sorted(gr.PRONOUNS[g]) for g in gr.GENDERS},
        "GenreSpec_fields": sorted(gr.GenreSpec.__dataclass_fields__),
        "GENRE_REGISTRY_keys": sorted(gr.GENRE_REGISTRY),
    }


def test_genre_randomizer_surface_is_stable():
    """Fails when the genre_randomizer surface changes.

    A change here is not automatically wrong -- but it must be deliberate:
    regenerate with API_SURFACE_WRITE_SNAPSHOT=1 and say what moved in the
    CHANGELOG. Removing a name from `public_names`, a field from
    `GenreSpec_fields`, or a leading parameter from `signatures` is a BREAKING
    change and needs a major/minor bump, not a patch.
    """
    got = _genre_surface()
    assert got == _snapshot(got, GENRE_SNAPSHOT)


def test_genre_randomizer_surface_is_additive_over_v0_2_0():
    """The 0.2.0 surface, written out explicitly, must still be a subset.

    This is the anti-regression half: the snapshot above would happily bless a
    removal once someone regenerates it. These literals are what shipped in the
    v0.2.0 tag and may never shrink without a deliberate breaking release.
    """
    got = _genre_surface()
    v0_2_0_names = {
        "Archetype", "GENRE_REGISTRY", "GenreSpec", "SHADOW_SCALE", "ShadowSeedSpec",
        "build_blended_concept", "build_genre_concept", "select_blend_genres",
    }
    missing = sorted(v0_2_0_names - set(got["public_names"]))
    assert missing == [], f"public names removed since v0.2.0: {missing}"

    v0_2_0_fields = {
        "ai_archetypes", "appearance_template", "builder", "core_descriptors",
        "core_values_pool", "display_label", "goal_pool", "human_archetypes",
        "intensity_ladder", "interests_pool", "key", "name_pool", "relationship_style",
        "shadow", "shadow_level", "style_theme_pool", "theme_colors", "tone_directive",
        "voice_style", "weight_by_pool_size",
    }
    gone = sorted(v0_2_0_fields - set(got["GenreSpec_fields"]))
    assert gone == [], f"GenreSpec fields removed since v0.2.0: {gone}"

    # Leading parameters are positional for existing callers; they may only be
    # appended to.  v0.2.0 shipped build_genre_concept(genre, rng=None) and
    # build_blended_concept(genres, rng=None).
    assert got["signatures"]["build_genre_concept"][:2] == ["genre", "rng=None"]
    assert got["signatures"]["build_blended_concept"][:2] == ["genres", "rng=None"]
