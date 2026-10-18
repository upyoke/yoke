"""Unit coverage for the yoke-ci identical-tree coverage reuse probe."""

from __future__ import annotations

from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
import zipfile

import pytest

from yoke_core.tools import yoke_ci_coverage_evidence as evidence_lib
from yoke_core.tools import yoke_ci_tree_reuse as probe


NOW = datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc)
COVERAGE = {"python": {"3.11": "interpreter", "3.14": "all"}, "shards": 8}
STORAGE = "https://storage.test/blob"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


def _commit(repo: Path, name: str, body: str) -> None:
    (repo / name).write_text(body, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-m", name)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A main line plus two pull request branches cut from the same base."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "ci@yoke.local")
    _git(repo, "config", "user.name", "Yoke CI")
    _git(repo, "checkout", "-B", "main")
    _commit(repo, "a.txt", "one\n")
    for branch in ("pr-one", "pr-two"):
        _git(repo, "checkout", "-b", branch, "main")
        _commit(repo, f"{branch}.txt", f"{branch}\n")
    _git(repo, "checkout", "main")
    return repo


def _merge(repo: Path, branch: str, *, onto: str, message: str) -> str:
    """Check out a merge commit the way a PR or queue run would."""
    _git(repo, "checkout", "--detach", onto)
    _git(repo, "merge", "--no-ff", branch, "-m", message)
    return _git(repo, "rev-parse", "HEAD")


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _zip(payload: Any) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(evidence_lib.EVIDENCE_FILE, json.dumps(payload))
    return buffer.getvalue()


class FakeGitHub:
    """Artifacts keyed by exact name, one archive, one run attempt."""

    def __init__(self, *, tree: str, commit: str, **overrides: Any) -> None:
        self.evidence = {
            "schema": 1,
            "commit": commit,
            "tree": tree,
            "run_id": 100,
            "run_attempt": 2,
            "coverage": COVERAGE,
        }
        self.evidence.update(overrides.pop("evidence", {}))
        self.artifact = {
            "id": 7,
            "expired": False,
            "created_at": "2026-08-07T17:00:00Z",
            "archive_download_url": "https://api.test/repos/o/r/actions/artifacts/7/zip",
            "workflow_run": {"id": 100, "repository_id": 1, "head_repository_id": 1},
        }
        self.artifact.update(overrides.pop("artifact", {}))
        self.run = {
            "path": ".github/workflows/yoke-ci.yml",
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://example.test/runs/100",
        }
        self.run.update(overrides.pop("run", {}))
        self.names = {evidence_lib.artifact_name(tree)}
        self.calls: list[tuple[str, Any]] = []

    def __call__(self, request: Any, timeout: float = 0) -> _Response:
        url = request.full_url
        self.calls.append((url, request.get_header("Authorization")))
        if "/actions/artifacts?" in url:
            name = parse_qs(urlsplit(url).query)["name"][0]
            found = [self.artifact] if name in self.names else []
            return _Response(json.dumps({"artifacts": found}).encode())
        if url.endswith("/zip"):
            raise HTTPError(url, 302, "Found", {"Location": STORAGE}, None)  # type: ignore[arg-type]
        if url == STORAGE:
            return _Response(_zip(self.evidence))
        assert url.endswith("/actions/runs/100/attempts/2"), url
        return _Response(json.dumps(self.run).encode())


def _decide(repo: Path, github: FakeGitHub, **kwargs: Any) -> probe.ReuseDecision:
    return probe.decide_reuse(
        worktree=repo,
        api_url="https://api.test",
        repository="o/r",
        token="token",
        current_run_id=999,
        now=NOW,
        opener=github,
        required=COVERAGE,
        **kwargs,
    )


def test_queue_entry_on_unchanged_base_reuses_the_pr_checkout_proof(repo: Path) -> None:
    """The PR run head is not what it tested; the evidence names the checkout."""
    pr_head = _git(repo, "rev-parse", "pr-one")
    tested = _merge(repo, "pr-one", onto="main", message="Merge PR into main")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    queue_commit = _merge(repo, "pr-one", onto="main", message="Merge group entry")
    assert queue_commit != tested and _git(repo, "rev-parse", "HEAD^{tree}") == tree
    github = FakeGitHub(tree=tree, commit=tested)

    decision = _decide(repo, github)

    assert decision.skip_suite is True
    assert decision.reason == "identical_tree_coverage"
    assert (decision.covering_run_id, decision.covering_run_attempt) == (100, 2)
    assert decision.covering_commit == tested != pr_head
    assert decision.proven_at == "2026-08-07T17:00:00Z"
    storage = [auth for url, auth in github.calls if url == STORAGE]
    assert storage == [None]  # the redirected download never carries the token


def test_changed_base_and_multi_entry_compositions_run_the_suite(repo: Path) -> None:
    tested = _merge(repo, "pr-one", onto="main", message="PR run")
    github = FakeGitHub(tree=_git(repo, "rev-parse", "HEAD^{tree}"), commit=tested)

    _git(repo, "checkout", "main")
    _commit(repo, "moved.txt", "base moved\n")
    _merge(repo, "pr-one", onto="main", message="entry on moved base")
    moved = _decide(repo, github)

    _git(repo, "checkout", "--detach", tested)
    _git(repo, "merge", "--no-ff", "pr-two", "-m", "second queue entry")
    combined = _decide(repo, github)

    for decision in (moved, combined):
        assert decision.skip_suite is False
        assert decision.reason == "no_coverage_evidence"


@pytest.mark.parametrize(
    ("overrides", "refusal"),
    [
        (
            {"evidence": {"coverage": {"python": {"3.14": "all"}, "shards": 8}}},
            "incomplete_coverage",
        ),
        ({"evidence": {"coverage": {**COVERAGE, "shards": 4}}}, "incomplete_coverage"),
        ({"artifact": {"expired": True}}, "expired_artifact"),
        (
            {"artifact": {"created_at": "2026-08-06T17:59:59Z"}},
            "proof_older_than_window",
        ),
        ({"artifact": {"created_at": "2026-08-07T18:00:01Z"}}, "proof_from_future"),
        ({"artifact": {"created_at": "yesterday"}}, "unreadable_proof_time"),
        (
            {
                "artifact": {
                    "workflow_run": {
                        "id": 999,
                        "repository_id": 1,
                        "head_repository_id": 1,
                    }
                }
            },
            "current_run",
        ),
        (
            {
                "artifact": {
                    "workflow_run": {
                        "id": 100,
                        "repository_id": 1,
                        "head_repository_id": 2,
                    }
                }
            },
            "fork_run",
        ),
        ({"run": {"conclusion": "cancelled"}}, "run_cancelled"),
        ({"run": {"conclusion": "failure"}}, "run_failure"),
        ({"run": {"status": "in_progress", "conclusion": None}}, "run_not_completed"),
        ({"run": {"path": ".github/workflows/other.yml"}}, "other_workflow"),
        ({"evidence": {"run_id": 101}}, "evidence_run_mismatch"),
        ({"evidence": {"run_attempt": 0}}, "evidence_attempt_missing"),
        ({"evidence": {"schema": 2}}, "unreadable_evidence"),
    ],
)
def test_ineligible_evidence_runs_the_suite_and_names_why(
    repo: Path, overrides: dict[str, Any], refusal: str
) -> None:
    tested = _merge(repo, "pr-one", onto="main", message="PR run")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")

    decision = _decide(repo, FakeGitHub(tree=tree, commit=tested, **overrides))

    assert decision.skip_suite is False
    assert decision.reason == "no_eligible_evidence"
    run_id = 999 if refusal == "current_run" else 100
    assert decision.rejected == (f"artifact 7 (run {run_id}): {refusal}",)


def test_unreadable_archive_and_api_failure_run_the_suite(repo: Path) -> None:
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    github = FakeGitHub(tree=tree, commit="c")
    github.evidence = "not json"  # type: ignore[assignment]
    assert _decide(repo, github).rejected == (
        "artifact 7 (run 100): unreadable_evidence",
    )

    def offline(request: Any, timeout: float = 0) -> _Response:
        raise URLError("offline")

    decision = probe.decide_reuse(
        worktree=repo,
        api_url="https://api.test",
        repository="o/r",
        token="t",
        current_run_id=1,
        now=NOW,
        opener=offline,
        required=COVERAGE,
    )
    assert (decision.skip_suite, decision.reason) == (False, "artifact_list_unreadable")


def test_main_reports_the_decision_and_summary(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    output, summary = tmp_path / "out", tmp_path / "summary"
    for key, value in {
        "GITHUB_TOKEN": "t",
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_RUN_ID": "5",
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        probe,
        "decide_reuse",
        lambda **_: probe.ReuseDecision(
            False,
            "tree",
            "no_eligible_evidence",
            rejected=("artifact 7 (run 1): run_failure",),
        ),
    )

    assert probe.main(["--worktree", str(repo), "--write-github-output"]) == 0

    assert "skip_suite=false\n" in output.read_text()
    assert "reason=no_eligible_evidence\n" in output.read_text()
    assert "- artifact 7 (run 1): run_failure" in summary.read_text()
    assert "rejected: artifact 7 (run 1): run_failure" in capsys.readouterr().out


def test_main_runs_the_suite_without_github_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_REPOSITORY", "GH_REPOSITORY"):
        monkeypatch.delenv(key, raising=False)
    assert probe.main([]) == 0
    assert "reason=missing_github_env" in capsys.readouterr().out
