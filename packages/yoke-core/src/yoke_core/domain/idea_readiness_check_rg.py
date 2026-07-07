"""Single-purpose helper: detect whether the rg binary is on PATH.

Used by owner verification in
:mod:`yoke_core.domain.idea_readiness_check`. Lives in a sibling
module so the readiness-check file stays under the 350-line cap and so
tests have a stable monkeypatch target for missing-rg scenarios.
"""

from __future__ import annotations

import logging
import shutil
from typing import Optional

_logger = logging.getLogger(__name__)
_warning_emitted = False


def rg_available() -> Optional[str]:
    """Return the resolved ``rg`` path, or ``None`` if rg is not on PATH.

    Emits one ``WARNING`` log on the first miss per process and stays
    silent on subsequent misses, so callers that hit the missing branch
    repeatedly do not spam logs.
    """
    global _warning_emitted
    rg_path = shutil.which("rg")
    if rg_path is None and not _warning_emitted:
        _logger.warning(
            "rg not on PATH; owner-verification skipped"
        )
        _warning_emitted = True
    return rg_path
