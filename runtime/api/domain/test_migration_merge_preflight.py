"""Pure merge-gate coverage for migration order and item collisions."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from runtime.api.fixtures.migration_model_test import (
    TEST_MIGRATION_MODULES_DIR,
    governed_postgres_test_seed,
)
from yoke_core.domain.migration_merge_preflight import (
    evaluate_migration_merge,
    migration_merge_applicable,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _write(repo: Path, identifier: str) -> None:
    path = repo / TEST_MIGRATION_MODULES_DIR / f"{identifier}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def apply(conn):\n    pass\n", encoding="utf-8")


def _lane(tmp_path: Path, identifier: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _write(repo, "0013_existing")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    _git(repo, "checkout", "-q", "-b", "lane")
    _write(repo, identifier)
    return repo


def _profile(identifier: str) -> str:
    return json.dumps(
        {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "apply",
            "migration_modules": [identifier],
            "compatibility_class": "pre_merge_safe",
            "migration_strategy": "additive_only",
            "schema_kinds": ["additive"],
            "data_kinds": [],
            "affected_surfaces": [{"table": "widgets"}],
            "count_preserving": True,
        },
        sort_keys=True,
    )


def _row(item_id: int, status: str, identifier: str) -> dict[str, str]:
    return {
        "internal_id": str(item_id),
        "id": f"YOK-{item_id}",
        "status": status,
        "db_mutation_profile": _profile(identifier),
    }


def _evaluate(repo: Path, rows: list[dict[str, str]]):
    return evaluate_migration_merge(
        rows=rows,
        item_id=1,
        capability_settings_json=json.dumps(governed_postgres_test_seed()),
        worktree_path=repo,
        integration_target="main",
    )


def test_gate_accepts_next_ordinal_when_prior_collision_is_done(
    tmp_path: Path,
) -> None:
    repo = _lane(tmp_path, "0014_current")
    rows = [
        _row(1, "reviewing-implementation", "0014_current"),
        _row(2, "done", "0014_old_lane"),
    ]

    decision = _evaluate(repo, rows)

    assert decision.applicable
    assert decision.passed


def test_gate_names_non_terminal_item_holding_same_ordinal(
    tmp_path: Path,
) -> None:
    repo = _lane(tmp_path, "0014_current")
    rows = [
        _row(1, "reviewing-implementation", "0014_current"),
        _row(2, "implementing", "0014_other_lane"),
    ]

    decision = _evaluate(repo, rows)

    assert not decision.passed
    assert "item 2 is non-terminal" in decision.errors[0]
    assert "ordinal 14" in decision.errors[0]
    assert "0014_other_lane" in decision.errors[0]


def test_gate_refuses_non_sequential_lane_entry(tmp_path: Path) -> None:
    repo = _lane(tmp_path, "0015_current")

    decision = _evaluate(
        repo, [_row(1, "reviewing-implementation", "0015_current")]
    )

    assert not decision.passed
    assert "requires exactly 14 next" in decision.errors[0]


def test_slug_only_migration_does_not_activate_numbered_gate() -> None:
    rows = [_row(1, "reviewing-implementation", "legacy_module")]

    assert not migration_merge_applicable(rows, 1)
