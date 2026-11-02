"""Concurrent artifact downloads keep the serial manifest and first refusal."""

import io
import threading
import time

import pytest
from botocore.exceptions import ClientError

from yoke_core.domain import universe_artifact_store as storage
from yoke_core.domain import universe_artifact_transfer as transfer
from yoke_core.domain.universe_archive import UniverseArchiveError


def _error(code):
    return ClientError({"Error": {"Code": code, "Message": "private"}}, "GetObject")


class SlowObjects:
    """Earlier keys answer later, so completion order inverts source order."""

    def __init__(self, count, failures=None):
        self.count = count
        self.failures = failures or {}
        self.lock = threading.Lock()
        self.active = self.peak = 0

    def get_object(self, *, Bucket, Key):
        index = int(Key)
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep((self.count - index) * 0.002)
            if index in self.failures:
                raise _error(self.failures[index])
            return {"Body": io.BytesIO(f"bytes-{index}".encode() * (index + 1))}
        finally:
            with self.lock:
                self.active -= 1


def _sources(count):
    sources = []
    for index in range(count):
        source = {
            "artifact_id": index,
            "project": "example",
            "key": f"qa-artifacts/example/{index:03d}",
            "original_handle": {"backend": "s3", "bucket": "b", "key": str(index)},
        }
        if index % 7 == 3:
            source.update(status="missing", reason="artifact_handle_or_owner_unavailable")
        sources.append(source)
    return sources


def _collect(monkeypatch, tmp_path, objects, count, workers):
    monkeypatch.setattr(transfer, "DOWNLOAD_WORKERS", workers)
    monkeypatch.setattr(
        transfer, "artifact_sources", lambda *_a, **_k: _sources(count)
    )
    built = []

    def factory(project, store):
        built.append(project)
        return objects

    manifest, files = transfer.collect_artifacts(
        None, tmp_path, stores={"example": {}}, client_factory=factory
    )
    return manifest, files, built


def test_concurrent_manifest_equals_serial(tmp_path, monkeypatch):
    count = 40
    failures = {5: "NoSuchKey", 18: "404"}
    serial = _collect(
        monkeypatch, tmp_path / "serial", SlowObjects(count, failures), count, 1
    )
    objects = SlowObjects(count, failures)
    concurrent = _collect(monkeypatch, tmp_path / "concurrent", objects, count, 8)

    assert concurrent[0] == serial[0]
    assert [e["key"] for e in concurrent[0]["entries"]] == [
        s["key"] for s in _sources(count)
    ]
    missing = [e for e in concurrent[0]["entries"] if e["status"] == "missing"]
    assert {e["reason"] for e in missing} == {
        "artifact_source_absent",
        "artifact_handle_or_owner_unavailable",
    }
    assert sorted(concurrent[1]) == sorted(serial[1])
    for key, path in concurrent[1].items():
        assert path.read_bytes() == serial[1][key].read_bytes()
    assert not (tmp_path / "concurrent/qa-artifacts/example/005").exists()
    assert objects.peak > 1
    assert concurrent[2] == ["example"]


def test_first_failure_in_source_order_refuses(tmp_path, monkeypatch):
    count = 30
    # Index 25 fails first in time; index 4 is earlier in source order.
    objects = SlowObjects(count, {4: "AccessDenied", 25: "SlowDown"})
    with pytest.raises(UniverseArchiveError) as caught:
        _collect(monkeypatch, tmp_path, objects, count, 8)
    assert str(caught.value) == (
        "archive_artifact_unreadable: example qa-artifacts/example/004: "
        "AccessDenied; repair access to that file or store and retry, "
        "or export with --exclude-artifacts"
    )
    assert objects.active == 0


def test_store_refusal_propagates_unchanged(tmp_path, monkeypatch):
    error = UniverseArchiveError("archive_artifact_store_unavailable: configure region")

    def fail(*_a, **_k):
        raise error

    monkeypatch.setattr(storage, "_client", fail)
    monkeypatch.setattr(transfer, "artifact_sources", lambda *_a, **_k: _sources(3))
    with pytest.raises(UniverseArchiveError) as caught:
        transfer.collect_artifacts(None, tmp_path, stores={})
    assert caught.value is error
