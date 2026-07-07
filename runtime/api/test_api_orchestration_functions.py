"""Unit tests for orchestration handlers — board.rebuild, packets.*, agents.render.*."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from yoke_core.domain.handlers import orchestration, orchestration_agents
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(function_id: str, payload=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


class TestBoardRebuild(unittest.TestCase):
    def test_returns_hash_and_line_count(self, tmp_dir=None):
        # AC-7.1: board.rebuild returns hash + line count.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            yoke_root = repo_root / ".yoke"
            yoke_root.mkdir()
            board_path = yoke_root / "BOARD.md"
            board_path.write_text("line1\nline2\nline3\n", encoding="utf-8")
            with patch(
                "yoke_core.domain.rebuild_board.rebuild", return_value=0,
            ):
                with patch(
                    "yoke_core.domain.rebuild_board.resolve_main_repo_root",
                    return_value=repo_root,
                ):
                    req = _request("board.rebuild.run", {"force": True})
                    outcome = orchestration.handle_board_rebuild(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["board_path"], str(board_path))
        self.assertEqual(outcome.result_payload["line_count"], 3)
        self.assertEqual(len(outcome.result_payload["sha256"]), 64)
        self.assertEqual(outcome.result_payload["exit_code"], 0)

    def test_nonzero_exit_surfaces_downstream_failure(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            yoke_root = Path(tmp)
            with patch(
                "yoke_core.domain.rebuild_board.rebuild", return_value=1,
            ):
                with patch(
                    "yoke_core.domain.rebuild_board.resolve_main_repo_root",
                    return_value=yoke_root,
                ):
                    with patch(
                        "yoke_core.domain.worktree.resolve_yoke_root",
                        return_value=str(yoke_root),
                    ):
                        req = _request("board.rebuild.run", {"force": True})
                        outcome = orchestration.handle_board_rebuild(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "downstream_failure")

    def test_nonzero_outcome_includes_rebuild_detail(self):
        import tempfile
        from yoke_core.domain import rebuild_board_outcome

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            board_path = repo_root / ".yoke" / "BOARD.md"
            result = rebuild_board_outcome.failed(
                board_path,
                "Python board renderer failed: kaboom",
            )
            with patch(
                "yoke_core.domain.rebuild_board.rebuild", return_value=result,
            ):
                with patch(
                    "yoke_core.domain.rebuild_board.resolve_main_repo_root",
                    return_value=repo_root,
                ):
                    req = _request("board.rebuild.run", {"force": True})
                    outcome = orchestration.handle_board_rebuild(req)

        self.assertFalse(outcome.primary_success)
        self.assertIn("status=failed", outcome.error.message)
        self.assertIn("Python board renderer failed: kaboom", outcome.error.message)
        self.assertEqual(
            outcome.result_payload["message"],
            "Python board renderer failed: kaboom",
        )

    def test_skips_without_local_checkout(self):
        # A server-side https board.rebuild has no repo: clean no-op success,
        # not a crash (the board is a client-local view rebuilt by the client).
        with patch(
            "yoke_core.domain.rebuild_board.try_resolve_main_repo_root",
            return_value=None,
        ):
            req = _request("board.rebuild.run", {})
            outcome = orchestration.handle_board_rebuild(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["status"], "skipped-no-checkout")
        self.assertIsNone(outcome.error)


class TestPacketsRender(unittest.TestCase):
    def test_rejects_missing_role(self):
        req = _request("packets.render.run", {})
        outcome = orchestration.handle_packets_render(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_returns_rendered_packet(self):
        with patch(
            "yoke_core.domain.schema_api_context.render_role_packet",
            return_value="fake packet body",
        ):
            req = _request("packets.render.run", {"role": "engineer_agent"})
            outcome = orchestration.handle_packets_render(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["role"], "engineer_agent")
        self.assertEqual(outcome.result_payload["body"], "fake packet body")
        self.assertEqual(outcome.result_payload["byte_count"], 16)


class TestPacketsCheck(unittest.TestCase):
    def test_no_drift_returns_seed_ok(self):
        with patch(
            "yoke_core.domain.schema_api_context.detect_seed_drift",
            return_value=[],
        ):
            req = _request("packets.check.run", {})
            outcome = orchestration.handle_packets_check(req)
        self.assertTrue(outcome.primary_success)
        self.assertTrue(outcome.result_payload["seed_ok"])

    def test_drift_surfaces_drift_list(self):
        with patch(
            "yoke_core.domain.schema_api_context.detect_seed_drift",
            return_value=["topic-x: column foo missing"],
        ):
            req = _request("packets.check.run", {})
            outcome = orchestration.handle_packets_check(req)
        self.assertTrue(outcome.primary_success)
        self.assertFalse(outcome.result_payload["seed_ok"])
        self.assertEqual(len(outcome.result_payload["drift"]), 1)


class TestAgentsRenderRun(unittest.TestCase):
    """AC-7.2 — agents.render.run routes through yoke_core.domain.agents_render."""

    def test_routes_through_renderer(self):
        captured: dict = {}

        def fake_write_all(*, target_root, dry_run):
            captured["target_root"] = target_root
            captured["dry_run"] = dry_run
            return {".claude/agents/yoke-engineer.md": ("write", "body")}

        with patch(
            "yoke_core.domain.agents_render.write_all",
            side_effect=fake_write_all,
        ):
            req = _request(
                "agents.render.run",
                {"target_root": "/tmp/fake-root", "dry_run": True},
            )
            outcome = orchestration_agents.handle_agents_render_run(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(captured["dry_run"], True)
        self.assertEqual(str(captured["target_root"]), "/tmp/fake-root")
        self.assertEqual(
            outcome.result_payload["results"][".claude/agents/yoke-engineer.md"],
            "write",
        )

    def test_renderer_exception_surfaces_downstream_failure(self):
        with patch(
            "yoke_core.domain.agents_render.write_all",
            side_effect=RuntimeError("renderer kaboom"),
        ):
            req = _request(
                "agents.render.run", {"target_root": "/tmp/x"},
            )
            outcome = orchestration_agents.handle_agents_render_run(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "downstream_failure")


class TestAgentsRenderCheck(unittest.TestCase):
    """AC-7.2 — agents.render.check routes through yoke_core.domain.agents_render."""

    def test_returns_drift_list(self):
        with patch(
            "yoke_core.domain.agents_render.detect_substrate_drift",
            return_value=["drift: .claude/agents/yoke-engineer.md"],
        ):
            req = _request(
                "agents.render.check", {"target_root": "/tmp/y"},
            )
            outcome = orchestration_agents.handle_agents_render_check(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(len(outcome.result_payload["drift"]), 1)


if __name__ == "__main__":
    unittest.main()
