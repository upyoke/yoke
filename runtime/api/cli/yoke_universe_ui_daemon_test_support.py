# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import os

from pathlib import Path

import socket

import subprocess

import sys

from types import SimpleNamespace

import pytest

from yoke_cli.config import universe_ui_daemon as daemon

from yoke_cli.config import universe_ui_launchd as launchd

from yoke_cli.config import universe_ui_daemon_state as state

CHILD_SCRIPT = """
import socket, sys, time
from yoke_cli.config import universe_ui_daemon as daemon
host, port, env = sys.argv[1], int(sys.argv[2]), sys.argv[3]
listener = socket.socket()
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind((host, port))
listener.listen(8)
daemon.publish_serving_identity(host=host, port=port, env=env)
while True:
    time.sleep(0.2)
"""


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
