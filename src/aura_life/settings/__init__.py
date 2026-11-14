"""Setting packs: the world a persona lives in (humanness program Task 9,
spec section 4.4).

A :class:`SettingSpec` holds every catalogue the engines draw a persona's life
from -- activities, places, what the people in her life do, what can happen
to her, what she wants, aims at and remembers, which days are holidays.
``LifeService`` resolves the persona's setting once, at construction, from
``PersonalityDefinition.setting`` (empty means :data:`DEFAULT_SETTING`) --
an unknown key raises ``ValueError`` there, naming it and every registered
key -- and every engine reads its catalogues from it.

:data:`DEFAULT_SETTING`, ``contemporary``, is registered on import: today's
catalogues, moved unchanged (:mod:`aura_life.settings.contemporary`). A host
adds its own with :func:`register_setting` (see
:mod:`aura_life.settings.spec` for the fields and which engine reads each).
"""

from .spec import (
    ACTIVITY_TAGS,
    ANCHOR_TAGS,
    COMMITMENT_TAGS,
    DEFAULT_SETTING,
    NEED_KEYS,
    PLAN_ONLY_TAGS,
    UNIVERSAL_TAGS,
    UNWELCOME_NPC_KINDS,
    CatchUpNarratives,
    HolidayCalendar,
    SettingSpec,
    get_setting,
    register_setting,
    unregister_setting,
)
from .contemporary import CONTEMPORARY

register_setting(CONTEMPORARY)

__all__ = [
    "SettingSpec",
    "CatchUpNarratives",
    "HolidayCalendar",
    "register_setting",
    "unregister_setting",
    "get_setting",
    "DEFAULT_SETTING",
    "ACTIVITY_TAGS",
    "UNIVERSAL_TAGS",
    "ANCHOR_TAGS",
    "PLAN_ONLY_TAGS",
    "COMMITMENT_TAGS",
    "NEED_KEYS",
    "UNWELCOME_NPC_KINDS",
]
