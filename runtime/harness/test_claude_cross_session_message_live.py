"""Opt-in live proof of Claude native cross-session message delivery."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import time
from uuid import UUID, uuid4

import pytest

from runtime.harness.claude_cross_session_live_support import (
    CrossSessionPrivateCapture,
    ScopedNativeProbe,
    agent_rows,
    mature_receiver,
    redacted_summary,
    sender_facts,
    single_sender_uuid,
    short_id_absent,
    target_row,
)
from runtime.harness.test_claude_background_resume_live import _ProbeFailure
from yoke_harness import session_relay_claude as claude_module
from yoke_harness import session_relay_claude_identity as identity_module
from yoke_harness.session_relay_environment import native_session_environment


_OPT_IN_ENV = "YOKE_RUN_LIVE_CLAUDE_CROSS_SESSION_MESSAGE"
_OPT_IN_VALUE = "I_ACCEPT_TWO_DISPOSABLE_SESSIONS"
_VERSION = "2.1.241"
_VERSION_PATTERN = re.compile(rf"(?<![0-9.]){re.escape(_VERSION)}(?![0-9.])")
_ATTEMPTS = 80
_INTERVAL_SECONDS = 0.25
_TARGET_SETTINGS = json.dumps(
    {"disableAllHooks": True, "crossSessionInbound": "accept"},
    separators=(",", ":"),
)


@pytest.mark.skipif(
    os.environ.get(_OPT_IN_ENV) != _OPT_IN_VALUE,
    reason=f"set {_OPT_IN_ENV}={_OPT_IN_VALUE} for two disposable sessions",
)
def test_named_claude_session_receives_native_cross_session_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = claude_module.discover_claude_cli()
    if executable is None:
        raise _ProbeFailure("Claude CLI is unavailable")
    isolated = tempfile.TemporaryDirectory(prefix="yoke-claude-message-project-")
    root = Path(isolated.name).resolve()
    temp_parent = Path(tempfile.gettempdir()).resolve()
    if (
        root.is_symlink()
        or root.parent != temp_parent
        or not root.name.startswith("yoke-claude-message-project-")
    ):
        raise _ProbeFailure("isolated project root failed validation")
    os.chmod(root, 0o700)
    project = root / "project"
    project.mkdir(mode=0o700)
    for name in (
        "DISABLE_TELEMETRY",
        "DO_NOT_TRACK",
        "DISABLE_GROWTHBOOK",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    ):
        monkeypatch.delenv(name, raising=False)
    environment = native_session_environment(
        executor="claude-code",
        executor_version=_VERSION,
        provider="anthropic",
        markers={"CLAUDE_CODE_ENTRYPOINT": "cli"},
    )
    capture = CrossSessionPrivateCapture()
    print(f"CLAUDE_CROSS_SESSION_PRIVATE_CAPTURE={capture.path}")
    probe = ScopedNativeProbe(executable, project, environment, capture)
    command, roster = probe.command, probe.roster

    target_short = None
    target_uuid = None
    target_name = f"yoke-wake-{uuid4().hex[:12]}"
    target_ready = False
    ready_nonce_seen = False
    sender_exit_zero = False
    sender_identity_distinct = False
    sender_not_registered = False
    post_commands_ok = False
    wake_observed = False
    response_observed = False
    same_target = False
    target_idle_after = False
    saw_working = False
    direct_exit_zero = False
    direct_identity_same = False
    direct_response_observed = False
    direct_logs_observed = False
    direct_same_target = False
    peer_safe_after_direct = False
    cleanup_identity_exact = False
    cleanup_ok = False
    failure: _ProbeFailure | None = None
    try:
        version = command("version", executable, "--version")
        version_text = f"{version.stdout}\n{version.stderr}"
        if version.returncode or not _VERSION_PATTERN.search(version_text):
            raise _ProbeFailure("installed Claude CLI version mismatch")

        requested_id = str(uuid4())
        ready_suffix = uuid4().hex
        ready_nonce = f"TARGET_READY_{ready_suffix}"
        target_prompt = f"Reply with the concatenation of TARGET_READY_ and {ready_suffix}, then end the turn. In a later turn, when a peer message begins WAKE_, derive its suffix in reverse, output TARGET_ACK_ followed by that reversed suffix, then end the turn. Do not use tools or modify files."
        launched = command(
            "target_launch",
            executable,
            "--session-id",
            requested_id,
            "--name",
            target_name,
            "--safe-mode",
            "--settings",
            _TARGET_SETTINGS,
            "--tools",
            "",
            "--bg",
            target_prompt,
        )
        if launched.returncode:
            raise _ProbeFailure("target launch exited nonzero")
        target_short = identity_module.background_agent_id(launched)
        if target_short is None:
            raise _ProbeFailure("target short identity was not parseable")
        lookup_count = 0

        def lookup():
            nonlocal lookup_count
            lookup_count += 1
            return roster(f"target_identity_{lookup_count}")

        resolution = identity_module.resolve_background_session(target_short, lookup)
        if resolution.session_id is None:
            raise _ProbeFailure("target UUID did not resolve")
        target_uuid = str(UUID(resolution.session_id))

        for attempt in range(1, _ATTEMPTS + 1):
            agents = roster(f"target_ready_agents_{attempt}")
            logs = command(
                f"target_ready_logs_{attempt}", executable, "logs", target_short
            )
            row, name_count = target_row(
                agents.stdout,
                short_id=target_short,
                session_id=target_uuid,
                name=target_name,
            )
            target_ready = (
                agents.returncode == 0 and name_count == 1 and mature_receiver(row)
            )
            ready_nonce_seen = (
                logs.returncode == 0 and ready_nonce in f"{logs.stdout}\n{logs.stderr}"
            )
            if target_ready and ready_nonce_seen:
                break
            time.sleep(_INTERVAL_SECONDS)
        if not target_ready or not ready_nonce_seen:
            raise _ProbeFailure("target did not reach unique idle readiness")

        wake_suffix = uuid4().hex
        wake_nonce = f"WAKE_{wake_suffix}"
        expected_response = f"TARGET_ACK_{wake_suffix[::-1]}"
        before_logs = command("target_logs_before", executable, "logs", target_short)
        before_text = f"{before_logs.stdout}\n{before_logs.stderr}"
        if before_logs.returncode:
            raise _ProbeFailure("target logs were unavailable before challenge")
        if wake_nonce in before_text or expected_response in before_text:
            raise _ProbeFailure("fresh wake challenge was already present")

        direct_suffix = uuid4().hex
        direct_expected = f"DIRECT_ACK_{direct_suffix[::-1]}"
        direct_prompt = f"Output DIRECT_ACK_ followed by the reverse of {direct_suffix}. Do not use tools or modify files."
        direct = command(
            "direct_resume_control",
            executable,
            "-p",
            "--resume",
            target_uuid,
            "--safe-mode",
            "--settings",
            _TARGET_SETTINGS,
            direct_prompt,
            "--output-format",
            "json",
            timeout=claude_module.CLAUDE_HEADLESS_WAKE_TIMEOUT_SECONDS,
        )
        direct_exit_zero = direct.returncode == 0
        try:
            direct_document = json.loads(direct.stdout)
            direct_identity = str(UUID(str(direct_document["session_id"])))
            direct_result = str(direct_document.get("result") or "")
        except (KeyError, TypeError, ValueError, AttributeError):
            direct_identity, direct_result = "", ""
        direct_identity_same = direct_identity == target_uuid
        direct_response_observed = direct_expected in direct_result
        for attempt in range(1, 9):
            agents = roster(f"direct_agents_{attempt}")
            logs = command(f"direct_logs_{attempt}", executable, "logs", target_short)
            row, count = target_row(
                agents.stdout,
                short_id=target_short,
                session_id=target_uuid,
                name=target_name,
            )
            direct_same_target = agents.returncode == 0 and count == 1 and bool(row)
            direct_logs_observed = (
                logs.returncode == 0
                and direct_expected in f"{logs.stdout}\n{logs.stderr}"
            )
            peer_safe_after_direct = direct_same_target and mature_receiver(row)
            if peer_safe_after_direct:
                break
            time.sleep(_INTERVAL_SECONDS)
        if not peer_safe_after_direct:
            raise _ProbeFailure("target did not return to idle after direct control")

        sender_id = str(uuid4())
        sender_prompt = f"Use ListAgents first and require exactly one local background session named {target_name}. Then use SendMessage to send exactly {wake_nonce} to that named session. Use no other tools. Return SENT when the tool succeeds."
        sender = command(
            "sender",
            executable,
            "-p",
            "--session-id",
            sender_id,
            "--no-session-persistence",
            "--safe-mode",
            "--settings",
            _TARGET_SETTINGS,
            "--tools",
            "ListAgents,SendMessage",
            sender_prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            timeout=claude_module.CLAUDE_HEADLESS_WAKE_TIMEOUT_SECONDS,
        )
        sender_exit_zero = sender.returncode == 0
        _, sender_tools, sender_tool_results = sender_facts(sender.stdout)
        sender_uuid = single_sender_uuid(sender.stdout)
        if sender_uuid is None:
            raise _ProbeFailure("sender structured identity was malformed")
        sender_identity_distinct = (
            sender_uuid == sender_id and sender_uuid != target_uuid
        )
        sender_tools_ok = {"ListAgents", "SendMessage"}.issubset(sender_tools)
        if not all(
            (
                sender_exit_zero,
                sender_identity_distinct,
                sender_tools_ok,
                sender_tool_results >= 2,
            )
        ):
            raise _ProbeFailure("sender did not complete as a distinct session")

        for attempt in range(1, _ATTEMPTS + 1):
            agents = roster(f"post_send_agents_{attempt}")
            logs = command(
                f"post_send_logs_{attempt}", executable, "logs", target_short
            )
            post_commands_ok = agents.returncode == 0 and logs.returncode == 0
            rows = agent_rows(agents.stdout) if agents.returncode == 0 else []
            sender_not_registered = all(
                str(row.get("sessionId") or "") != sender_uuid for row in rows
            )
            row, name_count = target_row(
                agents.stdout,
                short_id=target_short,
                session_id=target_uuid,
                name=target_name,
            )
            same_target = post_commands_ok and name_count == 1 and bool(row)
            saw_working = saw_working or row.get("state") == "working"
            target_idle_after = mature_receiver(row)
            log_text = f"{logs.stdout}\n{logs.stderr}" if post_commands_ok else ""
            wake_observed = wake_nonce in log_text
            response_observed = expected_response in log_text
            if (
                same_target
                and sender_not_registered
                and target_idle_after
                and wake_observed
                and response_observed
            ):
                break
            time.sleep(_INTERVAL_SECONDS)
        if not all(
            (
                same_target,
                sender_not_registered,
                target_idle_after,
                wake_observed,
                response_observed,
            )
        ):
            raise _ProbeFailure("target did not complete the cross-session turn")
    except _ProbeFailure as caught:
        failure = caught
    finally:
        if target_short:
            if failure is not None:
                roster("failure_agents")
                command("failure_logs", executable, "logs", target_short)
            agents = roster("cleanup_identity")
            if target_uuid:
                row, count = target_row(
                    agents.stdout,
                    short_id=target_short,
                    session_id=target_uuid,
                    name=target_name,
                )
                cleanup_identity_exact = (
                    agents.returncode == 0 and count == 1 and bool(row)
                )
            command("cleanup_stop", executable, "stop", target_short)
            removed = command("cleanup_remove", executable, "rm", target_short)
            after = roster("cleanup_absence")
            cleanup_ok = (
                removed.returncode == 0
                and after.returncode == 0
                and short_id_absent(after.stdout, target_short)
            )
        isolated.cleanup()
        root_removed = not root.exists()
        capture.close()
        capture_truncated = capture.capture_truncated
        passed = failure is None and cleanup_ok and root_removed
        summary = redacted_summary(locals(), passed=passed)
        print("CLAUDE_CROSS_SESSION_REDACTED=" + json.dumps(summary, sort_keys=True))
        if passed:
            capture.path.unlink(missing_ok=True)
    if failure is not None:
        pytest.fail(str(failure))
    if not cleanup_ok or not root_removed:
        pytest.fail("disposable native session cleanup failed")
