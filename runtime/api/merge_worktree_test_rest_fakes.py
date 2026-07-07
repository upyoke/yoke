"""REST fake-response builders for merge-worktree tests.

The failfast / orchestration tests in
:mod:`runtime.api.test_merge_worktree_failfast` invoke the merge engine
as a subprocess. The engine no longer shells out to ``gh``; it issues REST calls through
:mod:`yoke_core.domain.gh_rest_transport`. This module produces the
canned JSON response files that satisfy each merge scenario, mirroring
the role the ``MOCK_GH_*`` shell-script constants used to play.

Each ``write_*`` function lays down the per-endpoint JSON file the
transport's fake-dir loader reads. Tests choose which set of fakes the
engine sees by ``write_<scenario>(fake_dir, …)``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional

from yoke_core.domain.gh_rest_transport import RestRequest
from yoke_core.domain.gh_rest_transport_fakes import fake_response_filename


# Tests always exercise ``owner/repo`` with this name; the project's
# `projects.github_repo` is seeded to match.
TEST_REPO = "anthropics/yoke"
TEST_OWNER, TEST_NAME = TEST_REPO.split("/", 1)

# Canonical PR head SHA the happy-path fakes report for ``pulls/{n}``. The
# merge gate's freshness binding compares the local verdict's stamped SHA
# against this, so the seeded ``items.test_results`` verdict
# (``merge_worktree_test_db``) is stamped with the same value. One source of
# truth keeps the fake response and the seeded verdict in lockstep.
DEFAULT_HEAD_SHA = "abc123def"


def _write(
    fake_dir: Path,
    filename: str,
    *,
    status: int = 200,
    body: Any = "",
    headers: Optional[Mapping[str, str]] = None,
    side_effect: Optional[str] = None,
) -> None:
    fake_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "status": status,
        "headers": dict(headers or {}),
        "body": body,
    }
    if side_effect:
        payload["side_effect"] = side_effect
    (fake_dir / filename).write_text(json.dumps(payload))


def _merge_side_effect_command(origin_path: str, branch: str) -> str:
    """Shell snippet that simulates GitHub's merge by pushing the branch's
    commits into ``origin/main``. Mirrors what the legacy ``MOCK_GH`` ``pr
    merge`` script did."""
    return (
        "set -e; "
        f'_tmp="{origin_path}.merge-work"; '
        'rm -rf "$_tmp"; '
        f'git clone "{origin_path}" "$_tmp" >/dev/null 2>&1; '
        'cd "$_tmp"; '
        'git config user.email "test@test.com"; '
        'git config user.name "Test"; '
        f'git merge "origin/{branch}" -m "Merge {branch}" >/dev/null 2>&1 || true; '
        "git push origin main >/dev/null 2>&1 || true; "
        'cd /; '
        'rm -rf "$_tmp"'
    )


def pulls_create_filename() -> str:
    return fake_response_filename(
        RestRequest(method="POST", path=f"/repos/{TEST_OWNER}/{TEST_NAME}/pulls")
    )


def pulls_list_filename(branch: str) -> str:
    return fake_response_filename(
        RestRequest(
            method="GET",
            path=f"/repos/{TEST_OWNER}/{TEST_NAME}/pulls",
            query={"head": f"{TEST_OWNER}:{branch}", "state": "open"},
        )
    )


def pulls_get_filename(pr_num: str) -> str:
    return fake_response_filename(
        RestRequest(
            method="GET",
            path=f"/repos/{TEST_OWNER}/{TEST_NAME}/pulls/{pr_num}",
        )
    )


def pulls_merge_filename(pr_num: str) -> str:
    return fake_response_filename(
        RestRequest(
            method="PUT",
            path=f"/repos/{TEST_OWNER}/{TEST_NAME}/pulls/{pr_num}/merge",
        )
    )


def check_runs_filename(sha: str) -> str:
    return fake_response_filename(
        RestRequest(
            method="GET",
            path=f"/repos/{TEST_OWNER}/{TEST_NAME}/commits/{sha}/check-runs",
        )
    )


# ---------------------------------------------------------------------------
# Scenario writers
# ---------------------------------------------------------------------------


def write_happy_path(
    fake_dir: Path,
    *,
    branch: str,
    pr_num: str = "9999",
    head_sha: str = DEFAULT_HEAD_SHA,
    origin_path: Optional[str] = None,
) -> None:
    """Successful PR create + no-checks + merge.

    When ``origin_path`` is supplied the merge fake fires a side-effect
    that pushes the branch into ``origin/main`` so the engine's
    downstream verify step (which checks ``branch is ancestor of
    origin/main``) finds the merge. Without ``origin_path`` only the
    canned REST response fires — useful for unit-level fail-fast tests
    that stop before the verify step.
    """
    fake_dir = Path(fake_dir)
    _write(
        fake_dir,
        pulls_create_filename(),
        status=201,
        body={
            "number": int(pr_num),
            "html_url": f"https://github.com/{TEST_REPO}/pull/{pr_num}",
        },
    )
    _write(
        fake_dir,
        pulls_get_filename(pr_num),
        body={
            "number": int(pr_num),
            "head": {"sha": head_sha},
            "mergeable_state": "clean",
            "mergeable": True,
        },
    )
    _write(
        fake_dir,
        check_runs_filename(head_sha),
        body={"check_runs": []},  # no checks → skipped, falls back to local evidence
    )
    side_effect = (
        _merge_side_effect_command(origin_path, branch) if origin_path else None
    )
    _write(
        fake_dir,
        pulls_merge_filename(pr_num),
        body={"merged": True, "message": "Pull Request successfully merged"},
        side_effect=side_effect,
    )


def write_pr_create_hard_fail(fake_dir: Path) -> None:
    """POST /pulls returns 422 with a non-already-exists error."""
    fake_dir = Path(fake_dir)
    _write(
        fake_dir,
        pulls_create_filename(),
        status=422,
        body={"message": "Validation Failed", "errors": []},
    )
    # pr_list is never reached, but writing for safety.


def write_pr_create_empty_url(fake_dir: Path) -> None:
    """POST /pulls returns 201 with no number/url (degenerate)."""
    fake_dir = Path(fake_dir)
    _write(
        fake_dir,
        pulls_create_filename(),
        status=201,
        body={},  # no number, no html_url
    )


def write_pr_exists_reuse(
    fake_dir: Path,
    *,
    branch: str,
    pr_num: str = "42",
    head_sha: str = DEFAULT_HEAD_SHA,
    origin_path: Optional[str] = None,
) -> None:
    """POST /pulls returns 422 already-exists; GET /pulls?head=… returns a PR."""
    fake_dir = Path(fake_dir)
    _write(
        fake_dir,
        pulls_create_filename(),
        status=422,
        body={
            "message": (
                f"A pull request already exists for {TEST_OWNER}:{branch}"
            ),
            "errors": [
                {
                    "resource": "PullRequest",
                    "code": "custom",
                    "message": (
                        f"A pull request already exists for {TEST_OWNER}:{branch}"
                    ),
                }
            ],
        },
    )
    _write(
        fake_dir,
        pulls_list_filename(branch),
        body=[
            {
                "number": int(pr_num),
                "html_url": f"https://github.com/{TEST_REPO}/pull/{pr_num}",
            }
        ],
    )
    _write(
        fake_dir,
        pulls_get_filename(pr_num),
        body={
            "number": int(pr_num),
            "head": {"sha": head_sha},
            "mergeable_state": "clean",
            "mergeable": True,
        },
    )
    _write(
        fake_dir,
        check_runs_filename(head_sha),
        body={"check_runs": []},
    )
    side_effect = (
        _merge_side_effect_command(origin_path, branch) if origin_path else None
    )
    _write(
        fake_dir,
        pulls_merge_filename(pr_num),
        body={"merged": True, "message": "Pull Request successfully merged"},
        side_effect=side_effect,
    )


def write_pr_exists_unresolvable(fake_dir: Path, *, branch: str) -> None:
    """POST /pulls returns 422 already-exists; GET /pulls returns empty."""
    fake_dir = Path(fake_dir)
    _write(
        fake_dir,
        pulls_create_filename(),
        status=422,
        body={
            "message": (
                f"A pull request already exists for {TEST_OWNER}:{branch}"
            )
        },
    )
    _write(fake_dir, pulls_list_filename(branch), body=[])


def write_pr_merge_fail(
    fake_dir: Path, *, branch: str, pr_num: str = "9999", head_sha: str = DEFAULT_HEAD_SHA
) -> None:
    """Happy path through PR create + CI, then PUT /merge returns 409."""
    write_happy_path(fake_dir, branch=branch, pr_num=pr_num, head_sha=head_sha)
    fake_dir = Path(fake_dir)
    _write(
        fake_dir,
        pulls_merge_filename(pr_num),
        status=409,
        body={"message": "Pull Request is not mergeable"},
    )
