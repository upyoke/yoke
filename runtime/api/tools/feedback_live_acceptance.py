"""Prove public feedback delivery through the production CLI, then archive it."""

import json
import os
import subprocess
import sys
from uuid import uuid4


def call(*args):
    result = subprocess.run(["yoke", *args, "--json"], capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError(f"feedback_acceptance_command_failed: {' '.join(args[:3])}; inspect its named recovery and retry this case\n{result.stderr}")
    response = json.loads(result.stdout)
    if not response.get("success"):
        raise RuntimeError("feedback_acceptance_refused: inspect the public CLI refusal and restore its connection before retrying")
    return response


def main():
    note_id = None
    outcome = 0
    try:
        if os.environ.get("YOKE_FEEDBACK_URL"):
            raise RuntimeError("feedback_acceptance_override_set: unset YOKE_FEEDBACK_URL to prove the production public endpoint")
        evidence = "Public feedback production acceptance " + str(uuid4())
        receipt = call("feedback", "--to", "yoke", "--category", "observation", "--evidence", evidence)
        note_id = int(receipt["entry_id"])
        entry = call("feedback", "get", str(note_id))["result"]["entry"]
        if (entry.get("body") != evidence or entry.get("category") != "observation"
                or entry.get("project") != "yoke" or not entry.get("actor_id")
                or not entry.get("universe_fingerprint") or not entry.get("yoke_version")):
            raise RuntimeError(f"feedback_acceptance_metadata_missing: inspect feedback note {note_id} and repair delivery attribution, then retry")
        print(f"Feedback note {note_id}: public CLI receipt and receiver metadata verified.")
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
