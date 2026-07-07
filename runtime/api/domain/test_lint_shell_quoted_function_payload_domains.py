"""AC-3 / AC-5 / AC-19 — domain-only remediation copy.

Split from ``test_lint_shell_quoted_function_payload.py`` so the parent
file stays under the 350-line authored-file budget. Covers invocations
in a known Yoke CLI domain whose subcommand path is not a registered
function-call adapter (or is bare module / ``--help``): the lint must
surface the domain-level copy and MUST NOT attribute the invocation to
an unrelated function id.

Also home for the read-shape regression coverage and the
newline-boundary regression introduced when ``_find_boundary``
gained ``\\n`` as a subcommand terminator.
"""

from __future__ import annotations

import unittest

from yoke_core.domain import lint_shell_quoted_function_payload as lint
from yoke_core.domain.lint_shell_quoted_function_payload_classify import (
    extract_subcommand_path,
)


class TestDomainOnlyHits(unittest.TestCase):
    def test_epic_review_insert_pipe_blocks_with_domain_copy(self) -> None:
        cmd = (
            "printf 'verdict body' | python3 -m yoke_core.cli.db_router "
            "epic review-insert 1234 1 PASS"
        )
        reason = lint.evaluate_command(cmd)
        self.assertIsNotNone(reason)
        self.assertIn("Yoke CLI domain", reason)
        self.assertIn("yoke_core.cli.db_router", reason)
        self.assertNotIn("workflow_item.epic_progress_note.append", reason)

    def test_epic_review_insert_compact_pipe_blocks_with_domain_copy(
        self,
    ) -> None:
        cmd = (
            "printf 'verdict body'|python3 -m yoke_core.cli.db_router "
            "epic review-insert 1234 1 PASS"
        )
        reason = lint.evaluate_command(cmd)
        self.assertIsNotNone(reason)
        self.assertIn("Yoke CLI domain", reason)
        self.assertNotIn("workflow_item.epic_progress_note.append", reason)

    def test_epic_review_insert_heredoc_blocks_with_domain_copy(self) -> None:
        cmd = (
            "cat << 'REPORT' | python3 -m yoke_core.cli.db_router "
            "epic review-insert 1234 1 PASS\nbody\nREPORT"
        )
        reason = lint.evaluate_command(cmd)
        self.assertIsNotNone(reason)
        self.assertIn("Yoke CLI domain", reason)
        self.assertNotIn("workflow_item.epic_progress_note.append", reason)

    def test_items_get_pipe_to_head_does_not_attribute_to_update(self) -> None:
        # ``items get | head`` must NOT block with the over-broad
        # ``items.structured_field.replace`` attribution.
        cmd = (
            "python3 -m yoke_core.cli.db_router items get YOK-1234 spec "
            "| head -50"
        )
        reason = lint.evaluate_command(cmd)
        if reason is not None:
            self.assertNotIn("items.structured_field.replace", reason)

    def test_db_router_lifecycle_bare_subcommand_blocks_with_domain_copy(
        self,
    ) -> None:
        cmd = "python3 -m yoke_core.cli.db_router lifecycle 2>&1"
        reason = lint.evaluate_command(cmd)
        self.assertIsNotNone(reason)
        self.assertIn("Yoke CLI domain", reason)
        self.assertNotIn("items.structured_field.replace", reason)

    def test_db_router_help_with_pipe_to_head_allowed(self) -> None:
        # S1 (Class C): top-level ``--help`` short-circuits the lint,
        # even when wrapped with ``| head`` (read pipe). This unblocks
        # operators grounding via ``--help`` before authoring a command.
        cmd = "python3 -m yoke_core.cli.db_router --help | head -40"
        self.assertIsNone(lint.evaluate_command(cmd))

    def test_service_client_help_with_pipe_to_grep_allowed(self) -> None:
        # S1: ``service_client --help | grep claim`` — ``--help``
        # short-circuit takes precedence over domain detection.
        cmd = "python3 -m yoke_core.api.service_client --help | grep claim"
        self.assertIsNone(lint.evaluate_command(cmd))

    def test_service_client_backlog_freeze_help_allowed(self) -> None:
        # S1: subcommand-level ``--help`` short-circuits even with
        # ``2>&1 | head`` wrapping.
        cmd = (
            "python3 -m yoke_core.api.service_client backlog-cli "
            "freeze --help 2>&1 | head -40"
        )
        self.assertIsNone(lint.evaluate_command(cmd))


class TestReadShapeWithPipesAllowed(unittest.TestCase):
    """AC-47 — exact read-shape regressions.

    Reads (``items get``, ``events list``, etc.) wrapped with read-only
    downstream pipes (``2>&1 | head``, ``| jq .``) MUST be allowed. The
    write-vs-read classifier owns this distinction; these cases are the
    operator-observed shapes from the friction sweep.
    """

    def test_items_get_with_stderr_merge_head_allowed(self) -> None:
        cmd = (
            "python3 -m yoke_core.cli.db_router items get YOK-1234 spec "
            "--json 2>&1 | head"
        )
        self.assertIsNone(lint.evaluate_command(cmd))

    def test_items_get_with_jq_filter_allowed(self) -> None:
        cmd = (
            "python3 -m yoke_core.cli.db_router items get YOK-1234 spec "
            "--json | jq ."
        )
        self.assertIsNone(lint.evaluate_command(cmd))

    def test_events_list_with_stderr_merge_head_allowed(self) -> None:
        cmd = (
            "python3 -m yoke_core.cli.db_router events list --since "
            "'1 hour ago' 2>&1 | head"
        )
        self.assertIsNone(lint.evaluate_command(cmd))


class TestNewlineSubcommandTerminator(unittest.TestCase):
    """AC-48 — newline terminates the parsed subcommand path.

    The parser must not walk a top-level newline into the next command,
    or a cleanup-on-next-line (``rm -f $tmpfile``) gets folded into the
    detected adapter call and the lint denies the wrong shape.
    """

    def test_extract_subcommand_path_stops_at_top_level_newline(
        self,
    ) -> None:
        tail = " lifecycle\nrm -f /tmp/foo 2>&1"
        self.assertEqual(extract_subcommand_path(tail), "lifecycle")

    def test_extract_subcommand_path_excludes_next_line_cleanup(
        self,
    ) -> None:
        tail = " items get YOK-1234 spec\nrm -f /tmp/foo"
        self.assertEqual(
            extract_subcommand_path(tail), "items get YOK-1234 spec",
        )

    def test_domain_only_denial_names_only_first_line_subcommand(
        self,
    ) -> None:
        # The reproducer the refinement called out: a domain-only
        # invocation followed by ``rm -f`` on the next line must report
        # the detected subcommand path WITHOUT the cleanup folded in.
        cmd = (
            "python3 -m yoke_core.cli.db_router lifecycle\n"
            "rm -f /tmp/foo 2>&1"
        )
        reason = lint.evaluate_command(cmd)
        self.assertIsNotNone(reason)
        self.assertIn("``lifecycle``", reason)
        self.assertNotIn("rm -f", reason)


if __name__ == "__main__":
    unittest.main()
