"""Prove the bound CLI identity and public intake refusals, then archive the note."""

import json
import os
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from yoke_contracts.harness_sandbox_recovery import running_harness_family
import yoke_cli  # Load the CLI origin before resolving its reporting identity.
from yoke_contracts.release_version import reporting_version_shape
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.session_identity import resolve_actor_role

PRODUCTION_FINGERPRINT = "upyoke@2026-06-09T15:11:27.000000Z"


def run(*args):
    # Keep the candidate's dev-run binding, including PATH and PYTHONPATH.
    result = subprocess.run(["yoke", *args, "--json"], capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError(f"feedback_acceptance_command_failed: {' '.join(args[:3])}; inspect its named recovery and retry this case\n{result.stderr}")
    return json.loads(result.stdout)


def call(*args):
    response = run(*args)
    if not response.get("success"):
        raise RuntimeError("feedback_acceptance_refused: inspect the public CLI refusal and restore its connection before retrying")
    return response


def expected_version():
    from yoke_contracts.runtime_identity import reporting_version
    try:
        return reporting_version_shape(reporting_version())
    except ValueError as exc:
        raise RuntimeError(compose_refusal(
            "feedback_acceptance_version_unavailable",
            evaluated=f"CLI origin {yoke_cli.__file__!r}; {exc}",
            recovery="Run the case through yoke dev run with its bound candidate CLI, then retry.",
        )) from None


def negative_probes(entry):
    from yoke_cli.feedback_delivery import FEEDBACK_URL
    url = os.environ.get("YOKE_FEEDBACK_URL") or FEEDBACK_URL
    valid = {"category": "observation", "evidence": "Refused feedback identity probe",
             **{k: entry[k] for k in ("agent", "yoke_version", "universe_fingerprint")}}
    probes = []
    for field, name in (("yoke_version", "version"), ("universe_fingerprint", "fingerprint"), ("agent", "agent")):
        probes.append(({k: v for k, v in valid.items() if k != field},
                       "yoke-cli/" + entry["yoke_version"], f"feedback_{name}_missing"))
    probes.append((valid, "yoke-cli/unknown", "feedback_user_agent_invalid"))
    for payload, agent, code in probes:
        request = Request(url, data=json.dumps(payload).encode(), method="POST",
                          headers={"Content-Type": "application/json", "User-Agent": agent})
        try:
            with urlopen(request, timeout=20):
                raise RuntimeError(f"feedback_acceptance_invalid_note_accepted: expected {code}; repair intake")
        except HTTPError as exc:
            body = json.load(exc)
            if exc.code != 400 or body.get("error") != code or not body.get("recovery"):
                raise RuntimeError(f"feedback_acceptance_refusal_wrong: expected {code}; inspect intake and retry") from exc
    print("Public feedback identity refusals verified.")


def main():
    note_id = None
    outcome = 0
    try:
        version = expected_version()
        print(f"Feedback CLI version: {version}")
        evidence = "Public feedback acceptance " + str(uuid4())
        receipt = call("feedback", "--to", "yoke", "--category", "observation", "--evidence", evidence)
        note_id = int(receipt["entry_id"])
        entry = call("feedback", "get", str(note_id))["result"]["entry"]
        fingerprint = os.environ.get("YOKE_FEEDBACK_EXPECTED_FINGERPRINT") or PRODUCTION_FINGERPRINT
        if (entry.get("body") != evidence or entry.get("category") != "observation"
                or entry.get("project") != "yoke" or not entry.get("actor_id")
                or entry.get("universe_fingerprint") != fingerprint or entry.get("yoke_version") != version
                or entry.get("agent") != (resolve_actor_role() or running_harness_family() or "terminal")):
            raise RuntimeError(f"feedback_acceptance_metadata_wrong: feedback note {note_id} expected version {version!r}, received {entry.get('yoke_version')!r}; inspect the note and repair delivery attribution, then retry")
        negative_probes(entry)
        print(f"Feedback note {note_id}: exact CLI version, universe fingerprint and agent verified.")
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        outcome = 1
    if note_id is not None:
        try:
            call("feedback", "archive", str(note_id), "--project", "yoke")
            print(f"Feedback note {note_id}: acceptance evidence archived.")
        except Exception as exc:
            print(f"feedback_acceptance_cleanup_failed: archive feedback note {note_id} with yoke feedback archive {note_id} --project yoke\n{exc}", file=sys.stderr)
            outcome = 1
    return outcome


if __name__ == "__main__":
    raise SystemExit(main())
