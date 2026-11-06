# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import os

import stat

from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_test_support import (
    MACHINE_ONLY_ANSWERS,
    AgentDriver,
    isolate_agent_setup,
)

from yoke_contracts.machine_authorization import (
    HostedMachineAuthorizationDenied,
    HostedMachineCredential,
    PendingMachineAuthorization,
)

from yoke_cli.config import (
    github_device_flow,
    github_machine,
    hosted_machine_authorization,
    setup_agent_answers,
    yoke_token_verify,
)

from yoke_contracts.bounded_json_http import BoundedJsonHttpResponse

pytest.importorskip("textual")

TOKEN = "token-never-shown"

VERIFIED = {
    "ok": True,
    "actor": {"label": "Test Person"},
    "orgs": [{"name": "Acme"}],
    "projects": [],
}


def _pending(code: str) -> PendingMachineAuthorization:
    return PendingMachineAuthorization(
        platform_url="https://app.upyoke.com",
        device_code=f"device-{code}",
        user_code=code,
        verification_uri="https://app.upyoke.com/machine",
        verification_uri_complete=f"https://app.upyoke.com/machine?code={code}",
        expires_in=600,
        interval=5,
    )


class Server:
    """Codes started, and what each one-shot poll answers in turn."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.polls: list[object] = []

    def start(self, *_a, **_k) -> PendingMachineAuthorization:
        self.started.append(f"CODE-{len(self.started) + 1}")
        return _pending(self.started[-1])

    def poll_once(self, pending: PendingMachineAuthorization):
        assert pending.device_code == f"device-{self.started[-1]}"
        answer = self.polls.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _saved() -> dict:
    return json.loads(setup_agent_answers.store_path().read_text(encoding="utf-8"))


def _only_browser(result) -> dict:
    code, lines = result
    assert (code, [line["state"] for line in lines]) == (0, ["browser"]), lines
    return lines[0]
