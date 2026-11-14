"""The memory stream: her episodes, how she recalls them, and where they are
kept (humanness program Task 12, spec section 4.6).

Recording
=========

:meth:`MemoryStream.record` turns one significant event into an
:class:`~aura_life.memory.episodes.Episode` and gives it its importance
(the formula in :mod:`aura_life.memory.episodes`). Its novelty reads a small
index of when she last met each activity, place and person ("facets"), kept
beside the stream, so pruning an episode never makes a routine look new. And
nothing is new to her before her memory spans NOVELTY_WINDOW_DAYS: her first
days of memory are not her first days of life, and a routine counted as
"novel" then would be kept, as her most important memories, for good.

Retention: the stream keeps the EPISODE_CAP (2,000) most important episodes.
Each write that takes it past the cap drops the least important -- of equals,
the one written earliest; the episode just written, when it is the least
important -- in the same transaction, so the database always holds exactly
what the stream does. Deterministic: no draw, no clock read.

Recalling
=========

:meth:`MemoryStream.retrieve` ranks every episode by (:func:`retrieval_score`)::

    score = recency + importance + relevance + mood congruence
            (x retention when no query cues the recall)

    recency         0.995 per hour since she last recalled it (Episode.recency)
    importance      0.1..1, set when it was recorded
    relevance       with a query: the share of the query's words the episode
                    shares (aura_life.activities.choice.terms -- stemmed, no
                    stopwords); or, when the host registered the optional
                    ``embed`` hook, the cosine of their vectors (below 0 read
                    as 0). Without a query: 0.
    mood congruence 1 - |her valence now - the episode's| / 2
    retention       how much of it she still holds: exp(-t / S), t the days
                    since she last recalled it, S its strength (ruling
                    T12-R1; Episode.retention) -- applied only to unprompted
                    recall; a query-cued recall is not weighted by it, so a
                    good cue brings back a faded memory (ruling T12-R5)

Each term is on 0..1 by construction -- an absolute scale, not a min-max over
the episodes being ranked (Generative Agents' normalisation): min-max
stretches the smallest spread (two moods a tenth apart) as far as the largest,
and over a handful of episodes turns every term into 0 or 1, so the oldest
relevant episode could never outrank the newest irrelevant one. Retention is
0..1 too, so a score is 0..4, never negative. What she has not recalled fades
from unprompted recall -- a day on it weighs 0.37 of itself, three days on
0.05 -- while a cue still brings it back, and
what she keeps recalling stays: each recall adds 1 to S. Ties go to the
episode written later. :meth:`MemoryStream.recall` is ``retrieve`` plus
recall's effect on what it returns: each one's strength gains 1 and its
recency and retention start again (:meth:`Episode.recalled`), saved at once.

The ``embed`` hook is optional (:mod:`aura_life.hooks`) and called in one
guarded place, :func:`_embed`: a host without one gets keyword overlap and a
DEBUG line; one whose hook fails or answers anything but one finite vector per
text, all of one length, gets keyword overlap and one WARNING. An episode's
vector is asked once and kept in memory, never saved.

Persistence
===========

Three tables in the persona's ``life.db`` (``CREATE TABLE IF NOT EXISTS``: an
existing database gains them and keeps everything else):
``life_memory_episodes`` (one row per episode kept), ``life_memory_facets``
(the novelty index; a facet unseen for the window is equivalent to none and is
deleted) and ``life_memory_state`` (the next id, which never repeats, and
when her memory began). Saved on write -- each ``record``, ``reinforce`` and
``clear`` commits before it returns -- not only on stop. One stream per
database: two live streams on one file would give out the same ids.
"""

import contextlib
import json
import logging
import math
import sqlite3
import threading
from datetime import datetime
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from aura_life.hooks import HookNotConfigured, is_configured

from ..activities.choice import terms
from .episodes import (
    INITIAL_STRENGTH,
    NOVELTY_WINDOW_DAYS,
    Episode,
    dominant_emotion,
    emotion_intensity,
    hours_between,
    importance_of,
)

logger = logging.getLogger(__name__)

#: How many episodes the stream keeps: the most important (the Task 12 brief).
EPISODE_CAP = 2000

_WINDOW_HOURS = NOVELTY_WINDOW_DAYS * 24.0

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS life_memory_episodes (
        id INTEGER PRIMARY KEY,
        at TEXT NOT NULL,
        place TEXT NOT NULL DEFAULT '',
        people TEXT NOT NULL DEFAULT '[]',
        what TEXT NOT NULL,
        emotion TEXT NOT NULL DEFAULT '',
        valence REAL NOT NULL DEFAULT 0,
        importance REAL NOT NULL,
        strength REAL NOT NULL DEFAULT 1,
        last_recalled TEXT,
        tags TEXT NOT NULL DEFAULT '[]'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS life_memory_facets (
        facet TEXT PRIMARY KEY,
        last_seen TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS life_memory_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        next_id INTEGER NOT NULL DEFAULT 1,
        began_at TEXT
    )
    """,
)

_COLUMNS = "id, at, place, people, what, emotion, valence, importance, strength, last_recalled, tags"

#: What :func:`_embed` answers when the host registered no ``embed`` hook --
#: not ``None``, which a registered hook may answer (and is then reported).
NO_EMBED_HOOK = object()


def _embed(texts: List[str]):
    """The host's vectors for ``texts`` (the optional ``embed`` hook), or
    NO_EMBED_HOOK when the host registered none -- said at DEBUG only: most
    hosts have none, and relevance is then keyword overlap. Anything the hook
    itself raises is the caller's to report."""
    try:
        from aura_life.hooks import embed
        return embed(texts)
    except HookNotConfigured:
        logger.debug("No embed hook is configured: the memory stream's relevance is keyword overlap")
        return NO_EMBED_HOOK


def retrieval_score(episode: Episode, now: datetime, *, relevance: float = 0.0, mood_valence: float = 0.0,
                    cued: bool = False) -> float:
    """How readily ``episode`` comes to mind at ``now`` (the module
    docstring): recency + importance + relevance + mood congruence. Recall
    that comes unbidden (no cue, ``cued`` False) is weighted by the episode's
    retention (ruling T12-R1): what she has not rehearsed fades. A cued recall
    -- a query names what to remember -- is not (ruling T12-R5): a good cue
    brings back a faded memory. Each term is on 0..1 and retention too, so
    the score is on 0..4 -- never negative, never NaN."""
    mood = max(-1.0, min(1.0, float(mood_valence)))
    weight = episode.recency(now) + episode.importance + relevance + 1.0 - abs(episode.valence - mood) / 2.0
    return weight if cued else weight * episode.retention(now)


def _checked_vectors(vectors, count: int) -> List[Tuple[float, ...]]:
    """``vectors`` as ``count`` unit-length tuples of floats, or ValueError
    when they are not one finite, non-zero vector per text, all of one
    length."""
    try:
        answered = len(vectors)
    except TypeError:
        raise ValueError(f"the embed hook answered {type(vectors).__name__}, not one vector per text") from None
    if answered != count:
        raise ValueError(f"the embed hook answered {answered} vectors for {count} texts")
    checked: List[Tuple[float, ...]] = []
    for vector in vectors:
        values = tuple(float(x) for x in vector)
        if not values or not all(math.isfinite(x) for x in values):
            raise ValueError("the embed hook answered an empty vector, or one that is not a number")
        if checked and len(values) != len(checked[0]):
            raise ValueError("the embed hook answered vectors of different lengths")
        norm = math.sqrt(sum(x * x for x in values))
        checked.append(tuple(x / norm for x in values) if norm else values)
    return checked


def _row(episode: Episode) -> tuple:
    return (
        episode.id, episode.at.isoformat(), episode.place, json.dumps(list(episode.people)), episode.what,
        episode.emotion, episode.valence, episode.importance, episode.strength,
        episode.last_recalled.isoformat() if episode.last_recalled else None, json.dumps(list(episode.tags)),
    )


def _episode_from_row(row) -> Episode:
    (episode_id, at, place, people, what, feeling, valence, importance, strength, last_recalled, tags) = row
    return Episode(
        id=int(episode_id),
        at=datetime.fromisoformat(at),
        place=place or "",
        people=tuple(json.loads(people or "[]")),
        what=what or "",
        emotion=feeling or "",
        valence=float(valence or 0.0),
        importance=float(importance),
        strength=float(strength or INITIAL_STRENGTH),
        last_recalled=datetime.fromisoformat(last_recalled) if last_recalled else None,
        tags=tuple(json.loads(tags or "[]")),
    )


def _facets_of(place: str, people: Tuple[str, ...], activity: Optional[str]) -> List[str]:
    """What of an event can be new to her: its activity, its place, each of
    its people (case-insensitive)."""
    facets = set()
    if activity and activity.strip():
        facets.add("activity:" + " ".join(activity.lower().split()))
    if place:
        facets.add("place:" + place.lower())
    facets.update("person:" + person.lower() for person in people)
    return sorted(facets)


def _words(values: Iterable[str]) -> str:
    return " ".join(str(value).replace("_", " ") for value in values if value)


class MemoryStream:
    """Her memory stream (the module docstring): the episodes she keeps, in
    the order they were written, saved in ``db_path`` (none: in memory only)
    as each change is made. Thread-safe: a host may recall from a request
    thread while her ticks record."""

    def __init__(self, db_path: Optional[str] = None, *, cap: int = EPISODE_CAP):
        if int(cap) < 1:
            raise ValueError(f"a memory stream keeps at least one episode, not {cap}")
        self._db_path = db_path
        self._cap = int(cap)
        self._lock = threading.RLock()
        self._episodes: Dict[int, Episode] = {}
        self._facets: Dict[str, datetime] = {}
        self._next_id = 1
        self._began_at: Optional[datetime] = None
        self._terms: Dict[int, FrozenSet[str]] = {}
        self._vectors: Dict[int, Tuple[float, ...]] = {}
        self._embed_failure_reported = False

    # ============= What she keeps =============

    @property
    def cap(self) -> int:
        """How many episodes the stream keeps (the most important)."""
        return self._cap

    @property
    def episodes(self) -> Tuple[Episode, ...]:
        """Every episode she keeps, in the order they were written."""
        with self._lock:
            return tuple(self._episodes.values())

    def get(self, episode_id: int) -> Optional[Episode]:
        """The episode with this id, or ``None`` when she does not keep it."""
        with self._lock:
            return self._episodes.get(episode_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._episodes)

    # ============= Persistence =============

    @staticmethod
    def create_schema(cursor) -> None:
        """Create the stream's tables where they do not exist yet (see the
        module docstring); harmless to run again."""
        for statement in _SCHEMA:
            cursor.execute(statement)

    def load(self) -> None:
        """Read the stream back from its database -- creating its tables if
        the database has none -- replacing what is in memory. A row that
        cannot be read is skipped, with a WARNING. Nothing to read without a
        database."""
        if self._db_path is None:
            return
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            self.create_schema(cursor)
            conn.commit()
            episodes: Dict[int, Episode] = {}
            for row in cursor.execute(f"SELECT {_COLUMNS} FROM life_memory_episodes ORDER BY id").fetchall():
                try:
                    episode = _episode_from_row(row)
                except (TypeError, ValueError) as exc:
                    logger.warning("Skipping memory episode %r, which cannot be read: %s", row[0], exc)
                    continue
                episodes[episode.id] = episode
            facets: Dict[str, datetime] = {}
            for facet, last_seen in cursor.execute("SELECT facet, last_seen FROM life_memory_facets").fetchall():
                try:
                    facets[facet] = datetime.fromisoformat(last_seen)
                except (TypeError, ValueError):
                    continue
            state = cursor.execute("SELECT next_id, began_at FROM life_memory_state WHERE id = 1").fetchone()
        with self._lock:
            self._episodes = episodes
            self._facets = facets
            saved_next = int(state[0]) if state and state[0] else 1
            self._next_id = max(saved_next, max(episodes, default=0) + 1)
            began = state[1] if state else None
            self._began_at = (datetime.fromisoformat(began) if began
                              else min((e.at for e in episodes.values()), default=None))
            self._terms.clear()
            self._vectors.clear()

    def clear(self) -> None:
        """Forget every episode and the novelty index, on disk too (ids go
        on from where they were: one never repeats)."""
        with self._lock:
            self._episodes.clear()
            self._facets.clear()
            self._terms.clear()
            self._vectors.clear()
            self._began_at = None
            if self._db_path is None:
                return
            with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
                cursor = conn.cursor()
                self.create_schema(cursor)
                cursor.execute("DELETE FROM life_memory_episodes")
                cursor.execute("DELETE FROM life_memory_facets")
                self._save_state(cursor)
                conn.commit()

    def _save_state(self, cursor) -> None:
        cursor.execute(
            "INSERT OR REPLACE INTO life_memory_state (id, next_id, began_at) VALUES (1, ?, ?)",
            (self._next_id, self._began_at.isoformat() if self._began_at else None),
        )

    # ============= Recording =============

    def record(self, *, at: datetime, what: str, place: str = "", people: Iterable[str] = (),
               emotions: Optional[Mapping[str, float]] = None, emotion: Optional[str] = None,
               intensity: Optional[float] = None, valence: float = 0.0, tags: Iterable[str] = (),
               activity: Optional[str] = None) -> Episode:
        """Record one event as an episode, saved before this returns, and
        return it -- even when it is the least important of a full stream and
        so not kept (its importance still counts for whoever sums them).

        ``at``: when, on the world clock. ``what``: a short phrase of what
        happened, told as it will be quoted to her (never empty). ``place``:
        her location key. ``people``: who was there. ``emotions``: what she
        felt, name -> intensity -- the strongest is the episode's emotion, and
        its intensity how strongly she felt it; an appraisal passes
        ``emotion`` and ``intensity`` itself instead (Task 14's outcome
        appraisal, Task 16's user turns). ``valence``: her mood's when she
        lived it, or the appraisal's. ``tags``: what it is. ``activity``: the
        activity it was, when it was one (a facet of its novelty).
        """
        what = " ".join(str(what or "").split())
        if not what:
            raise ValueError("an episode needs what happened")
        who = tuple(dict.fromkeys(name for name in (" ".join(str(n).split()) for n in people) if name))
        felt = dict(emotions or {})
        strength_of_feeling = emotion_intensity(felt) if intensity is None else min(1.0, abs(float(intensity)))
        name = dominant_emotion(felt) if emotion is None else " ".join(str(emotion).split())
        where = " ".join(str(place or "").split())
        kinds = tuple(dict.fromkeys(tag for tag in (str(t).strip() for t in tags) if tag))
        with self._lock:
            facets = _facets_of(where, who, activity)
            episode = Episode(
                id=self._next_id, at=at, place=where, people=who, what=what, emotion=name,
                valence=max(-1.0, min(1.0, float(valence))),
                importance=importance_of(strength_of_feeling, self._is_novel(facets, at), len(who)),
                tags=kinds,
            )
            self._next_id += 1
            if self._began_at is None:
                self._began_at = at
            seen = {}
            for facet in facets:
                last = self._facets.get(facet)
                if last is None or hours_between(last, at) > 0:
                    self._facets[facet] = seen[facet] = at
            stale = [facet for facet, last in self._facets.items() if hours_between(last, at) >= _WINDOW_HOURS]
            for facet in stale:
                del self._facets[facet]
            self._episodes[episode.id] = episode
            pruned = self._prune()
            self._write(None if episode.id in pruned else episode, seen, stale, pruned)
        return episode

    def _is_novel(self, facets: Sequence[str], at: datetime) -> bool:
        """Whether one of ``facets`` is one she has not met in the window --
        never before her memory spans it."""
        if not facets or self._began_at is None or hours_between(self._began_at, at) < _WINDOW_HOURS:
            return False
        return any(facet not in self._facets or hours_between(self._facets[facet], at) >= _WINDOW_HOURS
                   for facet in facets)

    def _prune(self) -> List[int]:
        """Drop the least important episodes past the cap -- of equals, the
        earliest written -- and return their ids."""
        excess = len(self._episodes) - self._cap
        if excess <= 0:
            return []
        doomed = [e.id for e in sorted(self._episodes.values(), key=lambda e: (e.importance, e.id))[:excess]]
        for episode_id in doomed:
            del self._episodes[episode_id]
            self._terms.pop(episode_id, None)
            self._vectors.pop(episode_id, None)
        return doomed

    def _write(self, episode: Optional[Episode], seen: Mapping[str, datetime], stale: Sequence[str],
               pruned: Sequence[int]) -> None:
        """Save one record's changes in one transaction."""
        if self._db_path is None:
            return
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            self.create_schema(cursor)
            if episode is not None:
                cursor.execute(f"INSERT INTO life_memory_episodes ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               _row(episode))
            if seen:
                cursor.executemany("INSERT OR REPLACE INTO life_memory_facets (facet, last_seen) VALUES (?, ?)",
                                   [(facet, when.isoformat()) for facet, when in seen.items()])
            if stale:
                cursor.executemany("DELETE FROM life_memory_facets WHERE facet = ?", [(facet,) for facet in stale])
            if pruned:
                cursor.executemany("DELETE FROM life_memory_episodes WHERE id = ?", [(i,) for i in pruned])
            self._save_state(cursor)
            conn.commit()

    # ============= Recalling =============

    def retrieve(self, *, now: datetime, query: Optional[str] = None, k: int = 3,
                 mood_valence: float = 0.0) -> List[Episode]:
        """The ``k`` episodes that come to mind at ``now`` -- for ``query``
        when one is given -- in her mood (``mood_valence``, -1..1), best first
        (the score in the module docstring). Changes nothing: see
        :meth:`recall`."""
        if k <= 0:
            return []
        candidates = list(self.episodes)
        if not candidates:
            return []
        cued = bool(query and query.strip())
        relevance = self._relevance(query, candidates) if cued else [0.0] * len(candidates)
        scored = [
            (retrieval_score(episode, now, relevance=relevant, mood_valence=mood_valence, cued=cued),
             episode.id, episode)
            for episode, relevant in zip(candidates, relevance)
        ]
        scored.sort(key=lambda item: (-item[0], -item[1]))
        return [episode for _, _, episode in scored[:k]]

    def reinforce(self, episodes: Iterable[Episode], *, now: datetime) -> List[Episode]:
        """Recall's effect on ``episodes`` at ``now``: each one's strength
        gains 1 and its recency starts again (Episode.recalled), saved at
        once. Returns them as they are now; one no longer kept is skipped."""
        with self._lock:
            recalled = []
            for episode in episodes:
                current = self._episodes.get(episode.id)
                if current is None:
                    continue
                self._episodes[episode.id] = current.recalled(now)
                recalled.append(self._episodes[episode.id])
            if recalled and self._db_path is not None:
                with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
                    cursor = conn.cursor()
                    self.create_schema(cursor)
                    cursor.executemany(
                        "UPDATE life_memory_episodes SET strength = ?, last_recalled = ? WHERE id = ?",
                        [(e.strength, e.last_recalled.isoformat(), e.id) for e in recalled],
                    )
                    conn.commit()
            return recalled

    def recall(self, *, now: datetime, query: Optional[str] = None, k: int = 3,
               mood_valence: float = 0.0) -> List[Episode]:
        """What she recalls at ``now``: :meth:`retrieve`, and each episode it
        returns strengthened (:meth:`reinforce`)."""
        return self.reinforce(self.retrieve(now=now, query=query, k=k, mood_valence=mood_valence), now=now)

    # ============= Relevance =============

    def _relevance(self, query: str, candidates: List[Episode]) -> List[float]:
        """Each candidate's relevance to ``query``, 0..1: by the host's
        vectors when it has an ``embed`` hook that works, else by keyword
        overlap."""
        by_vectors = self._embedded_relevance(query, candidates)
        if by_vectors is not None:
            return by_vectors
        wanted = terms(query)
        if not wanted:
            return [0.0] * len(candidates)
        return [len(wanted & self._terms_of(episode)) / len(wanted) for episode in candidates]

    def relevance(self, query: Optional[str], texts: Sequence[str]) -> List[float]:
        """Each of ``texts``' relevance to ``query``, 0..1, the way an
        episode's is reckoned: the cosine of the host's vectors when it has
        an ``embed`` hook that works (through :func:`_embed`, the one place
        the hook is called), else keyword overlap -- for what the moment
        weighs that is not an episode (a goal, a stressor, a plan slot; ruling
        T18-R3). No query, all 0. Changes nothing but the once-only report of
        a failing hook."""
        texts = [str(text or "") for text in texts]
        if not texts or not (query and query.strip()):
            return [0.0] * len(texts)
        if is_configured("embed"):
            try:
                answered = _embed([query] + texts)
                if answered is not NO_EMBED_HOOK:
                    vectors = _checked_vectors(answered, len(texts) + 1)
                    wanted = vectors[0]
                    return [max(0.0, min(1.0, sum(a * b for a, b in zip(wanted, vector))))
                            for vector in vectors[1:]]
            except Exception as exc:
                if not self._embed_failure_reported:
                    self._embed_failure_reported = True
                    logger.warning("The embed hook failed (%s): the memory stream's relevance is keyword overlap", exc)
                else:
                    logger.debug("The embed hook failed again (%s)", exc)
        wanted = terms(query)
        if not wanted:
            return [0.0] * len(texts)
        return [len(wanted & terms(text)) / len(wanted) for text in texts]

    def _terms_of(self, episode: Episode) -> FrozenSet[str]:
        """The episode's words for keyword overlap: what happened, where, who,
        what she felt, and its tags (not its share ids)."""
        cached = self._terms.get(episode.id)
        if cached is None:
            cached = terms(_words([episode.what, episode.place, *episode.people, episode.emotion,
                                   *(tag for tag in episode.tags if ":" not in tag)]))
            with self._lock:
                if episode.id in self._episodes:
                    self._terms[episode.id] = cached
        return cached

    def _embedded_relevance(self, query: str, candidates: List[Episode], retried: bool = False) -> Optional[List[float]]:
        """Each candidate's relevance by the host's vectors -- the cosine of
        the query's and the episode's gist's, below 0 read as 0 -- or
        ``None`` when there is no hook or it failed (reported once)."""
        if not is_configured("embed"):
            # Asked before a single gist is written: most hosts have none.
            logger.debug("No embed hook is configured: the memory stream's relevance is keyword overlap")
            return None
        missing = [episode for episode in candidates if episode.id not in self._vectors]
        texts = [query] + [episode.gist() for episode in missing]
        try:
            answered = _embed(texts)
            if answered is NO_EMBED_HOOK:
                return None
            vectors = _checked_vectors(answered, len(texts))
        except Exception as exc:
            if not self._embed_failure_reported:
                self._embed_failure_reported = True
                logger.warning("The embed hook failed (%s): the memory stream's relevance is keyword overlap", exc)
            else:
                logger.debug("The embed hook failed again (%s)", exc)
            return None
        wanted, fresh = vectors[0], dict(zip((episode.id for episode in missing), vectors[1:]))
        with self._lock:
            for episode_id, vector in fresh.items():
                if episode_id in self._episodes:
                    self._vectors[episode_id] = vector
            kept = {episode.id: self._vectors.get(episode.id, fresh.get(episode.id)) for episode in candidates}
            model_changed = any(vector is not None and len(vector) != len(wanted) for vector in kept.values())
            if model_changed:
                self._vectors.clear()
        if model_changed:
            # The host changed its model: every vector is asked again, once
            # (outside the lock -- the hook is the host's, and may be slow).
            return None if retried else self._embedded_relevance(query, candidates, retried=True)
        return [max(0.0, min(1.0, sum(a * b for a, b in zip(wanted, kept[episode.id] or ()))))
                for episode in candidates]
