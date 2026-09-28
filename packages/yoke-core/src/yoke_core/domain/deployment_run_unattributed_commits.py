"""The refusal for carried commits no item receipt or release output claims.

A count tells an operator nothing they can act on. The two causes this
refusal has look identical from a count and need opposite repairs: an item's
own commit its receipt did not record belongs on that item, while a commit no
backlog item owns — a direct push, genuinely unrelated code — needs a
deliberate decision about how this run treats it. So the refusal names every
commit with its subject, which is what lets the operator tell them apart, and
states the repair for each.
"""

from __future__ import annotations

from typing import Any, Mapping


def unattributed_commits_refusal(
    run_id: str, project_set: Mapping[str, Any],
) -> str:
    """Name ``project_set``'s unattributed commits and both repairs, or ``''``."""
    bare = [str(value) for value in project_set.get("commits") or []]
    if not bare:
        return ""
    subjects = project_set.get("commit_subjects") or {}
    project = str(project_set.get("project") or "").strip()
    where = f" in project {project}" if project else ""
    listing = "\n".join(
        f"  {sha} {str(subjects.get(sha) or '(subject unavailable)')}"
        for sha in bare
    )
    return (
        f"deployment run {run_id!r} carries {len(bare)} commit(s){where} that "
        "no item merge receipt or recorded release output claims:\n"
        f"{listing}\n"
        "A commit that is an item's own work belongs on that item's receipt: "
        "yoke merge-receipt commits attest PREFIX-N --commit SHA "
        "[--commit SHA ...] --reason \"<why>\". "
        "For a commit no backlog item owns, record how this run treats it: "
        f"yoke deployment-runs update {run_id} composition_resolution "
        "\"<treatment>\". Then retry."
    )


__all__ = ["unattributed_commits_refusal"]
