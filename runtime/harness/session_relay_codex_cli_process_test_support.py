# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from io import BytesIO, StringIO

import json

import os

from pathlib import Path

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap

from yoke_harness import session_relay_codex_app_server as app_module

from yoke_harness import session_relay_codex_cli as cli_module

from yoke_harness import session_relay_codex_cli_process as process_module

from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV

from yoke_harness.session_relay_codex import CodexNativeOutcome, CodexNativeRequest

from yoke_harness.session_relay_codex_invocation import codex_base_command

from yoke_harness.session_relay_inventory import ResolvedNativeCli

from yoke_harness.session_relay_codex_worker_protocol import request_payload

SECRET = "codex-cli-owner-attestation"

INSTRUCTION = native_launch_bootstrap("launch-1")


def _request(tmp_path: Path, *, surface: str = "codex-cli") -> CodexNativeRequest:
    return CodexNativeRequest(
        job_kind="launch",
        job_id="12345678-1234-4234-8234-123456789abc",
        surface=surface,
        surface_version="0.148.0-alpha.15",
        checkout=tmp_path,
        requested_model="gpt-5.6",
        presentation="focused",
        target_liveness=None,
        target_session_id=None,
        wake_mode=None,
        instruction_id="launch:12345678-1234-4234-8234-123456789abc",
        native_instruction=INSTRUCTION,
        launch_attestation=SECRET,
    )
