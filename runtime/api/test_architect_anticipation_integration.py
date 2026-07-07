"""Integration regression for the plan-time anticipation helper."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.architect_plan_anticipation import (
    AnticipationList,
    build_anticipation_list,
)

FILE_BUDGET = [
    "runtime/api/domain/sample_auth.py",
    "runtime/api/domain/test_sample_auth.py",
]


def _plant(root: Path, rel: str, content: str) -> None:
    target = root.joinpath(rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path.joinpath("synthetic_repo")
    root.mkdir()
    files = {
        FILE_BUDGET[0]: "def auth_handler():\n    return None\n",
        FILE_BUDGET[1]: "from yoke_core.domain.sample_auth import auth_handler\n",
        "runtime/api/engines/doctor_hc_sample_auth.py": (
            "MODULE = 'sample_auth'\n"
        ),
        "runtime/api/engines/doctor_hc_unrelated_subsystem.py": (
            "MODULE = 'unrelated'\n"
        ),
        "runtime/api/orchestration/auth_consumer_one.py": (
            "from yoke_core.domain.sample_auth import auth_handler\n"
        ),
        "runtime/api/orchestration/auth_consumer_two.py": (
            "import yoke_core.domain.sample_auth\n"
        ),
        "runtime/api/adapters/external_auth_adapter.py": (
            "from yoke_core.domain.sample_auth import auth_handler\n"
        ),
        "runtime/api/integration/test_sample_auth_integration.py": (
            "from yoke_core.domain.sample_auth import auth_handler\n"
        ),
        "runtime/api/orchestration/unrelated.py": "import json\n",
    }
    for rel, content in files.items():
        _plant(root, rel, content)
    return root


def test_cross_cutting_fixture_expands_path_claim_surface(tmp_path: Path) -> None:
    """AC-7/AC-11: synthetic ``*-callers-a`` shape covers widened paths."""

    root = _fixture(tmp_path)
    result = build_anticipation_list(
        epic_id=1,
        task_num=6,
        file_budget_paths=FILE_BUDGET,
        repo_root=root,
    )

    assert isinstance(result, AnticipationList)
    assert set(result.file_budget) == set(FILE_BUDGET)
    assert result.doctor_hcs == ["runtime/api/engines/doctor_hc_sample_auth.py"]
    assert set(result.transitive_callers) == {
        "runtime/api/adapters/external_auth_adapter.py",
        "runtime/api/orchestration/auth_consumer_one.py",
        "runtime/api/orchestration/auth_consumer_two.py",
    }
    assert result.test_modules == [
        "runtime/api/integration/test_sample_auth_integration.py",
    ]
    assert "runtime/api/orchestration/unrelated.py" not in result.all_paths()
    assert len(set(result.all_paths()) - set(FILE_BUDGET)) >= 4
    assert not root.joinpath(".worktrees").exists()
    assert all(not path.startswith(".worktrees/") for path in result.all_paths())
