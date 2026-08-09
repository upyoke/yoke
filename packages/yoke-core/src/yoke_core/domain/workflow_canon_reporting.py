"""How one universe's stored definitions stand against the published canon.

Two reporters over the same relationship: where a single stored version's
content came from, and where the universe's selected definition stands overall.
Both answer by digest against the canon rather than by version number, because
a universe numbers its own history and that number says nothing about which
published generation a row holds.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.builtin_workflow_canon import (
    canon_generations,
    recognize,
)


def version_provenance(version_row) -> dict:
    """Where a stored version's content came from, as the dashboard shows it.

    A universe's version numbers are its own sequence positions, so the number
    alone says nothing about which published generation a row holds. Matching
    the digest against the canon answers that, and the caller compares
    ``canon_version`` with the local number to see that a universe adopted a
    generation on its own schedule -- normal, and not drift.

    Only built-in workflows have a canon. A workflow authored in this universe
    is local by definition, not by failing to be recognized.
    """
    generation = recognize(
        str(version_row["workflow_id"]), str(version_row["definition_digest"])
    )
    if generation is not None:
        return {"kind": "canon", "canon_version": generation.canon_version}
    baseline = version_row.get("derived_from_canon_version")
    return {
        "kind": "local",
        "derived_from_canon_version": None if baseline is None else int(baseline),
    }


def workflow_canon_status(version_row: Mapping[str, Any]) -> dict:
    """Where this universe's current definition stands against the canon.

    Four states, along two independent questions: is this definition Yoke's or
    this universe's own, and has Yoke published anything since. A customized
    definition sitting on the newest generation needs nothing; one whose
    baseline has been overtaken needs a merge, not an overwrite, and saying so
    requires the recorded baseline rather than a guess.

    The stored ``follow`` setting and the last automatic adoption ride along,
    because both are facts about this same relationship: a reader deciding what
    to show about an update needs to know whether the next one arrives by
    itself. Neither appears where there is no canon to stand against, since a
    following setting for a workflow nothing publishes describes nothing.
    """
    workflow_id = str(version_row["workflow_id"])
    generations = canon_generations(workflow_id)
    if str(version_row["source"]) != "built_in" or not generations:
        return {"state": "not_applicable"}
    newest = generations[-1]
    adopted_from = version_row.get("canon_adopted_from_version")
    status = {
        "latest_canon_version": newest.canon_version,
        "follow": str(version_row.get("canon_follow") or "auto"),
        "adopted_from_version": (
            None if adopted_from is None else int(adopted_from)
        ),
    }
    current = recognize(workflow_id, str(version_row["definition_digest"]))
    if current is not None:
        status["current_canon_version"] = current.canon_version
        status["state"] = (
            "up_to_date"
            if current.canon_version == newest.canon_version
            else "update_available"
        )
        return status
    baseline = version_row.get("derived_from_canon_version")
    baseline = None if baseline is None else int(baseline)
    status["derived_from_canon_version"] = baseline
    # An unknown baseline reports as plain customization. Claiming an update
    # is available would assert a relationship to the canon that was never
    # recorded, and the whole point of the baseline is to stop guessing it.
    status["state"] = (
        "customized_update_available"
        if baseline is not None and baseline < newest.canon_version
        else "customized"
    )
    return status


__all__ = ["version_provenance", "workflow_canon_status"]
