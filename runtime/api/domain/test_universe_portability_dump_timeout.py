"""Timeout attribution for the universe export dump subprocess.

A tiny universe dumps in well under a second, so an export that reaches its
end-to-end timeout is a stall, not slowness. The failure must say which side
stalled — the ``pg_dump`` subprocess or the archive write — and surface the
redacted stderr tail, or the operator is left with an unattributable flake.
"""

from __future__ import annotations

import io
import logging
import subprocess
import threading

import pytest

from yoke_core.domain import universe_portability as portability
from yoke_core.domain import universe_portability_dump as dump_runtime


_DSN = "host=localhost port=5432 user=u password=supersecret dbname=d"


class _HungDump:
    """A dump subprocess that never finishes: ``wait`` always times out."""

    exit_code_on_entry: "int | None" = None

    def __init__(self, *_args, **_kwargs):
        self.stdout = io.BytesIO()
        self.stderr = io.BytesIO(
            b"pg_dump: note before stall with password supersecret\n"
        )
        self.returncode = self.exit_code_on_entry

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired(["pg_dump"], timeout)

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


class _ExitedDump(_HungDump):
    """The state the stalled-archive-write path observes: pg_dump exited."""

    exit_code_on_entry = 0


class _CompletedDump(_HungDump):
    """A completed dump whose stdout still has to reach durable storage."""

    exit_code_on_entry = 0

    def __init__(self, *_args, **_kwargs):
        super().__init__()
        self.stdout = io.BytesIO(b"portable archive")
        self.stderr = io.BytesIO()

    def wait(self, timeout=None):
        return self.returncode


def _export(tmp_path, monkeypatch, fake):
    monkeypatch.setattr(subprocess, "Popen", fake)
    destination = tmp_path / "universe.dump"
    with pytest.raises(portability.UniversePortabilityError) as excinfo:
        portability.dump_universe(
            _DSN, destination, timeout_s=1, pg_dump="pg_dump"
        )
    assert not destination.exists()
    return str(excinfo.value)


def test_export_timeout_names_running_pg_dump_phase(
    tmp_path, monkeypatch, caplog
):
    with caplog.at_level(logging.ERROR, logger="yoke.universe.portability"):
        message = _export(tmp_path, monkeypatch, _HungDump)

    assert "universe export timed out after 1s" in message
    assert "pg_dump was still running" in message
    assert "s elapsed" in message
    assert "pg_dump: note before stall" in caplog.text
    assert "supersecret" not in caplog.text
    assert "<redacted-secret>" in caplog.text


def test_export_timeout_names_stalled_archive_write(tmp_path, monkeypatch):
    message = _export(tmp_path, monkeypatch, _ExitedDump)

    assert "universe export timed out after 1s" in message
    assert "the archive write stalled after pg_dump exited" in message


def test_archive_writer_receives_the_remaining_export_budget(
    tmp_path, monkeypatch
):
    joins: list[float | None] = []
    original_join = threading.Thread.join

    def recording_join(self, timeout=None):
        joins.append(timeout)
        return original_join(self, timeout)

    monkeypatch.setattr(subprocess, "Popen", _CompletedDump)
    monkeypatch.setattr(threading.Thread, "join", recording_join)
    marker = object()
    destination = tmp_path / "universe.dump"

    result = dump_runtime.dump_universe(
        _DSN,
        destination,
        timeout_s=30,
        pg_dump="pg_dump",
        archive_inspector=lambda *_args, **_kwargs: marker,
    )

    assert result is marker
    assert destination.read_bytes() == b"portable archive"
    assert joins[0] is not None and joins[0] > 20
