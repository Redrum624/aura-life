"""
Skills System (competencies that grow with practice)

Owns the persona's skill levels. ``practice()`` nudges a skill up and returns any
newly-crossed milestone texts; LifeService routes those into life events /
shareables (engines never call each other directly).

Engine contract: practice / on_user_message / export_state / get_status.
Persistence stays row-based in LifeService via the shared ``skills`` dict.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from ..models import SkillProgress


class SkillsSystem:
    """The persona's skills as a small engine over a name→SkillProgress dict."""

    def __init__(self, initial: Optional[Dict[str, SkillProgress]] = None):
        self._skills: Dict[str, SkillProgress] = initial if initial is not None else {}

    @property
    def skills(self) -> Dict[str, SkillProgress]:
        """The live dict (LifeService aliases this for load/save)."""
        return self._skills

    def levels(self) -> Dict[str, float]:
        return {name: round(sp.level, 3) for name, sp in self._skills.items()}

    def top_skills(self, n: int = 3) -> List[str]:
        ranked = sorted(self._skills.values(), key=lambda sp: sp.level, reverse=True)
        return [sp.skill_name for sp in ranked[:n] if sp.level > 0.05]

    def practice(
        self,
        skill_name: str,
        increment: float,
        milestones: Optional[List[Tuple[float, str]]] = None,
    ) -> List[str]:
        """Advance a skill; return newly-reached milestone texts (for LifeService
        to turn into shareables / life events)."""
        if skill_name not in self._skills:
            self._skills[skill_name] = SkillProgress(skill_name=skill_name)
        sk = self._skills[skill_name]
        old_level = sk.level
        sk.level = min(1.0, sk.level + increment)
        sk.last_practiced = datetime.now()

        reached: List[str] = []
        for threshold, text in (milestones or []):
            if old_level < threshold <= sk.level and text not in sk.milestones_reached:
                sk.milestones_reached.append(text)
                reached.append(text)
        return reached

    def on_user_message(self, text: str = "") -> None:
        return

    def export_state(self) -> dict:
        return {"top": self.top_skills(), "levels": self.levels()}

    def get_status(self) -> dict:
        return self.levels()
