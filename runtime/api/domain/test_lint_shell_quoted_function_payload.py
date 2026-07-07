"""Tests for yoke_core.domain.lint_shell_quoted_function_payload.

Covers hand-quoted JSON payload, registry-covered shell choreography
(precise function id), and domain-only invocations (no function id
attribution; the operator sees the registered subcommands listed).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from yoke_core.domain import lint_shell_quoted_function_payload as lint
from runtime.harness.hook_runner.types import Next, Outcome


def _payload(command: str) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }


def _record_for(payload: dict) -> "lint.HookContext":
    return lint._build_context_from_payload(payload)


class TestHandQuotedJsonPayload(unittest.TestCase):
    """Hand-quoted JSON payload to service_client is blocked."""

    def test_printf_pipe_payload_blocks(self) -> None:
        cmd = (
            "printf '{\"function\":\"items.scalar.update\",\"target\":{}}'"
            " | python3 -m yoke_core.api.service_client functions-call --payload -"
        )
        reason = lint.evaluate_command(cmd)
        self.assertIsNotNone(reason)
        self.assertIn("BLOCKED", reason)
        self.assertIn("hand-quoted JSON payload", reason)
        self.assertIn("FunctionCallRequest", reason)

    def test_inline_json_payload_blocks(self) -> None:
        cmd = (
            "python3 -m yoke_core.api.service_client db-claim-amend "
            "--item YOK-9001 --payload '{\"state\":\"declared\"}'"
        )
        reason = lint.evaluate_command(cmd)
        self.assertIsNotNone(reason)
        self.assertIn("hand-quoted JSON payload", reason)

    def test_dash_payload_with_real_file_is_allowed(self) -> None:
        # --payload <file> (no quoted JSON) is fine.
        cmd = (
            "python3 -m yoke_core.api.service_client db-claim-amend "
            "--item YOK-9001 --payload-file /tmp/claim.json"
        )
        self.assertIsNone(lint.evaluate_command(cmd))


class TestRegistryCoveredShellChoreography(unittest.TestCase):
    """Registry-covered CLI wrapped with shell choreography blocks with
    the precise function id. S2 carves out READ-shape adapters wrapped
    only with read-only shell shapes; mutation wrappers still deny."""

    def test_read_shape_with_read_wrapping_allowed(self) -> None:
        # S2 regression: every shape below is a READ-shape adapter
        # (no side effects) wrapped only by read-only shell shapes
        # (stderr merge, shell-variable capture, clean / --json call).
        for cmd in (
            "python3 -m yoke_core.cli.db_router projects has-capability "
            "yoke ephemeral-env 2>&1",
            "_cap=$(python3 -m yoke_core.cli.db_router projects "
            "has-capability yoke ephemeral-env)",
            "python3 -m yoke_core.cli.db_router projects has-capability "
            "yoke ephemeral-env",
            "python3 -m yoke_core.cli.db_router projects has-capability "
            "yoke ephemeral-env --json",
        ):
            self.assertIsNone(lint.evaluate_command(cmd), msg=cmd)

    def test_mutation_choreography_still_denies(self) -> None:
        # ``; echo $?`` clause has a non-read verb. ``| tee`` writes a
        # file. Mutation-shape adapters (items.structured_field.replace)
        # keep the existing deny path with their precise function id.
        for cmd, expected_id in (
            (
                "python3 -m yoke_core.cli.db_router projects has-capability "
                "yoke ephemeral-env; echo $?",
                "projects.capability.has",
            ),
            (
                "python3 -m yoke_core.cli.db_router events list "
                "--item YOK-9001 | tee /tmp/events.log",
                "events.query.run",
            ),
            (
                "python3 -m yoke_core.cli.db_router items update 1234 "
                "spec --stdin <<'EOF'\nbody\nEOF",
                "items.structured_field.replace",
            ),
        ):
            reason = lint.evaluate_command(cmd)
            self.assertIsNotNone(reason, msg=cmd)
            self.assertIn("registry-covered Yoke CLI", reason, msg=cmd)
            self.assertIn(expected_id, reason, msg=cmd)

    def test_unrelated_and_empty_commands_allowed(self) -> None:
        self.assertIsNone(lint.evaluate_command("git status"))
        self.assertIsNone(lint.evaluate_command(""))


class TestEvaluateDenyMode(unittest.TestCase):
    """Deny mode emits a deny envelope."""

    def test_evaluate_blocks_in_deny_mode(self) -> None:
        cmd = (
            "printf '{\"function\":\"x\"}' | python3 -m yoke_core.api.service_client"
            " functions-call --payload -"
        )
        with (
            mock.patch.object(lint, "_emit_denial"),
            mock.patch.object(lint, "_resolve_mode", return_value="deny"),
        ):
            decision = lint.evaluate(_record_for(_payload(cmd)))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertIs(decision.next, Next.STOP)
        decoded = json.loads(decision.message)
        self.assertEqual(
            decoded["hookSpecificOutput"]["permissionDecision"], "deny",
        )

    def test_evaluate_warns_only_in_warn_mode(self) -> None:
        cmd = (
            "printf '{\"function\":\"x\"}' | python3 -m yoke_core.api.service_client"
            " functions-call --payload -"
        )
        outcomes = []
        with (
            mock.patch.object(
                lint,
                "_emit_denial",
                lambda _p, _r, *, outcome="denied": outcomes.append(outcome),
            ),
            mock.patch.object(lint, "_resolve_mode", return_value="warn"),
        ):
            decision = lint.evaluate(_record_for(_payload(cmd)))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertEqual(outcomes, ["warn"])

    def test_evaluate_allows_safe_command(self) -> None:
        with mock.patch.object(lint, "_emit_denial"):
            decision = lint.evaluate(_record_for(_payload("git status")))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertFalse(decision.block)


class TestSuppressionToken(unittest.TestCase):
    """Suppression token is audit-only — the rule still denies."""

    def test_token_emits_suppression_attempted_audit(self) -> None:
        cmd = (
            "printf '{\"x\":1}' | python3 -m yoke_core.api.service_client "
            "functions-call --payload - "
            "# lint:no-shell-json-payload-check"
        )
        outcomes = []
        with (
            mock.patch.object(
                lint,
                "_emit_denial",
                lambda _p, _r, *, outcome="denied": outcomes.append(outcome),
            ),
            mock.patch.object(lint, "_resolve_mode", return_value="deny"),
        ):
            decision = lint.evaluate(_record_for(_payload(cmd)))
        self.assertEqual(outcomes, ["suppression_attempted"])
        self.assertIs(decision.outcome, Outcome.NOOP)


class TestConfigModeResolution(unittest.TestCase):
    """Mode reads from machine config honor warn / deny / default."""

    def test_resolve_mode_delegates_to_registry(self) -> None:
        # Mode now resolves through the single lint_config registry; per-key /
        # per-value parsing + the protected clamp are covered by test_lint_config.
        from yoke_core.domain import lint_config as registry

        with mock.patch.object(
            registry, "resolve_mode_for_payload", return_value="warn",
        ) as m:
            self.assertEqual(lint._resolve_mode(), "warn")
        m.assert_called_once_with("lint_shell_quoted_function_payload", None)


class TestHelpExemption(unittest.TestCase):
    """S1 / Class C: ``--help`` and ``-h`` short-circuit the lint."""

    def test_help_invocations_allowed(self) -> None:
        for cmd in (
            "python3 -m yoke_core.api.service_client --help",
            "python3 -m yoke_core.cli.db_router items get --help",
            "python3 -m yoke_core.cli.db_router epic "
            "progress-note-insert --help",
            "python3 -m yoke_core.cli.db_router items update -h",
        ):
            self.assertIsNone(
                lint.evaluate_command(cmd), f"expected allow for: {cmd}"
            )


class TestReadPipeTruncationAndScope(unittest.TestCase):
    """S2 / S9: read-shape adapters allow read wrapping; outer-token scope
    keeps adapter detection out of quoted/heredoc bodies."""

    def test_read_pipe_and_capture_allowed(self) -> None:
        for cmd in (
            # Pipe to head/grep on items get (read-shape).
            "python3 -m yoke_core.cli.db_router items get YOK-1700 spec "
            "| head -200",
            "python3 -m yoke_core.cli.db_router items get YOK-1700 spec "
            "| grep '^##'",
            # Adapter mentioned only inside a quoted commit message.
            "git -C /repo commit -m \"$(cat <<'EOF'\nUse "
            "python3 -m yoke_core.engines.doctor --list\nEOF\n)\"",
            "echo \"see python3 -m yoke_core.cli.db_router items get for details\"",
        ):
            self.assertIsNone(
                lint.evaluate_command(cmd), f"expected allow for: {cmd}"
            )

    def test_mutation_pipe_still_denies(self) -> None:
        # MUTATE-shape (items.structured_field.replace) + mutation
        # wrapping (``| tee /tmp/...``) still denies.
        cmd = (
            "python3 -m yoke_core.cli.db_router items update YOK-1700 "
            "spec --stdin | tee /tmp/x"
        )
        self.assertIsNotNone(lint.evaluate_command(cmd))


class TestSubcommandPathTokenization(unittest.TestCase):
    """S10 / Class M: subcommand-path extraction stops at shell boundaries."""

    def _tail(self, cmd: str) -> str:
        located = lint._find_registry_covered_adapter(cmd)
        self.assertIsNotNone(located)
        return (
            getattr(located, "command_tail", None)
            or getattr(located, "adapter_key", "").split(" ", 1)[1]
        )

    def test_pipe_chain_extracts_subcommand_only(self) -> None:
        cmd = (
            "python3 -m yoke_core.cli.db_router epic "
            "progress-note-list-unsynced 1700 2>&1 | grep -E '\\s7\\s' "
            "| head -10"
        )
        self.assertEqual(self._tail(cmd), "epic progress-note-list-unsynced 1700")

    def test_redirect_then_compound_extracts_subcommand_only(self) -> None:
        cmd = (
            "python3 -m yoke_core.cli.db_router epic task-get-body "
            "1700 7 > /tmp/yoke-task007-spec.md 2>&1; wc -l "
            "/tmp/yoke-task007-spec.md"
        )
        self.assertEqual(self._tail(cmd), "epic task-get-body 1700 7")


class TestAdapterIndex(unittest.TestCase):
    """AC-1: the adapter index carries only ``"<module> <sub-path>"`` keys
    — no bare-module fallback."""

    def test_subcommand_aware_keys_present(self) -> None:
        # Spot-check that registered ``<module> <sub-path>`` pairs are
        # present in the new index shape.
        self.assertIn(
            "yoke_core.cli.db_router items update", lint._ADAPTER_INDEX,
        )
        self.assertIn(
            "yoke_core.cli.db_router items get", lint._ADAPTER_INDEX,
        )
        self.assertIn(
            "yoke_core.cli.db_router epic progress-note-list-unsynced",
            lint._ADAPTER_INDEX,
        )
        self.assertIn(
            "yoke_core.cli.db_router projects has-capability",
            lint._ADAPTER_INDEX,
        )
        self.assertIn(
            "yoke_core.api.service_client db-claim-amend",
            lint._ADAPTER_INDEX,
        )

    def test_bare_module_keys_absent(self) -> None:
        # The bare-module fallback is gone. Each known module
        # appears only inside ``"<module> <sub-path>"`` keys.
        self.assertNotIn(
            "yoke_core.cli.db_router", lint._ADAPTER_INDEX,
        )
        self.assertNotIn(
            "yoke_core.api.service_client", lint._ADAPTER_INDEX,
        )

    def test_registered_subs_by_module_populated(self) -> None:
        subs = lint._REGISTERED_SUBS_BY_MODULE.get(
            "yoke_core.cli.db_router", [],
        )
        self.assertIn("items update", subs)
        self.assertIn("items get", subs)
        self.assertIn("epic progress-note-list-unsynced", subs)
        self.assertIn("projects has-capability", subs)
        # subs is sorted for stable remediation copy.
        self.assertEqual(subs, sorted(subs))


if __name__ == "__main__":
    unittest.main()
