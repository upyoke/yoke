"""Unit coverage for the coverage evidence a complete yoke-ci run publishes."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from yoke_core.tools import ci_shards
from yoke_core.tools import yoke_ci_coverage_evidence as evidence_lib


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "ci@yoke.local")
    _git(repo, "config", "user.name", "Yoke CI")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "first")
    return repo


def test_required_coverage_names_every_leg_and_its_scope() -> None:
    versions = ci_shards.python_versions()
    coverage = evidence_lib.required_coverage()

    assert coverage["shards"] == ci_shards.SHARD_COUNT
    assert list(coverage["python"]) == versions
    assert coverage["python"][versions[-1]] == "all"
    assert all(coverage["python"][v] == "interpreter" for v in versions[:-1])


def test_main_records_the_checked_out_commit_tree_run_and_attempt(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_RUN_ID", "41")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "3")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert (
        evidence_lib.main(
            [
                "--worktree",
                str(repo),
                "--output-dir",
                str(tmp_path),
                "--write-github-output",
            ]
        )
        == 0
    )

    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    evidence = json.loads((tmp_path / evidence_lib.EVIDENCE_FILE).read_text())
    assert evidence == {
        "schema": 1,
        "commit": _git(repo, "rev-parse", "HEAD"),
        "tree": tree,
        "run_id": 41,
        "run_attempt": 3,
        "coverage": evidence_lib.required_coverage(),
    }
    assert output.read_text() == f"artifact_name=yoke-ci-coverage-{tree}\n"
    assert (
        evidence_lib.evidence_refusal(
            evidence,
            candidate_tree=tree,
            run_id=41,
            required=evidence_lib.required_coverage(),
        )
        is None
    )


def test_main_refuses_outside_a_ci_run(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    with pytest.raises(SystemExit, match="coverage_evidence_run_identity_missing"):
        evidence_lib.main(["--worktree", str(repo)])


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        ({"tree": "other"}, "evidence_tree_mismatch"),
        ({"commit": ""}, "evidence_commit_missing"),
        ({"run_attempt": True}, "evidence_attempt_missing"),
        ({"coverage": {"python": {"3.14": "all"}, "shards": 8}}, "incomplete_coverage"),
    ],
)
def test_evidence_refusal_names_the_mismatch(change: dict, refusal: str) -> None:
    required = {"python": {"3.11": "interpreter", "3.14": "all"}, "shards": 8}
    evidence = {
        "schema": 1,
        "commit": "c",
        "tree": "t",
        "run_id": 1,
        "run_attempt": 1,
        "coverage": required,
        **change,
    }
    assert (
        evidence_lib.evidence_refusal(
            evidence, candidate_tree="t", run_id=1, required=required
        )
        == refusal
    )
