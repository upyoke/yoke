"""Envelope contract for the ``lint.config.show`` read handler."""

from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.hook_runner import lint_policy
from yoke_core.domain.handlers import lint_config_show as handler


def _request(payload: dict | None = None, kind: str = "global") -> FunctionCallRequest:
    return FunctionCallRequest(
        function="lint.config.show",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind=kind),
        payload=payload or {},
    )


class HandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="yoke-lint-handler-")
        self.addCleanup(shutil.rmtree, self.root, True)
        cfg = pathlib.Path(self.root).joinpath(*lint_policy.CONFIG_RELPATH)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("lint_destructive_git=warn\n")

    def test_returns_guards_and_rendered_text(self):
        outcome = handler.handle_lint_config_show(_request({"root": self.root}))
        self.assertTrue(outcome.primary_success)
        result = outcome.result_payload
        self.assertIn("text", result)
        self.assertTrue(result["guards"])
        self.assertEqual(result["root"], self.root)

    def test_reports_the_clamped_guard_through_the_envelope(self):
        outcome = handler.handle_lint_config_show(_request({"root": self.root}))
        clamped = [g for g in outcome.result_payload["guards"] if g["clamped"]]
        self.assertEqual([g["guard"] for g in clamped], ["lint_destructive_git"])

    def test_rejects_non_global_target(self):
        outcome = handler.handle_lint_config_show(
            _request({"root": self.root}, kind="item"))
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_rejects_non_string_root(self):
        outcome = handler.handle_lint_config_show(_request({"root": 7}))
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_root_is_optional(self):
        outcome = handler.handle_lint_config_show(_request({}))
        self.assertTrue(outcome.primary_success)


if __name__ == "__main__":
    unittest.main()
