"""What a host reads from her exported state holds no unfilled slot (humanness Task 43).

``export_inner_state()`` gave a nostalgia memory as her setting writes it --
"a book {subj} read in one sitting on a rainy day" -- and a host that prints
the export (Aura's digest pass and its inner-life section) sent the token to
the model. Found when Aura's parity reference was re-recorded on this branch.
"""

import random
from datetime import datetime

from aura_life.life_service import LifeService
from aura_life.models import NostalgiaEvent
from aura_life.world import WorldEnvironment

T0 = datetime(2026, 10, 5, 12, 0)


def _service(tmp_path) -> LifeService:
    return LifeService(db_path=str(tmp_path / "nova.db"), persona_id="nova",
                       world_environment=WorldEnvironment(now=lambda: T0, seed=1), rng=random.Random(1))


def test_an_exported_nostalgia_memory_is_addressed_to_her(tmp_path):
    svc = _service(tmp_path)
    svc._memory_time._nostalgia_log.append(NostalgiaEvent(
        trigger="song", memory_reference="a book {subj} read in one sitting on a rainy day", intensity=0.6,
        timestamp=T0))
    exported = svc.export_inner_state()["memory_time"]["recent_nostalgia"]
    assert exported == {"trigger": "song", "memory": "a book you read in one sitting on a rainy day"}
    # the engine keeps its template: the rendering is the export's
    assert svc._memory_time.get_recent_nostalgia(1)[0].memory_reference.count("{subj}") == 1


def test_no_exported_text_holds_a_slot(tmp_path):
    import json
    svc = _service(tmp_path)
    svc._memory_time._nostalgia_log.append(NostalgiaEvent(
        trigger="smell", memory_reference="the summer {subj} spent at {poss} aunt's", intensity=0.6, timestamp=T0))
    dumped = json.dumps({"inner": svc.export_inner_state(), "outer": svc.export_outer_state()}, default=str)
    assert "{subj}" not in dumped and "{poss}" not in dumped and "{obj}" not in dumped
