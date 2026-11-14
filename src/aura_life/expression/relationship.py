"""The user over time: relationship depth and absence (humanness Task 16b,
spec section 4.8: "Relationship depth comes from reciprocity and time and can
regress. Absence has a course by ``attachment_style``.").

Depth
=====

Depth runs 0..1 and sets the relationship stage (the names stay ``early``,
``comfortable``, ``deep``, ruling T16-R6): the deepest stage whose
:data:`STAGE_DEPTHS` it has reached. It moves on the user's turns and her
shares, never per tick:

* time -- each world day with a user turn (a contact day) adds
  ``CONTACT_DAY_GAIN x (1 - depth)``;
* reciprocity -- a disclosure deepens the bond only when it answers one from
  the other side. The user's ``disclosure`` (0..1, ``observe_user_turn``)
  and hers (a life event or shareable she told them, ``mark_shared``: a whole
  one, :data:`HER_DISCLOSURE`) each first answer what the other side left
  open; the part answered adds ``DISCLOSURE_GAIN x answered x (1 - depth)``,
  the rest stays open (at most :data:`OPEN_DISCLOSURE_CAP` a side);
* silence -- past :data:`REGRESSION_AFTER_DAYS` days without a user turn it
  regresses: ``depth x (1 - REGRESSION_PER_DAY) ** (silent days - 7)``,
  read at any instant from the world instant of the last user turn
  (``LifeService.last_user_turn_at``, ruling T16-R2) and kept on her next
  turn.

An old save (a stage from a message count, no depth) loads to the depth its
stage begins at, :data:`STAGE_DEPTHS` (ruling T16-R6).

Absence
=======

Hours since the user's last turn, from :data:`ABSENCE_AFTER_HOURS` on, are an
``after_absence`` state (a ``STATE_KEYS`` key; Task 18 renders it with her
``state_expressions``, ruling T16-R7). Its intensity rises from 0 at
:data:`ABSENCE_AFTER_HOURS` to the style's gain at :data:`ABSENCE_FULL_HOURS`
and stays there; what she feels follows her ``attachment_style``
(:data:`ATTACHMENT_COURSES`): secure, glad and curious; anxious, worried in
the course's first half and hurt in its second; avoidant, she notices and
stays cool. When the user comes back, the absence that just ended stays her
state while that conversation goes on (turns less than
:data:`IN_CONVERSATION_MINUTES` apart): ``ongoing`` is then False.

Every number, and where it comes from
=====================================

========================  =========  ==========================================
Value                     Is         From
========================  =========  ==========================================
REGRESSION_AFTER_DAYS     7 days     the Task 16 brief ("it regresses after 7
                                     days without contact")
STAGE_DEPTHS              0, 1/3,    chosen: three equal bands (the spec and
                          2/3        the brief give none; the old stages were
                                     50 and 200 messages, ``STAGE_THRESHOLDS``)
CONTACT_DAY_GAIN          0.05       chosen: a month of daily contact alone
                                     reaches deep (2/3 at about 22 days)
DISCLOSURE_GAIN           0.1        chosen: a disclosure answered counts
                                     twice a contact day
REGRESSION_PER_DAY        0.05       CONTACT_DAY_GAIN: a silent day past the
                                     seventh undoes about what a day of
                                     contact adds
HER_DISCLOSURE            1.0        chosen: what she shares is a whole one
OPEN_DISCLOSURE_CAP       1.0        chosen: one whole disclosure a side is
                                     banked at most
ABSENCE_AFTER_HOURS       8 h        ``ExpressionSystem.get_connection_context``
                                     ("It's been a while since you last
                                     talked" past 8 hours)
ABSENCE_FULL_HOURS        168 h      REGRESSION_AFTER_DAYS: the absence is at
                                     its full when the bond starts to fade
IN_CONVERSATION_MINUTES   20 min     ``LifeService.observe_user_turn``'s wake
                                     detection (a turn within 20 minutes of
                                     the last is mid-conversation)
ATTACHMENT_COURSES gains  anxious 1, chosen: the order attachment theory
                          secure 0.5, gives (anxious hyperactivates, avoidant
                          avoidant   deactivates)
                          0.25
SECOND_HALF_FROM          0.5        chosen: the course's second half (the
                                     anxious hurt) begins half way through
========================  =========  ==========================================

Nothing here reads a clock or draws randomness: the instants come in.
"""

from datetime import datetime
from typing import NamedTuple, Optional, Tuple

from ..emotion.user_appraisal import GLAD_EMOTION

#: The stages, shallowest first, and the depth each begins at.
STAGE_DEPTHS = {"early": 0.0, "comfortable": 1.0 / 3.0, "deep": 2.0 / 3.0}
STAGES = tuple(STAGE_DEPTHS)

REGRESSION_AFTER_DAYS = 7.0
CONTACT_DAY_GAIN = 0.05
DISCLOSURE_GAIN = 0.1
REGRESSION_PER_DAY = CONTACT_DAY_GAIN
HER_DISCLOSURE = 1.0
#: The most one side's unanswered disclosures add up to.
OPEN_DISCLOSURE_CAP = 1.0

ABSENCE_AFTER_HOURS = 8.0
ABSENCE_FULL_HOURS = REGRESSION_AFTER_DAYS * 24.0
IN_CONVERSATION_MINUTES = 20.0
#: Where in the course (0..1) its second half's feelings begin.
SECOND_HALF_FROM = 0.5

#: attachment style -> (how strongly the absence shows at its full, what she
#: feels in the course's first half, in its second). Every feeling is a
#: vocabulary name (``aura_life.emotion.vocabulary``).
ATTACHMENT_COURSES = {
    "secure": (0.5, (GLAD_EMOTION, "curious"), (GLAD_EMOTION, "curious")),
    "anxious": (1.0, ("worried",), ("hurt",)),
    "avoidant": (0.25, ("indifferent",), ("indifferent",)),
}
#: An unset or unknown ``attachment_style`` reads as this one.
DEFAULT_ATTACHMENT_STYLE = "secure"


def stage_for(depth: float) -> str:
    """The deepest stage whose :data:`STAGE_DEPTHS` ``depth`` has reached."""
    reached = STAGES[0]
    for stage in STAGES:
        if depth >= STAGE_DEPTHS[stage]:
            reached = stage
    return reached


def regressed(depth: float, silent_days: float) -> float:
    """``depth`` after ``silent_days`` without a user turn: unchanged up to
    :data:`REGRESSION_AFTER_DAYS`, then ``(1 - REGRESSION_PER_DAY)`` per day
    past it."""
    past = silent_days - REGRESSION_AFTER_DAYS
    if past <= 0.0:
        return depth
    return depth * (1.0 - REGRESSION_PER_DAY) ** past


def silent_days(now: datetime, last_turn_at: Optional[datetime]) -> float:
    """Days from the last user turn to ``now`` (0 with no turn yet)."""
    if last_turn_at is None:
        return 0.0
    return max(0.0, (now - last_turn_at).total_seconds() / 86400.0)


def attachment_style_of(value) -> str:
    """A definition's ``attachment_style`` as one of
    :data:`ATTACHMENT_COURSES`' keys (:data:`DEFAULT_ATTACHMENT_STYLE` when
    unset or unknown)."""
    style = str(value or "").strip().lower()
    return style if style in ATTACHMENT_COURSES else DEFAULT_ATTACHMENT_STYLE


class AfterAbsence(NamedTuple):
    """Her ``after_absence`` state (ruling T16-R7: computed, not rendered)."""
    #: How long the user was away, in hours.
    hours: float
    #: How strongly it shows, 0..1.
    intensity: float
    #: What she feels (vocabulary names).
    feelings: Tuple[str, ...]
    #: The style its course followed.
    attachment_style: str
    #: True while the user is still away; False in the conversation that
    #: ended it.
    ongoing: bool

    def as_dict(self) -> dict:
        """The state as plain data, for an export."""
        return {
            "hours": round(self.hours, 2),
            "intensity": round(self.intensity, 3),
            "feelings": list(self.feelings),
            "attachment_style": self.attachment_style,
            "ongoing": self.ongoing,
        }


def after_absence(hours: float, attachment_style: str, *, ongoing: bool) -> Optional[AfterAbsence]:
    """The ``after_absence`` state of an absence of ``hours`` for a persona
    of ``attachment_style`` (module docstring); ``None`` under
    :data:`ABSENCE_AFTER_HOURS`."""
    if hours < ABSENCE_AFTER_HOURS:
        return None
    style = attachment_style_of(attachment_style)
    gain, first_half, second_half = ATTACHMENT_COURSES[style]
    course = min(1.0, (hours - ABSENCE_AFTER_HOURS) / (ABSENCE_FULL_HOURS - ABSENCE_AFTER_HOURS))
    feelings = first_half if course < SECOND_HALF_FROM else second_half
    return AfterAbsence(float(hours), gain * course, tuple(feelings), style, ongoing)
