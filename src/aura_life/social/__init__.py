"""Social system module — NPC interactions and social events, and the
households of personas who live together."""

from .household import Household
from .social_system import SocialSystem

__all__ = ["SocialSystem", "Household"]
