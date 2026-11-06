# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import base64

import shlex

import subprocess

from types import SimpleNamespace

from yoke_contracts.test_machine_types import HostActionResult

import pytest

from yoke_contracts.machine_qa_execution import GUI_SESSION_CONTEXT

from yoke_harness.baseline_harness_requests import PROBE_PROMPT, harness_request

from yoke_harness.baseline_probe_failure_causes import PROBE_EXIT_CODES

from yoke_harness.ssh_linux_baseline import capture_linux_golden, prove_linux_probes

from yoke_harness.ssh_mac_baseline_probes import (
    prove_declared_probes,
    prove_probes_document,
)

from yoke_harness.ssh_mac_golden_capture import capture_golden_baseline

from yoke_harness import ssh_mac_gui_session

from yoke_harness.ssh_mac_transport import SshMacTransport

from yoke_harness.ssh_linux_host_operations import SshLinuxHostOperations


def _document(program):
    return json.dumps(
        {
            "probes": [
                {
                    "name": "signed-in harness",
                    "argv": [f"/home/test/.local/bin/{program}", "status"],
                    "expect_output_contains": "Logged in",
                }
            ]
        }
    )


def _events(*events):
    return "\n".join(json.dumps(event) for event in events)


def _response(program):
    if program == "codex":
        return _events(
            {"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}},
            {"type": "turn.completed", "usage": {"output_tokens": 1}},
        )
    return _events(
        {"type": "result", "subtype": "success", "is_error": False, "result": "OK"}
    )


class _Control:
    golden_baseline_path = "/srv/golden"

    def __init__(self, program, *, stdout=None, returncode=0):
        self.document = _document(program)
        self.result = SimpleNamespace(
            returncode=returncode,
            stdout=_response(program) if stdout is None else stdout,
            stderr="private-account@example.com expired OAuth token",
        )
        self.calls = []

    def check_terminal_bridge(self):
        return HostActionResult(True, {})

    def run_command(self, argv, *, timeout, **kwargs):
        self.calls.append((list(argv), timeout, kwargs))
        return self.result

    def read_remote_text(self, path):
        assert path == self.golden_baseline_path + ".probes"
        return self.document
