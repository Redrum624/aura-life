"""The moment (humanness Task 18, spec section 4.10): what is true of her now,
in a few plain lines a host puts near the end of its prompt, rebuilt every
turn.

:meth:`aura_life.life_service.LifeService.get_moment` builds a :class:`Moment`
from the engines' live state -- deterministic, no LLM (spec R4):

- ``situation``: where she is, what she is doing, the time of day and the
  weather, in one or two sentences.
- ``undercurrent``: the state that drives her most now and at most one more
  (sleep pressure and energy, mood, hunger, illness, drink, stressors, the
  user's absence, her shadow), each framed by a short plain lead and said
  through her own ``state_expressions`` -- or, for a persona without them,
  :data:`NEUTRAL_EXPRESSIONS` (ruling T18-R4).
- ``on_mind``: at most two cues -- an episode of her memory stream, a
  rumination, a goal, a curiosity or something put off, a stressor, her next
  plan slot -- ranked by salience x novelty x (1 + relevance to what the user
  just said). Within one conversation (moments less than
  ``CONVERSATION_ACTIVITY_WINDOW_MINUTES`` apart) a thought comes to her mind
  once: what was rendered, or anything about the same thing, is passed over
  unless the user's own words name it (Task 38), so her mind can be empty.
- ``to_share``: at most one unshared item with its stable id
  (:class:`Share`); the host calls ``mark_shared(id)`` once she told it. What
  she told, and news made later in the very same words, is not offered again.
- ``speech``: two to four constraints on the reply -- its length (also as
  data, :class:`LengthTarget`, ruling T18-R1), one question at most, no naming
  of feelings or of these notes, and how much she discloses at her depth with
  the user (``expression_system.DISTANCE_LINES``, ruling T18-R5).
- ``unspoken``: at most one line of what she keeps to herself.

:meth:`Moment.render` is at most :data:`MAX_RENDER_CHARS` characters, in the
second person, with no digit, no snake_case, no engine label and never "the
user" (spec section 4.10).

Novelty: a cue that is rendered loses :data:`NOVELTY_LOSS_PER_RENDER` of its
novelty and wins it back at :data:`NOVELTY_RECOVERY_PER_HOUR` on the world
clock (ruling T18-R6); the service saves it (table ``life_moment_state``).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Mapping, NamedTuple, Optional, Tuple

from ..memory.episodes import _ONES, _number_words, _spelled
from ..personas.keys import STATE_KEYS

logger = logging.getLogger(__name__)

# ============= Limits (spec section 4.10) =============

#: The most characters :meth:`Moment.render` returns (spec section 4.10).
MAX_RENDER_CHARS = 1000
#: The most cues ``on_mind`` holds (spec section 4.10: "<= 2").
MAX_ON_MIND = 2

# ============= Chosen, not derived (ruling T18-R6; the report lists each) =============

#: How much novelty a cue loses each time it is rendered (0..1). Chosen, not
#: derived: half, so a cue that wins two turns running is spent and others
#: come forward.
NOVELTY_LOSS_PER_RENDER = 0.5
#: How much novelty a rendered cue wins back per world hour. Chosen, not
#: derived: a day from spent to fresh (twelve hours after one render). The
#: spec section 6 row it bears on -- fewer than a fifth of the rendered lines
#: in six or more of twelve captures -- is measured per test persona in
#: ``tests/test_moment.py`` and in the Task 18 report.
NOVELTY_RECOVERY_PER_HOUR = 1.0 / 24.0
#: How long after waking she has "only just woken up", in hours. Chosen, not
#: derived: no window exists in the library (``consume_just_woke`` is a latch
#: the moment may not read, ruling T18-R2).
JUST_WOKE_HOURS = 1.0
#: The salience of her next plan slot as a cue (0..1). Chosen, not derived:
#: a slot carries no weight of its own.
PLAN_SLOT_SALIENCE = 0.5


class LengthTarget(NamedTuple):
    """The reply's length, in sentences (ruling T18-R1): what a host sets its
    token cap from; the ``speech`` line says the same in words."""
    min_sentences: int
    max_sentences: int

    def words(self) -> str:
        """The target as the ``speech`` line says it: "Keep it to two or three
        sentences." -- no digit."""
        lo, hi = self.min_sentences, self.max_sentences
        if hi <= 1:
            return "Keep it to one sentence."
        if hi == lo:
            return f"Keep it to {_number_words(hi)} sentences."
        joint = "or" if hi == lo + 1 else "to"
        return f"Keep it to {_number_words(lo)} {joint} {_number_words(hi)} sentences."

    def shortened(self) -> "LengthTarget":
        """One sentence less at each end, never under one (tired or low)."""
        return LengthTarget(max(1, self.min_sentences - 1), max(1, self.max_sentences - 1))


#: The length target when her ``communication_traits`` name none (the Task 18
#: brief: "two or three sentences").
DEFAULT_LENGTH = LengthTarget(2, 3)

#: The rule on questions (the Task 18 brief: "at most one question").
ONE_QUESTION = "Ask at most one question."
#: The rule on naming (the Task 18 brief: "don't name your feelings or these
#: notes").
DONT_NAME = "Don't name your feelings or these notes."


@dataclass(frozen=True)
class Share:
    """One unshared thing she could tell (spec section 4.9): its stable id
    (``"share:<n>"`` or ``"event:<n>"``, for ``mark_shared``) and what it is,
    told to her in the second person."""
    id: str
    text: str


@dataclass(frozen=True)
class Moment:
    """Her moment (spec section 4.10). Build it with
    ``LifeService.get_moment``; put :meth:`render` in the prompt."""
    situation: str
    undercurrent: str
    on_mind: Tuple[str, ...] = ()
    to_share: Optional[Share] = None
    speech: Tuple[str, ...] = ()
    unspoken: Tuple[str, ...] = ()
    length: LengthTarget = DEFAULT_LENGTH

    def lines(self) -> List[str]:
        """The rendered lines, in order: situation, undercurrent, what is on
        her mind, what she could share, how she speaks (one line), what she
        keeps to herself. Empty parts are left out."""
        out = [self.situation, self.undercurrent, *self.on_mind]
        if self.to_share is not None and self.to_share.text:
            out.append(f"Something you haven't shared yet: {self.to_share.text}")
        out.append(" ".join(part for part in self.speech if part))
        out.extend(self.unspoken)
        return [line for line in (" ".join(str(part or "").split()) for part in out) if line]

    def render(self) -> str:
        """The moment as text for her prompt: second person, no digit, at
        most :data:`MAX_RENDER_CHARS` characters (spec section 4.10; the
        builder fits its parts, so the cut here is only a guard)."""
        text = _spelled("\n".join(self.lines()))
        if len(text) <= MAX_RENDER_CHARS:
            return text
        cut = text[:MAX_RENDER_CHARS].rsplit(None, 1)[0]
        return cut.rstrip(" ,;:—")


# ============= The neutral table (ruling T18-R4) =============

#: Her state said for a persona whose profile has no ``state_expressions``:
#: one entry per ``STATE_KEYS`` key, written like an authored profile's
#: (lowercase fragments, addressed to her, no pronoun of hers). Design
#: values: no table existed in the library.
NEUTRAL_EXPRESSIONS: Dict[str, str] = {
    "tired": "keep it short; let a pause be a pause",
    "hungry": "a little distracted; food keeps coming to mind",
    "lonely": "glad of the company; lean into the talk",
    "stressed": "less patience than usual; get to the point",
    "low": "quieter than usual; no forced cheer",
    "restless": "hard to stay on one thing; let the talk wander",
    "excited": "quicker and warmer than usual; let it show",
    "just_woke": "slow to get going; the day hasn't started yet",
    "drinking": "looser and more open than usual",
    "hungover": "slow and fragile; keep things simple",
    "sick": "low on energy; keep things simple",
    "after_absence": "notice the gap without making a scene of it",
}

#: The ``STATE_KEYS`` an AI persona can reach: she has no body, so no hunger,
#: drink, hangover, illness or waking (``LifeService.is_asleep`` is always
#: False for her).
AI_STATE_KEYS: Tuple[str, ...] = ("tired", "lonely", "stressed", "low", "restless", "excited", "after_absence")

#: A mood label (``affect.MOOD_LABELS``) and the state key it is said
#: through; content, calm and neutral have none (their own line is enough).
MOOD_STATE_KEYS: Dict[str, str] = {
    "happy": "excited", "restless": "restless", "irritable": "stressed",
    "anxious": "stressed", "low": "low", "flat": "low",
}

#: The plain lead naming a state (ruling T18-R4: everyday words, never the
#: key); a mood's lead is its ``AffectSystem.MOOD_DESCRIPTIONS`` line, a
#: hunger's or an illness's the engine's own words.
LEADS: Dict[str, str] = {
    "tired": "You're tired",
    "exhausted": "You're exhausted",
    "lonely": "You're lonely",
    "stressed": "You're stressed",
    "just_woke": "You've only just woken up",
    "drinking": "You've been drinking",
    "hungover": "You're hungover",
    "on_edge": "Something has you on edge",
    "heavy": "Something you did sits heavy with you",
    "away": "It's been a long while since you heard from {user}",
    "back": "You're talking with {user} again after a long while",
}


class Candidate(NamedTuple):
    """A state that may drive the undercurrent: its ``STATE_KEYS`` key (or
    ``None``, said by its lead alone), how strongly it holds (0..1), its
    lead, and words that tie it to what the user says (relevance)."""
    key: Optional[str]
    salience: float
    lead: str
    words: str = ""


class Cue(NamedTuple):
    """Something that may be on her mind: a key for its novelty, how salient
    it is (0..1), its line, the episode it is (for reinforcement), and what
    it is about, which the user's words are weighed against and one
    conversation knows a thought by (Task 38): the line without its lead
    ("You've been working on"); for a memory, what happened, where and with
    whom."""
    key: str
    salience: float
    text: str
    episode: object = None
    about: str = ""


def _about(cue: Cue) -> str:
    """The key of what a cue is about, for one conversation: two memories
    told in the same words, or one topic through two sources (a rumination
    and the stressor it comes from), are one thought."""
    return "about:" + " ".join((cue.about or cue.text).lower().split())


def _named(user_text: Optional[str], cue: Cue) -> bool:
    """Whether the user's own words name what a cue is about: a word that
    says something, shared by stem (``activities.choice.terms``, the words
    keyword relevance is made of). Judged on the words themselves, whatever
    a host's ``embed`` hook would answer: a cosine is seldom zero."""
    from aura_life.activities.choice import terms

    return bool(user_text) and bool(terms(user_text) & terms(cue.about or cue.text))


def expression_for(key: str, expressions: Mapping[str, str], *, is_ai: bool = False) -> str:
    """How she is in state ``key``: her own expression when her profile has
    it, else the neutral one -- none for a key an AI cannot reach."""
    own = " ".join(str((expressions or {}).get(key) or "").split())
    if own:
        return own
    if is_ai and key not in AI_STATE_KEYS:
        return ""
    return NEUTRAL_EXPRESSIONS.get(key, "")


def state_line(candidate: Candidate, expressions: Mapping[str, str], *, is_ai: bool = False) -> str:
    """The undercurrent's line for ``candidate``: its lead, then her
    expression of the state as written (ruling T18-R4), as one sentence."""
    lead = candidate.lead.rstrip(" .")
    fragment = expression_for(candidate.key, expressions, is_ai=is_ai) if candidate.key else ""
    line = f"{lead} — {fragment}" if fragment else lead
    return line if line[-1:] in ".!?" else line + "."


# ============= The length target from her traits (ruling T18-R1) =============

_COUNT = r"(\d+|a single|" + "|".join(_ONES[1:11]) + r")"
_SENTENCES_RE = re.compile(_COUNT + r"(?:\s+(?:or|to)\s+" + _COUNT + r")?\s+sentences?\b", re.IGNORECASE)


def _count(word: str) -> int:
    word = word.lower()
    if word.isdigit():
        return int(word)
    return 1 if word == "a single" else _ONES.index(word)


def length_target(traits: Iterable[str]) -> LengthTarget:
    """The reply's length her ``communication_traits`` give -- the first one
    that names a number of sentences ("one or two sentences", "a single
    sentence") -- else :data:`DEFAULT_LENGTH`."""
    for trait in traits or ():
        match = _SENTENCES_RE.search(str(trait or ""))
        if match:
            lo = _count(match.group(1))
            hi = _count(match.group(2)) if match.group(2) else lo
            lo, hi = sorted((max(1, lo), max(1, hi)))
            return LengthTarget(lo, hi)
    return DEFAULT_LENGTH


# ============= Novelty (ruling T18-R6) =============

def _penalty_now(entry, now: datetime) -> float:
    penalty, at = entry
    hours = max(0.0, (now - at).total_seconds() / 3600.0)
    return max(0.0, float(penalty) - hours * NOVELTY_RECOVERY_PER_HOUR)


def novelty(store: Mapping[str, tuple], key: str, now: datetime) -> float:
    """How fresh cue ``key`` is at ``now``, 0..1: one never rendered, or
    rendered long enough ago, is 1."""
    entry = store.get(key)
    return 1.0 if entry is None else 1.0 - _penalty_now(entry, now)


def after_rendering(store: Mapping[str, tuple], keys: Iterable[str], now: datetime) -> Dict[str, tuple]:
    """``store`` once the cues ``keys`` were rendered at ``now``: each loses
    :data:`NOVELTY_LOSS_PER_RENDER`; an entry fresh again is dropped, so the
    store holds only what is still recovering."""
    kept = {key: (_penalty_now(entry, now), now) for key, entry in store.items()}
    for key in keys:
        penalty = kept.get(key, (0.0, now))[0]
        kept[key] = (min(1.0, penalty + NOVELTY_LOSS_PER_RENDER), now)
    return {key: entry for key, entry in kept.items() if entry[0] > 0.0}


# ============= Words =============

def sentence(text: str) -> str:
    """``text`` as one sentence: single spaces, numbers in words, no
    underscore or brace, a closing stop."""
    text = " ".join(_spelled(str(text or "")).replace("_", " ").replace("{", "").replace("}", "").split())
    if not text:
        return ""
    text = text[:1].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def fitted(moment: Moment) -> Moment:
    """``moment`` with parts left out, least needed first, until its render
    fits :data:`MAX_RENDER_CHARS`: what she keeps to herself, the second
    cue, the undercurrent's second state, what she could share, the first
    cue, the disclosure line."""
    from dataclasses import replace

    def fits(m: Moment) -> bool:
        return len(_spelled("\n".join(m.lines()))) <= MAX_RENDER_CHARS

    steps = (
        lambda m: replace(m, unspoken=()),
        lambda m: replace(m, on_mind=m.on_mind[:1]),
        lambda m: replace(m, undercurrent=_first_sentence_of(m.undercurrent)),
        lambda m: replace(m, to_share=None),
        lambda m: replace(m, on_mind=()),
        lambda m: replace(m, speech=m.speech[:3]),
    )
    for step in steps:
        if fits(moment):
            break
        moment = step(moment)
    return moment


#: The undercurrent's two states are joined by this.
_STATE_JOIN = "  "


def _first_sentence_of(undercurrent: str) -> str:
    return undercurrent.split(_STATE_JOIN, 1)[0]


# ============= The builder (LifeService.get_moment) =============

def _guarded(what: str, read, default):
    """``read()``, or ``default`` when an engine cannot answer (said at
    DEBUG): one engine's failure leaves the rest of the moment."""
    try:
        return read()
    except Exception:
        logger.debug("The moment could not read %s", what, exc_info=True)
        return default


def _say(service, text: str) -> str:
    """``text`` addressed to her (``LifeService._addressed_to_her``: every
    token of an event, an episode, a plan slot or her profile rendered,
    ruling T18-R7); a text the renderer cannot read (a stray brace) as it
    is, its braces then dropped by :func:`sentence`."""
    try:
        return service._addressed_to_her(text)
    except (ValueError, IndexError, KeyError, AttributeError):
        return text


def _addressed(text: str) -> bool:
    """Is ``text`` said to her -- no bare third-person pronoun in it (the
    Task 6 second-person lint's rule; the pattern is the one
    ``memory.reflection`` rejects an LLM belief by)? A profile's struggle is
    written about her ("the friend she let down"), so a cue made of one is
    not (fix round 1, C2)."""
    from aura_life.memory.reflection import _BARE_PRONOUN_RE
    return not _BARE_PRONOUN_RE.search(text or "")


def _ranked(items: List, scores: List[float]) -> List:
    """``items`` by score, best first; ties keep their order."""
    order = sorted(range(len(items)), key=lambda i: -scores[i])
    return [items[i] for i in order]


def _situation(service) -> str:
    """Where she is and what she is doing, then the time of day and the
    weather: "You're reading at home. It's a rainy evening." """
    from aura_life.life_service import _doing
    from aura_life.memory.episodes import place_phrase

    # Her place as get_current_location says it, without moving her there
    # (ruling T18-R2; fix round 1, C1).
    location = _guarded("the location", service._location_now, "")
    where = place_phrase(location)
    if _guarded("the sleep", service.is_asleep, False):
        doing = f"You're asleep {where}".strip()
    else:
        activity = _guarded("the activity", lambda: service.current_activity_name, "")
        activity = service._activity_for_display(activity) if activity else ""
        doing = _doing(activity, location) if activity else f"You're {where}".strip()
    weather = _guarded("the weather", lambda: service._world.weather.value, "")
    phase = _guarded("the time of day", lambda: service._persona_time_of_day.value, "")
    # sentence() says an underscore as a space ("clear_night", "late_night").
    if weather.endswith("night") or weather == "starry":
        when = f"It's a {weather if weather.endswith('night') else weather + ' night'}"
    elif weather and phase:
        when = f"It's a {weather} {phase}"
    else:
        when = f"It's {phase}" if phase else ""
    return " ".join(part for part in (sentence(_say(service, doing)), sentence(when)) if part)


#: The key under which the moment notes, for one conversation, that it told
#: her how to meet the user's return.
ABSENCE_KEY = "state:after_absence"


def _conversation(service, now: datetime) -> set:
    """The keys the moment has rendered in this conversation (Task 38): the
    thoughts it put on her mind, the memory it offered her to share, the
    line on the user's return. A host asks for her moment at every turn,
    minutes apart; a thought is not brought to her mind twice in one
    conversation unless the user's words touch it, and she is told once how
    to meet the user's return. A conversation is what the library already
    means by one: moments less than ``CONVERSATION_ACTIVITY_WINDOW_MINUTES``
    apart. Kept in memory only: a restart starts a new conversation."""
    from aura_life.life_service import CONVERSATION_ACTIVITY_WINDOW_MINUTES

    last, keys = getattr(service, "_moment_conversation", None) or (None, set())
    if last is None or not timedelta(0) <= now - last <= timedelta(minutes=CONVERSATION_ACTIVITY_WINDOW_MINUTES):
        keys = set()
    service._moment_conversation = (now, keys)
    return keys


def _candidates(service, said: frozenset = frozenset()) -> Tuple[List[Candidate], bool]:
    """The states that may drive her undercurrent now, and whether she is
    tired or low (the length target is shortened then). ``said``: what the
    moment already rendered in this conversation (:func:`_conversation`)."""
    from aura_life.affect.affect_system import AffectSystem
    from aura_life.models import EnergyLevel

    is_ai = bool(getattr(service, "_is_ai", False))
    found: List[Candidate] = []
    shorter = False

    energy = service._energy
    level = _guarded("the energy level", lambda: energy.energy_level, None)
    effective = _guarded("the energy", lambda: float(energy.effective_level), 1.0)
    pressure = 0.0 if is_ai else _guarded("the sleep pressure", lambda: float(energy.sleep_pressure), 0.0)
    asleep = _guarded("the sleep", service.is_asleep, False)
    if level in (EnergyLevel.EXHAUSTED, EnergyLevel.TIRED) or _guarded("the rest", energy.should_rest, False):
        lead = LEADS["exhausted"] if level == EnergyLevel.EXHAUSTED else LEADS["tired"]
        found.append(Candidate("tired", max(1.0 - effective, pressure), lead, "tired sleepy"))
        shorter = True

    # What her shadow's unease rises with -- her loneliness, her stress, a
    # mood under neutral (ShadowSystem.tick's unease target): once one of
    # them is a candidate it says the unease too (see the shadow, below).
    cause_said = False
    mood = _guarded("the mood", lambda: service._affect.mood, None)
    if mood is not None and mood.current_mood != "neutral" and mood.intensity >= 0.1:
        line = AffectSystem.MOOD_DESCRIPTIONS.get(mood.current_mood, "")
        if line:
            found.append(Candidate(MOOD_STATE_KEYS.get(mood.current_mood), float(mood.intensity), line))
            shorter = shorter or mood.current_mood in ("low", "flat")
            cause_said = cause_said or float(mood.valence) < 0.0

    loneliness = _guarded("the loneliness", lambda: float(service._affect.loneliness.level), 0.0)
    if loneliness >= 0.2:  # AffectSystem.get_loneliness_description's first line
        found.append(Candidate("lonely", loneliness, LEADS["lonely"], "lonely alone"))
        cause_said = True
    stress = _guarded("the stress", lambda: float(service._affect.stress.level), 0.0)
    if stress >= 0.2:  # AffectSystem.get_stress_description's first line
        found.append(Candidate("stressed", stress, LEADS["stressed"], "stressed"))
        cause_said = True

    absence = _guarded("the absence", lambda: service.after_absence, None)
    # On the user's return she is told once in a conversation how to meet it
    # (the note is taken for the return only: while the user is away the
    # line is true each time).
    if absence is not None and absence.intensity > 0.0 and ABSENCE_KEY not in said:
        lead = (LEADS["away"] if absence.ongoing else LEADS["back"]).format(user=service._user_ref())
        found.append(Candidate("after_absence", float(absence.intensity), lead))

    # Her shadow: unease and lost felt safety are "on edge" only when none of
    # their causes is said above -- beside "You're lonely" they were one
    # cause told as two states, in every moment of a persona nobody spoke to
    # (review of Task 36). They are said when the causes are each under
    # their own bar and add up, and when they outlive their cause. Her
    # self-doubt follows her mood and this unease; it is not said as edge.
    shadow = _guarded("the shadow", lambda: service._shadow.export_state(), {}) or {}
    edge = max((float(shadow.get(k) or 0.0) for k in ("felt_unsafe", "unease")), default=0.0)
    if edge > 0.0 and not cause_said:
        found.append(Candidate("stressed", edge, LEADS["on_edge"]))
    heavy = max((float(shadow.get(k) or 0.0) for k in ("guilt", "shame", "remorse")), default=0.0)
    if heavy > 0.0:
        found.append(Candidate("low", heavy, LEADS["heavy"]))

    if not is_ai:
        hunger = _guarded("the hunger", lambda: float(service._basic_needs.hunger), 0.0)
        label = _guarded("the hunger", service._sustenance.hunger_label, "satisfied")
        if label != "satisfied":
            meals = " ".join(sorted(_guarded("the meals", lambda: service._setting.names_tagged("meal"), ())))
            found.append(Candidate("hungry", hunger, f"You're {label}",
                                   f"hungry starving pretty hungry peckish meal {meals}"))
        awake = _guarded("the hours awake", lambda: float(energy.hours_awake), JUST_WOKE_HOURS)
        if not asleep and awake < JUST_WOKE_HOURS:
            found.append(Candidate("just_woke", 1.0 - awake / JUST_WOKE_HOURS, LEADS["just_woke"], "woke morning"))
        drink = _guarded("the drinking", service._body.get_inebriation_effects, {}) or {}
        if drink.get("is_inebriated"):
            found.append(Candidate("drinking", float(drink.get("level") or 0.0), LEADS["drinking"], "drink drinking"))
        if drink.get("is_hungover"):
            found.append(Candidate("hungover", float(drink.get("hangover") or 0.0), LEADS["hungover"], "hangover"))
        health = _guarded("the health", service._body.health_label, "healthy")
        if health and health != "healthy":
            body = service._body._health
            severity = max(float(body.illness_severity), float(body.injury_severity))
            found.append(Candidate("sick", severity, f"You're {health}", "sick ill"))
    return found, shorter


def _undercurrent(service, candidates: List[Candidate], relevance) -> str:
    """The top driver -- by salience x (1 + relevance to what the user
    said) -- and at most one more, of another state: the one the user's
    words touch most when they touch any (asked "what are you eating?", her
    hunger comes forward), else the next by that score."""
    if not candidates:
        return ""
    expressions = getattr(getattr(service, "_definition", None), "state_expressions", None) or {}
    is_ai = bool(getattr(service, "_is_ai", False))
    scores = relevance([f"{c.lead} {c.words} {expression_for(c.key, expressions, is_ai=is_ai)}"
                        if c.key else f"{c.lead} {c.words}" for c in candidates])
    touched = {id(c): r for c, r in zip(candidates, scores)}
    ranked = _ranked(candidates, [c.salience * (1.0 + r) for c, r in zip(candidates, scores)])
    chosen = [ranked[0]]
    others = [c for c in ranked[1:] if c.key != chosen[0].key or c.key is None and c.lead != chosen[0].lead]
    if others:
        relevant = max(others, key=lambda c: touched[id(c)])
        chosen.append(relevant if touched[id(relevant)] > 0.0 else others[0])
    lines = [sentence(_say(service, state_line(c, expressions, is_ai=is_ai))) for c in chosen]
    return _STATE_JOIN.join(line for line in lines if line)


def _shareables(service, now: datetime) -> Tuple[Optional[Share], Optional[object], str]:
    """The one unshared thing she would most like to tell -- an item whose
    memory (the episode carrying its share id) is hers and none of whose ids
    was marked shared -- its episode, and its novelty key."""
    from aura_life.life_service import _share_ids_of, _told

    unshared: Dict[str, float] = {}
    for item in _guarded("the shareables", service._get_unshared_experiences, []):
        if getattr(item, "share_id", ""):
            unshared[item.share_id] = float(item.priority)
    for event in _guarded("the life events", service._life_events.get_unshared_events, []):
        if getattr(event, "share_id", ""):
            unshared[event.share_id] = float(event.share_urgency)
    if not unshared:
        return None, None, ""
    store = getattr(service, "_moment_novelty", {}) or {}
    best = None
    seen = set()
    episodes = _guarded("the memory", lambda: service._memory.episodes, ())
    # What she already told, in its own words: news made later in the very
    # same words -- another hour of the same activity -- is not news (Task
    # 38). Only what she TOLD: an item that left her queue untold holds
    # nothing back.
    shared = {item.share_id for item in _guarded("the shareables", lambda: list(service._shareable_queue), [])
              if getattr(item, "shared", False)}
    shared |= {event.share_id for event in _guarded("the life events", lambda: list(service._life_events._events), [])
               if getattr(event, "shared", False)}
    told = {_told(episode) for episode in episodes if any(i in shared for i in _share_ids_of(episode))}
    for episode in reversed(episodes):
        ids = _share_ids_of(episode)
        if not ids or ids[0] in seen or not all(i in unshared for i in ids) or _told(episode) in told:
            continue
        seen.add(ids[0])
        score = max(unshared[i] for i in ids) * novelty(store, ids[0], now)
        if best is None or score > best[0]:
            best = (score, ids[0], episode)
    if best is None:
        return None, None, ""
    _, share_id, episode = best
    return Share(share_id, sentence(_told(episode))), episode, share_id


#: How many memories the moment weighs as cues each turn.
MEMORY_CUES = 3


def _cues(service, user_text: Optional[str], now: datetime, relevance, skip_episode,
          said: frozenset = frozenset()) -> List[Cue]:
    """What may be on her mind now (the Task 18 brief's sources). ``said``:
    what this conversation already had (:func:`_conversation`): her memory is
    asked for that many more, so its next thoughts come once the first were
    said."""
    from aura_life.affect.affect_system import INTERNAL_STRESSOR_KINDS
    from aura_life.memory.store import retrieval_score
    from aura_life.memory.episodes import place_phrase

    def say(text): return _say(service, text)

    def first_addressed(items, cue_of) -> List[Cue]:
        """The first of ``items`` whose cue is said to her: a text written
        about her in the third person -- a profile's struggle in a goal or
        a rumination, "guilt over the friend she let down" -- is passed
        over (fix round 1, C2)."""
        for item in items:
            cue = cue_of(item)
            if cue is not None and _addressed(cue.text):
                return [cue]
        return []

    cues: List[Cue] = []
    mood = _guarded("the mood", lambda: float(service._affect.mood.valence), 0.0)
    cued = bool(user_text and user_text.strip())
    # Her memory stream, read without reinforcing (ruling T12-R2).
    def memory_cue(episode) -> Cue:
        # retrieval_score's terms are each on 0..1; without its relevance
        # term (weighed below, as for every cue) the score is on 0..3.
        score = retrieval_score(episode, now, mood_valence=mood, cued=cued) / 3.0
        # A memory is about what happened, where and with whom -- not about
        # how she felt in it: the user's "annoying" does not name a memory
        # she was annoyed in.
        about = " ".join(str(part) for part in (episode.what, episode.place, *episode.people) if part)
        return Cue(f"episode:{episode.id}", score, sentence(service._on_her_mind_line(episode)), episode, about)

    # Her memory in the order it comes to mind, walked until MEMORY_CUES of
    # it are fresh for this conversation -- neither said nor about something
    # said -- or it is exhausted: memories about what was already said must
    # not take the places of the ones never said. The ones already said that
    # the user's words name stay candidates beside the fresh ones, never
    # instead of them (a broad word, "home", names many).
    wanted = MEMORY_CUES + sum(1 for key in said if key.startswith("episode:"))
    while True:
        found = _guarded("the memory", lambda: service._memory.retrieve(
            now=now, query=user_text, k=wanted, mood_valence=mood), [])
        remembered = [memory_cue(episode) for episode in found
                      if not (episode is skip_episode or getattr(skip_episode, "id", None) == episode.id)]
        fresh = [cue for cue in remembered if cue.key not in said and _about(cue) not in said]
        if len(fresh) >= MEMORY_CUES or len(found) < wanted:
            break
        wanted *= 2
    named = [cue for cue in remembered if cue not in fresh and _named(user_text, cue)]
    cues.extend(fresh[:MEMORY_CUES] + named[:MEMORY_CUES])
    # Of every other source, the one item its engine puts first: memory is
    # the richest, the rest add one thought each (a design choice: with all
    # three of her mindset's goals, goals took most cues of the twelve
    # captures in tests/test_moment.py).
    state = _guarded("the thoughts", service._cognitive.export_state, {}) or {}
    cues += first_addressed(
        [loop for loop in (state.get("ruminations") or []) if loop.get("topic")],
        lambda loop: Cue(f"rumination:{loop['topic']}", float(loop.get("intensity") or 0.0),
                         sentence(say(f"Something keeps replaying in your mind: {loop['topic']}")),
                         about=say(loop["topic"])))
    cues += first_addressed(
        [goal for goal in _guarded("the goals", service._goal_engine.get_goals_for_mindset, []) if goal.title],
        lambda goal: Cue(f"goal:{goal.title}", float(goal.motivation_level),
                         sentence(say(f"You've been working on “{goal.title}”")), about=say(goal.title)))
    cues += first_addressed(
        [q for q in _guarded("the curiosities", lambda: service._drive.get_active_curiosities(1), []) if q.topic],
        lambda q: Cue(f"curiosity:{q.topic}", float(q.intensity),
                      sentence(say(f"A question keeps coming back to you: {q.topic}")), about=say(q.topic)))
    put_off = _guarded("the things put off", service._drive.put_off, [])
    cues += first_addressed(
        put_off[:1],
        lambda what: Cue(f"put_off:{what}", _guarded("the things put off", service._drive.put_off_share, 0.0),
                         sentence(say(f"You keep putting off {what}")), about=say(what)))
    stressors = [s for s in _guarded("the stressors", lambda: service._affect.stressors, [])
                 if s.kind not in INTERNAL_STRESSOR_KINDS and s.source]
    cues += first_addressed(
        stressors,
        lambda stressor: Cue(f"stressor:{stressor.source}", float(stressor.severity),
                             sentence(say(f"You keep coming back to {stressor.source}")),
                             about=say(stressor.source)))
    plan = _guarded("the plan", lambda: service._daily_planner.current_plan, None)
    slot = _guarded("the plan", lambda: plan.get_next_slot(service._local_world_now()), None) if plan else None
    if slot is not None and slot.activity_name:
        name = service._activity_for_display(slot.activity_name)
        where = place_phrase(slot.location)
        cues.append(Cue(f"plan:{slot.activity_name}", PLAN_SLOT_SALIENCE,
                        sentence(say(f"Coming up later: {name} {where}")), about=say(f"{name} {where}")))
    return [cue for cue in cues if cue.text and _addressed(cue.text)]


def build_moment(service, user_text: Optional[str] = None) -> Moment:
    """Her moment now (``LifeService.get_moment``). It reads her state and
    changes two things that are saved (ruling T18-R2): the novelty of the
    cues it rendered, and the reinforcement of the at most two memory cues
    it rendered (ruling T12-R2) -- and one that is not: what this
    conversation has had (:func:`_conversation`, in memory only), which the
    next moment of the conversation passes over. It consumes no latch, marks
    nothing shared, fires no trigger and reaches no LLM."""
    now = service._world_clock()()
    memory = service._memory
    relevance = (lambda texts: memory.relevance(user_text, texts)) if user_text and user_text.strip() \
        else (lambda texts: [0.0] * len(texts))

    said = _conversation(service, now)
    candidates, shorter = _candidates(service, frozenset(said))
    undercurrent = _undercurrent(service, candidates, relevance)
    share, share_episode, share_key = _shareables(service, now)

    store = getattr(service, "_moment_novelty", {}) or {}
    cues = _cues(service, user_text, now, relevance, share_episode, frozenset(said))
    scores = relevance([cue.about or cue.text for cue in cues])
    # In this conversation already (Task 38), itself or in other words about
    # the same thing: passed over, unless the user's own words name it.
    fresh = [(cue, r) for cue, r in zip(cues, scores)
             if (cue.key not in said and _about(cue) not in said) or _named(user_text, cue)]
    cues, scores = [cue for cue, _ in fresh], [r for _, r in fresh]
    ranked = _ranked(cues, [c.salience * novelty(store, c.key, now) * (1.0 + r) for c, r in zip(cues, scores)])
    on_mind: List[Cue] = []
    for cue in ranked:
        if cue.text not in (c.text for c in on_mind) and _about(cue) not in (_about(c) for c in on_mind):
            on_mind.append(cue)
        if len(on_mind) == MAX_ON_MIND:
            break

    length = length_target(_guarded("the traits", service._communication_traits, []))
    if shorter:
        length = length.shortened()
    from aura_life.expression.expression_system import DISTANCE_LINES
    from aura_life.expression.relationship import stage_for
    stage = stage_for(_guarded("the depth", lambda: service.relationship_depth, 0.0))
    speech = (length.words(), ONE_QUESTION, DONT_NAME, DISTANCE_LINES[stage])

    moment = fitted(Moment(
        situation=_situation(service),
        undercurrent=undercurrent,
        on_mind=tuple(cue.text for cue in on_mind),
        to_share=share,
        speech=speech,
        unspoken=_unspoken(service),
        length=length,
    ))

    shown = [cue for cue in on_mind if cue.text in moment.on_mind]
    keys = [cue.key for cue in shown] + ([share_key] if moment.to_share is not None and share_key else [])
    said.update(cue.key for cue in shown)
    said.update(_about(cue) for cue in shown)
    if moment.to_share is not None and share_episode is not None:
        # What she is offered to share is that memory: not also "on her
        # mind" at the next turn.
        said.add(f"episode:{share_episode.id}")
    back = _say(service, LEADS["back"].format(user=service._user_ref()))
    if any(c.key == "after_absence" and c.lead and _say(service, c.lead) == back for c in candidates) \
            and back in moment.undercurrent:
        said.add(ABSENCE_KEY)
    service._moment_novelty = after_rendering(store, keys, now)
    _guarded("the moment's novelty", service._save_moment_state, None)
    episodes = [cue.episode for cue in shown if cue.episode is not None]
    if episodes:
        _guarded("the memory", lambda: memory.reinforce(episodes, now=now), None)
    return moment


def _unspoken(service) -> Tuple[str, ...]:
    """What she keeps to herself, at most one line: her newest secret, else
    the strongest of what her shadow hides."""
    secrets = _guarded("the secrets", lambda: list(service._shadow.state.secrets), [])
    if secrets:
        return (sentence(_say(service, f"You haven't told anyone: {secrets[-1]}")),)
    shadow = _guarded("the shadow", lambda: service._shadow.export_state(), {}) or {}
    lines = {
        "urge_to_confess": "You're carrying something you haven't said, and part of you wants it out",
        "concealment_load": "There's something you're keeping to yourself",
        "masking": "You're putting on a front",
    }
    present = [(float(shadow.get(k) or 0.0), k) for k in lines if shadow.get(k)]
    if not present:
        return ()
    return (sentence(lines[max(present)[1]]),)


__all__ = [
    "Moment", "Share", "LengthTarget", "DEFAULT_LENGTH", "NEUTRAL_EXPRESSIONS", "AI_STATE_KEYS",
    "MAX_RENDER_CHARS", "MAX_ON_MIND", "NOVELTY_LOSS_PER_RENDER", "NOVELTY_RECOVERY_PER_HOUR",
    "STATE_KEYS", "length_target", "novelty", "after_rendering", "expression_for", "state_line",
]
