"""Release QA: a real relay Claude worker survives a moved 21-minute wait."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import time
import uuid

from runtime.api.tools.session_launch_mandate_probe import CliClient, check_route
from runtime.api.tools.session_launch_probe_support import ProbeFailure

WAIT_SECONDS = 1265


def completion_matches(body: str, nonce: str, elapsed: float) -> bool:
    """Require the actual Bash result and the runner's independent elapsed bound."""
    try:
        proof = json.loads(body)
    except (ValueError, TypeError):
        return False
    return (
        isinstance(proof, dict)
        and proof.get("nonce") == nonce
        and proof.get("launch_timeout_ms") == "3600000"
        and isinstance(proof.get("elapsed_seconds"), (int, float))
        and proof["elapsed_seconds"] >= WAIT_SECONDS
        and elapsed >= WAIT_SECONDS
    )


def instructions(nonce: str, recipient: str) -> str:
    program = (
        "import json,os,time; "
        "v=os.environ.get('BASH_DEFAULT_TIMEOUT_MS'); "
        "assert v=='3600000', 'launch_timeout_missing: relaunch with manifest setting'; "
        "t=time.monotonic(); "
        f"time.sleep({WAIT_SECONDS}); "
        "print(json.dumps({"
        f"'nonce':{nonce!r},'launch_timeout_ms':v,"
        "'elapsed_seconds':time.monotonic()-t}),flush=True)"
    )
    command = "python3 -c " + shlex.quote(program)
    return (
        "Read and acknowledge this launch's exact mandate. This is an itemless "
        "release QA probe: claim no item and edit no repository files. "
        "Run exactly the following command in one foreground Bash call with "
        "timeout: 600000 and run_in_background: false. It must move to the "
        "background at ten minutes, then finish after twenty-one minutes. "
        "Preserve and continue that same call; do not change its timeout or "
        "start another. A raw Python wait is deliberate here to test the "
        "harness lifetime, so no watcher wrapper substitutes for it.\n"
        f"{command}\n"
        "Only after its exit 0, send its exact JSON stdout unchanged using "
        f"yoke say --stdin --session {recipient}. On failure send the actual "
        "diagnostic instead. Never synthesize a success result. Then end "
        "this probe session with yoke sessions end-if-empty --triggered-by wait-probe."
    )


def run_probe(client: CliClient, project: str, machine: str) -> str:
    if not os.environ.get("DEPLOYMENT_RUN_ID"):
        raise ProbeFailure(
            "released_subject_missing",
            "run this post-deploy case through the item's deployment QA stage",
        )
    identity = client.call(["sessions", "identity"])
    recipient = identity.get("session_id")
    if not recipient:
        raise ProbeFailure(
            "probe_identity_missing", "rerun from the item holder session"
        )
    check_route(client, project=project, surface="claude-cli", machine=machine)
    nonce = uuid.uuid4().hex
    start = time.monotonic()
    created = client.call(
        [
            "session-control",
            "launch",
            "create",
            "--project",
            project,
            "--surface",
            "claude-cli",
            "--machine",
            machine,
            "--raw-instructions",
            "--stdin",
            "--idempotency-key",
            f"headless-wait:{os.environ['DEPLOYMENT_RUN_ID']}:{nonce}",
        ],
        stdin=instructions(nonce, str(recipient)),
    )
    launch_id = (created.get("launch") or {}).get("launch_id")
    if not launch_id:
        raise ProbeFailure("probe_launch_missing", "inspect the launch create receipt")
    print(
        f"Waiting by design: relay launch {launch_id}; checks every 60s; "
        "gives up after 35 minutes. Requires a 1265-second Bash wait.",
        flush=True,
    )
    while time.monotonic() - start < 2100:
        launch = (
            client.call(
                ["session-control", "launch", "get", str(launch_id), "--full"]
            ).get("launch")
            or {}
        )
        sender = launch.get("registered_session_id")
        if launch.get("state") in {"failed", "cancelled", "expired", "outcome_unknown"}:
            raise ProbeFailure(
                "probe_launch_failed",
                f"{launch.get('result_code')}; inspect yoke session-control launch get {launch_id}",
            )
        if sender:
            for state in ("unacknowledged", "acknowledged"):
                messages = (
                    client.call(
                        [
                            "messages",
                            "list",
                            "--recipient-session",
                            str(recipient),
                            "--state",
                            state,
                            "--limit",
                            "20",
                            "--full",
                        ]
                    ).get("messages")
                    or []
                )
                for row in messages:
                    if row.get("sender_session_id") != sender:
                        continue
                    message_id = row.get("message_id")
                    message = (
                        client.call(["messages", "get", str(message_id), "--full"]).get(
                            "message"
                        )
                        or {}
                    )
                    if completion_matches(
                        message.get("body", ""), nonce, time.monotonic() - start
                    ):
                        return (
                            f"PASS launch={launch_id} session={sender} "
                            f"message={message_id} proof={message['body']}"
                        )
        print(
            f"relay wait proof pending: elapsed={int(time.monotonic() - start)}s",
            flush=True,
        )
        time.sleep(60)
    raise ProbeFailure(
        "relay_wait_proof_timeout",
        f"inspect yoke session-control launch get {launch_id} and its native capture; "
        "retain incomplete evidence, end any remaining probe session, then rerun",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--machine", required=True)
    args = parser.parse_args()
    try:
        print(run_probe(CliClient(), args.project, args.machine), flush=True)
    except ProbeFailure as exc:
        print(str(exc), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
