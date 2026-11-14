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

# ============= Words, negation and French (humanness Task 16a) =============
# Spec section 4.8: "The text fallback analyzer handles word boundaries, a
# 3-token negation window, curly apostrophes and a basic French lexicon."
# Every French word maps to an English entry of EMOTION_KEYWORDS (or
# EMOTION_PHRASES), whose label and intensity it takes: no label or number
# of its own.

#: Apostrophes a phone or a word processor writes, read as "'" (spec 4.8).
CURLY_APOSTROPHES = "’‘ʼ′´`"
_APOSTROPHE_TABLE = str.maketrans({c: "'" for c in CURLY_APOSTROPHES})

#: A word: letters and digits, joined by an apostrophe or a hyphen ("don't",
#: "self-conscious", "aujourd'hui").
_TOKEN_RE = re.compile(r"\w+(?:['\-]\w+)*")

#: Punctuation that ends a clause, and with it a negation's reach.
_CLAUSE_BREAK_RE = re.compile(r"[.,;:!?]")

#: Words that end a clause too ("not great but happy" is happy).
CLAUSE_BREAK_WORDS = frozenset({"but", "mais"})

#: How many tokens after a negator it negates (the spec's "3-token negation
#: window"): an emotion word or phrase starting 1 to 3 tokens after one, in
#: the same clause, is not felt.
NEGATION_WINDOW = 3

#: Negators. Any word ending in "n't" ("don't", "can't") is one too, and a
#: French word elided with "n'" ("n'aime") is negated itself. Bare "no" and
#: "non" are not: "oh no, I'm sad" is sad.
NEGATORS = frozenset({
    "not", "never", "nor", "neither", "cannot", "nothing", "nobody", "none", "without",
    "dont", "doesnt", "didnt", "isnt", "wasnt", "arent", "werent", "cant", "couldnt",
    "wouldnt", "shouldnt", "wont", "havent", "hasnt", "hadnt", "aint",
    # French: ne ... pas / jamais / rien / aucun, sans, ni
    "ne", "pas", "jamais", "rien", "aucun", "aucune", "sans", "ni",
})

#: French elisions ("j'aime", "l'amour", "t'aime"): the word after the
#: apostrophe is looked up.
FRENCH_ELISIONS = ("j'", "l'", "d'", "m'", "t'", "s'", "c'", "n'", "qu'")

#: A basic French lexicon: each word -> the English EMOTION_KEYWORDS entry
#: whose label and intensity it reads as. Words spelled the same as an
#: English word of another sense ("surprise", "confuse") are left out.
FRENCH_KEYWORDS: Dict[str, str] = {
    "heureux": "happy", "heureuse": "happy", "joie": "joy", "ravi": "delighted", "ravie": "delighted",
    "content": "content", "contente": "content", "génial": "awesome", "géniale": "awesome",
    "excité": "excited", "excitée": "excited", "fier": "proud", "fière": "proud",
    "aime": "love", "aimes": "love", "adore": "adore", "adores": "adore", "amour": "love",
    "merci": "grateful", "reconnaissant": "grateful", "reconnaissante": "grateful",
    "soulagé": "relieved", "soulagée": "relieved", "calme": "calm", "curieux": "curious",
    "curieuse": "curious", "surpris": "surprised",
    "triste": "sad", "tristesse": "sad", "malheureux": "unhappy", "malheureuse": "unhappy",
    "seul": "lonely", "seule": "lonely", "solitude": "lonely", "déprimé": "depressed",
    "déprimée": "depressed", "déçu": "disappointed", "déçue": "disappointed", "blessé": "hurt",
    "blessée": "hurt", "désolé": "sorry", "désolée": "sorry", "honte": "ashamed",
    "colère": "angry", "fâché": "angry", "fâchée": "angry", "furieux": "furious",
    "furieuse": "furious", "énervé": "annoyed", "énervée": "annoyed", "déteste": "hate",
    "détestes": "hate", "haine": "hate", "jaloux": "jealous", "jalouse": "jealous",
    "peur": "afraid", "effrayé": "frightened", "effrayée": "frightened", "inquiet": "worried",
    "inquiète": "worried", "anxieux": "anxious", "anxieuse": "anxious", "stressé": "stressed",
    "stressée": "stressed", "fatigué": "tired", "fatiguée": "tired", "épuisé": "exhausted",
    "épuisée": "exhausted", "ennui": "bored", "ennuyé": "bored", "ennuyée": "bored",
    "confus": "confused", "gêné": "embarrassed", "gênée": "embarrassed",
    "mdr": "lol",
}

#: French phrases -> the English EMOTION_PHRASES or EMOTION_KEYWORDS entry
#: they read as.
FRENCH_PHRASES: Dict[str, str] = {
    "tu me manques": "miss you",
    "j'en ai marre": "frustrated",
}

#: Greetings: formulas, not feelings. Their words are matched as a whole
#: and weighed by none of the tables ("good night" held "good": content --
#: every evening's goodbye read as the user feeling good, and left her a
#: memory of good news; Task 39). English and French, read whatever the
#: language asked for: none of them is a word of the other.
GREETING_PHRASES = (
    "good night", "good morning", "good evening", "good afternoon", "good day",
    "bonne nuit", "bonne journée", "bonne journee", "bonne soirée", "bonne soiree",
)

#: French words that amplify the next emotion word, as AMPLIFIERS do.
FRENCH_AMPLIFIERS = frozenset({
    "très", "tres", "tellement", "vraiment", "trop", "si", "extrêmement", "complètement",
    "totalement", "profondément",
})

#: Words that address the listener -- her: a turn with one of them is aimed
#: at her ("I hate you"), one without is about something else ("I hate my
#: job").
LISTENER_WORDS = frozenset({
    "you", "your", "yours", "yourself", "you're", "youre", "you've", "you'll", "you'd", "u", "ur",
})

#: The French ones, with a word elided with "t'" ("t'aime", "t'es"): read
#: unless the turn's language is English. "ton" and "ta" (your) are left
#: out, as the lexicon leaves out "surprise": English words of another sense
#: ("a ton of", "ta" for thanks), so "I hate this, I have a ton of homework"
#: is not at her.
FRENCH_LISTENER_WORDS = frozenset({"tu", "toi", "te", "tes", "vous", "votre", "vos"})


@dataclass(frozen=True)
class _Token:
    text: str
    start: int
    end: int
    clause: int


def normalize_text(text: str) -> str:
    """``text`` as the analyzer reads it: curly apostrophes straightened
    (:data:`CURLY_APOSTROPHES`), lower case."""
    return (text or "").translate(_APOSTROPHE_TABLE).lower()


def _tokens(normalized: str) -> List[_Token]:
    """The words of an already-normalized text, each with its clause: a
    clause ends at ``.,;:!?`` and at :data:`CLAUSE_BREAK_WORDS`."""
    tokens: List[_Token] = []
    clause = 0
    previous_end = 0
    for match in _TOKEN_RE.finditer(normalized):
        if _CLAUSE_BREAK_RE.search(normalized, previous_end, match.start()):
            clause += 1
        word = match.group()
        if word in CLAUSE_BREAK_WORDS:
            clause += 1
        tokens.append(_Token(word, match.start(), match.end(), clause))
        previous_end = match.end()
    return tokens


def _is_negator(word: str) -> bool:
    return word in NEGATORS or word.endswith("n't") or word.startswith("n'")


def _negated(tokens: List[_Token], index: int, protected: set) -> bool:
    """True when the token at ``index`` is negated: a negator 1 to
    :data:`NEGATION_WINDOW` tokens before it, in its clause, that is not part
    of a matched phrase (``protected``: "can't wait" negates nothing), or the
    token itself elided with "n'"."""
    if tokens[index].text.startswith("n'"):
        return True
    for j in range(max(0, index - NEGATION_WINDOW), index):
        if j in protected or tokens[j].clause != tokens[index].clause:
            continue
        if _is_negator(tokens[j].text):
            return True
    return False


def _phrase_occurrences(tokens: List[_Token], phrase_words: List[str]) -> List[int]:
    """Where ``phrase_words`` stand as consecutive tokens of one clause."""
    n = len(phrase_words)
    if n == 0:
        return []
    found = []
    for start in range(len(tokens) - n + 1):
        window = tokens[start:start + n]
        if [t.text for t in window] == phrase_words and window[0].clause == window[-1].clause:
            found.append(start)
    return found


def _lookup_word(word: str, language: Optional[str]) -> Optional[Tuple[str, float]]:
    """``(label, intensity)`` for one word, from EMOTION_KEYWORDS, or the
    French lexicon (unless ``language`` is English), after an elision."""
    english_only = _english_only(language)
    candidates = [word]
    if not english_only:
        for elision in FRENCH_ELISIONS:
            if word.startswith(elision) and len(word) > len(elision):
                candidates.append(word[len(elision):])
                break
    for candidate in candidates:
        if candidate in EMOTION_KEYWORDS:
            return EMOTION_KEYWORDS[candidate]
        if not english_only and candidate in FRENCH_KEYWORDS:
            return EMOTION_KEYWORDS[FRENCH_KEYWORDS[candidate]]
    return None


def _english_only(language: Optional[str]) -> bool:
    return bool(language) and str(language).lower().startswith("en")


def _phrase_table(language: Optional[str]) -> List[Tuple[str, Tuple[str, float]]]:
    table = list(EMOTION_PHRASES.items())
    if not _english_only(language):
        for french, english in FRENCH_PHRASES.items():
            entry = EMOTION_PHRASES.get(english) or EMOTION_KEYWORDS.get(english)
            if entry is not None:
                table.append((french, entry))
    return table


def matched_cues(text: str, cues) -> List[str]:
    """The ``cues`` (words or phrases, such as ``CONVERSATION_KEYWORD_MAP``'s
    keys) ``text`` says, in ``cues``' order: each on word boundaries and not
    negated, through the same tokenizer and negation window as
    :meth:`TextEmotionAnalyzer.analyze_text` (ruling T16-R4) -- "I don't love
    you" says no "love", "glove" says none. A negator inside a cue that
    matched, before its last word ("don't worry"), negates nothing; one that
    ends it ("that's not") still negates what follows."""
    tokens = _tokens(normalize_text(text))
    occurrences = []
    protected: set = set()
    for cue in cues:
        words = [t.text for t in _tokens(normalize_text(cue))]
        starts = _phrase_occurrences(tokens, words)
        occurrences.append((cue, starts))
        for start in starts:
            protected.update(range(start, start + len(words) - 1))
    return [cue for cue, starts in occurrences
            if any(not _negated(tokens, start, protected) for start in starts)]


def addresses_listener(text: str, language: Optional[str] = None) -> bool:
    """True when ``text`` speaks to its listener -- her (:data:`LISTENER_WORDS`;
    :data:`FRENCH_LISTENER_WORDS` and "t'" too unless ``language`` is
    English, as :meth:`TextEmotionAnalyzer.analyze_text` reads it)."""
    french = not _english_only(language)
    for token in _tokens(normalize_text(text)):
        if token.text in LISTENER_WORDS:
            return True
        if french and (token.text in FRENCH_LISTENER_WORDS or token.text.startswith("t'")):
            return True
    return False


class TextEmotionAnalyzer:
    """
    Analyzes text for emotional content.

    Detects emotion keywords with position tracking and intensity modifiers.
    """

    @classmethod
    def analyze_text(cls, text: str, language: Optional[str] = None) -> List[EmotionSpike]:
        """
        Analyze text and return detected emotions with positions.

        Phrases first (EMOTION_PHRASES, then FRENCH_PHRASES), then single
        words (EMOTION_KEYWORDS, then FRENCH_KEYWORDS), all on word
        boundaries -- "dismiss you" holds no "miss you" -- with curly
        apostrophes read as straight ones. A word or phrase that starts 1 to
        NEGATION_WINDOW tokens after a negator in its clause is not felt
        ("I'm not happy" holds no joy). Amplifiers ("so", "tellement") and
        punctuation strengthen what follows, as before.

        Args:
            text: Text to analyze
            language: ``None`` (the default) reads English and French; a
                code starting with "en" reads English only.

        Returns:
            List of EmotionSpike objects
        """
        spikes = []
        normalized = normalize_text(text)
        length = len(normalized)
        tokens = _tokens(normalized)

        # Multi-word phrases first, on whole tokens; a phrase never overlaps
        # one matched before it. Its words before its last negate nothing.
        phrase_matches = []  # (start token, end token, emotion, intensity, phrase)
        matched: set = set()
        protected: set = set()
        # A greeting first: its words are a formula, weighed by no table.
        for greeting in GREETING_PHRASES:
            words = [t.text for t in _tokens(normalize_text(greeting))]
            for start in _phrase_occurrences(tokens, words):
                matched.update(range(start, start + len(words)))
        for phrase, (emotion, base_intensity) in _phrase_table(language):
            words = [t.text for t in _tokens(normalize_text(phrase))]
            for start in _phrase_occurrences(tokens, words):
                span = range(start, start + len(words))
                if any(i in matched for i in span):
                    continue
                matched.update(span)
                protected.update(range(start, start + len(words) - 1))
                phrase_matches.append((start, start + len(words), emotion, base_intensity, phrase))

        for start, end, emotion, base_intensity, phrase in phrase_matches:
            if _negated(tokens, start, protected):
                continue
            intensity = base_intensity
            first, last = tokens[start], tokens[end - 1]
            nearby_text = normalized[first.start:min(last.end + 5, length)]
            for punct, bonus in INTENSITY_MODIFIERS.items():
                if punct in nearby_text:
                    intensity = min(1.0, intensity + bonus)
            spikes.append(EmotionSpike(
                position=first.start / length if length > 0 else 0.5,
                emotion=emotion,
                intensity=intensity,
                word=phrase,
            ))

        # Single words (a word inside a matched phrase is skipped)
        amplifier_active = False
        for i, token in enumerate(tokens):
            if i in matched:
                continue
            word = token.text
            if word in AMPLIFIERS or (not _english_only(language) and word in FRENCH_AMPLIFIERS):
                amplifier_active = True
                continue
            entry = _lookup_word(word, language)
            if entry is None:
                # Reset amplifier if not followed by emotion word
                amplifier_active = False
                continue
            amplified, amplifier_active = amplifier_active, False
            if _negated(tokens, i, protected):
                continue
            emotion, base_intensity = entry
            intensity = base_intensity
            if amplified:
                intensity = min(1.0, intensity * 1.3)
            # Punctuation modifiers between this word and the next
            end = tokens[i + 1].start if i + 1 < len(tokens) else length
            nearby_text = normalized[token.start:end]
            for punct, bonus in INTENSITY_MODIFIERS.items():
                if punct in nearby_text:
                    intensity = min(1.0, intensity + bonus)
            spikes.append(EmotionSpike(
                position=token.start / length if length > 0 else 0.5,
                emotion=emotion,
                intensity=intensity,
                word=word,
            ))

        return spikes

    @classmethod
    def get_emotional_tone(cls, text: str, language: Optional[str] = None) -> Dict[str, float]:
        """
        Get the overall emotional tone of text.

        Args:
            text: Text to analyze
            language: as for :meth:`analyze_text`

        Returns:
            Dict mapping emotion -> average intensity
        """
        spikes = cls.analyze_text(text, language=language)
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
    def get_dominant_emotion(cls, text: str, language: Optional[str] = None) -> Optional[Tuple[str, float]]:
        """
        Get the dominant emotion from text.

        Args:
            text: Text to analyze
            language: as for :meth:`analyze_text`

        Returns:
            Tuple of (emotion, intensity) or None
        """
        tone = cls.get_emotional_tone(text, language=language)
        if not tone:
            return None

        dominant = max(tone.items(), key=lambda x: x[1])
        return dominant
