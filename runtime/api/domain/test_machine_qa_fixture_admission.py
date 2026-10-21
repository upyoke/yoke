"""The admission fixture against the real server, routes, CLI and universe.

Each test starts the real fixture the way a test machine does, drives the
real admission routes and CLI, and proves the universe's actual rows. The
fixed fixture ports and root are shared machine-wide, so one lock
serializes these tests across workers and checkouts.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import httpx
import pytest

from yoke_contracts.machine_authorization import POLL_PATH, START_PATH
from yoke_contracts.teammate_invite_wire import INVITE_REDEEM_PATH
from yoke_core.domain.machine_qa_admission_host import (
    api_url,
    approver_home,
    mode_root,
)
from yoke_core.domain.machine_qa_admission_state import expectation_failures

HOST = "yoke_core.domain.machine_qa_admission_host"
LOCK = Path("/tmp/yoke-machine-qa-admission-test.lock")


def _clean_env(**extra: str) -> dict[str, str]:
    """A test machine's environment: no ambient Yoke authority or test run."""
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("YOKE_", "PYTEST_"))
    }
    return {**env, **extra}


def _host(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", HOST, *argv],
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=420,
        check=False,
    )


@contextmanager
def _fixture(mode: str) -> Iterator[dict]:
    LOCK.touch(exist_ok=True)
    with LOCK.open() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        started = _host("start", mode)
        try:
            assert started.returncode == 0, started.stderr
            yield json.loads(started.stdout.splitlines()[-1])
        finally:
            stopped = _host("stop", mode)
            assert stopped.returncode == 0, stopped.stderr
            assert not mode_root(mode).exists()


def _start_code(mode: str) -> dict:
    machine = {
        "machine_id": str(uuid.uuid4()),
        "machine_name": "QA joining machine",
        "platform": "macOS",
    }
    reply = httpx.post(api_url(mode) + START_PATH, json=machine)
    assert reply.status_code == 200, reply.text
    return {**machine, **reply.json()}


def _poll(mode: str, started: dict) -> httpx.Response:
    return httpx.post(
        api_url(mode) + POLL_PATH,
        json={
            "device_code": started["device_code"],
            "machine_id": started["machine_id"],
            "machine_name": started["machine_name"],
        },
    )


def _assert_state(mode: str, expect: str) -> subprocess.CompletedProcess[str]:
    return _host("assert", mode, expect)


def _cli(machine_home: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """Run the real CLI as the person whose machine home this is."""
    return subprocess.run(
        [sys.executable, "-m", "yoke_cli.main", *argv],
        env=_clean_env(YOKE_MACHINE_HOME=str(machine_home)),
        cwd=machine_home,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_a_teammate_invite_admits_one_machine_once() -> None:
    with _fixture("self-hosted"):
        issued = _cli(
            approver_home("self-hosted"), "invite", "Fixture Teammate", "--json"
        )
        assert issued.returncode == 0, issued.stderr
        invite_code = json.loads(issued.stdout)["result"]["code"]
        machine = _start_code("self-hosted")
        redeem = {
            key: machine[key] for key in ("machine_id", "machine_name", "platform")
        }
        redeem["invite_code"] = invite_code
        first = httpx.post(api_url("self-hosted") + INVITE_REDEEM_PATH, json=redeem)
        assert first.status_code == 200, first.text
        again = httpx.post(
            api_url("self-hosted") + INVITE_REDEEM_PATH,
            json={**redeem, "machine_id": str(uuid.uuid4())},
        )
        assert again.status_code != 200
        proved = _assert_state("self-hosted", "teammate-admitted")
        assert proved.returncode == 0, proved.stderr
        assert invite_code not in proved.stdout
        assert json.loads(proved.stdout.splitlines()[-1])["new_issued_invites"] == 1
        assert _assert_state("self-hosted", "owner-admitted").returncode == 1


def test_owner_approval_admits_the_machine_to_its_owner_only() -> None:
    with _fixture("self-hosted") as started:
        assert started["baseline"] == {"active_tokens": 1, "humans": 1, "machines": 0}
        code = _start_code("self-hosted")
        assert _poll("self-hosted", code).status_code != 200
        approval = _cli(
            approver_home("self-hosted"), "machines", "approve", code["user_code"]
        )
        assert approval.returncode == 0, approval.stderr
        credential = _poll("self-hosted", code)
        assert credential.status_code == 200 and credential.json()["token"]
        proved = _assert_state("self-hosted", "owner-admitted")
        assert proved.returncode == 0, proved.stderr
        report = json.loads(proved.stdout)
        assert report["new_humans"] == [] and len(report["new_machines"]) == 1
        refused = _assert_state("self-hosted", "nothing-admitted")
        assert refused.returncode == 1
        assert refused.stderr.startswith("machine_admission_state_mismatch:")
        assert credential.json()["token"] not in proved.stdout + refused.stderr


def test_company_sign_in_admits_a_distinct_teammate() -> None:
    mode = "self-hosted-company-sign-in"
    with _fixture(mode):
        code = _start_code(mode)
        browser = httpx.Client(follow_redirects=True)
        assert browser.get(api_url(mode) + "/v1/auth/oidc/start").status_code == 200
        decision = browser.post(
            api_url(mode) + "/v1/functions/call",
            json={
                "version": "v1",
                "function": "machine_authorization.resolve",
                "target": {"kind": "global"},
                "payload": {"code": code["user_code"], "action": "approve"},
            },
        )
        assert decision.json()["success"] is True, decision.text
        assert _poll(mode, code).status_code == 200
        proved = _assert_state(mode, "teammate-admitted")
        assert proved.returncode == 0, proved.stderr
        assert len(json.loads(proved.stdout)["new_humans"]) == 1
        assert _assert_state(mode, "owner-admitted").returncode == 1


def test_local_mode_births_a_disposable_universe_and_admits_nobody() -> None:
    with _fixture("local") as started:
        assert started["machine_home"] == str(mode_root("local") / "home")
        assert started["baseline"]["humans"] == 1
        refused = _cli(mode_root("local") / "home", "invite", "Fixture Teammate")
        assert refused.returncode != 0
        assert "invite_local_universe" in refused.stdout + refused.stderr
        proved = _assert_state("local", "nothing-admitted")
        assert proved.returncode == 0, proved.stderr
        unknown = _assert_state("local", "owner-admitted")
        assert unknown.stderr.startswith("machine_admission_expectation_unknown:")


BASE = {
    "humans": [1],
    "owner_actor_id": 1,
    "machines": {},
    "tokens": [[1, None]],
    "identities": {},
    "consumed_invites": [],
    "org_members": [1],
}


@pytest.mark.parametrize(
    ("current", "expect", "message"),
    [
        (
            {
                **BASE,
                "humans": [1, 2],
                "machines": {"m": 2},
                "tokens": [[1, None], [2, "m"]],
            },
            "owner-admitted",
            "not the owner",
        ),
        (
            {**BASE, "machines": {"m": 1}, "tokens": [[1, None], [1, "m"]]},
            "teammate-admitted",
            "belongs to the owner",
        ),
        (
            {**BASE, "machines": {"m": 1}, "tokens": [[1, None]]},
            "owner-admitted",
            "expected one active credential",
        ),
        ({**BASE, "machines": {"m": 1, "n": 1}}, "owner-admitted", "exactly one"),
        (
            {
                **BASE,
                "humans": [1, 2],
                "machines": {"m": 2},
                "tokens": [[1, None], [2, "m"]],
            },
            "teammate-admitted",
            "consumed by m",
        ),
        (
            {
                **BASE,
                "humans": [1, 2],
                "machines": {"m": 2},
                "tokens": [[1, None], [2, "m"]],
                "consumed_invites": [[2, "m"]],
            },
            "teammate-admitted",
            "without an org role",
        ),
    ],
)
def test_state_proof_names_the_wrong_subject(current, expect, message) -> None:
    failures = expectation_failures("self-hosted", expect, BASE, current)
    assert any(message in failure for failure in failures), failures
