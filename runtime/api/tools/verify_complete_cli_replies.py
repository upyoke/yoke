"""Prove complete CLI delivery against the deployed member's live detail."""

from __future__ import annotations

import json
import os
import subprocess


def main() -> None:
    member = os.environ.get("DEPLOYMENT_MEMBER_REF")
    if not member:
        raise SystemExit("deployment_member_missing: run this check as a deployment member QA case.")
    command = ["yoke", "items", "detail", "get", member]
    machine = subprocess.run([*command, "--json"], capture_output=True, text=True, timeout=60)
    if machine.returncode:
        raise SystemExit(f"member_detail_refused: inspect the item read before retrying: {machine.stderr}")
    envelope = json.loads(machine.stdout)
    if not envelope.get("success") or "result" not in envelope or "saved_response" in envelope:
        raise SystemExit("json_envelope_incomplete: install the candidate CLI and rerun member QA.")
    if len(machine.stdout.encode()) <= 4_000:
        raise SystemExit("oversized_json_not_exercised: use a member with full detail exceeding 4,000 bytes.")
    human = subprocess.run([*command, "--full"], capture_output=True, text=True, timeout=60)
    if human.returncode or "Complete reply saved:" in human.stdout:
        raise SystemExit("human_full_incomplete: install the candidate CLI and rerun member QA.")
    print(f"Complete JSON envelope: {len(machine.stdout.encode())} bytes; complete human detail: {len(human.stdout.encode())} bytes.")


if __name__ == "__main__":
    main()
