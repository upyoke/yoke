"""Canonical halt-class reason vocabulary for ``release-work-claim --help``.

Published as discoverable help text on ``release-work-claim --reason``.
Free-text reasons remain valid; the enum exists so Ouroboros and doctor
aggregations can classify the common cases. The canonical reason
DEFINITION lives in
:mod:`yoke_core.domain.release_intent_classification` and
:mod:`yoke_core.domain.idea_claim_events`; this module is a
help-text surface only.
"""

from __future__ import annotations


HALT_CLASS_REASONS: tuple[str, ...] = (
    "draft-in-progress",
    "idea-complete",
    "handoff-to-polish",
    "handoff-to-usher",
    "finalize-exit",
    "usher-halt-merge-failure",
    "usher-halt-deploy-infra-failure",
    "usher-halt-deploy-stage-failure",
    "usher-halt-unexpected",
    "rewrite-complete",
    "manual-inspection-complete",
)


def render_reason_help_text() -> str:
    """Multi-line help text enumerating canonical halt-class reasons.

    Renders one reason per line so argparse's default formatter cannot
    mid-word-wrap a long hyphenated name. Free-text reasons remain
    valid — Ouroboros and doctor consumers treat unknown values as the
    catch-all bucket. Consumed under ``argparse.RawTextHelpFormatter``.
    """
    bullets = "\n".join(f"  - {r}" for r in HALT_CLASS_REASONS)
    return (
        "Release reason. Canonical halt-class values (free text remains "
        "valid):\n" + bullets
    )


__all__ = ["HALT_CLASS_REASONS", "render_reason_help_text"]
