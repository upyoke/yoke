"""Readiness resolves the item project's checkout, or reports it missing.

The resolver has no ambient fallback on purpose. A hosted API host has no
project checkout, so a walk-up / cwd / ``git rev-parse`` fallback either
raised there (crashing the readiness handler) or silently validated an item
against whatever tree the server process stood in. ``None`` here means the
file-reading checks cannot run on this host — never "use another tree".
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from yoke_core.domain import idea_readiness_checkout as checkout
from yoke_core.domain.idea_readiness_checkout import (
    CHECKOUT_DEPENDENT_CHECKS,
    CHECKOUT_UNAVAILABLE_REASON,
    checkout_unavailable,
    item_project_checkout,
    unavailable_checkout_dependent_checks,
)


class _Row(list):
    pass


class _Conn:
    """Minimal stand-in returning one row for the item/project lookup."""

    def __init__(self, row):
        self._row = row

    def execute(self, _sql, _params=None):
        conn = self

        class _Cursor:
            def fetchone(self):
                return conn._row

        return _Cursor()


@pytest.fixture
def mapped_checkout(tmp_path, monkeypatch):
    root = tmp_path / "project-checkout"
    root.mkdir()
    monkeypatch.setattr(
        checkout, "checkout_for_project_id", lambda project_id: root,
    )
    return root


def test_resolves_the_item_projects_registered_checkout(mapped_checkout):
    conn = _Conn(_Row([7, "some-project"]))
    assert item_project_checkout(conn, 4101) == mapped_checkout


def test_unmapped_project_resolves_to_none(monkeypatch):
    monkeypatch.setattr(
        checkout, "checkout_for_project_id", lambda project_id: None,
    )
    conn = _Conn(_Row([7, "some-project"]))
    assert item_project_checkout(conn, 4101) is None


def test_mapped_path_that_is_not_a_directory_resolves_to_none(
    tmp_path, monkeypatch,
):
    missing = tmp_path / "was-deleted"
    monkeypatch.setattr(
        checkout, "checkout_for_project_id", lambda project_id: missing,
    )
    conn = _Conn(_Row([7, "some-project"]))
    assert item_project_checkout(conn, 4101) is None


def test_no_item_context_resolves_to_none_without_touching_cwd(monkeypatch):
    """No item means no project, so there is no checkout to resolve."""

    def _explode(_project_id):
        raise AssertionError("must not resolve a checkout without a project")

    monkeypatch.setattr(checkout, "checkout_for_project_id", _explode)
    assert item_project_checkout(None, 0) is None
    assert item_project_checkout(None, 4101) is None


def test_unknown_item_resolves_to_none():
    assert item_project_checkout(_Conn(None), 4101) is None


def test_unavailable_result_is_named_non_retryable_and_actionable():
    conn = _Conn(_Row([7, "some-project"]))
    result = checkout_unavailable("verify_function_owners", conn, 4101)
    assert result.check == "verify_function_owners"
    assert result.reason == CHECKOUT_UNAVAILABLE_REASON
    assert result.retryable is False
    assert "some-project" in result.recovery
    assert "yoke project register" in result.recovery
    assert result.context == {"project_id": 7, "project": "some-project"}


def test_unavailable_recovery_never_suggests_the_hosted_host():
    """Installing a checkout on the API host is not a supported recovery."""
    result = checkout_unavailable("verify_function_owners", _Conn(None), 4101)
    assert "not installed on the hosted API host" in result.recovery


def test_every_checkout_dependent_check_is_reported_unperformed():
    results = unavailable_checkout_dependent_checks(_Conn(None), 4101)
    assert [r.check for r in results] == list(CHECKOUT_DEPENDENT_CHECKS)
    assert all(r.retryable is False for r in results)


def test_checkout_resolution_reads_no_ambient_repo_root():
    """The module carries no git / cwd / walk-up resolver to fall back to.

    Structural rather than behavioral: an ambient fallback reintroduced here
    would make every caller silently validate against the wrong tree, which
    no single behavioral case can catch.
    """
    tree = ast.parse(Path(checkout.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "subprocess" not in imported

    referenced = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert "find_repo_root" not in referenced
    assert "cwd" not in referenced
    assert "getcwd" not in referenced
