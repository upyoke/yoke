"""Private and durable portable-archive destination handling."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import universe_archive_output as output


def test_private_archive_fsyncs_file_before_atomic_replace(monkeypatch, tmp_path: Path):
    destination = tmp_path / "universe.dump"
    events = []
    real_fsync = output.os.fsync
    real_replace = output.os.replace

    def fsync(descriptor):
        events.append("fsync")
        real_fsync(descriptor)

    def replace(source, target):
        events.append("replace")
        real_replace(source, target)

    monkeypatch.setattr(output.os, "fsync", fsync)
    monkeypatch.setattr(output.os, "replace", replace)
    archive = output.prepare_private_archive_output(destination)

    with archive as stream:
        stream.write(b"private archive")
    archive.commit()

    assert events == ["fsync", "replace", "fsync"]
    assert destination.read_bytes() == b"private archive"
