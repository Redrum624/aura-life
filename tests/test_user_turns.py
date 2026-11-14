"""The user's turn (humanness Task 16a, spec section 4.8).

``LifeService.observe_user_turn`` is the whole turn (ruling T16-R1): what
``on_user_message`` always did, plus her appraisal of the user's emotion --
concern for a sad user, amusement at a playful one, hurt or irritation (by her
volatility) at hostility aimed at her, never a copy of it -- and her trust in
the user, which hostility now lowers. The text fallback analyzer
(``TextEmotionAnalyzer``) matches on word boundaries, reads a 3-token negation
window and curly apostrophes, and knows a basic French lexicon; the
conversation keyword map goes through the same tokenizer (ruling T16-R4).
"""

import random
from datetime import datetime, timedelta

import pytest

from aura_life import LifeService
from aura_life.emotion.text_emotion_analyzer import TextEmotionAnalyzer
from aura_life.identity.identity_system import IdentitySystem
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.world import WorldEnvironment

#: A world instant far from any host's wall clock, so a stamp read from
#: ``datetime.now()`` can never pass for it.
WORLD_NOW = datetime(2031, 3, 4, 9, 30)


class RecordingEngine:
    """A host EmotionEngine that keeps what it was given."""

    def __init__(self):
        self.added = []

    def add_emotion(self, name, intensity):
        self.added.append((name, intensity))


def _service(tmp_path, name="ada", traits=None, seed=5, **kwargs) -> LifeService:
    clock = {"now": WORLD_NOW}
    definition = PersonalityDefinition(id=name, traits=dict(traits)) if traits else None
    svc = LifeService(
        db_path=str(tmp_path / f"{name}.db"), persona_id=name, definition=definition,
        world_environment=WorldEnvironment(now=lambda: clock["now"], seed=seed),
        rng=random.Random(seed), **kwargs,
    )
    svc._test_clock = clock
    return svc


def _labels(text, **kwargs):
    return {spike.emotion for spike in TextEmotionAnalyzer.analyze_text(text, **kwargs)}


def _trust(svc) -> float:
    return svc._identity.get_user_perception().trust_level


# ----------------------------------------------------------------------
# The text fallback analyzer
# ----------------------------------------------------------------------

def test_a_negated_happy_reads_no_joyful_label():
    assert "joyful" not in _labels("I'm not happy about this at all")
    assert "joyful" in _labels("I'm happy about this")


@pytest.mark.parametrize("greeting", ["good night", "Good morning!", "ok I should sleep. good night",
                                      "good evening", "bonne nuit", "bonne journée"])
def test_a_greeting_is_not_a_feeling(greeting):
    """Task 39: "good night" held the word "good" (content, 0.4), so every
    evening's goodbye read as the user feeling good -- and left her a memory
    "They told you something good" (seen in a measured conversation). A
    greeting is a formula: its words are not weighed one by one."""
    assert _labels(greeting) == set(), _labels(greeting)


def test_good_outside_a_greeting_still_reads():
    assert "content" in _labels("that sounds good to me")
    assert "content" in _labels("good morning, I feel good today")


def test_a_goodbye_leaves_no_memory_of_good_news(tmp_path):
    svc = _service(tmp_path)
    result = svc.observe_user_turn("ok I should sleep. good night")
    assert result["valence"] == 0.0 and result["persona_emotions"] == {}, result
    assert _conversation_episodes(svc) == []


def test_a_negated_love_reads_no_loving_label():
    assert "loving" not in _labels("honestly I don't love it")
    assert "loving" in _labels("honestly I love it")


def test_french_sadness_reads_sad():
    assert TextEmotionAnalyzer.get_dominant_emotion("Je suis tellement triste aujourd'hui")[0] == "sad"


def test_a_french_negation_reads_no_sadness():
    assert "sad" not in _labels("je ne suis pas triste")
    assert "loving" not in _labels("je ne t'aime pas")
    assert "loving" in _labels("je t'aime")


def test_curly_apostrophes_read_as_straight_ones():
    assert "loving" not in _labels("honestly I don’t love it")
    assert "eager" in _labels("I can’t wait")


def test_a_phrase_matches_on_word_boundaries_only():
    assert "lonely" not in _labels("they dismiss you every time")
    assert "lonely" in _labels("I miss you every time")


def test_the_negation_window_is_three_tokens():
    assert "joyful" not in _labels("not one bit happy")        # 3 tokens on
    assert "joyful" in _labels("not one tiny bit happy")       # 4 tokens on
    assert "joyful" in _labels("not today. happy though")      # a clause ends it


def test_but_ends_a_negation_and_a_phrases_own_negator_negates_nothing():
    assert "joyful" in _labels("not great but happy")
    assert "joyful" in _labels("I can't believe how happy I am")   # "can't" is the phrase's


def test_french_elisions_negate_and_amplifiers_strengthen():
    assert "loving" not in _labels("je n'aime pas ça")
    assert "sad" not in _labels("il n'est plus triste")
    tone = TextEmotionAnalyzer.get_emotional_tone
    assert tone("tellement triste")["sad"] > tone("triste")["sad"]


def test_a_turn_is_aimed_at_her_when_it_speaks_to_her():
    from aura_life.emotion.text_emotion_analyzer import addresses_listener

    assert addresses_listener("I hate you") and addresses_listener("je te déteste")
    assert addresses_listener("t'es nul")
    assert not addresses_listener("I hate my job")


def test_english_words_spelled_like_french_ones_are_not_aimed_at_her(tmp_path):
    """"ton" and "ta" (French "your") are English words too ("a ton of",
    "ta" for thanks): no listener words, as the French lexicon leaves out
    "surprise". So frustration at something else stays concern, and her
    trust still rises, whatever the turn's language."""
    from aura_life.emotion.text_emotion_analyzer import addresses_listener

    assert not addresses_listener("I hate this, I have a ton of homework")
    assert not addresses_listener("cheers, ta")
    for language in (None, "en"):
        result = _service(tmp_path, f"ton-{language}").observe_user_turn(
            "I hate this, I have a ton of homework", language=language)
        assert result["trust_delta"] > 0.0
        assert set(result["persona_emotions"]) == {"concerned"}


def test_an_english_turn_has_no_french_listener_words(tmp_path):
    """With ``language="en"`` a French listener word, or "t'", is no
    listener word; the turn's language reaches the check."""
    from aura_life.emotion.text_emotion_analyzer import addresses_listener

    assert not addresses_listener("tu es nul", language="en")
    assert not addresses_listener("t'es nul", language="en")
    assert addresses_listener("tu es nul") and addresses_listener("I hate you", language="en")
    english = _service(tmp_path, "en").observe_user_turn("tu es nul", emotions={"hostile": 0.8}, language="en")
    either = _service(tmp_path, "any").observe_user_turn("tu es nul", emotions={"hostile": 0.8})
    assert english["trust_delta"] > 0.0 > either["trust_delta"]


def test_english_only_reads_no_french():
    assert "sad" not in _labels("tellement triste", language="en")


def test_every_french_entry_reads_as_an_english_one():
    from aura_life.emotion import text_emotion_analyzer as tea

    assert tea.FRENCH_KEYWORDS and all(v in tea.EMOTION_KEYWORDS for v in tea.FRENCH_KEYWORDS.values())
    assert all(v in tea.EMOTION_PHRASES or v in tea.EMOTION_KEYWORDS for v in tea.FRENCH_PHRASES.values())
    assert "lonely" in _labels("tu me manques")


# ----------------------------------------------------------------------
# The appraisal: she appraises the user's emotion, never copies it
# ----------------------------------------------------------------------

def test_the_turn_returns_its_appraisal(tmp_path):
    result = _service(tmp_path).observe_user_turn("I'm so sad today")
    assert set(result) == {"valence", "persona_emotions", "trust_delta"}
    assert result["valence"] < 0.0
    assert isinstance(result["trust_delta"], float)


def test_a_sad_user_raises_her_concern_not_her_sadness_for_warmth_08(tmp_path):
    engine = RecordingEngine()
    warm = _service(tmp_path, "warm", traits={"warmth": 0.8}, emotion_engine=engine)
    felt = warm.observe_user_turn("I'm so sad today")["persona_emotions"]
    assert felt.get("concerned", 0.0) > 0.0
    assert "sad" not in felt
    names = [name for name, _intensity in engine.added]
    assert "concerned" in names and "sad" not in names
    cold = _service(tmp_path, "cold", traits={"warmth": 0.2})
    assert felt["concerned"] > cold.observe_user_turn("I'm so sad today")["persona_emotions"]["concerned"]


def test_hostility_at_her_hurts_or_irritates_her_by_volatility(tmp_path):
    calm = _service(tmp_path, "calm", traits={"volatility": 0.1}).observe_user_turn("I hate you")
    hot = _service(tmp_path, "hot", traits={"volatility": 0.9}).observe_user_turn("I hate you")
    calm_felt, hot_felt = calm["persona_emotions"], hot["persona_emotions"]
    assert calm_felt["hurt"] > calm_felt.get("irritated", 0.0)
    assert hot_felt["irritated"] > hot_felt.get("hurt", 0.0)
    assert "hostile" not in calm_felt and "hostile" not in hot_felt


def test_a_playful_user_amuses_her(tmp_path):
    felt = _service(tmp_path).observe_user_turn("haha that was so funny")["persona_emotions"]
    assert felt.get("amused", 0.0) > 0.0 and "playful" not in felt


def test_a_glad_user_warms_her(tmp_path):
    felt = _service(tmp_path).observe_user_turn("that's amazing")["persona_emotions"]
    assert felt.get("warm", 0.0) > 0.0 and "amazed" not in felt


def test_with_nothing_felt_the_valence_is_the_hosts_sentiment(tmp_path):
    assert _service(tmp_path, "a").observe_user_turn("ok", sentiment=-0.4)["valence"] == pytest.approx(-0.4)
    assert _service(tmp_path, "b").observe_user_turn("ok")["valence"] == 0.0
    # she feels concern, so the valence is hers, not the host's
    felt = _service(tmp_path, "c").observe_user_turn("I'm so sad today", sentiment=0.9)["valence"]
    assert felt < 0.0


def test_a_hosts_anger_words_are_hostility_as_the_analyzers_labels_are(tmp_path):
    """A host's ``emotions`` naming anger with the vocabulary's words
    ("angry", "irritated") or another word the analyzer reads as anger
    ("enraged" is its "furious") is hostility at her, as the analyzer's own
    label "mad" is: hurt and irritation, and her trust falls by as much."""
    mad = _service(tmp_path, "mad").observe_user_turn("I'm angry at you", emotions={"mad": 0.9})
    assert mad["trust_delta"] < 0.0
    for name in ("angry", "irritated", "enraged"):
        result = _service(tmp_path, name).observe_user_turn("I'm angry at you", emotions={name: 0.9})
        assert result["persona_emotions"] == pytest.approx(mad["persona_emotions"]), name
        assert result["trust_delta"] == pytest.approx(mad["trust_delta"]), name
    # the analyzer's own labels are read as before: hostile exactly when listed
    from aura_life.emotion import text_emotion_analyzer as tea
    from aura_life.emotion.user_appraisal import HOSTILE_EMOTIONS, is_hostile

    labels = {label for label, _ in [*tea.EMOTION_KEYWORDS.values(), *tea.EMOTION_PHRASES.values()]}
    assert {label for label in labels if is_hostile(label)} == HOSTILE_EMOTIONS


@pytest.mark.parametrize("text, relief, meaningful", [
    ("I hate you", 0.05, False),       # hostility aimed at her: contact only
    ("I hate my job", 0.15, True),     # hostility at something else
    ("I'm so sad today", 0.15, True),
])
def test_hostility_at_her_is_contact_not_a_meaningful_interaction(tmp_path, text, relief, meaningful):
    """Ruling T16a-R3: a turn of hostility aimed at her relieves her
    loneliness by plain contact's 0.05 (``AffectSystem.on_social_interaction(
    meaningful=False)``) and leaves her last meaningful interaction where it
    was; every other turn stays meaningful (0.15, stamped at the world
    instant). No new amount."""
    svc = _service(tmp_path)
    loneliness = svc._affect._loneliness
    loneliness.level = 0.6
    before = loneliness.last_meaningful_interaction
    svc._test_clock["now"] = WORLD_NOW + timedelta(hours=3)
    svc.observe_user_turn(text)
    assert loneliness.level == pytest.approx(0.6 - relief)
    stamped = WORLD_NOW + timedelta(hours=3)
    assert loneliness.last_meaningful_interaction == (stamped if meaningful else before)


def test_a_hosts_warm_words_are_warmth_as_the_analyzers_labels_are(tmp_path):
    """Task 16b step 0.3: a host's ``emotions`` naming warmth with a word the
    analyzer reads as one of its warm labels ("grateful" is its "thankful",
    "affectionate" and "warm" its "loving", "connected" its "intimate") is
    warmth for her, as the label itself is: the same feelings, and her trust
    rises by as much."""
    loving = _service(tmp_path, "loving").observe_user_turn("thank you", emotions={"loving": 0.9})
    plain = _service(tmp_path, "plain").observe_user_turn("thank you")["trust_delta"]
    assert loving["trust_delta"] > plain
    for name in ("grateful", "affectionate", "warm", "connected"):
        result = _service(tmp_path, name).observe_user_turn("thank you", emotions={name: 0.9})
        assert result["persona_emotions"] == pytest.approx(loving["persona_emotions"]), name
        assert result["trust_delta"] == pytest.approx(loving["trust_delta"]), name
    # the analyzer's own labels are read as before: warm exactly when listed
    from aura_life.emotion import text_emotion_analyzer as tea
    from aura_life.emotion.user_appraisal import WARM_EMOTIONS, is_warm

    labels = {label for label, _ in [*tea.EMOTION_KEYWORDS.values(), *tea.EMOTION_PHRASES.values()]}
    assert {label for label in labels if is_warm(label)} == WARM_EMOTIONS


def test_a_hosts_warm_word_with_no_vocabulary_name_warms_her_as_its_label_does(tmp_path):
    """Task 16b fix round 1 (W1): a host's warm word that is no vocabulary
    name ("love", "adore", "caring": the analyzer's "loving") is warmth for
    what she feels too, not only for her trust (step 0.3: "for the appraisal
    and for trust"): she feels what its analyzer label makes her feel, and the
    episode carries it. Before, she felt nothing (the vocabulary read the
    name as neutral)."""
    from aura_life.emotion import text_emotion_analyzer as tea
    from aura_life.emotion.user_appraisal import appraise_user_turn, is_warm
    from aura_life.emotion.vocabulary import is_known, normalize

    words = sorted(w for w in tea.EMOTION_KEYWORDS if is_warm(normalize(w)) and not is_known(w))
    assert "love" in words and "adore" in words
    for word in words:
        own = appraise_user_turn({word: 0.9}, aimed_at_her=True)
        as_label = appraise_user_turn({tea.EMOTION_KEYWORDS[word][0]: 0.9}, aimed_at_her=True)
        assert own.emotions and own.emotions == pytest.approx(as_label.emotions), word
        assert own.warmth == as_label.warmth, word
    loving = _service(tmp_path, "loving").observe_user_turn("thank you", emotions={"loving": 0.9})
    svc = _service(tmp_path, "love")
    love = svc.observe_user_turn("thank you", emotions={"love": 0.9})
    assert love["persona_emotions"] and love["persona_emotions"] == pytest.approx(loving["persona_emotions"])
    assert love["trust_delta"] == pytest.approx(loving["trust_delta"])
    (episode,) = _conversation_episodes(svc)
    assert (episode.what, episode.emotion) == ("They said something sweet to you", "warm")


def test_a_turn_with_no_text_is_aimed_at_her(tmp_path):
    assert _service(tmp_path).observe_user_turn(emotions={"hostile": 0.8})["trust_delta"] < 0.0


def test_the_user_model_hears_the_users_strongest_emotion(tmp_path):
    seen = []

    class Model:
        def observe_message(self, text, at, emotion, intensity):
            seen.append((text, emotion, intensity))

    host = _service(tmp_path, "host", user_model_provider=lambda pid: Model())
    host.on_user_message("I had a rough day", "sad", 0.7)
    fallback = _service(tmp_path, "fallback", user_model_provider=lambda pid: Model())
    fallback.observe_user_turn("I'm so sad today")
    expected = TextEmotionAnalyzer.get_dominant_emotion("I'm so sad today")
    assert seen[0] == ("I had a rough day", "sad", 0.7)
    assert seen[1][:2] == ("I'm so sad today", expected[0])
    assert seen[1][2] == pytest.approx(expected[1])


def test_three_hostile_turns_lower_trust(tmp_path):
    svc = _service(tmp_path)
    before = _trust(svc)
    deltas = [svc.observe_user_turn("I hate you")["trust_delta"] for _ in range(3)]
    assert all(delta < 0.0 for delta in deltas)
    assert _trust(svc) == pytest.approx(before + sum(deltas))
    assert _trust(svc) < before


def test_hostility_at_something_else_does_not_lower_trust(tmp_path):
    svc = _service(tmp_path)
    before = _trust(svc)
    result = svc.observe_user_turn("I hate my job")
    assert result["trust_delta"] > 0.0 and _trust(svc) > before
    assert "concerned" in result["persona_emotions"]


def test_trust_rises_more_on_warmth_and_disclosure(tmp_path):
    plain = _service(tmp_path, "plain").observe_user_turn("ok")["trust_delta"]
    warm = _service(tmp_path, "warm").observe_user_turn("I love you")["trust_delta"]
    opened = _service(tmp_path, "opened").observe_user_turn("ok", disclosure=1.0)["trust_delta"]
    elsewhere = _service(tmp_path, "pizza").observe_user_turn("I love pizza")["trust_delta"]
    assert plain > 0.0
    assert warm > plain
    assert opened > plain
    assert elsewhere == pytest.approx(plain)   # warmth for something else is not for her


def test_trust_moves_by_amounts_taken_from_existing_ones(tmp_path):
    """Ruling T16-R3: no new number. A message adds 0.003 (what
    ``update_from_user_message`` always added); hostility at her takes a
    rejection's drain, disclosure adds a personal question's boost, warmth one
    more message's gain -- each times the turn's intensity, for a neutral
    persona (trust multiplier 1)."""
    from aura_life.identity.identity_system import IDENTITY_CONVERSATION_TRIGGERS as triggers

    message = 0.003
    hate = TextEmotionAnalyzer.get_emotional_tone("I hate you")["hostile"]
    love = TextEmotionAnalyzer.get_emotional_tone("I love you")["loving"]
    assert _service(tmp_path, "h").observe_user_turn("I hate you")["trust_delta"] == pytest.approx(
        message - triggers["rejection"]["trust_drain"] * hate)
    assert _service(tmp_path, "d").observe_user_turn("ok", disclosure=0.5)["trust_delta"] == pytest.approx(
        message + triggers["personal_question"]["trust_boost"] * 0.5)
    assert _service(tmp_path, "w").observe_user_turn("I love you")["trust_delta"] == pytest.approx(
        message + message * love)


def _conversation_episodes(svc):
    return [e for e in svc._memory.episodes if "conversation" in e.tags]


def test_a_turn_is_a_conversation_episode_with_her_appraisal(tmp_path):
    # Task 16b step 0 (ruling T16a-R2): the episode is a gist of what the turn
    # was to her and what it was about, no longer the user's words (16a
    # asserted the text was quoted in it).
    svc = _service(tmp_path)
    result = svc.observe_user_turn("I'm so sad today", topics=["work"])
    episodes = _conversation_episodes(svc)
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.what == "They told you about a hard time, talking about work"
    assert episode.at == WORLD_NOW
    assert "work" in episode.tags
    assert episode.emotion == "concerned"
    assert episode.valence == pytest.approx(result["valence"])


def test_a_turn_never_stores_the_users_words(tmp_path):
    """Ruling T16a-R2: a turn's episode is built from structured facts (who,
    the host's topics, what the turn was to her), never from its text: a
    number and a secret word in it reach no episode."""
    svc = _service(tmp_path)
    svc.observe_user_turn("I'm so sad, my code is 4821 and the word is swordfish")
    (episode,) = _conversation_episodes(svc)
    for stored in (episode.what, episode.gist(), " ".join(episode.tags)):
        assert "4821" not in stored and "swordfish" not in stored.lower()
    assert all("swordfish" not in e.what.lower() for e in svc._memory.episodes)


def test_only_a_turn_that_left_a_trace_is_remembered(tmp_path):
    """A neutral turn records nothing; one with topics, a disclosure or a
    feeling in her does, each worded for what it was to her."""
    assert _conversation_episodes(_with_turn(tmp_path, "neutral", "ok")) == []
    cases = {
        "talk": (("ok",), {"topics": ["the_weekend plans"]}, "They talked with you about the weekend plans"),
        "opened": (("ok",), {"disclosure": 0.6}, "They opened up to you"),
        "hostile": (("I hate you",), {}, "They lashed out at you"),
        "sweet": (("I love you",), {}, "They said something sweet to you"),
        "amused": (("haha that was so funny",), {}, "They made you laugh"),
        "glad": (("that's amazing",), {}, "They told you something good"),
    }
    for name, (args, kwargs, what) in cases.items():
        (episode,) = _conversation_episodes(_with_turn(tmp_path, name, *args, **kwargs))
        assert episode.what == what, name


def test_a_hosts_topics_given_as_one_string_are_one_topic(tmp_path):
    """Task 16b fix round 1 (T1): ``topics="work"`` is the topic "work", not
    the letters w, o, r and k (the recalled gist carries the topics since
    step 0.1)."""
    (episode,) = _conversation_episodes(_with_turn(tmp_path, "one", "ok", topics="work"))
    assert episode.what == "They talked with you about work"
    assert list(episode.tags) == ["conversation", "work"]
    (listed,) = _conversation_episodes(_with_turn(tmp_path, "listed", "ok", topics=["work"]))
    assert listed.what == episode.what and list(listed.tags) == list(episode.tags)


def _with_turn(tmp_path, name, *args, **kwargs):
    svc = _service(tmp_path, name)
    svc.observe_user_turn(*args, **kwargs)
    return svc


# ----------------------------------------------------------------------
# T16-R1: one entry path
# ----------------------------------------------------------------------

def _turn_state(svc):
    p = svc._identity.get_user_perception()
    return {
        "mood": (svc._affect.mood.valence, svc._affect.mood.arousal),
        "loneliness": svc._affect.loneliness.level,
        "trust": p.trust_level, "warmth": p.emotional_valence, "count": p.interaction_count,
        "expression": svc._expression._interaction_count,
        "absorbed": (svc._affect.empathy.current_absorbed_emotion, svc._affect.empathy.absorbed_intensity),
        "episodes": [(e.what, e.emotion, e.valence, e.tags) for e in svc._memory.episodes],
        "last_turn": svc.last_user_turn_at,
    }


@pytest.mark.parametrize("args, emotions", [
    (("you're so sweet, I love you",), None),
    (("I had a rough day", "sad", 0.7), {"sad": 0.7}),
    (("I hate you",), None),           # contact, not meaningful (ruling T16a-R3)
])
def test_on_user_message_is_observe_user_turn(tmp_path, args, emotions):
    old, new = _service(tmp_path, "old"), _service(tmp_path, "new")
    count = _turn_state(old)["count"]
    assert old.on_user_message(*args) is None
    new.observe_user_turn(args[0], emotions=emotions)
    assert _turn_state(old) == _turn_state(new)
    assert _turn_state(old)["count"] == count + 1
    assert len(_turn_state(old)["episodes"]) == 1


# ----------------------------------------------------------------------
# T16-R2: the last user turn, on the world clock, saved with her state
# ----------------------------------------------------------------------

def test_the_last_user_turn_is_a_world_instant_saved_and_loaded(tmp_path):
    svc = _service(tmp_path)
    assert svc.last_user_turn_at is None
    svc._test_clock["now"] = WORLD_NOW + timedelta(hours=2)
    svc.observe_user_turn("hello")
    assert svc.last_user_turn_at == WORLD_NOW + timedelta(hours=2)
    svc._save_state()
    again = _service(tmp_path)
    again._load_state()
    assert again.last_user_turn_at == WORLD_NOW + timedelta(hours=2)


def test_an_old_save_loads_with_no_last_user_turn():
    saved = IdentitySystem().to_dict()
    saved.pop("last_user_turn_at", None)
    assert IdentitySystem.from_dict(saved).last_user_turn_at is None


def test_a_service_save_from_before_16a_loads_with_no_last_user_turn(tmp_path):
    """The service's own old-save path (``LifeService._load_identity``): a
    database saved before Task 16a has no ``life_user_turn_state`` table. It
    loads with no last user turn (``None``, as before any turn) and the rest
    of her identity as it was saved (her trust, lowered by three turns)."""
    import contextlib
    import sqlite3

    svc = _service(tmp_path)
    for _ in range(3):
        svc.observe_user_turn("I hate you")
    svc._save_state()
    with contextlib.closing(sqlite3.connect(str(tmp_path / "ada.db"))) as conn:
        conn.execute("DROP TABLE life_user_turn_state")
        conn.commit()
    again = _service(tmp_path)
    fresh_trust = _trust(again)
    again._load_state()
    assert again.last_user_turn_at is None
    assert _trust(again) == pytest.approx(_trust(svc)) and _trust(again) < fresh_trust


# ----------------------------------------------------------------------
# T16-R4: the keyword map through the analyzer's tokenizer
# ----------------------------------------------------------------------

def _triggers(svc, text):
    seen = []
    for name in ("_identity", "_desire_system", "_affect", "_cognitive", "_energy", "_drive"):
        engine = getattr(svc, name)
        original = engine.process_conversation_trigger

        def spy(trigger, _original=original, _name=name):
            seen.append((_name, trigger))
            return _original(trigger)

        engine.process_conversation_trigger = spy
    svc.observe_user_turn(text)
    return seen


def test_a_negated_keyword_triggers_nothing(tmp_path):
    assert ("_identity", "affirmation") in _triggers(_service(tmp_path, "a"), "I love you")
    negated = _triggers(_service(tmp_path, "b"), "I don't love you")
    assert ("_identity", "affirmation") not in negated
    assert ("_desire_system", "romantic_conversation") not in negated


def test_a_keyword_ending_in_a_negator_still_negates_what_follows(tmp_path):
    seen = _triggers(_service(tmp_path), "that's not love")
    assert ("_cognitive", "defending_opinion") in seen        # "that's not" itself
    assert ("_identity", "affirmation") not in seen


def test_a_keyword_matches_on_word_boundaries_only(tmp_path):
    seen = _triggers(_service(tmp_path), "where is my glove")
    assert ("_identity", "affirmation") not in seen
    assert ("_desire_system", "romantic_conversation") not in seen


def test_a_curly_apostrophe_keyword_still_triggers(tmp_path):
    assert ("_affect", "criticism") in _triggers(_service(tmp_path), "you’re wrong")


# ----------------------------------------------------------------------
# T16-R5: her empathy hears the user's emotion and her trust
# ----------------------------------------------------------------------

def test_the_users_emotion_reaches_her_empathy_with_her_trust(tmp_path):
    svc = _service(tmp_path)
    calls = []
    original = svc._affect.on_user_emotion_detected

    def spy(emotion, intensity, trust_level):
        calls.append((emotion, intensity, trust_level, _trust(svc)))
        return original(emotion, intensity, trust_level)

    svc._affect.on_user_emotion_detected = spy
    svc.observe_user_turn("I'm so sad today")
    expected = TextEmotionAnalyzer.get_dominant_emotion("I'm so sad today")
    assert len(calls) == 1
    emotion, intensity, trust_level, trust_then = calls[0]
    assert (emotion, intensity) == (expected[0], pytest.approx(expected[1]))
    assert trust_level == trust_then
    assert svc._affect.empathy.current_absorbed_emotion == "sad"
