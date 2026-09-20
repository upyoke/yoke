"""QA-catalog event-registry rows split from the curated table.

Keeps :mod:`populate_registry_data_curated` under its authored-row
headroom while retraction stays an explicit curated event: discovery
may not yet see the emitter on every control plane.
"""

from __future__ import annotations

from typing import Tuple

QA_RETRACT_EVENTS: Tuple[Tuple[str, str, str, str, str, str], ...] = (
    (
        "QARequirementRetracted",
        "lifecycle",
        "qa_lifecycle",
        "qa-db",
        "QA requirement retired because its item plan attachment was retracted",
        "STATUS",
    ),
)


__all__ = ["QA_RETRACT_EVENTS"]
