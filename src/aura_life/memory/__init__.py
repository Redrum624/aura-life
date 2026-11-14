"""The memory stream (humanness program Task 12, spec section 4.6): the
episodes of a persona's life, recalled by recency, importance, relevance and
mood congruence, with a strength that fades and grows with recall, kept in her
``life.db``.

:class:`Episode` and its numbers are in :mod:`aura_life.memory.episodes`;
:class:`MemoryStream` -- recording, recall, retention and persistence -- in
:mod:`aura_life.memory.store`. ``LifeService`` records her episodes and
answers ``recall(query=None, k=3)``.

Task 13 (spec section 4.6) adds reflection -- what she concludes about her
own recent history, deterministically, from the window of episodes since her
last one (:mod:`aura_life.memory.reflection`) -- recorded as episodes of her
own, tagged ``"belief"``.
"""

from .episodes import (
    CONTACT_PHRASES,
    EMOTION_WEIGHT,
    IMPORTANCE_FLOOR,
    INITIAL_STRENGTH,
    NOVELTY_WEIGHT,
    NOVELTY_WINDOW_DAYS,
    PEOPLE_WEIGHT,
    PLACE_PHRASES,
    RECALL_STRENGTH_GAIN,
    RECENCY_PER_HOUR,
    Episode,
    contact_phrase,
    dominant_emotion,
    emotion_intensity,
    importance_of,
    mean_valence,
    place_phrase,
)
from .reflection import (
    BELIEF_INTENSITY,
    BELIEF_KEY_TAG_PREFIX,
    BELIEF_REPEAT_COOLDOWN_DAYS,
    LLM_BELIEF_MAX_CHARS,
    MAX_BELIEFS_PER_REFLECTION,
    MIN_MOOD_SAMPLE,
    MIN_REPEAT_COUNT,
    REFLECTION_THRESHOLD,
    BeliefKey,
    belief_key_from_tag,
    belief_key_tag,
    generate_beliefs,
    mood_trend,
    recurring_places,
    repeated_activity_partners,
    validate_llm_belief,
)
from .store import EPISODE_CAP, MemoryStream

__all__ = [
    "BELIEF_INTENSITY",
    "BELIEF_KEY_TAG_PREFIX",
    "BELIEF_REPEAT_COOLDOWN_DAYS",
    "BeliefKey",
    "CONTACT_PHRASES",
    "EMOTION_WEIGHT",
    "EPISODE_CAP",
    "Episode",
    "IMPORTANCE_FLOOR",
    "INITIAL_STRENGTH",
    "LLM_BELIEF_MAX_CHARS",
    "MAX_BELIEFS_PER_REFLECTION",
    "MIN_MOOD_SAMPLE",
    "MIN_REPEAT_COUNT",
    "MemoryStream",
    "NOVELTY_WEIGHT",
    "NOVELTY_WINDOW_DAYS",
    "PEOPLE_WEIGHT",
    "PLACE_PHRASES",
    "RECALL_STRENGTH_GAIN",
    "RECENCY_PER_HOUR",
    "REFLECTION_THRESHOLD",
    "belief_key_from_tag",
    "belief_key_tag",
    "contact_phrase",
    "dominant_emotion",
    "emotion_intensity",
    "generate_beliefs",
    "importance_of",
    "mean_valence",
    "mood_trend",
    "place_phrase",
    "recurring_places",
    "repeated_activity_partners",
    "validate_llm_belief",
]
