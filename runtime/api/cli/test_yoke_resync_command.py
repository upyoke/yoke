"""Tests for the tool-shaped ``yoke resync`` command."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli import operation_inventory as inv
from yoke_cli import product_boundary_inventory as boundary_inventory
from yoke_cli.commands.resync import resync
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_cli.main import main as cli_main
from yoke_cli.product_boundary_teaching import generate_teaching_audit


REPO_ROOT = Path(__file__).resolve().parents[3]
RESYNC_SKILL = ".agents/skills/yoke/resync/SKILL.md"


class TestResyncCommand:
    def test_token_resolves(self) -> None:
        resolved = resolve_tool_shaped(["resync", "--fix"])

        assert resolved is not None
        adapter, rest = resolved
        assert adapter is resync
        assert rest == ["--fix"]

    def test_default_invocation_forwards_detect_only(self) -> None:
        calls: list[list[str]] = []

        def fake_main(argv):
            calls.append(list(argv))
            return 0

        module = SimpleNamespace(main=fake_main)
        with patch(
            "yoke_cli.commands.resync.importlib.import_module",
            return_value=module,
        ):
            assert cli_main(["resync"]) == 0

        assert calls == [["--detect-only"]]

    def test_fix_invocation_forwards_fix(self) -> None:
        calls: list[list[str]] = []

        def fake_main(argv):
            calls.append(list(argv))
            return 7

        module = SimpleNamespace(main=fake_main)
        with patch(
            "yoke_cli.commands.resync.importlib.import_module",
            return_value=module,
        ):
            assert cli_main(["resync", "--fix"]) == 7

        assert calls == [["--fix"]]

    def test_help_renders_sanctioned_surface(self) -> None:
        out, err = io.StringIO(), io.StringIO()

        with redirect_stdout(out), redirect_stderr(err):
            rc = cli_main(["resync", "--help"])

        assert rc == 0
        assert "usage: yoke resync" in out.getvalue()
        assert "python3 -m yoke_core.engines.resync" not in out.getvalue()
        assert err.getvalue() == ""

    def test_import_failure_reports_source_dev_admin_runtime(self) -> None:
        with patch(
            "yoke_cli.commands.resync.importlib.import_module",
            side_effect=ImportError("missing core"),
        ):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = cli_main(["resync"])

        assert rc == 1
        assert out.getvalue() == ""
        assert "source-dev/admin runtime" in err.getvalue()


def test_operation_inventory_marks_resync_tool_shaped() -> None:
    entry = inv.lookup("yoke resync")

    assert entry is not None
    assert entry.status == inv.PERMANENT
    assert entry.reason == inv.REASON_TOOL_SHAPED


def test_product_boundary_inventory_classifies_resync_source_dev_admin() -> None:
    rows = {
        row.command_helper: row
        for row in boundary_inventory.generate_inventory(repo_root=REPO_ROOT)
    }

    row = rows["yoke resync"]
    assert row.disposition == boundary_inventory.SOURCE_DEV_ADMIN
    assert row.function_id is None
    assert {edge.classification for edge in row.import_edges} == {"source_dev_admin"}


def test_resync_skill_teaches_yoke_command_not_internal_engine() -> None:
    audit = generate_teaching_audit(repo_root=REPO_ROOT)
    rows = [row for row in audit.surfaces if row.source == RESYNC_SKILL]

    assert not any(
        row.recipe.startswith("python3 -m yoke_core.engines.resync")
        for row in rows
    )
    assert any(
        row.recipe == "yoke resync" and row.resolution == "tool_shaped"
        for row in rows
    )
    assert any(
        row.recipe == "yoke resync --fix" and row.resolution == "tool_shaped"
        for row in rows
    )
