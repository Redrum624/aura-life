"""
Emotion Persistence System

Saves emotional state to database for persistence across restarts.
Enables multi-day emotional arcs.

Refactored to use shared PersonaDataStore connection.
"""

import logging
import contextlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import threading

logger = logging.getLogger(__name__)


@dataclass
class PersistedEmotion:
    """An emotion state persisted to database."""
    emotion: str
    intensity: float
    caused_by: str  # What caused this emotion
    timestamp: datetime
    decay_rate: float = 0.01  # How fast it decays per hour


class EmotionPersistence:
    """Manages persistent emotional state."""

    def __init__(self, persona_id: str, db_path: Optional[Path] = None, datastore=None):
        """
        Initialize emotion persistence.

        Args:
            persona_id: Identifier for the persona
            db_path: Legacy path for standalone DB (deprecated)
            datastore: PersonaDataStore instance for shared DB connection
        """
        self.persona_id = persona_id
        self._datastore = datastore
        self._legacy_db_path = db_path
        self._lock = threading.Lock()
        self._emotions: Dict[str, PersistedEmotion] = {}

        # Only init standalone DB if no datastore provided
        if datastore is None and db_path is not None:
            self._init_standalone_db()

        self._load()

    def _init_standalone_db(self):
        """Initialize standalone database tables (legacy mode)."""
        with contextlib.closing(sqlite3.connect(self._legacy_db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS emotion_state (
                    emotion TEXT PRIMARY KEY,
                    intensity REAL,
                    caused_by TEXT,
                    timestamp TEXT,
                    decay_rate REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS emotion_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    emotion TEXT,
                    intensity REAL,
                    caused_by TEXT,
                    timestamp TEXT
                )
            """)
            conn.commit()

    def _get_connection(self):
        """Get database connection (shared or standalone)."""
        if self._datastore:
            return self._datastore.get_connection()
        else:
            # Legacy standalone connection
            from contextlib import contextmanager

            @contextmanager
            def standalone_conn():
                conn = sqlite3.connect(self._legacy_db_path)
                conn.row_factory = sqlite3.Row
                try:
                    yield conn
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.close()

            return standalone_conn()

    def _load(self):
        """Load persisted emotions from database."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            now = datetime.now()

            for row in conn.execute("SELECT * FROM emotion_state").fetchall():
                timestamp = datetime.fromisoformat(row["timestamp"])
                hours_elapsed = (now - timestamp).total_seconds() / 3600

                # Apply decay
                intensity = row["intensity"] - (row["decay_rate"] * hours_elapsed)

                if intensity > 0.1:  # Only keep emotions above threshold
                    self._emotions[row["emotion"]] = PersistedEmotion(
                        emotion=row["emotion"],
                        intensity=max(0.1, min(1.0, intensity)),
                        caused_by=row["caused_by"],
                        timestamp=timestamp,
                        decay_rate=row["decay_rate"],
                    )
                else:
                    # Remove decayed emotion
                    conn.execute("DELETE FROM emotion_state WHERE emotion = ?", (row["emotion"],))

            conn.commit()
            logger.info(f"Loaded {len(self._emotions)} persisted emotions for {self.persona_id}")

    def save_emotion(self, emotion: str, intensity: float, caused_by: str = "", decay_rate: float = 0.01):
        """Save or update an emotion."""
        with self._lock:
            now = datetime.now()

            # Categorize decay rates
            # Sticky emotions: sadness, grief, resentment - decay slowly
            # Quick emotions: joy, surprise, annoyance - decay faster
            sticky_emotions = ["sad", "grief", "hurt", "disappointed", "lonely", "anxious"]
            quick_emotions = ["surprised", "excited", "annoyed", "amused"]

            if any(s in emotion.lower() for s in sticky_emotions):
                decay_rate = 0.005  # Very slow decay
            elif any(q in emotion.lower() for q in quick_emotions):
                decay_rate = 0.02  # Faster decay

            persisted = PersistedEmotion(
                emotion=emotion,
                intensity=intensity,
                caused_by=caused_by,
                timestamp=now,
                decay_rate=decay_rate,
            )
            self._emotions[emotion] = persisted

            with self._get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO emotion_state
                    (emotion, intensity, caused_by, timestamp, decay_rate)
                    VALUES (?, ?, ?, ?, ?)
                """, (emotion, intensity, caused_by, now.isoformat(), decay_rate))

                # Also log to history
                conn.execute("""
                    INSERT INTO emotion_history (emotion, intensity, caused_by, timestamp)
                    VALUES (?, ?, ?, ?)
                """, (emotion, intensity, caused_by, now.isoformat()))

    def get_current_emotions(self) -> Dict[str, float]:
        """Get current emotional state with decay applied."""
        with self._lock:
            now = datetime.now()
            result = {}

            for emotion, persisted in list(self._emotions.items()):
                hours_elapsed = (now - persisted.timestamp).total_seconds() / 3600
                intensity = persisted.intensity - (persisted.decay_rate * hours_elapsed)

                if intensity > 0.1:
                    result[emotion] = intensity
                else:
                    del self._emotions[emotion]

            return result

    def get_dominant_emotion(self) -> Optional[str]:
        """Get the current dominant emotion."""
        emotions = self.get_current_emotions()
        if not emotions:
            return None
        return max(emotions.keys(), key=lambda e: emotions[e])

    def get_emotional_context(self) -> str:
        """Get emotional context for the system prompt."""
        emotions = self.get_current_emotions()
        if not emotions:
            return ""

        lines = []
        dominant = self.get_dominant_emotion()

        if dominant:
            intensity = emotions[dominant]
            if intensity > 0.7:
                lines.append(f"You're feeling strongly {dominant}.")
            elif intensity > 0.4:
                lines.append(f"You're feeling {dominant}.")
            else:
                lines.append(f"There's a lingering sense of {dominant}.")

            # Check for emotional causes
            persisted = self._emotions.get(dominant)
            if persisted and persisted.caused_by:
                hours_ago = (datetime.now() - persisted.timestamp).total_seconds() / 3600
                if hours_ago < 1:
                    lines.append(f"This is recent—{persisted.caused_by}.")
                elif hours_ago < 24:
                    lines.append(f"This started earlier—{persisted.caused_by}.")
                else:
                    lines.append(f"You've been feeling this way since {persisted.caused_by}.")

        # Secondary emotions
        secondary = [(e, i) for e, i in emotions.items() if e != dominant and i > 0.3]
        if secondary:
            sec_names = [e for e, _ in sorted(secondary, key=lambda x: -x[1])[:2]]
            if sec_names:
                lines.append(f"Underneath, there's also some {' and '.join(sec_names)}.")

        return " ".join(lines)

    def get_emotional_history(self, limit: int = 20) -> List[dict]:
        """Get recent emotional history."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM emotion_history
                ORDER BY timestamp DESC LIMIT ?
            """, (limit,)).fetchall()

            return [dict(row) for row in rows]

    def clear_emotion(self, emotion: str):
        """Clear a specific emotion."""
        with self._lock:
            if emotion in self._emotions:
                del self._emotions[emotion]
            with self._get_connection() as conn:
                conn.execute("DELETE FROM emotion_state WHERE emotion = ?", (emotion,))

    def get_status(self) -> dict:
        """Get status dict for API."""
        emotions = self.get_current_emotions()
        return {
            "current_emotions": emotions,
            "dominant": self.get_dominant_emotion(),
            "emotion_count": len(emotions),
        }

    def reset(self) -> dict:
        """Reset all emotion data."""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM emotion_state")
                conn.execute("DELETE FROM emotion_history")

            self._emotions = {}
            logger.info(f"Emotion persistence reset for {self.persona_id}")

            return {
                "emotion_state_cleared": True,
                "emotion_history_cleared": True,
            }


# Global persistence managers per persona
_persistence_managers: Dict[str, EmotionPersistence] = {}


def get_emotion_persistence(persona_id: str, db_dir: Path = None, datastore=None) -> EmotionPersistence:
    """Get or create emotion persistence for a persona."""
    if persona_id not in _persistence_managers:
        # Try to get the persona's CONSOLIDATED datastore if not provided, so emotions land
        # in memory.db. Use the public factory (it owns the cache key "{persona}:owner");
        # the previous `persona_id in _datastores` check used a bare key that never matched,
        # so it always fell to legacy mode and scattered standalone *_emotions.db files.
        if datastore is None:
            try:
                from aura_life.hooks import get_config, get_persona_datastore
                datastore = get_persona_datastore(persona_id, db_dir or get_config().data_dir)
            except Exception:
                datastore = None

        if datastore:
            _persistence_managers[persona_id] = EmotionPersistence(persona_id, datastore=datastore)
        else:
            # Legacy mode - standalone DB (only if no datastore could be resolved)
            if db_dir is None:
                from aura_life.hooks import get_config
                db_dir = get_config().data_dir
            db_path = db_dir / f"{persona_id}_emotions.db"
            _persistence_managers[persona_id] = EmotionPersistence(persona_id, db_path=db_path)
    return _persistence_managers[persona_id]
