"""The refusal for carried commits no item receipt or release output claims.

A count tells an operator nothing they can act on. Name every commit with its
subject so the operator can identify its owning item and repair that receipt.
Creation rolls back a refused run, so recovery must not require that run.
"""

from __future__ import annotations

from shlex import quote
from typing import Any, Mapping


def unattributed_commits_refusal(
    run_id: str,
    project_set: Mapping[str, Any],
) -> str:
    """Name unattributed commits and a receipt repair independent of the run."""
    bare = [str(value) for value in project_set.get("commits") or []]
    if not bare:
        return ""
    subjects = project_set.get("commit_subjects") or {}
    project = str(project_set.get("project") or "").strip()
    where = f" in project {project}" if project else ""
    listing = "\n".join(
        f"  {sha} {str(subjects.get(sha) or '(subject unavailable)')}" for sha in bare
    )
    commits = " ".join(f"--commit {quote(sha)}" for sha in bare)
    project_arg = f" --project {quote(project)}" if project else ""
    return (
        f"deployment run {run_id!r} carries {len(bare)} commit(s){where} that "
        "no item merge receipt or recorded release output claims:\n"
        f"{listing}\n"
        "Identify the owning landed item from the subjects, replace PREFIX-N "
        "with its ref, and explain ownership in the reason. If owners differ, "
        "attest only each item's commits to that item. Recovery:\n"
        f"yoke merge-receipt commits attest PREFIX-N {commits}{project_arg} "
        '--reason "<why these commits are this item\'s work>"\n'
        "Then retry the refused creation or start. Refused creation leaves no "
        "run to update. If no item owns a commit, resolve ownership before retrying."
    )


__all__ = ["unattributed_commits_refusal"]
