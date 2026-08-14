"""Same-tree reuse probe for the yoke-ci workflow.

Two runs re-prove trees that were already proved. After a fast-forward
merge the push-to-main run re-executes the suite against the tree a
dispatch or pull-request run already covered; and a merge queue train
carrying one rebased item builds a candidate whose tree is byte-identical
to that item's entry tree, so the train run repeats the entry run exactly.
This probe resolves the checked-out tree's object id, walks recent
successful yoke-ci runs, and reports reuse when a covering run's head
commit resolves to the same tree id.

A ``pull_request`` run covers by the same rule everything else does, and
soundly: the run's recorded head sha is the pull request's head commit,
whose tree equals the candidate tree only when the base was already an
ancestor of it — which is exactly when the run tested that tree rather
than a merge of it. A batch train, or a train built after the base moved,
produces a tree no single run covers and runs the full suite, which is
when the integration proof is real.

Fail open on every uncertainty: API errors, missing shas, unresolvable
trees, empty result sets, or covering runs older than the window all mean
``skip_suite=false`` so the matrix runs exactly as today. Comparison is by
tree object id, never commit sha — merge commits that rewrite the tree
correctly force a fresh suite.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_WINDOW_HOURS = 24
DEFAULT_WORKFLOW_FILE = "yoke-ci.yml"
_HTTP_TIMEOUT_S = 30


@dataclass(frozen=True)
class ReuseDecision:
    skip_suite: bool
    candidate_tree: str
    covering_run_id: Optional[int]
    covering_head_sha: str
    covering_html_url: str
    reason: str


def _no_reuse(reason: str, candidate_tree: str = "") -> ReuseDecision:
    return ReuseDecision(
        skip_suite=False,
        candidate_tree=candidate_tree,
        covering_run_id=None,
        covering_head_sha="",
        covering_html_url="",
        reason=reason,
    )


def _parse_github_time(raw: str) -> Optional[datetime]:
    text = (raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def tree_object_id(worktree: str | Path, rev: str) -> Optional[str]:
    """Resolve *rev* to its git tree object id, or None on any failure."""
    try:
        proc = subprocess.run(
            [
                "git", "-C", str(worktree),
                "rev-parse", "--verify", "--quiet", f"{rev}^{{tree}}",
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


def _api_get_json(
    url: str, *, token: str, opener: Callable[..., Any] = urlopen,
) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "yoke-ci-tree-reuse",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    with opener(request, timeout=_HTTP_TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8"))


def commit_tree_via_api(
    *,
    api_url: str,
    repository: str,
    token: str,
    commit_sha: str,
    opener: Callable[..., Any] = urlopen,
) -> Optional[str]:
    """Return the tree oid for *commit_sha* from the GitHub Git API."""
    sha = (commit_sha or "").strip()
    if not sha:
        return None
    url = f"{api_url.rstrip('/')}/repos/{repository}/git/commits/{sha}"
    try:
        payload = _api_get_json(url, token=token, opener=opener)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    tree = payload.get("tree")
    if not isinstance(tree, dict):
        return None
    return str(tree.get("sha") or "").strip() or None


def list_successful_workflow_runs(
    *,
    api_url: str,
    repository: str,
    token: str,
    workflow_file: str,
    per_page: int = 50,
    opener: Callable[..., Any] = urlopen,
) -> list[dict[str, Any]]:
    """Return successful completed runs for *workflow_file*, newest first."""
    query = urlencode({"status": "success", "per_page": str(per_page)})
    url = (
        f"{api_url.rstrip('/')}/repos/{repository}/actions/workflows/"
        f"{workflow_file}/runs?{query}"
    )
    try:
        payload = _api_get_json(url, token=token, opener=opener)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []
    if not isinstance(payload, dict):
        return []
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        return []
    return [run for run in runs if isinstance(run, dict)]


def decide_reuse(
    *,
    worktree: str | Path,
    api_url: str,
    repository: str,
    token: str,
    current_run_id: int,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    workflow_file: str = DEFAULT_WORKFLOW_FILE,
    now: Optional[datetime] = None,
    opener: Callable[..., Any] = urlopen,
) -> ReuseDecision:
    """Return whether the suite may be skipped for HEAD's tree."""
    candidate = tree_object_id(worktree, "HEAD")
    if not candidate:
        return _no_reuse("unresolvable_candidate_tree")
    if window_hours <= 0:
        return _no_reuse("invalid_window", candidate)

    clock = now or datetime.now(timezone.utc)
    cutoff = clock - timedelta(hours=window_hours)
    runs = list_successful_workflow_runs(
        api_url=api_url,
        repository=repository,
        token=token,
        workflow_file=workflow_file,
        opener=opener,
    )
    if not runs:
        return _no_reuse("no_successful_runs", candidate)

    for run in runs:
        try:
            run_id = int(run.get("id"))
        except (TypeError, ValueError):
            continue
        if run_id == current_run_id:
            continue
        created = _parse_github_time(str(run.get("created_at") or ""))
        if created is None or created < cutoff:
            continue
        head_sha = str(run.get("head_sha") or "").strip()
        if not head_sha:
            continue
        covered = tree_object_id(worktree, head_sha)
        if covered is None:
            covered = commit_tree_via_api(
                api_url=api_url,
                repository=repository,
                token=token,
                commit_sha=head_sha,
                opener=opener,
            )
        if covered is None or covered != candidate:
            continue
        return ReuseDecision(
            skip_suite=True,
            candidate_tree=candidate,
            covering_run_id=run_id,
            covering_head_sha=head_sha,
            covering_html_url=str(run.get("html_url") or "").strip(),
            reason="identical_tree",
        )

    return _no_reuse("no_matching_tree", candidate)


def _append_github_output(path: Path, values: Mapping[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _append_step_summary(path: Path, decision: ReuseDecision) -> None:
    lines = [
        "## yoke-ci tree reuse",
        "",
        f"- skip_suite: `{str(decision.skip_suite).lower()}`",
        f"- reason: `{decision.reason}`",
        f"- candidate_tree: `{decision.candidate_tree or '(none)'}`",
    ]
    if decision.skip_suite:
        lines.extend(
            [
                f"- covering_run_id: `{decision.covering_run_id}`",
                f"- covering_head_sha: `{decision.covering_head_sha}`",
                f"- covering_html_url: {decision.covering_html_url or '(none)'}",
            ]
        )
    lines.append("")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", default=".")
    parser.add_argument("--window-hours", type=int, default=None)
    parser.add_argument("--workflow-file", default=DEFAULT_WORKFLOW_FILE)
    parser.add_argument("--write-github-output", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    token = _env("GITHUB_TOKEN") or _env("GH_TOKEN")
    repository = _env("GITHUB_REPOSITORY") or _env("GH_REPOSITORY")
    api_url = _env("GITHUB_API_URL") or _env("GH_API_URL") or "https://api.github.com"
    try:
        current_run_id = int(_env("GITHUB_RUN_ID") or _env("GH_RUN_ID") or "0")
    except ValueError:
        current_run_id = 0
    if args.window_hours is None:
        try:
            window_hours = int(_env("REUSE_WINDOW_HOURS") or str(DEFAULT_WINDOW_HOURS))
        except ValueError:
            window_hours = DEFAULT_WINDOW_HOURS
    else:
        window_hours = args.window_hours

    if not token or not repository:
        decision = _no_reuse("missing_github_env")
    else:
        try:
            decision = decide_reuse(
                worktree=args.worktree,
                api_url=api_url,
                repository=repository,
                token=token,
                current_run_id=current_run_id,
                window_hours=window_hours,
                workflow_file=args.workflow_file,
            )
        except Exception as exc:  # noqa: BLE001 - fail open
            print(f"yoke-ci tree reuse probe failed open: {exc}", file=sys.stderr)
            decision = _no_reuse("probe_exception")

    outputs = {
        "skip_suite": "true" if decision.skip_suite else "false",
        "candidate_tree": decision.candidate_tree,
        "covering_run_id": (
            str(decision.covering_run_id) if decision.covering_run_id is not None else ""
        ),
        "covering_head_sha": decision.covering_head_sha,
        "covering_html_url": decision.covering_html_url,
        "reason": decision.reason,
    }
    for key, value in outputs.items():
        print(f"{key}={value}")

    if args.write_github_output:
        output_path = _env("GITHUB_OUTPUT")
        if output_path:
            _append_github_output(Path(output_path), outputs)
        summary_path = _env("GITHUB_STEP_SUMMARY")
        if summary_path:
            _append_step_summary(Path(summary_path), decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_WINDOW_HOURS",
    "DEFAULT_WORKFLOW_FILE",
    "ReuseDecision",
    "commit_tree_via_api",
    "decide_reuse",
    "list_successful_workflow_runs",
    "main",
    "tree_object_id",
]
