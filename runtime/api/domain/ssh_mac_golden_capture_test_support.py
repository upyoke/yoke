# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import shlex

from types import SimpleNamespace

import pytest

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    run_zsh_syntax_if_available,
)

from yoke_harness.ssh_mac_golden_capture import (
    execute_golden_capture,
    probes_document_digest,
)

from yoke_harness.ssh_mac_golden_capture_contract import (
    CAPTURE_ENTRIES_PREFIX,
    CAPTURE_FAILURE_PREFIX,
    CAPTURE_KILOBYTES_PREFIX,
    CAPTURE_MANIFEST_DIGEST_PREFIX,
    CAPTURE_PHASES,
    CAPTURE_REFUSAL_KIND_DESTINATION_OCCUPIED,
    CAPTURE_REFUSAL_KIND_FOREIGN_OWNER,
    CAPTURE_REFUSAL_KIND_RESIDUE,
    CAPTURE_REFUSAL_PREFIX,
    GOLDEN_CAPTURE_MARKER,
    GOLDEN_CAPTURE_REMOTE_PATH,
    GOLDEN_SIDECAR_MODE,
)

from yoke_harness.ssh_mac_golden_capture_script import render_golden_capture_script

from yoke_harness.ssh_mac_full_reset_contract import (
    GOLDEN_MANIFEST_SUFFIX,
    GOLDEN_PROBES_SUFFIX,
    resolve_full_reset_path_contract,
)

from yoke_cli.config.path_doctor import resolve_path_state_contract

HOME = "/Users/tester"

DESTINATION = "/Users/Shared/yoke-golden/tester-home-20260903"

PROBES = '{"probes": [{"name": "harness", "argv": ["/bin/test", "-e", "/"]}]}'

MANIFEST_DIGEST = "c" * 64


class FakeCaptureTransport:
    def __init__(self, stdout: str, *, capture_returncode: int = 0) -> None:
        self.stdout = stdout
        self.capture_returncode = capture_returncode
        self.uploads: dict[str, str] = {}
        self.commands: list[tuple[str, int]] = []
        self.cleanup_returncode = 0
        self.seal_returncode = 0

    def upload(self, path: str, content: str) -> None:
        self.uploads[path] = content

    def run(self, command: str, *, timeout: int = 60):
        self.commands.append((command, timeout))
        argv = shlex.split(command)
        if argv and argv[0] == GOLDEN_CAPTURE_REMOTE_PATH:
            return SimpleNamespace(
                returncode=self.capture_returncode,
                stdout=self.stdout,
            )
        if argv[:3] == ["/bin/rm", "-f", "--"]:
            return SimpleNamespace(returncode=self.cleanup_returncode, stdout="")
        if argv[:3] == ["/bin/chmod", "--", GOLDEN_SIDECAR_MODE]:
            return SimpleNamespace(
                returncode=self.seal_returncode, stdout="", stderr="seal denied"
            )
        return SimpleNamespace(returncode=0, stdout="")


def closed_capture_stdout(
    *,
    entries: int = 34,
    kilobytes: int = 2048,
    manifest_digest: str = MANIFEST_DIGEST,
) -> str:
    """Return the counted success receipt the capture parser accepts."""
    return "\n".join(
        (
            f"{CAPTURE_ENTRIES_PREFIX}{entries}",
            f"{CAPTURE_KILOBYTES_PREFIX}{kilobytes}",
            f"{CAPTURE_MANIFEST_DIGEST_PREFIX}{manifest_digest}",
            GOLDEN_CAPTURE_MARKER,
        )
    )


def _capture(transport: FakeCaptureTransport, **overrides):
    arguments = {
        "run_remote": transport.run,
        "upload_text": transport.upload,
        "home": HOME,
        "destination": DESTINATION,
        "probes_document": PROBES,
    }
    arguments.update(overrides)
    return execute_golden_capture(**arguments)
