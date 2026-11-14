"""The universal activities: what every setting can do whatever its pack
holds (ruling T9-R6).

A setting none of whose own activities carries one of
:data:`~aura_life.settings.spec.UNIVERSAL_TAGS` gets the matching activity
below appended to its catalogue
(:meth:`~aura_life.settings.SettingSpec.resolved_activities`), so a pack of
three activities still sleeps, naps and eats. The contemporary pack tags its
own sleeping, napping and meals, so it gets none of them.

``sleeping`` and ``napping`` are the contemporary pack's own definitions
(copied, so nothing a setting does to them reaches the pack). ``having a
meal`` is the library's; its values and where each comes from are documented
on :data:`HAVING_A_MEAL`.
"""

import copy
from typing import Dict

from ..models import Activity, ActivityCategory, TimeOfDay, Weather
from .contemporary import ACTIVITIES as _CONTEMPORARY_ACTIVITIES
from .contemporary import CATCHUP_ACTIVITY_NARRATIVES, CATCHUP_MIDDAY_NARRATIVES


def _contemporary(name: str) -> Activity:
    return copy.deepcopy(next(a for a in _CONTEMPORARY_ACTIVITIES if a.name == name))


#: The fallback meal. It is tagged "meal", which is what relieves hunger
#: (``SustenanceSystem.on_activity``; ruling T9-R8). Values:
#:
#: - category REST, narratives: what the catch-up backfill already says of a
#:   meal -- its midday "cooking" entry is REST
#:   (``LifeService._get_activity_for_hour``), and the two lines are
#:   ``CATCHUP_MIDDAY_NARRATIVES[1]`` and
#:   ``CATCHUP_ACTIVITY_NARRATIVES["cooking a meal"]``;
#: - times, weather and place: the contemporary "cooking a meal"'s;
#: - emotions: the contemporary "cooking a meal"'s, less "creative";
#: - no thoughts (``ActivityEngine.execute_activity`` then draws none);
#: - tags "meal", and "physical" (a body eats: an AI persona's plan leaves
#:   it out, as it left out the contemporary meals);
#: - chosen here (Task 9 fix round report): energy cost 0.0 and minimum
#:   energy 0.0 -- she can always eat, even exhausted -- and 30 minutes
#:   (read only for a nap's length, never for a meal's);
#: - what she says when it does not go well (Task 14): the library's own
#:   lines, in the contemporary meals' voice -- a meal that goes wrong still
#:   feeds her (it is still tagged "meal"), so each one has her eat something.
HAVING_A_MEAL = Activity(
    name="having a meal",
    category=ActivityCategory.REST,
    energy_cost=0.0,
    min_energy=0.0,
    duration_minutes=30,
    preferred_times=[TimeOfDay.MORNING, TimeOfDay.AFTERNOON, TimeOfDay.EVENING],
    preferred_weather=list(Weather),
    suitable_locations=["home"],
    narrative_templates=[CATCHUP_MIDDAY_NARRATIVES[1], CATCHUP_ACTIVITY_NARRATIVES["cooking a meal"]],
    thought_possibilities=[],
    emotion_effects={"satisfied": 0.1, "content": 0.1},
    outcomes={
        "mixed": [
            "The meal was nothing special",
            "Ate in a hurry",
        ],
        "fail": [
            "The food came out cold and bland, ate some of it anyway",
            "Burned the meal and ate what {subj} could",
        ],
    },
    tags=frozenset({"meal", "physical"}),
)

#: Universal tag -> the activity a setting without it gets, in the order they
#: are appended.
UNIVERSAL_ACTIVITIES: Dict[str, Activity] = {
    "sleep": _contemporary("sleeping"),
    "nap": _contemporary("napping"),
    "meal": HAVING_A_MEAL,
}
