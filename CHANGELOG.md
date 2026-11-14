# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) — with two extra
narrative sections under 0.1.0, *Behaviour* and *Not extracted*, that a
pure-extraction release needs and Keep a Changelog has no type for — and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-11-14

The humanness program: what she lives, feels, remembers and says comes from
who she is and from what happened, on the world's clock. Every change is
listed below by task; this first part is what a host sees change.

### Notes for hosts

- **Ten new names on `aura_life`** (128 in all, none removed): `Moment`,
  `Share`, `LengthTarget`, `PersonaParameters`, `SettingSpec`,
  `register_setting`, `unregister_setting`, `get_setting`, `Household`,
  `Episode`. Each is the object of the module that defines it, so an import
  by its module path keeps working. Entries below that say a name is "not in
  the root facade" or that the 118 names are unchanged describe the branch
  before this export.
- **Hand an engine the world's instant.** An engine method that decides by
  time takes an optional keyword-only `now=`; without it, it reads the
  host's clock as before. `LifeService` passes its world's instant
  everywhere (`tests/test_world_clock.py`); a host calling one of these
  itself should pass `now=` too: `CognitiveSystem.get_inner_monologue`;
  `GoalEngine.get_emotional_context`, `export_state`, `get_status` (and
  `goalless_hours(now)` for the `goalless_duration_hours` property);
  `EmotionPersistence.get_emotional_context`, `get_current_emotions`,
  `get_dominant_emotion`, `save_emotion`, `get_status`, and
  `get_emotion_persistence(..., now=)` on a first construction; `MemoryTimeSystem.get_anticipations`,
  `export_state`; `ContinuitySystem.get_upcoming_anniversaries`,
  `export_state`; `SocialSystem.update_arc`, `add_plan`, `tick`, `tick_arcs`,
  `tick_obligations`, `tick_conflicts`, `add_obligation`,
  `trigger_conflict`, `resolve_conflict`; `BodySystem.on_activity`,
  `DesireSystem.tick`, `execute_intimate_activity`, `DriveSystem.tick`,
  `ChaosEngine.roll` (her local world time); `DailyPlan.get_current_slot`,
  `get_next_slot`, `get_remaining_slots` (there `now` may also be passed by
  position; `None` is the host's clock). A
  test stand-in replacing one of these methods must accept `now`
  (`lambda *a, **kw: ...`).
- **A new read of the host's clock in the library fails a test**
  (`tests/test_world_clock_lint.py`, its allow-list giving each remaining
  read its reason): what decides her life runs on the world's clock, so a
  host whose world clock is not its wall clock (one that simulates or
  pauses time) sees her days at the world's hours.
- **A user turn does more** (Task 16a): `on_user_message` appraises the
  turn, moves her trust in the user and records an episode, as
  `observe_user_turn` does; a text-only host (no detected emotion) gets the
  text analyzer's reading, and the user model's `observe_message` hears the
  analyzer's dominant emotion where such a call used to pass `""`. The
  analyzer's map keys no longer match inflections or inner substrings
  ("wonderful" is no "wonder", "smartphone" no "smart").
- **Randomness** (ruling T35-R1): `rng=None` hands her private world module
  `random`, as every released version did; an engine built without an rng
  draws from a fresh, unseeded stream. A host that wants repeatable runs
  passes `rng=`.
- **Eating needs the caller's word**: `SustenanceSystem.on_activity(...,
  *, meal=False)`; only a meal feeds her.
- **Her plan and her place** (Task 28): joining a housemate's activity takes
  the joiner's whole hour; `get_current_location` no longer moves her
  mid-transit or mid-joint activity; `plans[].at` in the social export is a
  world instant.
- **Hours, not ticks** (Tasks 29, 34, 34b, 34c): her affect and her money
  run on the hours scale, so a host's tick rate no longer sets how fast she
  gets lonely or spends; the downtime catch-up ticks her affect for the
  hours away and eats every meal she planned in them (three days away:
  loneliness 1.0, hunger as the host that stayed on has it, a mood valence
  of about -0.87 against that host's +0.26, back near neutral within a
  day: Task 41 and DEFERRED.md); a gap
  the process lived through charges her hunger once, whichever of the
  host's first tick and its catch-up comes first; a month is paid and billed
  only after the last one paid.
- **Shares and hints** (Task 17): a proactive hint carries concrete detail
  or is not made, and `share_id=` goes only to a follow-up object that
  declares `accepts_share_id = True`.
- **Her own picks lean less toward a practised activity** (Task 31): 1.7% of
  her own morning picks by day 7 where 0.5.0 had 23%.

### Added

- **The humanness program's public names are exported (humanness Task 19b,
  ruling T19b-R2).** `aura_life` re-exports `Moment`, `Share` and
  `LengthTarget` (`aura_life.context.moment`), `PersonaParameters`
  (`aura_life.personas.parameters`), `SettingSpec`, `register_setting`,
  `unregister_setting` and `get_setting` (`aura_life.settings.spec`),
  `Household` (`aura_life.social.household`) and `Episode`
  (`aura_life.memory.episodes`; its stream, `MemoryStream`, is in
  `aura_life.memory.store` and stays on its module path).
  `tests/api_surface.json` is regenerated (10 names added, none removed: 128)
  and `tests/test_api_surface.py::test_the_humanness_names_are_exported_from_their_modules`
  checks each is its module's own object.
- **A humanness regression test (humanness Task 19b, rulings R26, T19b-R3,
  T19b-R10 to T19b-R13).**
  `tests/test_humanness.py` runs a no-profile control and two contrasting
  invented personas parsed from profile text (`tests/fixtures/humanness_a_profile.txt`,
  a solitary night-owl illustrator; `humanness_b_profile.txt`, a sociable
  early-rising barista) for three days at the production cadence, seeds 1,
  2 and 3, and asserts every section 6 row of the program's spec that
  aura-life owns: no ERROR, no mood label on more than 70% of her waking
  ticks, asleep on 90% of her own nights, forced rest on at most 25% of her
  waking ticks, under 10% of her life events a template slotted with an
  engine label, her plan followed on at least half her waking ticks, hunger
  at 0.7 or more on at most a quarter of ticks, at least 10% of outcomes not
  a plain success, and an activity-mix cosine under 0.90 between the two
  personas. The activity mix is read over what each does outside her work
  (0.711, 0.554 and 0.590 on the three seeds): every occupation's work is
  the one activity "working", about a third of a working persona's waking
  ticks, which alone puts the raw-name cosine at 0.947, 0.925 and 0.929
  whatever the two prefer, and counted as each one's own occupation's work
  puts it at 0.099, 0.086 and 0.094 whatever they prefer too; both are
  printed beside the row. Given the same profile, the two read 0.881, 0.694
  and 0.917. One row fails on this tree and is held: the mood-label row,
  where the no-profile control's "low" is on 76.0% of her waking ticks on
  seed 1 (the other eight persona-seeds read 42.0% to 62.1%). That case is
  a strict expected failure with its number, and a test that is never
  marked keeps it from reading worse than that number, so the held case
  can still go red; the other eight are plain tests. Which case is over
  the bound moves with any change that reaches her mood: before Task 40 it
  was the barista's "content" on 70.9% on seed 3, and on seeds 4 and 5 of
  that tree, not the test's, the illustrator's 72.1% and 74.5%. The
  moment's two rows are `tests/test_moment.py`'s; the run takes about 20
  seconds.
- **The moment (humanness Task 18, spec section 4.10).**
  `LifeService.get_moment(user_text=None) -> Moment`
  (`aura_life.context.moment`: `Moment`, `Share`, `LengthTarget`; not
  re-exported by `aura_life`, whose 118 names stay) is what is true of her
  now, deterministic and with no LLM: `situation` (where, doing what, the
  time of day and the weather), `undercurrent` (the state driving her most
  and at most one more -- tiredness and sleep pressure, mood, hunger,
  illness, drink, a hangover, stress, the user's absence, her shadow's
  unease or guilt -- each a short plain lead and then her
  `state_expressions` entry as written, else `NEUTRAL_EXPRESSIONS`, one per
  `STATE_KEYS` key, an AI persona reaching only `AI_STATE_KEYS`; the state
  the user's words touch comes forward), `on_mind` (at most two cues of her
  memory stream, a rumination, a goal, a curiosity or something put off, a
  stressor, her next plan slot, by salience x novelty x (1 + relevance)),
  `to_share` (at most one unshared thing she remembers, with its stable id;
  the host marks it), `speech` (a length target from her traits, else two
  or three sentences, one less when tired or low; at most one question; no
  naming of feelings or of these notes; the disclosure line of her depth)
  with `length` as integers for a host's token cap (ruling T18-R1), and
  `unspoken` (at most one line: her newest secret, else what her shadow
  hides). `render()` is at most 1,000 characters, second person, no digit,
  no snake_case, no engine label, never "the user". A rendered cue loses
  half its novelty and wins it back over a day of world time, saved in a
  new one-row table `life_moment_state` (a database from before loads with
  every cue fresh); only the memory cues rendered are reinforced (ruling
  T12-R2); nothing else changes (ruling T18-R2). Relevance to the user's
  words is the memory stream's own, `MemoryStream.relevance(query, texts)`,
  through its one guarded `embed` call site (ruling T18-R3). README: "The
  moment" and "Placement contract". Tests: `tests/test_moment.py` (43; its
  acceptance runs three simulated days of two authored personas and a
  no-profile control, twelve captures each).
- **Proactive hints only with concrete detail (humanness Task 17).** Every
  follow-up trigger's `prompt_hint` is made of what moved her -- an episode
  of her memory stream (its gist: what, where, who, feeling) and when it was
  in words ("earlier today", "yesterday", "three days ago"), a life event, her
  plan slot, a calendar row, or, for a need of contact, when the user last
  spoke (`last_user_turn_at`); with none the trigger is not created:
  MOOD_SHIFT, NEED_DRIVEN, LONELINESS_SPIKE and the self-doubt and loneliness
  questions read what is on her mind (`recall(reinforce=False)`), CHAOS_EVENT
  and SOCIAL_EVENT their episodes, GOAL_MILESTONE also fires on a completion
  (its episode and what the goal was) and never on the goalless line, which
  names no goal. A dream is an episode now (tagged `dream` and its
  shareable's id, told to her in the second person): DREAM_SHARE is made only
  of it, never of the emotion residue alone. EXCITEMENT_SHARE waits for her
  memory of the event (the episode carrying its share id, recorded right
  after by every caller), so a mood-change event or a bare `LifeEvent`
  makes none. No number or engine label in a hint ("(intensity 0.4)" is
  gone); a plan slot's activity is phrased ("You're reading at home", "You're
  in the middle of your yoga at the gym"); UPCOMING_EVENT says the day by the
  calendar ("Robin's event 'the recital' is tomorrow", "in two days"), so an
  event under a day away that is tomorrow's no longer reads "Today is the
  day". A host whose follow-up object declares `accepts_share_id = True`
  also gets `share_id=` for a hint about a shareable; any other gets the call
  as before. `LifeEventSystem.mark_shared(share_id, now=None)` stamps
  `shared_at` with the world clock's instant `LifeService.mark_shared` gives.
  `tests/test_proactive_hints.py` (35): a golden example per trigger type,
  the Task 6 lint over each hint; `test_excitement_share_trigger_failure_is_logged`
  records and remembers its event, and the emotion-name scan no longer
  expects the residue's "strange". Fix round 1: a slot whose first word in
  -ing is a time of day or a season (`TimeOfDay`, `Season`) is a thing she
  has ("You're in the middle of your morning shower", no longer "You're
  morning shower"), and a name with its own article takes no "your" ("in the
  middle of a concert"); a dream's activity is said as she would say it
  ("thinking about Robin", not the id "thinking about user") in the dream,
  its episode and DREAM_SHARE; the dream and the goal completion a trigger
  was made of are saved (table `life_trigger_state`), so a restart no
  longer offers a fired one again; 11 more tests there (46).
- **The user over time: relationship depth, a style hint of her own and
  absence (humanness Task 16b, spec section 4.8).** New module
  `aura_life.expression.relationship` (every number with its source in its
  docstring). `LifeService.relationship_depth` (0..1, read-only) grows on
  each world day with a user turn (`CONTACT_DAY_GAIN` 0.05 x (1 - depth))
  and on a disclosure that answers one from the other side
  (`DISCLOSURE_GAIN` 0.1): the user's `disclosure` on `observe_user_turn`,
  and hers when `mark_shared` (or `mark_experience_shared`) marks something
  of her life shared; after `REGRESSION_AFTER_DAYS` (7) without a user turn
  it regresses by 0.05 a day, read from `last_user_turn_at` on the world
  clock. `LifeService.after_absence` (read-only, ruling T16-R7) is her
  `after_absence` state -- an `AfterAbsence(hours, intensity, feelings,
  attachment_style, ongoing)` from 8 hours away (the "it's been a while"
  of `get_connection_context`), rising to its full over the first week,
  its feelings by `attachment_style`: secure glad and curious, anxious
  worried then hurt, avoidant indifferent (unset reads as secure); the
  absence the user's return ended stays her state while that conversation
  goes on. It is computed, not rendered (Task 18 renders it).
  `export_outer_state()["expression"]` gains `depth` and `after_absence`,
  `ExpressionSystem.get_status()` gains `depth` (as of the user's last
  turn; `LifeService.get_status()["expression"]["depth"]` is the depth now,
  regressed by any silence, as the export gives it);
  `ExpressionSystem.distance_line()`, `depth`, `depth_at`, `note_user_turn`,
  `note_her_disclosure`, `refresh_stage`, `reunion_hours` are new; the
  expression table gains a `depth_state` column (migrated: a database from
  before loads its stage's depth and saves). The open-disclosure cap
  (`OPEN_DISCLOSURE_CAP`, 1.0 a side) and the point where an absence's
  second half begins (`SECOND_HALF_FROM`, 0.5) are constants of the block.
  Tests: `tests/test_user_over_time.py` (22).
- **`LifeService.observe_user_turn(text=None, *, sentiment=None,
  emotions=None, topics=None, disclosure=None, language=None) -> dict` --
  the user's turn, appraised (humanness Task 16a, spec section 4.8).** It
  does everything `on_user_message` did and returns her appraisal,
  `{"valence", "persona_emotions", "trust_delta"}`. She appraises the
  user's emotion (the host's `emotions`, else the text analyzer's reading of
  `text`) and never copies it (`aura_life.emotion.user_appraisal`): concern
  for a sad user, times her warmth (`PersonaParameters.empathy`); amusement
  at a playful one; warmth for a glad one; hurt and irritation at hostility
  aimed at her (the turn speaks to her), split by her volatility (hostility:
  the analyzer's anger labels, and a host's name the analyzer reads as one,
  "angry" or "irritated", `user_appraisal.is_hostile`; warmth likewise, a
  host's "grateful", "affectionate", "warm" or "connected" being the
  analyzer's "thankful", "loving" and "intimate", `user_appraisal.is_warm`,
  Task 16b step 0.3; no analyzer label changes its reading; a warm word the
  vocabulary has no name for, "love", "adore" or "caring", is felt as its
  label, "loving", as its warmth is read for trust); all times
  her volatility's multiplier, felt once by the host's `EmotionEngine` and
  her mood. `AffectSystem.on_user_emotion_detected` gets its first caller:
  the user's strongest emotion, its intensity and her trust in the user.
  Her trust in the user can fall now (`IdentitySystem.apply_user_turn`):
  hostility at her takes up to a rejection's drain (0.01), warmth for her
  adds up to one more message's gain (0.003) and `disclosure` up to a
  personal question's (0.005), all times her trust multiplier. Hostility
  aimed at her is contact, not a meaningful interaction (Task 16b step 0,
  ruling T16a-R3): such a turn eases her loneliness by plain contact's 0.05
  (`AffectSystem.on_social_interaction(meaningful=False)`) and leaves her
  last meaningful interaction where it was; every other turn stays
  meaningful (0.15), as every message was before. A turn that
  left a trace -- the host's `topics`, a `disclosure`, or a feeling in her --
  is an episode of her memory stream, tagged `conversation` and its
  `topics` (one string is one topic), with her strongest feeling and the
  turn's valence: a gist of
  what it was to her, from a small phrase table
  (`aura_life.memory.episodes.CONVERSATION_PHRASES`, `conversation_phrase`:
  "They lashed out at you", "They opened up to you", "They told you about a
  hard time, talking about work"), never the user's words (Task 16b step 0,
  ruling T16a-R2: recalled gists reach the moment, and an episode a message
  would push her days out of the stream's 2,000); a neutral turn records
  none. Each turn's world instant is kept by `LifeService.last_user_turn_at`,
  and her state saves it (table `life_user_turn_state`; an older save
  loads as `None`; identity's `to_dict` gains `last_user_turn_at`). The
  vocabulary gains "concerned" and "irritated", at the points of "worried"
  and "annoyed". Tests: `tests/test_user_turns.py` (47).
- **The text analyzer reads words, negation, curly apostrophes and French
  (Task 16a).** `TextEmotionAnalyzer.analyze_text` (and
  `get_emotional_tone`, `get_dominant_emotion`, each with a new optional
  `language`) matches phrases and words on whole words ("dismiss you" holds
  no "miss you"); a word or phrase starting 1 to 3 words after a negator in
  its clause is not felt ("I'm not happy about this at all", "honestly I
  don't love it", "je ne suis pas triste"); a clause ends at `.,;:!?`,
  "but" and "mais"; curly apostrophes read as straight ones; a basic French
  lexicon (`FRENCH_KEYWORDS`, `FRENCH_PHRASES`, `FRENCH_AMPLIFIERS`) reads
  each French word as an English entry, whose label and intensity it takes
  ("Je suis tellement triste aujourd'hui" is sad); `language="en"` reads
  English only. New helpers: `normalize_text`, `matched_cues`,
  `addresses_listener(text, language=None)` (the turn speaks to her: "you",
  and unless `language` is English a French "tu", "te", "vous" or "t'";
  "ton" and "ta" are left out as English words, "a ton of").
- **Profile text format gains example dialogue, state expressions, explicit
  traits, a setting pack, a household, an attachment style, an optional
  intimacy rate, a phrase filter and NPC kinds (humanness program Task 7).**
  `ProfileParser` accepts five new pieces of `profile.txt`, all optional and
  additive -- a profile that uses none of them parses exactly as it did
  before: `== EXAMPLE DIALOGUE ==` (blocks of `Speaker: line` separated by a
  line `<START>`, speaker is `{{user}}` or the persona's Name, text kept
  verbatim); `== STATE EXPRESSIONS ==` (`key: free text`, one line per state);
  `== VOICE & COMMUNICATION ==` gains `Never Say:` / `Allow Phrases:`
  (semicolon-separated, for the host's phrase filter); `== ENGINE SEEDS ==`
  gains `Traits:` (comma-separated `key value` pairs, 0..1), `Setting:`,
  `Household:` (comma-separated persona ids), `Attachment Style:`
  (`secure | anxious | avoidant`) and `Intimacy Rate:` (optional 0..1); and
  `== SOCIAL CIRCLE ==` entries take an optional `[kind]` tag after the name
  (e.g. `- Shirley [threat]: ...`), defaulting to `friend`. The three closed
  vocabularies -- `STATE_KEYS`, `TRAIT_KEYS`, `NPC_KINDS` -- live in one place,
  `aura_life.personas.keys` (re-exported from `aura_life.personas`), so a
  later task's trait/parameter derivation and the profile parser read the
  same spelling. A key outside its vocabulary is **kept, never dropped** and
  reported by `ParsedProfile.validate()`; a `Traits:`/`Intimacy Rate:` value
  outside 0..1 or unparsable is **dropped, never clamped**, also reported by
  `validate()`. An `EXAMPLE DIALOGUE` block with no parseable lines is
  dropped the same way.
- **`PersonalityDefinition` carries all of the above**, plus `personal_goal`
  (only ever set by `PersonalityDefinition.from_concept`, which now carries
  the generator concept's `goal` into it instead of dropping it -- an
  override still wins last). Every new field defaults to today's behaviour
  (`setting=""` means the default `contemporary` setting pack, see setting
  packs below; `intimacy_rate=None` means unset). Social-circle NPC dicts
  gain a `"kind"` key.
- **`ParsedProfile.to_personality_definition()` stops dropping four fields it
  had parsed all along**: `quirks` (from `behavioral_quirks`),
  `communication_traits`, `avoids` and `relationship_style` now reach the
  definition on the direct parse -> definition path, matching what the
  `ProfileDatabase` round trip already produced. A profile that set any of
  these and only ever went through `to_personality_definition()` (not the
  database) was silently losing them; that path is retired -- a passing
  `Avoids:`/`Behavioral Quirks:`/`Communication Traits:`/`Relationship
  Style:` line has always meant something once a persona reaches the engines,
  and now it means something on both paths.
- **`ProfileDatabase` persists and migrates every field above.** Three new
  tables (`profile_state_expressions`, `profile_traits`,
  `profile_example_dialogue`, the last ordered by block then line so
  dialogue replays in the authored order); four new `profile_core` columns
  (`setting`, `attachment_style`, `intimacy_rate`, `personal_goal`);
  `household` / `never_say` / `allow_phrases` join the existing
  `profile_lists` convention; `profile_social_circle` gains a `kind` column
  (`DEFAULT 'friend'`, so an existing NPC row is backfilled on open, not left
  `NULL`). An existing `profile.db` from before this change opens and
  migrates in place -- no re-migration from `.txt` required.
- **Setting packs: the world a persona lives in is data, registered by key
  (humanness program Task 9, spec section 4.4).** Measured before: every
  persona lived one modern-suburban life, because each engine read its
  catalogue from a module-level constant -- 45 activities, 20 wants, fixed
  goal pools, generic NPC events, US and GB holidays -- and genre only shaped
  persona generation (a Dustlands-2090 gridrunner spent 0 of 289 activity ticks
  on gridrunning, weapons, smoking or drinking). The new `aura_life.settings`
  holds them as `SettingSpec`: activities (each may be restricted to persona
  ids with the new, optional `Activity.persona_ids`) and their weather
  suffixes; places, the places an occupation or an interest adds, and their
  generic descriptions; NPC event templates keyed by `NPC_KINDS`, text topics
  and invitations; activity twists, life events and the emotions they carry;
  micro-events; skill mappings and milestone texts; dream templates and dream
  fragments; catch-up and gap narratives (`CatchUpNarratives`); wants and
  follow-up wants; a holiday calendar; goal pools and daily intentions;
  nostalgia fragments and their triggers; a workday's events and what each
  makes her feel; weather descriptions; cherished objects; life-event titles;
  and the intimate activities (left out -- `None` -- they are the default
  setting's, so how often she does one never depends on her setting; `[]` is
  none). `register_setting(spec, *, replace=False)` stores a deep copy,
  refuses a taken key without `replace=True`, and refuses a spec an engine
  would trip on or never match with a `ValueError` naming every problem (a
  string where a list belongs, at any depth; an activity with no narrative;
  a trigger, skill mapping, milestone or derived place that is not a pair; a
  weather's or a time of day's name where its `Weather` or `TimeOfDay` member
  belongs; a tag outside `ACTIVITY_TAGS` ...); `unregister_setting(key)`
  returns whether it was registered (the default cannot be dropped);
  `get_setting(key)` treats a blank key as `DEFAULT_SETTING = "contemporary"`
  and raises `ValueError` naming an unknown key and every registered one.
  - `contemporary` is today's catalogues, moved unchanged -- byte-identical
    strings and numbers, in order -- into `aura_life.settings.contemporary`.
    Every moved name stays importable from its old module
    (`activity_engine.ACTIVITIES`, `life_service.MICRO_EVENTS`,
    `chaos_engine.ACTIVITY_CHAOS`, `daily_planner.get_holidays`,
    `daily_planner.OCCUPATION_LOCATIONS`, `desire_system.INTIMATE_ACTIVITIES`,
    `affect_system.WORK_EVENT_EMOTIONS`, `cognitive_system.DREAM_TEMPLATES`
    ...) as a legacy re-export; `IntimateActivity` moved to
    `aura_life.models` and is re-exported from `desire_system` too. The three
    that were literals inside a method are named there now
    (`WEATHER_FLAVORS`, `CATCHUP_ACTIVITY_NARRATIVES`, `WANT_FOLLOW_UPS`),
    and `LifeService._DEFAULT_LOCATIONS` is `PLACES`.
  - Activities carry tags -- `Activity.tags`, a frozenset from
    `aura_life.settings.ACTIVITY_TAGS` -- and the engines read the tags
    instead of sets of today's activity names: "physical" (an AI persona's
    plan and moment-shares leave it out), "outdoor", "flow", "focus",
    "distracting", "quiet" (an AI persona's quiet hours), "fallback_rest"
    (what an empty slot, a quiet hour or a cancelled workday becomes),
    "restful", "soothing", "gentle", "clear_sky", "rained_off" and
    "rainy_day" (the planner's mood and weather swaps), and "sleep", "nap"
    and "meal". `SettingSpec.name_tags` tags a name that reaches an engine
    without being an activity (the planner's routine slots), and
    `SettingSpec.tag_order` keeps a pool's draw order. The contemporary pack
    is tagged so that each old name set is exactly its tag, which a test
    asserts set by set; `daily_planner.PHYSICAL_ACTIVITIES`,
    `daily_planner.OUTDOOR_ACTIVITIES` and `cognitive_system`'s focus sets
    keep their names but are no longer read.
  - Every setting can sleep, nap and eat: one none of whose own activities
    is tagged "sleep", "nap" or "meal" gets the library's `sleeping` or
    `napping` (the contemporary ones) or `having a meal` (new) for it
    (`SettingSpec.resolved_activities`, `aura_life.settings.universal`). A
    meal relieves hunger whatever it is called: `SustenanceSystem.on_activity`
    takes `meal=`, which `LifeService` sets from the tag. Measured on a
    three-activity setting over two production-cadence days: hunger below
    0.7 on 100.0% of 576 steps, against 30.2% before.
  - `LifeService` resolves the persona's setting from
    `PersonalityDefinition.setting` (empty is `contemporary`) first thing at
    construction -- an unknown key raises before anything touches the disk --
    and every engine reads its catalogues from it: `ActivityEngine` (the
    activities open to her persona id, and the weather suffixes),
    `ChaosEngine`, `SocialSystem` (the templates for an NPC's kind, the
    default kind's when it has none), `DailyPlanner` (wants, follow-ups,
    holidays, places, tags), `GoalEngine`, `MemoryTimeSystem`,
    `CognitiveSystem`, `CareerSystem`, `LifeEventSystem`, `DesireSystem`,
    `WorldEnvironment` (place and weather descriptions, cherished objects)
    and `LifeService` itself (the location registry, micro-events, skills,
    dreams, catch-up, what a work event makes her feel). Each takes a new
    `setting=` keyword that defaults to `contemporary`, so a bare engine is
    unchanged -- so do the `from_dict` a reload goes through (`ChaosEngine`,
    `CognitiveSystem`, `CareerSystem`, `DesireSystem`, `MemoryTimeSystem`);
    `ActivityEngine` and `DailyPlanner` also take `persona_id=`.
    `WorldEnvironment` takes `setting=` at construction and per call
    (`get_status`, `export_state`, `get_location_description`,
    `get_weather_description` and the cherished-object methods), so a shared
    world is handed each persona's, and so does `PersonaWorldView`. An engine
    given a catalogue the setting leaves empty does without it (no
    micro-event, twist, NPC event, goal, holiday, dream or nostalgia of that
    kind) instead of raising.
  - Her setting is saved with her (a `life_setting` table; a database from
    before it was saved in the default setting, the only one there was).
    Loaded into another setting than the one saved, she keeps her memories
    and relationships -- every other table -- and drops what pointed at the
    old setting's places: those places (registry, planner keys and their
    rows), the day's plan, a trip to one, and being at one (she is home). One
    INFO line says what went.
  - A persona with no setting is byte-identical to before: a seeded
    two-day production-cadence run of two personas reproduces, step by
    step, the trace recorded from the code before the move
    (`tests/fixtures/default_setting_trace.json`), and every moved
    catalogue's digest matches the one taken before it moved
    (`tests/fixtures/default_setting_catalogues.json`). Both are recorded
    fixtures that fail when missing and are re-recorded only on purpose
    (delete, then run with `SETTING_TRACE_WRITE=1`) -- so far once, for the
    they-agreement fix under Fixed, which changed no step.
  - Not yet: the planner still names its routine slots for today's life
    (waking up, meals, work, commuting, classes, bedtime). In another setting
    they match none of her activities, so the activity tick does one of hers
    instead, until Task 10 makes planned slots executable; catch-up after
    downtime still records the plan's slot names as they are.
- **Households: personas who live together (humanness program Task 11, spec
  section 4.5).** Measured before: Lina and Roberta live together, and each
  one's life knew the other only as a social-circle entry drawing friend
  events -- "Had coffee with Roberta" while Roberta slept. `Household()`
  (`aura_life.social.Household`; not in the root facade, whose 118 names are
  unchanged) is a runtime link: `LifeService(..., household=h)` joins it under
  `persona_id` (required then) once built, `stop()` leaves it -- once no
  member's activity tick is running, and before she is saved, so no housemate
  writes into a saved life; even when stopping the scheduler or a thread
  fails -- and `start()` joins it again. A household holds one service per
  persona id, and holds it weakly: a service dropped without `stop()` leaves
  once nothing else holds it (`join()` collects garbage once before refusing
  a persona id that looks taken). Her view of
  each housemate is the housemate's live state, read from the housemate's own
  service when asked: her life context gains "The people you live with"
  ("Roberta is asleep", "Roberta is here with you (reading)", "Roberta is at
  the cafe"), and `get_status()` / `export_outer_state()` gain
  `["social"]["household"]` -- each housemate's persona id, name, whether she
  is asleep, her location (and whether it is this persona's), and her last
  activity (never an intimate one: what she does in private is hers alone)
  -- with the persona ids her definition expects
  (`PersonalityDefinition.household`) and those not joined. Her
  social-circle entry for a housemate (the one named with the housemate's
  persona id or definition name, in any case) draws no ordinary NPC event
  (`SocialSystem.tick(skip=...)`); one she expects who is not joined is an
  ordinary NPC again. Nothing of it is saved: her database holds her own
  life only.
  - What they do together. A new activity tag, "joint"
    (`aura_life.settings.ACTIVITY_TAGS`), marks what housemates can do
    together; the contemporary pack tags 24 activities (the meals, cooking
    and baking, tea, music, games, walks, runs, the gym, yoga, errands,
    tidying, relaxing ...). When one member is about to do a joint activity,
    the housemates free for it -- awake and outside their sleep window, where
    she is, not on the way anywhere, not already acting at that instant, in
    an hour their plan leaves free or plans for that very activity, with the
    energy and the social battery -- join her on a roll of her own new
    "household" random stream (the chance one of her people gets in touch:
    `NPC_EVENT_CHANCE` times her sociability). She does it first (it may take
    her elsewhere); each who joins does it through her own activity pipeline
    where she now is, at her entry's instant, and her own next activity tick
    within one activity interval is taken by it -- so each does it once.
    Joining takes the joiner's hour (Task 28, below): her plan's slot for it
    becomes the activity where it is, so she stays there for the rest of the
    hour. The
    entry is in every log, worded from its own side (`JOINT_LINES`: "Roberta
    joined her" / "She joined Lina"), and each one's company eases the
    other's loneliness as a meaningful interaction and counts on their arc
    and in how each sees the other. Every member's activity tick holds the
    household's lock, so a joint activity never writes into a housemate
    whose own activity tick is running. Measured over three production-cadence
    days, two personas at home (seeds 5, 11, 23): 8, 6 and 5 joint
    activities, every one in both logs. `tests/sim_helpers.py` resets every
    probe before a step's first tick, so the one who joins has it in her step
    record.
- **A memory stream (humanness program Task 12, spec section 4.6).** Measured
  before: there was no episodic memory -- `LifeService` accepted a
  `memory_service` and only assigned it, nostalgia was ten generic
  templates, and nothing she lived could be recalled. `aura_life.memory` (not
  in the root facade, whose 118 names are unchanged) holds
  `Episode(id, at, place, people, what, emotion, valence, importance,
  strength, last_recalled, tags)` and `MemoryStream`, and `LifeService`
  records an episode, on the world clock, for each activity she does (as she
  would name it; with the housemates she did it with, tagged `together`; its
  category and tags, and the share ids of the shareable and life event it
  made), each thing one of her people does ("a call from Mara", with them;
  unwelcome contact with what it made her feel), each chaos event, small
  moment and good or bad day at work (in her setting's words addressed to
  her: "You spilled coffee on your shirt"), a goal reached or given up (a dip
  in motivation is no episode), a skill milestone and a finished book --
  with their share ids. Each takes her mood's valence when she lived it;
  `MemoryStream.record` takes an appraisal's emotion, intensity and valence
  instead (for the outcome appraisal and the user's turns still to come).
  Not recorded: what she does in private -- measured, with it the stream's
  top episodes were every one of them, several a day, as strongly felt as the
  library makes them, and kept by importance they would outlast the rest of
  her life -- sleep, mood-change life events, catch-up after downtime.
  - Importance, 0.1..1: `0.1 + 0.9 x (0.6 x felt + 0.2 x new + 0.2 x anyone
    there)` -- felt, her strongest emotion's intensity; new, an activity,
    place or person she has not met in 7 days, counted only once her memory
    spans 7 days (her first days of memory are not her first days of life).
    Measured over three production-cadence days, three personas, seeds 9, 1
    and 2: 152-184 episodes each, importance 0.10-0.33 (median 0.18),
    unwelcome contact on top; 7.9-12.0 importance summed per simulated day;
    over ten days (seed 9) 7 of 1,686 episodes were new to her.
  - `LifeService.recall(query=None, k=3) -> list[Episode]`: ranked by
    (recency (0.995 per hour since she last recalled it) + importance +
    relevance (the share of the query's words the episode shares, or the
    cosine of the host's vectors) + mood congruence (1 - |valence now -
    valence then| / 2)) x retention -- each term on 0..1 by construction,
    not min-max scaled over the episodes ranked, and retention `exp(-t/S)`,
    t the days since she last recalled it, S its strength (ruling T12-R1):
    what she does not recall fades from unprompted recall (0.37 of its weight
    a day on, 0.05 three days on), and what she keeps recalling stays. A
    cued recall -- a query names what to remember -- is not weighted by
    retention (ruling T12-R5): a good cue brings back a faded memory. Recalling
    strengthens: each episode returned gains 1 of strength S (days), and
    its recency and retention start again, saved at once;
    `recall(..., reinforce=False)` reads the same episodes without that, for
    a host that shows her memories rather than has her remember them
    (ruling T12-R2). `Episode.gist()` is one plain sentence -- "Cooking a meal at home
    with Roberta, feeling warm." -- no digit, no snake_case, never a
    transcript.
  - Kept: the 2,000 most important episodes, pruned as each is written (of
    equals, the earliest written), in three new `life.db` tables
    (`life_memory_episodes`, `life_memory_facets`, `life_memory_state`,
    `CREATE TABLE IF NOT EXISTS`), saved on write and read when the service
    is built, so a service that never starts goes on from the saved stream.
    Ids never repeat. `reset_state()` -- what a host calls to clear a
    persona's memory -- forgets every episode, on disk too.
  - A thirteenth hook, `aura_life.hooks.embed(texts) -> list[list[float]]`,
    optional by design: relevance uses it when a host registers it, and
    keyword overlap -- said at DEBUG only -- when none does; a hook that fails
    or answers anything but one finite vector per text is not used, with one
    WARNING. Its one call site is guarded, and
    `tests/test_hook_call_sites.py` pins it as guarded; the unguarded census
    is still thirteen.
  - `aura_life.personas.pronoun_render.render_second_person` (and its
    `SECOND_PERSON` tokens): a template addressed to the persona -- "you",
    "your", verbs as for "they".
- **Reflection, and nostalgia and chapters drawn from real history
  (humanness program Task 13, spec section 4.6).** Measured before: nostalgia
  was ten generic templates pinned in the prompt, monthly chapters recorded
  whatever the mood happened to be at the moment of writing, and nothing
  reflected on the memory stream Task 12 gave her -- Generative Agents found
  reflection load-bearing on its own (removing it dropped their believability
  score from 29.89 to 26.88).
  - `aura_life.memory.reflection.generate_beliefs`: once the importance she
    has lived since her last reflection sums to 15.0 (spec 4.6; Generative
    Agents' 150 on this library's 0.1..1 scale), `LifeService._reflect`
    looks at that window of her own episodes and derives up to 3 beliefs,
    deterministically -- a repeated activity with the same person (>= 3
    times), a recurring place (>= 3 times), a mood trend (>= 5 episodes,
    mean valence past `MOOD_VALENCE_BAND`) -- falling back to her single
    most important episode, quoted, when none of the three patterns is met.
    Each belief is remembered as an episode of her own (`tags=("belief",)`)
    and its grounding episodes are reinforced (ruling T12-R2: reflection
    that surfaces an episode reinforces it). Measured over nine simulated
    days, one persona, seed 17: 15 belief episodes from 522 total, e.g.
    "You've been at the cafe most days this week." An optional
    `reflection_llm=True` (default off, ruling R4) asks the host's
    `get_llm_service` hook for one more belief from the same window on top
    of the deterministic ones; a missing or raising hook leaves those
    exactly as they are, with no ERROR.
  - Nostalgia (`memory_time`) now draws from a real episode at least 7
    simulated days old when she has one -- her gist replaces the setting's
    template, and surfacing it reinforces it -- falling back to the ten
    templates (`aura_life.settings.contemporary.NOSTALGIA_MEMORIES`) only
    when no episode is old enough yet. Measured over the same nine-day run:
    13 nostalgia events, the first 11 (days 1-8) templated, the last 2
    (days 8-9, once episodes had crossed the 7-day mark) real: "Discovered a
    new artist you immediately loved at home, feeling joyful."
  - Two prompt-bound paths read a nostalgia `memory_reference` unrendered
    (found in Task 9): `LifeService._evaluate_life_triggers`'s nostalgia
    hint and `LifeContextBuilder`'s "A memory surfaced" line. Both now render
    it addressed to her as "you" (`pronoun_render.render_second_person`) --
    the same form her memory stream already quotes episodes in -- before it
    reaches either.
  - A life chapter (`continuity.monthly_tick`, unchanged itself) is now fed
    the mean valence and dominant activities of the WHOLE period it covers
    (`LifeService._chapter_window_stats`, read from her memory stream), not
    `_behavior._activity_history` (its last 50 only, a day or so at
    production cadence) or her mood at the one instant the month happened to
    end on.
- **Appraisal, and outcomes that can go wrong (humanness program Task 14,
  spec section 4.7).** Measured before: every activity succeeded, and every
  activity was felt as the same fixed emotions every time -- `ActivityEngine`
  copied its setting's `emotion_effects` onto the log -- never judged against
  what she wanted, needed or valued. An appraisal step (Chain-of-Emotion,
  PLOS ONE 2024) raised perceived naturalness (p = .008); human text carries
  more negative emotion and more variation than LLM text.
  - `aura_life.emotion.appraisal.appraise(event, parameters, goals, needs,
    values) -> list[EmotionSpike]` (no draw, no clock): what she feels about
    an `AppraisalEvent` (what happened, its outcome, what it feels like when
    it goes well, the needs it meets, whose doing it was, the chance of
    success she had). A success is felt as its own emotions; a failure as
    frustration (annoyance, for a commitment she had to keep -- a shift, the
    commute, a class, study); what she doubted becomes relief or
    resignation (the OCC model's prospect-based emotions); an active goal
    that lists it adds pride or disappointment, each need she came with its
    own feeling met or unmet (`NEED_FEELINGS`: satisfied/frustrated for
    hunger, connected/lonely for company ...), a value she holds fulfilment
    or discouragement -- each up to a third of the activity's stake, so all
    three double it -- and every feeling is scaled by her volatility
    (`PersonaParameters.affect_reactivity`: the same failure is felt three
    times as strongly at volatility 0.9 as at 0.1). A mixed outcome is half
    of each. A neutral persona's success she was sure of, serving nothing
    else, is felt exactly as her setting wrote it.
  - How an activity goes: `ActivityEngine.roll_outcome` draws success, mixed
    or fail from `outcome_chances(activity, energy=, valence=, skill=)` on an
    "outcome" stream of its own (`LifeService` derives it; never the
    service's or the activity choice's) -- a base risk of 0.08, more when
    she is tired for what it takes (its effort), low (her mood's valence
    below 0) or new to the skill it trains, at most 0.5, a third of it
    outright failure. Measured over three production-cadence days, the
    control and Lina's and Roberta's baselines, seeds 1-10 (3,593
    activities): 84.9% went well, 10.2% half well, 5.0% wrong; 11.9-18.5% not
    plain success per run.
  - What happened is told in her setting's words: `Activity.outcomes`
    (`"mixed"`/`"fail"` -> narratives, validated by `register_setting`),
    two lines each for every contemporary activity she can do and for the
    universal meal; the library's neutral words
    (`activity_engine.NEUTRAL_OUTCOME_NARRATIVES`, the activity named) for an
    activity whose setting has none. A success keeps its narratives, the
    text it always had. One that did not go well has no thought and is
    nothing to share.
  - `ActivityLog.outcome` ("success" by default) and an `activity_logs.outcome`
    column (`DEFAULT 'success'`, added to an existing database on open);
    `ActivityEngine.export_recent_state` reports it.
  - `LifeService(appraisal_llm=False)`: with `True`, what she feels is asked
    of the host's LLM (`get_llm_service`, guarded) instead, its reply
    validated -- a feeling the emotion vocabulary does not know is dropped,
    so is one whose valence contradicts how it went (a failure is never
    felt as joy; `parse_llm_appraisal(..., outcome=)`), each intensity
    clamped to 0..1, at most three kept -- and scaled by her volatility; a
    missing or raising hook, or a reply with nothing usable, leaves the
    deterministic appraisal as it is, with no ERROR (ruling R4: off by
    default). The host's client is called synchronously on her tick, under
    `Household.lock` when she has housemates, and must return or raise
    within a bounded time: that bound is the client's (ruling T14-R2).
  - **A day has a quality of its own (fix round 1, ruling T14-R1).** Some
    days are better than others: once per persona-day -- keyed by the date
    her last night ended (new `EnergySystem.last_wake`), so a night owl up
    past midnight is still in the day before -- at her first
    waking tick outside her sleep window, a valence offset on her mood's
    target is drawn (`AffectSystem.new_day`, on a "day_quality" stream of
    its own) -- `gauss(0, DAY_QUALITY_SD = 0.5)` plus
    `DAY_QUALITY_PER_SLEEP_QUALITY = 0.5` x (last night's sleep quality -
    `body_system.SLEEP_QUALITY_BASE`, the body's own 0.7, now named), times
    her volatility's multiplier -- and kept all day and across a reload
    (`life_affect_state` gains `day_quality_offset` and `day_quality_date`;
    an older row has none until her next draw). A night waking or a nap
    never draws again. The spread is tuned against the humanness spec's "no
    mood label on more than 70% of a persona's waking ticks" (section 6,
    rulings P1, T4-R2): over three production-cadence days, seeds 1-10, it
    now holds on 9/10 for the no-profile control and Lina's baseline and
    10/10 for Roberta's (before: 10/10, 0/10 and 2/10 -- Lina "neutral" on
    74-88% of waking ticks).
  - `AffectSystem.on_emotion_event(..., reactivity_applied=False)`: `True`
    for a feeling already scaled by her volatility (an appraised one), so
    mood does not scale it by the same multiplier again.
  - `JointSide.outcome`: a housemate who joins her takes how it went for her
    (one event, one outcome) and appraises it her own way.
- **Stressors as objects, and coping (humanness program Task 15).** Measured
  before: over three production-cadence days every persona listed "money
  worries", "errands piling up" and four "avoiding: ..." labels on nearly
  every tick while her stress read 0.00-0.01 -- a label, once added, stayed
  until something removed it, which nothing but hunger, sleep and sanity
  ever did, and her level only ever got a one-time +0.05 per new label that
  wore off at 0.005 a tick. A source was listed at stress 0 on 382-558 of a
  persona's ~590 waking energy ticks, and some were keys, not words
  (`sleep_deprivation`, `struggle:...`, `sanity`).
  - `aura_life.models.Stressor(source, severity, controllability,
    expires_at=None, kind="")`: what she is stressed about, in words; how
    much it weighs (0..1]; how far ending it is in her hands (0..1); the
    world instant it lapses unless raised again (`None`: until resolved);
    what produced it. `StressState.stressors` lists them heaviest first, and
    `StressState.sources` -- the list hosts read -- their words in the same
    order.
  - Her stress level is what her stressors weigh together plus the tension a
    hard moment adds on top (a sharp word, a busy place), recomputed
    whenever a stressor comes, goes or lapses. The tension fades by 0.06 an
    hour of world time (`STRESS_EXCESS_DECAY_PER_HOUR`: the old 0.005 a
    tick at the scheduler's 5-minute energy tick -- the same at any
    cadence now); comfort, a joke, a calm place or any activity ease the
    tension, never what her stressors weigh. **A listed stressor always
    weighs**: `level > 0` whenever `sources` is not empty. Resolving one
    takes its weight away at once.
  - Every stressor the library raises is a kind of `affect_system.STRESSOR_KINDS`
    (its words, its severity at the full of its cause -- the +0.05 a new
    stressor always added, 0.03 for hunger -- its controllability, and
    whether it is an episode). Its producer raises it while its cause holds
    -- by how much of the cause there is, on the producer's own scale
    (financial stress over its maximum, work stress, overdue errands over the
    backlog's cap, the guilt of what she has put off) -- and resolves it once
    the cause is gone: eating ends hunger, sleep ends "not enough sleep",
    money coming in ends "money worries", an errand done ends "errands piling
    up", the end of her shift ends "work". An upset -- a struggle flaring
    up, someone unwelcome getting in touch, compromising on a value -- is an
    episode that lapses her mood's valence half-life (4 h at neutral
    volatility) after it came. What a persona carries day in, day out (money
    a little tight, a backlog, things put off) weighs about 0.1, under the
    0.2 at which stress shows (`get_stress_description`, mood's stress
    floor, `SANITY_STRESSED_LEVEL`): over three days the no-profile control
    and Lina's and Roberta's baselines never reach 0.2 and their sanity is
    what it was; a nurse with two authored struggles is at 0.2 or more on
    17-31% of her waking ticks (seeds 9, 1, 2) and stays sound.
  - `AffectSystem.raise_stressor(kind, now=None, **words)`,
    `hold_stressors(kind, entries, now=None, share=1.0)` /
    `hold_stressor(kind, held, now=None, share=1.0, **words)` (the kind's
    stressors become exactly those named), `add_stressor(stressor)`,
    `stressor(kind, now=None, **words)`, the `stressors` and `coping_style`
    properties. `on_stressor_added(source, severity=0.05,
    controllability=0.5, expires_at=None, kind="")` keeps its meaning for a
    host (naming one she has changes nothing);
    `on_stressor_resolved(source, now=None)` takes the stressor's weight
    away instead of a flat -0.1, and does nothing for one she does not have.
    `AffectSystem.tick(..., now=)` lapses what `now` has reached (without
    `now` nothing lapses -- the engine reads no clock for it).
  - Exports keep their shapes and add: `export_state()["stress"]` keeps
    `level` and `sources` (her words, at most three) and adds only `coping`
    (a word: the engine export stays short keys with primitive values, and
    aura's inner digest prints the whole `stress` dict into its prompt);
    `get_status()` keeps `stress` and `stress_sources` and adds `stressors`
    (source, severity, controllability, expires_at, kind) and `coping_style`;
    `to_dict()` keeps `stress_level` and `stress_sources` (a JSON list of her
    words) and adds `stressors`, which a reload reads back as they were.
  - Old saves load: `life_affect_state` gains a `stressors` column (added to
    an existing database on open). A row saved before it has only labels;
    each label the library wrote becomes the stressor of its kind in its new
    words (`affect_system.LEGACY_STRESS_LABELS` / `LEGACY_STRESS_PREFIXES`,
    at the kind's full severity until its producer's next tick says how
    much), a struggle or a value conflict lapsing like an episode raised at
    the load; any other label (a host's, an unwelcome person's name) keeps
    its words and weighs 0.05 with controllability 0.5, lapsing like an
    episode. `AffectSystem.from_dict(..., now=)` takes the load instant.
  - **Coping, from her traits** (`PersonaParameters` rows 20-23):
    `problem_focus` (conscientiousness over rumination, f(c) - f(r)),
    `avoidance_scale` (1 + how avoidant), `contact_seeking` (f(s) - 1) and
    `coping_style` ("problem-focused", "avoidant", "social" or
    "balanced"). Problem-focused, she is drawn to what ends a stressor she
    can end herself (`ChoiceState.resolving`: meals for hunger, what clears
    an errand, what tidies -- by what the engine that clears it acts on;
    "the mess at home" is never raised today, since her home's comfort
    never falls below `COMFORT_BLEAK`, the floor of how it is computed) --
    over 100 activity ticks with errands piling up, a problem-focused
    persona ran errands 56 times, an avoidant one never. Avoidant, she puts
    more off and feels its guilt sooner (`DriveSystem`'s `AVOIDANCE_CHANCE`
    and guilt growth, times `avoidance_scale`). Seeking company, stress
    draws her to it, and on a low day the comforts her plan swaps to include
    company (`DailyPlanner`) while everyone else keeps to the gentle ones:
    low days now differ by how she copes. A persona whose traits are neutral
    copes exactly as before (no pull, no scale).
  - `ErrandsSystem.clears(name)` and `HabitationSystem.tidies(name)`: what
    each engine's `on_activity` acts on, now asked by her coping too.
  - `DriveSystem.put_off()` (what weighs on her, the most guilt first) and
    `put_off_share()`; `drive_system.AVOIDANCE_CHANCE` (the 3% it always was)
    and `GUILT_STRESSOR_LEVEL` (the 0.4 it always was).
  - When the figures above were measured (ruling T19b-R7b): four of them --
    "382-558 of a persona's ~590 waking energy ticks" at stress 0, the nurse
    "at 0.2 or more on 17-31% of her waking ticks (seeds 9, 1, 2)", "her mood
    moves by at most 0.008" (the trace re-record under *Changed*) and "6 of
    9, 2.60x" with the stressor model alone (*Coping makes low days differ*)
    -- were written into this file by `a2ea219`, Task 15's documentation
    commit: the first of the code before Task 15 (`2120688`, the parent of
    `442f44f`), the other three of Task 15's work at that commit. Task 15's
    completion did not re-run them, and none was re-run for 0.6.0.

### Changed

- **The relationship stage is read from depth, and the style hint sets no
  register of its own (humanness Task 16b, ruling T16-R6).** The stage
  names (`early`, `comfortable`, `deep`), `ExpressionSystem.get_style_hint()`
  and every exported key stay; the stage is now the deepest whose
  `relationship.STAGE_DEPTHS` (0, 1/3, 2/3) the depth has reached, no longer
  50 and 200 messages (`STAGE_THRESHOLDS` kept for the record), so a long
  first conversation leaves her `early` and a week of silence can lower
  the stage (refreshed each tick); `LifeService._relationship_is_close()`
  reads it as before. A save from before (a stage from a message count, no
  `depth_state`) loads to the depth its stage begins at. `STYLE_HINTS` is
  gone: the hint is the persona's own
  `PersonalityDefinition.communication_traits`, each as a sentence, then one
  `DISTANCE_LINES` line by stage (keeping what is personal, teasing, inside
  jokes); no line of the library's says "complete sentences", "lol" or
  "emoji". A stage gained still adjusts formality, emoji frequency, humour
  and openness as before, each toward its stage's bound and never back (a
  value already past it stays: openness 0.6 is no longer lowered to
  comfortable's 0.5, nor formality raised on a stage gained again); a stage
  lost leaves them. Three tests of
  `tests/test_expression.py` that asserted the message-count stages and one
  that asserted "complete sentences" now assert the depth reading, each
  with its reason in a comment.
- **`on_user_message` is `observe_user_turn` (ruling T16-R1), and its
  keyword triggers read whole, un-negated words (ruling T16-R4).**
  `on_user_message(text, detected_emotion="", emotion_intensity=0.0)` keeps
  its signature and returns `None`; it calls `observe_user_turn(text,
  emotions={detected_emotion: emotion_intensity})` (no `emotions` without a
  detected emotion, so the text analyzer reads the text), so a host calling
  it gets the appraisal, the trust change and the episode too, and a host
  that passes only text (aura-desk) now has the user's emotion read from it.
  The user model's `observe_message` hears the turn's strongest emotion (the
  host's, else the analyzer's) where it heard "" for a text-only call.
  `CONVERSATION_KEYWORD_MAP` (contents unchanged) is matched through the
  analyzer's tokenizer and negation window instead of as substrings: "I
  don't love you" is no affirmation, "glove", "lovely" and "loved" say no
  "love", "wonderful" no "wonder", "smartphone" no "smart", and a curly
  "you’re wrong" is criticism. The test of "no way" (`test_bug_batch.py`)
  compares her mood with the same turn without the cue, since she now
  appraises its "amazing".
- **aura-life 0.4.0 and 0.5.0 are merged in, with one habit mechanism
  (humanness program Task 31).** The branch now holds main's 0.4.0 (her
  social circle and her plans with it as public API) and 0.5.0 (habits from
  a dated history). Her habits are 0.5.0's dated `(raise, damp)` pairs
  (`BehaviorSystem.habit_factors`), acting where 0.5.0 puts them, around the
  top-k cut, now on the branch's choice weights: in her own picks
  (`ActivityEngine.select_activity(..., habit=)`, weights context x
  exp(utility / TEMPERATURE), cut to `TOP_CANDIDATES`) and in the planner's
  hobby slots (`DailyPlanner._slot_draw`, on score x exp(plan preference /
  TEMPERATURE), cut to six); the raise multiplies a weight before the cut,
  the damp a weight after it, and a damped one of the habit-free best keeps
  its place. The branch's undated habit term (Task 10's `HABIT_WEIGHT`, 1.0,
  times an activity's share of her last 50 activities) is gone from
  `ActivityPreferences.utility`, so a habit counts once (merged as it was, it
  counted twice in her own picks); `aura_life.activities.choice.HABIT_WEIGHT`
  is removed (it was never in `choice.__all__`); `ChoiceState.history` is
  still accepted and `LifeService` still fills it, but nothing reads it.
  0.5.0's design values are unchanged (x1.5 up and /1.5 down at most, the
  0.15 peak share, the 3.5-day half-life, full evidence at 60 ticks, four
  weeks). Against 0.5.0, on main's simulated week (`tests/test_habits.py`,
  30 seeded weeks): her plan leans as 0.5.0's does, to the digit, for a
  persona without interests, whose plan weights are flat (journaling 1.00 to
  1.73 and puzzles 1.00 to 0.70 from day 1 to day 7, no score raised past
  x1.333 nor weight lowered past /1.333); her own picks lean less (accepted,
  ruling T31-R1): on the branch's weights x1.5 is +0.203 utility, so a raised
  outsider within reach enters her five but does not head it (of the 20
  morning-at-home outsiders main's test picks from, 14 enter, 2 stay below
  the fifth's weight and 4 are plan-only anchors she never picks), and
  journaling is 1.7% of her own morning picks by day 7 where 0.5.0 had 23%.
  With interests her plan weighs them as the branch does, and the bound holds
  in every draw (accepted, ruling T31-R2): with reading, sketching and
  meditating journaling's chance in a morning slot rises 1.00 to 2.12 and
  puzzles' falls 1.00 to 0.64; with journaling and reading, journaling's
  ratio stays 1.00 (its chance 0.35 on day 7 with and without habits: its
  pair is a raise of x1.14-x1.19, and reading, her other interest, is raised
  more); with reading, poetry and music journaling rises 1.00 to 1.71 (0.5.0:
  1.73); with running, the gym, cooking and walking journaling is never in
  the habit-free six, the habit brings it in on 111 of 540 mornings, and its
  share of a day's morning draws sums to 0.18-0.34 where 0.5.0's planner,
  which reads no interest, gives 13.4-15.1.
- **What she is stressed about is said in words, and weighs while it lasts
  (humanness program Task 15).** The labels become words a person would
  use, which is what a host quotes ("You're stressed about ..."):
  `sleep_deprivation` is "not enough sleep", "work stress" "work", "messy
  space" "the mess at home", "hangover" "a hangover", `struggle:<it>` the
  struggle's own words, `overdue: <it>` "not getting to <it>",
  `value conflict: <value> vs <tag>` "compromising on <value>", and
  `SANITY_STRESS_SOURCE` -- the stressor sanity couples to affect while
  strained or worse -- is "keeping it together" (it was the engine's name,
  "sanity"). What she puts off is one stressor, "putting off <what she has
  put off most>", not one label each. "hunger", "money worries", "errands
  piling up" and an unwelcome person's name are as they were. Her stress no
  longer wears down by the tick while its causes last: it is what her
  stressors weigh (above). The default setting's trace pin is re-recorded
  (ruling T9-R3): from the first activity tick on (step 3) her stress is
  what her money worries weigh, not a bump wearing off, so the "calm" she
  feels about an activity that eases it -- her appraisal reads her stress --
  is a little less; her mood moves by at most 0.008, its label on 7 of the
  plain persona's 576 steps and 1 of the nurse's, and no activity or plan
  over the two days. With the stress model taken out (everything else of
  this task kept), the recording replays step for step.
- **Coping makes low days differ (Task 15, ruling T14-R3).** Task 14's
  day quality left Task 10's introvert/extrovert divergence at 2x the noise
  floor or more on 6 of 9 consecutive seed pairs of 1-10 (2.66x on the
  pinned pair). With coping -- the extrovert, a social coper, keeps her
  plans to see people on a low day and may swap to company; the
  introvert, avoidant, withdraws to the gentle comforts -- it is 9 of 9
  (4.17x on the pinned pair; the mean between-persona divergence 4.4x the
  mean within-persona one, from 3.1x). The stressor model alone leaves it
  where it was (6 of 9, 2.60x).
- **Her activities can go wrong, and she feels them as she appraises them
  (humanness program Task 14).** `LifeService._perform_activity` rolls each
  activity's outcome from her skill at it (her setting's `skill_mappings`;
  0 for one she has never practised), her energy and her mood as she comes
  to it, and her feelings about it -- in her log, the host's `EmotionEngine`,
  her mood and her memory -- are her appraisal of it, no longer the setting's
  fixed `emotion_effects`: what goes wrong brings her mood down. A failure
  moves no goal, inspires no new one, fulfils no want of hers, makes no
  creative artifact and turns no page of her book; what did not go well
  (mixed or fail) is nothing to share and no life event (ruling T11-R1's
  rule for her people's unwelcome news, for her own). Her memory of an
  activity keeps the valence of how it felt -- the appraisal's -- instead of
  her mood's, and one that did not go well is tagged `"mixed"` or `"fail"`.
  Skill practice, energy, hunger (a ruined meal still feeds her) and every
  other engine react as before. The default setting's trace pin is
  re-recorded (ruling T9-R3), and again in the fix round for the day's
  quality (every step moves from the first).
- **A low mood swaps her plan for the comforts she would pick (Task 14 fix
  round 1).** `DailyPlanner.revise_upcoming`'s low-mood swap draws the gentle
  activity by her plan preference (what she is into, how her traits lean
  her -- the weights her free hours are planned by), not uniformly. With
  bad days (the day's quality above), the uniform swap made every persona's
  low day the same few activities and erased Task 10's introvert/extrovert
  divergence (1.56x the noise floor on the pinned seeds, against 2x); drawn
  by her preference it is 2.66x there (6 of 9 consecutive seed pairs of
  1-10 at 2x or more; 9 of 9 before the day's quality).
- **Who her people are to her chooses what they do (humanness program Task
  11, spec section 4.1).** Measured before: a social-circle entry's `[kind]`
  tag reached the definition and the database and stopped there, so every
  person in her life was a friend -- a threat "texted to check in" (12 of 200
  events of Shirley, the mother hunting Lina), and someone she is estranged
  from "called to catch up". `NPC` gains `kind` (`LifeService` fills it from
  the entry's `kind`, lower-cased; "friend" when the entry names none; a kind
  outside `NPC_KINDS` is kept as written, as the parser keeps it).
  `aura_life.settings.UNWELCOME_NPC_KINDS` names the kinds whose contact she
  does not want, `("estranged", "threat")`: `SettingSpec.npc_event_templates_for`
  never gives them another kind's lines -- a pack with none of theirs has no
  events for them -- while every other kind still falls back to the
  default kind's. The contemporary pack gains lines for both (new text, the
  friend lines are untouched): someone she is estranged from reaches her
  unanswered -- a missed call, a message left unread, a reply started and
  deleted -- and a threat never gets in touch as a friend would. A
  `SocialEvent` carries its NPC's `kind` and a `valence`: 1.0 contact from
  someone she is glad of (`CONTACT_EVENT_TYPES`: a text, a call, an
  invitation, time together), 0.0 her thinking of them (a mention), -1.0
  anything from an unwelcome kind.
- **What her people do reaches her (humanness program Task 11).** Measured
  before: contact never touched her loneliness, and no event was ever
  unwelcome. Now (`LifeService._on_social_event`), contact from someone she
  is glad of eases her loneliness -- a call or time together as a meaningful
  interaction, a text or an invitation a small one
  (`AffectSystem.on_social_interaction`'s two reliefs, 0.15 and 0.05; her
  thinking of them eases nothing). Anything from a threat or someone she is
  estranged from is felt (`social_system.UNWELCOME_KIND_EMOTIONS`: anxious
  and unsettled, or guilty and sad, 0.1 each -- what the contemporary "uneasy
  feeling" twist weighs), cools how she sees them
  (`IdentitySystem.update_from_social_event` takes away the 0.02 it adds for
  anyone else), strains their relationship arc and feeds her stress (a
  stressor named for them, one per person). It is never news to share
  (ruling T11-R1): an unwelcome event is not share-worthy -- not by its type,
  and no share roll is drawn for it -- never becomes a shareable, and never
  prompts the "share it naturally" SOCIAL_EVENT hint. Her loneliness counts
  on the world clock: `AffectSystem.on_social_interaction` takes `now=` (the
  world instant `LifeService` passes from every call -- one of her people, a
  housemate's company, a user message, a theater conversation) and
  `AffectSystem.tick`'s `now` is when she counts the hours since from (both
  `None`: the host's wall clock, as before), so on a simulated world her
  loneliness no longer grows in host hours. The default setting's
  pinned trace is re-recorded for it: the nurse's friends ease her
  loneliness, which first shows in her mood 62 steps in; with the relief
  switched off the old recording replays step for step.
- **Hunger runs per world hour, only a meal feeds her, and hunger never drains
  her energy while she sleeps (humanness program Task 10; rulings T4-R4,
  T9-R8).** Measured before, at the production cadence: hunger rose 0.004 per
  energy tick -- every five minutes on a live host, a third as often in a
  fifteen-minute simulation -- and drained 0.01 of energy per tick above 0.7,
  asleep or awake, which beat sleep's 0.1-an-hour recovery (a hungry night
  ended at the 0.1 energy floor); and any activity whose name contained an
  eating word fed her ("creating a playlist" did: "cr-eat-ing").
  `SustenanceSystem.tick(now=None, hours=None)` now advances hunger by
  `HUNGER_RISE_PER_HOUR` (0.048: the old 0.004 at the scheduler's 12 energy
  ticks an hour, so a live host sees no change) and nutrition by the same
  per-interval drift on the clock; a bare `tick()` is one energy interval,
  exactly what a call gave before. `LifeService` hands it the world hours
  since its last sustenance tick (a stamp taken at construction and again on
  reload, so downtime is not charged as lived time), and applies the new
  `SustenanceSystem.energy_drain(hours, asleep)` -- `HUNGER_ENERGY_DRAIN_PER_HOUR`
  (0.12) while awake above `HUNGRY_THRESHOLD`, none asleep. Eating is the
  activity's "meal" tag alone (`on_activity(..., meal=True)`); the name
  keywords (`EAT_ACTIVITIES`, `REAL_MEAL`) are no longer read. A meal within
  `MEAL_LENGTH_MINUTES` (60) of the start of the last one is that meal going
  on, so a meal that spans several activity ticks is one relief and one
  count. Task 3's sleep acceptance simulations now run at the production
  cadence, and pass there. Across downtime: `catch_up_from_downtime` charges
  the hunger of the whole gap -- the hours before each backfilled activity
  (then its meal relieves them), and the rest of the gap after the last --
  where it charged one five-minute tick per backfilled hour while each
  backfilled meal relieved a whole meal (after a day away she came back less
  hungry than she left). A gap between two sustenance ticks longer than
  `SUSTENANCE_GAP_HOURS` (1 h: a paused host) is walked an energy interval at
  a time, each interval inside her sleep window counting as asleep for the
  drain (asking her sleep state once, at the gap's end, drained a night's
  worth of waking hunger: eight paused hours over her night floored her
  energy).
- **A planned slot is something she can do, and it governs its whole hour
  (humanness program Task 10).** Measured before: the slots `DailyPlanner`
  anchors a day with -- "waking up", "having breakfast", "having lunch",
  "having dinner", "getting ready for bed", "working", "commuting",
  "attending classes", "studying", "meeting up" -- named no activity, so the
  activity tick fell back to a free choice for them (a planned meal never fed
  her; plans ran as planned on 0-3% of waking ticks), and a slot that did name
  an activity governed only the first activity tick of its hour. The
  contemporary pack now has those ten as activities (the names they had,
  tagged "physical" as the names were -- all but "meeting up"), and ten new
  `ACTIVITY_TAGS` say which slot an activity fills: `wake_up`, `breakfast`,
  `lunch`, `dinner`, `bedtime`, `work`, `commute`, `class`, `study`, `meetup`
  (`aura_life.settings.ANCHOR_TAGS`; `PLAN_ONLY_TAGS` are the ones that are
  never an ordinary choice, `COMMITMENT_TAGS` the ones a whim never drops).
  The planner fills each anchor with her setting's activity for it (the
  first so tagged, in its tag order; a meal slot without its own takes her
  first "meal" activity -- the universal "having a meal" in a pack that has
  none) and plans no slot her setting has no activity for, so every slot is
  something she can do; a free hour is never planned with an anchor. A
  planned slot now governs every activity tick of its hour (the ruling
  carried from Task 8: plan adherence and a whim need the whole hour to act
  in), and forced to rest she keeps a planned slot that is itself rest. In a
  three-day, production-cadence run five personas followed their plan on
  77-87% of waking ticks. Because every tick marks its hour's slot
  completed, the schedule overrides (`cancel_work_today`,
  `stay_at_current_location`, `schedule_rendezvous`,
  `override_current_location`) now rewrite the slot of the hour she is in
  whether or not she has started it, and clear its `completed`
  (`override_current_location` takes an optional `now`, which `LifeService`
  passes, like the others); while a transit is under way the hour's slot
  does not run (nor does an intimate activity); and following her plan at the
  place it puts her, she stays there for the whole hour (she was moved away
  on the slot's second tick and back on its third: 7 times in three
  personas' three-day runs, now 0). The activity the planner fills an anchor
  with is an anchor whatever its tags -- the universal "having a meal" in a
  pack without meal slots of its own -- so it is never dropped on a whim,
  swapped by a revision, moved by the outing guarantee or planned in a free
  hour.
- **What she does is chosen from who she is (humanness program Task 10).**
  Measured before: `ActivityEngine` scored time of day, place, weather and
  variety and read no trait, so an introvert and an extrovert did the same
  things (their activity mixes diverged by no more than two runs of one
  persona did), and her interests were stored and never read. The new
  `aura_life.activities.choice` weighs every candidate by a utility --
  each need's shortfall (hunger, rest, loneliness, a drained social battery,
  stress, curiosity, rumination: `aura_life.settings.NEED_KEYS`, read by
  `LifeService` every activity tick into a `ChoiceState`) times what her
  traits make of it (`PersonaParameters.need_weights`, rows 15-19 of its
  table) times how much the activity meets it (derived from the activity's
  category and tags, and `Activity.needs` -- a new optional field validated
  by `register_setting` -- for each need it states), plus her affinity for it (her interests,
  comfort-zone seeds, tastes, media and substance tendencies, matched to its
  name and narratives; two new tags, "alcohol" and "smoking", are what a
  substance tendency draws her to or keeps her from), her habit, the pull of
  her goals and wants, and her mood's fit, less its effort -- and draws among
  the five best by `context * exp(utility / TEMPERATURE)`, the context being
  the old fit of time, weather, place, variety and values (the old goal and
  low-energy rest multipliers are utility terms now). A substance tag is
  also what her body reacts to (ruling T10-R2):
  `BodySystem.on_substance_activity(name, tags=)` falls back from its drink
  names (`SUBSTANCE_ACTIVITIES`) to `SUBSTANCE_TAG_EFFECTS` -- "alcohol" adds
  0.3 (the value of two of its three "alcohol" entries), "smoking" 0.05 (a
  smoke registers, never inebriates) -- scaled by her tendency for the
  substances of that kind, so a pack's "having a pint" makes a drinker
  tipsy. Every coefficient is in
  one documented block there. `DailyPlanner` fills a free hour the same way
  before any need is known -- what she is into, plus how far her traits lean
  her (zero for neutral traits) -- and reads her interests at last; a hunger
  at `HUNGRY_THRESHOLD` takes a free-time slot of her plan (she eats), never
  an anchor or a commitment. An AI persona never chooses an activity tagged
  "physical" or "meal" (her plan already left them out, but a free choice --
  rest forced on her -- could land on a meal or a shower). `ActivityPreferences` is built once per persona
  from her definition. Her shift's, commute's and meetup's own hours do not
  reach `CareerSystem.on_activity` (its tick already counts the workday;
  they had never reached it before -- and "meeting up" carries its "meeting"
  keyword, which added workload for a rendezvous). In three-day, production-cadence runs an
  introvert and an extrovert diverged by 0.43-0.53 bits against a
  same-persona noise floor of at most 0.16, and two personas with disjoint
  interests had an activity-mix cosine of 0.69-0.71.
- **Her goals are hers (humanness program Task 10).** Measured before: every
  persona's goals and daily intention were drawn from the same small pools,
  so two personas shared their starting goals (both held "Appreciate
  something beautiful"). `GoalEngine(rng, setting, definition=,
  parameters=, persona_id=, interests=)` now starts her with her personal
  goal as her dream (`PersonalityDefinition.personal_goal`), an interest as
  her long-term goal ("Go deeper into poetry"), her core values and
  struggles as her weekly goals ("Stay true to curiosity", "Work on
  self-doubt"), and draws her daily intention from her values and interests
  ("Make room for curiosity today", "Spend some time on poetry"), each
  pursued through the activities that match it (a value also through those
  of the setting's goals that speak of it, a struggle through the
  reflective ones). A kind she has none of comes from the setting's pools,
  ranked by fit -- its words against hers, and how much its activities are
  her kind by her affinity and her traits' lean. Without a definition the
  pools are drawn as before. A goal of hers her setting offers no activity
  to pursue ("Stay true to loyalty" where nothing is about loyalty, "To
  finish my first novel." where nothing is about writing one) is not taken
  up -- a goal only progresses through its activities, and such a goal was
  abandoned within a week -- and that kind comes from her setting's pools. After a goalless spell she picks up one of her
  own first. `LifeService` passes her definition, parameters and interests.
  Two profiles with nothing in common now share none of their starting
  goals.
- **Her wants are hers, and her setting's (humanness program Task 10).**
  Measured before: `DailyPlanner` drew every persona's short-term wants from
  the setting's one list. It now also builds her own from her definition --
  an interest ("Make time for poetry"), a comfort-zone seed ("Get back to
  journaling"), a taste ("Put on some jazz"; a food taste is met by her
  meals), something she reads, watches or listens to ("Get back into
  Dune"), a substance she takes ("Have a drink", never one she avoids) --
  each pursued through the activities of her setting that match it; a seed
  nothing in her setting meets is no want. She draws hers and her setting's
  in turn, hers first; with none of her own the draw is exactly as before.
  `DailyPlanner` takes `definition=` and `media_preferences=` (the host's
  interests and media win, as elsewhere); `LifeService` passes both.
- **Intimacy keeps to her free time, and her intimacy rate scales it
  (humanness program Task 10, spec R6).** Measured before: intimate
  activities took 15-32% of activity ticks for every persona, work shifts
  and her own night included. An intimate activity now never takes a slot of
  her commitments -- a shift, the commute, a class, study
  (`DailyPlanner.is_commitment`) -- nor, for a persona who sleeps, a tick
  inside her sleep window (the new `EnergySystem.in_sleep_window(local_now)`:
  that night's effective window, or the night her sleep drew); an AI
  persona, who rests through her window awake, keeps her nights as they
  were (ruling T10-R3). `DesireSystem(intimacy_rate=)` --
  `PersonalityDefinition.intimacy_rate`, a profile's optional `Intimacy
  Rate:`, which `LifeService` passes -- scales the chance of one on each
  activity tick: 1.0 is today's chance, 0.5 half of it, 0 never; unset
  (`None`) keeps today's exactly. There is no new default rate. A rate that
  is not a number in 0..1 is dropped with a warning (unset), as the profile
  parser drops one -- never clamped.
- **Sleep is a state with a duration, and fatigue runs in hours awake.** Measured
  before, three simulated days of three schedules (23:00-07:00, 03:00-11:00,
  05:00-13:00): personas "slept" about ten times a day at any hour and were
  doing something awake on 83-84% of the ticks inside their own sleep window,
  because `EnergySystem.sleep()` restored energy at once and falling asleep also
  needed effective energy below 0.4; and fatigue rose 0.005 per minute and
  crossed the 0.7 rest threshold about 2h20m after waking, so rest was forced on
  52-54% of waking ticks. `EnergySystem` now runs a two-process model:
  - `state.fatigue` is the sleep pressure (also readable as `sleep_pressure`).
    It rises `1/MAX_HOURS_AWAKE` per hour awake and falls per hour asleep at
    `sleep_pressure_fall_per_hour`, a per-persona rate at which her usual night
    clears what her usual day built. Resting while awake (`restore_energy`) no
    longer lowers it; a nap (`nap`) does, at the sleep rate for its length.
  - Each night's bedtime and wake time are drawn once, from the rng the caller
    passes, around the persona's own schedule: `bedtime_variance` and
    `wake_variance` as a triangular draw within that many minutes either way,
    `weekend_bedtime_shift` and `weekend_wake_shift` on Friday and Saturday
    nights, and `wake_up_chance` as the chance of an early morning (up to one
    more `wake_variance`). Those five fields were parsed and never read. The
    drawn night is `EnergySystem.night`, a new frozen `SleepNight`.
  - The new `EnergySystem.update_sleep(local_now, *, in_conversation, rng)`
    moves the state: she falls asleep inside the night's window once the
    pressure reaches `SLEEP_PRESSURE_TO_FALL_ASLEEP` (0.5) and the user is not
    chatting, stays asleep until the drawn wake time, and is done for that
    night once she wakes. Asleep, the energy tick has no circadian pull:
    energy comes back `SLEEP_ENERGY_RECOVERY_PER_HOUR` (0.1, the rate `sleep()`
    applies in one go) per hour instead. `LifeService`'s activity tick calls it
    with her local time -- the host's `persona_now` for a persona with a
    timezone, the world clock for one without (the same instant on a host
    whose world runs on the wall clock, and the simulated one on a host that
    simulates time) -- and a sleep stream of the service's own: with an
    injected `rng`, a `random.Random` seeded from that rng's state at
    construction plus the label "sleep" (`LifeService._sleep_stream`; reading
    the state takes no draw), so the same seed gives the same nights and no
    other draw on that rng can move her bedtimes; without one, module
    `random` as before. It logs one "sleeping" entry
    when she falls asleep, and does nothing else while she sleeps; the night's
    sleep quality is scored when she falls asleep and a dream, if any, is
    shared when she wakes. A message does not wake her -- `force_wake()` still
    does, as before.
  - A new persona starts on her own schedule at the current time
    (`EnergySystem.start_on_schedule`): inside that night's effective window
    (her bedtime and wake time, the weekend shift on a Friday or Saturday
    night, no variance) she is asleep, with the pressure a sleeper has that far
    into the night; outside it she is awake since that day's effective wake
    time. She used to start "awake eight hours" whatever her schedule, so a
    13:00 riser created at 15:00 had been up since 07:00. `LifeService` does
    this at construction, again in `start()`'s load when no energy was saved
    (once her timezone has loaded), and in `reset_state()`; a persona whose
    energy was saved keeps it.
  - `should_rest()` is true when her energy is nearly gone or she has been up
    longer than her usual day (`usual_awake_hours`), no longer when fatigue
    passes 0.7. `should_sleep()` means "asleep, or everything `update_sleep`
    needs to put her to sleep holds"; its collapse caps are more than 26 hours
    awake, or pressure above 0.92 with effective energy below 0.2 -- the
    `effective_level < 0.08` cap is gone, since an energy crash with little
    pressure behind it is exhaustion and she rests instead of sleeping for
    hours mid-day. A collapse that would wake her inside her window sleeps on
    to its wake time. `EnergySystem.is_asleep()` and `LifeService.is_asleep()`
    report the sleep state instead of "this hour is inside her window", which
    called her asleep through ticks she spent awake.
  - "sleeping" is no longer an activity she can pick, and "napping" only when
    she is tired (effective energy under 0.3, the top of the `TIRED` band),
    outside the night part of her day, and once per waking day
    (`EnergySystem.can_nap`). `ActivityEngine.select_activity` takes a new
    `exclude=` for this.
  - The state persists: `EnergySystem.to_dict()` gains a `sleep_state` key and
    `life_energy_state` a `sleep_state` column (added in place by
    `_init_database`); a row written before it restores her awake.
    `adjust_for_time` (downtime catch-up) now sets the sleep state too -- asleep
    inside her window, otherwise awake since her usual wake time with the
    pressure those hours built -- and `sleep()` stays, booking a whole night that
    ends now. `reset_state()` keeps the persona's own sleep schedule (its
    rebuilt `EnergySystem` used to fall back to the default one).
  - AI personas never sleep, as before, and now run on the same hours-scale
    fatigue and rest rule. With no sleep to clear the pressure, an AI rests
    through its effective window instead: awake and reachable, its pressure
    falling and its energy coming back at the sleep rates, its day starting
    over when the window ends. It picks neither "sleeping" nor "napping".
    `EnergySystem.FATIGUE_ACCUMULATION_RATE`, the old per-minute rate, is
    removed.
  - Measured after (`tests/test_sleep_state.py`, on the new
    `tests/sim_helpers.py`), asleep on each night's effective window, three
    days: weekday nights 94%, 98% and 99%; Thursday to Sunday, Friday and
    Saturday nights included, 95%, 97% and 98%; exactly one sleep episode per
    night; rest forced on 11-16% of waking ticks, and on 15% of an AI
    companion's ticks over two days.
- **One emotion vocabulary, and the feelings wheel no longer calls a name it
  does not list "happy".** The new `aura_life.emotion.vocabulary` maps every
  emotion name the library emits -- activity, intimate, chaos, micro-event,
  goal, life-event, dream and life-chapter emotions, the text analyzer's
  labels, the whole feelings wheel, `EmotionEngine`'s OCEAN baselines -- to a point: valence
  -1..1, arousal 0..1 (`EMOTION_VOCABULARY`, read with `valence_arousal(name)`,
  all three re-exported from `aura_life.emotion`). A name it does not know reads
  as `NEUTRAL_POINT`, (0.0, 0.3), logged at DEBUG. The values are hand
  placements on the scale the module docstring gives, held by tests to order
  and sign; `tests/test_mood_model.py` scans the source for emitted names
  (any argument, key, variable or collection named `emotion(s)`,
  `emotion_effects`, `emotional_impact`, `feeling` or ending in `_emotion(s)`)
  and fails on any the table lacks, except four words it lists as not
  feelings: a life chapter's themes "origin" and "growth", and how her money
  stands, "tight" and "flush". `FeelingsWheel.get_core_emotion` answered
  "happy" for every name the wheel does not list -- 46 of the 69 names the
  library emitted, "discouraged", "drained" and "restless" among them
  (measured in the humanness analysis). It now answers the core family whose
  members' mean point in the vocabulary is nearest the name's ("discouraged"
  and "drained" are sad, "restless" surprised), and a name the vocabulary does
  not know either lands in the family nearest the neutral point ("bad"),
  never "happy" by default. Names the wheel lists keep their family. Anger and
  fear sit close together on these two axes, so a name between them (such as
  "dreading") can land in either. The wheel's lookup and family tables are
  built whole and then assigned, so a first call that fails part-way, or a
  concurrent one, never leaves a half-built table behind.
- **Mood can go down: it is a valence and arousal point pulled back to the
  persona's own set-point.** Measured before, every persona's mood read
  "content" on 100% of ticks at ~0.98 intensity: mood was one axis that only
  ever added, fed by the activities' all-positive emotions, and a negative
  `emotional_baseline` was ignored. `AffectSystem`'s mood is now a point,
  `mood.valence` (-1..1) and `mood.arousal` (0..1) on `MoodState`:
  - Her **set-point** is the mean of her `emotional_baseline` emotions' points
    in the vocabulary, weighted by their intensities, together with the
    neutral point (weight `SETPOINT_NEUTRAL_WEIGHT`, 1.0). Negative entries
    count like any other: a sad or anxious baseline gives a set-point below
    zero, and her mood starts there (`AffectSystem.setpoint`). No baseline is
    the neutral point, (0.0, 0.3).
  - Mood is **pulled back toward a target by the hour**: each axis closes half
    its gap every `MOOD_VALENCE_HALF_LIFE_HOURS` (4) / `MOOD_AROUSAL_HALF_LIFE_HOURS`
    (2) of world time, whatever the tick cadence. `AffectSystem.tick` takes
    `hours=` and `now=`; `LifeService` passes the world-clock hours since its
    last energy tick. A `tick()` given no hours counts as one 5-minute energy
    tick. The target is her set-point, shifted by `WEATHER_MOOD_MAP` and
    `SEASON_MOOD_MAP` (once added to mood every tick, which only ever grew it)
    and pulled by her needs.
  - **Needs pull it down.** Loneliness, chronic stress (her own levels), and
    from `body_state` hunger, `sleep_pressure` and `illness` (the worst of
    illness, injury and pain) each have a floor below which they leave mood
    alone (`NEED_FLOORS`, taken from where the library already says the need
    starts to matter: loneliness and stress 0.2, the floors of their
    descriptions; hunger 0.4, where `hunger_label` stops saying "satisfied";
    sleep pressure `EnergySystem.SLEEP_PRESSURE_TO_FALL_ASLEEP`; illness
    body's `UNWELL_THRESHOLD`). Past it, each lowers the valence target by up to
    `NEED_VALENCE_PULL` (0.4) at its full shortfall; sleep pressure also lowers
    the arousal target and stress raises it (`NEED_AROUSAL_PULLS`, 0.3 each),
    and loneliness lowers it by as much as "lonely" sits below neutral arousal
    in the vocabulary (0.1), so a lonely mood reads low.
  - Each **emotion event** moves mood `EMOTION_MOOD_GAIN` (0.08) of the way
    toward that emotion's point per unit of intensity, so a stream of pleasant
    emotions can bring her near "content" but never carry her past it, and
    every name counts, "discouraged" and "drained" included. The gain is set
    from a measurement: at production cadence (each tick at `LifeScheduler`'s
    own interval) a waking hour of the three-day simulation brings 2.03 of
    emotion intensity (1.97-2.13 over four seeds and three personas), so the
    hour's emotions pull about as hard as the hour's pull back to the target
    (0.159 / 2.03 = 0.078). The legacy test cadence, every tick every 15
    minutes, brings 2.50, which would have given 0.064. Conversation, location and weather nudges
    move valence part of the way toward the end they point at. The emotions
    that drain regulation are the five `HIGH_AROUSAL_EMOTIONS` always listed
    (excited, anxious, angry, startled, restless), unchanged. Empathic
    fatigue keeps the eight names the old `NEGATIVE_EMOTIONS` listed, now
    `EMPATHIC_FATIGUE_EMOTIONS` (sad, anxious, frustrated, angry, lonely, hurt,
    overwhelmed, raw); the vocabulary does not widen it to every unpleasant
    name.
  - **Asleep, her mood quiets:** the arousal target is sleep's own level (the
    vocabulary's "sleepy", `ASLEEP_AROUSAL`), so her mood reads calm, flat or
    low through the night and groggy for a while after she wakes
    (`body_state["asleep"]`).
  - The **label** `mood.current_mood` is read off the pair: content, happy,
    calm, restless, irritable, anxious, low, flat or neutral (`MOOD_LABELS`,
    `mood_label`), from valence bands at +/-0.15 and arousal bands at 0.25 and
    0.55 -- except that an unpleasant mood reads low up to and including the
    neutral arousal (0.3, `MOOD_UNPLEASANT_QUIET_UP_TO`): a sad, grieving or
    lonely baseline rests near neutral arousal, and irritable needs arousal
    raised above rest. `mood.intensity` is how far the pair sits from neutral
    (`mood_intensity`). "blue" and "raw" are retired; `get_mood_description`,
    `get_irritability_level`, the planner's low-mood swap, time perception,
    tendency easing and the monthly chapter titles read the new labels.
  - `export_state()["mood"]` keeps `current` and `intensity` and adds
    `valence` and `arousal`; `get_status()` adds `mood_valence` and
    `mood_arousal`; `to_dict()` adds both, and `life_affect_state` gains the
    two columns (added in place by `_init_database`). A row saved before them
    starts her at her set-point.
  - The Shadow tick and `mental_health_index()` read the valence itself:
    `LifeService._mood_to_valence` takes `valence=`, and keeps its label-only
    mapping for a caller that passes none.
  - `POSITIVE_EMOTIONS` and `NEGATIVE_EMOTIONS` are removed from
    `aura_life.affect.affect_system`: the vocabulary replaces them.
  - Every constant is in the "Mood model" block of `affect_system.py`, with
    where it comes from -- the mood inputs the events bring included
    (`GOAL_COMPLETION_EMOTIONS`, `WORK_EVENT_EMOTIONS`,
    `ANTICIPATION_MOOD_PER_HOUR`); the half-lives, the set-point's neutral
    weight, the need pulls and the label bands are chosen values, not
    measurements.
  - Measured after (`tests/test_mood_model.py`, three simulated days at
    production cadence, seed 3), waking ticks: the no-profile control read low
    on 56%, neutral 37%, flat 5%, irritable 2%, content 1%; Lina's baseline
    neutral 42%, low 30%, irritable 19%, flat 5%, content 4%; Roberta's
    neutral 81%, content 14%, flat 4%, calm 1%. Over seeds 1-8 each persona
    showed three to six labels awake; the largest single label was 81% of a
    persona's waking ticks (Roberta, neutral) and 63% of all her ticks. At
    this cadence hunger is at or above 0.7 on about half the ticks (it rises
    by the energy tick, which runs every 5 minutes), which is most of the
    control's low mood.
- **Everything that should move mood now reaches it, and `LifeService`
  decays a host's `EmotionEngine` itself.**
  - The energy tick hands affect her sleep pressure (`EnergySystem.sleep_pressure`),
    `illness` (the worst of the body's illness, injury and pain) and whether
    she is `asleep` -- as `LifeService.is_asleep()` answers it, so the wake
    button wakes her mood too -- beside hunger; an AI persona, with no body,
    hands 0 for both needs and is never asleep.
  - Nature (a park or a beach) lifts her mood when she arrives there, once. It
    lifted it on every activity tick she spent there, so how high it carried
    her depended on how often the host ticked.
  - The proactive moment-share's "mood clearly lifted" signal needs a
    pleasant mood as well as a strong one: mood intensity is now distance
    from neutral in any direction, so on its own it fired at her lowest.
  - An **anticipation** is felt per world hour: `ANTICIPATION_MOOD_PER_HOUR`
    (0.1) times its intensity for each hour it lasts. It was 0.1 times its
    intensity on every energy tick, so the faster a host ticked the more she
    felt it -- about 450 "excited" events a day in the simulation, the
    largest single feed into mood; at the 5-minute tick it is twelve times
    weaker per hour than before.
  - Activities, intimate activities, micro-events, chaos events, goal events
    (a motivation drop, a goal given up, nothing left to pursue), completed
    goals and work events all go one way (`LifeService._feel`): to a host's
    `EmotionEngine` when one was injected, and to mood. Chaos emotions used to
    reach mood only when a host engine was injected; micro-event and intimate
    emotions and goal events reached the engine only; a completed goal and a
    work event reached neither.
  - A completed goal feels `GOAL_COMPLETION_EMOTIONS` (the emotions its life
    event already recorded). Each work event has its emotions in
    `affect.affect_system.WORK_EVENT_EMOTIONS` (keyed by
    `job.career_system`'s event texts), the chaos engine's own where it has
    the same event, and `CareerSystem.tick()` returns the event it rolled (at
    most one per workday) instead of `None`.
  - `LifeService.decays_emotion_engine` is `True`: the energy tick decays the
    injected engine by the world-clock seconds since its last decay, through
    `EmotionEngine`'s new private `_decay(seconds)`. `decay_tick()` is
    unchanged -- it now hands its own wall-clock seconds to `_decay` -- and a
    host engine without `_decay` is decayed through its own `decay_tick()`. A
    host that sees the attribute `True` must stop decaying the engine itself,
    or it decays twice.
- **`LifeScheduler.TICK_INTERVAL_MINUTES` and `LifeScheduler.TICK_ORDER` name
  the intervals and the order the scheduler already used** (world and energy
  every 5 minutes, plan 30, activity 20, goal 60; `force_all_ticks` runs world,
  energy, plan, activity, goal). The values are unchanged; the tests'
  simulation harness reads them to run a service at production cadence.
- **Life events are recorded once, not twice, and shares finally get marked.**
  Measured before, three simulated days: each persona logged about 380 life
  events, 72-76% of them a template slotted with a bare engine label or mood
  word as its noun ("Felt genuinely proud of content", "Couldn't stop
  thinking about reading"), because `LifeEventSystem.record_event` re-ran
  every title through a second, automatic template lookup keyed by
  `event_type` -- whatever the caller had already composed, or a bare mood
  label (from `on_emotion_event`) or activity name (from `on_activity`), as
  its noun -- and a mood-intensity life event was recorded on every energy
  tick. And nothing ever called `mark_shared`: the "eager to share" queue
  only ever grew.
  - `record_event`'s `title` is now used verbatim; a caller that wants a
    template applies one itself, once. `on_activity` does, drawing from
    `LIFE_EVENT_TEMPLATES["discovery"]` (safe with a bare activity name as
    `{context}`) or the new `_ACTIVITY_LINGERING_TITLES` (never the raw
    activity name slotted into an "emotional" phrase) -- one
    `self._rng.choice` either way, the same draw count `on_activity` made
    before, since `LifeService` shares one `random.Random` across many
    engines and a changed draw count anywhere shifts every later stochastic
    decision downstream of it.
  - `on_emotion_event` (fired from every energy tick whenever mood intensity
    crossed 0.5) is replaced by `LifeEventSystem.on_mood_change(mood_label,
    intensity, now)`: it records only when the mood label differs from the
    label at her last mood life event, and at most once per
    `MOOD_EVENT_MIN_HOURS` (6.0) simulated hours.
  - Every unshared `LifeEvent` / `ShareableExperience` carries a stable
    `share_id` (`"event:<n>"`, `"share:<n>"` -- spec Sec 4.9), a new field
    alongside the existing shape (`id`, `title`/`description`, `content`,
    etc. are unchanged). `LifeService.mark_shared(share_id) -> bool` marks
    either kind, persists the change, and returns `False` for an unknown or
    malformed id, never raising.
  - `life_events` gains a `share_id` column, migrated in place by
    `_init_database`. `ShareableExperience.share_id` is derived from its
    existing `id` (the row's pk) rather than stored on its own, since that id
    is already assigned synchronously at creation; `LifeEvent.share_id` is
    assigned by `LifeEventSystem` itself (scanned from its own in-memory
    events), since a `LifeEvent`'s `id` is only assigned on the next batched
    save.
- **Every engine that draws randomness draws from a stream of its own, not
  one shared `random.Random` and not the global module.** Ruling T4-R1
  (above) already gave the nightly sleep draws their own stream so other
  draws could not move her bedtimes; the `on_activity` fix above hit the
  general form of the same problem it could not fix there -- `LifeService`
  shares one `random.Random` across many engines, so a changed draw count
  anywhere shifts every later stochastic decision downstream of it -- and
  ruling T5-R1 generalises `_sleep_stream` into
  `LifeService._derive_stream(rng, label)` for every engine that used to
  share `self._rng` directly (desire, habitation, finance, career, errands,
  identity, cognitive, drive, memory-time, life-events) and the service's own
  direct draws (`self._service_rng`, label `"service"`). Ruling T26-R2 (a
  fix-round finding: T4-R1 only ever decided which draws sit on the *sleep*
  stream, never which engines this generalisation would cover) went further:
  activity selection, chaos, the daily planner's bare draws (its per-day,
  per-role `crc32`-seeded draws are untouched -- they already derive their
  own seed from the date and role), the body's sleep/daily-health rolls,
  social, behaviour, goals, transport, and `aura_life.schedule.ScheduledEvent`
  each gain an `rng=None` constructor parameter defaulting to a fresh,
  unseeded `random.Random()` (never the module), so a bare, standalone
  construction still works and shares no draw sequence with any other
  instance or the module; `LifeService` derives each its own stream the same
  way as the first ten. Every derived stream is computed once, at
  construction, from a *read* of the injected rng's state (never a draw), so
  it makes no difference which engine's stream is derived first or how many
  draws any engine -- or the service itself -- takes afterward: **a
  draw-count change in one engine never moves another engine's draws**, not
  even by drawing from the raw injected rng directly after construction, and
  even the service's own draws are no exception to that any more.
  `WorldEnvironment` is excluded on principle, not merely by omission: a
  world can be shared by every persona in a household, so it now owns its
  own `rng`/`seed` constructor argument (default: the same fresh,
  unseeded `random.Random()`) rather than ever taking one from a single
  persona's stream -- a caller that wants two worlds (or two runs) to agree
  on weather passes the same `seed` to each. `rng=None` on `LifeService`
  (the default) still leaves every draw on module `random`, byte-identical,
  the weather of the private world it builds for itself included (a world
  handed in keeps its own `rng`/`seed`).
  `sanity_rng` is unchanged (its own opt-in isolation from `rng`, defaulting
  to share it when not given separately, predates this and is untouched).
  Persona generation (`personas/genre_randomizer.py`,
  `personas/place_generation.py`) already takes its own rng through a
  separate, one-shot path and stays out of scope, as does
  `location/place_service.py` (already its own `rng or random.Random()`,
  never the module).
  `tests/test_rng_streams.py` (9 cases) proves it: an engine that takes N
  extra draws never moves any other engine's first 20 draws (the acceptance
  scenario, and every engine in turn as the one perturbed, eighteen labels
  plus sleep and service); the sleep-stream regression test
  (`test_sleep_state.py`) generalised to every stream, including drawing from
  the raw injected rng itself; `rng=None` still module `random` for every
  stream; every stream matches `_derive_stream` for its label with no
  collisions; the same seed replays the same 3-simulated-day
  production-cadence trace across two runs; and a lint that fails if any
  module under `src/aura_life/` (besides the two persona-generation
  exceptions) calls a global `random` drawing function -- `random.Random(...)`
  construction is fine, a call on it is not.
- **Traits set the engines' numbers, through one table (humanness program
  Task 8).** Measured before: free-text traits reached the simulation only
  through nine separate substring keyword tables with no negation --
  "insensitive" and "unemotional" read as *more* emotional, "antisocial loner"
  as *more* social, "uncaring" gave empathy 0.7, "quietly brave" lowered
  energy and social need -- only 25% of the persona generator's 239 trait
  strings moved any number, and none of the numbers reached the plan or the
  event rates. The new `aura_life.personas.parameters` (spec section 4.3)
  compiles a persona once: `PersonaParameters.from_definition(definition)`
  holds the eight `TRAIT_KEYS` traits -- the definition's explicit `traits`
  win; a missing one is inferred from `core_traits`; no evidence is 0.5 --
  and the engine parameters derived from them through the one table in its
  docstring. `LifeService` builds it at construction and every engine that
  reads a trait takes it (a new `params=` keyword on `AffectSystem`,
  `EnergySystem`, `IdentitySystem`, `CognitiveSystem`, `DriveSystem`,
  `DesireSystem`, `ShadowSystem`, `FinanceSystem`, `BodySystem`,
  `SocialSystem`, `ChaosEngine`, `DailyPlanner` and their `from_dict`s;
  `core_traits=` still works and is read by the same module). `PersonaParameters`
  is also re-exported from `aura_life.personas`.
  - One matcher reads every trait word in the library (`match_keywords`):
    whole words only (so "quietly" is not "quiet"); a word counts as its
    opposite when `not` / `never` / `no` / an `n't` word is one of the two
    words before it in the same clause, or when it carries a negating prefix
    (`un`, `in`, `non`, `anti`: "uncaring", "insensitive", "anti-social") --
    a word that is itself a keyword is never split that way ("intense");
    longest keyword first ("open-minded" is not "open"; "kind of" is a
    hedge). An inferred trait is `0.5 + 0.4 (high - low) / (high + low + 1)`:
    one word moves it 0.2, the step of the retired social-need and empathy
    tables. After: 43% of the generator's trait strings move a number, 38%
    one of the eight traits; the 15 strings that stop moving one were
    substring accidents ("quietly ...", "carefully hopeful", "warmly
    scheming").
  - Wired: volatility sets affect reactivity (the affect multiplier and a
    scale on `EMOTION_MOOD_GAIN`), the mood half-lives and the regulation
    baseline; warmth the set-point's valence (+/-0.1 at 0.9 / 0.1) and
    empathic contagion; sociability desired contact (loneliness growth), the
    social battery (`SocialSystem`'s `introversion`, which `LifeService`
    never passed) and the chance an NPC gets in touch; rumination how often
    a rumination loop replays and how slowly it fades; conscientiousness how
    tired or low she must be before `DailyPlanner.revise_upcoming` drops
    upcoming slots; impulsivity the chance she drops a planned free-time slot
    on a whim (new `DailyPlanner.abandons_slot`: never work, meals, other
    routine anchors, important commitments or a plan agreed with the user;
    0 at and below neutral); openness the chaos and micro-event chances;
    weather_sensitivity the weather's pull on mood. Event rates change a
    probability threshold, never the number of draws.
  - At every trait 0.5 each parameter is today's constant, and a persona with
    no traits and no trait text is byte-identical to before: two seeded
    two-day production-cadence simulations of three such personas produce
    the same trace, every activity narrative included, before and after.
  - The retired tables' words keep their weights where they read no single
    trait: `ENERGY_GROWTH_TRAITS`, `COGNITIVE_GROWTH_TRAITS`,
    `DRIVE_GROWTH_TRAITS`, `IDENTITY_GROWTH_TRAITS`, `DESIRE_GROWTH_TRAITS`,
    the shadow seeding sets (now `SHADOW_TRAIT_SETS`), the spending-habit
    words (`FRUGAL_TRAITS`, `SPENDER_TRAITS`) and
    `BODY_IMAGE_STRUGGLE_MARKERS` moved to `aura_life.personas.parameters`
    and read through the same matcher, so "not curious" now lowers what
    "curious" raises and "no body image issues" is not a struggle.
    `AFFECT_GROWTH_TRAITS` and `AffectSystem`'s `_calc_social_need`,
    `_calc_regulation_baseline`, `_calc_empathy` and `_calc_affect_multiplier`
    are gone: their words are the sociability, volatility and warmth
    vocabularies, their numbers the table's rows (one keyword gives the
    number it gave before; "analytical" and "logical" no longer lower
    empathy).
  - A reload built from parameters takes desired contact, the regulation
    baseline, empathy and the social battery's capacity from the traits,
    not from the saved row: they are who she is, not state, so a persona
    whose traits changed (or whose row came from the substring tables) gets
    the new numbers. Mood, regulation capacity and the battery's charge
    (capped at the capacity) still come back from the row.

### Fixed

- **A nostalgia memory in the exported state is addressed to her (humanness
  Task 43).** `export_inner_state()["memory_time"]["recent_nostalgia"]` gave
  the memory as her setting writes it, slot included ("a book {subj} read in
  one sitting on a rainy day"), and a host that prints the export sent the
  token to the model. Found when a host's parity reference was re-recorded on
  this branch. The export now renders it ("a book you read ..."); the engine
  keeps its template. Tests: `tests/test_export_slots.py`.

- **A caller written for 0.5.0 still builds a `LifeEvent` and marks it
  (humanness Task 42).** Found by the whole-branch review. `share_id` had
  been added as the second field of `LifeEvent` and `ShareableExperience`,
  so a caller that builds one by position put its event type in the id, its
  title in the type and its description in the title; it is now the last
  field of both, and the order 0.5.0 had stands. And 0.5.0's
  `LifeEventSystem.mark_shared(event_id: int)` compared a number with the
  stable string ids, marked nothing and said nothing: an `int` is again the
  event's row id (a `str` is the stable id, as `LifeService.mark_shared`
  passes it). Tests: `tests/test_sharing.py`
  `::test_a_life_event_built_by_position_fills_the_fields_it_filled_in_0_5_0`,
  `::test_mark_shared_by_the_row_id_still_marks_as_in_0_5_0` (both red
  before).
- **A long downtime does not bring her back starving, nor as tired as the
  evening the host went down (humanness Task 41).** Found by the branch's
  whole-branch review. The catch-up charges her hunger for every hour of the
  gap (Tasks 34b, 34c) but executed the first `max_activities` slots of its
  window in time order (12 for a gap over a day), and planned two calendar
  days where 48 hours from an evening touch three: after 72 hours away it
  backfilled one morning to evening, two or three meals, and charged the
  other day and a half with no meal. Measured, down Monday 22:00 and back
  Thursday 22:00: hunger 1.000 and a mood valence of -1.000 after the
  catch-up, 0.144 and +0.264 for the host that stayed on; a day to recover.
  Now every meal she planned in the gap is eaten (a slot in her sleep hours
  stays sleep), the rest of the budget is spread over the whole window, and
  every day the window touches is planned; a gap under a day keeps its meals
  the same way. And the catch-up's affect ticks read her sleep pressure and
  her hours awake from what her schedule gives at each span's start (the new
  query `EnergySystem.pressure_on_schedule`, which `start_on_schedule` now
  uses too), not from the energy state the reload left: that state is the
  evening the host went down (0.83 and fifteen hours awake in that run) and
  was handed to her mood for all three days. After, the same run: hunger
  0.144, valence -0.866, then -0.31 twelve hours on and -0.08 a day on.
  What is left of the difference is in DEFERRED.md. Tests:
  `tests/test_catch_up_long_gap.py` (23 cases at four host hours; the three
  behaviours red before, hunger 1.0 at each hour; 2 breaks red).
- **The same event is looked forward to once (humanness Task 40).** The
  goal tick adds a goal due within two days to what she looks forward to at
  every tick, and `MemoryTimeSystem.add_anticipation` appended each: the
  same goal twice or more in every capture of every persona, and five of
  them filled her five places and pushed out an event the user had told her
  of. An event she already looks forward to is kept current in its place
  (its newest feeling, intensity and date). Her mood no longer counts one
  goal five times: on the humanness test's seeds the no-profile control
  reads "flat" where it read "content" on two seeds, and "low" on 76.0% of
  her waking ticks on the third (68.9% before; see that test's entry under
  Added). Test:
  `tests/test_memory_time.py::TestAnticipation::test_the_same_event_is_looked_forward_to_once`
  (red before: five times the goal, the recital gone; 2 breaks red).
- **A greeting is not a feeling (humanness Task 39).** "good night" held the
  word "good" (content, 0.4), so every evening's goodbye read as the user
  feeling good: an appraisal of +0.6, her warmth, and a memory "They told
  you something good" (seen twice in two days of a measured conversation).
  `TextEmotionAnalyzer.analyze_text` reads the set greetings first
  (`GREETING_PHRASES`: good night, good morning, good evening, good
  afternoon, good day, bonne nuit, bonne journée, bonne soirée) and weighs
  none of their words; "good" outside a greeting reads as before. A host
  that calls the analyzer itself gets the same reading. Tests:
  `tests/test_user_turns.py::test_a_greeting_is_not_a_feeling`,
  `::test_good_outside_a_greeting_still_reads`,
  `::test_a_goodbye_leaves_no_memory_of_good_news` (five red before, 2
  breaks red).
- **Across the turns of one conversation a thought comes to her mind once
  (humanness Task 38).** A host asks for her moment at every turn, minutes
  apart, and novelty alone only reorders what is left. Measured on a
  conversation of eight turns five minutes apart, then six a day later (the
  host's order: `observe_user_turn`, then `get_moment`): the same memory
  line in five of eight turns, five to seven lines repeated per
  conversation, the line on the user's return ("notice how long it was and
  say so once") in six of six turns, what she had just been offered to
  share "on your mind" at the next turn, and an item told in the same words
  as the one before offered again. Now, within one conversation -- moments
  less than `CONVERSATION_ACTIVITY_WINDOW_MINUTES` apart, the library's own
  notion, kept in memory only -- what the moment rendered is passed over,
  by its key and by what it is about (`Cue.about`: the line without its
  lead, a memory's what, where and with whom; two memories told in the same
  words, or one topic through a rumination and its stressor, are one
  thought), unless the user's own words name it (a stemmed word that says
  something, weighed on what the cue is about and never on its lead,
  whatever an `embed` hook answers), so her mind can be empty; her memory
  is asked for `MEMORY_CUES` beyond the memories already said, so its next
  thoughts come once the first were said; she is told once in a
  conversation how to meet the user's return; the memory she is offered to
  share is not also on her mind at the next turn. `mark_shared(id)` also
  marks an item her memory tells in the very same words (two evenings of
  the same activity are one piece of news), and news made later in words
  she already told is not offered. Relevance to the user's words is weighed
  on what a cue is about. After: no line repeated in a conversation, the
  return line in one turn, two thoughts a turn tapering to one late in an
  eight-turn conversation (seeds 5 and 9, two personas). Across
  conversations novelty ranks as before, and the section-6 row is unchanged
  (0.100 for each test persona: captures six hours apart are separate
  conversations). For a host: `get_moment` now also keeps, in memory, what
  this conversation has had; a restart starts a new conversation. Tests:
  `tests/test_moment.py` (eleven new, eight red before their fixes; 17
  breaks red). After its review, three more: her memory is walked until
  `MEMORY_CUES` of it are fresh for this conversation or it is exhausted
  (asked for three beyond the memories said, the places went to memories
  about what was already said: her mind empty in five of forty turns of a
  measured conversation, forty things never said; after, two thoughts at
  each of forty turns), and the ones already said that the user names stay
  candidates beside the fresh ones; a moment built while the user is away
  no longer uses up the line on the return; only an item marked shared
  holds back later news in the same words (an item that left her queue
  untold did: three of ten offerable items were never offered).
- **A persona from before the hours-scale money gets her runway once
  (humanness Task 37, ruling T37-R1).** Found by opening, with this branch,
  the databases 0.5.0, 0.4.0 and 0.3.1 wrote after three simulated days:
  balances of 17, 444 and 54 against a new persona's 2,775 (those engines
  drew her purchases per tick and emptied every balance within three days
  at the app's cadence, from a default, 1,200 against 1,850 of expenses,
  that was already worried from her first tick), financial stress 0.67 to
  0.80 where `LifeService` holds "money worries" from 0.4, and two to four
  months of income before she is clear of them: the fix of the constant
  money worries reached new personas only. The first time this version
  opens a database a released version wrote -- the migration that adds
  `life_financial_state.spend_hour` succeeds exactly once, on such a
  database -- her balance is raised to the runway a new persona starts with
  (`STARTING_RUNWAY` x her own monthly expenses) when it is lower. More
  than that she keeps; what she spends afterwards is hers; a database this
  version created is never raised; `FinanceSystem.from_dict` stays value
  for value. The same three databases open without an error (38 tables
  become 46, none emptied); her loneliness and hunger, which those engines
  left at their top, come down by themselves (the user's first words;
  meals), her shadow within about a day, and her memory stream starts empty
  and fills within a day. Tests: `tests/test_finance_hours.py` section (f)
  (six on a table as 0.5.0 created it; four red before, 4 breaks red). The
  column and the raise land in one transaction (an open cut short between
  them had kept the column and lost the raise for good;
  `::test_her_runway_and_its_column_land_together`).
- **What the catch-up backfills is stamped when it happened (humanness Task
  19a, ruling T19a-R1).** An activity the catch-up backfills stamped her
  last workout and her goal's last progress on the host's clock, and a
  backfilled drink at the world's present instant, while the reads that age
  those stamps moved to the world's clock in Task 19a: on a host whose world
  clock is not its wall clock the pair disagreed, and a drink of five hours
  ago counted as one just had. `_tick_engines_for_catchup` now hands
  `BodySystem.on_activity`, `LifeService._give_substance` (a new optional
  `now`) and `GoalEngine.update_progress_from_activity` the backfilled
  activity's own instant, as it already handed it to her money, work, meals
  and errands. Test:
  `tests/test_world_clock.py::test_a_catch_up_hands_her_body_and_her_goals_the_instant_of_what_it_backfills`
  (3 cases; the two first red before, 4 breaks red).
- **Her shadow has a rest, and she comes back to it (humanness Task 36,
  rulings T18-R9, T18-R10).** With nothing driving it -- no stress, no
  loneliness, a neutral or even a perfect mood, no conflict -- a fresh
  `ShadowSystem`'s felt safety fell from 0.7 to 0.0 within 24 ticks and
  never came back, in 0.5.0 too. Her unease then sat at 0.45 to 0.55, so
  every persona read as unsafe and uneasy for good (`export_state()` gave
  `felt_unsafe` and `unease` at every tick from the second hour on, `doubt`
  and `masking` too in a neutral mood), `mental_health_index()` carried that
  unease, and the moment said "Something has you on edge" and "You're
  putting on a front." in every capture of every persona. Cause: the engine
  measured from the wrong zero. The unease target counted felt safety's
  whole distance from 1 and mood's from its best, so at rest it sat 0.19
  above `UNEASE_REST`; and felt safety was worn down by 0.15 of ALL her
  unease, which at the resting floor alone (0.0225 a tick) outran the most
  the recovery can give back (0.021 a tick). Both are measured from rest
  now: the target counts the felt safety she is short of `SAFETY_REST` and a
  mood below neutral (`NEUTRAL_MOOD`), each 0 at rest and 1 at its worst
  under the weights they had, and felt safety is worn down by her unease
  above `UNEASE_REST` at `SAFETY_EROSION`, a rate derived from the two rests
  (`SAFETY_RECOVERY * SAFETY_REST / (1 - UNEASE_REST)`): unease held at its
  maximum takes all her felt safety, anything less leaves her some, and the
  loop between the two returns 0.35 of a change, so she comes back when the
  pressure ends. A state the old engine saved (felt safety 0, unease 0.55)
  is back at rest within fifty hours of five-minute ticks. A conflict still
  shakes her at once (0.25 a tick, unchanged). Her shame's relief is
  measured from rest too (the task's review): it counted all her felt
  safety, so once felt safety rested at 0.7 her shame rested 0.245 under
  its baseline, at zero for a persona with no shame seed; it counts felt
  safety above `SAFETY_REST` now, and with nothing driving it her shame is
  her seeded, chronic level (`SHAME_BASELINE` 0.15 at least). Nothing in
  the engine lifts felt safety above its rest today and `LifeService` hands
  the tick neither `intimacy` nor `conflict`, so that relief waits for a
  caller. For a host, measured on a three-day run at the production cadence
  (seed 18, a no-profile persona and an authored anxious one, nobody
  speaking to them; before -> after, share of ticks): `masking` exported
  0.98 / 0.98 -> 0 / 0; `power_stance` exported 0.85 / 0.69 -> 0 / 0;
  `deferential` 0.98 / 0.99 -> 0.71 / 0.22; `felt_unsafe` 1.00 / 1.00 ->
  0.80 / 0.57 and `unease` 0.99 / 1.00 -> 0.87 / 0.68 (the first persona is
  at full loneliness from the second day on, which is what raises them
  now); the gate of the "pull to be noticed" photo hint (attention-seeking
  at 0.55 or more) open 0.66 / 0.16 -> 0.48 / 0; mean
  `mental_health_index()` score 0.569 / 0.664 -> 0.597 / 0.697; mean shame
  0.176 / 0.170 -> 0.142 / 0.143; the triggers created are the same, type
  for type. With nothing wrong, `export_state()` gives none of
  `felt_unsafe`, `unease`, `doubt`, `masking`, and an independent persona
  reads `self_assured` (her autonomy is no longer dragged under by a felt
  safety of zero). Her attention-seeking and her autonomy still rest near,
  not at, their seeded baselines (their terms measure mood from its best
  and felt safety from 1): not changed here. The per-tick rates of this
  engine are unchanged (they are still per tick, not per hour).
  The moment says her shadow's unease ("Something has you on edge") only
  when none of what raises it -- her loneliness, her stress, a mood under
  neutral -- is itself among the states it weighs: beside "You're lonely"
  it was one cause told as two states, in ten or more of twelve captures of
  a persona nobody spoke to, and under the neutral table the pair
  contradicted itself ("lean into the talk", "get to the point"); a real
  stress of 0.6 was told as "on edge" instead of "You're stressed". It is
  still said when the causes are each too small to be said and add up, when
  it outlives its cause, and in a good mood; her self-doubt, which follows
  her mood, is no longer said as edge. Tests: `tests/test_shadow_rest.py`
  (17: at rest, back to rest, a saved state, by degrees, the closed form of
  where a held pressure settles her, no undershoot, her shame at her own
  baseline; 11 red before their fixes, 15 breaks red, four of them the
  reviewer's), `tests/test_moment.py` (six cases on what is said as edge; 4
  red before, 6 breaks red). The moment's section-6 row is now tested as
  its source measured it
  (`tests/test_moment.py::test_fewer_than_a_fifth_of_the_rendered_lines_are_static`:
  of all the lines that describe her in twelve captures, the speech line
  left out, the share whose line is in six or more): 0.100 for each of the
  three test personas (0.194, 0.250 and 0.181 with the speech line
  counted); it was 0.30 to 0.39 with the speech line counted and the
  shadow's two lines in every capture.
- **The moment (Task 18) fix round 1.** `get_moment` no longer moves her:
  it read her place through `get_current_location`, whose sync moved her to
  her plan slot's place (ruling T18-R2); it now reads
  `LifeService._location_now`, the same answer without the move. A cue made
  of text written about her in the third person (a profile's struggle in a
  goal or a rumination: "guilt over the friend she let down") is passed over
  for the source's next item said to her, so her moment stays in the second
  person. `mark_shared(id)` of an item one episode tells together with
  another (a shareable and its life event) marks both, with one disclosure:
  the moment offers one id of the pair, and the other stayed unshared in
  `get_life_context()`. Tests: `tests/test_moment.py::test_get_moment_consumes_no_latch_and_marks_nothing`
  (both exports and the unshared ids compared),
  `::test_a_cue_in_the_third_person_is_passed_over_for_one_addressed_to_her`,
  `::test_marking_one_id_of_an_item_marks_the_ids_told_with_it`.
- **One goal completion gives one trigger (ruling T17-R6).** A completion
  made both an EXCITEMENT_SHARE (its life event, through the excitement
  wait) and a GOAL_MILESTONE (its episode), and a host dedups only on type
  and topic, so she could tell the same news twice. The completion's life
  event no longer waits for an EXCITEMENT_SHARE
  (`_bridge_life_event(event, excitement_share=False)` in `_on_goal_tick`);
  its GOAL_MILESTONE tells it. Any other life event at the same urgency is
  still an EXCITEMENT_SHARE. Tests:
  `tests/test_proactive_hints.py::test_one_goal_completion_gives_one_trigger`,
  `::test_another_life_event_of_a_completion_s_urgency_is_still_an_excitement_share`.
- **Her context's work line renders its slot (ruling T18-R7).** The career
  section read the career engine's raw text, which keeps the setting's
  tokens for the mood lookup, so "earlier you got praised by {poss} boss"
  reached her context unrendered; it is now said to her ("earlier you got
  praised by your boss"), as `_render_career_status` already did for the
  status. Test: `tests/test_moment.py::test_her_context_renders_the_work_line_s_slot`.
- **A dream's activity is phrased (ruling T18-R8).** The dream template that
  puts an ingredient after "were" read "Dreamed you were yoga"; an activity
  named by a thing is now led by `_doing`'s rule in the template
  (`_doing_lead`, `_phrase_after_was`, after every draw, so the draws are the
  same): "Dreamed you were in the middle of your yoga ...", in the episode
  and, with her pronouns, in the shareable. Tests:
  `tests/test_proactive_hints.py::test_a_dream_of_a_noun_named_activity_is_phrased`,
  `::test_every_activity_name_her_settings_know_is_phrased_in_a_dream`.
- **`rng=None` keeps her private world's weather on module `random` again
  (ruling T35-R1).** A `LifeService` built without an rng and without a
  world handed in gave its private `WorldEnvironment` no rng, so the world
  took a fresh, unseeded `random.Random()`: the one draw of her life off
  the module, although every released version's world drew from it. A host
  that seeds the module got two different lives from one seed (aura's
  parity test: 195 of about 460 exported leaves differed). The private world
  now takes `_derive_stream(rng, "world")`, which is module `random` when
  `rng` is `None`; a world the host builds itself keeps its own stream.
  Test: `tests/test_rng_streams.py::test_a_service_without_an_rng_keeps_its_private_world_on_the_module_random`.
- **Her habits are learned and read on her local world hour (Task 31).**
  After the merge her own pick took its part of the day's habits, and her
  lived tick dated its hour, by `persona_local_hour()`: the host's clock for
  a persona without a timezone, while her plan runs on her local world hour
  (Task 28's `_plan_instant`). With the host at 22:45 and the world at 09:00
  a morning's pick read her night's habits and was logged at hour 22. Both
  read `LifeService._local_world_now().hour` now.
- **A social plan lands on her own day and hour (Task 31).** 0.4.0 dated the
  plan its slots go into on the host's day, so with the host's evening and
  the world's morning apart a plan for the world's 21:00 landed nowhere; on
  the branch every plan is made on her local world time. And `at`
  (`add_social_plan`) is a naive instant on the world clock: a persona whose
  time runs seven hours ahead of the world's got a plan at the world's 15:00
  on her hour 15, already past for her, and one at the world's 21:00 on her
  21:00 that day rather than her 04:00 the next; each plan's instant is now
  read as her local world time (`LifeService._local_world_instant`, the
  shift `_local_world_now` has from the world's now, in whole minutes; none
  without a timezone), and "already passed" is judged at her local world
  time as on every other plan route. `get_upcoming_social_plans` and the
  export's `plans` still give the world instants. `add_social_plan`'s
  unknown-person error is rendered for her pronoun.
- **A plan with people is kept against a whim, a pressing need and a
  housemate (Task 31).** 0.4.0 keeps a social plan whatever her mood or the
  weather, and 0.5.0 follows its slot unless she is too tired; but the
  branch's `DailyPlanner.is_free_time` protected only a plan agreed with the
  user, so on the merged tree her impulsivity dropped a "plan with Maya" slot
  (140 times in 1,000 draws at a `plan_deviation_chance` of 0.15, the
  review's count),
  hunger took it for a meal, and a housemate's joint activity took its hour.
  `is_free_time` now also says no for a slot whose reason is a plan with
  people (`SOCIAL_PLAN_REASON_PREFIX`); too tired or too low on energy for
  it, she still does not do it, as on 0.5.0.
- **Her money is on the hours scale, and a new persona is not worried about
  it from her first tick (humanness program Task 29).** `FinanceSystem.tick`
  drew a discretionary purchase with a chance per TICK (0.04, scaled by the
  spending habit), so how often a host ticked set what she spent: at the
  5-minute energy tick a default persona's 1,200 was gone in about three
  simulated days, at 15-minute ticks it lasted longer, whatever her habit.
  Now her purchases are drawn once per world hour (`HOURS_PER_MONTH`) against
  a monthly budget, `discretionary_budget()`: her surplus (income minus
  recurring expenses) times `spending_habit / BREAK_EVEN_HABIT` -- the
  default habit spends her surplus, a frugal one (0.1) a fifth of it and
  saves, a spender (0.9) 1.8 times it and runs down; nothing left over, no
  purchases. `on_activity(name, now=...)` pays for an activity once in its
  world hour, however often the activity tick repeats it in that hour
  (`LifeService` passes the instant; without `now` every call is a purchase,
  as before); one she cannot afford is not paid for. And `FinancialState`'s
  1,200 against 1,850 of expenses (a runway of 0.65, financial stress 0.45)
  sat in the band where `LifeService` holds "money worries": every new
  persona was worried from her first tick. A new `FinanceSystem` now starts
  her at `STARTING_RUNWAY` months of her expenses (`STRESS_RUNWAY_CEILING`,
  the runway with no financial stress: 2,775 at the defaults,
  `starting_balance()`); a saved persona keeps her saved balance, and an old
  save loads unchanged (`tests/test_finance_hours.py`). The default
  setting's trace pin is re-recorded (ruling T9-R3).
  Host contract: a purchase is a draw for a world hour, once per hour from
  her first tick on; the first tick of a new or reloaded engine draws its
  own hour, so one tick with a sure chance still buys once (aura's
  `test_spending_habit_drives_discretionary` holds), and further ticks in
  that hour draw nothing. The last hour drawn is saved (a new nullable
  `spend_hour` column of `life_financial_state`, in `to_dict` /
  `from_dict`): after a reload the hours she was away are drawn once,
  whether the host's first live tick or its `catch_up_from_downtime` comes
  first (before, the live tick first drew none of them); an old database
  reads NULL and draws from its first tick. A single tick across whole
  calendar months (a process suspended past a month, a host off for one)
  draws only the rest of the last drawn hour's month and its own month up to
  its hour: `tick` credits one month's pay and bills however many months it
  crosses, so the months between are not spent from either (Task 29 fix
  round 1).
- **A host off over a month's end pays and bills her once.** A month counted
  as new whenever it differed from the last payday's, in either direction, and
  a tick moved the payday to its own instant: with the host's first live tick
  before its `catch_up_from_downtime`, the catch-up's slot backdated into the
  old month was a "new" month and the next one in the new month a third (her
  2,600 pay and 1,850 bills three times: 5,425 where 3,925 was due). A month
  is now new only when it comes after the last one paid, so a backdated tick
  pays nothing and leaves the marker where it is, as it draws no hour; while a
  world clock stays behind the last month paid, nothing is paid or billed
  (found reading Task 29's fix round; `FinanceSystem._is_new_month`).
- **A profile's `Gender: woman` is she, not they.** `pronoun_render.resolve_gender`
  knew only the three words of `GENDERS` ("female", "male", "nonbinary"), while a
  profile says `woman`: aura's persona wizard writes that word by default, and the
  profiles its hosts ship carry
  it. Every such persona was rendered as they/them in all prompt-bound text. The
  new `GENDER_WORDS` maps the words a profile writes (`woman`, `girl`, `f`, `man`,
  `boy`, `m`) to `GENDERS`; an unknown word is still never guessed
  (`tests/test_gender_words.py`). Found by the dustlands-2090 pack's sim (Task 20).
- **A record made without a time reads the clock a host or a simulation
  puts in place** (Task 15's completion). The models whose time defaults to
  "now" (`ActivityLog.started_at`, `DailyPlan.created_at`,
  `EnergyState.last_update`, `Goal.created_at`, `LifeEvent.created_at`,
  `ShareableExperience.created_at`, `ShortTermDesire.created_at`,
  `SocialEvent.timestamp`, `WorldState.virtual_time`) bound the host's
  `datetime.now` at import (`field(default_factory=datetime.now)`), so a
  simulated run -- which points every `aura_life` module's `datetime` at its
  own instant -- still stamped its goals and wants with the host's date, and
  what it did hung on that date: the default setting's trace pin, recorded
  on 2026-09-27, stopped replaying once the host's date passed the simulated
  one (on the code before Task 15 as well). `aura_life.models._now` reads
  the module's `datetime` when the record is made; a host's own clock is
  what it always was. The trace pin is re-recorded (ruling T9-R3): the
  trace every host date after 2026-10-12 gave, now on any date.
- **A persona's occupation and interests reach her planner when the host
  hands over only her definition** (Task 10). `LifeService` read the
  occupation from its `occupation=` argument or the definition for her career,
  but only from the argument for her `DailyPlanner` (and the places her
  occupation adds), and her interests only from `interests=`: a host that
  passed `definition=` alone got a nurse whose plans never held a shift and a
  planner with no interests. Both now come from the argument when given,
  else from the definition, for every engine that reads them.
- **Her body-image seed reaches her body** (Task 10). `BodySystem` lowers
  her body-image baseline when her struggles or core traits say so
  (`PersonaParameters.body_image_struggle`), but `LifeService` never handed
  it her definition, so the seed was never read; it passes her parameters
  now, at construction, in `reset_state()` and on reload:
  `BodySystem.from_dict(..., params=, substance_tendencies=)` takes her seeds
  as a new body does -- the baseline her parameters give, whatever the row
  saved, and her substance tendencies, which the row never held (a reloaded
  body forgot them: an "avoidant" drinker drank like anyone).
- **Two more chaos lines agree with "they" -- and with "you"** (Task 12 fix
  round, ruling T12-R4): "got lost in a section {subj} never visits" and
  "noticed something beautiful {subj} usually misses" read "they never
  visits" for a nonbinary persona, and "you never visits" once her memory
  stream kept them addressed to her. They read "never visit{s}" and
  "usually overlook{s}" now; the memory stream's second-person lint fails a
  hard-coded "-s" verb after the pronoun in every line an episode can be
  told in. The default setting's recorded fixtures were re-recorded for it
  on purpose (ruling T9-R3): the `activity_chaos` and `universal_chaos`
  digests moved; no step of the recorded trace did.
- **Seven lines agreed with "she" and "he" but not with a nonbinary
  persona's "they"** (Task 9 fix round, ruling T9-R4): a verb hard-coded
  after the pronoun token read "They was thinking about what Sam said", "a
  refund they wasn't counting on", "a laugh they hasn't thought about" (the
  contemporary NPC-event, serendipity and nostalgia pools) and "They was
  busy" (four of `ChaosEngine`'s message-delay explanations). They carry the
  agreeing `{was}` and `{have}` tokens now, and `tests/test_render_lint.py`
  fails "they" followed by was, has, is or does (or its "n't") in every pool
  it renders.
- **An NPC event told by the "mentioned" fallback is a mention.** When a
  setting has no template for the event type drawn, `SocialSystem` tells it
  with a "mentioned" line, but the event kept the type drawn -- and an
  "invitation" or "hangout" is always share-worthy. It is typed "mentioned"
  now, and share-worthy on a mention's 20% roll. The contemporary pack has a
  template for every type, so no default persona's events change.
- **Prompt-bound and user-visible text no longer hardcodes the persona as
  female or the user as male, and never calls the user "the user."** Measured
  before (humanness program, Task 6): about 300 template lines across
  `life_service`, `energy_system`, `world.environment`, `job.career_system`,
  `affect_system`, `activities.activity_engine`, `chaos_engine`,
  `social_system`, `intimacy.desire_system`, `continuity_system`,
  `memory_time_system`, `identity_system`, `cognitive_system` and
  `life_events.life_event_system` addressed the persona in second person
  ("You're...") while hardcoding third-person "she/her" mid-sentence ("dead
  tired, can barely keep her eyes open"; "Where you are: her workplace"); two
  thirds of genre-randomizer personas are male or nonbinary since 0.3.0, so
  most renders misgendered the persona. Three `daily_planner` wants assumed a
  male user ("Make a playlist for him"); `context_builder` and
  `identity_system` called the other person "the user" verbatim regardless of
  `user_info`; and the status bar capitalized the internal activity id
  `"thinking about user"` into "Thinking about user" instead of a name.
  `aura_life.personas.pronoun_render` (new) adds `render_line()`: fills a
  persona's pronoun tokens (`{subj}`/`{Subj}`, `{obj}`, `{poss}`/`{Poss}`,
  `{poss_pron}`, `{refl}`, `{be}`, `{have}`, `{was}`/`{Was}`, `{s}`, `{noun}`
  -- reusing `genre_randomizer.PRONOUNS`, the tested single source for those
  forms, via a lenient `resolve_gender()` that reads a missing/unknown gender
  as they/them rather than raising) and a user-reference token (`{user}`,
  `{User}`, `{user_poss}`/`{user_Poss}` -- the name from `LifeService`'s
  `user_info` when present, else the same they/them forms) in one pass,
  leaving any other `{token}` untouched. A line addressed to the persona in
  second person ("Where you are:", energy's "You're...") now says
  "your"/"you" instead, needing no token at all. Lines addressed in third
  person (activity narratives, micro/chaos events, nostalgia fragments,
  continuity milestones, intimate-activity narratives, gossip/dream
  fragments, the status bar, career events) render through the persona's own
  gender. Where a pool's chosen text is also a dict key an emotion table
  matches by exact/substring text (`affect_system.WORK_EVENT_EMOTIONS` against
  `job.career_system.POSITIVE_EVENTS`/`NEGATIVE_EVENTS`;
  `chaos_engine.CHAOS_EMOTIONS` against its own event pools), both sides keep
  the *same unrendered, tokenized* text so the match still fires, and
  rendering happens only at the export/status or narrative boundary, after
  the lookup (`LifeService._render_career_status`,
  `_render_desire_status`, the chaos-event handling in the activity tick).
  `IdentitySystem`'s user perception and `LifeService`'s own restore path
  default to `"them"`, never `"the user"`; `context_builder`'s goal and
  perceptions sections read the resolved name off `IdentitySystem` instead of
  a literal string. `tests/test_render_lint.py` (new, 94 cases) renders every
  converted pool with a male, female and nonbinary persona and a named and
  unnamed user, and scans every raw template for a hardcoded pronoun.
- **`get_life_context()` shows the mood that is being ticked.** The context
  builder kept the affect engine the service had at construction, while
  loading a saved row (every `start()` after the first save) and
  `reset_state()` replaced the service's own; after a restart the context's
  mood section read an engine nothing ticked any more. Both now go through
  `LifeService._use_affect`, which hands the builder the same engine.
- **Her day plan is read on the world clock, in her local time, and joining a
  housemate takes the joiner's hour (humanness program Task 28, ruling
  T13-R1).** Measured before: `DailyPlan.get_current_slot`, `get_next_slot`
  and `get_remaining_slots` read `datetime.now()` -- the host's clock -- and
  `LifeService.get_current_location()`, which the end of every activity calls
  (`_check_visual_transition`), moves her to her current slot's place. So a
  housemate who had just joined an activity at the park was moved back to
  wherever her plan said for the host's hour:
  `tests/test_household_npcs.py::test_a_joint_activity_goes_where_the_activity_is`
  passed with the host's clock at 02:00 and 09:00 and failed at 15:00 and 22:00
  ("park" == "home"). The simulations never showed it, because
  `tests/sim_helpers.py` patches `datetime` in every aura_life module during a
  run. Every `DailyPlan` slot lookup now takes the instant it is asked about
  (`now=None`, the host's wall clock, is kept only for a host outside
  aura-life that reads the plan itself -- aura does), and so do
  `DailyPlanner.needs_new_plan`, `generate_daily_plan` (the plan's day and the
  weekday her shift follows), `revise_upcoming` and `export_state`. Every
  caller inside aura-life passes her local world time
  (`LifeService._local_world_now`: her timezone's persona clock when she has
  one, else the world clock): `get_current_location`, `current_activity_name`,
  `get_status()`, `resume_planned_activity`, `export_inner_state()`, the plan,
  energy and activity ticks (the activity tick's hour and the slot it marks
  done were `persona_local_hour()`, the host's persona clock), the life-trigger
  evaluation, the visual check, the downtime catch-up's plan and location sync,
  the reload's location fallback, "skip work", "stay here" and "go to ..."
  (`apply_schedule_override`), a conversation plan, a meeting arrival and a
  transit arrival (through `_plan_instant`, which still gives a duck-typed
  stand-in no instant), and the
  context builder's "Your day today" ("Right now", "Coming up", "Later"; a
  builder without a service reads the host's clock as before). For a persona
  with a timezone her plan is now read on her own hours throughout: the slot
  lookups used to read the server's hour while the activity tick read hers.
  Joining is now an override of the joiner's own plan for the hour:
  `_join_housemate` rewrites her slot for the hour to the joint activity at
  the housemate's place, reason "with <name>", before she does it
  (`DailyPlanner.join_activity`, which adds the slot when her plan had none
  for the hour and, like every override, leaves it not done until she does
  it), so every later sync keeps her there and her own ticks for the rest of
  the hour follow it; the hours after it are as she planned them. And the
  sync itself no longer moves her while her place is held
  (`LifeService._location_held`): while a transit is getting ready or under
  way, and while a housemate's activity she joined is hers (`_joint_until`),
  `get_current_location()` answers where she is, and `get_status()`, the
  visual check and `resume_planned_activity()` leave her there -- a read of
  her status mid-transit used to put her at her plan's place, and one in a
  joint activity that ran into the next hour sent her to that hour's. The
  `DailyPlan` slot lookups, the plan's dating, revision and export, and the
  overrides answer on the world's hour with the host's clock frozen at 02:00,
  09:00, 15:00 and 22:00 (`tests/conftest.py`'s new `host_hour` fixture:
  `datetime` frozen in `aura_life.models`, the planner and `LifeService` for
  one test only; `tests/test_planner_clock.py` section 5 and the household
  joint tests run at each hour), and no plan read inside the library is made
  without an instant (`test_no_plan_read_in_the_library_falls_back_to_the_host_clock`).
  Every test outside the simulations that reaches the plan -- the 138 a probe
  of the suite found, with all of `tests/test_planner_clock.py` and the new
  join tests, 202 per run -- passed with the host's clock frozen through the
  same fixture code at each of the four hours. A host that injects no clock
  and the simulations are unchanged: the default-setting trace replays step
  for step. This finishes what 0.4.0's "A plan agreed in conversation ..."
  left on the host clock: only the desire stamps and expiry, a plan's own
  `created_at` stamp and the transit state machine's own stamps stay there,
  and a host that steers time by patching a module's `datetime` no longer
  steers any read of her day plan on a `LifeService` (inject a world clock
  instead).
- **"Persona Type" matched `"ai"` as a substring of the whole value**, so
  `"Human (Haitian)"` and `"human, trained sailor"` parsed as AI personas
  (both contain "ai": "H**ai**tian", "tr-**ai**ned"). `ProfileParser` now
  requires the normalised value to equal `ai`, `a.i.` or
  `artificial intelligence` exactly; everything else is `human`.
- **The daily planner's day-chaos seeds used the built-in `hash()`**, which is
  salted per process, so the same date produced a different seed -- and a
  different plan -- in every process; a replay disagreed with its own original
  run. Every seed site in `daily_planner.py` now uses
  `zlib.crc32(<str>.encode("utf-8"))`, which has no process-dependent state.
- **Shadow confession matched filler cues** ("honestly", "truth is", "to be
  honest") that appear in ordinary sentences with no confession in them (e.g.
  "honestly I'm tired"), clearing any recorded secrets on a false trigger.
  `ShadowSystem.on_user_message` now confesses only on the explicit cues
  ("i have to tell you", "i lied", "confess").
- **Conversation-derived goals and wants were generated from a random long word
  of the user's message**, about 10% of the time, regardless of what the word
  actually was. The mechanism -- `GoalEngine.generate_goal_from_conversation`,
  `DailyPlanner.generate_desire_from_conversation` and their call in
  `LifeService.on_user_message` -- is removed.
- **A behavioral-tendency thought could render the literal template placeholder
  `{npc}`** when nothing filled it. `IdentitySystem.get_active_tendency_thought`
  now fills it from a real NPC in the social circle (seeded into
  `_perceptions` at construction) when one exists, and falls back to a
  nameless variant otherwise -- no template renders a literal `{`.
- **The intrusive-pull pick always returned the same theme** (`pool[0]`),
  despite its own docstring's claim that it rotates.
  `ShadowSystem._pick_intrusive_theme` now rotates least-recently-used through
  the pool, and the rotation position (`_intrusive_pull_index`) is persisted
  alongside it so a reload continues the rotation instead of restarting it.
- **Disagreeing with the user applied `healthy_debate`'s positive mood shift**,
  so "i disagree", "you're wrong", "no way", "don't you think", "but what
  about", "agree to disagree" and "that's not" all made mood better, not
  worse. These cues now keep only their cognitive/identity effect;
  `"you're wrong"` maps to the `criticism` effect instead. `conflict_topic`
  keeps its stress effect and loses its own positive mood shift.
- **Nothing persisted inner state on a tick** -- only `stop()`, a state reset
  and downtime catch-up saved to disk, so a crash between those lost every
  simulated hour since the last one. A started service (one that has loaded
  its state) now also saves its inner state from `LifeService._on_energy_tick`,
  at most once per simulated hour on the world clock, so while it ticks a crash
  loses about an hour. A service that never loaded its state never saves from a
  tick, so it cannot overwrite a life persisted by an earlier run.
- **`LifeService.__init__` wrote its own `persona_locations` and
  `sleep_schedule` onto a shared `WorldEnvironment` at construction**, so
  whichever persona was built last decided both for every persona sharing that
  world: a measured run showed a persona with no profile describing another
  persona's room, and one persona's time-of-day phase disagreeing with her own
  sleep schedule 46% of the time. `WorldEnvironment.get_location_description`
  and `get_status` now take an optional `persona_locations`/`sleep_schedule`
  override instead of always reading the instance's own, and a new
  `get_time_of_day` recomputes the phase from an arbitrary schedule at the
  world's current instant. `LifeService.__init__` no longer writes either
  field on a world it was handed; a shared world's location description
  reaches `LifeContextBuilder` through a new `PersonaWorldView` (this
  persona's own locations, the world's actual weather and current location),
  and every other read of the world's time-of-day goes through a new
  `LifeService._persona_time_of_day` property that asks the world for this
  persona's own phase instead of trusting whichever persona's schedule the
  shared instance holds. A private (unshared) world is unaffected -- it only
  ever held one persona's data to begin with. `WorldEnvironment.export_state`
  (the host's digest input, `LifeService.export_outer_state`) gained the same
  optional overrides, plus a new `location_description` key, and its
  `ambiance` is rebuilt from the persona's own room when given one -- it used
  to always read the shared, generic one. Review round 1 also caught the two
  `LifeService` call sites (`get_status`, `export_outer_state`) passing the
  overrides unconditionally: for a *private* world with a real sleep schedule
  this made `WorldEnvironment.get_time_of_day` take its recompute-at-now
  branch instead of returning the phase as of the last tick, so a
  private-world `get_status()` read between ticks could disagree with the
  same persona's own `_persona_time_of_day` -- both call sites now pass the
  overrides only for a world this service was actually handed, with a
  `TypeError` fallback to the plain, argument-less call for a duck-typed
  world whose `get_status`/`export_state` predate these keywords.
- **A `WorldEnvironment` shared by several personas still held one
  `current_location`** (Task 2's fix above covered room descriptions and
  sleep phase, but its `PersonaWorldView` passed `current_location` straight
  through, documented as "genuinely shared physical state"), so one
  persona's move relocated every persona sharing the world: a measured run
  showed another persona moving the shared world after a persona's own tick
  in 82 of 288 steps, and one persona's traits changing another's trace
  (Task 8 humanness program, ruling T8-R1 / Task 27). `LifeService` now owns
  its own `current_location`, seeded to `"home"`; it never writes a shared
  world's. `WorldEnvironment.get_status` and `export_state` gained the same
  optional `current_location` override `persona_locations`/`sleep_schedule`
  already had, and `PersonaWorldView` takes a third constructor argument -- a
  zero-argument callable returning this persona's own location, the same
  shape `now` already gives the world's clock -- so its `current_location`
  property and `get_location_description()`'s default both describe her,
  never the wrapped world's. Every `LifeService` call site that used to write
  `self._world.move_to(...)` directly now goes through a new module-level
  `_move_persona_to` free function (not a method looked up on `self`, so it
  still works when `apply_schedule_override`, `schedule_meeting_arrival` or
  `advance_transit_phase` runs bound to a duck-typed stand-in with no
  `_shared_world` attribute at all, as `tests/test_planner_clock.py` already
  does): it always updates the persona's own location, and only moves the
  (possibly shared) world itself when this service is not sharing it. A
  private (unshared) world is unaffected -- the service still writes its own
  world directly, exactly as before. Weather, time of day and season stay
  genuinely world-level.
- **The hours she was away are lived hours for her affect (humanness program
  Task 34b).** After a reload the first live tick charges her affect only the
  time since the reload (kept: downtime is not charged as lived time, ruling
  T34-R1), and `catch_up_from_downtime` never ticked it: after an 8-hour gap
  her loneliness had gained 0.0019 where a host that stayed on gains 0.0591
  (0.0025 against 0.2425 with no interaction ever), and her regulation and
  empathic fatigue had moved by one tick. Now the catch-up ticks her affect
  for the gap, as it already charges her hunger: before each slot it executes
  (the world hours since the gap's start or the previous slot, up to the
  slot's instant) and for the rest of the gap (the whole gap when it executes
  no slot), the hours summing to the gap. Each of those spans is lived with
  the body state it began with (her hunger as the previous slot left it, the
  rest of the gap's too: it is ticked before her hunger is charged for those
  hours), and is split where her sleep hours begin or end, each part asleep
  exactly in her sleep hours, judged on the host's hour as the catch-up's
  sleep slots are (fix round 1: the rest of the gap had seen the gap's end
  hunger, 1.0 over 72 hours where its hours began at 0.32 with her planner
  and 0.0 with no slot; and a span had taken the flag of the slot that ended
  it, so an overnight gap with no sleep slot was lived awake). It
  runs on the world clock and ends where her live affect ticks began (her
  reload, kept in memory only), so the host's first live tick may come before
  it or after: after an 8-hour gap her loneliness gains 0.059094 and 0.242500
  in both orders, as the host that stayed on, and her empathic fatigue and
  (but for a slot's own regulation recharge) her regulation match it. The
  hours are the real gap, not the 48 the catch-up plans at most: five days
  away are not two (at a desired contact of 0.1 and no interaction, 72 hours
  give 0.4325 of loneliness, as a host that stayed on, where 48 would give
  0.2885). A gap under an hour charges nothing, as before, and a gap that
  does not reach back past her reload (the host's clock jumped while the
  process lived on, as aura-desk's poll reports a PC that slept) is the live
  tick's to charge, never twice. Her mood and stress move over the gap too,
  not as a day lived live would move them (the slots are not that day). No
  constant changed, no saved field (`tests/test_affect_catch_up.py`). One
  affect tick runs at a time (`LifeService._affect_tick_lock`): the live tick
  and the catch-up run on different threads, and interleaved one would have
  written over the other's change, the hours of a whole gap.
- **Her loneliness, regulation and empathic fatigue are on the hours scale
  (humanness program Task 34).** `AffectSystem.tick` already took `hours`, and
  mood's half-lives and stress's tension ran on it, but the other three
  updates added or removed a fixed amount per TICK: at the 15-minute ticks of
  the simulation harness a default persona with no interaction had 0.24 of
  loneliness after a day where the scheduler's 5-minute energy tick gives
  0.72 (0.06 and 0.03 at 60- and 120-minute ticks), her regulation took 8.75
  hours to come half-way back from 0.2 instead of 2.92, and an empathic
  fatigue of 0.5 lasted 25 hours instead of 8.33. A tick of `hours` now does
  what `hours / DEFAULT_TICK_HOURS` default ticks ending at its `now` did:
  loneliness before any meaningful interaction, empathic fatigue and an
  absorbed emotion's fading move by their per-tick amounts times that count,
  regulation's pull to its baseline (2% of the gap a tick) is compounded over
  it, and loneliness counted from her last meaningful interaction -- whose
  per-tick growth rises with the hours since -- adds the closed form of the
  series of its per-tick amounts, counting only the default ticks past the
  4-hour grace. One default tick (and `hours=None`) gives bit for bit the
  values a tick always gave, so the production cadence and the default
  setting's trace pin do not move (ruling R18; the amounts are named once,
  `LONELINESS_GROWTH_PER_TICK`, `LONELINESS_GAP_GROWTH_PER_TICK`,
  `REGULATION_RETURN_PER_TICK`, `EMPATHIC_FATIGUE_FADE_PER_TICK`,
  `ABSORBED_EMOTION_FADE_PER_TICK`, with their per-hour readings, none
  retuned); a tick of no world time moves none of them, and a tick of a
  month keeps each inside its bounds (`tests/test_affect_hours.py`). Not
  changed: after a reload the first live tick counts the hours since the
  reload, not the hours she was away, and `catch_up_from_downtime` does not
  tick her affect, so the gap still adds nothing to her loneliness, in
  either order (as for mood and stress); Task 34b's catch-up does (the entry
  above).
- **A gap the process lived through charges her hunger once (humanness
  program Task 34c).** aura-desk calls `catch_up_from_downtime` for a PC that
  slept while the process lived on (its poll), beside the scheduler's live
  ticks, so either may come first. The live tick charges her hunger every
  world hour since its stamp, and the catch-up charged the whole gap again:
  after 8 hours with no slot her hunger gained +0.7720 with the live tick
  first, where a host that stayed on gains +0.3880 (0.82, above the pressing
  need of 0.7). Now the catch-up charges her hunger only the hours of the gap
  her live tick never charges: the downtime before where her live hunger
  ticks began (her reload, which takes the live tick's stamp again; kept in
  memory only), the whole gap as before, in either order; and of a gap inside
  their span only the hours after the live tick's stamp, which the catch-up
  then takes, as before: none with the live tick first, all of them with the
  catch-up first. +0.3880 in both orders; with a meal slot in the gap, one
  meal and her hunger 0.3360 from 0.3480 in both orders, lived through or
  restarted (before: 0.7200 lived through with the live tick first). Its
  slots still feed her; a restart is unchanged. No constant changed, no saved
  field (`tests/test_catch_up_hunger.py`).
  Fix round 1: with the live tick first, every backfilled meal came after all
  of the gap's hours, so her end hunger depended on the order where a relief
  met the clamp at 0 (8 hours, meals 1 h and 3 h in: 0.0000 against 0.2400
  with the catch-up first; 30 hours: 0.0000 against 0.4400). The live tick now
  keeps, in memory only, a paused host's hours and her hunger and nutrition at
  their start; the catch-up of the same gap puts them back and lives those
  hours again in time order with its meals: 0.2400 and 0.4400 in both orders,
  her nutrition the same. A live meal after the wake keeps the hours as they
  were charged. Of a gap she lived through, every hour since the live tick's
  stamp is charged, those over the 48 hours the catch-up plans included.
- **At a joint activity's tail, what she is doing follows where she is held
  (humanness Task 19, ruling T19-R5).** A housemate's activity she joined at
  14:50 holds her at its place until 15:10 (`_joint_until`, Task 28), but
  from 15:00 `current_activity_name`, `get_status()["current_activity"]`, her
  context's "Right now" line, her next activity (`_next_activity_info`, the
  wrap-up's) and the plan `export_inner_state()` hands a digest pass read the
  15:00 slot -- "journaling at home" while her location said the park. They
  now read her plan at the instant she joined (`LifeService._activity_instant`,
  `_joint_at`) while the window holds her (`_joint_held`, the half of
  `_location_held()` that is the joint window): the joint activity, where she
  is, and "Right now" shows it though its slot is done; from 15:10 on, the new
  hour's slot again. So do the energy tick's activity for her body and her
  mind (`BodySystem.tick`, `CognitiveSystem.tick`: a walk's toll, not a
  desk's), the moment a proactive share names, and the visual check's
  activity (paired with her held location). A transit's hold is unchanged.
  `tests/test_household_npcs.py::test_at_a_joint_window_s_tail_what_she_is_doing_is_the_joint_activity`,
  `..._her_body_her_mind_her_moment_and_her_looks_follow_the_joint_activity`.
- **No drink reaches an AI persona's body (humanness Task 19, ruling T19-R6).**
  `BodySystem.on_substance_activity` was called for every persona from
  `_perform_activity` (outside the humans-only block) and the catch-up's
  `_tick_engines_for_catchup`; an AI was kept off drinks only by every drink
  activity carrying the "physical" tag, so a setting pack's "having a pint"
  (tagged "alcohol") made an AI tipsy by her own pick, a plan slot, a
  housemate's activity she joined, or a catch-up. Both now go through
  `LifeService._give_substance`, which tells the body nothing for an AI; a
  human's drink is as before, and the tag-based exclusions stay.
  `tests/test_activity_choice.py::test_an_ai_persona_s_body_is_never_given_a_drink`
  (4 paths x AI/human).
- **What decides her life reads the world clock, not the host's (humanness
  Task 19, rulings T11-R3, T19-R1, T19-R2).** A simulation froze the host's
  clock at the world's instant, so it never showed; a host whose world clock
  is not its wall clock (one that simulates or pauses time) had her
  relationships cool, debts fall overdue, quarrels be forgotten, goals stall,
  expire or wait, thoughts go stale, persisted emotions decay, ailments end,
  fitness wane, the chaos cap and the day's goal reset, anniversaries come up,
  avoidances and frustration grow, anticipations lapse, a place's visits count
  and a trip return by the host's hours, days or year. Each engine now takes
  the instant as an optional keyword-only `now=` (the host's clock without
  it, as before) and `LifeService` hands it the world's
  (`_world_clock()()`; her local world day for the chaos cap and her visits):
  `SocialSystem.tick`, `update_arc`, `tick_arcs`, `tick_obligations`,
  `tick_conflicts`, `add_plan` (its `created_at`), `add_obligation`,
  `trigger_conflict`, `resolve_conflict`; `GoalEngine.evaluate_motivation`,
  `generate_daily_goal` (the goal's `created_at` too), `generate_goal_from_activity`,
  `update_progress_from_activity`, `check_goal_completion`,
  `get_emotional_context`, `export_state`, `get_status`, `load_goals`,
  `initialize_goals` and the new `goalless_hours(now)` (the
  `goalless_duration_hours` property reads the host's clock as before);
  `CognitiveSystem.tick` and `get_inner_monologue`;
  `EmotionPersistence.save_emotion`, `get_current_emotions`,
  `get_dominant_emotion`, `get_emotional_context`, `get_status` (a host's
  read: on the host's clock it decayed away, and deleted, what the world's
  instant had just stamped), its constructor and
  `get_emotion_persistence` (the load's decay); `BodySystem.tick` (`now` in
  its keywords), `on_activity`, `on_new_day`, `roll_daily_health`,
  `on_substance_activity`; `ChaosEngine.roll`; `ContinuitySystem.get_upcoming_anniversaries`
  and `export_state`; `DriveSystem.tick`; `DesireSystem.tick` and
  `execute_intimate_activity`; `MemoryTimeSystem.get_anticipations` and
  `export_state`. `LifeService._apply_location_effects`, the goal tick's
  anticipation of a goal due, `_load_place_state`'s trip return and the
  world tick's `_update_trip` read the world clock. Signatures stay
  compatible; a stand-in that replaces one of these methods with a function
  taking no `now` must accept it (twelve test stand-ins in seven files did). The context
  builder passes the world instant only when its service has a world clock.
  At the simulation's frozen clock every instant is the one it was: the
  default setting's trace replays byte for byte. What stays on the host's
  clock, each with its reason, is the allow-list of
  `tests/test_world_clock_lint.py`, which fails on any other function that
  reads it, under whatever name the clock was imported as (`import time as
  _clock`, `from datetime import datetime as _dt`, `from time import
  monotonic`). `tests/test_world_clock.py` (52: each engine under a host clock
  four years away, each tick's and each other hand-over -- her company, a
  call, a new day, her proactive triggers' thought and goals, intimacy, an
  activity's progress, new goal and emotions, a reload -- what she lives
  through).

## [0.5.0] - 2026-11-07 — habits that drift over days

### Added

- **Habits her planner favours.** What she has done often lately becomes a habit the daily planner leans toward (comfort); what she has done too much loses its pull (staleness); her days shift slowly over a week and keep their variety. Per part of her day (`habit_band`: morning 6-11, afternoon 12-16, evening 17-21, night) each activity's lived ticks are weighted `0.5 ** (age_days / 3.5)`; its `share` of that part's free time (the day anchors, sleep and naps left out: `NOT_HABIT_FORMING`) gives `comfort = min(1, share / 0.15)` and `staleness = clamp(share / 0.15 - 1, 0, 2)`, a pull `confidence * (comfort - staleness)` in [-1, 1] (full at a 15% share, neutral at 30%, fully stale from 45%; `confidence = min(1, weighted ticks / 60)`), a factor `1.5 ** pull` in [1/1.5, 1.5], split in two: `raise = max(1, factor)` and `damp = min(1, factor)`. `DailyPlanner.generate_daily_plan(..., habits=None)` takes `{part of the day: {activity: (raise, damp)}}` (`BehaviorSystem.habit_factors(now, exclude)`): for each hobby slot, with its own part of the day's habits, the raise (comfort) multiplies a candidate's *score* before the planner's top-six cut, so a habit can bring an activity into the six; the damp (staleness) multiplies its *weight* after the cut, and a damped candidate the planner alone would have put in the six keeps its place there, so staleness lowers an activity's chance by at most ÷1.5 and nothing pushes it out: what she overdid is dampened, never erased (AI personas: the daytime slots). Her own picks between slots (`ActivityEngine.select_activity(..., habit=None)`, two ticks of every three) do the same around their top-five cut, for the part of the day of her hour. `habits=None` / `habit=None` draw exactly as 0.4.0. `LifeService` passes the habits on the world clock to the daily plan, the catch-up's plans and her own picks. The six numbers are design values in one block in `behavior/behavior_system.py`, one line each saying why. Measured on a fake clock (`tests/test_habits.py`, 30 seeded weeks of a human day with no work, two ticks of journaling and six of puzzles every morning of her own): her chance of journaling in a morning choice, over her chance without habits, went 1.00, 1.58, 1.58, 1.71, 1.87, 1.79, 1.73 from day 1 to day 7 (its share of the morning choices 11.5% to 16.7%), and of puzzles 1.00, 0.91, 0.84, 0.79, 0.76, 0.73, 0.70 (13.3% to 9.6%; 0.70 on day 7 for each of six seed sets, the test's floor 0.5); no score was raised past ×1.5 and no weight lowered past ÷1.5, and no activity took more than 14.1% of a part of her day's planned slots (16.8% at most over six seed sets).
- **Her patterns, as the prompt tells them, are her habits.** The context's "Your patterns" lines read the same habits the planner draws with: an activity whose pull is at least half its full strength "has become a comforting part of your mornings" (two at most), one pushed away as much is "You've had a lot of puzzles and games lately" (one at most), never the one for the other; the old routine counters (which cannot go stale in a varied day and are trained by catch-ups) no longer speak there. The digest's `export_outer_state()["behavior"]["routines"]` (`BehaviorSystem.export_state(now=None, exclude=())`) reads the same habits: the comforting ones, `{name, band, comfort}`, `comfort` being the pull (`band` is new).
- **A dated activity history.** `BehaviorSystem.track_activity(name, at=None, hour=None)` keeps `(activity, world-clock instant, her local hour)` for four weeks (at most 2016 entries, four weeks of the 20-minute activity tick; pruned by age against both this tick and the newest before it, so one tick with the clock far ahead cannot wipe it, and a tick dated after `now`, a clock set back, counts for nothing), read back as `BehaviorSystem.activity_log` and saved in a new `life_behavior_state.activity_log` column (added to an existing database when a `LifeService` opens it). The live activity tick dates every activity; a catch-up's replayed hours are not dated, so no habit is learned from hours she did not live. The 50-name `activity_history` and the routines are unchanged; a 0.4.0 database loads with an empty dated history and no habits, which form over her first week.

### Fixed

- **A catch-up whose gap held a run, yoga or the gym no longer fails.** `LifeService._categorize_activity` returned `ActivityCategory.PHYSICAL`, which does not exist, so `catch_up_from_downtime` raised `AttributeError` on such a slot and the rest of the catch-up (its remaining activities and every save) was lost; the activity now gets its own category (yoga `REST`, a run or the gym `EXPLORATION`), else `EXPLORATION`. Present since the extraction.

## [0.4.0] - 2026-10-15 — her people and her plans with them are public API

### Added

- **`ProfileDatabase.set_social_circle(npcs)`** replaces only the `profile_social_circle` rows, in one transaction (rolled back on failure, the old circle kept); no other table or column, timestamps included, is touched. Entries take `name`, `relationship`, `personality` (or `personality_brief`) and `shared_interests`; `contact_frequency` is ignored (derived on load). A running `LifeService` keeps its old circle until it is rebuilt.
- **The social circle and her plans with it are public API.**
  `LifeService.get_social_circle()` returns `{name, relationship, closeness,
  trend}` dicts, closest first (`closeness` and `trend` are `None` for someone
  with no arc). `add_social_plan(people, what, at, duration_min)` records a
  plan with people from her circle (`ValueError` for an unknown name, a blank
  activity, a non-positive duration, a timezone-aware or already-past `at`) and
  puts the matching slot(s) into today's daily plan through the same planner
  path as the `[PLAN: ...]` tag; `get_upcoming_social_plans(within_hours)` reads
  them back as `{people, what, at, duration_min}`. Everything is judged on the
  world clock and persists through the existing social-expansion save and load
  (a plan's slots are re-applied whenever a daily plan is generated, so tomorrow's plan and the after-midnight part of a late one get theirs; the day is the daily plan's own date, as the planner dates it on the host clock; `SocialObligation` gains `people` and `duration_min`; a plan is never overdue
  and the five-obligation cap never drops one). `export_outer_state()["social"]`
  gains `people` (her five closest, as `name`/`rel`/`close`/`trend`) and `plans`
  (the next 24 h, as `who`/`what`/`at`/`min`); the existing keys are unchanged.

### Fixed

- **A social event no longer aborts the activity tick.** The value-alignment
  lookup iterated `SocialSystem._npcs`, a `Dict[str, NPC]`, so every social
  event raised `'str' object has no attribute 'name'` and skipped the rest of
  the tick (445 times in one owner log).
- **A social plan and a debt with the same words no longer collide.** `add_obligation` and `fulfill_obligation` ignore plans.

- **Work stress, `on_shift` and the career status blocks answer on the world
  clock, not the host's.** 0.3.0 made the world clock injectable and moved
  `CareerSystem.tick` onto it, but a few lines later `_on_energy_tick` asked
  `self._career.work_stress()` with no instant, so `is_working_now` fell back to
  `datetime.now()`. On a host weekday inside shift hours work stress read the
  whole workload, crossed 0.5 and added the `"work stress"` stressor to affect --
  a stressor that raises the stress level sanity reads -- so a host that
  simulates time (a replay, a test) had its personas' stress decided by the hour
  the process ran. Measured in Hollow: one seed's ten-day, twelve-agent replay
  digest was `39aada4c915e` with the host clock frozen at 13:30 on a Wednesday
  or a Friday and `d6134fa0102c` at 22:45, 08:00 and 02:00 or at 13:00 on a
  Saturday; freezing one module at a time, only `aura_life.job.career_system`
  moved it. The same fallback answered `on_shift` in
  `CareerSystem.export_state` and `on_shift` and `work_stress` in
  `CareerSystem.get_status`, reached from `LifeService.get_status()`,
  `LifeService.export_outer_state()` and the context builder's work line. Both
  methods gain an additive `now=None`, forwarded to `is_working_now` and
  `work_stress`, and every call site passes the world instant: the energy tick
  passes the `_world_now` the career just ticked on, `get_status()` and
  `export_outer_state()` pass `self._world_clock()()`, and
  `LifeContextBuilder._build_career_section` reaches the clock through its
  `life_service` -- its only route to it; a builder built without a service, or
  on a duck-typed service with no `_world_clock`, asks with no instant, as
  before. After the fix Hollow's digest is identical, per
  seed, for seeds 1, 2 and 3 with the host clock frozen on a Monday at 09:30, a
  Wednesday at 13:30 and 23:59, a Friday at 16:59, a Saturday at 13:30 and a
  Sunday at 02:00, and with the host clock left running.
- **The energy tick's continuity cycles and weekly rhythm follow the world clock
  too.** Found by auditing every host-clock read reachable from the entry points
  a simulating host drives (`_on_energy_tick`, `get_status`, `on_sanity_blow`,
  `on_sanity_recovery`, `sanity`, `energy.sleep`, `stop`): two more of them
  decided something rather than stamping it. `_on_energy_tick` gated the daily,
  weekly and monthly cycles (anniversaries, growth snapshots, character
  evolution, life chapters) on `datetime.now()` minus stamps that
  `ContinuitySystem` and `CharacterEvolution` also took from the host, so on a
  simulated clock every cycle fired once, on the first tick, and again only after
  a real day, week or month of process life; and
  `MemoryTimeSystem._detect_weekly_rhythm` read
  the host's weekday and month, so "Monday heaviness" arrived on the host's
  Mondays. `ContinuitySystem.daily_tick`, `weekly_tick` and `monthly_tick`,
  `CharacterEvolution.monthly_evolution`, `MemoryTimeSystem.tick` and
  `MemoryTimeSystem.add_life_chapter` gain an additive `now=None`, and the tick
  passes one `self._world_clock()()` to the gate and to all of them -- so a
  simulating host now sees the cycles fire once per simulated day, week and
  month. The calendar scan inside the daily cycle stays on the host clock on
  purpose: it reads entries a host added in real time and feeds follow-up
  triggers whose cooldowns `_evaluate_life_triggers` stamps on the host clock.
  The host-clock reads left on those paths either only stamp a value (affect's
  `mood.since` and `last_relief`, shadow's `last_update`, cognitive's rumination
  and monologue stamps, drive's avoidance `created_at`, identity's `formed_at`
  and `last_surfaced`, a shareable's `created_at`), or compare it only on a
  `follow_up_provider` or companion path (`on_user_message`, the activity, goal
  and plan ticks, `add_calendar_entry`).
- **A plan agreed in conversation and the three schedule overrides are judged
  against the world's hour, not the host's.** `DailyPlanner.set_planned_activity`
  skips a slot whose hour has already passed today, and it read that hour from
  `datetime.now()` even inside a service on an injected world clock, so
  `LifeService.add_conversation_plan` dropped a `21:00` plan whenever the
  process ran between 22:00 and 23:59, whatever hour the world was at -- which
  is why `tests/test_multi_instance.py`'s 21:00 sentinel failed every night.
  `cancel_work_today`, `stay_at_current_location` and `schedule_rendezvous` had
  the same guard: they rewrite only the slots from the current hour on, so
  `apply_schedule_override` ("skip work", "stay here"),
  `schedule_meeting_arrival` and the arrival step of `advance_transit_phase`
  rewrote the slots ahead of the host's hour. All four planner methods gain an
  additive `now=None`, and those four service methods pass the world instant.
  They ask `getattr(self, "_world_clock", None)` first, because a host may call
  them bound to a duck-typed stand-in rather than a `LifeService` -- aura tests
  `add_conversation_plan` on an object with only `_daily_planner`,
  `_location_registry`, `_register_user_location` and `_save_plan` -- and a
  stand-in with no `_world_clock` passes no instant, so it keeps the host-clock
  behaviour. For a service with no injected clock the instant is the same
  wall-clock hour as before. The rest of the planner still reads the host
  clock: `needs_new_plan` and `generate_daily_plan` (which day and weekday a
  plan is for, and its stamps), the plan tick's silent `revise_upcoming`,
  `export_state`'s current slot, next slot and remaining count, the desire
  stamps and expiry, and `DailyPlan.get_current_slot`, `get_next_slot` and
  `get_remaining_slots` -- so "go to ..."
  (`override_current_location`) still picks the host's current and next slot,
  and "stay here" still takes the location of the host's current slot. The
  transit state machine's own stamps stay on the host clock too. Hollow reaches
  none of these. The multi-instance test now runs its shared world on a clock
  its rounds advance, so it no longer depends on when the suite runs.
  `tests/test_planner_clock.py` is the pin: with the planner module's host clock
  frozen at 22:45 and a world at 09:00, a 21:00 plan is kept and an 08:00 one
  dropped, and each override rewrites the 21:00 slot and leaves 08:00 alone;
  a service with no injected clock and a stand-in with no `_world_clock` still
  drop the 21:00 plan and leave the 21:00 slot alone.
- **A host that injects no clock is unchanged on the wall clock**, because
  `_world_clock()` is `datetime.now` without one, and a duck-typed service with
  no `_world_clock` asks the planner and the context builder with no instant,
  which is the host clock as before. A host that steers time by patching a
  module's `datetime` instead -- a test freezing
  `aura_life.job.career_system.datetime`, say -- no longer steers work stress,
  the career status blocks, the continuity and memory-time cycles, the
  conversation-plan check or which slots the three schedule overrides rewrite on
  a `LifeService`, because those now ask the world's clock: inject a world clock
  instead. Two byte-for-byte checks against 0.3.1's source back this, each only
  for the paths it measured. The first, run on the career and continuity change
  alone, covered 16 scenarios -- four frozen host instants, two seeds, an
  injected `rng` and module `random`, 48 energy ticks each -- comparing
  `get_status()`, both state exports, the work line, the continuity, evolution
  and memory-time rows and the rng state. The second, run with the planner
  changes in, covered the planner's guarded routes in 28 scenarios -- seven
  frozen host instants, a service with no injected clock and a duck-typed
  stand-in, each step on a fresh fixed plan and all steps in a row -- running
  conversation plans around the host hour, "skip work", "stay here", a meeting
  arrival and a transit arrival, and comparing the plan after every step and the
  module `random` state. Plan generation was not compared.
  `tests/test_career_clock.py` and `tests/test_world_clock_routes.py`
  are the pins: each engine method answers from the instant it is given with the
  host clock frozen to the opposite case, and two services on one injected
  clock, one seed and one rng -- every routed module's host clock at Wednesday
  13:30 for one and Saturday 02:00 for the other -- end with the same stress
  sources, career block, sanity and rng state. Nine of their sixteen tests fail
  on the previous tree; the seven that pass there are the no-clock guards and
  the check that a context builder whose service has no `_world_clock` keeps
  its work line.

## [0.3.1] - 2026-09-03 — the version has one source

### Fixed

- `aura_life.__version__` reported `0.1.0` in the 0.3.0 wheel while the distribution
  metadata said 0.3.0: the attribute and `pyproject.toml` were maintained separately and
  only one of them was bumped. The version now lives in the attribute alone and
  setuptools reads it (`dynamic = ["version"]`), so the two cannot drift; a smoke test
  asserts they agree.

## [0.3.0] - 2026-09-03 — personas are no longer all women, the world clock is injectable, and the generator's output finally fits its consumer

`_generic_concept` returned a hardcoded `"gender": "female"` from three literal
sites, and that was the small part of the problem. All seven `appearance_template`s
opened `"{age}-year-old woman ..."`, the module carried 209 she/her occurrences
and 15 woman/daughter/mother/sister, and every one of the seven name pools was
female. Deleting the three literals without touching the prose would have produced
a persona the library calls male and then describes as *"She has sat with ten
thousand people"* — a worse defect than the one being fixed, because it would look
fixed. So this release rewrites the corpus, not the constant.

**It is a minor bump rather than a patch, and it does reach existing callers.**
Nothing public was removed and no signature changed incompatibly — `gender` was
appended to both builders, so every v0.2.0 call form still binds — but the default
gender is now *drawn* instead of always being `"female"`, and the rng stream gained
one draw at the front. A caller replaying a run off a stored seed gets a different
persona than it did on 0.2.0. Both consequences are spelled out under *Changed*.

**The release carries a second, unrelated change: the world and the energy engine
no longer hard-code the host wall clock.** `EnergySystem` read `datetime.now()`
for `hours_awake`, which is right for a companion app that lives as long as the
person using it and wrong for anything that *simulates* time — the engine could
not be replayed, stepped, or unit-tested by any consumer without freezing global
state. It is additive and byte-identical by default: `now` defaults to
`datetime.now` at every new seam, so a caller that passes nothing gets exactly
what it got before. Details under *Added* and *Fixed*.

**The third change closes a gap between two halves of this same package.**
`build_genre_concept()` emits a 26-key dict; `LifeService(definition=...)` wants
a `PersonalityDefinition`. Seventeen of those keys are fields of that dataclass
and nine are not (`age`, `archetype`, `description`, `gender`, `genre`, `goal`,
`intensity`, `style_theme`, `tone_directive`), so `PersonalityDefinition(**concept)`
raises `TypeError` — and no converter existed anywhere in the package. The path
of least resistance, handing the raw dict over as `definition`, is worse than
the error: it *works*. Every read of the definition in `life_service.py` is
`getattr(definition, name, default)`, a dict answers none of them, and every
engine starts from its empty default with no exception and no log line. That is
a defect a consumer meets the first time it wires the generator to the service,
which is why the fix is a method on the library's own dataclass and not an
adapter in someone's app. Two smaller seams ship alongside it, on the same
argument: a supported way to register a genre, and a way to generate a cast
whose names do not collide. All three are additive.

**The fourth change is a new engine, and it is the one the library was missing.**
Eight engines carry interior -- mood, stress and loneliness in `affect`; unease,
felt safety, doubt, intrusive thought, concealment and masking in `shadow`; focus
in `cognitive` -- and none of them *integrates* those into a trajectory that can
break. A persona can be stressed, lonely, afraid and lying all at once,
indefinitely, and be the same persona tomorrow. `SanitySystem` is the seam that
ends: one scalar the host's blows push down, its recoveries push up, and world
time erodes or mends between, read through a closed graded vocabulary. Details
under *Added*.

**The fifth change is the one the fourth exposed: the energy tick now takes an
rng.** Every draw on `LifeService._on_energy_tick` -- identity's struggle,
defect and tendency rolls, desire's arousal drift, cognitive's monologue,
drive's avoidance roll, career, finance, errands, memory-time's nostalgia, the
life-event title, and the service's own coin between a surfaced struggle and a
rumination -- came from the module-level `random`. That is invisible to a
companion app, which never replays anything, and fatal to a consumer that does:
a host that seeds one `random.Random` per persona and drives two loops from the
same seed still watches them diverge, because the library keeps drawing from a
stream the host does not own, and nothing the host can seed reaches it short of
reseeding the global before every tick. Before `SanitySystem` nothing a host
*decided on* read those numbers, so the drift stayed in the digest text. Now
the sanity tick reads affect's stress level as `stressed`, a struggle surfacing
on one loop and not the other is a different state word from that hour on, and
the run is not reproducible by any consumer. A library tick that draws from
module `random` cannot be replayed, stepped or unit-tested against a fixed
outcome by anyone but the library itself. `LifeService(rng=...)` closes it,
additively and byte-identically by default; details under *Added*.

### Added

- **`SanitySystem` -- the one interior number that integrates and can break.**
  `aura_life.sanity` (exported from the facade beside the other engines) holds
  one scalar `sanity` in [0, 1] and the state word a consumer couples to:
  `STATES = ("sound", "strained", "fraying", "breaking", "broken")`, with the
  thresholds living in exactly one place (`state_for`) so a retune here cannot
  ripple outward. It starts at a per-persona *baseline* read from the definition
  -- more `struggles`, `character_defects` and `intrusive_thought_themes` mean a
  lower start and a higher *intensity* -- rather than at 1.0, so fragility is a
  lean the persona already carries and not a rule a wizard wrote. Severity is
  the blow's, intensity is the person's: `on_blow(kind, severity)` costs
  `severity x BLOW_WEIGHT[kind] x intensity` over a closed `BLOW_KINDS`
  (`grief`, `witnessed`, `did_harm`, `broke_value`, `rejected`, `neglect`,
  `concealment`); what a "grief" *is* stays the host's business.
  `on_recovery(kind, amount)` is the way up over a closed `RECOVERY_KINDS`
  (`rest`, `warmth`, `relief`, `answered`, `achieved`), scaled by a resilience
  of `1 / intensity` -- the same burdens that make a blow land harder make rest
  count for less. `tick(hours, *, stressed, concealment_load)` erodes while a
  stressor is live or a front is being kept up (scaled by shadow's
  `concealment_load`, so the mask costs something without the host writing a
  rule) and mends toward the baseline otherwise; the engine reads no clock and
  is told how much world time passed. Entering `breaking` queues one event the
  host drains with `drain_events()`; entering `broken` sets a terminal flag
  that only a reported recovery lifts. Replayable by construction: the single
  random draw is a baseline jitter at construction, taken only when an `rng`
  is injected -- `rng=None` is the default, so an existing seeded consumer's
  sequence is untouched.
- **`LifeService` wires it like the other engines.** Built from the definition
  (a new `sanity_rng=` keyword passes the one-draw rng through; `None` by
  default), exposed as `LifeService.sanity`, ticked from the energy tick with
  hours measured on the world clock the way energy measures them, reported in
  `get_status()["sanity"]` (number and word) and `export_inner_state()`,
  persisted in its own row (`life_sanity_state`) so a restarted host resumes the
  same number, word, flag and pending events. `on_sanity_blow()` and
  `on_sanity_recovery()` report through the service so the couplings apply at
  once; a host that calls the engine directly is coupled at the next tick.
- **Three couplings from the word to the library, applied by `LifeService`
  glue and never inside the engine, on a change of the word.** `strained` or
  worse: affect carries a stressor named `"sanity"`, cleared when `sound`
  again. A persona whose baseline already sits below `sound` (most shipped
  genre personas do) is *not* coupled for merely existing: the couplings fire
  when the word changes, so a persona that is never hit is byte-identical to
  one built before this engine existed. `fraying`
  or worse: shadow holds a restraint pull of `0.2` (inhibition down, the
  temptation bar for `intrusive_winning` down by the same), released when the
  word climbs back above. `breaking`: affect's regulation capacity collapses
  once, on the way in. The amounts are module constants on `life_service`
  (`SANITY_STRESS_SOURCE`, `SANITY_FRAYING_RESTRAINT_PRESSURE`,
  `SANITY_BREAKING_REGULATION_COLLAPSE`, `SANITY_STRESSED_LEVEL`); the words
  are the contract. "Stressed", for the tick, is affect's stress *level* at or
  above `SANITY_STRESSED_LEVEL` (0.2, the floor of affect's own stress
  description) -- not the `stress.sources` labels, which the service never
  resolves (`struggle:*`, `money worries`) and which would otherwise erode
  every persona with a struggle to `broken` in days without a single blow.
  The +0.05 the `"sanity"` stressor itself adds sits under that floor, so the
  state that opens it is not the state that keeps eroding. The word the
  couplings were last applied for travels in the sanity row, so a reload
  re-holds shadow's pull without firing the entry event twice.
- **`ShadowSystem.set_restraint_pressure(amount)`**, the smallest public seam
  that made the fraying coupling hold: shadow's tick recovers `inhibition`
  toward its baseline every call and recomputes `intrusive_winning` from
  scratch, so a one-shot nudge would have been a blip. The pull lowers the
  baseline the tick recovers toward and is applied to `inhibition` at once,
  both ways; `restraint_pressure` reads it back. It travels in shadow's row
  like the other baselines, because the drop is already in the stored
  `inhibition` and a load that re-applied it would lower restraint twice.
- **`tests/test_sanity.py`** (54 cases) proves the engine alone; and
  **`tests/test_sanity_wiring.py`** (18 cases) proves the seams: forty-eight
  simulated hours through the real energy tick leave an unstressed persona at
  its baseline and every other engine's status byte-identical to a service with
  the sanity tick disabled; each coupling by the word; hours on the world clock;
  a restart that resumes the number and re-applies the couplings without
  re-firing the entry event.
- **`SanitySystem` on the facade** -- `aura_life.__all__` goes from 117 names to
  118, and `tests/api_surface.json` is regenerated deliberately for that one
  addition; nothing was removed.
- **`LifeService(rng=None)` -- every draw on the energy-tick path comes from
  the injected `random.Random` when one is given.** `None`, the default, leaves
  every draw on the module-level `random` exactly as before, so an existing
  consumer, the golden parity fixture and the sanity wiring tests are
  byte-identical. Given, no draw on that path touches module `random`: two
  services built from one definition and two equal-seeded rngs, ticked on one
  scripted world clock, end 200 simulated hours later with every engine's
  status and both rng states identical. The rng is threaded into the engines
  that draw on the tick, each of which gains an additive `rng=None` keyword on
  its constructor and, where it has one, its `from_dict` (the reload path
  rebuilds engines from rows and would otherwise lose the seam):
  `IdentitySystem` (struggle, defect and tendency rolls), `DesireSystem`
  (five arousal draws in `tick`), `HabitationSystem` (the candle),
  `CognitiveSystem` (rumination replay and the monologue), `DriveSystem`
  (`roll_avoidance`), `CareerSystem`, `FinanceSystem`, `ErrandsSystem`,
  `MemoryTimeSystem` (`_check_nostalgia`), `LifeEventSystem` (the templated
  title). The service's own three draws on the path -- the struggle-to-
  rumination coin, the shareable priority, the life-trigger pick -- go through
  the same source. Draws *off* the energy tick are deliberately not routed:
  persona generation already takes `rng`; the daily planner, activities,
  chaos, the body's sleep and daily-health rolls, and the world's weather still
  read the module. `sanity_rng` keeps its own meaning (the one construction
  draw) but now defaults to `rng` when only `rng` is given, so one injected
  source replays the whole persona, jitter included; pass both to keep them
  apart. `aura_life.__all__` is unchanged; `tests/api_surface.json` is not
  touched.
- **`tests/test_tick_rng.py`** (5 cases): the 200-hour two-service replay; a
  sealed tick that asserts module `random`'s state never moves across
  `_on_energy_tick` while an rng is injected (the whole audit as one
  assertion); the seam surviving `reset_state()`; `rng=None` still reading the
  module (two runs under one module seed agree); and the `sanity_rng`
  defaulting rule.

- **Personas can be generated as female, male or nonbinary.**
  `aura_life.personas.genre_randomizer` gains `GENDERS`, a `PRONOUNS` token table
  and `render(text, gender, **extra)`; `GenreSpec` gains `name_pools` (keyed by
  `GENDERS`) and `build_genre_concept()` / `build_blended_concept()` gain a
  `gender` argument. `gender=None` draws one uniformly from the supplied rng; an
  unknown value raises `ValueError` naming the value and `GENDERS`. `PRONOUNS`
  carries verb-agreement forms (`be` / `have` / `s`) so a pronoun swap cannot
  produce "They's rebuilding".
- **A second pinned public surface.** `tests/genre_randomizer_surface.json` and
  two tests in `tests/test_api_surface.py` pin the genre_randomizer module — its
  public names, the builders' parameter lists, `GENDERS`, the `PRONOUNS` keys per
  gender, the `GenreSpec` fields and the registry keys. That module is not
  re-exported by the facade, so `tests/api_surface.json` (which pins
  `aura_life.__all__`) never covered it — yet Hollow imports it directly and this
  file documents its names as public. An unpinned de-facto public surface is how a
  breaking change ships unnoticed. One of the two tests compares against the
  regenerable snapshot; the other holds the v0.2.0 names as literals, so
  regenerating the snapshot cannot silently bless a *removal*.
- **`tests/test_gender_contract.py`** (65 cases): the back-compat surface, the
  behaviour change and the draw order, asserted rather than described. It pins the
  26 concept keys as a literal, proves `GenreSpec.name_pool` still reads as the
  female pool for all seven genres, proves the gender is the first draw and costs
  exactly one, and replays a seed in two fresh interpreters under different
  `PYTHONHASHSEED` values — because in-process equality would not catch a
  generator that depends on dict iteration order.
- **An injectable clock, carried by the world.**
  `aura_life.world.WorldEnvironment` gains a `now` constructor argument (a
  zero-argument callable returning a naive `datetime`) and a public
  `WorldEnvironment.now()` that every wall-clock read inside the class now goes
  through. `aura_life.energy.EnergySystem` gains the same `now` argument, a
  matching one on `EnergySystem.from_dict()`, and a read-only `EnergySystem.clock`
  property so a consumer can tell *which* clock is installed rather than infer it
  from behaviour — the same reason `hooks.provider_for()` exists for the hook
  registry. `LifeService` wires the two together: it hands `self._world.now` to
  the energy system at construction, at restore-from-SQLite and in
  `reset_state()`, so a consumer that injects one world on a simulated clock gets
  a simulated circadian rhythm across every agent sharing that world, with no
  per-engine wiring and no monkeypatching of `datetime`.
  The seam is a **method**, not only a constructor argument, because the consumer
  that needs it derives time from a tick counter and an epoch rather than holding
  a callable — it subclasses and overrides `now()`. `LifeService` binds
  `world.now` late, so an override reaches the energy engine too, and falls back
  to `datetime.now` when the injected world exposes no callable `now` (a host may
  hand in a duck-typed environment; an engine that loses its clock entirely is a
  worse failure than one reading the host's).
- **`tests/test_energy_clock.py`** (12 cases): the two properties the fix has to
  be worth — the same simulated clock gives the same energy twice, and the
  default still reads the wall clock — plus one case per clock read in
  `EnergySystem` (there were eight), the `from_dict` restore, the world-carries-it
  wiring through a real `LifeService`, the subclass-overrides-`now()` shape, and
  the duck-typed-world fallback. The determinism cases pin an **absolute**
  `hours_awake` as well as an equality, because `datetime.now()` moves in ~16ms
  steps on Windows and two wall-clock runs of a short script can agree by
  accident. Reverting either half of the fix (the `tick` clock read, or the
  `LifeService` wiring) fails 6 of the 12. The last case pins the naivety
  contract rather than leaving it as prose: an aware clock is self-consistent in
  memory and raises `TypeError` the moment it meets state restored from SQLite,
  which is why the migration note below says to use a naive one.
- **`PersonalityDefinition.from_concept(concept, **overrides)`** — the bridge
  from a generated concept to a `LifeService` definition. It keeps the keys that
  are fields, applies `overrides` last, and refuses an override that names no
  field. Three of the non-field keys are not dropped but **carried the way the
  profile loaders carry them**, because a definition built from a concept has
  to look like one built from `profile.db` to every reader downstream:
  `profile_db.load_profile` maps `age` to `age_range=str(age)` and puts
  `gender` and `age` into `appearance_details`, and `place_generation` reads
  `age_range` while the image path reads `appearance_details` — a converter
  that dropped them would hand those readers an empty string and no gender. The
  generator emits `theme_color` as `"#RRGGBB"`; the field is an ARGB `int` and
  both loaders parse the string before the definition exists, so `from_concept`
  runs the same parse (`#RRGGBB` / `#AARRGGBB`) and raises `TypeError` on
  anything else rather than inventing a default colour. The six remaining keys
  (`archetype`, `description`, `genre`, `goal`, `intensity`, `style_theme`,
  `tone_directive`) have no field and are dropped. Container fields are
  **shape-checked, not coerced**: a `str` where a `List[str]` belongs would
  iterate per character into the identity engine, so that raises `TypeError`
  naming the key; an `Optional` container accepts `None`.
  `tests/test_from_concept.py` (32 cases) converts every genre × gender and a
  blend, pins the override, wrong-shape, colour and age/gender behaviour, and —
  the one that matters — builds a real `LifeService` from a converted concept
  and asserts `core_traits`, the identity values, struggles, character defects,
  the intrusive thought pool and the `_is_ai` gate arrived, with the raw dict as
  the negative control: same concept, every one of those empty.
- **`register_genre(spec, *, replace=False)` and `unregister_genre(key)`.**
  `GENRE_REGISTRY` was a module-level dict a consumer could only extend by
  assigning into it, which means a spec missing a piece failed later, inside a
  builder, as an `IndexError` from `rng.choice` on an empty pool or a `KeyError`
  from `SHADOW_SCALE`. `register_genre` checks the spec up front and raises one
  `ValueError` naming everything that would fail (empty archetypes, a row that is
  not a 5-tuple, a gender with no names, no appearance template, an unknown
  `shadow_level`, a `shadow` that is not a `ShadowSeedSpec`, an empty
  `theme_colors` / `goal_pool` / `style_theme_pool`), and refuses to overwrite
  a registered key — a shipped genre must never be clobbered by accident —
  unless `replace=True` is passed. What goes into the registry is a **deep copy**
  of the spec: the natural way to author a genre is
  `dataclasses.replace(GENRE_REGISTRY["romance"], key="western", ...)`, and
  that shares every list and the `ShadowSeedSpec` with romance, so appending to
  the new genre's struggles would have edited a shipped genre in place. After
  registration neither the caller's object nor the shipped genre can be reached
  through the other. `unregister_genre` returns whether the key was there.
- **`build_cast(genre, n, rng=None, gender=None, balance=True)`** — `n` concepts
  with **distinct names**. Each builder draws `rng.choice(name_pool)`
  independently, so a consumer generating several personas gets collisions:
  measured over 300 seeds, 249 of 300 twelve-persona romance runs seated the
  same name twice, and some three times. A generator that cannot produce a
  distinct cast is incomplete, so this is the generator's problem to solve.
  Names are sampled without replacement inside each gender's pool and never
  reused across pools; asking for more than a pool holds raises `ValueError`
  naming the genre, the gender and both counts. With `gender=None` the cast is
  dealt as evenly as `n` allows (12 → 4/4/4, the remainder to rng-picked
  genders) in an rng-shuffled order; `balance=False` draws every member's gender
  independently, exactly as `n` calls to `build_genre_concept` would. Each member
  runs through the **same builder** as `build_genre_concept` with its name
  pre-assigned — nothing is patched into the dict afterwards — via a new
  trailing `name=None` keyword on the three builders. `build_genre_concept`
  itself still passes `name=None`, so its draw sequence is byte-identical and
  `tests/fixtures/persona_parity_golden.json` did not move.
  `tests/test_cast.py` (46 cases) pins the distinctness per genre, the 4/4/4
  split, the `balance=False` parity with sequential `build_genre_concept` calls,
  the over-pool message, determinism from a seed, that no prose field ever
  embeds the name (so a future template change cannot silently undo the seam),
  the register / unregister round-trip with its eleven refusal cases, and that
  a registered spec cannot corrupt the genre it was cloned from.

### Changed

- **`concept["gender"]` is drawn, where it used to be the constant `"female"`.**
  This is the behaviour change, and it is the reason for a minor rather than a
  patch bump: over 200 seeds on 0.2.0 the value was `{"female"}` for every genre;
  it is now `{"female", "male", "nonbinary"}`. A caller that never stored the
  gender because it could not vary, or that wrote female-assuming prose around the
  concept, must now pass `gender="female"` explicitly to keep its old output.
  `tests/test_gender_contract.py::test_default_gender_is_drawn_not_hardcoded_female`
  exists to fail if the old default is ever restored by accident.
- **The gender is drawn once, first, before any other draw** in both builders, so
  a seeded rng still replays a run deterministically — but the whole sequence after
  it has shifted by one draw. The draw order is part of the public contract and is
  stated in both docstrings. Consumers that hand in a shared world rng (Hollow
  passes `world.rng` and replays runs off the seed) will not reproduce a pre-0.3.0
  run from its seed *by default*: a run recorded on 0.2.0 is not replayable on
  0.3.0 unless the gender is supplied. An explicit `gender=` costs **no draw at
  all** — so passing `gender="female"` (and burning nothing) is what restores the
  v0.2.0 stream. Measured over 2,100 personas spanning all seven genres and 300
  seeds, `gender="female"` reproduces the v0.2.0 selection exactly: same
  archetype index, name, age, persona type, intensity, interests, theme colour,
  style theme and behavioural tendencies, with only the rewritten prose differing.
  Burning a `choice(GENDERS)` first does **not** restore the stream — it shifts it
  by one draw and reproduces only 493 of those 2,100.
  `tests/fixtures/persona_parity_golden.json` was regenerated deliberately with
  `PARITY_WRITE_GOLDEN=1`.
- `tests/api_surface.json` is **unchanged, and that is correct** — it pins
  `aura_life.__all__`, and none of the new names are exported from the package
  facade. It was not regenerated, and nothing was removed from it. The same holds
  for the clock seam: `EnergySystem` and `WorldEnvironment` are reached by
  submodule import (`from aura_life.energy import EnergySystem`) and are not in
  `__all__`, and neither snapshot pins signatures, so adding a trailing keyword
  argument moves neither file. Both were left alone deliberately; **nothing was
  removed from either.**
- **`tests/genre_randomizer_surface.json` gained exactly three names —
  `build_cast`, `register_genre`, `unregister_genre` — and lost none.** It was
  regenerated deliberately with `API_SURFACE_WRITE_SNAPSHOT=1`; the `signatures`
  block, `GENDERS`, the `PRONOUNS` keys, the `GenreSpec` fields and the registry
  keys are unchanged. `tests/api_surface.json` is still byte-identical to 0.2.0:
  `from_concept` is a method on a class that is not in `aura_life.__all__`.
- **`GenreSpec.builder` is now annotated `Callable[..., dict]`** and a custom
  builder is expected to accept a trailing `name=None`. A legacy three-argument
  builder still works for `build_genre_concept` — it is called with three
  arguments whenever no name is pre-assigned — but `build_cast` needs the fourth,
  and says so.
- **Every wall-clock read in `WorldEnvironment` and `EnergySystem` now goes
  through the world's clock rather than `datetime.now()` directly.** With no
  `now=` supplied that clock *is* `datetime.now`, so the behaviour is unchanged
  for every existing caller — but a subclass overriding `WorldEnvironment.now()`
  now changes the weather draw's notion of night, the `TimeOfDay` bucket, the
  season and the ambiance line as well as the energy curve, which is the point.
- `GenreSpec.name_pool` is retained and still reads as the female pool, and the
  flat `name_pool=[...]` constructor keyword still works. It stayed a field rather
  than becoming a property so that the keyword keeps binding; a genre that authors
  no pool for some gender falls back to the female one instead of raising.
- **All 126 archetypes across the seven genres were rewritten as pronoun-token
  prose**, and every genre now carries male and nonbinary name pools of the same
  length as its existing female pool (which is unchanged, and still in order). The
  seven `appearance_template`s take `{noun}` in place of the hardcoded "woman".
  Contractions were expanded rather than tokenised ("She's rebuilding" became
  "{Subj} {be} rebuilding"), and verbs that `{s}` cannot inflect (`does`,
  `processes`, `verifies`) were restructured, so no generated sentence reads
  "They's" or "They has".
- **24 archetype labels, occupations, traits and relationship titles were
  neutralised** where the *static* value was itself gendered — these fields are
  never passed through `render()`, so a token there would leak verbatim. Examples:
  `estranged daughter coming home` → `estranged child coming home`,
  `single mother carrying it all` → `single parent carrying it all`,
  `femme fatale who is tired of the role` → `fatal charmer who is tired of the
  role`, `club hostess` → `club host`, `girlfriend` → `partner`. Archetype count,
  order and meaning per genre are unchanged. Every other label, occupation, trait
  and title is byte-identical.
- `tests/fixtures/persona_parity_golden.json` was regenerated a second time, for
  the new prose. The gender, age, persona type and archetype selected by each
  pinned seed are unchanged — only the rendered text and the name differ, the
  latter because a male or nonbinary persona now draws from its own pool.

### Fixed

- **The energy tick's career, finance and errands engines tick on the world
  clock, not the host's.** `_on_energy_tick` called `self._career.tick()`,
  `self._finance.tick()` and `self._errands.tick()` bare, so each read
  `datetime.now()` -- while the catch-up path two thousand lines below already
  passed `now=timestamp`. `CareerSystem.tick` registers a workday off `now`'s
  date and hour and only then draws (`uniform`, up to two `random`, a `choice`),
  so with those draws on an injected `rng` the host wall clock decided how many
  values the stream gave up: a service ticked on a scripted world clock drew
  nothing from the career while the host sat before the shift start and four
  values a day once it moved past it. A run and its replay, hours apart on the
  host, consumed different counts from one seed -- the exact defect `rng=` was
  added to close, reopened by the clock. Measured in Hollow before the fix: two
  same-seed runs, one with the host clock frozen and one dragged an hour per
  simulated hour, diverged on day 0 as far as the weather; after it, identical
  over two days at seeds 5 and 11 and over ten days and twelve agents at
  seeds 5 and 20260827. All three ticks now take
  `now=self._world_clock()()`, which is `datetime.now` when no world clock is
  injected, so a consumer that injects nothing is byte-identical (210
  personas, 48 ticks each, `rng=None`, compared against the previous tree).
  `FinanceSystem` gains an additive `now=None` on its constructor and
  `from_dict` for the same reason: its "fire on the *next* month boundary"
  baseline was stamped from the host clock, and a tick measured on an injected
  world clock against a host-stamped baseline paid a month that never passed
  on the first hour. `tests/test_tick_rng.py` gains the pin: two services on
  one scripted world clock and two equal rngs, the host clock frozen for one
  and dragged an hour per simulated hour for the other, end at one rng state
  with one career; it fails with the bare ticks restored.
- **Six gendered strings in pools the archetype rewrite did not reach.** They
  were sampled straight into the concept without passing through `render()`, so
  they surfaced verbatim on a male or nonbinary persona: `horror.goal_pool`
  ("To make you hers completely"), `noir.core_values_pool` ("integrity on her own
  terms"), `noir.shadow.struggles` ("a hidden past she won't name"),
  `scifi.shadow.struggles` ("fear she doesn't belong"),
  `sexy.shadow.character_defects` ("uses seduction to get her way") and
  `sexy.shadow.intrusive_thought_themes` ("picturing exactly what she'd do to
  them"). The four that carry a real pronoun are now tokenised and the sampled
  results go through a private `_render_all()` helper; the other two were
  rewritten without the
  pronoun. **The module now contains no gendered word outside the `PRONOUNS`
  table itself** — `grep` for she/her/he/his/woman/girl/daughter/… over
  `genre_randomizer.py` returns only the five lines that define the table.
  `tests/test_gender_contract.py` closes the hole permanently: for every genre
  and every gender it generates personas and fails on any word belonging to
  another gender, over 1,600 personas spanning all seven genres, all three
  genders and three blends.
- **"chronic shame they buries under cruelty."** `_HORROR_STRUGGLES` hardcoded the
  third-person verb next to a `{subj}` token, so the horror and slasher tiers
  produced a broken sentence for every nonbinary persona — the exact failure the
  `{s}` token exists to prevent, in the one struggle string that predates it. It
  is now `chronic shame {subj} {have} buried under cruelty`, which agrees in all
  three genders.
- **Two nonbinary pronoun collisions in `_SEXY_THEME_POOLS`**, where a token
  referring to the persona sat in a sentence whose other party was already
  "they"/"them". `replaying the way they looked at {obj}` rendered as *"replaying
  the way they looked at them"* and `picturing exactly what {subj} would do to
  them` as *"picturing exactly what they would do to them"* — grammatical, but
  unreadable, and prose in the female original. They are now `replaying the way
  someone looked at {obj}` and `picturing exactly what to do to them`, the latter
  matching its twin in `sexy.shadow.intrusive_thought_themes` byte for byte.
- **The energy engine measured elapsed time against the host wall clock, so its
  answer depended on how long the process had been alive.** `EnergySystem.tick()`
  read `datetime.now()` to derive `hours_awake`, and seven other sites in the
  class did the same — `sleep()`, the `now_hour` fallbacks in `should_sleep()` /
  `is_asleep()` / `adjust_for_time()`, `hours_since_wake()`, the initial state and
  the `from_dict()` restore. `WorldEnvironment` had seven more. Past
  `MAX_HOURS_AWAKE` the fatigue penalty starts moving energy, so a persona
  rehydrated from a stored state into a fresh process and one carried by a
  server that had been up for hours reported different energy from *identical*
  state. Measured downstream, where energy feeds a score that can end an agent's
  life: same seed, same epoch, same roster, same directive sequence, differing
  only in process age — 2 of 8 seeds diverged inside 8 simulated days, and one
  ended at 3 deaths or 2 depending on nothing else. A run replayed from its own
  manifest was graded against a run that never happened. Nothing about that is
  specific to that consumer: an engine that reads the host clock cannot be
  simulated, replayed or unit-tested by anyone without freezing global state,
  which is why the fix is here and not in an adapter.

### Migrating from 0.2.0

- Nothing to do to keep *compiling*: no public name was removed, no `GenreSpec`
  field was removed, and `gender` was appended after `rng` in both builders, so
  positional calls still mean what they meant.
- To keep the old *output*, pass `gender="female"` explicitly. That also restores
  the old name pool, since the female pool is byte-identical to the v0.2.0
  `name_pool`.
- That single change keeps the old *seeded stream* too — **do not burn a draw**.
  An explicit `gender=` consumes nothing from the rng, so the builder's first draw
  is the persona-type coin exactly as it was on 0.2.0. Discarding a
  `rng.choice(GENDERS)` first is the one thing that breaks the replay.
- Downstream storage that defaults a missing gender to `"female"`
  (`ProfileDatabase` does, at the schema default and at two insert sites) is
  unaffected: a concept now always carries a resolved `gender`, so that default is
  only reached by a caller that supplies none.
- **The clock seam needs nothing done to it.** `now` was appended last to
  `WorldEnvironment.__init__`, `EnergySystem.__init__` and
  `EnergySystem.from_dict`, so positional calls still bind, and omitting it
  installs `datetime.now` — the behaviour every 0.2.0 caller already had. To opt
  in, pass `WorldEnvironment(now=my_clock)` and share that world with each
  `LifeService`; the energy engine follows without further wiring. A consumer
  whose time comes from a counter rather than a callable subclasses
  `WorldEnvironment` and overrides `now()` instead. Prefer a **naive** clock:
  an aware one is self-consistent while the state it built stays in memory, but
  the moment it meets state restored from SQLite — which is naive, as every
  persisted `datetime` in this library is — `tick()` raises `TypeError: can't
  subtract offset-naive and offset-aware datetimes`. This is the same naivety
  contract `persona_now`'s server-local fallback already carries, not a new rule.
- **If you pass a generated concept straight to `LifeService(definition=...)`,
  stop: it was never working.** Replace it with
  `LifeService(definition=PersonalityDefinition.from_concept(concept), ...)`.
  The service will look different afterwards — traits, values, struggles and the
  rest were silently empty before — which is the fix, not a regression. The
  definition you get back has `theme_color` as an ARGB `int`, `age_range` as
  the generated age and `appearance_details` holding `gender` and `age`, the
  same shape `load_profile` returns; nothing reads the `"#RRGGBB"` string off a
  definition, so nothing should notice.
- **A custom `GenreSpec.builder` needs a trailing `name=None` parameter only if
  you call `build_cast` on that genre.** `build_genre_concept` still calls a
  three-argument builder with three arguments. Registering through
  `register_genre` instead of assigning into `GENRE_REGISTRY` is recommended but
  not required; the dict is still there.

## [0.2.0] - 2026-08-27 — pre-publication hardening

Everything below landed **after** the `v0.1.0` tag and before the repository was
made public. The tag therefore does not contain these changes.

0.1.0's contract was "behaviour identical to the origin repo, no refactoring, and
defects get recorded rather than fixed" — that is what made the parity proof
meaningful. **That contract ends here.** A first public release that knowingly
ships a traversal sink, an SQL-injection sink and a public method that raises
unconditionally is not defensible, so an audit was run across five dimensions
(privacy, security, memory leaks, mock data, docs accuracy) and the approved
findings were fixed test-first.

### Security

- **Persona ids are validated at every id → path boundary.** A new internal
  `aura_life._safe_ids` supplies `safe_persona_id()` and `safe_join()`: an id must
  match `[a-z0-9_-]{1,64}` after lowercasing and is **rejected** with `ValueError`,
  never stripped or repaired, and the joined path is re-proved to sit under the
  resolved base directory. Previously `get_profile_db()`, `get_emotion_persistence()`
  and `get_owner_device_id()` interpolated the caller's id into a path with no
  validation at all, so a `..` segment escaped `data_dir` — the first two *created*
  files and directories outside it, and `get_owner_device_id()` was an arbitrary-read
  primitive that returned the `owner_device_id` (the multi-user isolation key) out of
  whatever `profile.db` the traversal landed on. Covered by
  `tests/test_persona_id_safety.py`.
- **`ProfileDatabase.update_field()` no longer builds SQL from caller input.** It
  interpolated `field` straight into `UPDATE profile_core SET {field} = ?`, so
  `field="name = 'x', owner_device_id"` rewrote the isolation column. The name must
  now appear in `PRAGMA table_info(profile_core)` and is quoted as an identifier —
  the same whitelist boundary the neighbouring `update_appearance()` already used.
  It was gated rather than deleted because it is an exported method of an exported
  class and this library was just extracted from a host whose call sites are not
  visible here.
- **The place kill switch fails closed.** `place_enabled` was read inside a `try`
  whose `except Exception` was a bare `pass`, so `HookNotConfigured` — the state of
  every host that has not registered `get_config`, i.e. the default — fell through
  and ran weather fetching and trip rolling as though the flag were on. An
  unreadable config now means "off".
- **The device-location store enforces the contract its docstring advertises.**
  `save_device_location()` rounds to `STORED_PRECISION` (2 decimals) and rejects
  out-of-range coordinates instead of writing whatever float pair it was handed.
  The docstring now separates what this module guarantees (a precision floor, no
  reverse-geocode, nothing but the point and a timestamp) from what the client is
  responsible for (the ~40 km fuzz, which happens outside this repo and cannot be
  verified here).

### Fixed

- **`start()` crashed instead of degrading when the `[scheduler]` extra was
  installed without a running event loop.** APScheduler's `AsyncIOScheduler`
  binds to the running loop at start time. The origin application always
  started the service from inside an async server, so this never surfaced
  there — but a synchronous host that installed the optional extra got
  `RuntimeError: no running event loop`, while a host that installed *nothing*
  got the documented "run manually" fallback. The stricter dependency produced
  the worse failure. `start()` now degrades to the same fallback and logs the
  real cause. Found by running the suite from a clean checkout with the extra
  installed — the development environment did not have `apscheduler`, so two
  thread-lifecycle tests had only ever exercised the no-scheduler path.

- **`persona_id` was silently discarded for any relative `db_path`.**
  `_persist_activity_emotions` derived the id with
  `db_parent if db_parent != "." else self._persona_id`, but
  `Path("mara.db").parent.name` is the empty string, not `"."` — and so is
  `Path("./mara.db").parent.name`, because `Path` normalises `./x` to `x`. The
  `"."` branch was therefore dead code for every relative and drive-root path:
  the explicit `persona_id` a caller passed was never consulted, and the warning
  claimed "no persona_id" about a service that had one. Activity emotions stopped
  persisting for those callers. Now guarded with `not in ("", ".")`.

- **`LifeService._datastore` was read three times and never assigned.**
  `add_calendar_entry()` and `get_upcoming_calendar_entries()` are public methods
  and both raised `AttributeError` on a fresh instance; `_scan_calendar_for_triggers()`
  runs on a tick behind a bare `except Exception`, so it failed **silently** —
  calendar `UPCOMING_EVENT` triggers, post-event `EMOTIONAL_CHECK_IN` check-ins and
  anniversary promotion **had never fired at all**, in any deployment, for the whole
  life of the code. `datastore` is now an optional constructor argument, appended
  last so no positional caller shifts; with none supplied the calendar lives in
  `db_path`, where `_init_database()` already created the table. Full write-up in
  `DEFERRED.md`; regression coverage in `tests/test_calendar_datastore.py`.
- **Activity emotions are no longer persisted under an invented persona id.** The
  fallback was a hardcoded character name from the origin application, so a
  `LifeService` that could not derive an id silently wrote another persona's file.
  It now skips the write and logs at `WARNING`.
- **Silent swallows narrowed.** Several `except Exception: pass` blocks around DB
  loads (identity values, behavioural tendencies, world location, places) are now
  `except sqlite3.OperationalError` for the genuine first-run-empty-table case, with
  anything else logged at `WARNING` with `exc_info=True`. The excitement-share
  trigger and the three user-model provider call sites, all previously swallowed
  with no log at any level, now log too — a broken host provider degraded three
  behaviours invisibly and forever.
- **Unbounded collections capped.** Every one of these grew for the life of the
  persona and was serialized to disk on each save: stress sources (10, with the two
  internal stressors pinned so the cap cannot become a stress ramp), goal history
  (20), anniversaries (20), secrets (10), plan revision notes (20), finished books
  (200, now deduped — the re-read fallback re-appended the same title forever),
  user-registered locations (100), `emotion_history` rows (500 per persona DB),
  `activity_logs` rows (500), shared `shareable_experiences` rows (90 days), and
  non-recurring `user_calendar` rows (30 days past the event). Caps are module or
  class constants, applied on write **and** on load, so a database written before
  the cap does not reload the whole leak on restart.
- **Teardown paths that did not exist.** `LifeScheduler.stop()` now calls
  `shutdown(wait=True)` and drops its reference, so in-flight ticks settle and the
  dead scheduler plus everything its jobs closed over becomes collectable;
  `LifeService.stop()` joins its two background threads (10 s each) *before*
  `_save_state()`, because both mutate engine state and saving first persisted a
  snapshot they then moved past; and the visual-description thread, which was
  spawned unguarded on every activity tick, is now a single handle that is skipped
  while one is alive.
- Stale internal comments removed: a "NO logic yet, schema only" placeholder sitting
  directly above the fully-implemented methods it described, private tracker ticket
  ids across nine sites, and a docstring naming an environment variable this package
  never reads.

### Added

- **`clear_persona_schedule()` joins the public facade** — `aura_life.__all__`
  goes from 116 names to 117. The rest of `schedule`'s names were already
  exported, so the teardown for a cache the facade hands you belongs beside them.
  `clear_emotion_persistence()` deliberately does *not* join: the `emotion`
  subpackage exports nothing through the facade, and one leaf without a trunk
  would be worse than a consistent subpackage import. See `DEFERRED.md`.

- `emotion_persistence.clear_emotion_persistence(persona_id=None)`,
  `schedule.clear_persona_schedule(persona_id=None)` and
  `MultiPersonalityManager.remove_personality(personality_id)` — teardown for three
  process-global caches that previously only grew. `remove_personality` stops the
  persona's `LifeService` before evicting it, so switching personas in a long-running
  host no longer leaks a whole simulation and its live tick jobs. None of the three
  is on `aura_life.__all__`; see `DEFERRED.md` for the v0.2 decision.
- `EmotionEngine(ocean_traits=...)` and
  `personality_config.set_default_languages(...)` / `get_default_languages()` — two
  values that were hardcoded to the origin application's character and locale are now
  inputs.
- Six test modules: `test_persona_id_safety`, `test_calendar_datastore`,
  `test_collection_caps`, `test_life_service_retention`,
  `test_life_service_failure_modes`, `test_emotion_history_retention`. The suite is
  **324 tests across 22 modules**, up from 129 across 13; the original 129 still pass
  unchanged.

### Changed

- **BREAKING — `PersonaSchedule` no longer ships three hardcoded characters.**
  The module previously dispatched on `persona_id == "florence" / "samantha" /
  "alice"` and carried those three characters' full authored weekly schedules —
  content belonging to the private application this library was extracted from,
  and dead weight for everyone else, since every other `persona_id` silently got
  an empty schedule. The dispatch and all three schedules are removed.
  `PersonaSchedule(persona_id, events=None)` is now a host-populated container
  with `add_event()`; empty is the documented default for every id. The module
  went from 355 lines to 218. Exported names are unchanged.

These are visible to a caller. None was avoidable while fixing the row above it.

- **`LifeService(db_path=...)` is effectively required.** The default was the
  relative string `"life.db"`, which put a SQLite file in whatever the process CWD
  happened to be and silently made two personas started from one directory share a
  database. It now defaults to `None` and resolves to
  `get_config().data_dir / <persona_id> / "life.db"`; with no host configured and no
  `db_path`, the constructor raises `ValueError` naming both options rather than
  scattering a file.
- **`LifeService.__init__` takes 19 parameters, not 18** — `datastore` is appended
  last, so every existing positional index is unchanged and `persona_id` is still
  the ninth.
- **`emotion_engine.TRAITS` is renamed `DEFAULT_OCEAN_TRAITS` and revalued** to a
  neutral 0.5-across profile. It was one specific character's OCEAN scores and it was
  the production default for every persona that omitted a baseline. A host that
  imported `TRAITS` breaks; a host that relied on the implicit baseline now gets a
  flat one.
- **`MultiPersonalityManager.current_id` returns `Optional[str]`**, initially `None`.
  It was initialized to a hardcoded persona id from the origin application, so a
  fresh manager resolved to a persona nobody had registered.
- **`GoalEngine.to_dict()["completed_count"]` / `["abandoned_count"]` are
  retained-history counts, not lifetime totals** — an unavoidable consequence of
  capping the history. A host displaying them as lifetime stats needs its own
  counter.
- **`ProfileDatabase.update_field()` raises `ValueError` on an unknown field**, where
  it previously raised `sqlite3.OperationalError`. A caller catching only
  `OperationalError` no longer catches.
- **Persona-id case is uniform.** `get_profile_db()` and `get_emotion_persistence()`
  now lowercase as `get_owner_device_id()` always did; the three previously
  disagreed, so `get_profile_db("Alice")` wrote `data/Alice/profile.db` while
  `get_owner_device_id("Alice")` read `data/alice/profile.db`. Ids generated inside
  the library were already lowercase, so real ids are unaffected.
- User-derived content is out of the logs. Calendar event names (documented as
  "extracted from conversation") were logged at `INFO` on add, on anniversary
  promotion and on post-event check-in; coordinates were logged at `INFO` and
  `WARNING` at three sites. Both now log an id, or nothing, at `DEBUG`.

## [0.1.0] - 2026-08-26

First release. aura-life is the life-simulation engine and persona pipeline
extracted from a larger private application by the same author, relicensed from
PolyForm Noncommercial 1.0.0 to Apache-2.0 by the copyright holder, who holds
sole copyright in both projects.

### Added

- **The life engine** — 31 subpackages, plus the top-level `life_service.py`,
  `models.py`, `schedule.py` and `conversation_session.py`. Energy and fatigue,
  daily planning, goals, activities, affect and mood, identity and character
  evolution, drives, cognition, behaviour and creative output, the body,
  habitation, money, career, errands, sustenance, transport, social life, skills,
  chaos events, life events, memory of time, expression, continuity, shadow,
  intimacy, location and places, prompt-context assembly, the tick scheduler, and a
  `WorldEnvironment` with weather, seasons, rooms and a clock. `README.md` carries
  the exhaustive one-line-per-subpackage index.
- **The persona pipeline** — `aura_life.personas`: genre randomisation, personality
  configuration, profile storage, place generation and appearance generation.
- Together: **32,088 lines across 82 modules and 32 subpackages**, importing
  standalone with no host application present.
- **A curated public facade.** `aura_life.__all__` exported **116 names** at 0.1.0 (117 as of 0.2.0): the 114
  the origin repo's own engine package exported — verified set-equal at extraction
  time, against a repository that is not published, so that half of the claim is not
  checkable here — plus `hooks` and `HookNotConfigured`. Everything else is
  re-exported from `aura_life.internals`, which is explicitly unstable.
- **`aura_life.hooks`** — a twelve-function registry that is the only seam between
  the engine and its host: `get_config`, `get_user_data_root`,
  `get_persona_datastore`, `get_image_service`, `resolve_outfit_for_context`,
  `get_schedule_phase`, `generate_and_update`, `get_weather_service`,
  `get_llm_service`, `geocode`, `resolve_timezone`, `persona_now`. The module
  imports `typing` and nothing else. An unconfigured hook raises
  `HookNotConfigured`, a subclass of `ImportError` — chosen so the `except
  ImportError` guards that already surrounded these call sites keep behaving exactly
  as they did.
- **`aura_life.defaults`** — a standard-library `persona_now`, installed on import.
  It is the only hook with a library default; without it every `activity` tick of a
  host-free `LifeService` died silently inside the scheduler. `install()` never
  overwrites an existing registration, so it cannot downgrade a host's clock.
  `hooks.provider_for(name)` was added so a consumer can tell a library default from
  a host registration (`is_configured` cannot).
- **Two per-persona providers** on `LifeService` — `user_model_provider` and
  `follow_up_provider`, both called as `provider(persona_id)` and both duck-typed.
  Omitting them is the supported standalone path; the engine skips adaptive
  cooldowns and proactive follow-up triggers.
- **A multi-instance guarantee.** `tests/test_multi_instance.py` runs three
  `LifeService` instances against one shared `WorldEnvironment`, in a process with no
  host application on `sys.path`, and asserts on the *log stream* rather than on "did not raise"
  — because `LifeScheduler.force_tick` swallows handler exceptions and only logs them
  at `ERROR`. Zero `ERROR` records, all five tick handlers completing, private state
  advancing, and a sentinel written through the public API landing in exactly one
  agent's database.
- **Tests relocated from the origin repo**: `test_affect`, `test_behavior`, `test_chaos`,
  `test_character_evolution`, `test_continuity`, `test_expression`,
  `test_life_events`, `test_memory_time` — the eight that exercised only the moved
  subsystems — plus `test_persona_parity` and its golden. New here:
  `test_multi_instance`, `test_hook_call_sites`, `test_api_surface`, `test_smoke`.
  13 modules, 129 tests.

### Behaviour

**Unchanged, and proven so.** A golden snapshot of twenty simulated ticks (inner
state, outer state and full status, clock frozen and RNG seeded) was captured
against the pre-extraction code *before a single line moved*, and the extracted
library reproduces it byte for byte. The persona-generation golden made the same
trip and matched byte for byte on arrival. Measured at extraction: **70 of the 78
moved modules are line-for-line identical to their originals**, the remainder
differing where imports had to be rewritten. Exactly one departure from byte
identity was made deliberately, in a `place_service.py` docstring, with parity
re-run immediately afterwards.

The two goldens then parted ways, and each is guarded by exactly one suite:

| Golden | Lives in | Run by |
|---|---|---|
| Life simulation (20 ticks) | the origin repo's test fixtures | the origin repo's parity suite |
| Persona generation | `tests/fixtures/persona_parity_golden.json` | this library — `tests/test_persona_parity.py` |

The persona golden moved here with the persona pipeline; it is **not** in the
origin repo's fixtures, and that suite does not guard persona generation.

Nothing was refactored on the way out. Where the extraction found a defect it
recorded it in `DEFERRED.md` rather than fixing it, because a fix would have
invalidated the proof. (The Unreleased section above is where that policy ends.)

### Not extracted: relationship modelling

Persona↔user relationship modelling — the user model, follow-up triggers, conflict
tracking, partner analysis, opinion evolution, conversation threads — stayed in the
origin application. 11 modules, 6,428 lines.

It is not a packaging preference; the code is **single-user by construction** and
would have to be redesigned, not moved. Three measurements, the last two quoted in
full so the argument does not depend on reading a private repository:

- **Zero `user_id` parameters.** Not one occurrence anywhere in that package. Every
  function signature assumes there is exactly one user and never says which.
- **A schema that enforces it.** The partner-analysis table is created as
  `id INTEGER PRIMARY KEY CHECK (id = 1)` — a single-row table. A second user is not
  a migration; it is a `CHECK` violation.
- **The only module-level singleton in the engine.** That same module holds
  `_instance: Optional[PartnerAnalysisService] = None`. It is the only `^_instance`
  anywhere in the origin engine, and there is no module-level singleton of that
  shape anywhere in the 32,088 extracted lines — which is precisely what lets N
  `LifeService` instances share one process.

aura-life's design target is N agents in one world. Shipping a subsystem whose
storage layer physically cannot hold a second relationship would have contradicted
that on day one. The seam is the two per-persona providers above: the host passes
its relationship services in, and a consumer that has no such concept passes
nothing.

### Known limitations

Carried into the release deliberately; see `README.md` and `DEFERRED.md`.

- No public `tick()`; driving the simulation uses `svc._scheduler.force_all_ticks()`
  and `WorldEnvironment` is not on the facade. Both are v0.2 candidates.
- Thirteen hook call sites are unguarded, two of them on the `world` tick path.
  `tests/test_hook_call_sites.py` is the authority for that census.
- `hooks.is_configured("persona_now")` is `True` with no host installed.
- `LifeService.start()` requires the `[scheduler]` extra and is a single-persona
  background-thread design.

[Unreleased]: https://github.com/Redrum624/aura-life/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/Redrum624/aura-life/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Redrum624/aura-life/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Redrum624/aura-life/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Redrum624/aura-life/releases/tag/v0.1.0
