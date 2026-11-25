"""The relay may exit while a detached native owner continues its turn."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
import pytest

from yoke_harness.session_relay_detached_worker import run_detached_json_worker
from yoke_harness.session_relay_process_group import spawn_relay_process

pytestmark = pytest.mark.windows

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


@pytest.mark.parametrize("descendant_holds_stdout", [False, True])
def test_handoff_returns_before_owner_closes_stdout(
    tmp_path: Path, descendant_holds_stdout: bool
) -> None:
    (tmp_path / "owner_probe.py").write_text(
        """
import json
from pathlib import Path
import subprocess
import sys
import time

def hold_stdout():
    deadline = time.monotonic() + 20
    while not Path("release-owner").exists() and time.monotonic() < deadline:
        time.sleep(0.02)

if sys.argv[1:] == ["hold-stdout"]:
    hold_stdout()
else:
    payload = json.loads(sys.stdin.buffer.read())
    descendant_holds_stdout = payload["descendant_holds_stdout"]
    if descendant_holds_stdout:
        subprocess.Popen([sys.executable, "-m", "owner_probe", "hold-stdout"])
    print('{"accepted":true}', flush=True)
    if not descendant_holds_stdout:
        hold_stdout()
"""
    )
    owners: list[subprocess.Popen[bytes]] = []

    def capture_owner(*args, **kwargs):
        process = spawn_relay_process(*args, **kwargs)
        owners.append(process)
        return process

    def decode(value):
        if descendant_holds_stdout:
            owners[0].wait(timeout=3)
        return value

    started = time.monotonic()
    try:
        outcome = run_detached_json_worker(
            module="owner_probe",
            checkout=tmp_path,
            environment=dict(os.environ),
            payload={"descendant_holds_stdout": descendant_holds_stdout},
            decode=decode,
            initial_failure="initial_failure",
            uncertain_failure="uncertain_failure",
            process_factory=capture_owner,
            timeout=4,
        )
        elapsed = time.monotonic() - started
        assert outcome == {"accepted": True}
        assert elapsed < 5, f"handoff took {elapsed:.2f}s while stdout was open"
        assert owners[0].poll() == (0 if descendant_holds_stdout else None)
    finally:
        (tmp_path / "release-owner").touch()
        for owner in owners:
            owner.wait(timeout=5)

    stream = owners[0].stdout
    assert stream is not None
    deadline = time.monotonic() + 5
    while not stream.closed and time.monotonic() < deadline:
        time.sleep(0.02)
    assert stream.closed


def test_owner_exits_without_json(tmp_path: Path) -> None:
    (tmp_path / "owner_probe.py").write_text("import sys\nsys.stdin.buffer.read()\n")

    outcome = run_detached_json_worker(
        module="owner_probe",
        checkout=tmp_path,
        environment=dict(os.environ),
        payload={},
        decode=lambda value: value,
        initial_failure="initial_failure",
        uncertain_failure="uncertain_failure",
    )

    assert outcome == "uncertain_failure"
