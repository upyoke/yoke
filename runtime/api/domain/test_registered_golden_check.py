"""Verify finds every golden registered for its home, or names the missing one."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness.registered_golden_check import (
    REGISTERED_GOLDEN_CHECK_FAILED,
    REGISTERED_GOLDEN_MISSING,
    check_registered_goldens,
)


def _run(command: str, *, timeout: int = 60):
    return subprocess.run(
        ["/bin/sh", "-c", command], capture_output=True, text=True, timeout=timeout
    )


def _golden(project: str, path: str) -> dict[str, str]:
    return {"project": project, "test_machine": f"{project}-mac", "path": path}


def test_every_present_golden_passes(tmp_path):
    for name in ("yoke", "platform"):
        (tmp_path / name).mkdir()

    check_registered_goldens(
        _run,
        [_golden("yoke", str(tmp_path / "yoke")), _golden("platform", str(tmp_path / "platform"))],
    )


def test_a_missing_or_symlinked_golden_is_named_by_path(tmp_path):
    (tmp_path / "yoke").mkdir()
    (tmp_path / "decoy").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "decoy")
    gone = str(tmp_path / "platform golden")

    with pytest.raises(HostControlLocalError) as raised:
        check_registered_goldens(
            _run,
            [
                _golden("yoke", str(tmp_path / "yoke")),
                _golden("platform", gone),
                _golden("other", str(tmp_path / "link")),
            ],
        )

    error = raised.value
    assert error.code == REGISTERED_GOLDEN_MISSING
    link = str(tmp_path / "link")
    registered = {str(tmp_path / "yoke"), gone, link}
    assert {path for path in registered if path in str(error)} == {gone, link}


def test_an_unreachable_host_refuses_by_name():
    def failing(_command: str, *, timeout: int = 60):
        return SimpleNamespace(returncode=255, stdout="", stderr="Connection refused")

    with pytest.raises(HostControlLocalError) as raised:
        check_registered_goldens(failing, [_golden("yoke", "/Users/Shared/g/yoke")])

    assert raised.value.code == REGISTERED_GOLDEN_CHECK_FAILED
    assert "Connection refused" in raised.value.stderr
