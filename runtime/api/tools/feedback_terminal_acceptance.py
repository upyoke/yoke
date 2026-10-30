"""Disposable plain-terminal checks against a local universe and self-host server."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
from uuid import uuid4


def command(*args, env=None, parse=True):
    result = subprocess.run(["yoke", *args, "--json"], env=env, capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise RuntimeError(f"feedback_terminal_command_failed: {' '.join(args[:3])}; {result.stderr}; repair the named prerequisite and retry")
    return json.loads(result.stdout) if parse else None


def org_fingerprint(env):
    org = command("organizations", "get", env=env)["result"]
    return org["slug"] + "@" + org["created_at"]


def main():
    env = dict(os.environ)
    for key in ("YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID", "CURSOR_SESSION_ID", "YOKE_ACTOR_ROLE"):
        env.pop(key, None)
    command("init", "--local", "--admin-name", "Feedback QA", "--activate", env=env, parse=False)
    local = {**env, "YOKE_ENV": "local"}
    version = command("status", env=local)["runtime_identity"]["version"]
    if "+" in version:
        raise RuntimeError("feedback_terminal_wheel_required: install the delivered wheel, then retry")
    with tempfile.TemporaryDirectory(prefix="yoke-feedback-qa-") as directory:
        bundle = Path(directory) / "server"
        try:
            command("self-host", "init", "--dir", str(bundle), "--admin-name", "Feedback QA",
                    "--port", "18769", "--start", env=env, parse=False)
            command("connect", "http://127.0.0.1:18769", "--name", "feedback-receiver",
                    "--token-file", str(bundle / "secrets/first-boot-admin-token"), env=env)
            receiver = {**env, "YOKE_ENV": "feedback-receiver"}
            command("projects", "create", "--slug", "yoke", "--name", "Feedback receiver",
                    "--public-item-prefix", "QA", "--github-sync-mode", "disabled", env=receiver)
            for label, sender in (("local", local), ("self-host", receiver)):
                fingerprint = org_fingerprint(sender)
                for destination in ("yoke", "universe"):
                    evidence = f"Plain terminal {label} {destination} " + str(uuid4())
                    sending = {**sender, "YOKE_FEEDBACK_URL": "http://127.0.0.1:18769/v1/feedback"}
                    receipt = command("feedback", "--to", destination, "--category", "observation",
                                      "--evidence", evidence, env=sending)
                    note_id = str(receipt.get("entry_id") or receipt["result"]["entry_id"])
                    reading = receiver if destination == "yoke" else sender
                    try:
                        entry = command("feedback", "get", note_id, env=reading)["result"]["entry"]
                        assert (entry["yoke_version"], entry["universe_fingerprint"], entry["agent"]) == (
                            version, fingerprint, "terminal"), entry
                        assert entry["body"] == evidence
                    finally:
                        command("feedback", "archive", note_id,
                                *(["--project", "yoke"] if destination == "yoke" else []), env=reading)
                print(f"Plain terminal {label}: both feedback destinations retain exact identity.")
        finally:
            if (bundle / "docker-compose.yml").exists():
                command("self-host", "teardown", "--dir", str(bundle), "--destroy-universe",
                        "--remove-bundle", "--activate", "local", "--yes", env=env, parse=False)
    print("Feedback terminal acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
