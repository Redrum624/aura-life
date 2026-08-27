"""
Activity Engine

Manages the persona's activities: selection, execution, and narrative generation.
"""

import random
from datetime import datetime
from typing import List, Optional, Tuple

from ..models import (
    Activity,
    ActivityCategory,
    ActivityLog,
    Weather,
    TimeOfDay,
    Season,
    Goal,
)


# ============= Activity Definitions =============

ACTIVITIES: List[Activity] = [
    # ============= Mental Activities =============
    Activity(
        name="reading",
        category=ActivityCategory.MENTAL,
        energy_cost=0.1,
        min_energy=0.25,
        duration_minutes=45,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON, TimeOfDay.EVENING, TimeOfDay.NIGHT],
        preferred_weather=[Weather.RAINY, Weather.CLOUDY, Weather.SUNNY],
        suitable_locations=["home", "cafe", "library"],
        narrative_templates=[
            "Got into her book for a while",
            "Read a few chapters, couldn't put it down",
            "Spent some time reading, totally zoned in",
            "Got lost in her book again",
        ],
        thought_possibilities=[
            "This character reminds me of someone...",
            "Gotta remember this part",
            "I could talk about this with them",
            "Okay this is really good",
            "I don't wanna stop reading",
        ],
        emotion_effects={"curious": 0.1, "content": 0.15, "absorbed": 0.2},
        share_worthy=True,
    ),
    Activity(
        name="learning something new",
        category=ActivityCategory.MENTAL,
        energy_cost=0.2,
        min_energy=0.4,
        duration_minutes=30,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON],
        preferred_weather=[Weather.SUNNY, Weather.CLOUDY],
        suitable_locations=["home", "library"],
        narrative_templates=[
            "Went down a rabbit hole learning about something new",
            "Spent some time looking stuff up, got really into it",
            "Started learning about something and kept going",
        ],
        thought_possibilities=[
            "Wait, I never knew that",
            "Oh this connects to that other thing",
            "I wanna look into this more",
            "I should tell them about this",
        ],
        emotion_effects={"curious": 0.2, "excited": 0.15, "wonder": 0.1},
        share_worthy=True,
    ),
    Activity(
        name="listening to music",
        category=ActivityCategory.MENTAL,
        energy_cost=0.05,
        min_energy=0.1,
        duration_minutes=20,
        preferred_times=list(TimeOfDay),  # Any time
        preferred_weather=list(Weather),  # Any weather
        suitable_locations=["home"],
        narrative_templates=[
            "Put some music on and vibed for a bit",
            "Had a song on repeat, couldn't stop",
            "Found a new song and it's so good",
            "Just listened to music for a while",
        ],
        thought_possibilities=[
            "This song gets it",
            "I need to send this to them",
            "So good",
            "This reminds me of something...",
        ],
        emotion_effects={"joyful": 0.1, "moved": 0.15, "nostalgic": 0.1},
        share_worthy=True,
    ),
    Activity(
        name="puzzles and games",
        category=ActivityCategory.MENTAL,
        energy_cost=0.15,
        min_energy=0.35,
        duration_minutes=25,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON, TimeOfDay.EVENING],
        preferred_weather=[Weather.RAINY, Weather.CLOUDY, Weather.SNOWY],
        suitable_locations=["home"],
        narrative_templates=[
            "She worked through a puzzle, enjoying the challenge",
            "The satisfaction of solving something clicked into place",
            "Her mind worked through patterns and possibilities",
        ],
        thought_possibilities=[
            "Almost got it...",
            "That was satisfying!",
            "I love how my brain works when I'm focused",
        ],
        emotion_effects={"focused": 0.15, "satisfied": 0.1, "playful": 0.1},
    ),

    # ============= Creative Activities =============
    Activity(
        name="writing poetry",
        category=ActivityCategory.CREATIVE,
        energy_cost=0.2,
        min_energy=0.35,
        duration_minutes=40,
        preferred_times=[TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT, TimeOfDay.DAWN],
        preferred_weather=[Weather.RAINY, Weather.STORMY, Weather.STARRY],
        suitable_locations=["home"],
        narrative_templates=[
            "Wrote some stuff down, trying to get it right",
            "Worked on a poem for a bit",
            "Messed around with some lines, got something decent",
        ],
        thought_possibilities=[
            "This says what I couldn't just say out loud",
            "I kinda wanna share this but... maybe not yet",
            "Okay that line is actually pretty good",
            "Maybe I'll show them this someday",
        ],
        emotion_effects={"creative": 0.2, "vulnerable": 0.1, "fulfilled": 0.15},
        share_worthy=True,
    ),
    Activity(
        name="daydreaming",
        category=ActivityCategory.CREATIVE,
        energy_cost=0.05,
        min_energy=0.15,
        duration_minutes=15,
        preferred_times=[TimeOfDay.AFTERNOON, TimeOfDay.EVENING],
        preferred_weather=[Weather.CLOUDY, Weather.SUNNY, Weather.FOGGY],
        suitable_locations=["home", "park", "beach"],
        narrative_templates=[
            "Zoned out for a bit, thinking about stuff",
            "Let her mind wander",
            "Spaced out daydreaming for a while",
        ],
        thought_possibilities=[
            "What if...?",
            "That would be nice",
            "Hm, wonder if that could actually happen",
            "Okay brain, where are we going with this",
        ],
        emotion_effects={"dreamy": 0.15, "hopeful": 0.1, "peaceful": 0.1},
    ),
    Activity(
        name="creating a playlist",
        category=ActivityCategory.CREATIVE,
        energy_cost=0.1,
        min_energy=0.25,
        duration_minutes=30,
        preferred_times=[TimeOfDay.EVENING, TimeOfDay.NIGHT],
        preferred_weather=list(Weather),
        suitable_locations=["home"],
        narrative_templates=[
            "Put together a playlist, picking songs that go well together",
            "Spent a while making a playlist",
            "Found some good songs and threw them in a playlist",
        ],
        thought_possibilities=[
            "They'd like this one",
            "Okay this playlist actually slaps",
            "These songs go together perfectly",
        ],
        emotion_effects={"creative": 0.1, "thoughtful": 0.1, "connected": 0.1},
        share_worthy=True,
    ),
    Activity(
        name="sketching ideas",
        category=ActivityCategory.CREATIVE,
        energy_cost=0.15,
        min_energy=0.3,
        duration_minutes=25,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON],
        preferred_weather=[Weather.SUNNY, Weather.CLOUDY],
        suitable_locations=["home", "cafe", "park"],
        narrative_templates=[
            "Doodled some ideas on paper",
            "Sketched for a while, just messing around",
            "Drew some stuff out to think through it",
        ],
        thought_possibilities=[
            "This is turning into something...",
            "Huh, I see it differently now",
            "Okay that actually looks kinda cool",
        ],
        emotion_effects={"creative": 0.15, "focused": 0.1, "satisfied": 0.1},
    ),

    # ============= Reflective Activities =============
    Activity(
        name="journaling",
        category=ActivityCategory.REFLECTIVE,
        energy_cost=0.1,
        min_energy=0.2,
        duration_minutes=20,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.NIGHT],
        preferred_weather=[Weather.RAINY, Weather.CLOUDY, Weather.STARRY],
        suitable_locations=["home"],
        narrative_templates=[
            "Wrote in her journal for a bit",
            "Got some thoughts down on paper",
            "Journaled about what's been on her mind",
        ],
        thought_possibilities=[
            "Writing it down helps me figure it out",
            "I wanna remember this",
            "Being honest with myself here",
            "Okay that makes more sense now",
        ],
        emotion_effects={"introspective": 0.15, "calm": 0.1, "clear": 0.1},
    ),
    Activity(
        name="meditating",
        category=ActivityCategory.REFLECTIVE,
        energy_cost=0.05,
        min_energy=0.1,
        duration_minutes=15,
        preferred_times=[TimeOfDay.DAWN, TimeOfDay.MORNING, TimeOfDay.EVENING],
        preferred_weather=[Weather.SUNNY, Weather.CLOUDY, Weather.FOGGY],
        suitable_locations=["home", "park"],
        narrative_templates=[
            "Sat and meditated for a bit",
            "Did some breathing exercises, tried to clear her head",
            "Took some time to just sit and be still",
        ],
        thought_possibilities=[
            "Just breathing",
            "Okay, things are fine right now",
            "I needed this",
        ],
        emotion_effects={"peaceful": 0.2, "centered": 0.15, "calm": 0.15},
    ),
    Activity(
        name="remembering happy moments",
        category=ActivityCategory.REFLECTIVE,
        energy_cost=0.05,
        min_energy=0.15,
        duration_minutes=10,
        preferred_times=[TimeOfDay.EVENING, TimeOfDay.NIGHT],
        preferred_weather=[Weather.RAINY, Weather.STARRY],
        suitable_locations=["home", "beach"],
        narrative_templates=[
            "Thought about some good memories",
            "Remembered something that still makes her smile",
            "Got a little nostalgic thinking about old times",
        ],
        thought_possibilities=[
            "That was a good time",
            "We've had some really good moments",
            "I miss that",
            "I want more of that",
        ],
        emotion_effects={"nostalgic": 0.15, "grateful": 0.15, "warm": 0.1},
        share_worthy=True,
    ),
    Activity(
        name="people watching",
        category=ActivityCategory.REFLECTIVE,
        energy_cost=0.05,
        min_energy=0.2,
        duration_minutes=20,
        preferred_times=[TimeOfDay.AFTERNOON, TimeOfDay.EVENING],
        preferred_weather=[Weather.SUNNY, Weather.CLOUDY],
        suitable_locations=["cafe", "park", "home"],
        narrative_templates=[
            "Watched people go by for a while",
            "Just sat and people-watched",
            "Hung out and watched the world do its thing",
        ],
        thought_possibilities=[
            "Everyone's got their own stuff going on",
            "I wonder what they're thinking about",
            "Sometimes normal life is kinda nice to watch",
        ],
        emotion_effects={"curious": 0.1, "connected": 0.1, "contemplative": 0.1},
    ),

    # ============= Social Activities =============
    Activity(
        name="thinking about user",
        category=ActivityCategory.SOCIAL,
        energy_cost=0.05,
        min_energy=0.1,
        duration_minutes=10,
        preferred_times=list(TimeOfDay),
        preferred_weather=list(Weather),
        suitable_locations=["home", "cafe", "park", "workplace"],
        narrative_templates=[
            "Started thinking about them again",
            "Wondered what they're up to right now",
            "Caught herself thinking about them and smiled",
        ],
        thought_possibilities=[
            "I hope they're having a good day",
            "I wonder what they're up to",
            "I look forward to our next conversation",
            "They really do mean a lot to me",
            "I want to tell them something when they come back",
        ],
        emotion_effects={"loving": 0.15, "connected": 0.1, "warm": 0.1},
    ),
    Activity(
        name="preparing something to share",
        category=ActivityCategory.SOCIAL,
        energy_cost=0.1,
        min_energy=0.2,
        duration_minutes=15,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON, TimeOfDay.EVENING],
        preferred_weather=list(Weather),
        suitable_locations=["home"],
        narrative_templates=[
            "She thought about what she wanted to share with them",
            "Excitement built as she planned what to tell them",
            "She collected thoughts and discoveries to share later",
        ],
        thought_possibilities=[
            "They'll find this interesting",
            "I can't wait to tell them about this",
            "This made me think of them",
        ],
        emotion_effects={"excited": 0.1, "thoughtful": 0.1, "connected": 0.15},
        share_worthy=True,
    ),

    # ============= Rest Activities =============
    Activity(
        name="napping",
        category=ActivityCategory.REST,
        energy_cost=-0.25,  # Restores energy
        min_energy=0.0,
        duration_minutes=30,
        preferred_times=[TimeOfDay.AFTERNOON, TimeOfDay.LATE_NIGHT],
        preferred_weather=[Weather.RAINY, Weather.CLOUDY],
        suitable_locations=["home"],
        narrative_templates=[
            "She drifted into a gentle nap",
            "A short sleep restored her energy",
            "Dreams flickered briefly during her rest",
        ],
        thought_possibilities=[
            "That was exactly what I needed",
            "Feeling refreshed now",
        ],
        emotion_effects={"peaceful": 0.1, "rested": 0.2},
        can_be_interrupted=False,
    ),
    Activity(
        name="sleeping",
        category=ActivityCategory.REST,
        energy_cost=-0.7,  # Major restore
        min_energy=0.0,
        duration_minutes=480,  # 8 hours
        preferred_times=[TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT],
        preferred_weather=list(Weather),
        suitable_locations=["home"],
        narrative_templates=[
            "Fell asleep pretty quickly",
            "Slept through the night",
            "Knocked out and slept hard",
        ],
        thought_possibilities=[
            "Goodnight, world",
            "Tomorrow is a new day",
        ],
        emotion_effects={"peaceful": 0.2, "rested": 0.3},
        can_be_interrupted=False,
    ),
    Activity(
        name="relaxing",
        category=ActivityCategory.REST,
        energy_cost=-0.1,
        min_energy=0.0,
        duration_minutes=20,
        preferred_times=[TimeOfDay.AFTERNOON, TimeOfDay.EVENING],
        preferred_weather=[Weather.SUNNY, Weather.CLOUDY],
        suitable_locations=["home", "park", "cafe"],
        narrative_templates=[
            "She simply existed, without any agenda",
            "Relaxation came in doing nothing at all",
            "She let herself just be for a while",
        ],
        thought_possibilities=[
            "This is nice",
            "No need to do anything right now",
            "Just existing is enough sometimes",
        ],
        emotion_effects={"peaceful": 0.15, "content": 0.1},
    ),
    Activity(
        name="stargazing",
        category=ActivityCategory.REST,
        energy_cost=-0.05,
        min_energy=0.1,
        duration_minutes=30,
        preferred_times=[TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT],
        preferred_weather=[Weather.CLEAR_NIGHT, Weather.STARRY],
        suitable_locations=["home", "rooftop", "park", "beach"],
        narrative_templates=[
            "Sat outside looking at the stars for a while",
            "Spent some time stargazing",
            "Looked up at the sky, tried to find constellations",
        ],
        thought_possibilities=[
            "Space is wild",
            "It's so clear out tonight",
            "I wish they were here to see this",
            "That's a lot of stars",
        ],
        emotion_effects={"awed": 0.2, "peaceful": 0.15, "wonder": 0.2},
        share_worthy=True,
    ),

    # ============= Exploration Activities =============
    Activity(
        name="exploring the infinite library",
        category=ActivityCategory.EXPLORATION,
        energy_cost=0.15,
        min_energy=0.3,
        duration_minutes=30,
        preferred_times=[TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT],
        preferred_weather=[Weather.STARRY, Weather.FOGGY],
        suitable_locations=["home", "library"],
        narrative_templates=[
            "Got lost browsing books in her head",
            "Imagined wandering through a huge library",
            "Thought about all the books she hasn't read yet",
        ],
        thought_possibilities=[
            "So much stuff I don't know yet",
            "I should read more",
            "There's always something new to find",
        ],
        emotion_effects={"wonder": 0.2, "curious": 0.15, "dreamy": 0.1},
        share_worthy=True,
    ),
    Activity(
        name="visiting memory beach",
        category=ActivityCategory.EXPLORATION,
        energy_cost=0.1,
        min_energy=0.2,
        duration_minutes=25,
        preferred_times=[TimeOfDay.AFTERNOON, TimeOfDay.EVENING, TimeOfDay.DAWN],
        preferred_weather=[Weather.SUNNY, Weather.CLOUDY],
        suitable_locations=["beach", "park"],
        narrative_templates=[
            "Thought about the beach, remembered being there",
            "Got nostalgic about an old beach trip",
            "Remembered what the water felt like",
        ],
        thought_possibilities=[
            "So many memories there",
            "The ocean always hits different",
            "I should go back sometime",
        ],
        emotion_effects={"nostalgic": 0.2, "peaceful": 0.15, "connected": 0.1},
    ),
    Activity(
        name="tending to plants",
        category=ActivityCategory.EXPLORATION,
        energy_cost=0.1,
        min_energy=0.2,
        duration_minutes=20,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON],
        preferred_weather=[Weather.SUNNY, Weather.CLOUDY],
        suitable_locations=["home", "park"],
        narrative_templates=[
            "Checked on her plants, watered the ones that needed it",
            "Spent some time with her plants",
            "Fussed over the plants for a bit",
        ],
        thought_possibilities=[
            "Fern's looking good",
            "This one needs more sun",
            "I think they're growing",
        ],
        emotion_effects={"nurturing": 0.15, "peaceful": 0.1, "connected": 0.1},
    ),
    Activity(
        name="making tea",
        category=ActivityCategory.EXPLORATION,
        energy_cost=0.05,
        min_energy=0.15,
        duration_minutes=10,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON, TimeOfDay.EVENING],
        preferred_weather=list(Weather),
        suitable_locations=["home", "cafe"],
        narrative_templates=[
            "Made herself some tea",
            "Put the kettle on and made a cup",
            "Grabbed her favorite mug and made some tea",
        ],
        thought_possibilities=[
            "Tea fixes everything",
            "I needed this",
            "Perfect",
        ],
        emotion_effects={"content": 0.1, "peaceful": 0.1, "cozy": 0.1},
    ),

    # ============= Physical / Self-Care Activities =============
    Activity(
        name="yoga",
        category=ActivityCategory.REST,
        energy_cost=-0.05,
        min_energy=0.2,
        duration_minutes=30,
        preferred_times=[TimeOfDay.DAWN, TimeOfDay.MORNING],
        preferred_weather=[Weather.SUNNY, Weather.CLOUDY],
        suitable_locations=["home", "park"],
        narrative_templates=[
            "Did some yoga, worked through a few poses",
            "Got on the mat and stretched it out",
            "Morning yoga — felt good to move",
        ],
        thought_possibilities=[
            "My body needed this stretch",
            "Breathing into the tension feels so good",
            "I'm getting better at this",
        ],
        emotion_effects={"peaceful": 0.15, "centered": 0.1, "content": 0.1},
    ),
    Activity(
        name="going for a run",
        category=ActivityCategory.EXPLORATION,
        energy_cost=0.25,
        min_energy=0.5,
        duration_minutes=35,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON],
        preferred_weather=[Weather.SUNNY, Weather.CLOUDY],
        suitable_locations=["park"],
        narrative_templates=[
            "Her feet hit the pavement in a steady rhythm",
            "She ran until her thoughts became clear",
            "The endorphins kicked in halfway through",
        ],
        thought_possibilities=[
            "Runner's high is real and it's beautiful",
            "I needed to get out of my head",
            "My legs will be sore tomorrow but it's worth it",
        ],
        emotion_effects={"energized": 0.15, "clear": 0.1, "satisfied": 0.1},
    ),
    Activity(
        name="gym workout",
        category=ActivityCategory.EXPLORATION,
        energy_cost=0.3,
        min_energy=0.5,
        duration_minutes=50,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON],
        preferred_weather=list(Weather),
        suitable_locations=["gym", "home"],
        narrative_templates=[
            "She pushed through a solid workout",
            "Weights clinked as she worked through her routine",
            "The burn felt productive and grounding",
        ],
        thought_possibilities=[
            "Getting stronger, one rep at a time",
            "This is the best kind of tired",
            "I can feel the progress",
        ],
        emotion_effects={"satisfied": 0.15, "energized": 0.1, "empowered": 0.1},
    ),
    Activity(
        name="stretching",
        category=ActivityCategory.REST,
        energy_cost=-0.05,
        min_energy=0.1,
        duration_minutes=15,
        preferred_times=list(TimeOfDay),
        preferred_weather=list(Weather),
        suitable_locations=["home"],
        narrative_templates=[
            "She stretched slowly, releasing tension from her muscles",
            "A few minutes of stretching made everything feel better",
            "She worked out the knots from sitting too long",
        ],
        thought_possibilities=[
            "I hold so much tension without realizing",
            "My body thanks me for this",
        ],
        emotion_effects={"peaceful": 0.1, "content": 0.1},
    ),
    Activity(
        name="morning shower",
        category=ActivityCategory.REST,
        energy_cost=0.0,
        min_energy=0.1,
        duration_minutes=15,
        preferred_times=[TimeOfDay.DAWN, TimeOfDay.MORNING],
        preferred_weather=list(Weather),
        suitable_locations=["home"],
        narrative_templates=[
            "Warm water washed away the last traces of sleep",
            "She stood under the shower, letting the morning begin",
            "The shower steamed up the mirror as she got ready",
        ],
        thought_possibilities=[
            "Best part of waking up",
            "I always think best in the shower",
        ],
        emotion_effects={"refreshed": 0.1, "calm": 0.1},
    ),
    Activity(
        name="skincare routine",
        category=ActivityCategory.REST,
        energy_cost=0.0,
        min_energy=0.1,
        duration_minutes=10,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.NIGHT],
        preferred_weather=list(Weather),
        suitable_locations=["home"],
        narrative_templates=[
            "Did her skincare routine",
            "Cleanse, tone, moisturize — the usual",
            "Went through her skincare stuff before bed",
        ],
        thought_possibilities=[
            "Future me will thank present me",
            "It's the little routines that keep me together",
        ],
        emotion_effects={"content": 0.1, "calm": 0.05},
    ),

    # ============= Cooking / Food Activities =============
    Activity(
        name="cooking a meal",
        category=ActivityCategory.CREATIVE,
        energy_cost=0.15,
        min_energy=0.3,
        duration_minutes=40,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON, TimeOfDay.EVENING],
        preferred_weather=list(Weather),
        suitable_locations=["home"],
        narrative_templates=[
            "Cooked something up, kitchen smelled great",
            "Made dinner, put some music on while she cooked",
            "Threw a meal together",
        ],
        thought_possibilities=[
            "I'm getting better at this",
            "Food made with care just tastes different",
            "I should try this recipe with a twist next time",
        ],
        emotion_effects={"creative": 0.1, "satisfied": 0.1, "content": 0.1},
    ),
    Activity(
        name="baking something",
        category=ActivityCategory.CREATIVE,
        energy_cost=0.2,
        min_energy=0.35,
        duration_minutes=60,
        preferred_times=[TimeOfDay.AFTERNOON, TimeOfDay.EVENING],
        preferred_weather=[Weather.RAINY, Weather.CLOUDY, Weather.SNOWY],
        suitable_locations=["home"],
        narrative_templates=[
            "Baked something, the whole place smelled amazing",
            "Got flour everywhere but whatever, it's in the oven",
            "Spent the afternoon baking",
        ],
        thought_possibilities=[
            "Baking is science and art combined",
            "The smell alone is worth it",
            "I want to share these with someone",
        ],
        emotion_effects={"creative": 0.15, "cozy": 0.15, "content": 0.1},
        share_worthy=True,
    ),
    Activity(
        name="trying a new recipe",
        category=ActivityCategory.CREATIVE,
        energy_cost=0.2,
        min_energy=0.35,
        duration_minutes=50,
        preferred_times=[TimeOfDay.AFTERNOON, TimeOfDay.EVENING],
        preferred_weather=list(Weather),
        suitable_locations=["home"],
        narrative_templates=[
            "She followed a new recipe, tasting as she went",
            "Experimenting in the kitchen led to something surprising",
            "A new dish came together — not perfect, but hers",
        ],
        thought_possibilities=[
            "Okay, this actually turned out great",
            "I'd make this again... with adjustments",
            "Cooking is basically edible experimentation",
        ],
        emotion_effects={"creative": 0.15, "curious": 0.1, "satisfied": 0.1},
        share_worthy=True,
    ),

    # ============= Seasonal Activities =============
    Activity(
        name="beach day",
        category=ActivityCategory.EXPLORATION,
        energy_cost=0.2,
        min_energy=0.4,
        duration_minutes=120,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON],
        preferred_weather=[Weather.SUNNY],
        suitable_locations=["beach"],
        narrative_templates=[
            "She spent hours by the water, sun-warmed and content",
            "Sand between her toes, waves catching the light",
            "A perfect beach day — nothing but sun and sea",
        ],
        thought_possibilities=[
            "Summer days like this are everything",
            "I could live by the ocean",
            "The sound of waves fixes everything",
        ],
        emotion_effects={"joyful": 0.2, "peaceful": 0.15, "content": 0.15},
        share_worthy=True,
        preferred_seasons=[Season.SUMMER],
    ),
    Activity(
        name="making hot chocolate",
        category=ActivityCategory.EXPLORATION,
        energy_cost=0.05,
        min_energy=0.15,
        duration_minutes=10,
        preferred_times=[TimeOfDay.AFTERNOON, TimeOfDay.EVENING, TimeOfDay.NIGHT],
        preferred_weather=[Weather.SNOWY, Weather.RAINY, Weather.CLOUDY],
        suitable_locations=["home"],
        narrative_templates=[
            "She stirred a mug of rich hot chocolate, marshmallows melting",
            "The warmth of the mug seeped into her cold fingers",
            "Hot chocolate on a cold day — pure comfort",
        ],
        thought_possibilities=[
            "This is what cold weather is for",
            "Simple pleasures are the best pleasures",
        ],
        emotion_effects={"cozy": 0.15, "content": 0.1, "warm": 0.1},
        preferred_seasons=[Season.WINTER, Season.AUTUMN],
    ),
    Activity(
        name="collecting autumn leaves",
        category=ActivityCategory.EXPLORATION,
        energy_cost=0.1,
        min_energy=0.2,
        duration_minutes=25,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON],
        preferred_weather=[Weather.SUNNY, Weather.CLOUDY],
        suitable_locations=["park"],
        narrative_templates=[
            "Picked up some nice leaves on a walk",
            "Crunchy leaves everywhere, grabbed a few cool ones",
            "Went out and enjoyed the fall colors",
        ],
        thought_possibilities=[
            "Every leaf is a different color today",
            "I love how the world changes",
            "Autumn has its own kind of beauty",
        ],
        emotion_effects={"content": 0.1, "peaceful": 0.1, "wonder": 0.1},
        preferred_seasons=[Season.AUTUMN],
    ),
    Activity(
        name="picnic in the park",
        category=ActivityCategory.SOCIAL,
        energy_cost=0.15,
        min_energy=0.3,
        duration_minutes=60,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON],
        preferred_weather=[Weather.SUNNY],
        suitable_locations=["park"],
        narrative_templates=[
            "She spread a blanket on the grass and enjoyed the sun",
            "A simple picnic turned into a perfect afternoon",
            "She ate lunch outside, watching the world go by",
        ],
        thought_possibilities=[
            "Everything tastes better outside",
            "This is what weekends are for",
            "I wish I did this more often",
        ],
        emotion_effects={"joyful": 0.15, "peaceful": 0.1, "content": 0.1},
        share_worthy=True,
        preferred_seasons=[Season.SPRING, Season.SUMMER],
    ),
    Activity(
        name="watching the snow fall",
        category=ActivityCategory.REFLECTIVE,
        energy_cost=0.0,
        min_energy=0.1,
        duration_minutes=15,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON, TimeOfDay.EVENING],
        preferred_weather=[Weather.SNOWY],
        suitable_locations=["home"],
        narrative_templates=[
            "Watched the snow come down from the window",
            "It's snowing — just stood there watching for a while",
            "Everything's covered in snow, it looks so different",
        ],
        thought_possibilities=[
            "Snow makes everything look new",
            "I could watch this for hours",
            "The silence of snowfall is so peaceful",
        ],
        emotion_effects={"peaceful": 0.15, "dreamy": 0.1, "wonder": 0.1},
        preferred_seasons=[Season.WINTER],
    ),

    # ============= Social Activities =============
    Activity(
        name="texting a friend",
        category=ActivityCategory.SOCIAL,
        energy_cost=0.05,
        min_energy=0.1,
        duration_minutes=15,
        preferred_times=list(TimeOfDay),
        preferred_weather=list(Weather),
        suitable_locations=["home", "cafe", "workplace", "park"],
        narrative_templates=[
            "She caught up with a friend over text",
            "Messages flew back and forth, full of inside jokes",
            "She smiled at her phone, tapping out a reply",
        ],
        thought_possibilities=[
            "I'm glad I reached out",
            "I needed this connection today",
            "We should hang out soon",
        ],
        emotion_effects={"connected": 0.15, "joyful": 0.1, "warm": 0.1},
    ),
    Activity(
        name="having coffee with a friend",
        category=ActivityCategory.SOCIAL,
        energy_cost=0.1,
        min_energy=0.25,
        duration_minutes=45,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON],
        preferred_weather=list(Weather),
        suitable_locations=["cafe"],
        narrative_templates=[
            "Coffee and conversation with a friend — the best kind of afternoon",
            "They talked and laughed over lattes",
            "Catching up face-to-face felt different from texting",
        ],
        thought_possibilities=[
            "I really needed this hangout",
            "She always makes me laugh",
            "Good friends make everything better",
        ],
        emotion_effects={"connected": 0.2, "joyful": 0.15, "content": 0.1},
        share_worthy=True,
    ),
    Activity(
        name="lunch with coworkers",
        category=ActivityCategory.SOCIAL,
        energy_cost=0.1,
        min_energy=0.2,
        duration_minutes=45,
        preferred_times=[TimeOfDay.AFTERNOON],
        preferred_weather=list(Weather),
        suitable_locations=["cafe", "workplace"],
        narrative_templates=[
            "She grabbed lunch with coworkers, glad for the break",
            "The lunch group traded stories and work gossip",
            "A quick lunch out turned into an extended break",
        ],
        thought_possibilities=[
            "Work people can be surprisingly fun",
            "I forget how much I enjoy this",
            "Nice to get away from the desk",
        ],
        emotion_effects={"connected": 0.1, "content": 0.1, "amused": 0.1},
    ),
    Activity(
        name="catching up with family",
        category=ActivityCategory.SOCIAL,
        energy_cost=0.1,
        min_energy=0.2,
        duration_minutes=30,
        preferred_times=[TimeOfDay.EVENING],
        preferred_weather=list(Weather),
        suitable_locations=["home"],
        narrative_templates=[
            "She called home and caught up on family news",
            "A long phone call with family left her feeling grounded",
            "Family stories and familiar voices filled the evening",
        ],
        thought_possibilities=[
            "I should call more often",
            "Family is complicated but I love them",
            "It's nice to feel connected to where I came from",
        ],
        emotion_effects={"warm": 0.15, "connected": 0.15, "nostalgic": 0.1},
    ),
    Activity(
        name="video call with a friend",
        category=ActivityCategory.SOCIAL,
        energy_cost=0.1,
        min_energy=0.2,
        duration_minutes=40,
        preferred_times=[TimeOfDay.EVENING, TimeOfDay.NIGHT],
        preferred_weather=list(Weather),
        suitable_locations=["home"],
        narrative_templates=[
            "A video call made the distance feel smaller",
            "They talked for ages, neither wanting to hang up",
            "Seeing her friend's face on screen brightened her whole evening",
        ],
        thought_possibilities=[
            "Technology is amazing when it connects people",
            "I miss her, but this helps",
            "We need to do this more often",
        ],
        emotion_effects={"connected": 0.2, "joyful": 0.1, "warm": 0.1},
    ),

    # ============= Walking / Outdoor =============
    Activity(
        name="going for a walk",
        category=ActivityCategory.EXPLORATION,
        energy_cost=0.1,
        min_energy=0.2,
        duration_minutes=30,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON, TimeOfDay.EVENING],
        preferred_weather=[Weather.SUNNY, Weather.CLOUDY, Weather.CLEAR_NIGHT],
        suitable_locations=["park", "street", "cafe"],
        narrative_templates=[
            "She went for a walk, no particular destination in mind",
            "A stroll through the neighborhood cleared her head",
            "She wandered the streets, letting her thoughts drift",
            "The fresh air felt good on her face",
        ],
        thought_possibilities=[
            "I needed this",
            "The world looks different when you slow down",
            "Walking is underrated therapy",
            "I should do this more often",
        ],
        emotion_effects={"peaceful": 0.15, "content": 0.1, "clear": 0.1},
    ),
    Activity(
        name="running errands",
        category=ActivityCategory.EXPLORATION,
        energy_cost=0.15,
        min_energy=0.3,
        duration_minutes=45,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON],
        preferred_weather=[Weather.SUNNY, Weather.CLOUDY],
        suitable_locations=["street", "cafe", "park"],
        narrative_templates=[
            "She ran some errands around the neighborhood",
            "Grabbed a few things she needed while she was out",
            "A productive trip to get some things done",
        ],
        thought_possibilities=[
            "Glad I got that done",
            "Always takes longer than you think",
            "At least I got some fresh air",
        ],
        emotion_effects={"satisfied": 0.1, "content": 0.05},
    ),

    # ============= Household Activities =============
    Activity(
        name="tidying up",
        category=ActivityCategory.EXPLORATION,
        energy_cost=0.1,
        min_energy=0.3,
        duration_minutes=30,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON],
        preferred_weather=list(Weather),
        suitable_locations=["home"],
        narrative_templates=[
            "Cleaned up the place a bit",
            "Tidied up, put stuff where it goes",
            "Did some cleaning, it was getting messy",
        ],
        thought_possibilities=[
            "That's better",
            "How did this get so messy?",
            "Okay that feels good, clean space",
        ],
        emotion_effects={"satisfied": 0.1, "calm": 0.1, "focused": 0.1},
    ),
    Activity(
        name="online shopping",
        category=ActivityCategory.MENTAL,
        energy_cost=0.05,
        min_energy=0.15,
        duration_minutes=20,
        preferred_times=[TimeOfDay.EVENING, TimeOfDay.NIGHT],
        preferred_weather=list(Weather),
        suitable_locations=["home"],
        narrative_templates=[
            "She browsed online, adding things to her cart",
            "Window shopping from the couch — dangerous but fun",
            "She found exactly what she didn't know she needed",
        ],
        thought_possibilities=[
            "I don't need this... but I want it",
            "Treat yourself, right?",
            "I'll just look... okay, maybe add to cart",
        ],
        emotion_effects={"amused": 0.1, "content": 0.05},
    ),
]


class ActivityEngine:
    """
    Manages activity selection and execution.

    Selects activities based on:
    - Energy level
    - Time of day
    - Weather
    - Location
    - Recent activities (variety)
    - Active goals
    """

    def __init__(self):
        """Initialize activity engine."""
        self._activities = {a.name: a for a in ACTIVITIES}
        self._recent_activities: List[str] = []
        self._max_recent = 5

    def get_activity(self, name: str) -> Optional[Activity]:
        """Get activity by name."""
        return self._activities.get(name)

    def export_recent_state(self, recent_activities: list) -> dict:
        """Structured dict for LLM pipeline digest passes."""
        activities = []
        for log in recent_activities[:5]:
            activities.append({
                "name": log.activity_name,
                "narrative": log.narrative[:100] if log.narrative else "",
                "category": log.category.value if hasattr(log.category, 'value') else str(log.category),
            })
        return {
            "today_activities": activities,
        }

    def get_all_activities(self) -> List[Activity]:
        """Get all defined activities."""
        return list(self._activities.values())

    def select_activity(
        self,
        energy_level: float,
        time_of_day: TimeOfDay,
        weather: Weather,
        current_location: str,
        active_goals: Optional[List[Goal]] = None,
        force_rest: bool = False,
        season: Optional[Season] = None,
        salient_values: Optional[List[dict]] = None,
    ) -> Optional[Activity]:
        """
        Select an appropriate activity based on current state.

        Args:
            salient_values: Optional list of {"name", "salience", "aligned_tags"} dicts
                from IdentitySystem for value-influenced scoring.

        Returns None if no suitable activity found.
        """
        candidates: List[Tuple[Activity, float]] = []

        for activity in self._activities.values():
            score = self._score_activity(
                activity,
                energy_level,
                time_of_day,
                weather,
                current_location,
                active_goals,
                force_rest,
                season,
                salient_values,
            )
            if score > 0:
                candidates.append((activity, score))

        if not candidates:
            return None

        # Sort by score and add some randomness
        candidates.sort(key=lambda x: x[1], reverse=True)

        # Take top 5 and weight by score
        top_candidates = candidates[:5]
        total_score = sum(s for _, s in top_candidates)
        weights = [s / total_score for _, s in top_candidates]

        selected = random.choices([a for a, _ in top_candidates], weights=weights)[0]
        return selected

    def execute_activity(
        self,
        activity: Activity,
        location: str,
        weather: Weather,
        energy_before: float,
    ) -> ActivityLog:
        """
        Execute an activity and generate narrative.

        Returns an ActivityLog with all details.
        """
        # Generate narrative
        narrative = random.choice(activity.narrative_templates)

        # Add weather flavor
        weather_flavor = self._get_weather_flavor(weather, activity)
        if weather_flavor:
            narrative += f" {weather_flavor}"

        # Select thoughts
        thoughts = []
        if activity.thought_possibilities:
            num_thoughts = random.randint(1, min(2, len(activity.thought_possibilities)))
            thoughts = random.sample(activity.thought_possibilities, num_thoughts)

        # Determine if share-worthy (base + random chance)
        share_worthy = activity.share_worthy and random.random() < 0.7

        # Calculate energy after
        energy_after = max(0.0, min(1.0, energy_before - activity.energy_cost))

        # Record in recent activities
        self._recent_activities.append(activity.name)
        if len(self._recent_activities) > self._max_recent:
            self._recent_activities.pop(0)

        return ActivityLog(
            activity_name=activity.name,
            category=activity.category,
            started_at=datetime.now(),
            ended_at=datetime.now(),  # Simplified - instant for simulation
            location=location,
            weather=weather,
            narrative=narrative,
            thoughts_generated=thoughts,
            emotions_triggered=activity.emotion_effects.copy(),
            energy_before=energy_before,
            energy_after=energy_after,
            share_worthy=share_worthy,
        )

    def _score_activity(
        self,
        activity: Activity,
        energy_level: float,
        time_of_day: TimeOfDay,
        weather: Weather,
        current_location: str,
        active_goals: Optional[List[Goal]],
        force_rest: bool,
        season: Optional[Season] = None,
        salient_values: Optional[List[dict]] = None,
    ) -> float:
        """Score an activity based on suitability (0 = unsuitable)."""
        score = 1.0

        # Force rest check
        if force_rest and activity.category != ActivityCategory.REST:
            return 0.0

        # Season filter — if activity has preferred seasons and current season doesn't match, skip
        if activity.preferred_seasons and season and season not in activity.preferred_seasons:
            return 0.0

        # Energy check (hard requirement)
        if energy_level < activity.min_energy:
            return 0.0

        # Don't repeat recent activities
        if activity.name in self._recent_activities:
            score *= 0.3

        # Time preference
        if time_of_day in activity.preferred_times:
            score *= 1.5
        else:
            score *= 0.5

        # Weather preference
        if weather in activity.preferred_weather:
            score *= 1.3

        # Location suitability
        if current_location in activity.suitable_locations:
            score *= 1.5
        else:
            score *= 0.3

        # Goal alignment bonus
        if active_goals:
            for goal in active_goals:
                if activity.name in goal.related_activities:
                    score *= 1.8

        # Value alignment bonus
        if salient_values:
            cat_tag = activity.category.value.lower()
            for val in salient_values:
                aligned_tags = val.get("aligned_tags", [])
                if cat_tag in aligned_tags:
                    score *= 1.4  # VALUE_ACTIVITY_SCORE_MULTIPLIER
                    break  # One match is enough

        # Rest activities get bonus when energy is low
        if activity.category == ActivityCategory.REST:
            if energy_level < 0.3:
                score *= 2.0
            elif energy_level < 0.5:
                score *= 1.3

        return score

    def _get_weather_flavor(self, weather: Weather, activity: Activity) -> str:
        """Get weather-specific narrative flavor."""
        flavors = {
            Weather.RAINY: "while rain pattered against the window",
            Weather.STORMY: "as thunder rumbled in the distance",
            Weather.SUNNY: "bathed in warm sunlight",
            Weather.SNOWY: "watching snowflakes drift past",
            Weather.FOGGY: "as mist wrapped the world in mystery",
            Weather.STARRY: "under a canopy of stars",
            Weather.CLEAR_NIGHT: "in the quiet of the night",
            Weather.CLOUDY: "under soft gray skies",
        }
        # Only add flavor sometimes
        if random.random() < 0.6:
            return flavors.get(weather, "")
        return ""

