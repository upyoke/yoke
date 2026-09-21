"""QA-catalog event-registry rows split from the curated table.

Keeps :mod:`populate_registry_data_curated` under its authored-row
headroom while retraction and rebind stay explicit curated events:
discovery may not yet see those emitters on every control plane.
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

QA_REQUIREMENT_STATUS_EVENTS: Tuple[Tuple[str, str, str, str, str, str], ...] = (
    (
        "QARequirementTargetRebound",
        "lifecycle",
        "qa_lifecycle",
        "qa-db",
        "QA requirement rebound to the live same-environment declaration",
        "STATUS",
    ),
    (
        "QARequirementWaived",
        "lifecycle",
        "qa_lifecycle",
        "qa-db",
        "QA requirement waived with rationale",
        "STATUS",
    ),
)


__all__ = ["QA_REQUIREMENT_STATUS_EVENTS", "QA_RETRACT_EVENTS"]
