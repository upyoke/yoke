"""Tests for the canonical operation tracker.

Covers AC-TRACKER: the tracker carries one ``OperationEntry`` per
operation surfaced by AC-1's audit, with self-consistent shape rules:

* Every entry's status / reason is in the closed enum.
* status=pending rows MUST carry proposed_function_id.
* status=(wrapped|permanent) rows MUST NOT carry proposed_function_id.
* No two entries share the same shell_form.
* Lookup helpers round-trip.
"""

from __future__ import annotations

import pytest

from yoke_cli import operation_inventory as inv


class TestOperationEntryValidation:
    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValueError):
            inv.OperationEntry(
                shell_form="x", family="y",
                status="not-a-status",
                reason=inv.REASON_WRAPPED_BY_YOKE_CLI,
            )

    def test_invalid_reason_rejected(self) -> None:
        with pytest.raises(ValueError):
            inv.OperationEntry(
                shell_form="x", family="y",
                status=inv.WRAPPED, reason="not-a-reason",
            )

    def test_pending_without_function_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            inv.OperationEntry(
                shell_form="x", family="y",
                status=inv.PENDING,
                reason=inv.REASON_NO_HANDLER_REGISTERED,
            )

    def test_wrapped_with_function_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            inv.OperationEntry(
                shell_form="x", family="y",
                status=inv.WRAPPED,
                reason=inv.REASON_WRAPPED_BY_YOKE_CLI,
                proposed_function_id="foo.bar",
            )

    def test_permanent_with_function_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            inv.OperationEntry(
                shell_form="x", family="y",
                status=inv.PERMANENT,
                reason=inv.REASON_OPERATOR_BREAK_GLASS,
                proposed_function_id="foo.bar",
            )


class TestRegistryShape:
    def test_no_duplicate_shell_forms(self) -> None:
        seen = set()
        for entry in inv.all_entries():
            assert entry.shell_form not in seen, (
                f"duplicate shell_form: {entry.shell_form!r}"
            )
            seen.add(entry.shell_form)

    def test_wrapped_count_matches_source_rows(self) -> None:
        from yoke_cli.operation_inventory_data import WRAPPED_ROWS

        wrapped = inv.by_status(inv.WRAPPED)
        assert len(wrapped) == len(WRAPPED_ROWS)

    def test_every_wrapped_starts_with_yoke(self) -> None:
        for entry in inv.by_status(inv.WRAPPED):
            assert entry.shell_form.startswith("yoke "), (
                f"wrapped entry {entry.shell_form!r} should start with "
                "'yoke ' (the canonical agent CLI form)"
            )

    def test_every_pending_is_multi_module(self) -> None:
        allowed_prefixes = ("python3 -m yoke_core.",)
        for entry in inv.by_status(inv.PENDING):
            assert entry.shell_form.startswith(allowed_prefixes), (
                f"pending entry {entry.shell_form!r} should start with "
                f"{allowed_prefixes!r} (final package multi-module shape)"
            )

    def test_every_pending_has_proposed_function_id(self) -> None:
        for entry in inv.by_status(inv.PENDING):
            assert entry.proposed_function_id is not None
            assert entry.proposed_function_id

    def test_no_wrapped_carries_function_id(self) -> None:
        for entry in inv.by_status(inv.WRAPPED):
            assert entry.proposed_function_id is None

    def test_no_permanent_carries_function_id(self) -> None:
        for entry in inv.by_status(inv.PERMANENT):
            assert entry.proposed_function_id is None


class TestAccessors:
    def test_lookup_known_wrapped(self) -> None:
        entry = inv.lookup("yoke items get")
        assert entry is not None
        assert entry.status == inv.WRAPPED

    def test_db_read_wrapped_and_db_router_query_operator_debug(self) -> None:
        wrapped = inv.lookup("yoke db read")
        assert wrapped is not None
        assert wrapped.status == inv.WRAPPED
        assert wrapped.reason == inv.REASON_WRAPPED_BY_YOKE_CLI

        raw = inv.lookup("python3 -m yoke_core.cli.db_router query")
        assert raw is not None
        assert raw.status == inv.PERMANENT
        assert raw.reason == inv.REASON_OPERATOR_BREAK_GLASS

    @pytest.mark.parametrize(
        "shell_form",
        [
            "yoke core build",
            "yoke core start",
            "yoke core status",
            "yoke core logs",
            "yoke core stop",
            "yoke core upgrade",
        ],
    )
    def test_core_launcher_rows_are_permanent_tool_shaped(
        self, shell_form: str,
    ) -> None:
        entry = inv.lookup(shell_form)
        assert entry is not None
        assert entry.status == inv.PERMANENT
        assert entry.reason == inv.REASON_TOOL_SHAPED

    @pytest.mark.parametrize(
        "shell_form",
        [
            "yoke sessions touch",
            "yoke sessions checkpoint",
            "yoke sessions checkpoint-read",
            "yoke sessions offer",
            "yoke sessions ownership-guard",
            "yoke charge schedule",
        ],
    )
    def test_session_orchestration_rows_are_wrapped(
        self, shell_form: str,
    ) -> None:
        entry = inv.lookup(shell_form)
        assert entry is not None
        assert entry.status == inv.WRAPPED
        assert entry.reason == inv.REASON_WRAPPED_BY_YOKE_CLI

    def test_lookup_unknown_returns_none(self) -> None:
        assert inv.lookup("not a real shell form") is None

    def test_is_wrapped_true_for_wrapped(self) -> None:
        assert inv.is_wrapped("yoke items get") is True
        assert inv.is_wrapped("yoke db-claim amend") is True

    def test_is_wrapped_false_for_permanent(self) -> None:
        assert inv.is_wrapped(
            "python3 -m yoke_core.api.service_client coordination-lease-acquire"
        ) is False
        worktree = inv.lookup("python3 -m yoke_core.domain.worktree create")
        assert worktree is not None
        assert worktree.status == inv.PERMANENT
        assert worktree.reason == inv.REASON_TOOL_SHAPED

    def test_is_wrapped_false_for_pending(self) -> None:
        assert inv.is_wrapped(
            "python3 -m yoke_core.cli.db_router events list"
        ) is False

    def test_is_wrapped_false_for_unknown(self) -> None:
        assert inv.is_wrapped("not real") is False

    def test_by_status_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            inv.by_status("not-a-status")

    def test_by_shell_form_is_complete(self) -> None:
        d = inv.by_shell_form()
        assert len(d) == len(inv.all_entries())


class TestRegistryCoverage:
    """The tracker MUST cover every yoke subcommand registered today."""

    def test_every_registered_subcommand_is_wrapped(self) -> None:
        from yoke_cli.commands.registry import (
            SUBCOMMAND_ALIAS_REGISTRY,
            SUBCOMMAND_REGISTRY,
        )

        tracker_wrapped = {
            e.shell_form for e in inv.by_status(inv.WRAPPED)
        }
        for cli_tokens, _ in SUBCOMMAND_REGISTRY.items():
            shell_form = "yoke " + " ".join(cli_tokens)
            assert shell_form in tracker_wrapped, (
                f"registered subcommand {shell_form!r} missing from "
                "wrapped tracker entries"
            )
        # Operator-facing aliases share the tracker so the inventory
        # surface still teaches their existence.
        for cli_tokens, _ in SUBCOMMAND_ALIAS_REGISTRY.items():
            shell_form = "yoke " + " ".join(cli_tokens)
            assert shell_form in tracker_wrapped, (
                f"registered alias {shell_form!r} missing from "
                "wrapped tracker entries"
            )
