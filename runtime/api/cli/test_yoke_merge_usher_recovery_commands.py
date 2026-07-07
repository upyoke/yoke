"""Tests for the merge-audit and usher-reconcile tool-shaped commands."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from yoke_cli import operation_inventory as inv
from yoke_cli import product_boundary_inventory as boundary_inventory
from yoke_cli.commands.merge_audit import merge_audit
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_cli.commands.usher_reconcile import usher_reconcile_github
from yoke_cli.main import main as cli_main
from yoke_cli.product_boundary_teaching import generate_teaching_audit


REPO_ROOT = Path(__file__).resolve().parents[3]
CONDUCT_VERIFY = ".agents/skills/yoke/conduct/dispatch-context-verify.md"
MERGE_SKILL = ".agents/skills/yoke/merge/SKILL.md"
USHER_COLLECT = ".agents/skills/yoke/usher/collect.md"


def test_merge_audit_token_resolves() -> None:
    resolved = resolve_tool_shaped(["merge", "audit", "YOK-42"])

    assert resolved is not None
    adapter, rest = resolved
    assert adapter is merge_audit
    assert rest == ["YOK-42"]


def test_usher_reconcile_token_resolves() -> None:
    resolved = resolve_tool_shaped(
        ["usher", "reconcile-github", "YOK-42", "--workflow-run-id", "99"]
    )

    assert resolved is not None
    adapter, rest = resolved
    assert adapter is usher_reconcile_github
    assert rest == ["YOK-42", "--workflow-run-id", "99"]


def test_merge_audit_forwards_filter_to_engine(capsys) -> None:
    calls: list[int | None] = []

    def fake_generate_report(epic_filter=None):
        calls.append(epic_filter)
        return f"report:{epic_filter}\n"

    module = SimpleNamespace(generate_report=fake_generate_report)
    with patch(
        "yoke_cli.commands.merge_audit.importlib.import_module",
        return_value=module,
    ):
        assert cli_main(["merge", "audit", "YOK-42"]) == 0

    assert calls == [42]
    assert capsys.readouterr().out == "report:42\n"


def test_merge_audit_help_uses_yoke_surface() -> None:
    out, err = io.StringIO(), io.StringIO()

    with redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(["merge", "audit", "--help"])

    assert rc == 0
    assert "usage: yoke merge audit" in out.getvalue()
    assert "python3 -m yoke_core.engines.merge_audit" not in out.getvalue()
    assert err.getvalue() == ""


def test_top_level_help_lists_recovery_commands() -> None:
    out, err = io.StringIO(), io.StringIO()

    with redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(["--help"])

    help_text = out.getvalue()
    assert rc == 0
    assert "yoke merge audit" in help_text
    assert "yoke usher reconcile-github" in help_text
    assert "client-local helper (no function id)" in help_text
    assert err.getvalue() == ""


def test_merge_audit_invalid_filter_stays_in_cli_layer() -> None:
    out, err = io.StringIO(), io.StringIO()

    with patch(
        "yoke_cli.commands.merge_audit.importlib.import_module",
        side_effect=AssertionError("engine import should not happen"),
    ):
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli_main(["merge", "audit", "not-an-id"])

    assert rc == 2
    assert out.getvalue() == ""
    assert "invalid epic ID" in err.getvalue()


def test_usher_reconcile_forwards_to_engine_main() -> None:
    calls: list[list[str]] = []

    def fake_main(argv):
        calls.append(list(argv))
        return 7

    module = SimpleNamespace(main=fake_main)
    with patch(
        "yoke_cli.commands.usher_reconcile.importlib.import_module",
        return_value=module,
    ):
        assert cli_main(
            ["usher", "reconcile-github", "YOK-42", "--workflow-run-id", "99"]
        ) == 7

    assert calls == [["YOK-42", "--workflow-run-id", "99"]]


def test_usher_reconcile_help_uses_yoke_surface() -> None:
    out, err = io.StringIO(), io.StringIO()

    with redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(["usher", "reconcile-github", "--help"])

    assert rc == 0
    assert "usage: yoke usher reconcile-github" in out.getvalue()
    assert "yoke_core.engines.usher_reconcile_github" not in out.getvalue()
    assert err.getvalue() == ""


def test_operation_inventory_marks_recovery_commands_tool_shaped() -> None:
    for shell_form in ("yoke merge audit", "yoke usher reconcile-github"):
        entry = inv.lookup(shell_form)

        assert entry is not None
        assert entry.status == inv.PERMANENT
        assert entry.reason == inv.REASON_TOOL_SHAPED


def test_product_boundary_inventory_classifies_recovery_commands() -> None:
    rows = {
        row.command_helper: row
        for row in boundary_inventory.generate_inventory(repo_root=REPO_ROOT)
    }

    for shell_form in ("yoke merge audit", "yoke usher reconcile-github"):
        row = rows[shell_form]
        assert row.disposition == boundary_inventory.SOURCE_DEV_ADMIN
        assert row.function_id is None
        assert row.transport_branch == "source-dev-admin-local"
        assert {edge.classification for edge in row.import_edges} == {
            "source_dev_admin"
        }


def test_skills_teach_yoke_commands_not_internal_modules() -> None:
    audit = generate_teaching_audit(repo_root=REPO_ROOT)
    rows = {
        (row.source, row.recipe): row
        for row in audit.surfaces
        if row.source in {CONDUCT_VERIFY, MERGE_SKILL, USHER_COLLECT}
    }

    assert not any(
        row.source == CONDUCT_VERIFY and "timeout_portable" in row.recipe
        for row in rows.values()
    )
    assert rows[(MERGE_SKILL, "yoke merge audit {epic-id-if-provided}")].resolution == (
        "tool_shaped"
    )
    assert rows[(USHER_COLLECT, "yoke usher reconcile-github YOK-N")].resolution == (
        "tool_shaped"
    )
