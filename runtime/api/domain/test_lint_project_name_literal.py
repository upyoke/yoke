"""Tests for the project-name-literal scanner."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.lint_project_name_literal import (
    ProjectLiteralHit,
    is_exempt_relpath,
    scan,
    scan_source,
)
from yoke_core.domain.lint_project_name_literal_allowances import Allowance, classify

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
        "Q = \"SELECT id FROM items i JOIN projects p ON p.id=i.project_id WHERE p.slug <> 'acme'\"\n",
        "Q = \"SELECT id FROM projects WHERE slug='acme'\"\n",
        "Q = \"LEFT JOIN projects owner ON owner.slug='acme'\"\n",
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
        "if project == other_project:\n    pass\n",
        'if command_base != "yoke":\n    pass\n',
        'if row.name == "yoke":\n    pass\n',
        'if part in {".", ".."}:\n    pass\n',
        "Q = \"SELECT content FROM strategy_docs WHERE slug = 'VISION'\"\n",
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


_NAMES = {"acme", "hostco"}


@pytest.mark.parametrize(
    "source",
    [
        'if pid == "acme":\n    pass\n',
        'if slug != "acme":\n    pass\n',
        'if env.deploy_namespace == "acme":\n    pass\n',
        'merge(project="acme")\n',
        'resolve(project_id="acme")\n',
        'RECEIPT_PROJECT = "acme"\n',
        'HOST_SLUG = "hostco"\n',
        'conn.execute("SELECT 1 FROM projects WHERE slug = %s", ("acme",))\n',
        "Q = \"SELECT id FROM projects WHERE slug <> 'acme'\"\n",
        "Q = \"SELECT 'acme' as project FROM epic_tasks\"\n",
        'event = {"project": "acme"}\n',
        'resolve_project_github_auth("acme")\n',
        'def _canonical_project_label():\n    return "acme"\n',
    ],
)
def test_registered_project_name_bindings_are_flagged(source: str) -> None:
    hits = scan_source(_REL, source, _NAMES)
    assert len(hits) == 1, hits


@pytest.mark.parametrize(
    "source",
    [
        'if command_base != "acme":\n    pass\n',
        'if slug != "delegated-sync":\n    pass\n',
        'LAUNCHER = "acme"\n',
        'merge(project="unregistered")\n',
        'conn.execute("SELECT 1 WHERE name = %s", ("other",))\n',
    ],
)
def test_unregistered_names_and_cli_comparisons_pass(source: str) -> None:
    assert scan_source(_REL, source, _NAMES) == []


def test_classify_separates_violations_pending_and_stale_allowances() -> None:
    allowed = ProjectLiteralHit("a.py", 1, "X = 'acme'", "X")
    pending = ProjectLiteralHit("b.py", 2, "Y = 'acme'", "Y")
    violation = ProjectLiteralHit("c.py", 3, "Z = 'acme'", "Z")
    allowances = (
        Allowance("a.py", "X", "named reason"),
        Allowance("b.py", "Y", "replacement in flight", pending=True),
        Allowance("d.py", "W", "no longer present"),
    )

    violations, pending_hits, stale = classify(
        [allowed, pending, violation], allowances
    )

    assert violations == [violation]
    assert pending_hits == [pending]
    assert [a.relpath for a in stale] == ["d.py"]
