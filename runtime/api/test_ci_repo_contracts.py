"""Coverage for the CI repo-contracts fast-fail front.

The parity scenarios boot a real tmp git repo because the defect they pin
is a git-resolution one: a dispatched run and a pull-request run of the same
workflow check out different commits (branch tip versus merge commit) that
share a fork point, and both must enumerate the same changed files.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import List

import pytest

from yoke_core.tools import ci_repo_contracts as crc


REPO_ROOT = Path(__file__).resolve().parents[2]
YOKE_CI = REPO_ROOT / ".github" / "workflows" / "yoke-ci.yml"

FILE_LINE_CHECK = "yoke_harness.git_hooks.file_line_check.changed_files_check"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def forked_repo(tmp_path: Path) -> Path:
    """A lane that edits one file with an unused import, main since advanced."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "ci@yoke.test")
    _git(repo, "config", "user.name", "Yoke Test")
    (repo / "edited.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "untouched.py").write_text("OTHER = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _git(repo, "branch", "item-lane")
    (repo / "untouched.py").write_text("OTHER = 2\n", encoding="utf-8")
    _git(repo, "commit", "-am", "main advances past the fork point")
    _git(repo, "checkout", "item-lane")
    (repo / "edited.py").write_text("import os\n\nVALUE = 2\n", encoding="utf-8")
    _git(repo, "commit", "-am", "edit a file that carries an unused import")
    return repo


def test_yoke_ci_gates_shards_on_repo_contracts() -> None:
    workflow = YOKE_CI.read_text(encoding="utf-8")

    assert "repo_contracts:" in workflow
    assert "name: repo-contracts" in workflow
    assert "yoke_core.tools.ci_repo_contracts" in workflow
    assert "needs: [repo_contracts, reuse_coverage]" in workflow
    # Aggregate that waited on shards must stay gone.
    assert "needs: test_shard" not in workflow


def test_workflow_scopes_delta_checks_identically_on_every_event() -> None:
    workflow = YOKE_CI.read_text(encoding="utf-8")

    assert (
        '--base "origin/${{ github.event.repository.default_branch }}"' in workflow
    )
    # github.base_ref is populated only on pull_request, so any diff-scoped
    # step reading it silently degrades to a skip on every other event.
    assert "github.base_ref" not in workflow
    assert "github.event_name == 'pull_request'" not in workflow


def test_contract_roster_names_expected_checks() -> None:
    names = [name for name, _ in crc.CONTRACTS]
    assert names == [
        "authored-file-limit",
        "changed-path-ruff",
        "atlas-currency",
        "install-bundle-tree",
    ]


def test_branch_tip_and_merge_commit_resolve_one_file_set(
    forked_repo: Path,
) -> None:
    dispatch = crc.resolve_changed_path_scope(forked_repo, "main")

    _git(forked_repo, "checkout", "-b", "entry-run", "main")
    _git(forked_repo, "merge", "--no-ff", "-m", "entry merge", "item-lane")
    pull_request = crc.resolve_changed_path_scope(forked_repo, "main")

    assert dispatch.paths == ("edited.py",)
    assert pull_request.paths == dispatch.paths
    assert dispatch.python_paths == ["edited.py"]


def test_changed_path_ruff_flags_a_defect_in_an_edited_file(
    forked_repo: Path,
) -> None:
    pytest.importorskip("ruff")
    scope = crc.resolve_changed_path_scope(forked_repo, "main")

    ok, detail = crc.check_changed_path_ruff(forked_repo, scope)

    assert ok is False
    assert "F401" in detail
    assert "edited.py" in detail
    assert ":1:" in detail


def test_changed_path_ruff_reports_every_finding_then_passes_when_fixed(
    tmp_path: Path,
) -> None:
    pytest.importorskip("ruff")
    (tmp_path / "zeta.py").write_text(
        "import sys\n\nZETA = 1\n",
        encoding="utf-8",
    )
    (tmp_path / "alpha.py").write_text(
        "import os\nimport json\n\nALPHA = 1\n",
        encoding="utf-8",
    )
    scope = crc.ChangedPathScope(
        base_sha="abc123",
        paths=("zeta.py", "alpha.py"),
    )

    ok, detail = crc.check_changed_path_ruff(tmp_path, scope)

    lines = detail.splitlines()
    assert ok is False
    assert len(lines) == 3
    assert [Path(line.split(":", 1)[0]).name for line in lines] == [
        "alpha.py",
        "alpha.py",
        "zeta.py",
    ]
    assert all("F401" in line for line in lines)
    assert all(name in detail for name in ("os", "json", "sys"))

    (tmp_path / "alpha.py").write_text("ALPHA = 1\n", encoding="utf-8")
    (tmp_path / "zeta.py").write_text("ZETA = 1\n", encoding="utf-8")

    ok, detail = crc.check_changed_path_ruff(tmp_path, scope)

    assert ok is True
    assert detail == "ruff clean on 2 path(s)"


def test_ruff_failure_detail_is_stably_ordered_and_bounded() -> None:
    diagnostics = [
        {
            "filename": f"file_{index:02d}.py",
            "location": {"row": index + 1, "column": 1},
            "code": "F401",
            "message": f"unused_{index}",
        }
        for index in reversed(range(22))
    ]

    lines = crc._ruff_failure_detail(json.dumps(diagnostics), "").splitlines()

    assert len(lines) == 21
    assert lines[0].startswith("file_00.py:1:1: F401")
    assert lines[-2].startswith("file_19.py:20:1: F401")
    assert lines[-1] == "... and 2 more"


def test_changed_path_ruff_clean_when_no_python_diff(tmp_path: Path) -> None:
    scope = crc.ChangedPathScope(base_sha="abc123", paths=("docs/notes.md",))

    ok, detail = crc.check_changed_path_ruff(tmp_path, scope)

    assert ok is True
    assert "no changed Python paths" in detail


def test_authored_file_limit_anchors_on_the_shared_base(
    forked_repo: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = crc.resolve_changed_path_scope(forked_repo, "main")
    seen: dict[str, object] = {}

    def _record(*, repo_root: Path, base: str, staged: bool):
        seen.update(repo_root=repo_root, base=base, staged=staged)
        return SimpleNamespace(ok=True, summary="ok")

    monkeypatch.setattr(FILE_LINE_CHECK, _record)

    ok, _detail = crc.check_authored_file_limit(forked_repo, scope)

    assert ok is True
    assert seen["base"] == scope.base_sha
    assert seen["staged"] is False


def test_unresolvable_base_fails_instead_of_skipping(
    forked_repo: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    assert crc.run_contracts(forked_repo, base="origin/never-fetched") == 1

    assert "unresolvable" in capsys.readouterr().err


def test_main_requires_an_explicit_base() -> None:
    with pytest.raises(SystemExit):
        crc.main([])


def test_run_contracts_reports_named_failure(
    forked_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    def _fail(_repo: Path, _scope: crc.ChangedPathScope) -> tuple[bool, str]:
        return False, "deliberately broken"

    def _pass(_repo: Path, _scope: crc.ChangedPathScope) -> tuple[bool, str]:
        return True, "ok"

    monkeypatch.setattr(
        crc,
        "CONTRACTS",
        (
            ("authored-file-limit", _pass),
            ("changed-path-ruff", _pass),
            ("atlas-currency", _fail),
            ("install-bundle-tree", _pass),
        ),
    )
    assert crc.run_contracts(forked_repo, base="main") == 1
    captured = capsys.readouterr()
    assert "repo-contract atlas-currency: FAIL" in captured.out
    assert "atlas-currency" in summary.read_text(encoding="utf-8")
    assert "**Failed contracts:** atlas-currency" in summary.read_text(
        encoding="utf-8"
    )


def test_run_contracts_passes_when_all_green(
    forked_repo: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    passes: List[str] = []
    scopes: List[crc.ChangedPathScope] = []

    def _pass(name: str):
        def _inner(_repo: Path, scope: crc.ChangedPathScope) -> tuple[bool, str]:
            passes.append(name)
            scopes.append(scope)
            return True, "ok"

        return _inner

    monkeypatch.setattr(
        crc,
        "CONTRACTS",
        tuple((name, _pass(name)) for name, _ in crc.CONTRACTS),
    )
    assert crc.run_contracts(forked_repo, base="main") == 0
    assert passes == [name for name, _ in crc.CONTRACTS]
    # Every contract reads the same resolved scope object.
    assert len({id(scope) for scope in scopes}) == 1
