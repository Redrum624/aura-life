import json, os, pathlib, random
from aura_life.personas.genre_randomizer import build_genre_concept, build_blended_concept   # Task 3b rewrites

GOLDEN = pathlib.Path(__file__).parent / "fixtures" / "persona_parity_golden.json"

def _golden(got: dict) -> dict:
    """Load the golden for comparison — or fail loudly if it is missing.

    A MISSING GOLDEN IS A DEFECT, NOT A FRESH START. Task 3b moves this test and its fixture
    together; if only the test arrives, silently regenerating the golden would bless whatever
    the moved code now produces. Regeneration is opt-in only: set PARITY_WRITE_GOLDEN=1.
    Only the exact value "1" opts in -- PARITY_WRITE_GOLDEN=0 does not.
    """
    if not GOLDEN.exists():
        if os.environ.get("PARITY_WRITE_GOLDEN") != "1":
            raise AssertionError(
                f"Golden fixture is missing: {GOLDEN}\n"
                "This is a DEFECT, not a fresh start — the fixture is committed and should always be present.\n"
                "Restore it from git (git checkout -- tests/fixtures/persona_parity_golden.json).\n"
                "To regenerate it deliberately, re-run with PARITY_WRITE_GOLDEN=1."
            )
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(got, indent=2, sort_keys=True))
    return json.loads(GOLDEN.read_text())

def test_generated_concepts_match_golden():
    """rng is optional (falls back to the global `random` module at genre_randomizer.py:134/:165),
    so pass a real random.Random — never a falsy stub. Output is a plain dict, JSON-clean."""
    got = {
        "horror": build_genre_concept("horror", rng=random.Random(4242)),
        "romance": build_genre_concept("romance", rng=random.Random(99)),
        "blend": build_blended_concept(["horror", "romance"], rng=random.Random(7)),
    }
    assert got == _golden(got)
