# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import io

import json

import multiprocessing

import os

import socket

import subprocess

import sys

import tempfile

import threading

import time

from contextlib import redirect_stderr, redirect_stdout

from pathlib import Path

from unittest.mock import Mock

import pytest

from yoke_cli.commands.adapters import hook_inprocess, hooks

from yoke_cli.hook_resident_client import ResidentUnavailable

from yoke_contracts.hook_evaluator_protocol import (
    HookEvaluatorRequest,
    receive_frame,
    send_frame,
)

from yoke_contracts.hook_resident_routing import is_read_only_tool_event

from yoke_contracts.hook_runner.hook_ordering import event_types

from yoke_harness.hook_resident_observations import MESSAGE_PROBE_INTERVAL_SECONDS


def _request(
    event_name: str,
    *,
    cwd: str,
    revision: str,
    environment: dict[str, str] | None = None,
    dry_run: bool = False,
) -> HookEvaluatorRequest:
    return HookEvaluatorRequest(
        event_name=event_name,
        stdin=json.dumps(
            {
                "session_id": f"resident-{event_name.lower()}",
                "tool_name": "Read",
                "tool_input": {"file_path": "/tmp/example"},
            }
        ),
        dry_run=dry_run,
        pid=41001,
        ppid=41000,
        cwd=cwd,
        environment=environment or dict(os.environ),
        revision=revision,
    )


def _round_trip(socket_path: str, request: HookEvaluatorRequest) -> dict:
    peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        peer.settimeout(10)
        peer.connect(socket_path)
        send_frame(peer, request.to_mapping())
        return receive_frame(peer)
    finally:
        peer.close()
