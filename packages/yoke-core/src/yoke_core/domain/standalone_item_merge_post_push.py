"""Prove publication and candidate ancestry before closing a landing."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional, Sequence

from yoke_contracts.designed_wait import announce_designed_wait, poll_every
from yoke_contracts.machine_config.settings_keys import machine_setting_default
from yoke_core.domain import runtime_settings
from yoke_core.domain.standalone_post_push_policy import observe_post_push_checks
from yoke_core.domain.standalone_post_push_ci import (
    read_push_checks,
    superseding_push_sha,
)
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.merge_github_authority import github_merge_enabled
from yoke_core.domain.standalone_item_merge_publication_message import (
    refusal_message,
    publication_narration,
)
from yoke_core.domain import item_merge_receipts as receipts
from yoke_core.domain.merge_landing_proof import (
    LandingUnverified,
    verified_landing_identity,
    verified_target_sha,
)
from yoke_core.domain.github_poll_schedule import MINIMUM_POLL_INTERVAL_SECONDS
from yoke_core.engines.main_checkout_sync import fast_forward_main_checkout

DISCOVERY_TIMEOUT_KEY = "standalone_post_push_ci_discovery_timeout"
CONCLUSION_TIMEOUT_KEY = "standalone_post_push_ci_timeout"
_GREEN_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})
_MALFORMED_PAGINATION = "post-push check-runs pagination is incomplete or malformed"


@dataclass(frozen=True)
class CheckRun:
    """One check run attached to the pushed merge commit."""

    name: str
    status: str
    conclusion: str = ""
    url: str = ""

    def evidence(self) -> dict[str, str]:
        return asdict(self)

    def describe(self) -> str:
        state = self.conclusion or self.status or "unreported"
        return f"{self.name}: {state}" + (f" ({self.url})" if self.url else "")


@dataclass(frozen=True)
class PostPushVerdict:
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


def _decode_check_runs_page(
    payload: object,
) -> tuple[Optional[list[CheckRun]], Optional[int], str]:
    if not isinstance(payload, dict):
        return None, None, "post-push check-runs response omitted check_runs"
    raw_runs = payload.get("check_runs")
    if not isinstance(raw_runs, list):
        return None, None, "post-push check-runs response omitted check_runs"
    raw_count = payload.get("total_count")
    if isinstance(raw_count, bool) or not isinstance(raw_count, int) or raw_count < 0:
        return None, None, _MALFORMED_PAGINATION
    runs: list[CheckRun] = []
    for raw in raw_runs:
        if not isinstance(raw, dict):
            error = "post-push check-runs response contained a malformed run"
            return None, None, error
        runs.append(
            CheckRun(
                name=str(raw.get("name") or "unnamed check").strip(),
                status=str(raw.get("status") or "").strip().lower(),
                conclusion=str(raw.get("conclusion") or "").strip().lower(),
                url=str(raw.get("html_url") or raw.get("details_url") or "").strip(),
            )
        )
    if len(runs) > raw_count:
        return None, None, _MALFORMED_PAGINATION
    return runs, raw_count, ""


def read_check_runs(
    project: str,
    merge_sha: str,
    authority: str,
) -> tuple[Optional[tuple[CheckRun, ...]], str]:
    raw, error = read_push_checks(project, merge_sha, authority)
    if raw is None:
        return None, error
    runs, _, error = _decode_check_runs_page(
        {"check_runs": raw, "total_count": len(raw)}
    )
    return (tuple(runs) if runs is not None else None), error


def _terminal_kind(runs: tuple[CheckRun, ...]) -> str:
    completed = tuple(run for run in runs if run.status == "completed")
    if any(
        run.conclusion not in _GREEN_CONCLUSIONS | {"cancelled"} for run in completed
    ):
        return "failed"
    if any(run.conclusion == "cancelled" for run in completed):
        return "cancelled"
    if len(completed) == len(runs):
        return "passed"
    return "pending"


def await_post_push_checks(
    project: str,
    merge_sha: str,
    authority: str,
    *,
    read: Callable[
        [str, str, str], tuple[Optional[tuple[CheckRun, ...]], str]
    ] = read_check_runs,
    supersede: Callable[[str, str, str], tuple[str, str]] = superseding_push_sha,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> PostPushVerdict:
    discovery_timeout = float(_setting_seconds(DISCOVERY_TIMEOUT_KEY))
    conclusion_timeout = float(_setting_seconds(CONCLUSION_TIMEOUT_KEY))
    started = monotonic()
    discovery_deadline = min(discovery_timeout, conclusion_timeout)
    announce_designed_wait(
        f"post-push CI checks on {merge_sha}",
        max_wait_seconds=conclusion_timeout,
        cadence=poll_every(MINIMUM_POLL_INTERVAL_SECONDS),
    )

    while True:
        runs, error = read(project, merge_sha, authority)
        if error or runs is None:
            return PostPushVerdict("unreadable", detail=error)
        if runs:
            break
        remaining = discovery_deadline - (monotonic() - started)
        if remaining <= 0:
            return PostPushVerdict("no_checks")
        sleep(min(remaining, MINIMUM_POLL_INTERVAL_SECONDS))

    detail = ""
    while True:
        kind = _terminal_kind(runs)
        if kind == "cancelled":
            successor, error = supersede(project, merge_sha, authority)
            if error:
                return PostPushVerdict(
                    "unreadable", runs=runs, detail=f"{detail}; {error}".strip("; ")
                )
            if not successor:
                return PostPushVerdict("failed", runs=runs, detail=detail)
            notice = f"post-push CI on {merge_sha} superseded by {successor}"
            print(notice, flush=True)
            detail = f"{detail}; {notice}".strip("; ")
            merge_sha = successor
            refreshed, error = read(project, merge_sha, authority)
            if error or not refreshed:
                reason = (
                    error
                    or "post_push_ci_unreadable: superseding push checks disappeared; retry merge close-out"
                )
                return PostPushVerdict(
                    "unreadable", runs=runs, detail=f"{detail}; {reason}"
                )
            runs = refreshed
            kind = _terminal_kind(runs)
        if kind in {"failed", "passed"}:
            return PostPushVerdict(kind, runs=runs, detail=detail)
        remaining = conclusion_timeout - (monotonic() - started)
        if remaining <= 0:
            return PostPushVerdict("timed_out", runs=runs, detail=detail)
        sleep(min(remaining, MINIMUM_POLL_INTERVAL_SECONDS))
        refreshed, error = read(project, merge_sha, authority)
        if error or not refreshed:
            error = (
                error
                or "post_push_ci_unreadable: previously observed push checks disappeared; retry merge close-out"
            )
            return PostPushVerdict(
                "unreadable", runs=runs, detail=f"{detail}; {error}".strip("; ")
            )
        runs = refreshed


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
    from yoke_core.domain.standalone_item_merge import (
        StandaloneMergeOutcome,
        stamp_merged_at,
    )

    notes = list(warnings)
    pushed, push_warning = git.publish(repo_root, target)
    if push_warning and not pushed:
        notes.append(push_warning)
    try:
        if not pushed and push_warning:
            command = resume_command or f"yoke merge item {branch}"
            raise LandingUnverified(f"{push_warning}; repair publication, then retry `{command}`")
        merge_sha = verified_target_sha(repo_root, target, commit_sha)
        merge_sha = verified_landing_identity(repo_root, merge_sha, commit_sha)
        disconnected = (
            not github_merge_enabled(project) if git.has_remote(repo_root) else True
        )
    except (LandingUnverified, RuntimeError) as exc:
        reason = (
            str(exc)
            if isinstance(exc, LandingUnverified)
            else (
                f"github_merge_mode_unreadable: {exc}. Repair the project GitHub "
                f"binding status read, then retry {resume_command or f'yoke merge item {branch}'}; "
                "the lane is retained and close-out has not advanced."
            )
        )
        note = receipts.record_failure(
            item_id,
            branch=branch,
            target=target,
            label="merge_landing_unverified",
            phase="publication",
            reason=reason,
        )
        if note:
            notes.append(note)
        return StandaloneMergeOutcome(
            ok=False,
            exit_code=1,
            already_merged=False,
            commit_sha=commit_sha,
            touched_files=touched,
            pushed=pushed,
            output=output,
            error=reason,
            warnings=tuple(notes),
        )
    stamp_error = stamp_merged_at(item_id, repo_root=repo_root, merge_sha=merge_sha)
    if stamp_error:
        notes.append(f"merged_at not recorded: {stamp_error}")

    def record(check_runs: tuple[dict[str, str], ...] = ()) -> None:
        note = receipts.record(
            item_id,
            receipts.MergeReceipt(
                branch=branch,
                target=target,
                commit_sha=commit_sha,
                merge_sha=merge_sha,
                touched_files=touched,
                check_runs=check_runs,
            ),
        )
        if note:
            notes.append(note)

    record()
    observed: Optional[PostPushVerdict] = None
    if pushed and not disconnected and merge_sha:
        observed, required = observe_post_push_checks(
            project, merge_sha, authority, notes
        )
        if observed.runs:
            record(observed.evidence)
        if required and not observed.ok:
            command = resume_command or f"yoke merge item {branch}"
            return StandaloneMergeOutcome(
                ok=False,
                exit_code=1,
                already_merged=already,
                commit_sha=commit_sha,
                merge_sha=merge_sha,
                touched_files=touched,
                pushed=True,
                output=output,
                error=refusal_message(
                    observed,
                    merge_sha=merge_sha,
                    resume_command=command,
                ),
                warnings=tuple(notes),
            )

    narration = publication_narration(
        pushed=pushed,
        push_warning=push_warning if not pushed else "",
        verdict=observed,
    )
    if pushed and push_warning:
        narration = f"{push_warning} {narration}".strip()
    if narration:
        output = f"{output}\n{narration}".strip() if output else narration
    if not disconnected and git.has_remote(repo_root):
        sync_warning = fast_forward_main_checkout(repo_root, target)
        if sync_warning:
            notes.append(sync_warning)
    return StandaloneMergeOutcome(
        ok=True,
        exit_code=0,
        already_merged=already,
        commit_sha=commit_sha,
        merge_sha=merge_sha,
        touched_files=touched,
        pushed=pushed,
        output=output,
        publication_message=narration,
        warnings=tuple(notes),
    )
