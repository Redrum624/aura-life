"""
Shadow Engine (Engine 15)

Tracks the persona's darker inner psychology and moral tension:
- Felt insecurity: diffuse unease, sense of (un)safety, self-doubt
- Temptation & transgression: the pull to cross a line, rebellion, intrusive themes
- Concealment: the weight of secrets, lying, masking / putting on a front
- Conscience: guilt, remorse, the urge to confess and clear the air
- Coping: healthy ↔ maladaptive (avoidant / self-soothing / destructive)
- Power: relational stance from submissive to dominant, felt superiority

Trait fields (rebelliousness, deceptiveness, dominance_disposition,
conscientiousness, vice_proneness) are seeded once at init from profile data
that is otherwise dead, and barely decay. The remaining fields are dynamic and
move each tick under stress, loneliness, mood, conflict, and intimacy.
"""

import json
import logging
import random
from datetime import datetime
from typing import Dict, List, Optional

from ..models import ShadowState

logger = logging.getLogger(__name__)


# ============= Clamp Helpers =============

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _clamp11(x: float) -> float:
    return max(-1.0, min(1.0, x))


# ============= Decay / Recovery Rates =============

UNEASE_DECAY = 0.04             # pull toward rest each tick when nothing drives it
UNEASE_APPROACH = 0.25         # how fast unease moves toward its driven target
UNEASE_REST = 0.15             # resting floor of unease
SAFETY_RECOVERY = 0.03         # felt_safety drifts back toward its rest
SAFETY_REST = 0.7             # resting level of felt_safety
DOUBT_APPROACH = 0.2

TRANSGRESSION_BUILD = 0.05      # how fast pressure accumulates from tension
TRANSGRESSION_DECAY = 0.06     # pressure bleeds off when calm
TEMPTATION_APPROACH = 0.3

CONCEALMENT_SUSTAIN = 0.01     # secrets keep their weight alive
CONCEALMENT_DECAY = 0.03       # concealment fades when nothing to hide
GUILT_FROM_CONCEALMENT = 0.15  # guilt accrual = load * conscientiousness * this
GUILT_DECAY = 0.02            # only bleeds off once concealment is essentially gone
REMORSE_APPROACH = 0.15
CONFESS_BUILD = 0.05           # urge_to_confess accrual factor
CONFESS_DECAY = 0.03

MASKING_APPROACH = 0.2
POWER_DRIFT = 0.05             # power_stance drifts toward its disposition
SUPERIORITY_DRIFT = 0.05      # superiority drifts back toward its seed

TRAIT_INERTIA = 0.999         # trait seeds barely move (near-frozen)

# --- Shame (about the SELF; distinct from guilt about an act) ---
SHAME_BASELINE = 0.15         # chronic resting level when nothing drives it
SHAME_APPROACH = 0.2          # how fast shame moves toward its driven target
SHAME_EASE = 0.06             # relief per tick from intimacy + felt_safety
SHAME_PULL_DOWN = 0.04        # how hard shame drags autonomy / power_stance down each tick

# --- Inhibition (restraint; recovers as the alcohol/impulse effect wears off) ---
INHIBITION_RECOVERY = 0.08    # drift back toward baseline each tick
DRINK_INHIBITION_DROP = 0.35  # how far a drinking/partying activity drops restraint
LOW_INHIBITION = 0.4          # below this she reads as "uninhibited"

# --- Attention-seeking (drive for attention / validation) ---
ATTN_APPROACH = 0.2           # how fast it moves toward its driven target
ATTN_DECAY = 0.05             # decay toward baseline when she feels secure
ATTN_VALIDATION_RELIEF = 0.12  # how much a compliment satisfies the drive

# --- Autonomy (own person vs pushover) ---
AUTONOMY_APPROACH = 0.15      # tracks toward its baseline each tick
AUTONOMY_PULL = 0.05          # how hard low autonomy reinforces a submissive stance


# ============= Thresholds =============

INTRUSIVE_PRESSURE_ON = 0.45   # pressure above which an intrusive theme is picked
INTRUSIVE_PRESSURE_OFF = 0.25  # pressure below which the theme clears
INTRUSIVE_TEMPTATION_HI = 0.5  # temptation considered "high" for losing the fight
LOW_CONSCIENTIOUSNESS = 0.4    # below this, conscience offers weak resistance
MALADAPTIVE_STRAIN = 1.0       # (unease + stress) above this risks bad coping
MALADAPTIVE_VICE = 0.4         # vice_proneness above this enables bad coping
DESTRUCTIVE_VICE = 0.7         # vice_proneness above this can go destructive

# Export visibility thresholds (omit fields at rest)
EXP_UNEASE = 0.35
EXP_SAFETY = 0.5
EXP_TEMPTATION = 0.3
EXP_GUILT = 0.2
EXP_SHAME = 0.3
EXP_CONFESS = 0.3
EXP_CONCEALMENT = 0.2
EXP_MASKING = 0.4
EXP_POWER = 0.3
EXP_SUPERIORITY = 0.4
EXP_INHIBITION_LOW = 0.4       # below this, flag "uninhibited"
EXP_ATTENTION = 0.45          # above this, flag attention-seeking
EXP_AUTONOMY_LOW = 0.4        # below this, flag "deferential/pushover"
EXP_AUTONOMY_HI = 0.7         # above this, flag "self-assured"
ATTN_ACTING_OUT = 0.6        # attention_seeking above this + low inhibition → "look at me"


# ============= Seeding Keyword Maps =============

# core_traits keyword → effect on trait seeds
REBEL_TRAITS = {"rebellious", "defiant", "stubborn", "contrarian"}
SUBMISSIVE_TRAITS = {"submissive", "deferential", "meek", "compliant"}
DOMINANT_TRAITS = {"dominant", "assertive", "commanding", "domineering"}

# core_traits keyword → effect on inhibition seed
UNINHIBITED_TRAITS = {"impulsive", "wild", "uninhibited", "reckless"}
RESERVED_TRAITS = {"reserved", "proper", "shy"}

# core_traits keyword → effect on attention_seeking seed
ATTENTION_TRAITS = {"dramatic", "extroverted", "flirty", "validation", "needy"}
PRIVATE_TRAITS = {"private", "reserved"}

# core_traits keyword → effect on autonomy seed
AUTONOMY_TRAITS = {"independent", "assertive", "strong-willed", "stubborn"}

# substance frequency → vice contribution
SUBSTANCE_FREQUENCY_WEIGHTS = {
    "heavy": 0.30, "daily": 0.30, "frequent": 0.22,
    "moderate": 0.15, "regular": 0.15, "social": 0.08,
    "occasional": 0.06, "rare": 0.02, "none": 0.0,
}


class ShadowSystem:
    """Tracks the persona's dark psychology: unease, temptation, concealment,
    conscience, coping, and relational power."""

    # Upper bound on retained secrets, matching the cap on
    # `recent_transgressions` in `record_transgression`.
    MAX_SECRETS = 10

    def __init__(self, behavioral_tendencies: Optional[dict] = None,
                 character_defects: Optional[list] = None,
                 struggles: Optional[list] = None,
                 intrusive_thought_themes: Optional[list] = None,
                 substance_tendencies: Optional[dict] = None,
                 core_traits: Optional[list] = None,
                 initial_state: Optional[ShadowState] = None):
        self._intrusive_pool: List[str] = list(intrusive_thought_themes or [])
        # Per-persona resting levels for the dimensions that drift toward a
        # baseline (set by _capture_baselines after seed/deserialize).
        self._shame_baseline: float = SHAME_BASELINE
        self._attention_baseline: float = 0.2
        self._autonomy_baseline: float = 0.5
        if initial_state is not None:
            self._state = initial_state
            self._capture_baselines()
        else:
            self._state = ShadowState()
            self._seed_from_profile(
                behavioral_tendencies or {},
                character_defects or [],
                struggles or [],
                substance_tendencies or {},
                core_traits or [],
            )

    # ============= Seeding =============

    def _seed_from_profile(self, behavioral_tendencies: dict, character_defects: list,
                           struggles: list, substance_tendencies: dict, core_traits: list):
        """Seed trait fields from otherwise-dead profile data."""
        s = self._state

        # --- behavioral_tendencies: dict name -> 0..1 ---
        bt = {str(k).lower(): float(v) for k, v in behavioral_tendencies.items()}
        pride = bt.get("pride", 0.0)
        dishonesty = bt.get("dishonesty", 0.0)
        lust = bt.get("lust", 0.0)
        negativity = bt.get("negativity", 0.0)
        if pride:
            s.superiority += pride * 0.6
            s.dominance_disposition += pride * 0.5
        if dishonesty:
            s.deceptiveness += dishonesty
        if lust:
            s.vice_proneness += lust * 0.4
        if negativity:
            s.unease += negativity * 0.4
            s.felt_safety -= negativity * 0.2

        # --- substance_tendencies: dict name -> frequency str ---
        for _name, freq in substance_tendencies.items():
            weight = SUBSTANCE_FREQUENCY_WEIGHTS.get(str(freq).strip().lower(), 0.0)
            s.vice_proneness += weight

        # --- character_defects: list of strings ---
        defects = " ".join(str(d).lower() for d in character_defects)
        if "people-pleasing" in defects or "people pleasing" in defects:
            s.dominance_disposition -= 0.3
            s.power_stance -= 0.3
            s.masking += 0.2
        if "overthinking" in defects:
            s.doubt += 0.2
            s.unease += 0.15
        if "pride" in defects or "superiority" in defects:
            s.superiority += 0.2

        # --- struggles: list of strings ---
        strug = " ".join(str(x).lower() for x in struggles)
        abandonment = "fear of abandonment" in strug or "abandonment" in strug
        if abandonment:
            s.felt_safety -= 0.3
            s.unease += 0.2
        if "shame" in strug:  # covers "chronic shame"
            s.conscientiousness += 0.2
            s.felt_safety -= 0.15
        if "anxiety" in strug:
            s.unease += 0.2

        # --- core_traits: list of strings ---
        traits = " ".join(str(t).lower() for t in core_traits)
        for kw in REBEL_TRAITS:
            if kw in traits:
                s.rebelliousness += 0.2
                break
        for kw in SUBMISSIVE_TRAITS:
            if kw in traits:
                s.dominance_disposition -= 0.25
                break
        for kw in DOMINANT_TRAITS:
            if kw in traits:
                s.dominance_disposition += 0.25
                break

        # --- Shame: "I am bad/unworthy" (about the self) ---
        # Seeded higher by shame-flavoured struggles and high conscientiousness.
        if any(k in strug for k in ("shame", "chronic shame", "worthless", "unworthy")):
            s.shame += 0.35
        s.shame += max(0.0, s.conscientiousness - 0.6) * 0.3
        s.shame = _clamp01(s.shame)

        # --- Inhibition: restraint (baseline from conscientiousness vs vice) ---
        cons_now = _clamp01(s.conscientiousness)
        vice_now = _clamp01(s.vice_proneness)
        s.inhibition = (cons_now + (1.0 - vice_now)) / 2.0
        if any(kw in traits for kw in UNINHIBITED_TRAITS):
            s.inhibition -= 0.25
        if any(kw in traits for kw in RESERVED_TRAITS):
            s.inhibition += 0.2
        s.inhibition = _clamp01(s.inhibition)

        # --- Attention-seeking: drive for attention / validation ---
        if any(kw in traits for kw in ATTENTION_TRAITS):
            s.attention_seeking += 0.3
        if any(kw in traits for kw in PRIVATE_TRAITS):
            s.attention_seeking -= 0.15
        # Paradoxical: deep shame + abandonment fear quietly fuels validation-seeking.
        if abandonment and s.shame > 0.4:
            s.attention_seeking += 0.15
        s.attention_seeking = _clamp01(s.attention_seeking)

        # --- Autonomy: own person (high) vs pushover/people-pleaser (low) ---
        if "people-pleasing" in defects or "people pleasing" in defects or "codependent" in defects:
            s.autonomy -= 0.25
        if abandonment:
            s.autonomy -= 0.15
        if any(kw in traits for kw in AUTONOMY_TRAITS):
            s.autonomy += 0.25
        s.autonomy = _clamp01(s.autonomy)

        # --- clamp & finalize ---
        s.unease = _clamp01(s.unease)
        s.felt_safety = _clamp01(s.felt_safety)
        s.doubt = _clamp01(s.doubt)
        s.masking = _clamp01(s.masking)
        s.superiority = _clamp01(s.superiority)
        s.rebelliousness = _clamp01(s.rebelliousness)
        s.deceptiveness = _clamp01(s.deceptiveness)
        s.conscientiousness = _clamp01(s.conscientiousness)
        s.vice_proneness = _clamp01(s.vice_proneness)
        s.dominance_disposition = _clamp11(s.dominance_disposition)
        # Power stance starts at the disposition lean.
        s.power_stance = s.dominance_disposition

        # Capture seeded baselines so the dynamics can drift toward each
        # persona's own resting level (not a one-size-fits-all constant).
        self._capture_baselines()

    def _capture_baselines(self):
        """Snapshot the per-persona resting levels of the new dimensions.
        The seeded value IS the chronic baseline each field drifts toward;
        SHAME_BASELINE acts as a global floor for personas with no shame seed.
        Called after seeding and after deserialization."""
        s = self._state
        self._shame_baseline = _clamp01(max(SHAME_BASELINE, s.shame))
        self._attention_baseline = _clamp01(s.attention_seeking)
        self._autonomy_baseline = _clamp01(s.autonomy)

    # ============= Tick =============

    def tick(self, stress: float = 0.0, loneliness: float = 0.0, mood: float = 0.5,
             conflict: float = 0.0, intimacy: float = 0.0, **kwargs) -> None:
        """Per-tick update of the shadow modules."""
        s = self._state
        low_mood = 1.0 - _clamp01(mood)

        # --- Inhibition: restraint recovers toward baseline (alcohol wears off) ---
        inhibition_baseline = _clamp01((s.conscientiousness + (1.0 - s.vice_proneness)) / 2.0)
        s.inhibition += (inhibition_baseline - s.inhibition) * INHIBITION_RECOVERY
        # Disinhibition factor: low restraint amplifies temptation / attention,
        # high restraint damps them. 1.0 at baseline, >1 when uninhibited.
        disinhibition = 1.0 + (LOW_INHIBITION - s.inhibition)

        # --- Unease & felt safety ---
        # Target driven by external pressure + felt insecurity + negativity baseline.
        unease_target = _clamp01(
            UNEASE_REST
            + 0.4 * stress
            + 0.3 * loneliness
            + 0.3 * (1.0 - s.felt_safety)
            + 0.2 * low_mood
        )
        if unease_target > s.unease:
            s.unease += (unease_target - s.unease) * UNEASE_APPROACH
        else:
            s.unease -= (s.unease - max(unease_target, UNEASE_REST)) * UNEASE_DECAY

        # felt_safety recovers slowly, eroded by current unease + conflict.
        s.felt_safety += (SAFETY_REST - s.felt_safety) * SAFETY_RECOVERY
        s.felt_safety -= (0.15 * s.unease + 0.25 * conflict)

        # --- Doubt ---
        doubt_target = _clamp01(0.4 * s.unease + 0.5 * low_mood)
        s.doubt += (doubt_target - s.doubt) * DOUBT_APPROACH

        # --- Transgression pressure & temptation ---
        # Low inhibition makes acting-out more likely; high inhibition restrains it.
        tension = 0.5 * s.unease + 0.5 * low_mood
        s.transgression_pressure += s.rebelliousness * tension * TRANSGRESSION_BUILD * disinhibition
        s.transgression_pressure -= TRANSGRESSION_DECAY * (1.0 - tension)
        s.transgression_pressure = _clamp01(s.transgression_pressure)

        temptation_target = _clamp01(
            (0.5 * s.transgression_pressure + 0.4 * s.vice_proneness + 0.2 * low_mood) * disinhibition
        )
        s.temptation += (temptation_target - s.temptation) * TEMPTATION_APPROACH

        # Intrusive theme management.
        if s.transgression_pressure >= INTRUSIVE_PRESSURE_ON and self._intrusive_pool and not s.intrusive_theme:
            s.intrusive_theme = self._pick_intrusive_theme()
        elif s.transgression_pressure < INTRUSIVE_PRESSURE_OFF:
            s.intrusive_theme = ""
        s.intrusive_winning = bool(
            s.intrusive_theme
            and s.temptation >= INTRUSIVE_TEMPTATION_HI
            and s.conscientiousness < LOW_CONSCIENTIOUSNESS
        )

        # --- Concealment ---
        if s.secrets:
            s.concealment_load = _clamp01(s.concealment_load + CONCEALMENT_SUSTAIN)
        else:
            s.concealment_load = max(0.0, s.concealment_load - CONCEALMENT_DECAY)

        # --- Conscience ---
        # Guilt accrues while there's something to feel guilty about, and only
        # bleeds off once concealment is essentially gone (so accrual and decay
        # don't cancel each other while a secret is still being carried).
        s.guilt += s.concealment_load * s.conscientiousness * GUILT_FROM_CONCEALMENT
        if s.concealment_load < 0.05:
            s.guilt = max(0.0, s.guilt - GUILT_DECAY)
        s.guilt = _clamp01(s.guilt)
        remorse_target = _clamp01(s.guilt * 0.8)
        s.remorse += (remorse_target - s.remorse) * REMORSE_APPROACH
        confess_target = _clamp01((s.concealment_load + s.guilt) * s.conscientiousness)
        if confess_target > s.urge_to_confess:
            s.urge_to_confess += (confess_target - s.urge_to_confess) * CONFESS_BUILD * 10
        else:
            s.urge_to_confess = max(0.0, s.urge_to_confess - CONFESS_DECAY)
        s.urge_to_confess = _clamp01(s.urge_to_confess)

        # --- Masking ---
        masking_target = _clamp01(0.6 * s.concealment_load + 0.4 * (1.0 - s.felt_safety) - 0.3 * intimacy)
        s.masking += (masking_target - s.masking) * MASKING_APPROACH

        # --- Shame (about the SELF; distinct from guilt about an act) ---
        # Drifts toward its chronic baseline; spikes with concealment, recent
        # transgressions and conflict; eased by intimacy and feeling safe.
        recent_tx = min(1.0, len(s.recent_transgressions) / 3.0)
        shame_target = _clamp01(
            self._shame_baseline
            + 0.3 * s.concealment_load
            + 0.25 * recent_tx
            + 0.25 * conflict
            - 0.2 * intimacy
            - 0.2 * s.felt_safety
        )
        s.shame += (shame_target - s.shame) * SHAME_APPROACH
        s.shame -= SHAME_EASE * (0.5 * intimacy + 0.5 * s.felt_safety)
        s.shame = _clamp01(s.shame)
        # Shame makes her shrink: it raises masking and drags autonomy/power down.
        if s.shame > 0.3:
            s.masking = _clamp01(s.masking + (s.shame - 0.3) * 0.2)

        # --- Attention-seeking (drive for attention / validation) ---
        # Rises with loneliness + low mood + feeling unsafe; decays toward the
        # seeded baseline when she feels secure / connected. Low inhibition
        # amplifies how strongly the drive expresses.
        attn_target = _clamp01(
            (self._attention_baseline
             + 0.35 * loneliness
             + 0.25 * low_mood
             + 0.2 * (1.0 - s.felt_safety)) * disinhibition
        )
        if attn_target > s.attention_seeking:
            s.attention_seeking += (attn_target - s.attention_seeking) * ATTN_APPROACH
        else:
            # Secure / connected → relax back toward baseline.
            relax = ATTN_DECAY * (0.5 + 0.5 * intimacy)
            s.attention_seeking += (self._attention_baseline - s.attention_seeking) * relax
        s.attention_seeking = _clamp01(s.attention_seeking)

        # --- Power / superiority ---
        # Superiority drifts toward a rest coupled to her dominance disposition.
        superiority_rest = _clamp01(0.1 + max(0.0, s.dominance_disposition) * 0.3)
        s.superiority += (superiority_rest - s.superiority) * SUPERIORITY_DRIFT

        # --- Autonomy (own person vs pushover) ---
        # Tracks toward baseline; lowered by submission, shame, masking; raised
        # by feeling safe with low unease. Low autonomy reinforces a submissive
        # stance (pushover); high autonomy supports a neutral/assertive one.
        submission = max(0.0, -s.power_stance)
        autonomy_target = _clamp01(
            self._autonomy_baseline
            - 0.3 * submission
            - 0.2 * s.shame
            - 0.15 * s.masking
            + 0.2 * (s.felt_safety - s.unease)
        )
        s.autonomy += (autonomy_target - s.autonomy) * AUTONOMY_APPROACH
        if s.shame > 0.3:
            s.autonomy = max(0.0, s.autonomy - SHAME_PULL_DOWN * (s.shame - 0.3))
        s.autonomy = _clamp01(s.autonomy)

        # Power stance: dominance lean + superiority, with autonomy/shame pulling
        # toward submission when she shrinks.
        power_target = _clamp11(s.dominance_disposition + s.superiority * 0.3)
        s.power_stance += (power_target - s.power_stance) * POWER_DRIFT
        # Low autonomy nudges toward a pushover stance; shame deepens it.
        s.power_stance -= AUTONOMY_PULL * (0.5 - s.autonomy) if s.autonomy < 0.5 else 0.0
        if s.shame > 0.3:
            s.power_stance -= SHAME_PULL_DOWN * (s.shame - 0.3)
        s.power_stance = _clamp11(s.power_stance)

        # --- Coping ---
        strain = s.unease + stress
        if strain >= MALADAPTIVE_STRAIN and s.vice_proneness >= MALADAPTIVE_VICE:
            s.maladaptive_coping_active = True
            s.coping_style = "destructive" if s.vice_proneness >= DESTRUCTIVE_VICE else "self_soothing"
        else:
            s.maladaptive_coping_active = False
            s.coping_style = "avoidant" if s.masking > 0.6 else "healthy"

        # --- Clamp & finalize ---
        self._clamp_dynamic()
        s.last_update = datetime.now()

    def _pick_intrusive_theme(self) -> str:
        """Deterministically rotate through the intrusive pool (no RNG dependency
        for the picked theme, so tick stays testable)."""
        if not self._intrusive_pool:
            return ""
        return self._intrusive_pool[0]

    def _clamp_dynamic(self):
        s = self._state
        s.unease = _clamp01(s.unease)
        s.felt_safety = _clamp01(s.felt_safety)
        s.doubt = _clamp01(s.doubt)
        s.temptation = _clamp01(s.temptation)
        s.inhibition = _clamp01(s.inhibition)
        s.attention_seeking = _clamp01(s.attention_seeking)
        s.transgression_pressure = _clamp01(s.transgression_pressure)
        s.concealment_load = _clamp01(s.concealment_load)
        s.masking = _clamp01(s.masking)
        s.guilt = _clamp01(s.guilt)
        s.shame = _clamp01(s.shame)
        s.remorse = _clamp01(s.remorse)
        s.urge_to_confess = _clamp01(s.urge_to_confess)
        s.autonomy = _clamp01(s.autonomy)
        s.superiority = _clamp01(s.superiority)
        s.power_stance = _clamp11(s.power_stance)

    # ============= Activity Hook =============

    def on_activity(self, activity_name: str) -> None:
        """React to an activity being performed."""
        if not activity_name:
            return
        name = activity_name.lower()
        s = self._state
        if any(k in name for k in ("drinking", "smoking", "binge", "drugs", "getting drunk",
                                   "drunk", "partying", "bar")):
            s.maladaptive_coping_active = True
            s.coping_style = "destructive" if s.vice_proneness >= DESTRUCTIVE_VICE else "self_soothing"
            s.temptation = max(0.0, s.temptation - 0.3)        # relief from indulging
            s.transgression_pressure = max(0.0, s.transgression_pressure - 0.2)
            s.guilt = _clamp01(s.guilt + 0.15)                  # ...but guilt after
            s.vice_proneness = _clamp01(s.vice_proneness + 0.02)
            # Alcohol/partying drops restraint sharply (recovers over later ticks)
            # and loosens her up to seek attention.
            s.inhibition = _clamp01(s.inhibition - DRINK_INHIBITION_DROP)
            s.attention_seeking = _clamp01(s.attention_seeking + 0.1)
        elif any(k in name for k in ("journaling", "meditating", "meditation", "therapy", "praying")):
            s.unease = max(0.0, s.unease - 0.15)
            s.doubt = max(0.0, s.doubt - 0.1)
            s.coping_style = "healthy"
            s.maladaptive_coping_active = False
            # Reflection restores composure and softens self-directed shame.
            s.inhibition = _clamp01(s.inhibition + 0.1)
            s.shame = max(0.0, s.shame - 0.1)
        elif any(k in name for k in ("venting", "confiding", "talking it out")):
            s.urge_to_confess = max(0.0, s.urge_to_confess - 0.2)
            s.concealment_load = max(0.0, s.concealment_load - 0.15)

    # ============= Message Hook =============

    def on_user_message(self, text: str = "") -> None:
        """React to a user message via keyword cues."""
        if not text:
            return
        t = text.lower()
        s = self._state

        # Confession / honesty cues → she comes clean.
        if any(k in t for k in ("honestly", "i have to tell you", "i lied", "truth is", "confess", "to be honest")):
            self.confess()

        # Reassurance / affection → safer, calmer.
        if any(k in t for k in ("i love you", "i'm here", "im here", "you're safe", "youre safe", "proud of you")):
            s.felt_safety = _clamp01(s.felt_safety + 0.15)
            s.unease = max(0.0, s.unease - 0.1)

        # Criticism / conflict → less safe, more uneasy.
        if any(k in t for k in ("you're wrong", "youre wrong", "disappointed", "angry", "stop it", "shut up")):
            s.unease = _clamp01(s.unease + 0.15)
            s.felt_safety = max(0.0, s.felt_safety - 0.15)

        # Shaming / contempt → "I am bad": shame up, less safe, she shrinks (autonomy down).
        if any(k in t for k in ("you should be ashamed", "pathetic", "disgusting", "embarrassing")):
            s.shame = _clamp01(s.shame + 0.2)
            s.felt_safety = max(0.0, s.felt_safety - 0.15)
            s.autonomy = max(0.0, s.autonomy - 0.1)

        # Affirmation / acceptance → shame eases, safer, she stands taller (autonomy up).
        if any(k in t for k in ("i accept you", "no judgment", "no judgement", "you're enough",
                                "youre enough", "i'm proud of you", "im proud of you", "you matter")):
            s.shame = max(0.0, s.shame - 0.2)
            s.felt_safety = _clamp01(s.felt_safety + 0.15)
            s.autonomy = _clamp01(s.autonomy + 0.1)

        # Validation of looks → attention partially satisfied + a small lift
        # (Shadow doesn't own mood, so the lift lands on felt_safety as the proxy).
        if any(k in t for k in ("you're so pretty", "youre so pretty", "look at you", "gorgeous")):
            s.attention_seeking = max(0.0, s.attention_seeking - ATTN_VALIDATION_RELIEF)
            s.felt_safety = _clamp01(s.felt_safety + 0.05)

        # User dominance cues → she submits (and yields autonomy), unless rebellious
        # / self-possessed (then she resists and pressure builds instead).
        if any(k in t for k in ("obey", "do as i say", "you're mine", "youre mine", "do what i say")):
            if s.rebelliousness >= 0.6 or s.autonomy >= 0.6:
                s.transgression_pressure = _clamp01(s.transgression_pressure + 0.2)
            else:
                s.power_stance = _clamp11(s.power_stance - 0.2)
                s.autonomy = max(0.0, s.autonomy - 0.1)

        # User submission cues → she takes the lead.
        if any(k in t for k in ("whatever you want", "you decide", "your call", "up to you")):
            s.power_stance = _clamp11(s.power_stance + 0.15)

    # ============= Helper Mutators =============

    # --- Chaos hooks: tiny clamped setters used by the chaos engine to nudge
    #     a single dimension. No dynamics logic — the next tick() reconciles
    #     these toward their targets like any other perturbation. ---

    def add_unease(self, amount: float) -> None:
        """Chaos hook: bump felt unease by `amount` (clamped to [0,1])."""
        self._state.unease = _clamp01(self._state.unease + amount)

    def add_temptation(self, amount: float) -> None:
        """Chaos hook: bump the pull toward transgression by `amount`."""
        self._state.temptation = _clamp01(self._state.temptation + amount)

    def add_guilt(self, amount: float) -> None:
        """Chaos hook: bump conscience-guilt by `amount` (clamped to [0,1])."""
        self._state.guilt = _clamp01(self._state.guilt + amount)

    def add_secret(self, secret: str) -> None:
        """Record something the persona is now hiding.

        Only `confess()` shrinks this list, and it is host-driven — a host that
        never calls it would otherwise grow the list, and the JSON blob it is
        serialized into, without bound.
        """
        if not secret:
            return
        self._state.secrets.append(secret)
        if len(self._state.secrets) > self.MAX_SECRETS:
            self._state.secrets = self._state.secrets[-self.MAX_SECRETS:]
        self._state.concealment_load = _clamp01(self._state.concealment_load + 0.2)

    def record_lie(self, text: str) -> None:
        """Record a lie she told; guilt scales with deceptiveness (the more
        natural lying is, the less it stings — inverse weighting)."""
        if not text:
            return
        s = self._state
        s.last_lie = text
        s.concealment_load = _clamp01(s.concealment_load + 0.15)
        guilt_weight = (1.0 - s.deceptiveness) * 0.2
        s.guilt = _clamp01(s.guilt + guilt_weight)

    def confess(self) -> None:
        """Clear the air: drop secrets, concealment, guilt, and the confess urge."""
        s = self._state
        s.secrets = []
        s.last_lie = ""
        s.concealment_load = max(0.0, s.concealment_load - 0.6)
        s.guilt = max(0.0, s.guilt - 0.4)
        s.urge_to_confess = max(0.0, s.urge_to_confess - 0.6)
        s.felt_safety = _clamp01(s.felt_safety + 0.1)

    def record_transgression(self, description: str) -> None:
        """Log an acted-out transgression and relieve the pressure behind it."""
        if not description:
            return
        s = self._state
        s.recent_transgressions.append(description)
        if len(s.recent_transgressions) > 10:
            s.recent_transgressions = s.recent_transgressions[-10:]
        s.transgression_pressure = max(0.0, s.transgression_pressure - 0.3)
        s.temptation = max(0.0, s.temptation - 0.3)
        s.guilt = _clamp01(s.guilt + 0.1 * s.conscientiousness)

    # ============= Export / Status =============

    def export_state(self) -> dict:
        """Structured export for pipeline digest. Omits fields at rest."""
        s = self._state
        out: dict = {}
        if s.unease > EXP_UNEASE:
            out["unease"] = round(s.unease, 2)
        if s.felt_safety < EXP_SAFETY:
            out["felt_unsafe"] = round(1.0 - s.felt_safety, 2)
        if s.doubt > EXP_UNEASE:
            out["doubt"] = round(s.doubt, 2)
        if s.temptation > EXP_TEMPTATION:
            out["temptation"] = round(s.temptation, 2)
        if s.inhibition < EXP_INHIBITION_LOW:
            out["uninhibited"] = round(1.0 - s.inhibition, 2)
        if s.attention_seeking > EXP_ATTENTION:
            out["attention_seeking"] = round(s.attention_seeking, 2)
        if s.intrusive_winning and s.intrusive_theme:
            out["intrusive"] = {"theme": s.intrusive_theme, "winning": True}
        if s.guilt > EXP_GUILT:
            out["guilt"] = round(s.guilt, 2)
        if s.shame > EXP_SHAME:
            out["shame"] = round(s.shame, 2)
        if s.remorse > EXP_GUILT:
            out["remorse"] = round(s.remorse, 2)
        if s.urge_to_confess > EXP_CONFESS:
            out["urge_to_confess"] = round(s.urge_to_confess, 2)
        if s.concealment_load > EXP_CONCEALMENT:
            out["concealment_load"] = round(s.concealment_load, 2)
        if s.masking > EXP_MASKING:
            out["masking"] = round(s.masking, 2)
        if abs(s.power_stance) > EXP_POWER:
            out["power_stance"] = round(s.power_stance, 2)
        if s.autonomy < EXP_AUTONOMY_LOW:
            out["deferential"] = round(1.0 - s.autonomy, 2)   # pushover / people-pleaser
        elif s.autonomy > EXP_AUTONOMY_HI:
            out["self_assured"] = round(s.autonomy, 2)
        if s.superiority > EXP_SUPERIORITY:
            out["superiority"] = round(s.superiority, 2)
        if s.maladaptive_coping_active:
            out["coping"] = s.coping_style
        if s.secrets:
            out["secrets_count"] = len(s.secrets)
        if s.recent_transgressions:
            out["recent_transgressions_count"] = len(s.recent_transgressions)
        # Derived: a "look at me" moment is primed when the validation drive is
        # high and restraint is low. Downstream code reads this to trigger an
        # attention-seeking picture.
        if s.attention_seeking > ATTN_ACTING_OUT and s.inhibition < LOW_INHIBITION:
            out["acting_out_for_attention"] = True
        return out

    def get_status(self) -> dict:
        """Fuller scalar dump for the status endpoint / debugging."""
        s = self._state
        return {
            "unease": round(s.unease, 3),
            "felt_safety": round(s.felt_safety, 3),
            "doubt": round(s.doubt, 3),
            "temptation": round(s.temptation, 3),
            "inhibition": round(s.inhibition, 3),
            "attention_seeking": round(s.attention_seeking, 3),
            "transgression_pressure": round(s.transgression_pressure, 3),
            "intrusive_theme": s.intrusive_theme,
            "intrusive_winning": s.intrusive_winning,
            "concealment_load": round(s.concealment_load, 3),
            "masking": round(s.masking, 3),
            "secrets_count": len(s.secrets),
            "last_lie": s.last_lie,
            "guilt": round(s.guilt, 3),
            "shame": round(s.shame, 3),
            "remorse": round(s.remorse, 3),
            "urge_to_confess": round(s.urge_to_confess, 3),
            "coping_style": s.coping_style,
            "maladaptive_coping_active": s.maladaptive_coping_active,
            "power_stance": round(s.power_stance, 3),
            "autonomy": round(s.autonomy, 3),
            "superiority": round(s.superiority, 3),
            "rebelliousness": round(s.rebelliousness, 3),
            "deceptiveness": round(s.deceptiveness, 3),
            "dominance_disposition": round(s.dominance_disposition, 3),
            "conscientiousness": round(s.conscientiousness, 3),
            "vice_proneness": round(s.vice_proneness, 3),
            "recent_transgressions": len(s.recent_transgressions),
        }

    # ============= Serialize =============

    def to_dict(self) -> dict:
        """Serialize full state (lists included) for DB storage."""
        s = self._state
        return {
            "unease": s.unease,
            "felt_safety": s.felt_safety,
            "doubt": s.doubt,
            "temptation": s.temptation,
            "inhibition": s.inhibition,
            "attention_seeking": s.attention_seeking,
            "transgression_pressure": s.transgression_pressure,
            "recent_transgressions": json.dumps(s.recent_transgressions),
            "intrusive_theme": s.intrusive_theme,
            "intrusive_winning": s.intrusive_winning,
            "concealment_load": s.concealment_load,
            "masking": s.masking,
            "secrets": json.dumps(s.secrets),
            "last_lie": s.last_lie,
            "guilt": s.guilt,
            "shame": s.shame,
            "remorse": s.remorse,
            "urge_to_confess": s.urge_to_confess,
            "coping_style": s.coping_style,
            "maladaptive_coping_active": s.maladaptive_coping_active,
            "power_stance": s.power_stance,
            "autonomy": s.autonomy,
            "superiority": s.superiority,
            "rebelliousness": s.rebelliousness,
            "deceptiveness": s.deceptiveness,
            "dominance_disposition": s.dominance_disposition,
            "conscientiousness": s.conscientiousness,
            "vice_proneness": s.vice_proneness,
            "last_update": s.last_update.isoformat() if s.last_update else None,
            "intrusive_pool": json.dumps(self._intrusive_pool),
            # Per-persona resting levels for shame/attention/autonomy.
            "shame_baseline": self._shame_baseline,
            "attention_baseline": self._attention_baseline,
            "autonomy_baseline": self._autonomy_baseline,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ShadowSystem":
        """Reconstruct a ShadowState (and wrap it) from a serialized dict."""
        if not data:
            return cls()

        def _list(raw):
            if isinstance(raw, list):
                return raw
            if isinstance(raw, str):
                try:
                    val = json.loads(raw)
                    return val if isinstance(val, list) else []
                except (json.JSONDecodeError, TypeError):
                    return []
            return []

        last_update = None
        if data.get("last_update"):
            try:
                last_update = datetime.fromisoformat(data["last_update"])
            except (ValueError, TypeError):
                last_update = None

        state = ShadowState(
            unease=data.get("unease", 0.2),
            felt_safety=data.get("felt_safety", 0.7),
            doubt=data.get("doubt", 0.2),
            temptation=data.get("temptation", 0.1),
            inhibition=data.get("inhibition", 0.6),
            attention_seeking=data.get("attention_seeking", 0.2),
            transgression_pressure=data.get("transgression_pressure", 0.0),
            recent_transgressions=_list(data.get("recent_transgressions", [])),
            intrusive_theme=data.get("intrusive_theme", ""),
            intrusive_winning=bool(data.get("intrusive_winning", False)),
            concealment_load=data.get("concealment_load", 0.0),
            masking=data.get("masking", 0.2),
            secrets=_list(data.get("secrets", [])),
            last_lie=data.get("last_lie", ""),
            guilt=data.get("guilt", 0.0),
            shame=data.get("shame", 0.1),
            remorse=data.get("remorse", 0.0),
            urge_to_confess=data.get("urge_to_confess", 0.0),
            coping_style=data.get("coping_style", "healthy"),
            maladaptive_coping_active=bool(data.get("maladaptive_coping_active", False)),
            power_stance=data.get("power_stance", 0.0),
            autonomy=data.get("autonomy", 0.5),
            superiority=data.get("superiority", 0.1),
            rebelliousness=data.get("rebelliousness", 0.3),
            deceptiveness=data.get("deceptiveness", 0.15),
            dominance_disposition=data.get("dominance_disposition", 0.0),
            conscientiousness=data.get("conscientiousness", 0.6),
            vice_proneness=data.get("vice_proneness", 0.2),
            last_update=last_update,
        )
        system = cls(initial_state=state)
        system._intrusive_pool = _list(data.get("intrusive_pool", []))
        # Restore the saved per-persona baselines (fall back to the values
        # _capture_baselines() derived from the restored state for old rows).
        system._shame_baseline = data.get("shame_baseline", system._shame_baseline)
        system._attention_baseline = data.get("attention_baseline", system._attention_baseline)
        system._autonomy_baseline = data.get("autonomy_baseline", system._autonomy_baseline)
        return system

    # ============= Properties =============

    @property
    def state(self) -> ShadowState:
        return self._state

    @property
    def intrusive_pool(self) -> List[str]:
        return self._intrusive_pool
