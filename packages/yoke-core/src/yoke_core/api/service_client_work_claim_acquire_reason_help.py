"""Discoverable help text for ``claim-work --reason``.

Published as help text on ``claim-work --reason``. The vocabulary is
advisory — free-text values remain valid and land verbatim in
``work_claims.reason``; vocabulary matches classify into
``work_claims.reason_intent`` so Ouroboros and doctor aggregations never
second-guess prose. The vocabulary itself is domain-owned by
:mod:`yoke_core.domain.claim_chain_state` (the acquire write path
classifies against the same constant).

This module mirrors the shape of
:mod:`yoke_core.api.service_client_work_claim_reason_help` (which owns
the release-side halt-class vocabulary).
"""

from __future__ import annotations

from yoke_core.domain.claim_chain_state import ACQUIRE_INTENT_REASONS


CLAIM_WORK_DESCRIPTION = (
    "Acquire a typed work claim for the active session. Exactly one "
    "target shape is required:\n"
    "  --item YOK-N\n"
    "  --epic-task YOK-EPIC --task-num K\n"
    "  --process KEY [--project P]\n\n"
    "Worked example (canonical agent shape):\n"
    "  yoke claims work acquire --item YOK-N --reason draft-in-progress\n"
    "Operator-debug fallback inside a Yoke checkout:\n"
    "  python3 -m yoke_core.api.service_client claim-work \\\n"
    "    --item YOK-N --reason draft-in-progress\n"
)


def render_acquire_reason_help_text() -> str:
    """Multi-line help text enumerating canonical acquire-intent values.

    Renders one reason per line so argparse's default formatter cannot
    mid-word-wrap a hyphenated name. Free-text reasons remain valid —
    Ouroboros and doctor consumers treat unknown values as the
    catch-all bucket. Consumed under ``argparse.RawTextHelpFormatter``.
    """
    bullets = "\n".join(f"  - {r}" for r in ACQUIRE_INTENT_REASONS)
    return (
        "Optional intent tag recorded in WorkClaimed event context. "
        "Canonical values (free text remains valid):\n" + bullets
    )


__all__ = [
    "ACQUIRE_INTENT_REASONS",
    "CLAIM_WORK_DESCRIPTION",
    "render_acquire_reason_help_text",
]
