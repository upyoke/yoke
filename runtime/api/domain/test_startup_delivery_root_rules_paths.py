"""The rules channel resolves in both layouts the report has to run in.

A Yoke source checkout keeps the Claude session rules at the renderer's source
path and exposes the installed path as a symlink to it. An external project has
no ``runtime/`` tree at all and carries the bundle's real file at the installed
path. Measuring only the source path reported zero bytes for that contributor in
every external checkout — understating the channel exactly where a project's own
rules grow, and reading as headroom instead of as a gap.

Sibling of ``test_startup_delivery_budget.py``, which holds the per-channel
budget coverage and is at the authored-file line cap.
"""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.project_contract.installed_layer import CLAUDE_RULES_DEST
from yoke_core.domain import startup_delivery_budget as delivery
from yoke_core.domain.install_bundle import CLAUDE_RULES_SOURCE


def _repo_root() -> Path:
    from runtime.api.domain.test_agents_render_workspace_fixtures import (
        resolve_live_repo_root,
    )

    return resolve_live_repo_root()


def _claude_root_rules(root: Path) -> dict:
    report = delivery.startup_delivery_report(root)
    return next(
        row
        for row in report["channels"]
        if row["harness_id"] == "claude" and row["channel"] == "root_rules"
    )


def test_root_rules_resolve_in_an_installed_checkout(tmp_path) -> None:
    """An external project has no ``runtime/`` tree, only the installed path.

    Measuring the source path alone reported zero bytes for the Claude session
    rules in every external checkout — understating the channel exactly where
    it is most likely to be over, because a project's own rules grow there.
    """
    (tmp_path / "AGENTS.md").write_text("x" * 100, encoding="utf-8")
    installed = tmp_path / CLAUDE_RULES_DEST
    installed.mkdir(parents=True)
    (installed / "session.md").write_text("y" * 40, encoding="utf-8")
    assert not (tmp_path / "runtime").exists()

    claude = _claude_root_rules(tmp_path)
    assert claude["bytes"] == 140, claude["contributors"]
    paths = [c["path"] for c in claude["contributors"] if c.get("resolved")]
    assert f"{CLAUDE_RULES_DEST}/session.md" in paths


def test_root_rules_prefer_the_source_path_in_a_yoke_checkout() -> None:
    """In the source tree the installed path is a symlink to the source one.

    First-match resolution therefore counts the file once rather than twice,
    and names the source path it actually read.
    """
    claude = _claude_root_rules(_repo_root())
    paths = [c["path"] for c in claude["contributors"] if c.get("resolved")]
    assert f"{CLAUDE_RULES_SOURCE}/session.md" in paths
    assert len(paths) == len(set(paths))
    assert claude["bytes"] == sum(
        c["bytes"] for c in claude["contributors"] if c.get("resolved")
    )


def test_an_unresolvable_contributor_is_named_not_counted_as_zero(tmp_path) -> None:
    """A contributor nobody can find is a measurement gap, not headroom."""
    (tmp_path / "AGENTS.md").write_text("x" * 100, encoding="utf-8")

    claude = _claude_root_rules(tmp_path)
    unresolved = [c for c in claude["contributors"] if not c.get("resolved")]
    assert len(unresolved) == 1
    assert CLAUDE_RULES_SOURCE in unresolved[0]["path"]
    assert CLAUDE_RULES_DEST in unresolved[0]["path"]
