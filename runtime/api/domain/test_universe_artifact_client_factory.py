"""Caller-owned S3 clients and tenant routing carry real artifact bytes."""

import hashlib
import json

import pytest

from runtime.api.domain._universe_import_test_helpers import _canonical_universe
from runtime.api.domain.test_universe_artifact_transfer import Objects, _seed
from yoke_core.domain import universe_artifact_store as storage
from yoke_core.domain import universe_artifact_transfer as transfer
from yoke_core.domain.qa_artifact_handle import parse_handle, s3_handle
from yoke_core.domain.universe_archive import UniverseArchiveError
from yoke_core.domain.universe_archive_artifacts import MANIFEST


@pytest.fixture
def caller_store(monkeypatch):
    objects = Objects()
    routing = {"bucket": "tenant-source", "prefix": "tenants/source"}
    calls = []

    def factory(project, store):
        calls.append((project, store))
        return objects

    def unexpected_default(*args, **kwargs):
        pytest.fail("caller-owned transfer used machine storage settings")

    monkeypatch.setattr(storage, "project_stores", unexpected_default)
    monkeypatch.setattr(storage, "machine_aws_client", unexpected_default)
    return objects, routing, calls, factory


def test_collect_and_restore_caller_routing_without_region(tmp_path, caller_store):
    objects, routing, calls, factory = caller_store
    evidence = b"hosted evidence\x00\xff"
    shared = b"tenant shared file"
    original = s3_handle(routing["bucket"], "old/evidence.txt", "text/plain")
    objects.objects[routing["bucket"], original["key"]] = evidence
    objects.objects[routing["bucket"], "tenants/source/shared-files/yoke/notes.txt"] = (
        shared
    )
    # These must not leak through the caller's tenant prefix.
    objects.objects[
        routing["bucket"], "tenants/other/shared-files/yoke/private.txt"
    ] = b"other tenant"
    objects.objects[routing["bucket"], "shared-files/yoke/unscoped.txt"] = b"unscoped"
    with _canonical_universe() as (conn, _dsn):
        _seed(conn, original)
        manifest, files = transfer.collect_artifacts(
            conn,
            tmp_path / "artifacts",
            stores={"yoke": routing},
            client_factory=factory,
        )
        included = [e for e in manifest["entries"] if e["status"] == "included"]
        assert len(included) == 2
        assert sum(e["status"] == "missing" for e in manifest["entries"]) == 1
        assert {files[e["key"]].read_bytes() for e in included} == {evidence, shared}
        for entry in included:
            data = files[entry["key"]].read_bytes()
            assert entry["sha256"] == hashlib.sha256(data).hexdigest()
            assert entry["bytes"] == len(data)
        shared_entry = next(e for e in included if e["key"].startswith("shared-files/"))
        assert shared_entry["key"] == "shared-files/yoke/notes.txt"
        assert shared_entry["original_handle"]["key"] == (
            "tenants/source/shared-files/yoke/notes.txt"
        )
        assert calls and all(
            project == "yoke" and store is routing for project, store in calls
        )
        calls.clear()
        (tmp_path / MANIFEST).write_text(json.dumps(manifest))
        destination = {"bucket": "tenant-destination", "prefix": "tenants/destination"}
        result = transfer.restore_artifacts(
            conn,
            tmp_path / "universe.dump",
            {"yoke": destination},
            client_factory=factory,
        )
        assert result == {"included": 2, "missing": 1, "manifest": True}
        for entry in included:
            assert (
                objects.objects[
                    destination["bucket"], "tenants/destination/" + entry["key"]
                ]
                == files[entry["key"]].read_bytes()
            )
        restored = parse_handle(
            conn.execute(
                "SELECT artifact_handle FROM qa_artifacts ORDER BY id LIMIT 1"
            ).fetchone()[0]
        )
        assert restored["bucket"] == destination["bucket"]
        assert objects.objects[restored["bucket"], restored["key"]] == evidence
        assert calls and all(store is destination for _project, store in calls)


def test_estimate_uses_caller_head_and_shared_listing(caller_store):
    objects, routing, calls, factory = caller_store
    handle = s3_handle(routing["bucket"], "evidence.txt")
    objects.objects[routing["bucket"], handle["key"]] = b"evidence bytes"
    objects.objects[routing["bucket"], "tenants/source/shared-files/yoke/notes.txt"] = (
        b"shared bytes"
    )
    heads = []
    original_head = objects.head_object

    def head(**kwargs):
        heads.append(kwargs)
        return original_head(**kwargs)

    objects.head_object = head
    with _canonical_universe() as (conn, dsn):
        _seed(conn, handle)
        result = transfer.estimate_universe(
            dsn=dsn,
            stores={"yoke": routing},
            client_factory=factory,
        )
    assert result["artifact_bytes"] == len(b"evidence bytes") + len(b"shared bytes")
    assert (
        result["estimated_bytes"]
        == result["estimated_dump_bytes"] + result["artifact_bytes"]
    )
    assert result["artifact_count"] == 3
    assert result["missing_artifacts"] == 1
    assert heads == [{"Bucket": routing["bucket"], "Key": handle["key"]}]
    assert calls and all(store is routing for _project, store in calls)


def test_empty_caller_stores_do_not_load_machine_routing(tmp_path, caller_store):
    with _canonical_universe() as (conn, dsn):
        assert transfer.collect_artifacts(conn, tmp_path, stores={}) == (
            {"version": 1, "entries": []},
            {},
        )
        assert transfer.estimate_universe(dsn=dsn, stores={})["artifact_count"] == 0


def test_default_client_still_requires_region():
    with pytest.raises(
        UniverseArchiveError, match="archive_artifact_store_unavailable"
    ):
        storage.handle_size(s3_handle("bucket", "key"), project="example", store={})
