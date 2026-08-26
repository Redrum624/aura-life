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
        self._current_id: str = "samantha"

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

    def get_current(self) -> Optional[PersonalityInstance]:
        """Get the current active personality instance."""
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
    def current_id(self) -> str:
        """Get the current personality ID as string."""
        return self._current_id

    @property
    def current_name(self) -> str:
        """Get the current personality name."""
        instance = self.get_current()
        return instance.definition.name if instance else "Unknown"

