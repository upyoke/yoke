"""Post-push proof for a queue-less standalone landing.

The local merge is already a durable fact when this boundary runs. A remote
push can therefore only decide whether close-out is safe: green checks (or a
bounded proof that the project has none) allow the caller's evidence and done
transition; red or still-pending checks preserve both claim and lane for a
follow-up commit through the same merge command. Physical retirement belongs
to the later successful terminal boundary.

The proof reads checks under the authority the merge itself ran under, passed
in by the boundary that classified the route. Demanding a stricter authority
here is how a landed merge came to report failure: the branch was already on
the base branch, and the only thing that failed was asking for a machine user
authorization the read never needed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CHECKS_READ_PERMISSION_LEVELS as CHECKS_READ,
)
from yoke_contracts.machine_config.settings_keys import machine_setting_default
from yoke_core.domain import gh_rest_transport, runtime_settings
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import standalone_item_merge_receipt as receipts
from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
)
from yoke_core.domain.github_poll_schedule import MINIMUM_POLL_INTERVAL_SECONDS
from yoke_core.engines.merge_worktree_pr_rest import (
    AuthResolutionFailed,
    resolve_auth,
)
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext
from yoke_core.engines.main_checkout_sync import fast_forward_main_checkout


DISCOVERY_TIMEOUT_KEY = "standalone_post_push_ci_discovery_timeout"
CONCLUSION_TIMEOUT_KEY = "standalone_post_push_ci_timeout"
_GREEN_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})


@dataclass(frozen=True)
class CheckRun:
    """One check run attached to the pushed merge commit."""

    name: str
    status: str
    conclusion: str = ""
    url: str = ""

    def evidence(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "conclusion": self.conclusion,
            "url": self.url,
        }

    def describe(self) -> str:
        state = self.conclusion or self.status or "unreported"
        return f"{self.name}: {state}" + (f" ({self.url})" if self.url else "")


@dataclass(frozen=True)
class PostPushVerdict:
    """What the bounded observer proved about one pushed merge commit."""

    kind: str
    runs: tuple[CheckRun, ...] = field(default=())
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.kind in {"passed", "no_checks"}

    @property
    def evidence(self) -> tuple[dict[str, str], ...]:
        return tuple(run.evidence() for run in self.runs)


def _setting_seconds(key: str) -> int:
    default = int(machine_setting_default(key))
    return runtime_settings.get_seconds(key, default)


def read_check_runs(
    project: str, merge_sha: str, authority: str,
) -> tuple[Optional[tuple[CheckRun, ...]], str]:
    """Read check runs for exactly ``merge_sha`` under the merge's authority."""
    ctx = MergeContext(args=MergeArgs(branch=""), project=project)
    try:
        auth = resolve_auth(
            ctx,
            required_permissions=CHECKS_READ,
            required_authority=authority,
        )
    except AuthResolutionFailed as exc:
        hint = f" Repair: {exc.hint}" if exc.hint else ""
        return None, f"post-push check auth resolution failed: {exc}.{hint}"
    owner, repo = gh_rest_transport.split_repo(auth.repo)
    request = RestRequest(
        method="GET",
        path=f"/repos/{owner}/{repo}/commits/{merge_sha}/check-runs",
    )
    try:
        response = request_with_retry(request, token=auth.token)
    except RestTransportError as exc:
        return None, f"post-push check-runs read failed: {exc}"
    payload = response.body if isinstance(response.body, dict) else None
    raw_runs = payload.get("check_runs") if payload is not None else None
    if not isinstance(raw_runs, list):
        return None, "post-push check-runs response omitted check_runs"
    runs: list[CheckRun] = []
    for raw in raw_runs:
        if not isinstance(raw, dict):
            return None, "post-push check-runs response contained a malformed run"
        runs.append(CheckRun(
            name=str(raw.get("name") or "unnamed check").strip(),
            status=str(raw.get("status") or "").strip().lower(),
            conclusion=str(raw.get("conclusion") or "").strip().lower(),
            url=str(raw.get("html_url") or raw.get("details_url") or "").strip(),
        ))
    return tuple(runs), ""


def _terminal_kind(runs: tuple[CheckRun, ...]) -> str:
    completed = tuple(run for run in runs if run.status == "completed")
    if any(run.conclusion not in _GREEN_CONCLUSIONS for run in completed):
        return "failed"
    if len(completed) == len(runs):
        return "passed"
    return "pending"


def _descriptions(runs: Sequence[CheckRun]) -> str:
    return "; ".join(run.describe() for run in runs)


def await_post_push_checks(
    project: str,
    merge_sha: str,
    authority: str,
    *,
    read: Callable[
        [str, str, str], tuple[Optional[tuple[CheckRun, ...]], str]
    ] = read_check_runs,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> PostPushVerdict:
    """Discover and then poll checks without violating the 60-second floor."""
    discovery_timeout = float(_setting_seconds(DISCOVERY_TIMEOUT_KEY))
    conclusion_timeout = float(_setting_seconds(CONCLUSION_TIMEOUT_KEY))
    started = monotonic()
    discovery_deadline = min(discovery_timeout, conclusion_timeout)

    while True:
        runs, error = read(project, merge_sha, authority)
        if error or runs is None:
            return PostPushVerdict("unreadable", detail=error)
        if runs:
            break
        remaining = discovery_deadline - (monotonic() - started)
        if remaining <= 0:
            return PostPushVerdict("no_checks")
        if remaining < MINIMUM_POLL_INTERVAL_SECONDS:
            sleep(remaining)
            return PostPushVerdict("no_checks")
        sleep(MINIMUM_POLL_INTERVAL_SECONDS)

    while True:
        kind = _terminal_kind(runs)
        if kind in {"failed", "passed"}:
            return PostPushVerdict(kind, runs=runs)
        remaining = conclusion_timeout - (monotonic() - started)
        if remaining <= 0:
            return PostPushVerdict("timed_out", runs=runs)
        if remaining < MINIMUM_POLL_INTERVAL_SECONDS:
            sleep(remaining)
            return PostPushVerdict("timed_out", runs=runs)
        sleep(MINIMUM_POLL_INTERVAL_SECONDS)
        refreshed, error = read(project, merge_sha, authority)
        if error or refreshed is None:
            return PostPushVerdict("unreadable", runs=runs, detail=error)
        runs = refreshed


def _refusal_message(
    verdict: PostPushVerdict, *, merge_sha: str, resume_command: str,
) -> str:
    observed = _descriptions(verdict.runs)
    if verdict.kind == "failed":
        reason = f"post-push CI failed for {merge_sha}: {observed}"
    elif verdict.kind == "timed_out":
        reason = f"post-push CI remained pending for {merge_sha}: {observed}"
    else:
        reason = verdict.detail or f"post-push CI was unreadable for {merge_sha}"
    return (
        f"{reason}. The merge is landed; the work claim and lane are retained. "
        f"Commit the fix in the same lane, then resume with `{resume_command}`."
    )


def complete(
    *,
    item_id: int,
    branch: str,
    target: str,
    repo_root: str,
    project: str,
    authority: str,
    commit_sha: str,
    touched: tuple[str, ...],
    already: bool,
    output: str = "",
    warnings: Sequence[str] = (),
    resume_command: str = "",
):
    """Publish a landed merge and prove its checks for terminal close-out."""
    from yoke_core.domain.standalone_item_merge import (
        StandaloneMergeOutcome,
        stamp_merged_at,
    )

    merge_sha = git.git_out(repo_root, "rev-parse", target)
    notes = list(warnings)
    pushed, push_warning = git.publish(repo_root, target)
    if push_warning:
        notes.append(push_warning)
    stamp_error = stamp_merged_at(item_id)
    if stamp_error:
        notes.append(f"merged_at not recorded: {stamp_error}")

    def record(check_runs: tuple[dict[str, str], ...] = ()) -> None:
        note = receipts.record(
            item_id,
            receipts.MergeReceipt(
                branch=branch, target=target, commit_sha=commit_sha,
                merge_sha=merge_sha, touched_files=touched,
                check_runs=check_runs,
            ),
            project=project,
        )
        if note:
            notes.append(note)

    record()
    if pushed:
        verdict = await_post_push_checks(project, merge_sha, authority)
        if verdict.runs:
            record(verdict.evidence)
        if not verdict.ok:
            command = resume_command or f"yoke merge item {branch}"
            return StandaloneMergeOutcome(
                ok=False, exit_code=1, already_merged=already,
                commit_sha=commit_sha, merge_sha=merge_sha,
                touched_files=touched, pushed=True, output=output,
                error=_refusal_message(
                    verdict, merge_sha=merge_sha, resume_command=command,
                ),
                warnings=tuple(notes),
            )

    if git.has_remote(repo_root):
        sync_warning = fast_forward_main_checkout(repo_root, target)
        if sync_warning:
            notes.append(sync_warning)
    return StandaloneMergeOutcome(
        ok=True, exit_code=0, already_merged=already,
        commit_sha=commit_sha, merge_sha=merge_sha, touched_files=touched,
        pushed=pushed, output=output, warnings=tuple(notes),
    )


__all__ = [
    "CONCLUSION_TIMEOUT_KEY",
    "DISCOVERY_TIMEOUT_KEY",
    "CheckRun",
    "PostPushVerdict",
    "await_post_push_checks",
    "complete",
    "read_check_runs",
]
