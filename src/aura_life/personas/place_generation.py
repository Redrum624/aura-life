"""
place_generation.py — LLM-driven persona-place generators.

Phase 3 of the persona place-identity feature:
  - generate_cultural_stance: per-issue cultural stance coherent with persona traits.
  - generate_appearance: demographic-realistic physical appearance for a NEW
    randomized persona, grounded in her home region (T3.3).

⚠️  SAFETY (T3.3): appearance generation describes a CONCRETE INDIVIDUAL via
specific physical features only (hair, eyes, complexion-as-a-neutral-colour,
height, build, distinguishing features).  It NEVER uses racial categories, ethnic
labels, nationalities-as-appearance, or stereotypes.  The system prompt carries an
explicit guardrail (``_APPEARANCE_GUARDRAIL``) and the generator structurally drops
any non-physical key the LLM returns (so an "ethnicity"/"race" field can never be
emitted).  See ``_APPEARANCE_FIELDS``.
"""

import json
import logging
import random as _random
import re

logger = logging.getLogger(__name__)


# ============= Cultural stance generation =============

_CULTURAL_SYSTEM_PROMPT = (
    "You are a character development assistant. Respond with ONLY a valid JSON object — "
    "no prose, no markdown fences. Focus on cultural values and norms, not national "
    "stereotypes. Be respectful, nuanced, and individual in your characterization."
)

_EMPTY_RESULT: dict = {"cultural_stance": [], "cultural_summary": ""}


def _build_stance_prompt(definition, home: dict) -> str:
    """Build the user-side LLM prompt for cultural stance generation."""
    city = (home.get("city") or "").strip()
    country = (home.get("country") or "").strip()

    traits = getattr(definition, "core_traits", []) or []
    values = getattr(definition, "core_values", []) or []
    relationship = getattr(definition, "relationship_with_user", "") or ""
    struggles = getattr(definition, "struggles", []) or []
    defects = getattr(definition, "character_defects", []) or []
    behavioral = getattr(definition, "behavioral_tendencies", {}) or {}

    behavioral_str = ""
    if isinstance(behavioral, dict) and behavioral:
        behavioral_str = ", ".join(
            f"{k}: {v}" for k, v in list(behavioral.items())[:4]
        )

    return (
        f"Generate a cultural stance for a fictional character who lives in {city}, {country}.\n\n"
        f"Persona personality:\n"
        f"- Core traits: {', '.join(str(t) for t in traits[:5]) or 'none specified'}\n"
        f"- Core values: {', '.join(str(v) for v in values[:5]) or 'none specified'}\n"
        f"- Relationship with user: {relationship or 'none specified'}\n"
        f"- Struggles: {', '.join(str(s) for s in struggles[:3]) or 'none'}\n"
        f"- Character defects: {', '.join(str(d) for d in defects[:3]) or 'none'}\n"
        f"- Behavioral tendencies: {behavioral_str or 'none'}\n\n"
        f"Based on this personality, generate 3-5 cultural facets relevant to {city}, {country}. "
        f"A rebellious/high-shadow/nonconformist persona rejects more local norms; "
        f"a traditional/agreeable one embraces more; mixed per issue.\n\n"
        f"Facets to consider (pick what fits this place and person): "
        f"family expectations, religion/spirituality, work ethic, social norms, "
        f"food/arts, politics, gender roles.\n\n"
        f"Respond with exactly this JSON shape:\n"
        f'{{"cultural_stance": ['
        f'{{"facet": "example facet", "stance": "embrace|reject|conflicted", "note": "one sentence"}}'
        f'], "cultural_summary": "One natural sentence capturing her overall relationship to local culture."}}'
    )


def _parse_stance_json(text: str) -> dict:
    """Tolerantly parse cultural stance JSON from LLM output.

    Strips markdown fences, finds first {…} block, validates shape.
    On any error → empty result (never raises).
    """
    if not text:
        return _EMPTY_RESULT.copy()

    # Strip markdown fences
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)

    # Find first {…} (possibly multi-line)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return _EMPTY_RESULT.copy()

    try:
        obj = json.loads(m.group())
    except (json.JSONDecodeError, TypeError, ValueError):
        return _EMPTY_RESULT.copy()

    stance_list = obj.get("cultural_stance", [])
    summary = obj.get("cultural_summary", "")

    if not isinstance(stance_list, list):
        return _EMPTY_RESULT.copy()

    valid_stances = {"embrace", "reject", "conflicted"}
    cleaned = []
    for item in stance_list:
        if not isinstance(item, dict):
            continue
        facet = str(item.get("facet", "")).strip()
        stance = str(item.get("stance", "")).lower().strip()
        note = str(item.get("note", "")).strip()
        if facet and stance in valid_stances:
            cleaned.append({"facet": facet, "stance": stance, "note": note})

    return {
        "cultural_stance": cleaned,
        "cultural_summary": str(summary).strip() if summary else "",
    }


def generate_cultural_stance(definition, home: dict, *, llm=None) -> dict:
    """Generate a per-issue cultural stance coherent with the persona's personality.

    Args:
        definition: PersonalityDefinition (or duck-typed equivalent).
        home: dict with at least "city" and "country".
        llm: injectable LLM service (default: get_llm_service()). Mock in tests.

    Returns:
        {"cultural_stance": [{"facet": str, "stance": str, "note": str}, ...],
         "cultural_summary": str}
        On error / AI persona / missing home → {"cultural_stance": [], "cultural_summary": ""}.
    """
    # AI personas have no physical home → no cultural stance
    if getattr(definition, "persona_type", "human") == "ai":
        logger.debug("generate_cultural_stance: skipped for AI persona")
        return _EMPTY_RESULT.copy()

    city = (home.get("city") or "").strip()
    country = (home.get("country") or "").strip()
    if not city or not country:
        logger.debug("generate_cultural_stance: no city/country in home dict")
        return _EMPTY_RESULT.copy()

    user_prompt = _build_stance_prompt(definition, home)

    if llm is None:
        from aura_life.hooks import get_llm_service
        llm = get_llm_service()

    try:
        raw = llm.generate(
            user_prompt,
            system_prompt=_CULTURAL_SYSTEM_PROMPT,
            max_tokens=400,
        )
    except Exception as exc:
        logger.warning("generate_cultural_stance: LLM error: %s", exc)
        return _EMPTY_RESULT.copy()

    result = _parse_stance_json(raw)
    logger.info(
        "generate_cultural_stance: %d facets for %s, %s",
        len(result["cultural_stance"]), city, country,
    )
    return result


# ============= Appearance generation (T3.3) =============
#
# ⚠️  This is the SENSITIVE generator.  Read the SAFETY block at the top of the
# module.  Two layers protect against racial/ethnic profiling:
#   1. The system prompt carries an explicit guardrail forbidding racial
#      categories / ethnic labels / stereotypes (``_APPEARANCE_GUARDRAIL``).
#   2. The parser emits ONLY the physical-feature keys in ``_APPEARANCE_FIELDS``
#      (a subset of the [LOOKS:] whitelist that deliberately EXCLUDES the
#      "ethnicity" field) — any other key the LLM returns is dropped.

# The verbatim guardrail.  Exposed as a module constant so a test can assert it
# is present and so it can be embedded in both the system and user prompts.
_APPEARANCE_GUARDRAIL = (
    "Never use racial categories, ethnic labels, nationalities, or stereotypes. "
    "Describe ONE concrete fictional individual using specific physical features "
    "only: hair colour and style, eye colour, complexion as a neutral tonal word "
    "(for example fair, olive, deep brown — a colour, NOT a race), height and "
    "build, and any distinguishing features. Skin tone is a colour, never a race "
    "or ethnicity. Keep it tasteful, respectful, and individual — a single person, "
    "not a 'type'."
)

_APPEARANCE_SYSTEM_PROMPT = (
    "You are a character-design assistant describing one fictional person's "
    "physical appearance. Respond with ONLY a valid JSON object — no prose, no "
    "markdown fences. " + _APPEARANCE_GUARDRAIL
)

# Physical-feature fields this generator may emit.  This is a SUBSET of the
# prompt.looks_tags WHITELIST: it intentionally OMITS "ethnicity" (a racial
# category — forbidden by the safety rules), plus cosmetic/non-demographic fields
# (makeup, accessories, bust, base_prompt).  Every key here is also a real
# profile_core / appearance_details column, so it persists via
# ProfileDatabase.update_appearance.
_APPEARANCE_FIELDS: frozenset = frozenset({
    "hair_color",
    "hair_style",
    "hair_length",
    "eye_color",
    "skin_tone",
    "body_type",
    "distinguishing_features",
})

# Origin roll.  ~22% of new personas are an outlier (do NOT match the local
# default) — keeping appearance individual, never deterministic-by-region.
_LOCAL_ORIGIN = "local"
_OUTLIER_ORIGINS: tuple = ("adopted", "immigrant", "expat")
_OUTLIER_CHANCE = 0.22


def _empty_appearance_result() -> dict:
    """Return a FRESH empty appearance result.

    A function (not a shared ``_EMPTY.copy()`` constant) so callers never share
    the inner ``appearance`` dict — this avoids the T3.1 M3 shallow-copy hazard.
    """
    return {"appearance": {}, "appearance_origin": _LOCAL_ORIGIN, "origin_note": ""}


def _roll_appearance_origin(rng) -> str:
    """Roll the persona's appearance origin.

    ~``_OUTLIER_CHANCE`` of the time returns one of ``_OUTLIER_ORIGINS``
    (adopted / immigrant / expat); otherwise ``"local"``.  ``rng`` is injectable
    (seed/stub in tests) and must expose ``.random()`` and ``.choice(seq)``.
    """
    try:
        if rng.random() < _OUTLIER_CHANCE:
            return rng.choice(_OUTLIER_ORIGINS)
    except Exception:
        return _LOCAL_ORIGIN
    return _LOCAL_ORIGIN


def _build_appearance_prompt(definition, home: dict, origin: str) -> str:
    """Build the user-side LLM prompt for demographic appearance generation.

    Contains the home region, the persona's vibe, the rolled origin, and an
    embedded copy of the safety guardrail.
    """
    city = (home.get("city") or "").strip()
    country = (home.get("country") or "").strip()

    traits = getattr(definition, "core_traits", []) or []
    age_range = getattr(definition, "age_range", "") or ""
    vibe = ", ".join(str(t) for t in traits[:4]) or "no specific vibe"

    if origin == _LOCAL_ORIGIN:
        origin_clause = (
            f"This person GREW UP in {city}, {country}. Choose concrete individual "
            f"features that would be unremarkable and plausible for one real person "
            f"from there — without ever naming a race, ethnicity, or nationality."
        )
        note_clause = '"origin_note": ""'
    else:
        origin_clause = (
            f"This person currently lives in {city}, {country} but is an OUTLIER who "
            f"does NOT match the most common local look — her heritage is from "
            f"elsewhere ({origin}: e.g. adopted, an immigrant, or an expat). Choose "
            f"concrete individual features from a DIFFERENT background, plus a single "
            f"short, tasteful backstory hook explaining it — again WITHOUT naming any "
            f"race, ethnicity, or nationality."
        )
        note_clause = (
            '"origin_note": "one short sentence — a tasteful backstory hook for why '
            'her look differs from the local default (no race/ethnicity words)"'
        )

    fields_json = (
        '"hair_color": "...", "hair_style": "...", "hair_length": "...", '
        '"eye_color": "...", "skin_tone": "neutral colour word", '
        '"body_type": "height and build", '
        '"distinguishing_features": "freckles / scar / dimples / etc., or empty"'
    )

    return (
        f"Describe the physical appearance of one fictional adult woman "
        f"(vibe: {vibe}; age range: {age_range or 'adult'}).\n\n"
        f"{origin_clause}\n\n"
        f"SAFETY RULES: {_APPEARANCE_GUARDRAIL}\n\n"
        f"Respond with exactly this JSON shape:\n"
        f"{{{fields_json}, {note_clause}}}"
    )


def _parse_appearance_json(text: str) -> dict:
    """Tolerantly parse appearance JSON from LLM output.

    Strips markdown fences, finds the first {…} block, and emits ONLY the
    whitelisted physical-feature keys (``_APPEARANCE_FIELDS``) — any other key
    (ethnicity, race, nationality, name, age, …) is dropped.  On any error →
    fresh empty result (never raises, never a shared inner dict).
    """
    if not text:
        return _empty_appearance_result()

    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return _empty_appearance_result()

    try:
        obj = json.loads(m.group())
    except (json.JSONDecodeError, TypeError, ValueError):
        return _empty_appearance_result()

    if not isinstance(obj, dict):
        return _empty_appearance_result()

    appearance: dict = {}
    for key in _APPEARANCE_FIELDS:
        val = obj.get(key)
        if val is None:
            continue
        val = str(val).strip()
        if val:
            appearance[key] = val

    note = str(obj.get("origin_note", "") or "").strip()

    result = _empty_appearance_result()
    result["appearance"] = appearance
    result["origin_note"] = note
    return result


def generate_appearance(definition, home: dict, *, llm=None, rng=None) -> dict:
    """Generate demographic-realistic physical appearance for a NEW persona.

    Samples plausible INDIVIDUAL physical features for someone whose home is
    ``home`` — with a real outlier chance (adopted / immigrant / expat).  Emits
    ONLY whitelisted physical-feature fields; never a racial/ethnic category.

    Args:
        definition: PersonalityDefinition (or duck-typed equivalent).
        home: dict with at least "city" and "country".
        llm: injectable LLM service (default: get_llm_service()). Mock in tests.
        rng: injectable random source with .random()/.choice (seed/stub in tests).

    Returns:
        {"appearance": {<whitelisted physical fields>},
         "appearance_origin": "local|adopted|immigrant|expat",
         "origin_note": str}
        On error / AI persona / missing home → fresh empty result
        ({"appearance": {}, "appearance_origin": "local", "origin_note": ""}).
    """
    # AI personas have no physical body → no demographic appearance.
    if getattr(definition, "persona_type", "human") == "ai":
        logger.debug("generate_appearance: skipped for AI persona")
        return _empty_appearance_result()

    city = (home.get("city") or "").strip() if isinstance(home, dict) else ""
    country = (home.get("country") or "").strip() if isinstance(home, dict) else ""
    if not city or not country:
        logger.debug("generate_appearance: no city/country in home dict")
        return _empty_appearance_result()

    if rng is None:
        rng = _random.Random()

    origin = _roll_appearance_origin(rng)
    user_prompt = _build_appearance_prompt(definition, home, origin)

    if llm is None:
        from aura_life.hooks import get_llm_service
        llm = get_llm_service()

    try:
        raw = llm.generate(
            user_prompt,
            system_prompt=_APPEARANCE_SYSTEM_PROMPT,
            max_tokens=300,
        )
    except Exception as exc:
        logger.warning("generate_appearance: LLM error: %s", exc)
        return _empty_appearance_result()

    result = _parse_appearance_json(raw)
    result["appearance_origin"] = origin
    # A local persona carries no origin note even if the LLM volunteered one.
    if origin == _LOCAL_ORIGIN:
        result["origin_note"] = ""

    logger.info(
        "generate_appearance: %d features for %s, %s (origin=%s)",
        len(result["appearance"]), city, country, origin,
    )
    return result
