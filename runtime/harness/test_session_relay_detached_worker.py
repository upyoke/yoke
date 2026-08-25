"""The relay may exit while a detached native owner continues its turn."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time


OWNER_SOURCE = """
import json
from pathlib import Path
import sys
import time

payload = json.loads(sys.stdin.buffer.read())
sys.stdout.write('{"accepted":true}\\n')
sys.stdout.flush()
time.sleep(0.15)
Path(payload["sentinel"]).write_text("owner-survived-relay-exit")
time.sleep(0.15)
"""

RELAY_SOURCE = """
import os
from pathlib import Path
import sys

from yoke_harness.session_relay_detached_worker import run_detached_json_worker

root = Path(sys.argv[1])
sentinel = Path(sys.argv[2])
accepted = run_detached_json_worker(
    module="owner_probe",
    checkout=root,
    environment=dict(os.environ),
    payload={"sentinel": str(sentinel)},
    decode=lambda value: bool(isinstance(value, dict) and value.get("accepted")),
    initial_failure=False,
    uncertain_failure=False,
)
raise SystemExit(0 if accepted else 2)
"""


def test_detached_owner_survives_one_shot_relay_exit(tmp_path: Path) -> None:
    owner = tmp_path / "owner_probe.py"
    relay = tmp_path / "relay_probe.py"
    sentinel = tmp_path / "owner-finished"
    owner.write_text(OWNER_SOURCE)
    relay.write_text(RELAY_SOURCE)
    environment = dict(os.environ)
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{tmp_path}{os.pathsep}{existing}" if existing else str(tmp_path)
    )

    completed = subprocess.run(
        [sys.executable, str(relay), str(tmp_path), str(sentinel)],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    # Wait for the content, not merely for the path. ``write_text`` creates
    # the file and writes it separately, so a reader that stops at
    # ``exists()`` can read the empty window between the two and compare ''.
    deadline = time.monotonic() + 3
    observed = ""
    while time.monotonic() < deadline:
        try:
            observed = sentinel.read_text()
        except FileNotFoundError:
            observed = ""
        if observed:
            break
        time.sleep(0.02)
    assert observed == "owner-survived-relay-exit"
