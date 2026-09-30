"""Replay native hook recordings through the installed project's rendered commands."""

from __future__ import annotations

import json
from pathlib import Path
import uuid

HARNESS_CONFIGS = {
    "claude": (".claude/settings.json", "SessionStart", "PreToolUse", "claude-code"),
    "codex": (".codex/hooks.json", "SessionStart", "PreToolUse", "codex"),
    "cursor": (".cursor/hooks.json", "sessionStart", "beforeShellExecution", "cursor"),
}


def rendered_command(project: Path, config: str, event: str) -> str:
    hooks = json.loads((project / config).read_text(encoding="utf-8"))["hooks"][event]
    commands = {
        hook["command"]
        for group in hooks
        for hook in group.get("hooks", [group])
        if "command" in hook
    }
    if len(commands) != 1:
        raise ValueError(
            f"rendered_hook_ambiguous: {config}:{event} has {len(commands)} commands; "
            "update replay selection for the rendered hook structure"
        )
    return commands.pop()


def remap_recording(
    payload: dict, *, project: Path, session: str, command=None
) -> dict:
    """Replace recorded identities/paths and the probe command; preserve wire structure."""
    identities = {"session_id", "conversation_id", "thread_id"}
    roots = {"cwd", "workspace", "project_dir"}

    def transform(value):
        if isinstance(value, list):
            return [transform(part) for part in value]
        if not isinstance(value, dict):
            return value
        return {
            key: session
            if key in identities
            else [str(project)]
            if key == "workspace_roots"
            else str(project)
            if key in roots
            else str(project / "recorded-transcript.jsonl")
            if key in {"transcript_path", "transcriptPath"}
            else str(uuid.uuid4())
            if key == "tool_use_id"
            else command
            if key == "command" and command is not None
            else transform(part)
            for key, part in value.items()
        }

    return transform(payload)


def require_dispatch(rows: list[dict], *, outcome: str) -> dict:
    """This diagnostic requires affirmative proof; absent telemetry proves no product fault."""
    for row in rows:
        if row.get("event_name") in {"HookExecutionFailed", "HarnessSessionHookFailed"}:
            raise ValueError(
                "hook_execution_failed: inspect the hook diagnostic capture and repair before rerunning"
            )
    for row in rows:
        if row.get("event_name", "HookDispatchTelemetry") != "HookDispatchTelemetry":
            continue
        envelope = row["envelope"]
        if isinstance(envelope, str):
            envelope = json.loads(envelope)
        context = envelope["context"]
        if envelope["hook_event_name"] != "PreToolUse":
            continue
        if context.get("decision_outcome") != outcome:
            raise ValueError(
                f"hook_decision_mismatch: expected {outcome}, got {context}; inspect hook capture and repair policy/replay"
            )
        if context.get("timed_out") or not context.get("chain_length", 0):
            raise ValueError(
                "hook_not_evaluated: empty/timed-out chain; inspect captures and rerun after recovery"
            )
        return {
            "event_id": row["event_id"],
            "outcome": outcome,
            "chain_length": context["chain_length"],
        }
    raise ValueError(
        "hook_evaluation_proof_unavailable: no affirmative dispatch receipt; "
        "inspect telemetry configuration/captures and repeat the diagnostic; missing telemetry establishes no product verdict"
    )


def require_wire(result, *, harness: str, outcome: str) -> None:
    if harness == "claude":
        valid = result.returncode == (2 if outcome == "deny" else 0)
        if outcome == "deny":
            valid = valid and "BLOCKED" in result.stdout
    else:
        payload = json.loads(result.stdout or "{}")
        decision = (
            payload.get("permission")
            if harness == "cursor"
            else payload.get("hookSpecificOutput", {}).get("permissionDecision")
        )
        valid = result.returncode == 0 and (
            decision == "deny" if outcome == "deny" else decision != "deny"
        )
        if harness == "cursor" and outcome == "allow":
            valid = valid and decision == "allow"
    if not valid:
        raise ValueError(
            f"hook_wire_mismatch: {harness} expected {outcome}; inspect the replay capture and correct the adapter"
        )


def replay_hooks(root: Path, project: Path, commands, yoke: str) -> list[dict]:
    proofs = []
    corpus = root / "tests/fixtures/harness-sessions"
    for harness, (config, start_event, call_event, executor) in HARNESS_CONFIGS.items():
        recording = corpus / f"{harness}.json"
        if not recording.is_file():
            raise ValueError(
                f"native_recording_missing: {recording}; capture native SessionStart and shell PreToolUse stdin "
                "as documented in product-smoke.md, sanitize it, and rerun"
            )
        fixture = json.loads(recording.read_text(encoding="utf-8"))
        if not fixture.get("provenance", {}).get("capture_source"):
            raise ValueError(
                f"native_recording_provenance_missing: {recording}; record the native capture source and version"
            )
        session = str(uuid.uuid4())
        commands.run(
            f"{harness}-session-start",
            rendered_command(project, config, start_event),
            cwd=project,
            stdin=json.dumps(
                remap_recording(
                    fixture["session_start"], project=project, session=session
                )
            ),
            shell=True,
        )
        rows = commands.document(
            f"{harness}-registration",
            [yoke, "sessions", "list", "--session", session, "--json"],
            cwd=project,
        )["rows"]
        if (
            len(rows) != 1
            or rows[0]["executor"] != executor
            or rows[0]["workspace"] != str(project)
        ):
            raise ValueError(
                f"session_registration_missing: {harness} native startup did not register the expected session; inspect startup/registration captures"
            )
        proof = {
            "harness": harness,
            "session_id": session,
            "executor": rows[0]["executor"],
            "decisions": [],
        }
        for outcome, probe in (
            ("allow", "git status --short"),
            ("deny", "git clean -fd"),
        ):
            key = "pre_tool_use_denied" if outcome == "deny" else "pre_tool_use_allowed"
            payload = remap_recording(
                fixture[key], project=project, session=session, command=probe
            )
            result = commands.run(
                f"{harness}-{outcome}",
                rendered_command(project, config, call_event),
                cwd=project,
                stdin=json.dumps(payload),
                accepted=(0, 2),
                shell=True,
            )
            require_wire(result, harness=harness, outcome=outcome)
            dispatch = commands.document(
                f"{harness}-{outcome}-evaluation",
                [
                    yoke,
                    "events",
                    "query",
                    "--session",
                    session,
                    "--limit",
                    "50",
                    "--json",
                ],
                cwd=project,
            )
            proof["decisions"].append(
                require_dispatch(dispatch["rows"], outcome=outcome)
            )
        proofs.append(proof)
    return proofs
