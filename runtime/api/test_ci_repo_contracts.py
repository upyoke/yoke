"""Coverage for the CI repo-contracts fast-fail front."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from yoke_core.tools import ci_repo_contracts as crc


REPO_ROOT = Path(__file__).resolve().parents[2]
YOKE_CI = REPO_ROOT / ".github" / "workflows" / "yoke-ci.yml"


def test_yoke_ci_gates_shards_on_repo_contracts() -> None:
    workflow = YOKE_CI.read_text(encoding="utf-8")

    assert "repo_contracts:" in workflow
    assert "name: repo-contracts" in workflow
    assert "yoke_core.tools.ci_repo_contracts" in workflow
    assert "needs: repo_contracts" in workflow
    # Aggregate that waited on shards must stay gone.
    assert "needs: test_shard" not in workflow


def test_contract_roster_names_expected_checks() -> None:
    names = [name for name, _ in crc.CONTRACTS]
    assert names == [
        "authored-file-limit",
        "changed-path-ruff",
        "atlas-currency",
        "install-bundle-tree",
    ]


def test_delta_contracts_skip_without_base(tmp_path: Path) -> None:
    ok, detail = crc.check_authored_file_limit(tmp_path, None)
    assert ok is True
    assert "skipped" in detail
    ok, detail = crc.check_changed_path_ruff(tmp_path, None)
    assert ok is True
    assert "skipped" in detail


def test_changed_path_ruff_clean_when_no_python_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(crc, "_changed_python_paths", lambda *_a, **_k: [])
    ok, detail = crc.check_changed_path_ruff(tmp_path, "main")
    assert ok is True
    assert "no changed Python paths" in detail


def test_run_contracts_reports_named_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    def _fail(_repo: Path, _base: str | None) -> tuple[bool, str]:
        return False, "deliberately broken"

    def _pass(_repo: Path, _base: str | None) -> tuple[bool, str]:
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
    assert crc.run_contracts(tmp_path, base=None) == 1
    captured = capsys.readouterr()
    assert "repo-contract atlas-currency: FAIL" in captured.out
    assert "atlas-currency" in summary.read_text(encoding="utf-8")
    assert "**Failed contracts:** atlas-currency" in summary.read_text(
        encoding="utf-8"
    )


def test_run_contracts_passes_when_all_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    passes: List[str] = []

    def _pass(name: str):
        def _inner(_repo: Path, _base: str | None) -> tuple[bool, str]:
            passes.append(name)
            return True, "ok"

        return _inner

    monkeypatch.setattr(
        crc,
        "CONTRACTS",
        tuple((name, _pass(name)) for name, _ in crc.CONTRACTS),
    )
    assert crc.run_contracts(tmp_path, base="origin/main") == 0
    assert passes == [name for name, _ in crc.CONTRACTS]
