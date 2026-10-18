"""Reuse completed yoke-ci coverage only for an identical tested git tree.

A merge-group candidate that merges one pull request onto an unchanged base
has the same tree that pull request's run tested, and a push after landing
repeats the tree its queue run tested. Changed bases and multi-entry queue
compositions create new trees, find no evidence, and run the suite.

Evidence comes from :mod:`yoke_ci_coverage_evidence`: an artifact named for
the tree the shards actually checked out. Reuse requires that the artifact is
unexpired, inside the window, from a same-repository yoke-ci run whose
recorded attempt concluded successfully, and that it names the candidate tree
and the complete required coverage. Missing, expired, unreadable, failed,
cancelled or partial evidence runs the suite; every rejection is reported.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import urlencode
import zipfile

from yoke_contracts.timestamps import InvalidInstant, parse_instant, utc_now

from yoke_core.tools import yoke_ci_coverage_evidence as evidence_lib


DEFAULT_WINDOW_HOURS = 24
WORKFLOW_PATH = ".github/workflows/yoke-ci.yml"


@dataclass(frozen=True)
class ReuseDecision:
    skip_suite: bool
    candidate_tree: str
    reason: str
    covering_run_id: Optional[int] = None
    covering_run_attempt: Optional[int] = None
    covering_commit: str = ""
    covering_html_url: str = ""
    proven_at: str = ""
    rejected: tuple[str, ...] = field(default_factory=tuple)


def _parse_github_time(raw: Any) -> Optional[datetime]:
    """Unreadable external evidence cannot authorize skipping verification."""
    if raw is None:
        return None
    try:
        return parse_instant(raw)
    except InvalidInstant:
        return None


def tree_object_id(worktree: str | Path, rev: str) -> Optional[str]:
    """Resolve *rev* to its git tree object id, or None on any failure."""
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(worktree),
                "rev-parse",
                "--verify",
                "--quiet",
                f"{rev}^{{tree}}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


def _artifact_refusal(
    artifact: Mapping[str, Any],
    *,
    current_run_id: int,
    cutoff: datetime,
    clock: datetime,
) -> Optional[str]:
    if artifact.get("expired"):
        return "expired_artifact"
    run = artifact.get("workflow_run")
    if not isinstance(run, dict) or not isinstance(run.get("id"), int):
        return "artifact_run_missing"
    if run["id"] == current_run_id:
        return "current_run"
    if run.get("head_repository_id") != run.get("repository_id"):
        return "fork_run"
    created = _parse_github_time(artifact.get("created_at"))
    if created is None:
        return "unreadable_proof_time"
    if created < cutoff:
        return "proof_older_than_window"
    if created > clock:
        return "proof_from_future"
    return None


def _run_refusal(run: Any) -> Optional[str]:
    if not isinstance(run, dict):
        return "unreadable_run"
    if run.get("path") != WORKFLOW_PATH:
        return "other_workflow"
    if run.get("status") != "completed":
        return "run_not_completed"
    if run.get("conclusion") != "success":
        return f"run_{run.get('conclusion') or 'unconcluded'}"
    return None


def decide_reuse(
    *,
    worktree: str | Path,
    api_url: str,
    repository: str,
    token: str,
    current_run_id: int,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    now: Optional[datetime] = None,
    opener: Callable[..., Any] = evidence_lib.default_opener,
    required: Optional[Mapping[str, Any]] = None,
) -> ReuseDecision:
    """Return whether the suite may be skipped for HEAD's tree."""
    clock = utc_now() if now is None else parse_instant(now)
    candidate = tree_object_id(worktree, "HEAD")
    if not candidate:
        return ReuseDecision(False, "", "unresolvable_candidate_tree")
    if window_hours <= 0:
        return ReuseDecision(False, candidate, "invalid_window")
    coverage = evidence_lib.required_coverage() if required is None else required
    github = evidence_lib.GitHubArtifacts(api_url, repository, token, opener)
    query = urlencode({"name": evidence_lib.artifact_name(candidate), "per_page": "20"})
    try:
        listing = github.get_json(f"actions/artifacts?{query}")
    except evidence_lib.FETCH_ERRORS as exc:
        print(f"coverage evidence listing failed: {exc}", file=sys.stderr)
        return ReuseDecision(False, candidate, "artifact_list_unreadable")
    artifacts = listing.get("artifacts") if isinstance(listing, dict) else None
    if not isinstance(artifacts, list) or not artifacts:
        return ReuseDecision(False, candidate, "no_coverage_evidence")

    cutoff = clock - timedelta(hours=window_hours)
    rejected: list[str] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        label = f"artifact {artifact.get('id')}"
        refusal = _artifact_refusal(
            artifact, current_run_id=current_run_id, cutoff=cutoff, clock=clock
        )
        run_id = (artifact.get("workflow_run") or {}).get("id")
        evidence: Any = None
        if refusal is None:
            try:
                evidence = github.read_evidence(artifact)
            except (
                *evidence_lib.FETCH_ERRORS,
                zipfile.BadZipFile,
                KeyError,
                UnicodeError,
            ):
                refusal = "unreadable_evidence"
        if refusal is None:
            refusal = evidence_lib.evidence_refusal(
                evidence, candidate_tree=candidate, run_id=run_id, required=coverage
            )
        run: Any = None
        if refusal is None:
            attempt = evidence["run_attempt"]
            try:
                run = github.get_json(f"actions/runs/{run_id}/attempts/{attempt}")
            except evidence_lib.FETCH_ERRORS:
                refusal = "unreadable_run"
            else:
                refusal = _run_refusal(run)
        if refusal is not None:
            rejected.append(f"{label} (run {run_id}): {refusal}")
            continue
        return ReuseDecision(
            skip_suite=True,
            candidate_tree=candidate,
            reason="identical_tree_coverage",
            covering_run_id=run_id,
            covering_run_attempt=evidence["run_attempt"],
            covering_commit=evidence["commit"],
            covering_html_url=str(run.get("html_url") or "").strip(),
            proven_at=str(artifact.get("created_at") or ""),
            rejected=tuple(rejected),
        )
    return ReuseDecision(
        False, candidate, "no_eligible_evidence", rejected=tuple(rejected)
    )


def decision_outputs(decision: ReuseDecision) -> dict[str, str]:
    return {
        "skip_suite": "true" if decision.skip_suite else "false",
        "candidate_tree": decision.candidate_tree,
        "reason": decision.reason,
        "covering_run_id": str(decision.covering_run_id or ""),
        "covering_run_attempt": str(decision.covering_run_attempt or ""),
        "covering_commit": decision.covering_commit,
        "covering_html_url": decision.covering_html_url,
        "proven_at": decision.proven_at,
    }


def _step_summary(decision: ReuseDecision) -> str:
    lines = ["## yoke-ci tree reuse", ""]
    lines += [
        f"- {key}: `{value or '(none)'}`"
        for key, value in decision_outputs(decision).items()
    ]
    if decision.rejected:
        lines += [
            "",
            "Rejected evidence (the suite runs unless another proof matched):",
        ]
        lines += [f"- {entry}" for entry in decision.rejected]
    if not decision.skip_suite:
        lines += ["", "The full suite runs on this tree; no recovery is needed."]
    return "\n".join(lines) + "\n"


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", default=".")
    parser.add_argument("--window-hours", type=int, default=None)
    parser.add_argument("--write-github-output", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    token = _env("GITHUB_TOKEN") or _env("GH_TOKEN")
    repository = _env("GITHUB_REPOSITORY") or _env("GH_REPOSITORY")
    api_url = _env("GITHUB_API_URL") or "https://api.github.com"
    try:
        current_run_id = int(_env("GITHUB_RUN_ID") or "0")
        window_hours = (
            args.window_hours
            if args.window_hours is not None
            else int(_env("REUSE_WINDOW_HOURS") or str(DEFAULT_WINDOW_HOURS))
        )
    except ValueError:
        current_run_id, window_hours = 0, 0

    if not token or not repository:
        decision = ReuseDecision(False, "", "missing_github_env")
    else:
        try:
            decision = decide_reuse(
                worktree=args.worktree,
                api_url=api_url,
                repository=repository,
                token=token,
                current_run_id=current_run_id,
                window_hours=window_hours,
            )
        except Exception as exc:  # noqa: BLE001 - any probe fault runs the suite
            print(
                f"yoke-ci tree reuse probe failed; running the suite: {exc}",
                file=sys.stderr,
            )
            decision = ReuseDecision(
                False, "", f"probe_exception: {type(exc).__name__}"
            )

    outputs = decision_outputs(decision)
    for key, value in outputs.items():
        print(f"{key}={value}")
    for entry in decision.rejected:
        print(f"rejected: {entry}")

    if args.write_github_output:
        output_path = _env("GITHUB_OUTPUT")
        if output_path:
            with Path(output_path).open("a", encoding="utf-8") as handle:
                handle.writelines(f"{key}={value}\n" for key, value in outputs.items())
        summary_path = _env("GITHUB_STEP_SUMMARY")
        if summary_path:
            with Path(summary_path).open("a", encoding="utf-8") as handle:
                handle.write(_step_summary(decision))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_WINDOW_HOURS",
    "ReuseDecision",
    "WORKFLOW_PATH",
    "decide_reuse",
    "decision_outputs",
    "main",
    "tree_object_id",
]
