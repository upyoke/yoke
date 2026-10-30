"""Prove delivered CLI identity and public intake refusals, then archive the note."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from yoke_contracts.harness_sandbox_recovery import running_harness_family
from yoke_contracts.release_version import release_version

PRODUCTION_FINGERPRINT = "upyoke@2026-06-09T15:11:27.000000Z"


def delivered_environment():
    env = dict(os.environ)
    if env.get("YOKE_FEEDBACK_SOURCE_PROBE") == "1":
        return env
    # Source-run QA must invoke the delivered wheel through the machine launcher.
    source_bin = str(Path(sys.executable).parent)
    env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if p != source_bin)
    for key in ("PYTHONPATH", "VIRTUAL_ENV", "YOKE_SOURCE_DEV", "YOKE_SOURCE_DEV_RUN_ROOT", "YOKE_HOME",
                "YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID", "CURSOR_SESSION_ID", "YOKE_ACTOR_ROLE"):
        env.pop(key, None)
    return env


def run(*args):
    env = delivered_environment()
    executable = shutil.which("yoke", path=env["PATH"])
    if not executable:
        raise RuntimeError("feedback_acceptance_cli_missing: install the delivered Yoke CLI and retry")
    result = subprocess.run([executable, *args, "--json"], env=env, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError(f"feedback_acceptance_command_failed: {' '.join(args[:3])}; inspect its named recovery and retry this case\n{result.stderr}")
    return json.loads(result.stdout)


def call(*args):
    response = run(*args)
    if not response.get("success"):
        raise RuntimeError("feedback_acceptance_refused: inspect the public CLI refusal and restore its connection before retrying")
    return response


def expected_version():
    if os.environ.get("YOKE_FEEDBACK_SOURCE_PROBE") == "1":
        from yoke_contracts.runtime_identity import reporting_version
        return reporting_version()
    return release_version(run("status")["runtime_identity"]["version"])


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
        evidence = "Public feedback acceptance " + str(uuid4())
        receipt = call("feedback", "--to", "yoke", "--category", "observation", "--evidence", evidence)
        note_id = int(receipt["entry_id"])
        entry = call("feedback", "get", str(note_id))["result"]["entry"]
        fingerprint = os.environ.get("YOKE_FEEDBACK_EXPECTED_FINGERPRINT") or PRODUCTION_FINGERPRINT
        if (entry.get("body") != evidence or entry.get("category") != "observation"
                or entry.get("project") != "yoke" or not entry.get("actor_id")
                or entry.get("universe_fingerprint") != fingerprint or entry.get("yoke_version") != version
                or entry.get("agent") != (running_harness_family() or "terminal")):
            raise RuntimeError(f"feedback_acceptance_metadata_wrong: inspect feedback note {note_id} and repair delivery attribution, then retry")
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
