"""The machine card's harness families stay the engine's own vocabulary.

The card is drawn in the browser, so it carries its own copy of the family
list the engine stores in ``harness_sessions.executor``. A family added or
renamed in the engine and not here would leave one machine card heading a
provider's meters with an identity the control plane no longer uses, which
no runtime error would ever surface.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from yoke_contracts.executor_labels import CANONICAL_HARNESS_IDS

METERS_MODULE = (
    Path(__file__).resolve().parents[2]
    / "packages/yoke-core/src/yoke_core/ui/static/universe_machines_meters.js"
)
_DECLARATION = re.compile(r"export const CANONICAL_HARNESS_IDS = (?P<ids>\[[^\]]*\]);")


def test_card_families_match_the_engine_vocabulary() -> None:
    declared = _DECLARATION.search(METERS_MODULE.read_text(encoding="utf-8"))
    assert declared is not None, (
        f"{METERS_MODULE.name} must declare CANONICAL_HARNESS_IDS as one "
        "array literal; the machine card reads its family headings from it"
    )
    assert tuple(json.loads(declared.group("ids"))) == CANONICAL_HARNESS_IDS
