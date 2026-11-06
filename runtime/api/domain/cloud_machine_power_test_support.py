# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import subprocess

import pytest

from yoke_contracts.machine_qa_failures import HostControlLocalError

from yoke_core.domain import cloud_machine_power

from yoke_core.domain.deploy_remote import CommandResult

from yoke_core.domain.cloud_machine_power import (
    power_on,
    wait_for_ssh_login,
)

from runtime.api.domain.deploy_remote_test_support import FakeRunner

OK = CommandResult(0, "", "")

CLOUD = {
    "resource_name": "windows-lab",
    "host": "54.0.0.1",
    "user": "Administrator",
    "os": "windows",
    "cloud_instance_id": "i-1",
}

MAC = {"resource_name": "mac-lab", "host": "10.0.0.2", "user": "qa", "os": "macos"}
