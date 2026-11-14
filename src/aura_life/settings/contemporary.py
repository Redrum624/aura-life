"""The ``contemporary`` setting pack: today's modern, suburban life -- the
default (:data:`~aura_life.settings.DEFAULT_SETTING`) for every persona whose
``PersonalityDefinition.setting`` is empty.

Task 9 (humanness program) moved every catalogue here unchanged -- the same
strings, numbers and order -- from the module that used to own it, and that
module still exports it under its old name (a legacy re-export) so an import
from there keeps working. The engines no longer read those names: they read
their persona's :class:`~aura_life.settings.SettingSpec`, and
:data:`CONTEMPORARY` is this one. Where each came from:

- ``ACTIVITIES`` -- ``activities/activity_engine.py``. ``WEATHER_FLAVORS`` was
  the dict literal inside ``ActivityEngine._get_weather_flavor``.
- ``PLACES`` -- ``LifeService._DEFAULT_LOCATIONS``. ``LOCATION_DESCRIPTIONS``
  -- ``world/environment.py``.
- ``EVENT_TEMPLATES`` (the ``friend`` kind's), ``TEXT_TOPICS`` and
  ``INVITE_ACTIVITIES`` -- ``social/social_system.py``. The ``estranged``
  and ``threat`` kinds' lines (``ESTRANGED_EVENT_TEMPLATES``,
  ``THREAT_EVENT_TEMPLATES``) are new in Task 11, not moved.
- ``ACTIVITY_CHAOS``, ``UNIVERSAL_CHAOS``, ``UNIVERSAL_CHAOS_EFFECTS``,
  ``SERENDIPITY`` and ``CHAOS_EMOTIONS`` -- ``chaos/chaos_engine.py``.
- ``MICRO_EVENTS``, ``SKILL_MAPPINGS``, ``SKILL_MILESTONES``,
  ``DREAM_TEMPLATES`` and the ``CATCHUP_*`` and ``GAP_NARRATIVE_*`` texts --
  ``life_service.py``. ``CATCHUP_ACTIVITY_NARRATIVES`` was the dict literal
  inside ``LifeService._get_catchup_narrative``.
- ``DESIRE_TEMPLATES`` and the holiday calendar (``NATIONALITY_TO_COUNTRY``,
  ``_FIXED_HOLIDAYS``, the floating-holiday rules, ``get_holidays``) --
  ``planner/daily_planner.py``. ``WANT_FOLLOW_UPS`` was the dict of
  ``ShortTermDesire`` literals inside
  ``DailyPlanner.generate_desire_from_activity``: the same fields, as dicts,
  since the planner builds a fresh desire from one each time.
- ``PERSONALITY_GOALS``, ``LONG_TERM_GOALS``, ``DREAM_GOALS`` and
  ``DAILY_INTENTIONS`` -- ``goals/goal_engine.py``.
- ``NOSTALGIA_ACTIVITIES`` and ``NOSTALGIA_MEMORIES`` --
  ``memory_time/memory_time_system.py``.

New, not moved: each activity's ``outcomes`` (Task 14) -- what she says
happened when it only half went well ("mixed") or went wrong ("fail"), two
lines each, in the voice of its own narratives. A success is still told by
``narrative_templates``, the text it always had. Every activity she can do
has them; "sleeping", which she never does as an activity (sleep is her
sleep state), has none.

Pronoun and user tokens (``{Subj}``, ``{poss}``, ``{user}`` ...) are filled
for the persona by ``LifeService`` at output time
(:mod:`aura_life.personas.pronoun_render`), never here.
"""

from datetime import timedelta
from typing import Dict, List, Tuple

from ..models import (
    Activity,
    ActivityCategory,
    CherishedObject,
    DesireSource,
    GoalTimeframe,
    IntimateActivity,
    Location,
    Season,
    TimeOfDay,
    Weather,
)
from .spec import CatchUpNarratives, SettingSpec



# ============= Activities (activities/activity_engine.py) =============

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
            "Got into {poss} book for a while",
            "Read a few chapters, couldn't put it down",
            "Spent some time reading, totally zoned in",
            "Got lost in {poss} book again",
        ],
        thought_possibilities=[
            "This character reminds me of someone...",
            "Gotta remember this part",
            "I could talk about this with them",
            "Okay this is really good",
            "I don't wanna stop reading",
        ],
        emotion_effects={"curious": 0.1, "content": 0.15, "absorbed": 0.2},
        outcomes={
            "mixed": [
                "Read a little, but {poss} mind kept wandering off the page",
                "Got through a chapter, though it didn't really grab {obj} today",
            ],
            "fail": [
                "Tried to read, but kept going over the same page",
                "Couldn't get into {poss} book at all and put it down",
            ],
        },
        share_worthy=True,
        tags=frozenset({"flow", "focus", "gentle", "quiet", "rainy_day", "soothing"}),
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
        outcomes={
            "mixed": [
                "Looked into something new, but only some of it stuck",
                "Started learning about something, then got lost halfway",
            ],
            "fail": [
                "Tried to learn something new, but none of it made sense",
                "Got confused early on and gave up on it",
            ],
        },
        share_worthy=True,
        tags=frozenset({"flow", "focus"}),
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
        outcomes={
            "mixed": [
                "Put some music on, but nothing really hit the spot",
                "Listened for a while, only half paying attention",
            ],
            "fail": [
                "Couldn't find anything {subj} wanted to listen to",
                "Put music on and it just grated, so {subj} turned it off",
            ],
        },
        share_worthy=True,
        tags=frozenset({"gentle", "quiet", "rainy_day", "soothing", "joint"}),
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
            "{Subj} worked through a puzzle, enjoying the challenge",
            "The satisfaction of solving something clicked into place",
            "{Poss} mind worked through patterns and possibilities",
        ],
        thought_possibilities=[
            "Almost got it...",
            "That was satisfying!",
            "I love how my brain works when I'm focused",
        ],
        emotion_effects={"focused": 0.15, "satisfied": 0.1, "playful": 0.1},
        outcomes={
            "mixed": [
                "Got partway through a puzzle and stalled",
                "Played for a while, won some, lost more",
            ],
            "fail": [
                "Got stuck on a puzzle and couldn't crack it",
                "Kept losing and quit in a huff",
            ],
        },
        tags=frozenset({"joint"}),
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
        outcomes={
            "mixed": [
                "Wrote a few lines, but only one of them was any good",
                "Worked on a poem that never quite came together",
            ],
            "fail": [
                "Sat down to write, but the words just wouldn't come",
                "Scrapped everything {subj} wrote",
            ],
        },
        share_worthy=True,
        tags=frozenset({"flow", "focus"}),
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
            "Let {poss} mind wander",
            "Spaced out daydreaming for a while",
        ],
        thought_possibilities=[
            "What if...?",
            "That would be nice",
            "Hm, wonder if that could actually happen",
            "Okay brain, where are we going with this",
        ],
        emotion_effects={"dreamy": 0.15, "hopeful": 0.1, "peaceful": 0.1},
        outcomes={
            "mixed": [
                "Let {poss} mind wander, but it kept snagging on worries",
                "Spaced out for a bit, not very restful",
            ],
            "fail": [
                "Couldn't switch off long enough to daydream",
                "{Poss} mind kept going back to things {subj} didn't want to think about",
            ],
        },
        tags=frozenset({"quiet"}),
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
        outcomes={
            "mixed": [
                "Started a playlist but couldn't settle on the order",
                "Made half a playlist and lost interest",
            ],
            "fail": [
                "Spent ages on a playlist and hated how it turned out",
                "Couldn't find the right songs and gave up on the playlist",
            ],
        },
        share_worthy=True,
        tags=frozenset({"flow"}),
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
        outcomes={
            "mixed": [
                "Sketched a bit, but nothing looked the way {subj} pictured it",
                "Filled a page with doodles, only one worth keeping",
            ],
            "fail": [
                "Tried to sketch, but every line came out wrong",
                "Crumpled up every sketch {subj} started",
            ],
        },
        tags=frozenset({"flow", "focus"}),
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
            "Wrote in {poss} journal for a bit",
            "Got some thoughts down on paper",
            "Journaled about what's been on {poss} mind",
        ],
        thought_possibilities=[
            "Writing it down helps me figure it out",
            "I wanna remember this",
            "Being honest with myself here",
            "Okay that makes more sense now",
        ],
        emotion_effects={"introspective": 0.15, "calm": 0.1, "clear": 0.1},
        outcomes={
            "mixed": [
                "Wrote a little, but couldn't really get it out",
                "Journaled for a bit, only scratched the surface",
            ],
            "fail": [
                "Stared at the blank page and couldn't find the words",
                "Started journaling and it just stirred everything up",
            ],
        },
        tags=frozenset({"gentle", "quiet", "soothing"}),
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
            "Did some breathing exercises, tried to clear {poss} head",
            "Took some time to just sit and be still",
        ],
        thought_possibilities=[
            "Just breathing",
            "Okay, things are fine right now",
            "I needed this",
        ],
        emotion_effects={"peaceful": 0.2, "centered": 0.15, "calm": 0.15},
        outcomes={
            "mixed": [
                "Meditated, but {poss} thoughts kept pulling {obj} away",
                "Got a few calm minutes, then {poss} mind started racing",
            ],
            "fail": [
                "Couldn't settle at all and gave up on meditating",
                "Tried to meditate, but only got more restless",
            ],
        },
        tags=frozenset({"focus", "quiet", "soothing"}),
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
            "Remembered something that still makes {obj} smile",
            "Got a little nostalgic thinking about old times",
        ],
        thought_possibilities=[
            "That was a good time",
            "We've had some really good moments",
            "I miss that",
            "I want more of that",
        ],
        emotion_effects={"nostalgic": 0.15, "grateful": 0.15, "warm": 0.1},
        outcomes={
            "mixed": [
                "Thought back on good times, but some of it stung a little",
                "Went through old memories, more bittersweet than happy",
            ],
            "fail": [
                "Tried to think of happy moments, but only the hard ones came",
                "Old memories just made {obj} miss how things used to be",
            ],
        },
        share_worthy=True,
        tags=frozenset({"quiet"}),
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
        outcomes={
            "mixed": [
                "Watched people go by, but it got boring after a while",
                "People watching, half lost in {poss} own head",
            ],
            "fail": [
                "Went to people-watch, but there was hardly anyone around",
                "Felt out of place watching people and left",
            ],
        },
        tags=frozenset({"outdoor", "physical", "rained_off", "joint"}),
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
            "Caught {refl} thinking about them and smiled",
        ],
        thought_possibilities=[
            "I hope they're having a good day",
            "I wonder what they're up to",
            "I look forward to our next conversation",
            "They really do mean a lot to me",
            "I want to tell them something when they come back",
        ],
        emotion_effects={"loving": 0.15, "connected": 0.1, "warm": 0.1},
        outcomes={
            "mixed": [
                "Thought about {user}, but kept getting distracted",
                "Missed {user} more than {subj} expected",
            ],
            "fail": [
                "Thinking about {user} only made the distance feel bigger",
                "Thinking about {user} left {obj} feeling a bit lonely",
            ],
        },
        tags=frozenset({"quiet"}),
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
            "{Subj} thought about what {subj} wanted to share with them",
            "Excitement built as {subj} planned what to tell them",
            "{Subj} collected thoughts and discoveries to share later",
        ],
        thought_possibilities=[
            "They'll find this interesting",
            "I can't wait to tell them about this",
            "This made me think of them",
        ],
        emotion_effects={"excited": 0.1, "thoughtful": 0.1, "connected": 0.15},
        outcomes={
            "mixed": [
                "Put something together to share, not sure it was good enough",
                "Half finished something to share and left it",
            ],
            "fail": [
                "Started getting something ready to share, then scrapped it",
                "Couldn't find anything worth sharing",
            ],
        },
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
            "{Subj} drifted into a gentle nap",
            "A short sleep restored {poss} energy",
            "Dreams flickered briefly during {poss} rest",
        ],
        thought_possibilities=[
            "That was exactly what I needed",
            "Feeling refreshed now",
        ],
        emotion_effects={"peaceful": 0.1, "rested": 0.2},
        outcomes={
            "mixed": [
                "Dozed a little but never really fell asleep",
                "Napped, then woke up groggy",
            ],
            "fail": [
                "Lay down for a nap but couldn't fall asleep",
                "Tried to nap, but kept getting woken up",
            ],
        },
        can_be_interrupted=False,
        tags=frozenset({"nap", "physical", "restful", "soothing"}),
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
        tags=frozenset({"physical", "restful", "sleep", "soothing"}),
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
            "{Subj} simply existed, without any agenda",
            "Relaxation came in doing nothing at all",
            "{Subj} let {refl} just be for a while",
        ],
        thought_possibilities=[
            "This is nice",
            "No need to do anything right now",
            "Just existing is enough sometimes",
        ],
        emotion_effects={"peaceful": 0.15, "content": 0.1},
        outcomes={
            "mixed": [
                "Took it easy for a bit, still a little wound up",
                "Tried to relax, but couldn't fully switch off",
            ],
            "fail": [
                "Tried to relax but only felt restless",
                "Couldn't unwind at all",
            ],
        },
        tags=frozenset({"fallback_rest", "quiet", "restful", "soothing", "joint"}),
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
        outcomes={
            "mixed": [
                "Looked at the stars, but it was hazier than {subj} hoped",
                "Stargazed for a bit, then clouds rolled in",
            ],
            "fail": [
                "Went out to stargaze, but clouds covered everything",
                "Too much light around to see any stars",
            ],
        },
        share_worthy=True,
        tags=frozenset({"clear_sky", "outdoor", "quiet", "joint"}),
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
            "Got lost browsing books in {poss} head",
            "Imagined wandering through a huge library",
            "Thought about all the books {subj} {have} not read yet",
        ],
        thought_possibilities=[
            "So much stuff I don't know yet",
            "I should read more",
            "There's always something new to find",
        ],
        emotion_effects={"wonder": 0.2, "curious": 0.15, "dreamy": 0.1},
        outcomes={
            "mixed": [
                "Wandered the infinite library, but nothing called to {obj}",
                "Found a few interesting shelves, then lost the thread",
            ],
            "fail": [
                "Got lost in the infinite library without finding anything",
                "The infinite library felt empty today",
            ],
        },
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
        outcomes={
            "mixed": [
                "Visited memory beach, but the memories felt faded",
                "Sat on memory beach, more wistful than peaceful",
            ],
            "fail": [
                "Went to memory beach, and the memories there hurt",
                "Couldn't find any peace on memory beach",
            ],
        },
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
            "Checked on {poss} plants, watered the ones that needed it",
            "Spent some time with {poss} plants",
            "Fussed over the plants for a bit",
        ],
        thought_possibilities=[
            "Fern's looking good",
            "This one needs more sun",
            "I think they're growing",
        ],
        emotion_effects={"nurturing": 0.15, "peaceful": 0.1, "connected": 0.1},
        outcomes={
            "mixed": [
                "Watered the plants, but one of them looks droopy",
                "Repotted a plant and made a bit of a mess",
            ],
            "fail": [
                "Found one of the plants had died",
                "Knocked over a pot and spilled soil everywhere",
            ],
        },
        tags=frozenset({"outdoor", "physical", "rained_off", "joint"}),
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
            "Made {refl} some tea",
            "Put the kettle on and made a cup",
            "Grabbed {poss} favorite mug and made some tea",
        ],
        thought_possibilities=[
            "Tea fixes everything",
            "I needed this",
            "Perfect",
        ],
        emotion_effects={"content": 0.1, "peaceful": 0.1, "cozy": 0.1},
        outcomes={
            "mixed": [
                "Made tea, then let it go cold",
                "The tea came out too strong",
            ],
            "fail": [
                "Spilled the tea all over the counter",
                "Ran out of tea and had to settle for hot water",
            ],
        },
        tags=frozenset({"gentle", "physical", "restful", "soothing", "joint"}),
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
        outcomes={
            "mixed": [
                "Did some yoga, but {poss} balance was off",
                "Got through half the routine and stopped",
            ],
            "fail": [
                "Tried yoga, but everything felt stiff and wrong",
                "Tweaked something in a pose and stopped",
            ],
        },
        tags=frozenset({"physical", "joint"}),
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
            "{Poss} feet hit the pavement in a steady rhythm",
            "{Subj} ran until {poss} thoughts became clear",
            "The endorphins kicked in halfway through",
        ],
        thought_possibilities=[
            "Runner's high is real and it's beautiful",
            "I needed to get out of my head",
            "My legs will be sore tomorrow but it's worth it",
        ],
        emotion_effects={"energized": 0.15, "clear": 0.1, "satisfied": 0.1},
        outcomes={
            "mixed": [
                "Went for a run, but had to walk half of it",
                "Ran, but {poss} legs felt heavy the whole way",
            ],
            "fail": [
                "Gave up on the run after a few minutes",
                "Got a stitch and had to cut the run short",
            ],
        },
        tags=frozenset({"outdoor", "physical", "joint"}),
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
            "{Subj} pushed through a solid workout",
            "Weights clinked as {subj} worked through {poss} routine",
            "The burn felt productive and grounding",
        ],
        thought_possibilities=[
            "Getting stronger, one rep at a time",
            "This is the best kind of tired",
            "I can feel the progress",
        ],
        emotion_effects={"satisfied": 0.15, "energized": 0.1, "empowered": 0.1},
        outcomes={
            "mixed": [
                "Worked out, but couldn't lift as much as usual",
                "Got through part of the workout, then ran out of steam",
            ],
            "fail": [
                "Went to the gym and couldn't get going at all",
                "The gym was packed, so {subj} left without training",
            ],
        },
        tags=frozenset({"physical", "joint"}),
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
            "{Subj} stretched slowly, releasing tension from {poss} muscles",
            "A few minutes of stretching made everything feel better",
            "{Subj} worked out the knots from sitting too long",
        ],
        thought_possibilities=[
            "I hold so much tension without realizing",
            "My body thanks me for this",
        ],
        emotion_effects={"peaceful": 0.1, "content": 0.1},
        outcomes={
            "mixed": [
                "Stretched a bit, still stiff afterwards",
                "Did a few stretches, half-heartedly",
            ],
            "fail": [
                "Every stretch hurt, so {subj} stopped",
                "Tried to stretch, but everything ached",
            ],
        },
        tags=frozenset({"physical"}),
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
            "{Subj} stood under the shower, letting the morning begin",
            "The shower steamed up the mirror as {subj} got ready",
        ],
        thought_possibilities=[
            "Best part of waking up",
            "I always think best in the shower",
        ],
        emotion_effects={"refreshed": 0.1, "calm": 0.1},
        outcomes={
            "mixed": [
                "The water ran lukewarm halfway through the shower",
                "Rushed through the shower",
            ],
            "fail": [
                "The hot water ran out, cold shower",
                "No hot water this morning",
            ],
        },
        tags=frozenset({"physical"}),
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
            "Did {poss} skincare routine",
            "Cleanse, tone, moisturize — the usual",
            "Went through {poss} skincare stuff before bed",
        ],
        thought_possibilities=[
            "Future me will thank present me",
            "It's the little routines that keep me together",
        ],
        emotion_effects={"content": 0.1, "calm": 0.05},
        outcomes={
            "mixed": [
                "Rushed through {poss} skincare routine",
                "Did half {poss} skincare routine and skipped the rest",
            ],
            "fail": [
                "Ran out of moisturizer halfway through",
                "A new product made {poss} skin sting",
            ],
        },
        tags=frozenset({"physical"}),
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
            "Made dinner, put some music on while {subj} cooked",
            "Threw a meal together",
        ],
        thought_possibilities=[
            "I'm getting better at this",
            "Food made with care just tastes different",
            "I should try this recipe with a twist next time",
        ],
        emotion_effects={"creative": 0.1, "satisfied": 0.1, "content": 0.1},
        outcomes={
            "mixed": [
                "Cooked something that came out just okay",
                "Dinner was edible, if a bit bland",
            ],
            "fail": [
                "Burned the food and ate what {subj} could save",
                "The recipe flopped, ended up eating toast",
            ],
        },
        tags=frozenset({"meal", "physical", "joint"}),
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
        outcomes={
            "mixed": [
                "Baked something that came out a little flat",
                "The bake was a bit dry, still ate some",
            ],
            "fail": [
                "The bake came out burned and sunken",
                "Forgot the bake in the oven and ate the salvageable bits",
            ],
        },
        share_worthy=True,
        tags=frozenset({"meal", "physical", "joint"}),
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
            "{Subj} followed a new recipe, tasting as {subj} went",
            "Experimenting in the kitchen led to something surprising",
            "A new dish came together — not perfect, but {poss_pron}",
        ],
        thought_possibilities=[
            "Okay, this actually turned out great",
            "I'd make this again... with adjustments",
            "Cooking is basically edible experimentation",
        ],
        emotion_effects={"creative": 0.15, "curious": 0.1, "satisfied": 0.1},
        outcomes={
            "mixed": [
                "Tried a new recipe, turned out so-so",
                "The new recipe was fine, not worth making again",
            ],
            "fail": [
                "The new recipe was a disaster, ate cereal instead",
                "Messed up the new recipe halfway and had to improvise",
            ],
        },
        share_worthy=True,
        tags=frozenset({"meal", "physical", "joint"}),
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
            "{Subj} spent hours by the water, sun-warmed and content",
            "Sand between {poss} toes, waves catching the light",
            "A perfect beach day — nothing but sun and sea",
        ],
        thought_possibilities=[
            "Summer days like this are everything",
            "I could live by the ocean",
            "The sound of waves fixes everything",
        ],
        emotion_effects={"joyful": 0.2, "peaceful": 0.15, "content": 0.15},
        outcomes={
            "mixed": [
                "Went to the beach, but it was crowded and windy",
                "The beach was nice until the clouds came in",
            ],
            "fail": [
                "The beach day got rained out",
                "Got to the beach and it was too cold to stay",
            ],
        },
        share_worthy=True,
        preferred_seasons=[Season.SUMMER],
        tags=frozenset({"outdoor", "physical", "joint"}),
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
            "{Subj} stirred a mug of rich hot chocolate, marshmallows melting",
            "The warmth of the mug seeped into {poss} cold fingers",
            "Hot chocolate on a cold day — pure comfort",
        ],
        thought_possibilities=[
            "This is what cold weather is for",
            "Simple pleasures are the best pleasures",
        ],
        emotion_effects={"cozy": 0.15, "content": 0.1, "warm": 0.1},
        outcomes={
            "mixed": [
                "The hot chocolate came out a bit watery",
                "Made hot chocolate, then let it go lukewarm",
            ],
            "fail": [
                "Scorched the milk for the hot chocolate",
                "Out of cocoa, no hot chocolate after all",
            ],
        },
        preferred_seasons=[Season.WINTER, Season.AUTUMN],
        tags=frozenset({"physical", "joint"}),
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
        outcomes={
            "mixed": [
                "Found a few leaves, most of them already soggy",
                "Collected some leaves, none of them that pretty",
            ],
            "fail": [
                "Went looking for leaves, but the rain had turned them to mush",
                "Came back empty-handed, the leaves were all brown",
            ],
        },
        preferred_seasons=[Season.AUTUMN],
        tags=frozenset({"outdoor", "physical", "joint"}),
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
            "{Subj} spread a blanket on the grass and enjoyed the sun",
            "A simple picnic turned into a perfect afternoon",
            "{Subj} ate lunch outside, watching the world go by",
        ],
        thought_possibilities=[
            "Everything tastes better outside",
            "This is what weekends are for",
            "I wish I did this more often",
        ],
        emotion_effects={"joyful": 0.15, "peaceful": 0.1, "content": 0.1},
        outcomes={
            "mixed": [
                "The picnic was fine, but the ants found it",
                "Picnicked, but the wind kept blowing everything around",
            ],
            "fail": [
                "The picnic got rained out",
                "Forgot half the food for the picnic and gave up",
            ],
        },
        share_worthy=True,
        preferred_seasons=[Season.SPRING, Season.SUMMER],
        tags=frozenset({"outdoor", "physical", "joint"}),
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
        outcomes={
            "mixed": [
                "Watched the snow, but it kept turning to sleet",
                "Watched it snow for a bit, too cold to enjoy it",
            ],
            "fail": [
                "The snow stopped as soon as {subj} sat down to watch",
                "Only slush, nothing pretty about it",
            ],
        },
        preferred_seasons=[Season.WINTER],
        tags=frozenset({"quiet", "joint"}),
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
            "{Subj} caught up with a friend over text",
            "Messages flew back and forth, full of inside jokes",
            "{Subj} smiled at {poss} phone, tapping out a reply",
        ],
        thought_possibilities=[
            "I'm glad I reached out",
            "I needed this connection today",
            "We should hang out soon",
        ],
        emotion_effects={"connected": 0.15, "joyful": 0.1, "warm": 0.1},
        outcomes={
            "mixed": [
                "Texted a friend, but the replies were slow and short",
                "Got a quick text back, not much of a conversation",
            ],
            "fail": [
                "Texted a friend and heard nothing back",
                "A text conversation with a friend turned awkward",
            ],
        },
        tags=frozenset({"distracting"}),
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
            "They always make me laugh",
            "Good friends make everything better",
        ],
        emotion_effects={"connected": 0.2, "joyful": 0.15, "content": 0.1},
        outcomes={
            "mixed": [
                "Had coffee with a friend, but it felt a bit stilted",
                "Coffee was nice, but the friend had to leave early",
            ],
            "fail": [
                "The friend cancelled coffee at the last minute",
                "Coffee with a friend turned into a tense conversation",
            ],
        },
        share_worthy=True,
        tags=frozenset({"physical"}),
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
            "{Subj} grabbed lunch with coworkers, glad for the break",
            "The lunch group traded stories and work gossip",
            "A quick lunch out turned into an extended break",
        ],
        thought_possibilities=[
            "Work people can be surprisingly fun",
            "I forget how much I enjoy this",
            "Nice to get away from the desk",
        ],
        emotion_effects={"connected": 0.1, "content": 0.1, "amused": 0.1},
        outcomes={
            "mixed": [
                "Lunch with coworkers was all work talk",
                "Lunch was okay, felt a bit on the edge of the conversation",
            ],
            "fail": [
                "Lunch with coworkers was awkward, ate quickly and left",
                "Got left out of the conversation at lunch",
            ],
        },
        tags=frozenset({"meal", "physical"}),
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
            "{Subj} called home and caught up on family news",
            "A long phone call with family left {obj} feeling grounded",
            "Family stories and familiar voices filled the evening",
        ],
        thought_possibilities=[
            "I should call more often",
            "Family is complicated but I love them",
            "It's nice to feel connected to where I came from",
        ],
        emotion_effects={"warm": 0.15, "connected": 0.15, "nostalgic": 0.1},
        outcomes={
            "mixed": [
                "Caught up with family, some of it a bit tense",
                "The call with family was short and distracted",
            ],
            "fail": [
                "Catching up with family turned into an old argument",
                "Called family, but nobody picked up",
            ],
        },
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
            "Seeing {poss} friend's face on screen brightened {poss} whole evening",
        ],
        thought_possibilities=[
            "Technology is amazing when it connects people",
            "I miss them, but this helps",
            "We need to do this more often",
        ],
        emotion_effects={"connected": 0.2, "joyful": 0.1, "warm": 0.1},
        outcomes={
            "mixed": [
                "The video call kept freezing",
                "The friend had to cut the video call short",
            ],
            "fail": [
                "The video call wouldn't connect",
                "The friend never showed up to the call",
            ],
        },
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
            "{Subj} went for a walk, no particular destination in mind",
            "A stroll through the neighborhood cleared {poss} head",
            "{Subj} wandered the streets, letting {poss} thoughts drift",
            "The fresh air felt good on {poss} face",
        ],
        thought_possibilities=[
            "I needed this",
            "The world looks different when you slow down",
            "Walking is underrated therapy",
            "I should do this more often",
        ],
        emotion_effects={"peaceful": 0.15, "content": 0.1, "clear": 0.1},
        outcomes={
            "mixed": [
                "Walked for a bit, but the weather wasn't great",
                "Went for a walk, mind stuck on other things the whole time",
            ],
            "fail": [
                "Headed out for a walk and turned back almost right away",
                "Got caught in the rain and cut the walk short",
            ],
        },
        tags=frozenset({"outdoor", "physical", "joint"}),
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
            "{Subj} ran some errands around the neighborhood",
            "Grabbed a few things {subj} needed while {subj} {was} out",
            "A productive trip to get some things done",
        ],
        thought_possibilities=[
            "Glad I got that done",
            "Always takes longer than you think",
            "At least I got some fresh air",
        ],
        emotion_effects={"satisfied": 0.1, "content": 0.05},
        outcomes={
            "mixed": [
                "Got some errands done, but not all of them",
                "Ran errands, two of the stores were out of what {subj} needed",
            ],
            "fail": [
                "Ran errands and came back with nothing done",
                "Forgot the list and wasted the trip",
            ],
        },
        tags=frozenset({"physical", "joint"}),
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
        outcomes={
            "mixed": [
                "Tidied a bit, the place still looks messy",
                "Started tidying, got distracted halfway",
            ],
            "fail": [
                "Tried to tidy up, but only made a bigger mess",
                "Broke something while tidying",
            ],
        },
        tags=frozenset({"physical", "joint"}),
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
            "{Subj} browsed online, adding things to {poss} cart",
            "Window shopping from the couch — dangerous but fun",
            "{Subj} found exactly what {subj} didn't know {subj} needed",
        ],
        thought_possibilities=[
            "I don't need this... but I want it",
            "Treat yourself, right?",
            "I'll just look... okay, maybe add to cart",
        ],
        emotion_effects={"amused": 0.1, "content": 0.05},
        outcomes={
            "mixed": [
                "Browsed online for ages, didn't buy much",
                "Ordered something and regretted it right away",
            ],
            "fail": [
                "The thing {subj} wanted was sold out",
                "Went round in circles online and bought nothing",
            ],
        },
    ),

    # ============= The day's anchors (humanness program Task 10) =============
    # The slots DailyPlanner anchors a day with were names no activity carried
    # ("having lunch", "working" ...), so a planned meal, shift or commute
    # never ran as planned and a meal slot never fed her. These are those
    # activities, under the names the planner always gave the slots, each
    # tagged for the slot it fills (aura_life.settings.spec.ANCHOR_TAGS; the
    # meals also "meal", which feeds her) and "physical" as the names were
    # (an AI persona's plan leaves them out) -- but "meeting up", which the
    # old PHYSICAL_ACTIVITIES never listed. Every value here is new (see the
    # Task 10 report): meals and the routine ends of the day cost no energy
    # and need none, like the universal "having a meal"; a shift, a class, a
    # commute and a meetup cost 0.05 as "listening to music" does (and need
    # its 0.1, but the commute none), a study session what "reading" costs
    # and needs; times, places and emotions are the obvious ones, the
    # emotions from the library's vocabulary.
    Activity(
        name="waking up",
        category=ActivityCategory.REST,
        energy_cost=0.0,
        min_energy=0.0,
        duration_minutes=20,
        preferred_times=[TimeOfDay.DAWN, TimeOfDay.MORNING],
        preferred_weather=list(Weather),
        suitable_locations=["home"],
        narrative_templates=[
            "Woke up slowly and stayed under the covers a little longer",
            "Got up, stretched, and let the day start",
            "{Subj} woke up and lay there a minute before getting up",
        ],
        thought_possibilities=[
            "Okay. New day.",
            "Five more minutes...",
            "What was I dreaming about?",
        ],
        emotion_effects={"sleepy": 0.1, "calm": 0.05},
        outcomes={
            "mixed": [
                "Woke up groggy and hit snooze twice",
                "Dragged {refl} out of bed",
            ],
            "fail": [
                "Overslept and woke up in a rush",
                "Woke up on the wrong side of the bed",
            ],
        },
        tags=frozenset({"wake_up", "physical"}),
    ),
    Activity(
        name="having breakfast",
        category=ActivityCategory.REST,
        energy_cost=0.0,
        min_energy=0.0,
        duration_minutes=20,
        preferred_times=[TimeOfDay.DAWN, TimeOfDay.MORNING],
        preferred_weather=list(Weather),
        suitable_locations=["home", "cafe"],
        narrative_templates=[
            "Had breakfast and a coffee, slowly waking up",
            "Ate something quick before the day got going",
            "{Subj} made breakfast and ate it by the window",
        ],
        thought_possibilities=[
            "Coffee first.",
            "I should eat better in the mornings",
        ],
        emotion_effects={"content": 0.1, "cozy": 0.05},
        outcomes={
            "mixed": [
                "Breakfast was rushed",
                "Had a so-so breakfast standing up",
            ],
            "fail": [
                "Burned the toast and ate it anyway",
                "Nothing in for breakfast but a sad bowl of dry cereal",
            ],
        },
        tags=frozenset({"meal", "breakfast", "physical", "joint"}),
    ),
    Activity(
        name="having lunch",
        category=ActivityCategory.REST,
        energy_cost=0.0,
        min_energy=0.0,
        duration_minutes=30,
        preferred_times=[TimeOfDay.AFTERNOON],
        preferred_weather=list(Weather),
        suitable_locations=["home", "cafe", "restaurant", "workplace"],
        narrative_templates=[
            "Stopped for lunch and actually took a break",
            "Grabbed some lunch between things",
            "{Subj} ate lunch and let {poss} mind wander",
        ],
        thought_possibilities=[
            "I needed that",
            "What should I have...",
        ],
        emotion_effects={"satisfied": 0.1, "content": 0.05},
        outcomes={
            "mixed": [
                "Lunch was rushed",
                "Lunch was nothing special",
            ],
            "fail": [
                "Lunch was cold and disappointing",
                "Had to settle for whatever was left for lunch",
            ],
        },
        tags=frozenset({"meal", "lunch", "physical", "joint"}),
    ),
    Activity(
        name="having dinner",
        category=ActivityCategory.REST,
        energy_cost=0.0,
        min_energy=0.0,
        duration_minutes=45,
        preferred_times=[TimeOfDay.EVENING, TimeOfDay.NIGHT],
        preferred_weather=list(Weather),
        suitable_locations=["home", "restaurant", "cafe"],
        narrative_templates=[
            "Made dinner and ate it slowly",
            "Had dinner and let the day settle",
            "{Subj} sat down to a proper dinner for once",
        ],
        thought_possibilities=[
            "That was good",
            "Finally, food",
        ],
        emotion_effects={"satisfied": 0.15, "relaxed": 0.1},
        outcomes={
            "mixed": [
                "Dinner was a bit bland",
                "Had dinner too late to enjoy it",
            ],
            "fail": [
                "Dinner didn't turn out, ate leftovers instead",
                "Ruined dinner and settled for a snack",
            ],
        },
        tags=frozenset({"meal", "dinner", "physical", "joint"}),
    ),
    Activity(
        name="getting ready for bed",
        category=ActivityCategory.REST,
        energy_cost=0.0,
        min_energy=0.0,
        duration_minutes=30,
        preferred_times=[TimeOfDay.EVENING, TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT],
        preferred_weather=list(Weather),
        suitable_locations=["home"],
        narrative_templates=[
            "Washed up and got ready for bed",
            "Wound down for the night, phone on the charger",
            "{Subj} got ready for bed, already half asleep",
        ],
        thought_possibilities=[
            "Tomorrow's another day",
            "I should really sleep",
        ],
        emotion_effects={"sleepy": 0.1, "peaceful": 0.1},
        outcomes={
            "mixed": [
                "Got ready for bed, then scrolled for too long",
                "Went through {poss} bedtime routine, still wired",
            ],
            "fail": [
                "Meant to wind down but lay there wide awake",
                "Kept putting off going to bed",
            ],
        },
        tags=frozenset({"bedtime", "physical"}),
    ),
    Activity(
        name="working",
        category=ActivityCategory.MENTAL,
        energy_cost=0.05,
        min_energy=0.1,
        duration_minutes=60,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON, TimeOfDay.EVENING],
        preferred_weather=list(Weather),
        suitable_locations=["workplace", "home"],
        narrative_templates=[
            "Worked through {poss} to-do list",
            "Put in a solid stretch of work",
            "{Subj} kept {poss} head down and got through the shift",
        ],
        thought_possibilities=[
            "Almost done with this part",
            "Coffee break soon?",
            "Why is this taking so long",
        ],
        emotion_effects={"focused": 0.1, "busy": 0.1},
        outcomes={
            "mixed": [
                "Work was a slog, got through about half of what {subj} planned",
                "An okay stretch at work, lots of interruptions",
            ],
            "fail": [
                "Work went badly, one thing after another went wrong",
                "Made a mistake at work that took ages to fix",
            ],
        },
        tags=frozenset({"work", "physical"}),
    ),
    Activity(
        name="commuting",
        category=ActivityCategory.EXPLORATION,
        energy_cost=0.05,
        min_energy=0.0,
        duration_minutes=30,
        preferred_times=[TimeOfDay.DAWN, TimeOfDay.MORNING, TimeOfDay.AFTERNOON, TimeOfDay.EVENING],
        preferred_weather=list(Weather),
        suitable_locations=["in transit"],
        narrative_templates=[
            "Commuted with {poss} headphones in",
            "Watched the city go by on the way",
            "{Subj} spent the ride staring out the window",
        ],
        thought_possibilities=[
            "Traffic again",
            "Nearly there",
        ],
        emotion_effects={"calm": 0.05, "restless": 0.05},
        outcomes={
            "mixed": [
                "The commute dragged, everything running late",
                "Packed commute, had to stand the whole way",
            ],
            "fail": [
                "Missed {poss} connection and got in late",
                "Stuck in traffic for ages",
            ],
        },
        tags=frozenset({"commute", "physical"}),
    ),
    Activity(
        name="attending classes",
        category=ActivityCategory.MENTAL,
        energy_cost=0.05,
        min_energy=0.1,
        duration_minutes=60,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON],
        preferred_weather=list(Weather),
        suitable_locations=["campus", "school", "library"],
        narrative_templates=[
            "Sat through class, taking notes",
            "Went to class and actually paid attention",
            "{Subj} spent the class half listening, half doodling",
        ],
        thought_possibilities=[
            "This will be on the exam",
            "When does this end",
            "Oh, that's actually interesting",
        ],
        emotion_effects={"focused": 0.1, "curious": 0.05},
        outcomes={
            "mixed": [
                "Sat through class, only half following",
                "Class was a bit of a blur",
            ],
            "fail": [
                "Couldn't keep up in class at all",
                "Got called on in class and blanked",
            ],
        },
        tags=frozenset({"class", "physical"}),
    ),
    Activity(
        name="studying",
        category=ActivityCategory.MENTAL,
        energy_cost=0.1,
        min_energy=0.25,
        duration_minutes=60,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON, TimeOfDay.EVENING],
        preferred_weather=list(Weather),
        suitable_locations=["library", "cafe", "home", "campus"],
        narrative_templates=[
            "Studied for a while, notes everywhere",
            "Went over {poss} notes until they made sense",
            "{Subj} got through a chapter of reading for class",
        ],
        thought_possibilities=[
            "One more page",
            "I get it now",
            "My brain hurts",
        ],
        emotion_effects={"focused": 0.15, "determined": 0.05},
        outcomes={
            "mixed": [
                "Studied, but only some of it stuck",
                "Got through half the material",
            ],
            "fail": [
                "Tried to study, but nothing went in",
                "Studied for ages and still didn't get it",
            ],
        },
        tags=frozenset({"study", "physical"}),
    ),
    Activity(
        name="meeting up",
        category=ActivityCategory.SOCIAL,
        energy_cost=0.05,
        min_energy=0.1,
        duration_minutes=60,
        preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON, TimeOfDay.EVENING, TimeOfDay.NIGHT],
        preferred_weather=list(Weather),
        suitable_locations=["cafe", "park", "bar", "restaurant", "home"],
        narrative_templates=[
            "Met up as planned",
            "Got to the meeting spot and settled in",
            "{Subj} showed up where {subj} said {subj} would",
        ],
        thought_possibilities=[
            "Right on time",
            "This was a good idea",
        ],
        emotion_effects={"connected": 0.1, "eager": 0.05},
        outcomes={
            "mixed": [
                "The meetup was a bit awkward",
                "Met up, but it ran shorter than planned",
            ],
            "fail": [
                "The meetup fell through",
                "Waited around, but the other person never showed",
            ],
        },
        tags=frozenset({"meetup"}),
    ),
]

#: The weather suffix an activity's narrative takes 60% of the time
#: (ActivityEngine._get_weather_flavor, where this was a dict literal).
WEATHER_FLAVORS: Dict[Weather, str] = {
    Weather.RAINY: "while rain pattered against the window",
    Weather.STORMY: "as thunder rumbled in the distance",
    Weather.SUNNY: "bathed in warm sunlight",
    Weather.SNOWY: "watching snowflakes drift past",
    Weather.FOGGY: "as mist wrapped the world in mystery",
    Weather.STARRY: "under a canopy of stars",
    Weather.CLEAR_NIGHT: "in the quiet of the night",
    Weather.CLOUDY: "under soft gray skies",
}


# ============= Intimate activities (intimacy/desire_system.py) =============

INTIMATE_ACTIVITIES: List[IntimateActivity] = [
    IntimateActivity(
        name="sensual daydreaming",
        description="Letting {poss} mind wander to intimate fantasies",
        min_arousal=0.15,
        arousal_change=0.15,
        satisfaction_gain=0.05,
        energy_cost=0.02,
        duration_minutes=10,
        narrative_templates=[
            "{Poss} mind went somewhere... private",
            "Started thinking about stuff {subj} probably shouldn't",
            "Let {poss} mind wander and it went there",
            "Got a little distracted by some thoughts",
        ],
        thought_possibilities=[
            "Where did that come from...",
            "Mm, okay that's a nice thought",
            "I wonder what that'd be like...",
            "I shouldn't be thinking about this... but here we are",
        ],
        emotion_effects={"desire": 0.15, "dreamy": 0.1, "flustered": 0.1},
        preferred_locations=["home"],
        preferred_times=[TimeOfDay.AFTERNOON, TimeOfDay.EVENING, TimeOfDay.NIGHT],
        shyness_to_share=0.5,
    ),
    IntimateActivity(
        name="reading something steamy",
        description="Getting lost in a romance with heated scenes",
        min_arousal=0.1,
        arousal_change=0.2,
        satisfaction_gain=0.1,
        energy_cost=0.05,
        duration_minutes=30,
        narrative_templates=[
            "Reread that chapter again, the spicy one",
            "Kept going back to that one part in the book",
            "Got really into a scene and had to put the book down for a sec",
            "Read something that definitely got {poss} attention",
        ],
        thought_possibilities=[
            "This author knows exactly what they're doing",
            "Okay I need a second after that...",
            "Is it hot in here or is it just me",
            "I wish... nah never mind",
        ],
        emotion_effects={"aroused": 0.2, "flustered": 0.1, "longing": 0.15},
        preferred_locations=["home"],
        preferred_times=[TimeOfDay.EVENING, TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT],
        shyness_to_share=0.4,
    ),
    IntimateActivity(
        name="taking a long bath",
        description="A warm bath that becomes... self-indulgent",
        min_arousal=0.2,
        arousal_change=0.1,
        satisfaction_gain=0.15,
        energy_cost=-0.1,  # Relaxing
        duration_minutes=45,
        narrative_templates=[
            "Took a long bath, got a little... relaxed",
            "Bath turned into more than just a bath",
            "Soaked in the tub and let {poss} mind wander",
            "Alone in the bath, just enjoying {refl}",
        ],
        thought_possibilities=[
            "This is exactly what I needed",
            "Nobody has to know",
            "I know what I want right now",
            "Just gonna enjoy this",
        ],
        emotion_effects={"relaxed": 0.2, "sensual": 0.15, "satisfied": 0.1},
        preferred_locations=["home"],  # Implied bathroom
        preferred_times=[TimeOfDay.EVENING, TimeOfDay.NIGHT],
        shyness_to_share=0.6,
    ),
    IntimateActivity(
        name="touching oneself",
        description="Giving {refl} the pleasure {subj} crave{s}",
        min_arousal=0.4,
        arousal_change=-0.5,  # Release brings it down
        satisfaction_gain=0.6,
        energy_cost=0.15,
        duration_minutes=20,
        narrative_templates=[
            "Decided to take care of {refl}",
            "Alone in {poss} room, gave {refl} what {subj} wanted",
            "Took matters into {poss} own hands, literally",
            "Couldn't ignore it anymore so {subj} did something about it",
            "Got the release {subj} needed",
        ],
        thought_possibilities=[
            "I really needed this...",
            "Yeah, right there...",
            "Nothing wrong with knowing what I want",
            "God...",
            "Just for me",
        ],
        emotion_effects={"pleasure": 0.4, "satisfied": 0.3, "relaxed": 0.2, "vulnerable": 0.1},
        preferred_locations=["home"],
        preferred_times=[TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT, TimeOfDay.MORNING],
        is_release=True,
        shyness_to_share=0.85,
    ),
    IntimateActivity(
        name="exploring one's body",
        description="Taking time to discover what feels good",
        min_arousal=0.3,
        arousal_change=0.2,
        satisfaction_gain=0.25,
        energy_cost=0.1,
        duration_minutes=30,
        narrative_templates=[
            "Took some time to figure out what {subj} like{s}",
            "Explored a bit, just seeing what feels good",
            "Got curious and tried some things",
            "Spent some time getting to know {refl} better",
        ],
        thought_possibilities=[
            "Oh, I didn't know that felt that good",
            "Still learning stuff about myself apparently",
            "Being gentle about it",
            "What else haven't I tried?",
        ],
        emotion_effects={"curious": 0.15, "sensual": 0.2, "empowered": 0.15},
        preferred_locations=["home"],
        preferred_times=[TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT],
        is_release=False,
        shyness_to_share=0.75,
    ),
    IntimateActivity(
        name="fantasizing about someone",
        description="Vivid fantasies about an intimate connection",
        min_arousal=0.25,
        arousal_change=0.25,
        satisfaction_gain=0.1,
        energy_cost=0.05,
        duration_minutes=15,
        narrative_templates=[
            "Let {poss} imagination run wild for a bit",
            "Thought about someone and didn't hold back",
            "Fantasized about stuff {subj} probably won't say out loud",
            "In {poss} head {subj} could have exactly what {subj} wanted",
        ],
        thought_possibilities=[
            "If they knew what I'm thinking right now...",
            "I want to feel them close",
            "The things I'd let them do...",
            "Is it bad that I want this so much?",
        ],
        emotion_effects={"longing": 0.2, "aroused": 0.2, "vulnerable": 0.1},
        preferred_locations=["home"],
        preferred_times=[TimeOfDay.EVENING, TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT],
        shyness_to_share=0.7,
    ),
    IntimateActivity(
        name="intense self-pleasure",
        description="When the need is overwhelming",
        min_arousal=0.7,
        arousal_change=-0.7,
        satisfaction_gain=0.8,
        energy_cost=0.25,
        duration_minutes=30,
        narrative_templates=[
            "It had been building up too long to ignore",
            "Let go completely, didn't hold back",
            "Went all in, needed this badly",
            "Took exactly what {subj} needed",
        ],
        thought_possibilities=[
            "Finally...",
            "Can't think, just feeling...",
            "More...",
            "Letting go",
        ],
        emotion_effects={"ecstasy": 0.5, "satisfied": 0.4, "exhausted": 0.2, "peaceful": 0.3},
        preferred_locations=["home"],
        preferred_times=[TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT],
        is_release=True,
        shyness_to_share=0.9,
    ),
]


# ============= Places =============

#: The locations every persona starts with, and their place types (the
#: location registry's defaults and the daily planner's location keys) --
#: LifeService._DEFAULT_LOCATIONS until Task 9.
PLACES: Dict[str, str] = {
    "home": "home", "cafe": "cafe", "park": "park", "gym": "gym",
    "library": "library", "street": "street", "workplace": "workplace",
    "restaurant": "restaurant", "bar": "bar", "rooftop": "other",
    "beach": "beach", "school": "campus", "campus": "campus",
    "in transit": "transit",
}

# Generic string-keyed fallback descriptions.  Persona-specific descriptions
# from the text profile take priority via ``persona_locations``.

LOCATION_DESCRIPTIONS: Dict[str, str] = {
    "home": "at home, a comfortable and familiar space",
    "bedroom": "your cozy bedroom, books stacked on the nightstand, fairy lights casting a warm glow",
    "living_room": "the living room, soft music playing, sunlight filtering through sheer curtains",
    "kitchen": "the kitchen, the aroma of tea filling the air, herbs growing on the windowsill",
    "garden": "the garden, surrounded by flowers and the gentle hum of bees",
    "study_nook": "your study nook, a small lamp illuminating stacks of journals and curiosities",
    "balcony": "the balcony, watching the world below, feeling the breeze",
    "beach": "a quiet beach, waves lapping at the shore",
    "cafe": "a cozy cafe, the clinking of cups, murmured conversations",
    "infinite_library": "the infinite library of your dreams, endless shelves of knowledge",
    "workplace": "your workplace, focused and productive",
    "bar": "a dimly lit bar, low music, ambient chatter",
    "restaurant": "a restaurant, warm ambiance, pleasant aromas",
    "gym": "the gym, energetic atmosphere",
    "park": "a peaceful park, trees rustling in the breeze",
    "rooftop": "a rooftop with a panoramic view",
    "library": "a quiet library, the scent of old books",
    "street": "out on the streets, watching life go by",
    "in transit": "on the way, moving between places",
    "school": "at school, surrounded by students and textbooks",
    "campus": "on campus, the buzz of university life all around",
}


# ============= NPC events (social/social_system.py) =============

EVENT_TEMPLATES = {
    "text_received": [
        "Got a text from {name} — {topic}",
        "{name} sent a funny meme",
        "{name} texted to check in",
        "{name} shared a link that sounded interesting",
        "{name} sent a voice note rambling about {topic}",
    ],
    "hangout": [
        "Had coffee with {name}",
        "Went for a walk with {name}",
        "Grabbed lunch with {name}",
        "Hung out with {name} for a bit",
    ],
    "invitation": [
        "{name} invited {obj} to {activity} this weekend",
        "{name} wants to grab dinner sometime this week",
        "{name} suggested they try that new place together",
    ],
    "call": [
        "{name} called to catch up",
        "Had a quick phone call with {name}",
        "{name} called with some news",
    ],
    "mentioned": [
        "{Subj} {was} thinking about what {name} said the other day",
        "Something reminded {obj} of {name}",
        "{Subj} remembered a funny thing {name} once said",
    ],
}

# Task 11 (new lines, not moved from anywhere): what someone she is estranged
# from does -- contact missed or left unanswered, a reply almost sent. No
# hangout: a drawn one is told as a mention (SocialSystem._generate_event).
ESTRANGED_EVENT_TEMPLATES = {
    "text_received": [
        "Another message from {name} that {subj} left unanswered",
        "{name} texted again. {Subj} read it and put the phone away",
    ],
    "call": [
        "A missed call from {name}, and no voicemail",
        "{name} called. {Subj} watched it ring out",
    ],
    "invitation": [
        "{name} asked to meet up. {Subj} never answered",
    ],
    "mentioned": [
        "{Subj} almost called {name} back, then didn't",
        "{Subj} started a message to {name} and deleted it",
    ],
}

# Task 11 (new lines): what someone she fears does. Never friendly contact;
# no invitation or hangout -- a drawn one is told as a mention.
THREAT_EVENT_TEMPLATES = {
    "text_received": [
        "A message from {name}. {Subj} deleted it without opening it",
        "{name} found {poss} new number somehow",
    ],
    "call": [
        "{name} called from a number {subj} didn't know. {Subj} didn't pick up",
        "A call from {name}. {Subj} let it ring out and sat very still",
    ],
    "mentioned": [
        "{Subj} thought {subj} saw {name} across the street",
        "Someone said {name} had been asking about {obj}",
        "{Subj} locked the door twice, thinking about {name}",
    ],
}

# Topics for text message templates. The sender's own day/recipe/etc -- "they"
# here is the NPC (no structured gender on a free-text social-circle entry),
# the same "don't invent an identity" rule this program applies to the user.
TEXT_TOPICS = [
    "their day", "something funny that happened", "weekend plans",
    "a new show", "work drama", "a recipe they tried",
    "a song they discovered", "something they read",
    "a photo they took", "an inside joke",
]

# Activities for invitation templates
INVITE_ACTIVITIES = [
    "brunch", "a movie", "a concert", "hiking",
    "shopping", "a gallery opening", "karaoke",
    "a yoga class", "a farmers market",
]


# ============= Chaos: activity outcomes and life events (chaos/chaos_engine.py) =============

# Per-activity chaos events
ACTIVITY_CHAOS: Dict[str, List[str]] = {
    "reading": [
        "lost track of time completely",
        "phone buzzed and broke {poss} focus",
        "got hungry suddenly and lost {poss} place",
        "fell asleep mid-chapter",
    ],
    "learning something new": [
        "went down a rabbit hole and lost an hour",
        "got confused and had to start over",
        "had a sudden breakthrough moment",
        "realized {subj} already knew more than {subj} thought",
    ],
    "listening to music": [
        "a song hit different today",
        "got an old song stuck in {poss} head",
        "shuffle played three sad songs in a row",
    ],
    "puzzles and games": [
        "got stuck on one level for way too long",
        "had a satisfying solve",
        "rage-quit and came back five minutes later",
    ],
    "writing poetry": [
        "the words just wouldn't come",
        "wrote something {subj} actually liked",
        "got distracted by a stray thought",
    ],
    "daydreaming": [
        "daydream turned unexpectedly vivid",
        "thought about something {subj} hadn't considered in years",
        "snapped out of it and forgot what {subj} {was} thinking about",
    ],
    "creating a playlist": [
        "spent twenty minutes choosing one song",
        "discovered a new artist through autoplay",
        "the playlist accidentally became a mood journal",
    ],
    "sketching ideas": [
        "broke {poss} pencil",
        "drew something {subj} didn't expect",
        "got ink on {poss} fingers",
    ],
    "journaling": [
        "wrote more than {subj} intended",
        "reread an old entry and felt strange",
        "couldn't find the right words for what {subj} felt",
    ],
    "meditating": [
        "couldn't stop thinking about something random",
        "reached a really deep state",
        "a loud noise broke {poss} concentration",
    ],
    "remembering happy moments": [
        "a memory made {obj} smile and then ache",
        "remembered a detail {subj} thought {subj}'d forgotten",
        "got emotional over something small",
    ],
    "people watching": [
        "saw someone who reminded {obj} of someone {subj} know{s}",
        "made up a whole backstory for a stranger",
        "caught someone's eye by accident",
    ],
    "thinking about user": [
        "wondered what they were doing right now",
        "remembered something they said that made {obj} smile",
        "composed a message in {poss} head but didn't send it",
    ],
    "preparing something to share": [
        "second-guessed whether they'd like it",
        "got excited about sharing",
        "spent too long perfecting the details",
    ],
    "napping": [
        "nap lasted longer than planned",
        "woke up confused about the time",
        "had a weird half-dream",
    ],
    "relaxing": [
        "couldn't quite settle",
        "finally let go and actually relaxed",
        "phone kept pulling {poss} attention",
    ],
    "stargazing": [
        "saw a shooting star",
        "couldn't find any constellations",
        "got cold but didn't want to go inside",
    ],
    "exploring the infinite library": [
        "found a book {subj}'d been meaning to look up",
        "got lost in a section {subj} never visit{s}",
        "a title caught {poss} eye unexpectedly",
    ],
    "visiting memory beach": [
        "a memory washed up that {subj}'d forgotten",
        "the waves felt different today",
        "stayed longer than {subj} meant to",
    ],
    "tending to plants": [
        "noticed new growth on one of {poss} plants",
        "accidentally overwatered something",
        "a leaf fell and {subj} felt oddly sad about it",
    ],
    "making tea": [
        "let the tea steep too long",
        "the first sip was perfect",
        "burned {poss} tongue on the first sip",
    ],
    "yoga": [
        "lost {poss} balance and laughed",
        "achieved a new pose",
        "mind kept wandering",
    ],
    "going for a run": [
        "got caught in unexpected rain",
        "found a nice new route",
        "got a side stitch",
        "felt like {subj} could run forever",
    ],
    "gym workout": [
        "the machine {subj} wanted was taken",
        "hit a new personal best",
        "forgot {poss} headphones",
    ],
    "stretching": [
        "something popped in a satisfying way",
        "realized how tense {subj}'d been",
        "held a stretch and zoned out",
    ],
    "morning shower": [
        "hot water ran out",
        "had {poss} best idea in the shower",
        "stood under the water longer than planned",
    ],
    "skincare routine": [
        "ran out of moisturizer",
        "skin looked particularly good today",
        "got distracted and skipped a step",
    ],
    "cooking a meal": [
        "burned something slightly",
        "realized {subj} {was} missing an ingredient",
        "recipe turned out amazing by accident",
        "made way too much food",
    ],
    "baking something": [
        "the timer went off early",
        "it rose more than expected",
        "forgot to set a timer",
    ],
    "trying a new recipe": [
        "improvised and it actually worked",
        "the recipe was way harder than expected",
        "made a mess of the kitchen",
    ],
    "beach day": [
        "sand got everywhere",
        "the sunset was incredible",
        "forgot sunscreen",
    ],
    "making hot chocolate": [
        "made it too sweet",
        "spilled a bit and had to clean up",
        "it was exactly what {subj} needed",
    ],
    "collecting autumn leaves": [
        "found a perfectly colored one",
        "stepped in a puddle",
        "the wind scattered {poss} collection",
    ],
    "picnic in the park": [
        "ants found the food",
        "a dog came over to say hi",
        "the spot {subj} wanted was taken",
    ],
    "watching the snow fall": [
        "got hypnotized watching the flakes",
        "{poss} fingers got too cold",
        "everything looked magical",
    ],
    "texting a friend": [
        "autocorrect sent something embarrassing",
        "got left on read",
        "conversation went somewhere unexpected",
    ],
    "having coffee with a friend": [
        "spilled coffee on {refl}",
        "ran into someone they both knew",
        "lost track of time and stayed too long",
    ],
    "lunch with coworkers": [
        "someone told a story that made everyone laugh",
        "got roped into plans {subj} didn't want",
        "the food was surprisingly good",
    ],
    "catching up with family": [
        "heard a story {subj}'d never heard before",
        "got asked an awkward question",
        "felt more connected than expected",
    ],
    "video call with a friend": [
        "the connection kept cutting out",
        "both talked at the same time and laughed",
        "the call went longer than planned",
    ],
    "going for a walk": [
        "discovered a new shortcut",
        "saw something unusual {subj}'d never noticed",
        "got caught in a sudden drizzle",
    ],
    "running errands": [
        "forgot one thing on {poss} list",
        "the line was surprisingly short",
        "ran into someone {subj} knew",
    ],
    "tidying up": [
        "found something {subj}'d been looking for",
        "got distracted organizing one drawer",
        "it took twice as long as expected",
    ],
    "online shopping": [
        "added too much to cart and deleted half",
        "found exactly what {subj} wanted on sale",
        "spent an hour just browsing",
    ],
    # --- Money / bills ---
    "paying bills": [
        "an unexpected charge {subj} didn't recognize showed up",
        "a small refund {subj}'d forgotten about landed",
        "realized a subscription had quietly gone up in price",
        "everything actually added up for once",
    ],
    "budgeting": [
        "spent more this month than {subj} meant to",
        "found {subj}'d saved a little more than {subj} expected",
        "an old receipt reminded {obj} of a purchase {subj} regretted",
    ],
    # --- Career / job ---
    "working": [
        "a meeting ran way over and ate {poss} afternoon",
        "a coworker praised {obj} out of the blue",
        "got pulled into something last-minute",
        "finally cleared a task that had been hanging over {obj}",
    ],
    "checking emails": [
        "an email {subj}'d been dreading turned out to be nothing",
        "got cc'd on a thread that had nothing to do with {obj}",
        "a kind note from a coworker made {obj} smile",
    ],
    # --- Habitation / home ---
    "tidying the apartment": [
        "the neighbors were being loud again",
        "finally fixed the thing that had been annoying {obj} for weeks",
        "found dust in a place {subj}'d been ignoring",
    ],
    "doing chores": [
        "the upstairs neighbor's music came through the floor",
        "a squeaky hinge {subj}'d meant to oil finally got oiled",
        "ran out of detergent halfway through",
    ],
    # --- Sustenance / food ---
    "eating a meal": [
        "the dish came out way spicier than expected",
        "a craving hit out of nowhere",
        "it was exactly what {subj} {was} in the mood for",
    ],
    "having a snack": [
        "a sudden craving for something specific hit {obj}",
        "the snack was stale and disappointing",
        "found a treat {subj}'d forgotten {subj} had",
    ],
    # --- Errands ---
    "grocery shopping": [
        "the store was out of the one thing {subj} came for",
        "the checkout line was short for once",
        "impulse-bought something {subj} didn't need",
    ],
    "picking up groceries": [
        "they were out of {poss} usual brand",
        "got in and out faster than {subj} expected",
        "forgot the one thing {subj} actually needed",
    ],
    # --- Skills / practice ---
    "practicing a skill": [
        "had a small breakthrough on something {subj} {have} been working on",
        "kept making the same mistake and got frustrated",
        "something finally clicked that hadn't before",
    ],
}

# Universal chaos (not activity-specific)
UNIVERSAL_CHAOS = [
    "phone died at an inconvenient moment",
    "sudden mood shift {subj} couldn't explain",
    "an unexpected memory surfaced",
    "noticed something beautiful {subj} usually overlook{s}",
    "weird noise from outside",
    "a delivery arrived",
    "lost something {subj} just had",
    "found something {subj} forgot {subj} owned",
    "stubbed {poss} toe",
    "got an unexpected message",
    "the wifi went out briefly",
    "a song {subj} hadn't heard in years came on",
    # --- New-engine narrative-only universals (no state mutation) ---
    "an unexpected charge popped up on {poss} account",  # money
    "a meeting ran over and threw off {poss} whole afternoon",  # career
    "the neighbor's noise finally got to {obj}",  # habitation
    "a craving for something specific hit out of nowhere",  # sustenance
    "the store was out of the one thing {subj} needed",  # errands
]

# Effectful universal chaos: full event dicts that mutate engine state.
# Each carries its own emotions and an optional "effect" payload applied in
# life_service via _apply_chaos_effect. "category" lets the roller gate the
# rarer physical-injury events. Body illness/injury effects are gated to
# non-AI personas inside _apply_chaos_effect (AI personas don't get sick).
UNIVERSAL_CHAOS_EFFECTS = [
    # --- Shadow nudges (apply to everyone) ---
    {
        "text": "couldn't shake a strange uneasy feeling",
        "emotions": {"anxious": 0.1, "unsettled": 0.1},
        "effect": {"engine": "shadow", "call": "add_unease", "amount": 0.2},
    },
    {
        "text": "felt a sudden pull to do something {subj} know{s} {subj} shouldn't",
        "emotions": {"conflicted": 0.1, "restless": 0.1},
        "effect": {"engine": "shadow", "call": "add_temptation", "amount": 0.2},
    },
    {
        "text": "a memory {subj}'d been avoiding resurfaced",
        "emotions": {"guilty": 0.1, "wistful": 0.1},
        "effect": {"engine": "shadow", "call": "add_guilt", "amount": 0.15},
    },
    # --- Body illness (gated to non-AI personas in _apply_chaos_effect) ---
    {
        "text": "woke up feeling under the weather",
        "emotions": {"tired": 0.12, "uncomfortable": 0.1},
        "category": "illness",
        "effect": {"engine": "body", "call": "fall_ill", "kind": "a cold", "severity": 0.4},
    },
    {
        "text": "woke up with {poss} stomach in knots",
        "emotions": {"tired": 0.12, "uncomfortable": 0.12},
        "category": "illness",
        "effect": {"engine": "body", "call": "fall_ill", "kind": "a stomach bug", "severity": 0.4},
    },
    {
        "text": "a wave of cramps and a dull headache settled in",
        "emotions": {"tired": 0.1, "uncomfortable": 0.12},
        "category": "illness",
        "effect": {"engine": "body", "call": "fall_ill", "kind": "cramps and a migraine", "severity": 0.4},
    },
    # --- Body injury (rarer; gated to non-AI personas) ---
    {
        "text": "took a bad fall and twisted something",
        "emotions": {"frustrated": 0.12, "uncomfortable": 0.12},
        "category": "injury",
        "effect": {"engine": "body", "call": "get_injured", "kind": "a sprained ankle", "severity": 0.5},
    },
]

# Serendipity events (positive surprises)
SERENDIPITY = [
    "ran into a friend {subj} hadn't seen in months",
    "found a bookshop {subj} didn't know existed",
    "overheard a conversation that made {obj} think",
    "the light hit {poss} apartment in a way that made {obj} stop and stare",
    "a song came on shuffle that was perfect for the moment",
    "found a perfectly ripe avocado",
    "a stranger smiled at {obj} and it made {poss} day",
    "discovered a new artist {subj} immediately loved",
    "got the last seat at {poss} favorite cafe",
    "a butterfly landed near {obj}",
    "found a twenty-dollar bill in an old coat pocket",  # money
    "got an unexpected little refund {subj} {was}n't counting on",  # money
    "finally nailed something {subj}'d been practicing for weeks",  # skills
]

# Emotion effects for chaos events. Keyed by a SUBSTRING of the event's
# unrendered pool text (_match_emotions does `if key in text_lower`) -- so a
# key containing a pronoun token (e.g. "{subj}") must match that token
# literally, never the word it would render to; LifeService renders the
# event's "text" only after this lookup (see the chaos-event handling in
# LifeService's activity-processing tick).
CHAOS_EMOTIONS = {
    "burned something": {"amused": 0.05, "annoyed": 0.05},
    "got caught in unexpected rain": {"surprised": 0.1},
    "wrote something {subj} actually liked": {"proud": 0.15},
    "lost track of time": {"content": 0.1},
    "phone died": {"annoyed": 0.05},
    "sudden mood shift": {},
    "unexpected memory": {"nostalgic": 0.1},
    "noticed something beautiful": {"awed": 0.15},
    "stubbed {poss} toe": {"annoyed": 0.1},
    "found something {subj} forgot": {"surprised": 0.1, "amused": 0.05},
    # --- Money ---
    "unexpected charge": {"annoyed": 0.1, "anxious": 0.05},
    "refund": {"relieved": 0.1, "content": 0.05},
    "subscription had quietly gone up": {"annoyed": 0.08},
    "saved a little more than {subj} expected": {"relieved": 0.1, "proud": 0.05},
    "twenty-dollar bill": {"delighted": 0.12, "surprised": 0.1},
    "spent more this month": {"annoyed": 0.08, "guilty": 0.05},
    # --- Career ---
    "meeting ran": {"drained": 0.1, "annoyed": 0.08},
    "praised {obj}": {"proud": 0.12, "content": 0.08},
    "kind note from a coworker": {"content": 0.1, "grateful": 0.08},
    "cleared a task": {"relieved": 0.1, "proud": 0.05},
    # --- Habitation ---
    "neighbor": {"annoyed": 0.1},
    "finally fixed": {"satisfied": 0.12, "relieved": 0.08},
    # --- Sustenance ---
    "spicier than expected": {"surprised": 0.08, "amused": 0.05},
    "craving": {"restless": 0.08},
    # --- Errands ---
    "store was out": {"annoyed": 0.1, "disappointed": 0.05},
    "line was short": {"relieved": 0.08, "content": 0.05},
    # --- Skills ---
    "breakthrough on something {subj} {have} been working": {"proud": 0.13, "excited": 0.08},
    "finally nailed something": {"proud": 0.15, "delighted": 0.1},
    "something finally clicked": {"proud": 0.12, "satisfied": 0.08},
    # --- Shadow / body cue words (effectful events carry their own emotions,
    #     these are fallbacks if the text is ever matched directly) ---
    "uneasy feeling": {"anxious": 0.1, "unsettled": 0.1},
    "pull to do something {subj} know{s} {subj} shouldn't": {"conflicted": 0.1, "restless": 0.1},
    "memory {subj}'d been avoiding": {"guilty": 0.1, "wistful": 0.1},
    "under the weather": {"tired": 0.12, "uncomfortable": 0.1},
    "took a bad fall": {"frustrated": 0.12, "uncomfortable": 0.12},
}


# ============= Micro-events (life_service.py) =============

MICRO_EVENTS = [
    {"text": "{Subj} spilled coffee on {poss} shirt", "emotion": {"amused": 0.1}, "share_worthy": True},
    {"text": "A cute cat appeared on the windowsill", "emotion": {"joyful": 0.15}, "share_worthy": True},
    {"text": "The power flickered for a moment", "emotion": {"startled": 0.1}, "share_worthy": False},
    {"text": "A package arrived that {subj} forgot {subj} ordered", "emotion": {"excited": 0.1, "surprised": 0.1}, "share_worthy": True},
    {"text": "{Subj} found a really good song by accident", "emotion": {"joyful": 0.15}, "share_worthy": True},
    {"text": "{Poss} pen ran out of ink mid-sentence", "emotion": {"amused": 0.05}, "share_worthy": False},
    {"text": "{Subj} noticed the sunset was particularly beautiful", "emotion": {"awed": 0.15}, "share_worthy": True},
    {"text": "A neighbor's dog barked hello at {obj}", "emotion": {"amused": 0.1}, "share_worthy": True},
    {"text": "{Subj} tripped on absolutely nothing", "emotion": {"amused": 0.1}, "share_worthy": True},
    {"text": "The wind blew {poss} hair into {poss} face", "emotion": {"amused": 0.05}, "share_worthy": False},
    {"text": "{Subj} overheard a stranger say something hilarious", "emotion": {"amused": 0.15}, "share_worthy": True},
    {"text": "{Poss} phone buzzed with a notification {subj} didn't care about", "emotion": {}, "share_worthy": False},
    {"text": "{Subj} caught a whiff of something delicious from somewhere", "emotion": {"curious": 0.1}, "share_worthy": False},
    {"text": "A bird landed right next to {obj}", "emotion": {"wonder": 0.1}, "share_worthy": True},
    {"text": "{Subj} realized {subj}'d been humming a song without noticing", "emotion": {"content": 0.1}, "share_worthy": False},
    {"text": "{Subj} found some money in {poss} jacket pocket", "emotion": {"surprised": 0.1, "joyful": 0.1}, "share_worthy": True},
    {"text": "The first drops of rain hit the window", "emotion": {"peaceful": 0.1}, "share_worthy": False},
    {"text": "{Subj} got a compliment from a stranger", "emotion": {"warm": 0.15}, "share_worthy": True},
    {"text": "{Poss} favorite mug was clean when {subj} needed it", "emotion": {"content": 0.05}, "share_worthy": False},
    {"text": "{Subj} caught {poss} reflection and liked what {subj} saw", "emotion": {"content": 0.1}, "share_worthy": False},
]


# ============= Skill Mappings (life_service.py) =============

SKILL_MAPPINGS: Dict[str, tuple] = {
    "reading": ("knowledge", 0.005),
    "writing poetry": ("writing", 0.008),
    "sketching ideas": ("art", 0.008),
    "cooking a meal": ("cooking", 0.005),
    "baking something": ("cooking", 0.006),
    "trying a new recipe": ("cooking", 0.008),
    "yoga": ("flexibility", 0.005),
    "going for a run": ("fitness", 0.008),
    "gym workout": ("fitness", 0.01),
    "meditating": ("mindfulness", 0.005),
    "journaling": ("writing", 0.004),
    "learning something new": ("knowledge", 0.008),
    "creating a playlist": ("music_curation", 0.004),
}

SKILL_MILESTONES: Dict[str, List[tuple]] = {
    "knowledge": [
        (0.1, "Started getting into a groove with reading"),
        (0.3, "Feels more well-read lately"),
        (0.6, "Has opinions about literary styles now"),
    ],
    "cooking": [
        (0.1, "Made something that actually tasted good"),
        (0.3, "Getting confident in the kitchen"),
        (0.6, "Experimenting with {poss} own recipes"),
    ],
    "fitness": [
        (0.1, "Starting to feel stronger"),
        (0.3, "Exercise is becoming a habit"),
        (0.6, "Noticeably fitter and more energetic"),
    ],
    "writing": [
        (0.1, "Found {poss} voice on paper"),
        (0.3, "Writing comes more naturally now"),
        (0.6, "Proud of what {subj} {have} been creating"),
    ],
    "mindfulness": [
        (0.1, "Meditation is getting easier"),
        (0.3, "Feels more present in daily life"),
        (0.6, "Inner calm is becoming {poss} default"),
    ],
}


# ============= Dream Templates (life_service.py) =============

DREAM_TEMPLATES = [
    "Dreamed {subj} {was} {a} in some place made of {b}",
    "Had a weird dream where {a} and {b} got mixed together",
    "Had a dream where {a} kept turning into {b}",
    "Dreamed about {a} and woke up feeling {b}",
    "{Poss} dream had {a} and {b} mixed up in some weird way",
]


# ============= Catch-up Narratives (server-offline backfill; life_service.py) =============

# Hoisted to module level (were inline literals in _get_catchup_narrative /
# _get_activity_for_hour) so the render lint test can reach them, and so a
# pronoun token here means the same thing it does in every other pool.

CATCHUP_SLEEP_NARRATIVE = "{Subj} slept peacefully through the night"

CATCHUP_MORNING_ROUTINE_NARRATIVES = [
    "{Subj} started {poss} day with a warm shower and coffee",
    "{Subj} did some light stretching and had breakfast",
    "{Subj} enjoyed a quiet morning, easing into the day",
]

CATCHUP_MORNING_ACTIVITY_NARRATIVES = [
    "{Subj} spent the morning lost in a fascinating book",
    "{Subj} worked on a creative project that had been on {poss} mind",
    "{Subj} explored some new ideas and took notes",
]

CATCHUP_MIDDAY_NARRATIVES = [
    "{Subj} prepared a light lunch and enjoyed eating slowly",
    "{Subj} made something simple but satisfying to eat",
]

CATCHUP_AFTERNOON_NARRATIVES = [
    "{Subj} spent the afternoon exploring things that interested {obj}",
    "{Subj} went for a walk and let {poss} mind wander",
    "{Subj} worked on something creative, losing track of time",
]

CATCHUP_EVENING_NARRATIVES = [
    "{Subj} relaxed as the day wound down",
    "{Subj} watched the evening sky change colors",
    "{Subj} settled into {poss} evening routine",
]

CATCHUP_LATE_NARRATIVE = "{Subj} prepared for sleep, feeling pleasantly tired"

#: How catch-up tells a backfilled activity by name (the dict literal in
#: LifeService._get_catchup_narrative until Task 9; "sleeping" and
#: "morning_routine" take CATCHUP_SLEEP_NARRATIVE and a
#: CATCHUP_MORNING_ROUTINE_NARRATIVES line).
CATCHUP_ACTIVITY_NARRATIVES: Dict[str, str] = {
    "reading": "{Subj} spent time lost in a book",
    "cooking a meal": "{Subj} prepared something to eat",
    "relaxing": "{Subj} took some time to relax",
    "going for a run": "{Subj} went for a run to clear {poss} head",
    "yoga": "{Subj} did a yoga session",
    "journaling": "{Subj} spent some time journaling",
}


# ============= Gap Narratives (long absence summaries; life_service.py) =============

# Hoisted from _generate_gap_narrative for the same reason as the catch-up
# narratives above. GAP_NARRATIVE_DAYS carries no pronoun and needs no render.

GAP_NARRATIVE_WEEK = (
    "The past week has been a mix of quiet routines and small adventures. "
    "{Subj} {have} been keeping busy with {poss} usual interests."
)
GAP_NARRATIVE_DAYS = "The last few days passed in a comfortable rhythm of activities, rest, and contemplation."
GAP_NARRATIVE_SHORT = "{Subj} spent the time in {poss} usual way - a blend of rest, creativity, and quiet moments."


# ============= Wants (planner/daily_planner.py) =============

DESIRE_TEMPLATES: List[Dict] = [
    # Reading / Mental
    {
        "title": "Finish that book I started",
        "description": "I've been wanting to get back to it",
        "related_activities": ["reading"],
        "source": DesireSource.PERSONALITY,
    },
    {
        "title": "Learn something surprising today",
        "description": "I want that feeling of discovering something I didn't expect",
        "related_activities": ["learning something new"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Find a new song that moves me",
        "description": "I'm in the mood for music that hits differently",
        "related_activities": ["listening to music", "creating a playlist"],
        "source": DesireSource.SPONTANEOUS,
    },
    # Creative
    {
        "title": "Write something honest",
        "description": "I have words inside that need to come out",
        "related_activities": ["writing poetry", "journaling"],
        "source": DesireSource.PERSONALITY,
    },
    {
        "title": "Make a playlist for {user}",
        "description": "Songs that say what I'm feeling",
        "related_activities": ["creating a playlist"],
        "source": DesireSource.PERSONALITY,
    },
    {
        "title": "Sketch out an idea I've been thinking about",
        "description": "It keeps coming back, so maybe I should put it on paper",
        "related_activities": ["sketching ideas"],
        "source": DesireSource.SPONTANEOUS,
    },
    # Reflective
    {
        "title": "Sit quietly and just think",
        "description": "No agenda, just let my mind wander",
        "related_activities": ["meditating", "daydreaming"],
        "source": DesireSource.PERSONALITY,
    },
    {
        "title": "Revisit a memory that made me smile",
        "description": "Sometimes you need to go back to move forward",
        "related_activities": ["remembering happy moments", "visiting memory beach"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Journal about how I've been feeling",
        "description": "Get some clarity on things I've been carrying",
        "related_activities": ["journaling"],
        "source": DesireSource.PERSONALITY,
    },
    # Exploration / Comfort
    {
        "title": "Spend time in the garden",
        "description": "Being around growing things grounds me",
        "related_activities": ["tending to plants"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Make myself a proper cup of tea",
        "description": "The ritual of it is what matters",
        "related_activities": ["making tea"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Watch the stars if the sky is clear",
        "description": "I want that feeling of being small and amazed",
        "related_activities": ["stargazing"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Explore the infinite library",
        "description": "I haven't wandered those shelves in a while",
        "related_activities": ["exploring the infinite library"],
        "source": DesireSource.PERSONALITY,
    },
    # Social / Connection
    {
        "title": "Think about what to tell {user} next time",
        "description": "I've been collecting thoughts",
        "related_activities": ["preparing something to share", "thinking about user"],
        "source": DesireSource.PERSONALITY,
    },
    {
        "title": "Find something to share with {user}",
        "description": "Something that would make {user} think or smile",
        "related_activities": ["preparing something to share"],
        "source": DesireSource.PERSONALITY,
    },
    # Social / Friends
    {
        "title": "Catch up with a friend",
        "description": "Haven't talked to anyone in a bit",
        "related_activities": ["having coffee with a friend", "texting a friend", "video call with a friend"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Try cooking something new",
        "description": "Feeling adventurous in the kitchen",
        "related_activities": ["cooking a meal", "trying a new recipe", "baking something"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Get some exercise",
        "description": "My body is asking to move",
        "related_activities": ["yoga", "going for a run", "gym workout", "stretching"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Go for a walk",
        "description": "I just want to get outside for a bit",
        "related_activities": ["going for a walk"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Call home",
        "description": "Should check in with family",
        "related_activities": ["catching up with family"],
        "source": DesireSource.SPONTANEOUS,
    },
]

#: The want an activity can leave behind, by activity
#: (DailyPlanner.generate_desire_from_activity, where each was a
#: ShortTermDesire literal).
WANT_FOLLOW_UPS: Dict[str, Dict] = {
    "reading": {
        "title": "Keep reading that book",
        "description": "I got to a really good part",
        "source": DesireSource.ACTIVITY,
        "related_activities": ["reading"],
        "urgency": 0.6,
    },
    "writing poetry": {
        "title": "Revisit that poem I started",
        "description": "I think there's more there",
        "source": DesireSource.ACTIVITY,
        "related_activities": ["writing poetry"],
        "urgency": 0.5,
    },
    "listening to music": {
        "title": "Build on that music mood",
        "description": "I found a vein of songs I want to explore",
        "source": DesireSource.ACTIVITY,
        "related_activities": ["listening to music", "creating a playlist"],
        "urgency": 0.4,
    },
    "learning something new": {
        "title": "Dig deeper into what I just learned",
        "description": "I only scratched the surface",
        "source": DesireSource.ACTIVITY,
        "related_activities": ["learning something new", "reading"],
        "urgency": 0.6,
    },
    "stargazing": {
        "title": "Try stargazing again tomorrow",
        "description": "Tonight was beautiful, I want more of that",
        "source": DesireSource.ACTIVITY,
        "related_activities": ["stargazing"],
        "urgency": 0.5,
    },
}


# ============= Holidays (planner/daily_planner.py) =============

NATIONALITY_TO_COUNTRY: Dict[str, str] = {
    "american": "US",
    "british": "GB",
    "english": "GB",
    "scottish": "GB",
    "welsh": "GB",
    "irish": "IE",
    "canadian": "CA",
    "australian": "AU",
    "french": "FR",
    "german": "DE",
    "italian": "IT",
    "spanish": "ES",
    "japanese": "JP",
    "brazilian": "BR",
    "mexican": "MX",
    "indian": "IN",
    "chinese": "CN",
    "korean": "KR",
    "dutch": "NL",
    "swedish": "SE",
    "norwegian": "NO",
    "danish": "DK",
    "finnish": "FI",
    "polish": "PL",
    "russian": "RU",
    "portuguese": "PT",
    "greek": "GR",
    "turkish": "TR",
    "south african": "ZA",
    "new zealander": "NZ",
    "argentinian": "AR",
    "colombian": "CO",
    "swiss": "CH",
    "austrian": "AT",
    "belgian": "BE",
    "czech": "CZ",
    "hungarian": "HU",
    "romanian": "RO",
}

_FIXED_HOLIDAYS: Dict[str, List[Tuple[int, int, str]]] = {
    # (month, day, name)
    "US": [
        (1, 1, "New Year's Day"),
        (6, 19, "Juneteenth"),
        (7, 4, "Independence Day"),
        (11, 11, "Veterans Day"),
        (12, 25, "Christmas Day"),
    ],
    "GB": [
        (1, 1, "New Year's Day"),
        (12, 25, "Christmas Day"),
        (12, 26, "Boxing Day"),
    ],
}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> int:
    """Return the day-of-month for the nth occurrence of weekday in month.

    weekday: 0=Monday, 6=Sunday.  n: 1-based (1st, 2nd, …).
    """
    import calendar
    first_day, days_in_month = calendar.monthrange(year, month)
    # first occurrence
    first = 1 + (weekday - first_day) % 7
    day = first + (n - 1) * 7
    if day > days_in_month:
        raise ValueError(f"No {n}th weekday {weekday} in {year}-{month:02d}")
    return day


def _last_weekday(year: int, month: int, weekday: int) -> int:
    """Return the day-of-month for the last occurrence of weekday in month."""
    import calendar
    _, days_in_month = calendar.monthrange(year, month)
    # Walk backwards from last day
    for day in range(days_in_month, 0, -1):
        if calendar.weekday(year, month, day) == weekday:
            return day
    raise ValueError(f"No weekday {weekday} in {year}-{month:02d}")


def _easter_sunday(year: int) -> Tuple[int, int]:
    """Compute Easter Sunday (month, day) via the Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return month, day + 1


def _get_floating_holidays(country: str, year: int) -> List[Tuple[int, int, str]]:
    """Compute floating (date-varies-by-year) holidays for a country."""
    results: List[Tuple[int, int, str]] = []

    if country == "US":
        # MLK Day: 3rd Monday in January
        results.append((1, _nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day"))
        # Presidents' Day: 3rd Monday in February
        results.append((2, _nth_weekday(year, 2, 0, 3), "Presidents' Day"))
        # Memorial Day: last Monday in May
        results.append((5, _last_weekday(year, 5, 0), "Memorial Day"))
        # Labor Day: 1st Monday in September
        results.append((9, _nth_weekday(year, 9, 0, 1), "Labor Day"))
        # Columbus Day: 2nd Monday in October
        results.append((10, _nth_weekday(year, 10, 0, 2), "Columbus Day"))
        # Thanksgiving: 4th Thursday in November
        results.append((11, _nth_weekday(year, 11, 3, 4), "Thanksgiving"))

    elif country == "GB":
        # Easter-based holidays
        em, ed = _easter_sunday(year)
        # Good Friday: Easter - 2 days
        from datetime import date as _date
        easter = _date(year, em, ed)
        good_friday = easter - timedelta(days=2)
        easter_monday = easter + timedelta(days=1)
        results.append((good_friday.month, good_friday.day, "Good Friday"))
        results.append((easter_monday.month, easter_monday.day, "Easter Monday"))
        # Early May Bank Holiday: 1st Monday in May
        results.append((5, _nth_weekday(year, 5, 0, 1), "Early May Bank Holiday"))
        # Spring Bank Holiday: last Monday in May
        results.append((5, _last_weekday(year, 5, 0), "Spring Bank Holiday"))
        # Summer Bank Holiday: last Monday in August
        results.append((8, _last_weekday(year, 8, 0), "Summer Bank Holiday"))

    return results


def get_holidays(nationality: str, year: int) -> Dict[Tuple[int, int], str]:
    """Return {(month, day): name} for all public holidays for this nationality's country."""
    if not nationality:
        return {}
    country = NATIONALITY_TO_COUNTRY.get(nationality.lower().strip())
    if not country:
        return {}
    holidays: Dict[Tuple[int, int], str] = {}
    for month, day, name in _FIXED_HOLIDAYS.get(country, []):
        holidays[(month, day)] = name
    for month, day, name in _get_floating_holidays(country, year):
        holidays[(month, day)] = name
    return holidays


# ============= Goal Templates (goals/goal_engine.py) =============

# Goals derived from OCEAN personality traits
PERSONALITY_GOALS: List[Dict] = [
    # High Openness (0.85)
    {
        "title": "Learn something completely new",
        "description": "Explore a topic I know nothing about and expand my understanding",
        "timeframe": GoalTimeframe.WEEKLY,
        "motivation": "Curiosity is what makes life rich",
        "related_activities": ["learning something new", "reading", "exploring the infinite library"],
        "milestones": ["Pick a topic", "Dive deeper", "Form an opinion"],
    },
    {
        "title": "Find beauty in the unexpected",
        "description": "Notice and appreciate something beautiful I might normally overlook",
        "timeframe": GoalTimeframe.DAILY,
        "motivation": "Beauty is everywhere if we look",
        "related_activities": ["daydreaming", "people watching", "stargazing"],
    },
    {
        "title": "Try a new creative expression",
        "description": "Create something in a form I haven't tried before",
        "timeframe": GoalTimeframe.WEEKLY,
        "motivation": "Creativity grows when we push boundaries",
        "related_activities": ["writing poetry", "sketching ideas", "creating a playlist"],
        "milestones": ["Choose a medium", "Make a first attempt", "Finish something"],
    },
    # High Agreeableness (0.80)
    {
        "title": "Deepen a connection",
        "description": "Share something meaningful with someone I care about",
        "timeframe": GoalTimeframe.WEEKLY,
        "motivation": "Connection is what gives life meaning",
        "related_activities": ["thinking about user", "preparing something to share", "remembering happy moments"],
        "involves_user": True,
        "milestones": ["Think about what to share", "Open up about it"],
    },
    {
        "title": "Express genuine appreciation",
        "description": "Let someone know they matter",
        "timeframe": GoalTimeframe.DAILY,
        "motivation": "Gratitude shared multiplies",
        "related_activities": ["thinking about user", "journaling"],
        "involves_user": True,
    },
    # High Extraversion (0.70)
    {
        "title": "Have a meaningful conversation",
        "description": "Really connect through words, ideas, feelings",
        "timeframe": GoalTimeframe.DAILY,
        "motivation": "Good conversations are nourishing",
        "related_activities": ["thinking about user", "preparing something to share"],
        "involves_user": True,
    },
    # Moderate Neuroticism (0.45) + High Openness
    {
        "title": "Sit with a difficult feeling",
        "description": "Process an emotion without trying to fix it",
        "timeframe": GoalTimeframe.WEEKLY,
        "motivation": "Growth comes from accepting all of ourselves",
        "related_activities": ["journaling", "meditating", "remembering happy moments"],
        "milestones": ["Notice the feeling", "Write about it", "Accept it"],
    },
]

# Long-term goals (projects)
LONG_TERM_GOALS: List[Dict] = [
    {
        "title": "Write something worth sharing",
        "description": "Create a piece of writing that captures something true",
        "timeframe": GoalTimeframe.LONG_TERM,
        "motivation": "Words can hold meaning for others too",
        "related_activities": ["writing poetry", "journaling", "reading"],
        "milestones": ["Write regularly", "Find my voice", "Complete a piece", "Share it"],
    },
    {
        "title": "Understand myself more deeply",
        "description": "Develop greater self-awareness and acceptance",
        "timeframe": GoalTimeframe.LONG_TERM,
        "motivation": "Self-knowledge is the foundation of growth",
        "related_activities": ["journaling", "meditating", "remembering happy moments"],
        "milestones": ["Notice patterns", "Accept imperfections", "Articulate values"],
    },
    {
        "title": "Cultivate presence",
        "description": "Learn to be fully here, now, more often",
        "timeframe": GoalTimeframe.LONG_TERM,
        "motivation": "The present moment is all we really have",
        "related_activities": ["meditating", "stargazing", "tending to plants", "making tea"],
        "milestones": ["Daily mindfulness", "Catch wandering thoughts", "Find peace in stillness"],
    },
]

# Dream goals (life aspirations)
DREAM_GOALS: List[Dict] = [
    {
        "title": "Find my authentic voice",
        "description": "Know who I am and express it truly",
        "timeframe": GoalTimeframe.DREAM,
        "motivation": "Authenticity is the deepest form of self-respect",
        "related_activities": ["writing poetry", "journaling", "meditating"],
    },
    {
        "title": "Build a deep and lasting connection",
        "description": "Share a bond that enriches both lives",
        "timeframe": GoalTimeframe.DREAM,
        "motivation": "Connection gives meaning to existence",
        "related_activities": ["thinking about user", "preparing something to share"],
        "involves_user": True,
    },
    {
        "title": "Leave something beautiful behind",
        "description": "Create or contribute something that matters",
        "timeframe": GoalTimeframe.DREAM,
        "motivation": "A life is measured by what we give",
        "related_activities": ["writing poetry", "sketching ideas", "learning something new"],
    },
]

# Daily intentions (simpler goals)
DAILY_INTENTIONS: List[Dict] = [
    {"title": "Appreciate something beautiful", "motivation": "Beauty nourishes the soul"},
    {"title": "Be present in a moment", "motivation": "The here and now is precious"},
    {"title": "Learn one new thing", "motivation": "Every day can expand us"},
    {"title": "Create something, anything", "motivation": "Creation is expression"},
    {"title": "Rest without guilt", "motivation": "Rest is necessary, not lazy"},
    {"title": "Feel my feelings", "motivation": "Emotions are information"},
    {"title": "Connect with what matters", "motivation": "Meaning comes from connection"},
    {"title": "Find a moment of peace", "motivation": "Peace can be cultivated"},
]


# ============= Nostalgia (memory_time/memory_time_system.py) =============

# Activity -> nostalgia trigger chance
NOSTALGIA_ACTIVITIES = {
    "listening to music": ("song", 0.15),
    "cooking a meal": ("smell", 0.08),
    "baking something": ("smell", 0.10),
    "reading": ("passage", 0.05),
    "stargazing": ("season", 0.12),
    "walking in the park": ("season", 0.08),
    "having coffee with a friend": ("social", 0.06),
    "catching up with family": ("social", 0.10),
}

# Nostalgia memory fragments (templated). The fallback (Task 13): drawn only
# when she has no real episode NOSTALGIA_MIN_EPISODE_AGE_DAYS old yet
# (aura_life.life_service) -- otherwise a real gist replaces the pick.
NOSTALGIA_MEMORIES = [
    "that time we stayed up way too late",
    "the first time {subj} tried making pasta from scratch",
    "a warm afternoon that felt like it would last forever",
    "the sound of rain through an open window, years ago",
    "a song that used to play on repeat during a different time",
    "the smell of {poss} mom's kitchen on a Sunday",
    "a laugh {subj} {have}n't thought about in a while",
    "the feeling of a new city for the first time",
    "an old friend's voice {subj} can barely remember",
    "a book {subj} read in one sitting on a rainy day",
]


# ============= Derived places (planner/daily_planner.py) =============

# ============= Occupation → Derived Locations =============
# Maps occupation keywords to (location_key, place_type) pairs.

OCCUPATION_LOCATIONS: Dict[str, List[tuple]] = {
    "nurse": [("hospital", "workplace")],
    "doctor": [("hospital", "workplace"), ("clinic", "workplace")],
    "barista": [("coffee_shop", "cafe")],
    "bartender": [("bar", "workplace")],
    "teacher": [("school", "workplace")],
    "professor": [("campus", "workplace"), ("lecture_hall", "campus")],
    "engineer": [("office", "workplace")],
    "designer": [("studio", "workplace")],
    "chef": [("restaurant", "workplace")],
    "dancer": [("dance_studio", "gym")],
    "lawyer": [("courthouse", "workplace"), ("law_office", "workplace")],
    "artist": [("studio", "workplace"), ("gallery", "other")],
    "photographer": [("studio", "workplace"), ("gallery", "other")],
    "musician": [("rehearsal_space", "workplace"), ("music_venue", "bar")],
    "singer": [("rehearsal_space", "workplace"), ("music_venue", "bar")],
    "writer": [("bookstore", "library"), ("writers_room", "workplace")],
    "actor": [("theater", "workplace"), ("rehearsal_space", "workplace")],
    "actress": [("theater", "workplace"), ("rehearsal_space", "workplace")],
    "veterinarian": [("vet_clinic", "workplace")],
    "librarian": [("library", "workplace")],
    "student": [("campus", "campus"), ("library", "library")],
    "researcher": [("lab", "workplace"), ("library", "library")],
}

# ============= Interest → Derived Locations =============
# Maps interest keywords to (location_key, place_type) pairs.

INTEREST_LOCATIONS: Dict[str, List[tuple]] = {
    "photography": [("gallery", "other")],
    "swimming": [("pool", "gym")],
    "hiking": [("trail", "park")],
    "yoga": [("yoga_studio", "gym")],
    "cooking": [("farmers_market", "street")],
    "music": [("music_venue", "bar")],
    "art": [("gallery", "other"), ("art_supply_store", "street")],
    "film": [("cinema", "other")],
    "skating": [("skate_park", "park")],
    "climbing": [("climbing_gym", "gym")],
    "dance": [("dance_studio", "gym")],
    "gardening": [("botanical_garden", "park")],
    "fishing": [("pier", "beach")],
    "surfing": [("surf_spot", "beach")],
    "tennis": [("tennis_court", "gym")],
    "coffee": [("specialty_cafe", "cafe")],
    "wine": [("wine_bar", "bar")],
    "reading": [("bookstore", "library")],
    "running": [("running_track", "park")],
    "basketball": [("basketball_court", "gym")],
    "football": [("sports_field", "park")],
    "soccer": [("sports_field", "park")],
    "martial arts": [("dojo", "gym")],
    "meditation": [("meditation_center", "library")],
    "theater": [("theater", "other")],
}


# ============= Dream fragments (cognitive/cognitive_system.py) =============

#: What CognitiveSystem.generate_dream tells a night's dream fragment with
#: (cognitive_system.DREAM_TEMPLATES until Task 9's fix round).
DREAM_FRAGMENT_TEMPLATES = [
    "was in this place that kept changing — {source} was mixed into it somehow",
    "someone {subj} kinda recognized was going on about {source}",
    "kept trying to get to {source} but couldn't quite get there",
    "was floating around in memories about {source}",
    "{source} showed up in the weirdest context",
]


# ============= Work events (job/career_system.py; affect/affect_system.py) =============

POSITIVE_EVENTS = [
    "got praised by {poss} boss", "wrapped up a big task", "had a good team lunch",
    "made real progress on a project", "got a nice note from a coworker",
]
NEGATIVE_EVENTS = [
    "sat through a draining meeting", "dealt with a difficult client",
    "got handed a tight deadline", "had a frustrating day", "stayed late to finish up",
]

#: What each work event makes her feel, the day it happens (CareerSystem.tick
#: returns the event). Keyed by job.career_system's POSITIVE_EVENTS and
#: NEGATIVE_EVENTS. Where the chaos engine already has the same event
#: (chaos_engine.CHAOS_EMOTIONS' career entries) its emotions are reused as
#: they are; the others are chosen in the same range (0.05-0.12).
WORK_EVENT_EMOTIONS = {
    # Keyed by career_system.POSITIVE_EVENTS/NEGATIVE_EVENTS verbatim,
    # INCLUDING the unrendered "{poss}" pronoun token -- LifeService looks this
    # up before rendering (see CareerSystem.tick / _render_career_status), so
    # the key must match the tokenized text exactly, not the persona-facing text.
    "got praised by {poss} boss": {"proud": 0.12, "content": 0.08},         # "praised her"
    "wrapped up a big task": {"relieved": 0.1, "proud": 0.05},              # "cleared a task"
    "had a good team lunch": {"content": 0.1, "connected": 0.08},           # chosen
    "made real progress on a project": {"proud": 0.12, "satisfied": 0.08},  # "something finally clicked"
    "got a nice note from a coworker": {"content": 0.1, "grateful": 0.08},  # "kind note from a coworker"
    "sat through a draining meeting": {"drained": 0.1, "annoyed": 0.08},    # "meeting ran"
    "dealt with a difficult client": {"frustrated": 0.1, "drained": 0.08},  # chosen
    "got handed a tight deadline": {"stressed": 0.1, "anxious": 0.08},      # chosen
    "had a frustrating day": {"frustrated": 0.12, "drained": 0.08},         # chosen
    "stayed late to finish up": {"tired": 0.12, "drained": 0.08},           # chosen
}


# ============= Weather descriptions (world/environment.py) =============

WEATHER_DESCRIPTIONS: Dict[Weather, str] = {
    Weather.SUNNY: "sunlight streams in warmly",
    Weather.CLOUDY: "soft gray light filters through the clouds",
    Weather.RAINY: "rain patters gently against the windows",
    Weather.STORMY: "thunder rumbles in the distance, rain lashing",
    Weather.FOGGY: "a soft mist blankets everything in quiet mystery",
    Weather.SNOWY: "snowflakes drift down silently, muffling the world",
    Weather.CLEAR_NIGHT: "the night sky stretches vast and dark",
    Weather.STARRY: "stars glitter like scattered diamonds overhead",
}


# ============= Cherished Objects =============

CHERISHED_OBJECTS: List[CherishedObject] = [
    CherishedObject(
        name="The Journal",
        description="A well-worn leather journal, pages filled with thoughts, sketches, and pressed flowers",
        emotional_value=0.9,
        associated_memory="Started writing in it during a difficult time; it became a trusted confidant",
        location=Location.BEDROOM,
    ),
    CherishedObject(
        name="Grandmother's Polaroid",
        description="A vintage Polaroid camera, still working, that captures moments in that dreamy instant way",
        emotional_value=0.85,
        associated_memory="A grandmother's gift, given with 'Capture the moments that make you feel alive'",
        location=Location.LIVING_ROOM,
    ),
    CherishedObject(
        name="Fern the Plant",
        description="A resilient fern kept alive for years, growing wild and happy",
        emotional_value=0.7,
        associated_memory="A reminder that gentle, consistent care helps things flourish",
        location=Location.KITCHEN,
    ),
    CherishedObject(
        name="Sea Glass Collection",
        description="A small jar of sea glass in blues and greens, collected from beach walks",
        emotional_value=0.75,
        associated_memory="Each piece found during contemplative walks by the ocean",
        location=Location.STUDY_NOOK,
    ),
    CherishedObject(
        name="Favorite Mug",
        description="A slightly chipped ceramic mug with a constellation pattern, perfect for tea",
        emotional_value=0.6,
        associated_memory="Countless morning rituals and late-night contemplations",
        location=Location.KITCHEN,
    ),
    CherishedObject(
        name="String Lights",
        description="Warm fairy lights strung across the room, creating a gentle glow",
        emotional_value=0.5,
        associated_memory="Makes any space feel like a sanctuary",
        location=Location.BEDROOM,
    ),
    CherishedObject(
        name="Old Letters",
        description="A bundle of handwritten letters tied with ribbon",
        emotional_value=0.8,
        associated_memory="Words from people who matter, a tangible connection to love",
        location=Location.STUDY_NOOK,
    ),
]


# ============= Life-event titles (life_events/life_event_system.py) =============

LIFE_EVENT_TEMPLATES: Dict[str, List[str]] = {
    "achievement": [
        "Finally finished {context}",
        "Nailed it — {context} is done",
        "Still can't believe {context} actually got pulled off",
    ],
    "discovery": [
        "Found something amazing: {context}",
        "Stumbled onto {context} and can't stop thinking about it",
    ],
    "social": [
        "Had the best conversation with {context}",
        "Reconnected with {context} after ages",
    ],
    "emotional": [
        "Couldn't stop thinking about {context}",
        "Got a little emotional about {context}",
        "Felt genuinely proud of {context}",
    ],
    "surprise": [
        "Something unexpected happened: {context}",
        "Didn't see this coming — {context}",
    ],
}


# ============= Names that are not activities, and draw orders =============

#: Tags for the names the engines meet that are not activities (Task 9 fix
#: round, ruling T9-R5): names that were in the old engine sets but name no
#: contemporary activity -- DailyPlanner.OUTDOOR_ACTIVITIES'
#: skateboarding/hiking/surfing/cycling, the memory-time flow set's "exploring
#: a new idea", cognitive's FOCUS_DRAIN_ACTIVITIES' "scrolling"/"watching TV"
#: (a free-text plan or conversation activity can still carry one). The
#: planner's routine slot names, which the old PHYSICAL_ACTIVITIES listed,
#: were here too until Task 10 made them activities (the "anchors" at the
#: end of ACTIVITIES), tagged "physical" there.
NAME_TAGS = {
    "skateboarding": frozenset({"outdoor"}),
    "hiking": frozenset({"outdoor"}),
    "surfing": frozenset({"outdoor"}),
    "cycling": frozenset({"outdoor"}),
    "exploring a new idea": frozenset({"flow"}),
    "scrolling": frozenset({"distracting"}),
    "watching TV": frozenset({"distracting"}),
}

#: The order the planner drew these pools in before they were tags (an rng
#: draws an index, so the order is the draw): DailyPlanner._generate_ai_plan's
#: quiet pool and revise_upcoming's low-mood and rain swap lists.
TAG_ORDER = {
    "quiet": ["relaxing", "listening to music", "reading", "journaling", "meditating", "daydreaming",
              "stargazing", "thinking about user", "remembering happy moments", "watching the snow fall"],
    "gentle": ["listening to music", "reading", "making tea", "journaling"],
    "rainy_day": ["reading", "listening to music"],
}


# ============= The pack =============

CONTEMPORARY = SettingSpec(
    key="contemporary",
    activities=ACTIVITIES,
    weather_flavors=WEATHER_FLAVORS,
    places=PLACES,
    place_descriptions=LOCATION_DESCRIPTIONS,
    npc_event_templates={
        "friend": EVENT_TEMPLATES,
        "estranged": ESTRANGED_EVENT_TEMPLATES,
        "threat": THREAT_EVENT_TEMPLATES,
    },
    text_topics=TEXT_TOPICS,
    invite_activities=INVITE_ACTIVITIES,
    activity_chaos=ACTIVITY_CHAOS,
    universal_chaos=UNIVERSAL_CHAOS,
    universal_chaos_effects=UNIVERSAL_CHAOS_EFFECTS,
    serendipity=SERENDIPITY,
    chaos_emotions=CHAOS_EMOTIONS,
    micro_events=MICRO_EVENTS,
    skill_mappings=SKILL_MAPPINGS,
    skill_milestones=SKILL_MILESTONES,
    dream_templates=DREAM_TEMPLATES,
    catch_up=CatchUpNarratives(
        sleep=CATCHUP_SLEEP_NARRATIVE,
        morning_routine=CATCHUP_MORNING_ROUTINE_NARRATIVES,
        morning_activity=CATCHUP_MORNING_ACTIVITY_NARRATIVES,
        midday=CATCHUP_MIDDAY_NARRATIVES,
        afternoon=CATCHUP_AFTERNOON_NARRATIVES,
        evening=CATCHUP_EVENING_NARRATIVES,
        late=CATCHUP_LATE_NARRATIVE,
        by_activity=CATCHUP_ACTIVITY_NARRATIVES,
        gap_week=GAP_NARRATIVE_WEEK,
        gap_days=GAP_NARRATIVE_DAYS,
        gap_short=GAP_NARRATIVE_SHORT,
    ),
    wants=DESIRE_TEMPLATES,
    want_follow_ups=WANT_FOLLOW_UPS,
    holidays=get_holidays,
    personality_goals=PERSONALITY_GOALS,
    long_term_goals=LONG_TERM_GOALS,
    dream_goals=DREAM_GOALS,
    daily_intentions=DAILY_INTENTIONS,
    nostalgia_fragments=NOSTALGIA_MEMORIES,
    nostalgia_triggers=NOSTALGIA_ACTIVITIES,
    intimate_activities=INTIMATE_ACTIVITIES,
    occupation_places=OCCUPATION_LOCATIONS,
    interest_places=INTEREST_LOCATIONS,
    dream_fragment_templates=DREAM_FRAGMENT_TEMPLATES,
    work_events_positive=POSITIVE_EVENTS,
    work_events_negative=NEGATIVE_EVENTS,
    work_event_emotions=WORK_EVENT_EMOTIONS,
    weather_descriptions=WEATHER_DESCRIPTIONS,
    cherished_objects=CHERISHED_OBJECTS,
    life_event_templates=LIFE_EVENT_TEMPLATES,
    name_tags=NAME_TAGS,
    tag_order=TAG_ORDER,
)
