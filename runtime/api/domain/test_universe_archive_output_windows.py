"""Private archive output uses the shared Windows file custody boundary."""
from __future__ import annotations

from yoke_core.domain import universe_archive_output as output


def test_windows_commit_does_not_try_to_open_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(output, "_WINDOWS", True)
    protected = []
    monkeypatch.setattr(output.windows_private_directory, "make_private_file", protected.append)
    destination = tmp_path / "universe.tar"
    private = output.prepare_private_archive_output(destination)
    with private as stream:
        stream.write(b"universe")
    assert protected == [private.temporary]
    monkeypatch.setattr(output.os, "open", lambda *args, **kw: (_ for _ in ()).throw(
        AssertionError("Windows must not open a directory for fsync")))
    private.commit()
    assert destination.read_bytes() == b"universe"
    assert private.committed


def test_windows_refuses_unsafe_existing_archive(monkeypatch, tmp_path):
    import pytest
    monkeypatch.setattr(output, "_WINDOWS", True)
    destination = tmp_path / "public.tar"
    destination.write_bytes(b"old")
    monkeypatch.setattr(output, "is_owner_private_file", lambda path: False)
    with pytest.raises(output.PrivateArchiveOutputError, match="current-owner"):
        output.prepare_private_archive_output(destination)
    assert destination.read_bytes() == b"old"


def test_snapshot_staging_file_has_private_owner_permissions(tmp_path):
    from yoke_contracts.owner_private_path import is_owner_private_file
    from yoke_core.domain.universe_snapshot_archive import _staged_dump_path
    staged = _staged_dump_path(tmp_path / "universe.tar")
    try:
        assert staged.read_bytes() == b""
        assert is_owner_private_file(staged)
    finally:
        staged.unlink()
