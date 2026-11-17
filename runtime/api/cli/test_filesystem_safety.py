"""Tests for shared symlink-component and atomic-file safety helpers."""

import stat
from types import SimpleNamespace
from pathlib import Path

import pytest

from yoke_contracts import filesystem_safety


def test_atomic_replace_cleans_unique_temporary_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "settings.json"

    def refuse_replace(_source, _target):
        raise OSError("injected replace failure")

    monkeypatch.setattr(filesystem_safety.os, "replace", refuse_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        filesystem_safety.atomic_replace_bytes(target, b"payload\n")

    assert list(tmp_path.glob(".settings.json.*.tmp")) == []
    assert not target.exists()


def test_first_symlink_component_can_exclude_materializable_leaf(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    leaf = tmp_path / "leaf"
    leaf.symlink_to(real_parent)

    assert filesystem_safety.first_symlink_component(tmp_path, leaf) is None
    assert filesystem_safety.first_symlink_component(
        tmp_path, leaf, include_leaf=True,
    ) == leaf


def test_atomic_replace_preserves_existing_private_file_mode(
    tmp_path: Path,
) -> None:
    target = tmp_path / "settings.json"
    target.write_bytes(b"old\n")
    target.chmod(0o600)

    filesystem_safety.atomic_replace_bytes(target, b"new\n")

    assert target.read_bytes() == b"new\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_atomic_replace_preserves_private_mode_from_symlink_target(
    tmp_path: Path,
) -> None:
    linked_target = tmp_path / "shared-settings.json"
    linked_target.write_bytes(b"shared\n")
    linked_target.chmod(0o600)
    materialized = tmp_path / "settings.json"
    materialized.symlink_to(linked_target)

    filesystem_safety.atomic_replace_bytes(materialized, b"local\n")

    assert not materialized.is_symlink()
    assert materialized.read_bytes() == b"local\n"
    assert stat.S_IMODE(materialized.stat().st_mode) == 0o600
    assert linked_target.read_bytes() == b"shared\n"


@pytest.mark.windows
def test_atomic_replace_on_windows_does_not_require_fchmod(tmp_path, monkeypatch):
    host_os = filesystem_safety.os
    native_os = SimpleNamespace(name="nt", **{
        name: getattr(host_os, name) for name in ("fdopen", "fsync", "close", "replace", "chmod")
    })
    monkeypatch.setattr(filesystem_safety, "os", native_os)
    target = tmp_path / "rendered.md"
    filesystem_safety.atomic_replace_bytes(target, b"rendered\n")
    assert target.read_bytes() == b"rendered\n"
    assert list(tmp_path.glob(".rendered.md.*.tmp")) == []


def _flaky(failures: int):
    calls = []

    def operation():
        calls.append(None)
        if len(calls) <= failures:
            raise PermissionError("[WinError 5] Access is denied")
        return "done"

    return operation, calls


def test_windows_sharing_violation_is_retried_until_the_holder_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(filesystem_safety, "_RETRY_SHARING_VIOLATIONS", True)
    operation, calls = _flaky(3)
    assert filesystem_safety.retry_sharing_violations(operation) == "done"
    assert len(calls) == 4


def test_windows_sharing_violation_that_outlasts_the_window_is_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(filesystem_safety, "_RETRY_SHARING_VIOLATIONS", True)
    monkeypatch.setattr(filesystem_safety, "SHARING_RETRY_SECONDS", 0.05)
    operation, calls = _flaky(10**6)
    with pytest.raises(PermissionError, match="Access is denied"):
        filesystem_safety.retry_sharing_violations(operation)
    assert len(calls) > 1


def test_permission_error_off_windows_is_a_real_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(filesystem_safety, "_RETRY_SHARING_VIOLATIONS", False)
    operation, calls = _flaky(1)
    with pytest.raises(PermissionError):
        filesystem_safety.retry_sharing_violations(operation)
    assert len(calls) == 1
