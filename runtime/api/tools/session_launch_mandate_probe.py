"""Deployment QA probe: a launched session acknowledges its exact mandate.

Run as a Command QA case from a Yoke checkout:

    yoke dev run -- python3 -m runtime.api.tools.session_launch_mandate_probe \\
        --project P --surface S --machine MACHINE-ID --model M

After deployment (``DEPLOYMENT_RUN_ID`` set) it launches one fresh session on
the pinned machine and proves the session read and acknowledged the exact
message its launch assigned before the control plane reported success. The
case owns the launch it created, so once the verdict is known -- pass or fail
-- it ends the launched session: an idle harness otherwise keeps holding the
machine's session lanes until someone terminates it by hand. A session that
already ended is left alone, and a runner without termination authority names
the session it left running instead of failing a proven verdict.

Before deployment it proves only that the pinned route is launchable and the
candidate bootstrap names the exact receipt read and acknowledgement; a live
launch there would exercise the build already serving.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
import json
import os
import subprocess
import sys
import time
from typing import Any
import uuid

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap

from runtime.api.tools.session_launch_probe_support import (
    FAILED_LAUNCH_STATES,
    ProbeFailure,
    end_launched_session,
)


LAUNCH_INSTRUCTIONS = (
    "Read and acknowledge this launch's exact assigned message. Then say "
    "'Mandate receipt confirmed' and end the session.\n"
)


class CliClient:
    """Call registered ``yoke`` commands and return their result payloads."""

    def call(self, args: Sequence[str], *, stdin: str | None = None) -> dict[str, Any]:
        process = subprocess.run(
            ["yoke", *args, "--json"],
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )
        command = " ".join(args)
        try:
            envelope = json.loads(process.stdout)
        except ValueError:
            envelope = None
        error = envelope.get("error") if isinstance(envelope, dict) else None
        refusal_code = str(error.get("code") or "") if isinstance(error, dict) else ""
        if process.returncode or not isinstance(envelope, dict):
            raise ProbeFailure(
                "registered_command_refused",
                f"{command}: {process.stderr or process.stdout}",
                refusal_code=refusal_code,
            )
        if not envelope.get("success"):
            raise ProbeFailure(
                "registered_command_refused",
                f"{command}: {error}",
                refusal_code=refusal_code,
            )
        return envelope.get("result") or {}


def check_route(client: CliClient, *, project: str, surface: str, machine: str) -> None:
    """Refuse unless the launch would place on exactly the pinned machine."""
    preview = client.call(
        [
            "session-control",
            "launch",
            "preview",
            "--project",
            project,
            "--surface",
            surface,
            "--machine",
            machine,
        ]
    )
    if not preview.get("launchable"):
        raise ProbeFailure(
            "test_machine_launch_unavailable",
            f"{preview.get('rejection_codes')}; recover the pinned machine's "
            "relay, capacity, or project checkout, then rerun",
        )
    if (preview.get("selected_relay") or {}).get("machine_id") != machine:
        raise ProbeFailure(
            "test_machine_launch_misrouted", f"expected pinned machine {machine}"
        )


def check_candidate_bootstrap() -> str:
    bootstrap = native_launch_bootstrap("probe")
    if (
        "yoke messages get MESSAGE-ID" not in bootstrap
        or "yoke messages acknowledge MESSAGE-ID" not in bootstrap
    ):
        raise ProbeFailure(
            "candidate_bootstrap_probe_failed",
            "the launch bootstrap no longer names the exact receipt read and "
            "acknowledgement",
        )
    return "candidate bootstrap names exact receipt read and acknowledgement"


def _await_acknowledgement(
    client: CliClient,
    launch_id: str,
    *,
    timeout: float,
    poll: float,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> str:
    deadline = monotonic() + timeout
    while True:
        launch = (
            client.call(["session-control", "launch", "get", launch_id]).get("launch")
            or {}
        )
        state = launch.get("state")
        if state == "succeeded":
            break
        if state in FAILED_LAUNCH_STATES:
            raise ProbeFailure(
                "launch_failed_before_acknowledgement",
                f"{launch.get('result_code')}; recovery={launch.get('recovery')}",
            )
        if monotonic() >= deadline:
            raise ProbeFailure(
                "launch_acknowledgement_timeout",
                f"inspect yoke session-control launch get {launch_id}",
            )
        sleep(poll)
    message_id = launch.get("message_id")
    registered = launch.get("registered_session_id")
    if (
        not message_id
        or not registered
        or launch.get("native_session_id") != registered
    ):
        raise ProbeFailure(
            "launch_identity_or_message_missing",
            f"inspect yoke session-control launch get {launch_id}",
        )
    if launch.get("result_code") != "registered_and_acknowledged":
        raise ProbeFailure(
            "launch_success_without_acknowledgement", str(launch.get("result_code"))
        )
    message = client.call(["messages", "get", str(message_id)]).get("message") or {}
    matching = [
        recipient
        for recipient in message.get("recipients") or []
        if recipient.get("session_id") == registered
    ]
    if (
        len(matching) != 1
        or matching[0].get("state") != "acknowledged"
        or not matching[0].get("acknowledged_at")
    ):
        raise ProbeFailure("exact_message_acknowledgement_unproven", str(message_id))
    return (
        f"session {registered} acknowledged exact mandate {message_id}; "
        f"launch {launch_id} succeeded"
    )


def run_live_probe(
    client: CliClient,
    *,
    project: str,
    surface: str,
    machine: str,
    model: str,
    run_id: str,
    member: str,
    timeout: float = 610.0,
    poll: float = 8.0,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> str:
    """Launch, prove the exact acknowledgement, then end the launched session."""
    created = client.call(
        [
            "session-control",
            "launch",
            "create",
            "--project",
            project,
            "--surface",
            surface,
            "--machine",
            machine,
            "--model",
            model,
            "--raw-instructions",
            "--stdin",
            "--idempotency-key",
            f"mandate-acknowledgement:{run_id}:{member}:{uuid.uuid4().hex}",
        ],
        stdin=LAUNCH_INSTRUCTIONS,
    )
    launch_id = (created.get("launch") or {}).get("launch_id")
    if not launch_id:
        raise ProbeFailure("launch_id_missing", "inspect the launch create receipt")
    try:
        verdict = _await_acknowledgement(
            client,
            launch_id,
            timeout=timeout,
            poll=poll,
            sleep=sleep,
            monotonic=monotonic,
        )
    except ProbeFailure as failure:
        _cleanup, not_ended = end_launched_session(client, launch_id)
        if not_ended is not None:
            raise ProbeFailure(
                failure.code, f"{failure.detail}; {not_ended}"
            ) from failure
        raise
    cleanup, not_ended = end_launched_session(client, launch_id)
    if not_ended is not None:
        raise not_ended
    return f"{verdict}; {cleanup}"


def main(
    argv: Sequence[str] | None = None,
    *,
    client: CliClient | None = None,
    environ: Mapping[str, str] = os.environ,
) -> int:
    parser = argparse.ArgumentParser(prog="session_launch_mandate_probe")
    parser.add_argument("--project", required=True)
    parser.add_argument("--surface", required=True)
    parser.add_argument("--machine", required=True)
    parser.add_argument("--model", required=True)
    parsed = parser.parse_args(argv)
    client = client or CliClient()
    try:
        check_route(
            client,
            project=parsed.project,
            surface=parsed.surface,
            machine=parsed.machine,
        )
        run_id = environ.get("DEPLOYMENT_RUN_ID")
        if not run_id:
            print(check_candidate_bootstrap())
            print("pinned route launchable; the live launch runs after deployment")
            return 0
        member = environ.get("DEPLOYMENT_MEMBER_REF")
        if not member or not environ.get("BASE_URL"):
            raise ProbeFailure(
                "deployment_qa_subject_missing", "rerun as the deployment member case"
            )
        print(f"deployed subject: {run_id} / {member} / {environ['BASE_URL']}")
        print(
            run_live_probe(
                client,
                project=parsed.project,
                surface=parsed.surface,
                machine=parsed.machine,
                model=parsed.model,
                run_id=run_id,
                member=member,
            )
        )
    except ProbeFailure as failure:
        print(str(failure), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
