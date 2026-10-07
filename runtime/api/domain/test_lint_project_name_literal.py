"""Tests for the project-name-literal scanner."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.lint_project_name_literal import (
    is_exempt_relpath,
    scan,
    scan_source,
)

_REL = "packages/example/src/example/module.py"


@pytest.mark.parametrize(
    "source",
    [
        'if args.project == "acme":\n    pass\n',
        'if item_project != "acme":\n    pass\n',
        'x = proj["slug"] == "acme"\n',
        'x = str(identity["project_slug"]) == "acme"\n',
        'x = project.strip().lower() == "acme"\n',
        'x = "acme" in project_slugs\n',
        'x = project_id in {"acme", "other"}\n',
        'Q = "SELECT id FROM items i JOIN projects p ON p.id=i.project_id WHERE p.slug <> \'acme\'"\n',
        'Q = "SELECT id FROM projects WHERE slug=\'acme\'"\n',
        'Q = "LEFT JOIN projects owner ON owner.slug=\'acme\'"\n',
    ],
)
def test_project_name_branch_is_flagged(source: str) -> None:
    hits = scan_source(_REL, source)
    assert len(hits) == 1
    assert hits[0].relpath == _REL
    assert hits[0].line == 1


@pytest.mark.parametrize(
    "source",
    [
        'if project == "":\n    pass\n',
        'if project == "all":\n    pass\n',
        'if project_slug in ("null", "none"):\n    pass\n',
        'if project == other_project:\n    pass\n',
        'if command_base != "yoke":\n    pass\n',
        'if row.name == "yoke":\n    pass\n',
        'if part in {".", ".."}:\n    pass\n',
        'Q = "SELECT content FROM strategy_docs WHERE slug = \'VISION\'"\n',
        'merge(project="acme")\n',
    ],
)
def test_non_branches_and_cli_name_comparisons_pass(source: str) -> None:
    assert scan_source(_REL, source) == []


@pytest.mark.parametrize(
    "relpath",
    [
        "runtime/api/test_something.py",
        "runtime/api/conftest.py",
        "runtime/api/merge_worktree_test_db.py",
        "runtime/api/migration_applied_evidence_test_helpers.py",
        "runtime/api/fixtures/backlog_inserts.py",
        "runtime/api/parity_service_client_project_fixture.py",
        "packages/yoke-core/src/yoke_core/install_bundle_tree/docs/x.py",
    ],
)
def test_tests_fixtures_and_generated_copies_are_exempt(relpath: str) -> None:
    assert is_exempt_relpath(relpath)


def test_product_module_is_in_scope() -> None:
    assert not is_exempt_relpath(
        "packages/yoke-core/src/yoke_core/engines/doctor_hc_worktrees.py"
    )


def test_scan_walks_roots_and_skips_exempt_files(tmp_path: Path) -> None:
    product = tmp_path / "packages" / "pkg" / "src" / "pkg" / "branch.py"
    product.parent.mkdir(parents=True)
    product.write_text('if args.project == "acme":\n    pass\n', encoding="utf-8")
    test_file = tmp_path / "runtime" / "api" / "test_branch.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text('assert args.project == "acme"\n', encoding="utf-8")

    hits = scan(tmp_path)

    assert [(hit.relpath, hit.line) for hit in hits] == [
        ("packages/pkg/src/pkg/branch.py", 1)
    ]
