"""
Personality Manager

Manages multiple AI personalities with their own:
- Memory databases
- Emotion engines
- Voice profiles
"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass

from .personality_config import PersonalityDefinition, get_personality

logger = logging.getLogger(__name__)


@dataclass
class PersonalityInstance:
    """A running instance of a personality with its services."""
    definition: PersonalityDefinition
    memory_service: "MemoryService"
    emotion_engine: "EmotionEngine"
    life_service: Optional["LifeService"] = None


class MultiPersonalityManager:
    """
    Manages multiple AI personalities, each with separate state.
    """

    def __init__(self):
        self._instances: Dict[str, PersonalityInstance] = {}
        # No persona is current until one is registered and selected: a
        # hardcoded id here resolved to a personality nobody had initialized.
        self._current_id: Optional[str] = None

    def initialize_personality(
        self,
        personality_id: str,
        memory_service: "MemoryService",
        emotion_engine: "EmotionEngine",
        life_service: Optional["LifeService"] = None,
    ) -> Optional[PersonalityInstance]:
        """
        Initialize a personality with its services.

        Args:
            personality_id: The personality identifier
            memory_service: Memory service for this personality
            emotion_engine: Emotion engine for this personality
            life_service: Optional life service for this personality

        Returns:
            The initialized PersonalityInstance, or None if personality not found
        """
        definition = get_personality(personality_id)
        if not definition:
            logger.error(f"Personality '{personality_id}' not found")
            return None

        instance = PersonalityInstance(
            definition=definition,
            memory_service=memory_service,
            emotion_engine=emotion_engine,
            life_service=life_service,
        )

        # Set emotional baseline
        for emotion, intensity in definition.emotional_baseline.items():
            emotion_engine.add_emotion(emotion, intensity)

        self._instances[personality_id.lower()] = instance
        logger.info(f"Initialized personality: {definition.name}")

        return instance

    def get_instance(self, personality_id: str) -> Optional[PersonalityInstance]:
        """Get a personality instance by ID."""
        return self._instances.get(personality_id.lower())

    def remove_personality(self, personality_id: str) -> bool:
        """Tear down a personality and drop it from the manager.

        This is the teardown path for `initialize_personality`. Without it the
        instance dict only ever grew, and every retained `PersonalityInstance`
        pinned a `LifeService` — whose `LifeScheduler` may still hold live tick
        jobs — for the life of the process.

        Returns True if a personality was removed, False if the id was unknown.
        """
        pid = personality_id.lower()
        instance = self._instances.pop(pid, None)
        if instance is None:
            return False

        life_service = getattr(instance, "life_service", None)
        if life_service is not None:
            try:
                life_service.stop()
            except Exception as e:
                logger.warning(f"Error stopping life service for '{pid}': {e}")

        if self._current_id == pid:
            self._current_id = None

        logger.info(f"Removed personality: {pid}")
        return True

    def get_current(self) -> Optional[PersonalityInstance]:
        """Get the current active personality instance, or None if unset."""
        if self._current_id is None:
            return None
        return self._instances.get(self._current_id)

    def set_current(self, personality_id: str) -> bool:
        """Set the current active personality."""
        pid = personality_id.lower()
        if pid in self._instances:
            self._current_id = pid
            logger.info(f"Switched to personality: {self._instances[pid].definition.name}")
            return True
        return False

    @property
    def current_id(self) -> Optional[str]:
        """Get the current personality ID, or None until `set_current` succeeds."""
        return self._current_id

    @property
    def current_name(self) -> str:
        """Get the current personality name."""
        instance = self.get_current()
        return instance.definition.name if instance else "Unknown"

