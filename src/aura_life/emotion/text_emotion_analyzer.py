"""
Text Emotion Analyzer

Analyzes text for emotional content and provides real-time emotion signals.
"""
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class EmotionSpike:
    """Represents an emotion spike at a specific position in text."""
    position: float      # 0-1, where in the text this occurs
    emotion: str         # Detected emotion
    intensity: float     # 0-1 spike intensity
    word: str           # The word that triggered this


# Emotion keywords mapped to (emotion, base_intensity)
# Prioritizes tertiary (most specific) emotions for rich, varied displays
EMOTION_KEYWORDS: Dict[str, Tuple[str, float]] = {
    # ============= HAPPY FAMILY =============
    # Joyful (tertiary)
    "love": ("loving", 0.85),
    "amazing": ("amazed", 0.8),
    "wonderful": ("joyful", 0.8),
    "fantastic": ("joyful", 0.8),
    "overjoyed": ("joyful", 0.95),
    "delighted": ("joyful", 0.75),
    "ecstatic": ("joyful", 0.95),
    "joy": ("joyful", 0.8),
    "joyful": ("joyful", 0.8),
    "blissful": ("joyful", 0.85),
    "elated": ("joyful", 0.85),
    "exhilarated": ("joyful", 0.9),
    "radiant": ("joyful", 0.7),
    "beaming": ("joyful", 0.7),
    "gleeful": ("joyful", 0.75),
    # Excited (tertiary)
    "excited": ("excited", 0.75),
    "thrilled": ("excited", 0.85),
    "eager": ("eager", 0.7),
    "energetic": ("energetic", 0.7),
    "pumped": ("excited", 0.75),
    "stoked": ("excited", 0.8),
    "hyped": ("excited", 0.75),
    "exuberant": ("excited", 0.8),
    "enthusiastic": ("eager", 0.7),
    "anticipating": ("eager", 0.6),
    "looking forward": ("eager", 0.65),
    # Playful (tertiary)
    "playful": ("playful", 0.65),
    "cheeky": ("cheeky", 0.7),
    "mischievous": ("cheeky", 0.7),
    "fun": ("playful", 0.55),
    "silly": ("playful", 0.6),
    "goofy": ("playful", 0.6),
    "whimsical": ("playful", 0.6),
    "teasing": ("cheeky", 0.65),
    # Content (tertiary)
    "content": ("content", 0.6),
    "satisfied": ("content", 0.65),
    "comfortable": ("content", 0.55),
    "relaxed": ("content", 0.6),
    "peaceful": ("peaceful", 0.65),
    "serene": ("peaceful", 0.7),
    "tranquil": ("peaceful", 0.65),
    "calm": ("peaceful", 0.55),
    "at ease": ("content", 0.6),
    "cozy": ("content", 0.6),
    # Proud (tertiary)
    "proud": ("proud", 0.7),
    "accomplished": ("successful", 0.75),
    "successful": ("successful", 0.75),
    "confident": ("confident", 0.7),
    "capable": ("confident", 0.6),
    "strong": ("courageous", 0.65),
    "brave": ("courageous", 0.7),
    "bold": ("courageous", 0.65),
    # Inspired (tertiary)
    "inspired": ("inspired", 0.75),
    "creative": ("creative", 0.7),
    "motivated": ("inspired", 0.65),
    "imaginative": ("creative", 0.65),
    "visionary": ("inspired", 0.7),
    # Hopeful (tertiary)
    "hopeful": ("hopeful", 0.7),
    "optimistic": ("hopeful", 0.7),
    "promising": ("hopeful", 0.6),
    "bright": ("hopeful", 0.55),
    # Grateful (tertiary)
    "grateful": ("thankful", 0.75),
    "thankful": ("thankful", 0.75),
    "appreciative": ("thankful", 0.7),
    "blessed": ("thankful", 0.7),
    # Loving (tertiary)
    "loving": ("loving", 0.8),
    "affectionate": ("loving", 0.75),
    "tender": ("loving", 0.7),
    "caring": ("loving", 0.65),
    "warm": ("loving", 0.6),
    "fond": ("loving", 0.6),
    "adoring": ("loving", 0.8),
    "devoted": ("loving", 0.75),
    # Happy - general
    "happy": ("joyful", 0.65),
    "glad": ("content", 0.55),
    "pleased": ("content", 0.55),
    "good": ("content", 0.4),
    "nice": ("content", 0.4),
    "great": ("content", 0.55),
    "enjoy": ("content", 0.5),
    "sweet": ("loving", 0.55),
    "cool": ("content", 0.45),
    "awesome": ("excited", 0.75),
    "brilliant": ("inspired", 0.7),
    "excellent": ("proud", 0.7),
    "perfect": ("content", 0.75),
    "lovely": ("loving", 0.65),
    "yay": ("excited", 0.7),
    "woohoo": ("excited", 0.8),
    "hooray": ("excited", 0.75),

    # ============= SAD FAMILY =============
    # Hurt (tertiary)
    "hurt": ("hurt", 0.75),
    "heartbroken": ("hurt", 0.95),
    "wounded": ("hurt", 0.7),
    "betrayed": ("betrayed", 0.85),
    "rejected": ("rejected", 0.75),
    "abandoned": ("abandoned", 0.8),
    "neglected": ("abandoned", 0.7),
    # Lonely (tertiary)
    "lonely": ("lonely", 0.7),
    "isolated": ("isolated", 0.75),
    "alone": ("lonely", 0.65),
    "disconnected": ("isolated", 0.65),
    "left out": ("excluded", 0.7),
    # Grief (tertiary)
    "devastated": ("grief", 0.95),
    "grief": ("grief", 0.85),
    "grieving": ("grief", 0.8),
    "mourning": ("grief", 0.8),
    "loss": ("grief", 0.7),
    # Depressed (tertiary)
    "depressed": ("depressed", 0.8),
    "hopeless": ("despair", 0.85),
    "despair": ("despair", 0.9),
    "miserable": ("depressed", 0.85),
    "empty": ("empty", 0.75),
    "numb": ("numb", 0.7),
    "hollow": ("empty", 0.7),
    # Disappointed (tertiary)
    "disappointed": ("disappointed", 0.65),
    "let down": ("disappointed", 0.7),
    "discouraged": ("disappointed", 0.6),
    "disheartened": ("disappointed", 0.65),
    # Remorseful (tertiary)
    "sorry": ("remorseful", 0.55),
    "regret": ("remorseful", 0.65),
    "guilty": ("guilty", 0.7),
    "ashamed": ("ashamed", 0.75),
    "remorseful": ("remorseful", 0.7),
    # Vulnerable (tertiary)
    "vulnerable": ("vulnerable", 0.7),
    "fragile": ("fragile", 0.7),
    "helpless": ("helpless", 0.75),
    "powerless": ("powerless", 0.75),
    # Sad - general
    "sad": ("sad", 0.65),
    "unhappy": ("sad", 0.6),
    "upset": ("hurt", 0.6),
    "miss": ("lonely", 0.55),
    "unfortunately": ("disappointed", 0.45),
    "melancholy": ("sad", 0.65),
    "down": ("sad", 0.5),
    "blue": ("sad", 0.55),
    "gloomy": ("sad", 0.6),
    "heartache": ("hurt", 0.8),

    # ============= ANGRY FAMILY =============
    # Furious (tertiary)
    "furious": ("furious", 0.95),
    "enraged": ("furious", 0.95),
    "outraged": ("furious", 0.9),
    "livid": ("furious", 0.9),
    "infuriated": ("infuriated", 0.9),
    "seething": ("bitter", 0.85),
    "raging": ("furious", 0.9),
    # Bitter (tertiary)
    "bitter": ("bitter", 0.75),
    "resentful": ("resentful", 0.75),
    "spiteful": ("bitter", 0.7),
    # Hostile (tertiary)
    "hate": ("hostile", 0.8),
    "hostile": ("hostile", 0.8),
    "aggressive": ("aggressive", 0.75),
    "confrontational": ("aggressive", 0.7),
    # Frustrated (tertiary)
    "frustrated": ("frustrated", 0.65),
    "exasperated": ("frustrated", 0.7),
    "annoyed": ("annoyed", 0.55),
    "irritated": ("annoyed", 0.55),
    "bothered": ("annoyed", 0.5),
    "agitated": ("frustrated", 0.6),
    # Jealous (tertiary)
    "jealous": ("jealous", 0.75),
    "envious": ("jealous", 0.7),
    # Distant/Critical (tertiary)
    "dismissive": ("dismissive", 0.65),
    "critical": ("critical", 0.6),
    "judgmental": ("judgmental", 0.65),
    "sceptical": ("sceptical", 0.55),
    "skeptical": ("sceptical", 0.55),
    # Angry - general
    "angry": ("mad", 0.7),
    "mad": ("mad", 0.6),
    "ugh": ("annoyed", 0.45),
    "hmph": ("annoyed", 0.5),
    "grumpy": ("annoyed", 0.55),

    # ============= FEARFUL FAMILY =============
    # Frightened (tertiary)
    "terrified": ("frightened", 0.95),
    "horrified": ("frightened", 0.9),
    "petrified": ("frightened", 0.9),
    "terror": ("frightened", 0.85),
    "frightened": ("frightened", 0.75),
    "spooked": ("frightened", 0.65),
    # Anxious (tertiary)
    "anxious": ("anxious", 0.65),
    "worried": ("worried", 0.55),
    "nervous": ("nervous", 0.55),
    "uneasy": ("anxious", 0.55),
    "concerned": ("worried", 0.5),
    "apprehensive": ("anxious", 0.6),
    "tense": ("anxious", 0.55),
    "on edge": ("anxious", 0.6),
    # Overwhelmed (tertiary)
    "panic": ("overwhelmed", 0.85),
    "overwhelmed": ("overwhelmed", 0.75),
    "stressed": ("stressed", 0.65),
    "swamped": ("overwhelmed", 0.7),
    "frazzled": ("stressed", 0.65),
    # Scared (tertiary)
    "scared": ("scared", 0.7),
    "afraid": ("scared", 0.7),
    "dread": ("scared", 0.8),
    "fearful": ("scared", 0.7),
    # Insecure (tertiary)
    "insecure": ("insecure", 0.65),
    "inadequate": ("inadequate", 0.7),
    "inferior": ("inferior", 0.7),
    "self-conscious": ("insecure", 0.6),
    "doubtful": ("insecure", 0.55),

    # ============= SURPRISED FAMILY =============
    # Amazed (tertiary)
    "amazed": ("amazed", 0.8),
    "astonished": ("astonished", 0.85),
    "awestruck": ("awe", 0.85),
    "awe": ("awe", 0.8),
    "wonder": ("awe", 0.7),
    "wondrous": ("awe", 0.7),
    "breathtaking": ("awe", 0.75),
    "incredible": ("astonished", 0.7),
    "unbelievable": ("astonished", 0.75),
    "mindblowing": ("astonished", 0.85),
    # Shocked (tertiary)
    "shocked": ("shocked", 0.9),
    "stunned": ("shocked", 0.85),
    "startled": ("startled", 0.7),
    "taken aback": ("startled", 0.65),
    # Confused (tertiary)
    "confused": ("confused", 0.6),
    "puzzled": ("perplexed", 0.6),
    "perplexed": ("perplexed", 0.65),
    "bewildered": ("confused", 0.7),
    "baffled": ("perplexed", 0.65),
    "disoriented": ("confused", 0.65),
    # Surprised - general
    "surprised": ("startled", 0.65),
    "unexpected": ("startled", 0.55),
    "wow": ("amazed", 0.7),
    "whoa": ("amazed", 0.65),
    "omg": ("shocked", 0.7),
    "gosh": ("startled", 0.5),
    "oh my": ("startled", 0.55),
    "no way": ("shocked", 0.65),

    # ============= DISGUSTED FAMILY =============
    "disgusting": ("repelled", 0.85),
    "revolting": ("revolted", 0.85),
    "gross": ("repelled", 0.7),
    "nasty": ("repelled", 0.65),
    "vile": ("detestable", 0.8),
    "repulsive": ("repelled", 0.8),
    "yuck": ("nauseated", 0.6),
    "ew": ("repelled", 0.5),
    "eww": ("repelled", 0.55),
    "appalled": ("appalled", 0.75),
    "offended": ("appalled", 0.65),
    "disapproving": ("disapproving", 0.6),

    # ============= BAD/TIRED FAMILY =============
    "terrible": ("awful", 0.75),
    "awful": ("awful", 0.75),
    "horrible": ("awful", 0.75),
    "exhausted": ("tired", 0.7),
    "tired": ("tired", 0.55),
    "sleepy": ("sleepy", 0.55),
    "drowsy": ("sleepy", 0.55),
    "drained": ("tired", 0.65),
    "fatigued": ("tired", 0.65),
    "weary": ("tired", 0.6),
    "bored": ("bored", 0.55),
    "indifferent": ("indifferent", 0.5),
    "apathetic": ("apathetic", 0.55),
    "uninspired": ("bored", 0.5),
    "unfocused": ("unfocused", 0.55),
    "distracted": ("unfocused", 0.5),

    # ============= INTIMATE/PASSIONATE =============
    # Intimate (tertiary)
    "intimate": ("intimate", 0.75),
    "close": ("intimate", 0.55),
    "connected": ("intimate", 0.65),
    "bonded": ("intimate", 0.7),
    # Aroused (tertiary)
    "aroused": ("aroused", 0.8),
    "turned on": ("aroused", 0.85),
    "horny": ("aroused", 0.9),
    "lusty": ("aroused", 0.8),
    "sexy": ("aroused", 0.7),
    "hot": ("aroused", 0.6),
    "sultry": ("aroused", 0.7),
    "steamy": ("aroused", 0.75),
    # Passionate (tertiary)
    "passionate": ("passionate", 0.8),
    "passion": ("passionate", 0.75),
    "desire": ("passionate", 0.75),
    "yearning": ("passionate", 0.7),
    "longing": ("passionate", 0.7),
    "craving": ("passionate", 0.7),
    # Sensual (tertiary)
    "sensual": ("sensual", 0.7),
    "seductive": ("sensual", 0.75),
    "alluring": ("sensual", 0.7),
    "enticing": ("sensual", 0.65),
    # Flirty (tertiary)
    "flirty": ("flirty", 0.65),
    "flirt": ("flirty", 0.6),
    "coy": ("flirty", 0.6),
    "playfully": ("flirty", 0.55),
    "tease": ("flirty", 0.6),
    "naughty": ("cheeky", 0.65),
    # Physical affection
    "kiss": ("intimate", 0.65),
    "kissing": ("intimate", 0.7),
    "caress": ("intimate", 0.7),
    "touch": ("intimate", 0.5),
    "touching": ("intimate", 0.55),
    "embrace": ("intimate", 0.65),
    "cuddle": ("intimate", 0.6),
    "cuddling": ("intimate", 0.65),
    "snuggle": ("intimate", 0.6),
    "hold": ("intimate", 0.5),
    "holding": ("intimate", 0.55),
    "babe": ("intimate", 0.55),
    "baby": ("intimate", 0.5),

    # ============= AFFECTIONATE =============
    "adore": ("loving", 0.85),
    "cherish": ("loving", 0.8),
    "sweetheart": ("loving", 0.7),
    "darling": ("loving", 0.65),
    "honey": ("loving", 0.6),
    "cutie": ("playful", 0.6),
    "precious": ("loving", 0.7),
    "dear": ("loving", 0.55),

    # ============= PLAYFUL/AMUSED =============
    "hehe": ("playful", 0.6),
    "haha": ("playful", 0.65),
    "lol": ("playful", 0.5),
    "teehee": ("cheeky", 0.65),
    "giggle": ("playful", 0.6),
    "giggly": ("playful", 0.65),
    "laugh": ("playful", 0.6),
    "laughing": ("playful", 0.65),
    "hilarious": ("playful", 0.7),
    "funny": ("playful", 0.55),
    "amusing": ("playful", 0.55),
    "entertained": ("playful", 0.55),
    "giddy": ("playful", 0.7),

    # ============= EMBARRASSED/SHY =============
    "embarrassed": ("embarrassed", 0.7),
    "blushing": ("embarrassed", 0.65),
    "shy": ("sensitive", 0.55),
    "flustered": ("embarrassed", 0.7),
    "awkward": ("embarrassed", 0.55),
    "sheepish": ("embarrassed", 0.6),
    "mortified": ("embarrassed", 0.85),
    "self-conscious": ("embarrassed", 0.6),

    # ============= CURIOUS/INTERESTED =============
    "curious": ("curious", 0.6),
    "intrigued": ("curious", 0.65),
    "fascinated": ("inquisitive", 0.7),
    "interested": ("curious", 0.55),
    "interesting": ("curious", 0.5),
    "wondering": ("curious", 0.5),
    "inquisitive": ("inquisitive", 0.65),
    "captivated": ("inquisitive", 0.7),
    "engrossed": ("inquisitive", 0.65),

    # ============= TRUSTING/SECURE =============
    "trusting": ("trusting", 0.7),
    "trust": ("trusting", 0.65),
    "safe": ("secure", 0.65),
    "secure": ("secure", 0.65),
    "protected": ("secure", 0.6),
    "comfortable with": ("trusting", 0.6),

    # ============= THOUGHTFUL/REFLECTIVE =============
    "thoughtful": ("thoughtful", 0.6),
    "reflective": ("thoughtful", 0.6),
    "contemplative": ("thoughtful", 0.65),
    "pensive": ("thoughtful", 0.6),
    "pondering": ("thoughtful", 0.55),
    "considering": ("thoughtful", 0.5),
    "musing": ("thoughtful", 0.55),

    # ============= DETERMINED/FOCUSED =============
    "determined": ("determined", 0.7),
    "focused": ("focused", 0.65),
    "driven": ("determined", 0.7),
    "resolute": ("determined", 0.7),
    "committed": ("determined", 0.65),
    "dedicated": ("determined", 0.65),

    # ============= RELIEVED =============
    "relieved": ("relieved", 0.7),
    "relief": ("relieved", 0.7),
    "glad it's over": ("relieved", 0.65),
    "weight off": ("relieved", 0.65),

    # ============= NOSTALGIC =============
    "nostalgic": ("nostalgic", 0.7),
    "reminiscing": ("nostalgic", 0.65),
    "memories": ("nostalgic", 0.55),
    "remember when": ("nostalgic", 0.6),

    # ============= CONVERSATIONAL EXPRESSIONS =============
    "hmm": ("thoughtful", 0.45),
    "oh": ("curious", 0.35),
    "ooh": ("curious", 0.45),
    "ahh": ("content", 0.45),
    "aww": ("loving", 0.6),
    "aw": ("loving", 0.55),
    "mmm": ("content", 0.5),
    "mhm": ("content", 0.4),
    "sigh": ("thoughtful", 0.5),
    "phew": ("relieved", 0.6),
    "yikes": ("scared", 0.6),
    "oops": ("embarrassed", 0.5),
    "whoops": ("embarrassed", 0.5),
    "oof": ("sympathetic", 0.5),
    "geez": ("frustrated", 0.5),
    "dang": ("disappointed", 0.5),
    "darn": ("disappointed", 0.5),
    "yikes": ("anxious", 0.6),
}

# Multi-word phrases mapped to (emotion, base_intensity)
# These are checked before single-word keywords
EMOTION_PHRASES: Dict[str, Tuple[str, float]] = {
    # Joyful expressions
    "can't wait": ("eager", 0.75),
    "so happy": ("joyful", 0.8),
    "over the moon": ("joyful", 0.9),
    "on cloud nine": ("joyful", 0.9),
    "makes me smile": ("joyful", 0.7),
    "warms my heart": ("loving", 0.75),
    "melts my heart": ("loving", 0.8),
    "fills me with joy": ("joyful", 0.85),
    "bursting with": ("excited", 0.8),
    # Loving expressions
    "care about you": ("loving", 0.75),
    "mean so much": ("loving", 0.75),
    "close to you": ("intimate", 0.7),
    "feel connected": ("intimate", 0.7),
    "by your side": ("loving", 0.65),
    "thinking of you": ("loving", 0.65),
    "miss you": ("lonely", 0.7),
    # Excited/Eager
    "looking forward": ("eager", 0.7),
    "can't believe": ("amazed", 0.75),
    "so excited": ("excited", 0.85),
    "dying to": ("eager", 0.75),
    # Worried/Anxious
    "what if": ("worried", 0.55),
    "not sure if": ("anxious", 0.5),
    "kind of worried": ("worried", 0.6),
    "a bit nervous": ("nervous", 0.6),
    "hope everything": ("hopeful", 0.6),
    # Curious
    "want to know": ("curious", 0.6),
    "tell me more": ("curious", 0.65),
    "wondering about": ("curious", 0.6),
    "what do you think": ("curious", 0.55),
    # Affirmative/Supportive
    "of course": ("confident", 0.55),
    "absolutely": ("confident", 0.6),
    "definitely": ("confident", 0.55),
    "no doubt": ("confident", 0.6),
    "believe in you": ("trusting", 0.75),
    "proud of you": ("proud", 0.8),
    # Empathetic
    "understand how you feel": ("empathetic", 0.7),
    "must be hard": ("empathetic", 0.65),
    "here for you": ("loving", 0.7),
    "by your side": ("trusting", 0.65),
    # Playful
    "just kidding": ("playful", 0.6),
    "only joking": ("playful", 0.6),
    "messing with you": ("cheeky", 0.65),
    # Intimate
    "feel so close": ("intimate", 0.75),
    "want you": ("passionate", 0.8),
    "need you": ("passionate", 0.75),
    "crave you": ("passionate", 0.85),
    "can't stop thinking": ("passionate", 0.75),
    "turn me on": ("aroused", 0.85),
    "drives me crazy": ("aroused", 0.8),
    # Embarrassed
    "a little embarrassed": ("embarrassed", 0.65),
    "kind of shy": ("sensitive", 0.6),
    "face is red": ("embarrassed", 0.7),
    # Thoughtful
    "let me think": ("thoughtful", 0.55),
    "thinking about": ("thoughtful", 0.5),
    "on my mind": ("thoughtful", 0.55),
    # Grateful
    "thank you so much": ("thankful", 0.8),
    "means a lot": ("thankful", 0.75),
    "so grateful": ("thankful", 0.8),
    "appreciate it": ("thankful", 0.65),
    # Relief
    "what a relief": ("relieved", 0.75),
    "so relieved": ("relieved", 0.8),
    "glad that's over": ("relieved", 0.7),
    # Nostalgic
    "remember when": ("nostalgic", 0.65),
    "good old days": ("nostalgic", 0.7),
    "takes me back": ("nostalgic", 0.7),
}

# Punctuation intensity modifiers
INTENSITY_MODIFIERS = {
    "!": 0.15,
    "!!": 0.25,
    "!!!": 0.35,
    "?": 0.05,
    "...": 0.1,
}

# Words that amplify following emotion words
AMPLIFIERS = {
    "very", "so", "really", "extremely", "incredibly", "absolutely",
    "totally", "completely", "utterly", "deeply", "truly"
}


class TextEmotionAnalyzer:
    """
    Analyzes text for emotional content.

    Detects emotion keywords with position tracking and intensity modifiers.
    """

    @classmethod
    def analyze_text(cls, text: str) -> List[EmotionSpike]:
        """
        Analyze text and return detected emotions with positions.

        Args:
            text: Text to analyze

        Returns:
            List of EmotionSpike objects
        """
        spikes = []
        lower_text = text.lower()

        # First, check for multi-word phrases
        matched_positions = set()  # Track positions already matched by phrases
        for phrase, (emotion, base_intensity) in EMOTION_PHRASES.items():
            idx = lower_text.find(phrase)
            while idx >= 0:
                # Check if this position overlaps with already matched content
                phrase_end = idx + len(phrase)
                if not any(idx <= pos < phrase_end for pos in matched_positions):
                    # Check for punctuation near the phrase
                    intensity = base_intensity
                    context_end = min(phrase_end + 5, len(text))
                    nearby_text = text[idx:context_end]
                    for punct, bonus in INTENSITY_MODIFIERS.items():
                        if punct in nearby_text:
                            intensity = min(1.0, intensity + bonus)

                    position = idx / len(text) if len(text) > 0 else 0.5
                    spikes.append(EmotionSpike(
                        position=position,
                        emotion=emotion,
                        intensity=intensity,
                        word=phrase
                    ))
                    # Mark these positions as matched
                    for p in range(idx, phrase_end):
                        matched_positions.add(p)

                # Look for next occurrence
                idx = lower_text.find(phrase, phrase_end)

        # Split into words for single-word matching
        words = re.split(r'[\s,;:.!?]+', lower_text)
        word_positions = []

        # Calculate word positions in original text
        pos = 0
        for word in words:
            idx = lower_text.find(word, pos)
            if idx >= 0:
                word_positions.append(idx)
                pos = idx + len(word)
            else:
                word_positions.append(pos)

        # Check for emotion keywords (skip if already matched by phrase)
        amplifier_active = False
        for i, word in enumerate(words):
            word = word.strip()
            if not word:
                continue

            # Skip if this word was part of a matched phrase
            if i < len(word_positions) and word_positions[i] in matched_positions:
                continue

            # Check for amplifiers
            if word in AMPLIFIERS:
                amplifier_active = True
                continue

            # Check for emotion keywords
            if word in EMOTION_KEYWORDS:
                emotion, base_intensity = EMOTION_KEYWORDS[word]
                intensity = base_intensity

                # Apply amplifier bonus
                if amplifier_active:
                    intensity = min(1.0, intensity * 1.3)

                # Check for punctuation modifiers nearby
                nearby_text = ""
                if i < len(word_positions):
                    start = word_positions[i]
                    end = word_positions[i + 1] if i + 1 < len(word_positions) else len(text)
                    nearby_text = text[start:end]

                for punct, bonus in INTENSITY_MODIFIERS.items():
                    if punct in nearby_text:
                        intensity = min(1.0, intensity + bonus)

                # Calculate position
                position = word_positions[i] / len(text) if i < len(word_positions) and len(text) > 0 else 0.5

                spikes.append(EmotionSpike(
                    position=position,
                    emotion=emotion,
                    intensity=intensity,
                    word=word
                ))

                amplifier_active = False
            else:
                # Reset amplifier if not followed by emotion word
                if word not in AMPLIFIERS:
                    amplifier_active = False

        return spikes

    @classmethod
    def get_emotional_tone(cls, text: str) -> Dict[str, float]:
        """
        Get the overall emotional tone of text.

        Args:
            text: Text to analyze

        Returns:
            Dict mapping emotion -> average intensity
        """
        spikes = cls.analyze_text(text)
        if not spikes:
            return {}

        # Group by emotion and average intensities
        emotion_intensities: Dict[str, List[float]] = {}
        for spike in spikes:
            if spike.emotion not in emotion_intensities:
                emotion_intensities[spike.emotion] = []
            emotion_intensities[spike.emotion].append(spike.intensity)

        return {
            emotion: sum(intensities) / len(intensities)
            for emotion, intensities in emotion_intensities.items()
        }

    @classmethod
    def get_dominant_emotion(cls, text: str) -> Optional[Tuple[str, float]]:
        """
        Get the dominant emotion from text.

        Args:
            text: Text to analyze

        Returns:
            Tuple of (emotion, intensity) or None
        """
        tone = cls.get_emotional_tone(text)
        if not tone:
            return None

        dominant = max(tone.items(), key=lambda x: x[1])
        return dominant
