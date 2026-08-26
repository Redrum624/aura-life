"""In-memory per-persona conversation-session state.

Tracks an active chat session so LifeService can decide when to send a
sign-off / wrap-up message (active -> inactive transition) and how insistent
it should be (escalation). Deliberately NOT persisted: losing it on restart is
fine — a new session simply starts fresh.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# A real exchange (not a one-line "hi") before a wrap-up is allowed.
WRAPUP_MIN_MESSAGES = 3
# Quiet time after the last user message before the wrap-up fires.
WRAPUP_QUIET_MINUTES = 12
# Gap (or a new calendar day) that starts a fresh session and resets escalation.
WRAPUP_SESSION_RESET_MINUTES = 30
# Cap on how insistent repeated sign-offs get.
WRAPUP_MAX_ESCALATION = 2


@dataclass
class ConversationSession:
    msg_count: int = 0
    escalation: int = 0
    wrapup_sent: bool = False
    day: str = ""

    def on_user_message(self, now: datetime, prev_user_at: Optional[datetime]) -> None:
        """Update session state on a new user message.

        `prev_user_at` is the timestamp of the PREVIOUS user message (None if
        this is the first ever / first after restart).
        """
        gap_min = ((now - prev_user_at).total_seconds() / 60.0) if prev_user_at else 1e9
        day = now.strftime("%Y-%m-%d")
        if gap_min > WRAPUP_SESSION_RESET_MINUTES or self.day != day:
            # New session: fresh count, escalation, and sent-flag.
            self.msg_count = 0
            self.escalation = 0
            self.wrapup_sent = False
            self.day = day
        elif self.wrapup_sent:
            # She signed off, but they pulled her back in the same session ->
            # next sign-off is more insistent.
            self.escalation = min(self.escalation + 1, WRAPUP_MAX_ESCALATION)
            self.wrapup_sent = False
        self.msg_count += 1

    def wrapup_context(
        self, now: datetime, last_user_at: Optional[datetime], is_asleep_now: bool
    ) -> Optional[dict]:
        """Return {'escalation': int} when a sign-off should fire now, else None."""
        if last_user_at is None:
            return None
        if self.msg_count < WRAPUP_MIN_MESSAGES:
            return None
        if self.wrapup_sent:
            return None
        if is_asleep_now:
            return None
        quiet_min = (now - last_user_at).total_seconds() / 60.0
        if quiet_min < WRAPUP_QUIET_MINUTES:
            return None
        return {"escalation": self.escalation}

    def note_wrapup_sent(self) -> None:
        self.wrapup_sent = True
