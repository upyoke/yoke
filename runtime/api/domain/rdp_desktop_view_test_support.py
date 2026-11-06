# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import base64

from contextlib import contextmanager

import io

import json

from pathlib import Path

import stat

import subprocess

import pytest

from yoke_contracts.machine_config.capability_secret_store import store_machine_capability_secret

from yoke_harness import desktop_access, rdp_desktop_client as viewer

PASSWORD = "fixture-secret"

SETTINGS = {
    "resource_name": "lab",
    "os": "windows",
    "host": "host.example",
    "user": "Administrator",
    "desktop_route": "ssh-forward",
    "desktop_protocol": "rdp",
    "desktop_port": "3390",
    "desktop_user": "fixture",
}

RECEIPT = {"desktop_session": "reused", "environment": {"DISPLAY": ":10.0"}}


class Client:
    def __init__(self, *, interrupted=False, code=0, output=None):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(
            output or "client started\npassword=" + PASSWORD + "\n"
        )
        self.code = code
        self.returncode = None
        self.password = None
        self.running = True
        self.interrupted = interrupted
        self.terminated = False

    def poll(self):
        return None if self.running else self.code

    def wait(self, timeout=None):
        if self.interrupted and timeout is None:
            raise KeyboardInterrupt()
        self.running = False
        self.returncode = self.code
        return self.code

    def terminate(self):
        self.terminated = True


def geometry(command, **kw):
    assert "DISPLAY=:10.0" in command and "xwininfo -root" in command
    return subprocess.CompletedProcess(
        command, 0, "  Width: 1280\n  Height: 1024\n  Depth: 24\n", ""
    )
