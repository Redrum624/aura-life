"""Tests for the curated public facade: aura_life/__init__.py and aura_life/internals.py.

Also proves that aura_life.life_service's module-level absolute self-imports
(`from aura_life.conversation_session import ConversationSession`) do not
break under partial-initialization, regardless of which import order a
consumer uses. That must be demonstrated in a fresh interpreter (subprocess),
not assumed or inferred from other tests having already imported aura_life.
"""
import json
import pathlib
import subprocess
import sys

import aura_life

SNAPSHOT = pathlib.Path(__file__).parent / "api_surface.json"


def test_public_surface_is_stable():
    """Fails when __all__ changes. If intentional: delete the snapshot, re-run, explain in the commit."""
    got = sorted(aura_life.__all__)
    if not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps(got, indent=2))
    assert got == json.loads(SNAPSHOT.read_text())


def test_every_exported_name_actually_resolves():
    missing = [n for n in aura_life.__all__ if not hasattr(aura_life, n)]
    assert missing == [], f"__all__ lists names that do not exist: {missing}"


def test_surface_size_is_the_seeded_one():
    assert len(aura_life.__all__) == 116          # 114 from Aura's engine/__init__.py + hooks + HookNotConfigured


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
