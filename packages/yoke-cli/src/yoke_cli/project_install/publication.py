"""Publish the installer's commit to the project's remote, or say why not.

``yoke project install`` / ``refresh`` write the operating layer and commit
the paths they own. A commit that never leaves the machine leaves every other
clone of the project — and every teammate's next install — reconciling the
same generated content by hand, so this module finishes the job: it pushes
that commit to the branch it belongs on, and where the branch does not accept
a direct push it proposes the same commit for review instead.

What it will not do is report success it did not achieve. Every outcome is
named, and the ones that leave the layer committed locally but unpublished
carry the commit and the exact recovery command, because an install that
prints a clean report while the remote never saw it is the failure mode this
module exists to remove.

Three outcomes are deliberate rather than failures: an explicit
``--no-commit`` run has nothing to publish, a checkout with no remote is a
local-only project, and a source-dev/admin local-source apply publishes
nothing by design.

Two things it refuses to do on the operator's behalf. It never force-pushes,
and it never publishes a commit the installer did not write: a default branch
carrying the operator's own unpushed work is reported with its recovery
rather than pushed, because "publish the installed layer" is not permission
to publish everything else sitting on the branch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from yoke_cli.project_install import publication_outcome as outcome_layer
from yoke_cli.project_install import publication_pull_request as proposal_layer
from yoke_cli.project_install import publication_reconcile as reconcile_layer

MAX_PUSH_ATTEMPTS = 2


def publish_installed_layer(
    repo_root: Path,
    report: dict[str, Any],
    *,
    commit: dict[str, Any],
    default_branch: str,
    operation: str,
    regenerate: Callable[[], dict[str, Any]] | None = None,
    project_slug: str | None = None,
    publish: bool = True,
) -> dict[str, Any]:
    """Push (or propose) the installer commit, and name the outcome.

    ``commit`` is the result this run's commit step returned. ``regenerate``
    re-runs the bundle write so a remote that advanced mid-run is reconciled
    by regeneration rather than by a merge preference; a caller without a
    bundle in hand passes ``None`` and gets the pending outcome with its
    recovery instead of a reconcile. When a reconcile does replace the
    commit, ``report`` is updated with the regenerated content so the caller
    reports what it actually published.
    """
    if not publish:
        return {"status": outcome_layer.SKIPPED,
                "reason": outcome_layer.DISABLED_REASON}
    if commit.get("status") == outcome_layer.SKIPPED:
        return {
            "status": outcome_layer.SKIPPED,
            "reason": str(commit.get("reason") or "nothing was committed"),
        }
    branch = str(default_branch or "").strip()
    if not branch:
        return {
            "status": outcome_layer.SKIPPED,
            "reason": "no publish branch was resolved for this checkout",
        }
    remote = reconcile_layer.publish_remote(repo_root, branch)
    if remote is None:
        return {"status": outcome_layer.SKIPPED,
                "reason": outcome_layer.LOCAL_ONLY_REASON}
    return _publish_to_remote(
        repo_root,
        report,
        branch=branch,
        remote=remote,
        operation=operation,
        regenerate=regenerate,
        project_slug=project_slug,
    )


def publish_onboarded_layer(
    repo_root: Path,
    report: dict[str, Any],
    *,
    default_branch: str,
    project_slug: str | None = None,
) -> dict[str, Any]:
    """Publish an onboarding install's commit once its credentials are set.

    Onboarding configures the checkout's credential helper after the install
    writes, so the install defers publication to here rather than pushing
    through credentials that do not exist yet.
    """
    return publish_installed_layer(
        repo_root,
        report,
        commit=report.get("commit") or {},
        default_branch=default_branch,
        operation="install",
        project_slug=project_slug,
    )


def _publish_to_remote(
    repo_root: Path,
    report: dict[str, Any],
    *,
    branch: str,
    remote: str,
    operation: str,
    regenerate: Callable[[], dict[str, Any]] | None,
    project_slug: str | None,
) -> dict[str, Any]:
    reconciled: dict[str, Any] | None = None
    for attempt in range(1, MAX_PUSH_ATTEMPTS + 1):
        eligible = _push_eligibility(repo_root, branch=branch, remote=remote)
        if eligible["status"] != outcome_layer.ELIGIBLE:
            return outcome_layer.with_reconcile(eligible, reconciled)
        pushed = reconcile_layer.network_git(
            repo_root, "push", remote, f"{branch}:refs/heads/{branch}",
        )
        if pushed.returncode == 0:
            return outcome_layer.with_reconcile(
                {
                    "status": outcome_layer.PUBLISHED,
                    "remote": remote,
                    "branch": branch,
                    "commit": outcome_layer.head(repo_root),
                },
                reconciled,
            )
        detail = (pushed.stderr.strip() or pushed.stdout.strip()).strip()
        failure = outcome_layer.classify_push_failure(detail)
        if failure == outcome_layer.PROTECTED:
            return outcome_layer.with_reconcile(
                proposal_layer.propose_pull_request(
                    repo_root,
                    remote=remote,
                    branch=branch,
                    detail=detail,
                    project_slug=project_slug,
                ),
                reconciled,
            )
        if failure == outcome_layer.STALE and attempt < MAX_PUSH_ATTEMPTS:
            outcome, reconciled = _reconcile_stale_branch(
                repo_root,
                report,
                branch=branch,
                remote=remote,
                operation=operation,
                regenerate=regenerate,
                detail=detail,
            )
            if outcome is not None:
                return outcome_layer.with_reconcile(outcome, reconciled)
            continue
        return outcome_layer.with_reconcile(
            outcome_layer.pending(
                repo_root,
                remote=remote,
                branch=branch,
                detail=detail,
                recovery=outcome_layer.push_recovery(
                    failure, remote=remote, branch=branch,
                ),
            ),
            reconciled,
        )
    return outcome_layer.with_reconcile(
        outcome_layer.pending(
            repo_root,
            remote=remote,
            branch=branch,
            detail=f"the remote refused the push {MAX_PUSH_ATTEMPTS} times",
            recovery=outcome_layer.push_recovery(
                outcome_layer.FAILED, remote=remote, branch=branch,
            ),
        ),
        reconciled,
    )


def _reconcile_stale_branch(
    repo_root: Path,
    report: dict[str, Any],
    *,
    branch: str,
    remote: str,
    operation: str,
    regenerate: Callable[[], dict[str, Any]] | None,
    detail: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Move onto the advanced remote tip and regenerate, or name the blocker.

    Returns ``(None, reconcile_record)`` when the caller should retry the
    push against the regenerated commit, and ``(outcome, record)`` when the
    reconcile itself decided the result.
    """
    if regenerate is None:
        return (
            outcome_layer.pending(
                repo_root,
                remote=remote,
                branch=branch,
                detail=detail,
                recovery=(
                    f"{remote}/{branch} advanced while this run was writing. "
                    "recipe: re-run the install, which regenerates the layer "
                    "on the updated revision"
                ),
            ),
            None,
        )
    record = reconcile_layer.reconcile_by_regeneration(
        repo_root,
        branch=branch,
        remote=remote,
        regenerate=regenerate,
        operation=operation,
    )
    status = record.get("status")
    if status == "regenerated":
        report.update(record.pop("regenerated_report"))
        report["commit"] = record["commit"]
        return None, record
    if status == "already_published":
        return (
            outcome_layer.already_published(
                remote=remote,
                branch=branch,
                commit=outcome_layer.head(repo_root),
            ),
            record,
        )
    return (
        outcome_layer.pending(
            repo_root,
            remote=remote,
            branch=branch,
            detail=detail,
            recovery=str(
                record.get("recovery")
                or f"reconcile {branch} with {remote}/{branch}, then re-run "
                "the install to publish the layer"
            ),
        ),
        record,
    )


def _push_eligibility(
    repo_root: Path, *, branch: str, remote: str,
) -> dict[str, Any]:
    """Refuse to publish anything but the installer's own unpushed commits."""
    state = reconcile_layer.read_remote_state(
        repo_root, branch=branch, remote=remote,
    )
    if state.status == reconcile_layer.CURRENT:
        return outcome_layer.already_published(
            remote=remote, branch=branch, commit=state.local_sha,
        )
    if state.status == reconcile_layer.BEHIND:
        return outcome_layer.already_published(
            remote=remote,
            branch=branch,
            commit=state.local_sha,
            detail=f"{remote}/{branch} already carries this checkout's commits",
        )
    if state.status == reconcile_layer.FETCH_FAILED:
        return outcome_layer.pending(
            repo_root,
            remote=remote,
            branch=branch,
            detail=state.detail,
            recovery=(
                f"the remote could not be read. recipe: restore access to "
                f"{remote}, then `git push {remote} {branch}`"
            ),
        )
    operator = state.operator_commits
    if operator:
        listed = "\n".join(f"  {line}" for line in operator)
        return outcome_layer.pending(
            repo_root,
            remote=remote,
            branch=branch,
            detail=(
                f"{branch} carries commits {remote}/{branch} does not, and "
                f"they are not this installer's:\n{listed}"
            ),
            recovery=(
                "the installed layer is committed but was not pushed, "
                "because pushing would publish those commits too. recipe: "
                f"publish or drop them yourself, then `git push {remote} "
                f"{branch}`"
            ),
        )
    return {
        "status": outcome_layer.ELIGIBLE, "remote": remote, "branch": branch,
    }


__all__ = ["MAX_PUSH_ATTEMPTS", "publish_installed_layer",
           "publish_onboarded_layer"]
