"""Codex UserPromptSubmit first-prompt lifecycle event coverage.

A fresh Codex session emits one ``HarnessSessionSentFirstUserPromptSubmit``
on its first real ``UserPromptSubmit`` hook.
Duplicate Codex ``UserPromptSubmit`` hooks for the same session do not
emit duplicate rows.
An empty Codex session id (``resolve_session_id`` returns falsy) does
not emit.
A ``source="startup"`` payload with no ``transcript_path`` matches the
documented early-return path and must not emit.
Codex sessions emit exactly one event even when ``_register_codex``
reports an error — emission is decoupled from registration outcome.
Install-advisory rendering on the hook-enhanced Codex
reminder path. When orientation is suppressed for ``source="startup"`` +
no ``transcript_path``, ``SESSION_MARKER`` stays unarmed and the reminder
must own the advisory so the first model-visible Codex output still teaches
the install path. When orientation already rendered the advisory
(SESSION_MARKER armed) the reminder must NOT duplicate it. When ``yoke``
resolves on PATH the reminder must omit the advisory (no false positives).
"""

from __future__ import annotations

import os
import unittest
import uuid
from pathlib import Path
from unittest import mock

import runtime.harness.bootstrap_packets as bootstrap_packets
from runtime.harness.bootstrap_packets import (
    INSTALL_ADVISORY_COMMAND,
    INSTALL_ADVISORY_HEADING,
    INSTALL_ADVISORY_POINTER,
)
from runtime.harness.codex.codex_hooks_payload import (
    prompt_marker_path,
    runtime_cache_path,
    session_marker_path,
)
from runtime.harness.hook_runner import session_dispatch
from runtime.harness.hook_runner.types import HookContext


def _fresh_codex_session_id() -> str:
    """Synthesize a unique Codex session id and clear its prompt marker.

    The prompt marker is filesystem-backed (resolved by
    ``codex_hooks_payload.prompt_marker_path(sid)``) and persists across
    test invocations if the same id is reused. Each test case must own a
    unique session id (or unlink the marker before invoking the handler) so
    ``_first_prompt(codex=True)`` does not silently report "already armed" and
    mask a regression.
    """
    sid = str(uuid.uuid4())
    try:
        os.unlink(prompt_marker_path(sid))
    except FileNotFoundError:
        pass
    return sid


def _payload(session_id: str, **extras: object) -> dict:
    payload: dict = {"session_id": session_id, "model": "gpt-5"}
    payload.update(extras)
    return payload


def _ctx(payload: dict) -> HookContext:
    return HookContext(
        event_name="UserPromptSubmit",
        executor_family="codex",
        executor_surface="codex",
        payload=payload,
    )


class _Invoker:
    """Helper that runs ``_run_codex_prompt_submit`` with subprocess-free mocks
    and captures every ``emit_event`` call. The patches isolate the dispatch
    from real subprocesses (``_touch``, ``_register_codex``,
    ``_render_codex_reminder``) and from the codex-side ``/tmp`` runtime cache
    so each test exercises only the in-process flow.
    """

    def invoke(
        self,
        payload: dict,
        *,
        touch_rc: int = 0,
        register_err: str = "",
        resolved_session_id: object = "__from_payload__",
    ) -> list[tuple[str, dict]]:
        captured: list[tuple[str, dict]] = []

        def _capture(name: str, **kwargs: object) -> None:
            captured.append((name, dict(kwargs)))

        sid = (
            payload.get("session_id", "")
            if resolved_session_id == "__from_payload__"
            else resolved_session_id
        )

        with mock.patch(
            "runtime.harness.codex.codex_hooks_payload.resolve_session_id",
            return_value=sid,
        ), mock.patch(
            "runtime.harness.codex.codex_hooks_payload.read_runtime_cache_field",
            return_value="",
        ), mock.patch(
            "runtime.harness.codex.codex_model.resolve",
            return_value="gpt-5",
        ), mock.patch(
            "runtime.harness.codex.codex_model.resolve_entrypoint",
            return_value="codex-entry",
        ), mock.patch(
            "runtime.harness.hook_runner.session_dispatch._touch",
            return_value=touch_rc,
        ), mock.patch(
            "runtime.harness.hook_runner.session_dispatch._register_codex",
            return_value=register_err,
        ), mock.patch(
            "runtime.harness.hook_runner.session_dispatch._render_codex_reminder",
            return_value="",
        ), mock.patch(
            "yoke_core.domain.events.emit_event",
            side_effect=_capture,
        ):
            session_dispatch._run_codex_prompt_submit(_ctx(payload), "/repo")
        return captured


def _first_prompt_events(captured: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    return [
        (name, kwargs)
        for name, kwargs in captured
        if name == "HarnessSessionSentFirstUserPromptSubmit"
    ]


class TestCodexFirstPromptEmission(unittest.TestCase):
    """regression coverage for Codex UserPromptSubmit telemetry."""

    def setUp(self) -> None:
        self.session_id = _fresh_codex_session_id()
        self.invoker = _Invoker()
        self.addCleanup(self._cleanup_marker)

    def _cleanup_marker(self) -> None:
        try:
            os.unlink(prompt_marker_path(self.session_id))
        except FileNotFoundError:
            pass

    def test_fresh_codex_session_emits_first_prompt_event(self) -> None:
        captured = self.invoker.invoke(_payload(self.session_id))
        emissions = _first_prompt_events(captured)
        self.assertEqual(len(emissions), 1, captured)
        _name, kwargs = emissions[0]
        self.assertEqual(kwargs.get("session_id"), self.session_id)
        self.assertEqual(kwargs.get("event_type"), "session_lifecycle")
        self.assertEqual(kwargs.get("source_type"), "hook")

    def test_duplicate_codex_prompt_submit_does_not_re_emit(self) -> None:
        first = self.invoker.invoke(_payload(self.session_id))
        second = self.invoker.invoke(_payload(self.session_id))
        self.assertEqual(len(_first_prompt_events(first)), 1)
        self.assertEqual(len(_first_prompt_events(second)), 0)

    def test_empty_codex_session_id_does_not_emit(self) -> None:
        captured = self.invoker.invoke(
            _payload(""), resolved_session_id="",
        )
        self.assertEqual(len(_first_prompt_events(captured)), 0)

    def test_startup_source_with_no_transcript_does_not_emit(self) -> None:
        # source=startup + no transcript_path is the documented Codex
        # early-return path. The marker must NOT be armed, so emission
        # cannot fire on this dispatch.
        captured = self.invoker.invoke(
            _payload(self.session_id, source="startup"),
        )
        self.assertEqual(len(_first_prompt_events(captured)), 0)
        # And the marker is still un-armed, so a real follow-up prompt
        # would emit normally.
        self.assertFalse(
            os.path.exists(prompt_marker_path(self.session_id)),
        )

    def test_registration_error_does_not_suppress_emission(self) -> None:
        captured = self.invoker.invoke(
            _payload(self.session_id),
            touch_rc=1,
            register_err="session registration failed: connection refused",
        )
        self.assertEqual(len(_first_prompt_events(captured)), 1)


class TestCodexReminderInstallAdvisory(unittest.TestCase):
    """Coverage for the install advisory on the hook-enhanced Codex reminder.

    The reminder is the first model-visible output for the typical fresh-Codex
    case where SessionStart suppresses orientation (``source="startup"`` with
    no ``transcript_path``). When ``yoke`` is missing on PATH, the advisory
    must surface here. When orientation already rendered (SESSION_MARKER
    armed) or when ``yoke`` resolves on PATH, the reminder must omit it.
    """

    def setUp(self) -> None:
        self.session_id = _fresh_codex_session_id()
        self.session_marker = session_marker_path(self.session_id)
        self.prompt_marker = prompt_marker_path(self.session_id)
        self.runtime_cache = runtime_cache_path(self.session_id)
        self.addCleanup(self._cleanup_session_marker)
        self.addCleanup(self._cleanup_prompt_marker)
        self.addCleanup(self._cleanup_runtime_cache)
        # Stub capability-registry helpers so the reminder body is deterministic
        # and independent of registry contents.
        patcher_prompt = mock.patch(
            "yoke_core.domain.harness_capability_registry.prompt_reminder_lines",
            return_value=["  /yoke do  -- continue work"],
        )
        patcher_paths = mock.patch(
            "yoke_core.domain.harness_capability_registry.shared_downstream_paths",
            return_value=["refine", "advance"],
        )
        patcher_prompt.start()
        patcher_paths.start()
        self.addCleanup(patcher_prompt.stop)
        self.addCleanup(patcher_paths.stop)

    def _cleanup_session_marker(self) -> None:
        try:
            os.unlink(self.session_marker)
        except FileNotFoundError:
            pass

    def _cleanup_prompt_marker(self) -> None:
        try:
            os.unlink(self.prompt_marker)
        except FileNotFoundError:
            pass

    def _cleanup_runtime_cache(self) -> None:
        try:
            os.unlink(self.runtime_cache)
        except FileNotFoundError:
            pass

    def _arm_session_marker(self) -> None:
        Path(self.session_marker).touch()

    def _render(self) -> str:
        return session_dispatch._render_codex_reminder(
            self.session_id, "/repo", "", "gpt-5", "codex-entry",
        )

    def test_reminder_renders_advisory_when_orientation_suppressed(self) -> None:
        """SESSION_MARKER unarmed + yoke missing → reminder owns the advisory."""

        with mock.patch.object(bootstrap_packets.shutil, "which", return_value=None):
            output = self._render()
        # Advisory leads the reminder so the operator sees it before the
        # command catalog, matching the bootstrap-compact contract.
        self.assertTrue(
            output.startswith(INSTALL_ADVISORY_HEADING),
            f"reminder must lead with the install advisory; got: {output!r}",
        )
        self.assertIn(INSTALL_ADVISORY_COMMAND, output)
        self.assertIn(INSTALL_ADVISORY_POINTER, output)
        self.assertIn("Yoke/Codex safe operator commands", output)

    def test_prompt_after_startup_suppression_renders_advisory(self) -> None:
        """startup/no-transcript suppression does not hide the first real prompt advisory."""

        startup = HookContext(
            event_name="SessionStart",
            executor_family="codex",
            executor_surface="codex",
            payload=_payload(self.session_id, source="startup"),
        )
        prompt = HookContext(
            event_name="UserPromptSubmit",
            executor_family="codex",
            executor_surface="codex",
            payload=_payload(self.session_id, transcript_path="/tmp/codex.jsonl"),
        )
        root = str(Path.cwd())
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch(
            "runtime.harness.codex.codex_hooks_payload.resolve_session_id",
            return_value=self.session_id,
        ), mock.patch(
            "runtime.harness.hook_runner.session_dispatch.export_bound_workspace_for_session",
        ), mock.patch(
            "runtime.harness.codex.codex_model.resolve",
            return_value="gpt-5",
        ), mock.patch(
            "runtime.harness.hook_runner.session_dispatch._touch",
            return_value=0,
        ), mock.patch(
            "runtime.harness.hook_runner.telemetry.emit_harness_session_sent_first_user_prompt_submit",
        ), mock.patch.object(
            bootstrap_packets.shutil,
            "which",
            return_value=None,
        ):
            self.assertEqual(session_dispatch._run_codex_session_start(startup, root), "")
            self.assertFalse(os.path.exists(self.session_marker))
            output = session_dispatch._run_codex_prompt_submit(prompt, root)

        self.assertTrue(output.startswith(INSTALL_ADVISORY_HEADING), output)
        self.assertIn(INSTALL_ADVISORY_COMMAND, output)
        self.assertIn(INSTALL_ADVISORY_POINTER, output)
        self.assertIn("Yoke/Codex safe operator commands", output)

    def test_reminder_omits_advisory_when_orientation_already_rendered(self) -> None:
        """SESSION_MARKER armed (orientation fired) → reminder must NOT duplicate it."""

        self._arm_session_marker()
        with mock.patch.object(bootstrap_packets.shutil, "which", return_value=None):
            output = self._render()
        self.assertNotIn(INSTALL_ADVISORY_HEADING, output)
        self.assertNotIn(INSTALL_ADVISORY_COMMAND, output)
        self.assertTrue(output.startswith("Yoke/Codex safe operator commands"))

    def test_reminder_omits_advisory_when_yoke_on_path(self) -> None:
        """Installed sessions see no advisory regardless of SESSION_MARKER state."""

        # Even with orientation suppressed, an installed session must stay quiet.
        with mock.patch.object(
            bootstrap_packets.shutil, "which", return_value="/usr/local/bin/yoke",
        ):
            output = self._render()
        self.assertNotIn(INSTALL_ADVISORY_HEADING, output)
        self.assertNotIn(INSTALL_ADVISORY_COMMAND, output)
        self.assertTrue(output.startswith("Yoke/Codex safe operator commands"))
        self.assertIn("yoke board art variant create", output)


if __name__ == "__main__":
    unittest.main()
