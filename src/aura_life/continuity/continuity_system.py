"""
Continuity Engine

Runs on slower cycles (daily/weekly/monthly) to build long-term meaning:
- Anniversary awareness: track and remember meaningful dates
- Growth journal: periodic snapshots comparing past and present
- Relationship milestones: detect firsts and turning points
- Temporal context: layered time awareness
"""

import json
from datetime import datetime
from typing import Dict, List, Optional

from ..models import (
    Anniversary,
    GrowthSnapshot,
    LifeChapter,
    RelationshipMilestone,
)

logger = __import__("logging").getLogger(__name__)

# Milestone detection patterns
MILESTONE_PATTERNS = {
    "first_vulnerability": {
        "name": "First vulnerability",
        "description": "The first time she shared something truly personal",
    },
    "first_disagreement": {
        "name": "First disagreement",
        "description": "The first real disagreement — and they got through it",
    },
    "first_inside_joke": {
        "name": "First inside joke",
        "description": "Something only the two of them would understand",
    },
    "first_missed_you": {
        "name": "First 'I missed you'",
        "description": "Genuinely missing someone after time apart",
    },
    "first_hundred_messages": {
        "name": "100 messages",
        "description": "A hundred conversations — they really talk",
    },
}


class ContinuitySystem:
    """Tracks long-term narrative threads across days, weeks, months."""

    def __init__(self):
        self._anniversaries: List[Anniversary] = []
        self._growth_snapshots: List[GrowthSnapshot] = []
        self._milestones: List[RelationshipMilestone] = []
        self._life_chapters: List[LifeChapter] = []
        self._milestones_detected: set = set()  # Track which milestones have been detected
        self._last_daily_tick: Optional[datetime] = None
        self._last_weekly_tick: Optional[datetime] = None
        self._last_monthly_tick: Optional[datetime] = None

    # ============= Daily Tick =============

    def daily_tick(self) -> List[str]:
        """Run daily continuity checks. Returns list of notable events."""
        now = datetime.now()
        events = []

        # Check anniversaries
        today_str = now.strftime("%m-%d")
        for ann in self._anniversaries:
            if ann.date.endswith(today_str):
                ann.emotional_weight = min(1.0, ann.emotional_weight + 0.05)
                events.append(f"anniversary: {ann.name}")

        self._last_daily_tick = now
        return events

    # ============= Weekly Tick =============

    def weekly_tick(self, skill_levels: Dict[str, float],
                    identity_facets: Dict[str, float],
                    relationship_trust: float) -> Optional[GrowthSnapshot]:
        """Run weekly growth snapshot. Returns snapshot if notable changes detected."""
        now = datetime.now()

        snapshot = GrowthSnapshot(
            date=now,
            skill_levels=dict(skill_levels),
            identity_facets=dict(identity_facets),
            relationship_trust=relationship_trust,
        )

        # Compare with last snapshot to detect notable changes
        if self._growth_snapshots:
            last = self._growth_snapshots[-1]
            changes = []

            # Skill improvements
            for skill, level in skill_levels.items():
                old_level = last.skill_levels.get(skill, 0.0)
                if level - old_level > 0.05:
                    changes.append(f"improved at {skill}")

            # Identity shifts
            for facet, strength in identity_facets.items():
                old_strength = last.identity_facets.get(facet, 0.0)
                if strength - old_strength > 0.1:
                    changes.append(f"growing more {facet}")

            # Trust change
            if relationship_trust - last.relationship_trust > 0.05:
                changes.append("trust deepening")

            snapshot.notable_changes = changes

        self._growth_snapshots.append(snapshot)
        # Keep last 20 snapshots
        if len(self._growth_snapshots) > 20:
            self._growth_snapshots = self._growth_snapshots[-20:]

        self._last_weekly_tick = now
        return snapshot if snapshot.notable_changes else None

    # ============= Monthly Tick (Life Chapter Synthesis) =============

    def monthly_tick(self, activity_summary: Dict[str, int],
                     dominant_mood: str, avg_energy: float,
                     goals_completed: List[str], goals_abandoned: List[str],
                     identity_shifts: List[str]) -> Optional[LifeChapter]:
        """Synthesize a life chapter from the past month's accumulated data.

        Called once per month. Generates a narrative chapter title and summary
        from growth snapshots, milestones, activities, and emotional arcs.
        Returns the chapter or None if too little data.
        """
        now = datetime.now()

        # Need at least some data to synthesize
        if not self._growth_snapshots and not activity_summary and not self._milestones:
            self._last_monthly_tick = now
            return None

        # Gather turning points from recent milestones and notable changes
        turning_points = []
        recent_milestones = [m for m in self._milestones
                             if m.date and (now - m.date).days <= 35]
        for m in recent_milestones:
            turning_points.append(m.name)

        # Growth changes from recent snapshots
        recent_snapshots = [s for s in self._growth_snapshots
                            if s.date and (now - s.date).days <= 35]
        for snap in recent_snapshots:
            turning_points.extend(snap.notable_changes)

        if goals_completed:
            turning_points.extend([f"completed: {g}" for g in goals_completed[:3]])
        if goals_abandoned:
            turning_points.extend([f"let go of: {g}" for g in goals_abandoned[:2]])

        # Determine dominant emotions from mood + milestones
        dominant_emotions = [dominant_mood] if dominant_mood != "neutral" else []
        if recent_milestones:
            dominant_emotions.append("growth")
        if goals_completed:
            dominant_emotions.append("accomplishment")
        if avg_energy < 0.3:
            dominant_emotions.append("exhaustion")

        # Generate chapter title from most notable theme
        title = self._generate_chapter_title(
            activity_summary, dominant_mood, turning_points,
            goals_completed, identity_shifts,
        )

        # Generate summary
        summary = self._generate_chapter_summary(
            activity_summary, dominant_mood, avg_energy,
            turning_points, goals_completed, goals_abandoned,
        )

        # Close previous chapter
        if self._life_chapters:
            self._life_chapters[-1].period_end = now

        chapter = LifeChapter(
            title=title,
            period_start=now.replace(day=1),
            summary=summary,
            turning_points=turning_points[:5],
            dominant_emotions=dominant_emotions[:4],
        )
        self._life_chapters.append(chapter)

        # Keep last 12 chapters (1 year of monthly synthesis)
        if len(self._life_chapters) > 12:
            self._life_chapters = self._life_chapters[-12:]

        self._last_monthly_tick = now
        logger.info(f"Life chapter synthesized: \"{title}\"")
        return chapter

    def _generate_chapter_title(self, activity_summary: Dict[str, int],
                                mood: str, turning_points: List[str],
                                goals_completed: List[str],
                                identity_shifts: List[str]) -> str:
        """Generate a short evocative chapter title from the month's themes."""
        # Priority: milestones > goals > identity shifts > top activity > mood
        if goals_completed:
            return f"the month {goals_completed[0]}"
        if turning_points:
            for tp in turning_points:
                if tp.startswith("completed:") or tp.startswith("let go of:"):
                    continue
                return f"when {tp.lower()}"
        if identity_shifts:
            return f"becoming more {identity_shifts[0]}"
        if activity_summary:
            top_activity = max(activity_summary, key=activity_summary.get)
            return f"the {top_activity} month"
        # Mood-based fallback
        mood_titles = {
            "content": "a quiet, good stretch",
            "blue": "the heavy weeks",
            "restless": "the restless month",
            "bright": "everything clicking",
            "raw": "when everything felt too much",
        }
        return mood_titles.get(mood, "another month, passing")

    def _generate_chapter_summary(self, activity_summary: Dict[str, int],
                                  mood: str, energy: float,
                                  turning_points: List[str],
                                  goals_completed: List[str],
                                  goals_abandoned: List[str]) -> str:
        """Generate a 2-3 sentence chapter summary from data."""
        parts = []

        # Energy/mood sentence
        if energy < 0.3:
            parts.append("A low-energy stretch — dragging through most days.")
        elif energy > 0.7:
            parts.append("High energy this month — felt capable and present.")
        if mood == "blue":
            parts.append("The overall mood was heavy.")
        elif mood == "bright":
            parts.append("Generally bright and engaged.")
        elif mood == "restless":
            parts.append("A restless, searching period.")

        # Activity highlights
        if activity_summary:
            top_activities = sorted(activity_summary.items(), key=lambda x: x[1], reverse=True)[:3]
            activity_str = ", ".join(f"{a}" for a, _ in top_activities)
            parts.append(f"Spent most time: {activity_str}.")

        # Turning points
        notable = [tp for tp in turning_points if not tp.startswith("completed:") and not tp.startswith("let go of:")]
        if notable:
            parts.append(f"Notable moments: {'; '.join(notable[:3])}.")

        # Goals
        if goals_completed:
            parts.append(f"Accomplished: {', '.join(goals_completed[:2])}.")
        if goals_abandoned:
            parts.append(f"Let go of: {', '.join(goals_abandoned[:2])}.")

        return " ".join(parts) if parts else "A quiet month without much to note."

    def get_recent_chapters(self, limit: int = 3) -> List[LifeChapter]:
        """Get the most recent life chapters."""
        return self._life_chapters[-limit:]

    def get_current_chapter(self) -> Optional[LifeChapter]:
        """Get the current (most recent) life chapter."""
        return self._life_chapters[-1] if self._life_chapters else None

    # ============= Backstory / Founding Chapter =============

    def seed_backstory(self, background: str = "", contradictions: str = "",
                       what_makes_unique: str = "", persona_name: str = ""):
        """Create the founding chapter of the life narrative from profile backstory.

        Called once during first initialization when no chapters exist yet.
        Uses raw profile data to create an origin chapter.
        """
        if self._life_chapters:
            return  # Already have chapters, don't overwrite

        parts = []
        if background:
            parts.append(background)
        if what_makes_unique:
            parts.append(what_makes_unique)
        if contradictions:
            parts.append(f"Internal tensions: {contradictions}")

        if not parts:
            return  # No backstory data available

        summary = " ".join(parts)
        # Truncate if too long
        if len(summary) > 500:
            summary = summary[:497] + "..."

        chapter = LifeChapter(
            title=f"before — who {persona_name or 'she'} was",
            period_start=None,  # No specific start date for backstory
            summary=summary,
            turning_points=[],
            dominant_emotions=["origin"],
        )
        self._life_chapters.append(chapter)
        logger.info(f"Seeded founding backstory chapter for {persona_name}")

    # ============= Anniversaries =============

    def add_anniversary(self, name: str, date_str: str, yearly: bool = True):
        """Add an anniversary date (MM-DD format)."""
        for ann in self._anniversaries:
            if ann.name == name:
                return  # Already tracked
        self._anniversaries.append(Anniversary(
            name=name,
            date=date_str,
            yearly=yearly,
            first_occurrence=datetime.now(),
        ))

    def get_upcoming_anniversaries(self, days_ahead: int = 7) -> List[Anniversary]:
        """Get anniversaries coming up in the next N days."""
        now = datetime.now()
        upcoming = []
        for ann in self._anniversaries:
            try:
                # Parse MM-DD
                parts = ann.date.split("-")
                if len(parts) >= 2:
                    month = int(parts[-2])
                    day = int(parts[-1])
                    this_year = now.replace(month=month, day=day, hour=0, minute=0, second=0, microsecond=0)
                    if this_year < now:
                        this_year = this_year.replace(year=now.year + 1)
                    if 0 <= (this_year - now).days <= days_ahead:
                        upcoming.append(ann)
            except (ValueError, IndexError):
                continue
        return upcoming

    # ============= Relationship Milestones =============

    def check_milestones(self, interaction_count: int,
                          vulnerability_openness: float,
                          inside_joke_count: int) -> Optional[RelationshipMilestone]:
        """Check if any relationship milestones have been reached."""
        # First 100 messages
        if (interaction_count >= 100 and
                "first_hundred_messages" not in self._milestones_detected):
            return self._record_milestone("first_hundred_messages")

        # First inside joke
        if (inside_joke_count >= 1 and
                "first_inside_joke" not in self._milestones_detected):
            return self._record_milestone("first_inside_joke")

        # First vulnerability (openness > 0.5)
        if (vulnerability_openness > 0.5 and
                "first_vulnerability" not in self._milestones_detected):
            return self._record_milestone("first_vulnerability")

        return None

    def _record_milestone(self, key: str) -> RelationshipMilestone:
        """Record a detected milestone."""
        pattern = MILESTONE_PATTERNS[key]
        milestone = RelationshipMilestone(
            name=pattern["name"],
            description=pattern["description"],
            date=datetime.now(),
            detected_retrospectively=True,
        )
        self._milestones.append(milestone)
        self._milestones_detected.add(key)
        logger.info(f"Relationship milestone: {milestone.name}")
        return milestone

    # ============= Export / Serialize =============

    def export_state(self) -> dict:
        """Structured export for pipeline digest."""
        result = {}

        # Upcoming anniversaries
        upcoming = self.get_upcoming_anniversaries(7)
        if upcoming:
            result["upcoming_anniversaries"] = [
                {"name": a.name, "date": a.date}
                for a in upcoming[:2]
            ]

        # Recent growth
        if self._growth_snapshots:
            last = self._growth_snapshots[-1]
            if last.notable_changes:
                result["recent_growth"] = last.notable_changes[:3]

        # Milestones
        if self._milestones:
            result["milestones_count"] = len(self._milestones)
            result["latest_milestone"] = self._milestones[-1].name

        # Current life chapter
        current = self.get_current_chapter()
        if current:
            result["current_chapter"] = {
                "title": current.title,
                "summary": current.summary,
            }

        return result

    def get_status(self) -> dict:
        """Status for API/debugging."""
        return {
            "anniversaries_count": len(self._anniversaries),
            "growth_snapshots_count": len(self._growth_snapshots),
            "life_chapters_count": len(self._life_chapters),
            "current_chapter": self._life_chapters[-1].title if self._life_chapters else None,
            "milestones": [m.name for m in self._milestones],
            "milestones_detected": list(self._milestones_detected),
            "last_daily_tick": self._last_daily_tick.isoformat() if self._last_daily_tick else None,
            "last_weekly_tick": self._last_weekly_tick.isoformat() if self._last_weekly_tick else None,
            "last_monthly_tick": self._last_monthly_tick.isoformat() if self._last_monthly_tick else None,
        }

    def to_dict(self) -> dict:
        """Serialize for DB storage."""
        return {
            "anniversaries": json.dumps([
                {
                    "name": a.name, "date": a.date,
                    "emotional_weight": a.emotional_weight,
                    "yearly": a.yearly,
                    "first_occurrence": a.first_occurrence.isoformat() if a.first_occurrence else None,
                }
                for a in self._anniversaries
            ]),
            "growth_snapshots": json.dumps([
                {
                    "date": s.date.isoformat() if s.date else None,
                    "skill_levels": s.skill_levels,
                    "identity_facets": s.identity_facets,
                    "relationship_trust": s.relationship_trust,
                    "notable_changes": s.notable_changes,
                }
                for s in self._growth_snapshots[-10:]  # Keep last 10 for storage
            ]),
            "milestones": json.dumps([
                {
                    "name": m.name, "description": m.description,
                    "emotional_weight": m.emotional_weight,
                    "date": m.date.isoformat() if m.date else None,
                    "detected_retrospectively": m.detected_retrospectively,
                }
                for m in self._milestones
            ]),
            "milestones_detected": json.dumps(list(self._milestones_detected)),
            "life_chapters": json.dumps([
                {
                    "title": c.title, "summary": c.summary,
                    "period_start": c.period_start.isoformat() if c.period_start else None,
                    "period_end": c.period_end.isoformat() if c.period_end else None,
                    "turning_points": c.turning_points,
                    "dominant_emotions": c.dominant_emotions,
                }
                for c in self._life_chapters
            ]),
            "last_daily_tick": self._last_daily_tick.isoformat() if self._last_daily_tick else None,
            "last_weekly_tick": self._last_weekly_tick.isoformat() if self._last_weekly_tick else None,
            "last_monthly_tick": self._last_monthly_tick.isoformat() if self._last_monthly_tick else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContinuitySystem":
        """Deserialize from DB."""
        system = cls()
        if not data:
            return system

        # Anniversaries
        raw = data.get("anniversaries", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            items = []
        system._anniversaries = [
            Anniversary(
                name=a.get("name", ""),
                date=a.get("date", ""),
                emotional_weight=a.get("emotional_weight", 0.3),
                yearly=a.get("yearly", True),
                first_occurrence=datetime.fromisoformat(a["first_occurrence"]) if a.get("first_occurrence") else None,
            )
            for a in items
        ]

        # Growth snapshots
        raw = data.get("growth_snapshots", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            items = []
        system._growth_snapshots = [
            GrowthSnapshot(
                date=datetime.fromisoformat(s["date"]) if s.get("date") else None,
                skill_levels=s.get("skill_levels", {}),
                identity_facets=s.get("identity_facets", {}),
                relationship_trust=s.get("relationship_trust", 0.0),
                notable_changes=s.get("notable_changes", []),
            )
            for s in items
        ]

        # Milestones
        raw = data.get("milestones", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            items = []
        system._milestones = [
            RelationshipMilestone(
                name=m.get("name", ""),
                description=m.get("description", ""),
                emotional_weight=m.get("emotional_weight", 0.5),
                date=datetime.fromisoformat(m["date"]) if m.get("date") else None,
                detected_retrospectively=m.get("detected_retrospectively", True),
            )
            for m in items
        ]

        # Milestones detected set
        raw = data.get("milestones_detected", "[]")
        try:
            detected = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            detected = []
        system._milestones_detected = set(detected)

        # Life chapters
        raw = data.get("life_chapters", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            items = []
        system._life_chapters = [
            LifeChapter(
                title=c.get("title", ""),
                summary=c.get("summary", ""),
                period_start=datetime.fromisoformat(c["period_start"]) if c.get("period_start") else None,
                period_end=datetime.fromisoformat(c["period_end"]) if c.get("period_end") else None,
                turning_points=c.get("turning_points", []),
                dominant_emotions=c.get("dominant_emotions", []),
            )
            for c in items
        ]

        # Timestamps
        ts = data.get("last_daily_tick")
        if ts:
            try:
                system._last_daily_tick = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                pass
        ts = data.get("last_weekly_tick")
        if ts:
            try:
                system._last_weekly_tick = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                pass
        ts = data.get("last_monthly_tick")
        if ts:
            try:
                system._last_monthly_tick = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                pass

        return system
