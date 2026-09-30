"""Where a Command case runs: its lane, an explicit tree, or the candidate.

A deployment-run case answers for the revision its run deployed
(:mod:`yoke_core.domain.qa_case_tree_binding_scope`), not for whatever the
project checkout happens to hold. Running it in that checkout breaks as soon
as the default branch moves past the release, and every recovery an owner can
reach is closed: the run driver's own pinned tree belongs to another session,
and a member whose item already finished cannot claim anything to re-run.

So the runner pins the tree itself. With no explicit ``--checkout-path``, a
deployment case runs in a disposable checkout of the case's own project
cloned at the candidate revision, outside every lane and shared tree, and
removed once the case has recorded its verdict. The clone shares the project
checkout's object store, so it costs a checkout rather than a download; a
revision that checkout lacks is fetched from ``origin`` first.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping, Optional

from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.qa_case_tree_binding_scope import (
    candidate_revision,
    session_lane_binds_case,
)
from yoke_core.domain.worktree_paths import _run, captured_process_detail
from yoke_core.domain.worktree_provision import GIT_WORKTREE_ADD_TIMEOUT_SECONDS

#: Name prefix of every candidate checkout, so a leftover is recognizable.
CANDIDATE_CHECKOUT_PREFIX = "yoke-qa-candidate-"
_FETCH_TIMEOUT_SECONDS = 120


def _commit(repo: Path, revision: str) -> str:
    resolved = _run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{revision}^{{commit}}"]
    )
    return (resolved.stdout or "").strip() if resolved.returncode == 0 else ""


def _candidate_commit(source: Path, revision: str, subject: str) -> str:
    sha = _commit(source, revision)
    if sha:
        return sha
    fetched = _run(
        ["git", "-C", str(source), "fetch", "--quiet", "origin", revision],
        timeout=_FETCH_TIMEOUT_SECONDS,
    )
    sha = _commit(source, revision)
    if sha:
        return sha
    raise QaCaseExecutionError(
        f"CANDIDATE CHECKOUT REFUSAL: {subject} deployed {revision}, which is "
        f"not a commit in '{source}' and could not be fetched from origin: "
        f"{captured_process_detail(fetched)}.\n"
        f'Fetch it with `git -C "{source}" fetch origin {revision}`, then '
        "re-run the same command."
    )


def _source_checkout(case: Mapping[str, Any]) -> Path:
    from yoke_core.domain.project_checkout_locations import checkout_for_project_id

    source = checkout_for_project_id(case.get("project_id"))
    if source is None or not source.is_dir():
        raise QaCaseExecutionError(
            "CANDIDATE CHECKOUT REFUSAL: no local checkout is mapped for "
            f"project {case.get('project')!r}, so its deployed candidate cannot "
            "be materialized. Register it with `yoke project register "
            "<checkout> --project-id <id>`, then re-run the same command."
        )
    return source


@contextmanager
def candidate_checkout(case: Mapping[str, Any]) -> Iterator[Path]:
    """Yield a disposable checkout at the case's candidate; remove it after."""
    subject = f"deployment run {case.get('deployment_run_id')!r}"
    revision = candidate_revision(case)
    if not revision:
        raise QaCaseExecutionError(
            f"CANDIDATE CHECKOUT REFUSAL: {subject} records no candidate "
            "revision for this case, so which code its verdict covers cannot "
            "be established. Inspect the case's execution target with "
            f"`yoke qa requirement get --requirement-id {case.get('requirement_id')}`."
        )
    source = _source_checkout(case)
    sha = _candidate_commit(source, revision, subject)
    root = Path(tempfile.mkdtemp(prefix=f"{CANDIDATE_CHECKOUT_PREFIX}{sha[:12]}-"))
    try:
        for step in (
            [
                "git",
                "clone",
                "--quiet",
                "--shared",
                "--no-checkout",
                str(source),
                str(root),
            ],
            ["git", "-C", str(root), "checkout", "--quiet", "--detach", sha],
        ):
            done = _run(step, timeout=GIT_WORKTREE_ADD_TIMEOUT_SECONDS)
            if done.returncode != 0:
                raise QaCaseExecutionError(
                    f"CANDIDATE CHECKOUT REFUSAL: materializing {subject}'s "
                    f"candidate {sha[:12]} from '{source}' failed at "
                    f"`{' '.join(step[:3])}`: {captured_process_detail(done)}. "
                    "Nothing was run or recorded; repair that checkout and "
                    "re-run the same command."
                )
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@contextmanager
def case_checkout(
    case: Mapping[str, Any], checkout_path: Optional[str | Path]
) -> Iterator[Path]:
    """Yield the tree a Command case runs in.

    An explicit path always wins and is judged by the tree binding like any
    other. Otherwise a case about the session's lane runs in that lane, and a
    deployment case runs in a disposable checkout at its run's candidate.
    """
    if checkout_path is not None:
        yield Path(checkout_path).resolve()
    elif session_lane_binds_case(case):
        from yoke_core.domain.qa_case_execution import _execution_checkout

        yield _execution_checkout(dict(case))
    else:
        with candidate_checkout(case) as root:
            yield root


__all__ = ["CANDIDATE_CHECKOUT_PREFIX", "candidate_checkout", "case_checkout"]
