"""
Shared key vocabularies for the profile text format (spec §4.1).

One importable place for the three fixed tuples the profile format binds to,
so ``ProfileParser`` (parsing + ``ParsedProfile.validate()``), the persona
parameter derivation (``aura_life.personas.parameters``, spec §4.3) and any
external consumer agree on the exact same keys, spelling and order. Values are copied verbatim from the spec; do not reorder or
respell them without a spec change, since ``ParsedProfile.validate()``
reports any profile key outside these sets as an "unknown" warning.
"""

from typing import Tuple

# Keys accepted in the ``== STATE EXPRESSIONS ==`` section (one line each,
# ``key: free text``). A key outside this tuple is kept (never dropped) and
# reported by ``ParsedProfile.validate()``.
STATE_KEYS: Tuple[str, ...] = (
    "tired",
    "hungry",
    "lonely",
    "stressed",
    "low",
    "restless",
    "excited",
    "just_woke",
    "drinking",
    "hungover",
    "sick",
    "after_absence",
)

# Keys accepted in the ``== ENGINE SEEDS ==`` section's ``Traits:`` line
# (comma-separated ``key value`` pairs). Each value is 0..1. A key outside
# this tuple is kept (never dropped) and reported by
# ``ParsedProfile.validate()``; a value outside 0..1 or unparsable is
# dropped (never clamped) and reported the same way.
TRAIT_KEYS: Tuple[str, ...] = (
    "sociability",
    "volatility",
    "rumination",
    "impulsivity",
    "conscientiousness",
    "openness",
    "warmth",
    "weather_sensitivity",
)

# Optional ``[kind]`` tag accepted after a name in ``== SOCIAL CIRCLE ==``
# (e.g. ``- Shirley [threat]: ...``). Absent -> "friend" (spec §4.1). A kind
# outside this tuple is kept verbatim (never coerced to the default) and
# reported by ``ParsedProfile.validate()``.
NPC_KINDS: Tuple[str, ...] = (
    "friend",
    "family",
    "estranged",
    "threat",
    "colleague",
    "partner",
    "co_resident",
)

__all__ = ["STATE_KEYS", "TRAIT_KEYS", "NPC_KINDS"]
