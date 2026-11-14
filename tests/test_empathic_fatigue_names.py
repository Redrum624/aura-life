"""Empathic fatigue keeps the eight names it has always listed.

The emotion vocabulary gives every name a valence, but empathic fatigue from a
user's detected emotion stays on ``EMPATHIC_FATIGUE_EMOTIONS`` rather than
widening to every unpleasant name.
"""

from aura_life.affect.affect_system import EMPATHIC_FATIGUE_EMOTIONS, AffectSystem


def test_the_fatigue_set_is_the_original_eight():
    assert EMPATHIC_FATIGUE_EMOTIONS == {
        "sad", "anxious", "frustrated", "angry", "lonely", "hurt", "overwhelmed", "raw",
    }


def test_a_listed_heavy_emotion_tires_her_and_an_unlisted_one_does_not():
    listed = AffectSystem()
    listed.on_user_emotion_detected("sad", 0.9, trust_level=1.0)
    assert listed._empathy.empathic_fatigue > 0.0

    unlisted = AffectSystem()
    unlisted.on_user_emotion_detected("disappointed", 0.9, trust_level=1.0)
    assert unlisted._empathy.empathic_fatigue == 0.0
