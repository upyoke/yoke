"""Real database archive transfers preserve file contents across local and S3 stores."""

import contextlib
import hashlib
import io
import json
from pathlib import Path

import psycopg
import pytest

from runtime.api.domain._universe_import_test_helpers import _canonical_universe
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.machine_config import runtime as machine_runtime
from yoke_core.domain import universe_artifact_store as store
from yoke_core.domain import universe_export, local_universe_import, universe_import_cli
from yoke_core.domain.universe_artifact_transfer import estimate_universe
from yoke_core.domain.qa_artifact_handle import parse_handle
from yoke_core.domain.shared_file_storage import read_shared_file


class Objects:
    def __init__(self):
        self.objects = {}

    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Bucket, Key])}

    def head_object(self, *, Bucket, Key):
        return {"ContentLength": len(self.objects[Bucket, Key])}

    def put_object(self, *, Bucket, Key, Body, **kwargs):
        self.objects[Bucket, Key] = Body.read()

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, *, Bucket, Prefix):
        yield {
            "Contents": [
                {"Key": key, "Size": len(data)}
                for (bucket, key), data in self.objects.items()
                if bucket == Bucket and key.startswith(Prefix)
            ]
        }


def _seed(conn, handle):
    item_id = 88541
    insert_item(conn, id=item_id, title="Portable files", workflow_id="issue")
    requirement = conn.execute(
        "INSERT INTO qa_requirements(item_id,qa_kind,qa_phase,created_at) "
        "VALUES (%s,'manual','verification',now()) RETURNING id",
        (item_id,),
    ).fetchone()[0]
    run = conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,created_at) "
        "VALUES (%s,'test','manual','pass',now()) RETURNING id",
        (requirement,),
    ).fetchone()[0]
    for source_handle in (handle, {"backend": "local", "path": "/absent/artifact"}):
        conn.execute(
            "INSERT INTO qa_artifacts(qa_run_id,artifact_type,artifact_handle,created_at) "
            "VALUES (%s,'text',%s,now())",
            (run, json.dumps(source_handle)),
        )
    conn.commit()


def _configure(conn, routing):
    project_id = conn.execute("SELECT id FROM projects WHERE slug='yoke'").fetchone()[0]
    site = conn.execute(
        "INSERT INTO sites(project_id,name,created_at) "
        "VALUES(%s,'files',now()) RETURNING id",
        (project_id,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO environments(site,project_id,name,settings,created_at) "
        "VALUES(%s,%s,'prod',%s,now())",
        (site, project_id, json.dumps({"artifacts": routing})),
    )
    conn.execute(
        "INSERT INTO project_capabilities(project_id,type,settings,created_at) "
        "VALUES(%s,'aws-admin',%s,now())",
        (project_id, json.dumps({"region": routing["region"]})),
    )
    conn.commit()


@pytest.mark.parametrize(
    "source_s3,destination_s3,container",
    [
        (False, False, False),
        (False, True, False),
        (True, False, False),
        (False, False, True),
    ],
)
def test_archive_roundtrip_rehomes_bytes(
    tmp_path, monkeypatch, source_s3, destination_s3, container
):
    objects = Objects()
    monkeypatch.setattr(store, "_client", lambda project, routing: objects)
    source_home, dest_home = tmp_path / "source-home", tmp_path / "dest-home"
    monkeypatch.setenv(machine_runtime.HOME_ENV, str(source_home))
    content = b"portable QA evidence\x00\xff"
    shared = b"shared file bytes"
    local = source_home / "artifacts" / "original.txt"
    local.parent.mkdir(parents=True)
    local.write_bytes(content)
    shared_path = source_home / "shared-files" / "yoke" / "folder" / "notes.txt"
    shared_path.parent.mkdir(parents=True)
    shared_path.write_bytes(shared)
    handle = {"backend": "local", "path": str(local)}
    source_routing = {
        "bucket": "source-bucket",
        "prefix": "source-prefix",
        "region": "us-east-1",
    }
    if source_s3:
        objects.objects["source-bucket", "old/qa-artifacts/yoke/evidence"] = content
        objects.objects[
            "source-bucket", "source-prefix/shared-files/yoke/folder/notes.txt"
        ] = shared
        handle = {
            "backend": "s3",
            "bucket": "source-bucket",
            "key": "old/qa-artifacts/yoke/evidence",
        }
    with _canonical_universe() as (source, source_dsn):
        from yoke_core.domain.api_tokens import bootstrap_admin_token

        bootstrap_admin_token(source)
        _seed(source, handle)
        if source_s3:
            _configure(source, source_routing)
        estimate = estimate_universe(dsn=source_dsn)
        assert estimate["artifact_bytes"] == len(content) + len(shared)
        assert estimate["missing_artifacts"] == 1
        report = universe_export.export_universe(
            dsn=source_dsn, out=tmp_path / "move.tar"
        )
        assert report["artifacts"] == {"included": 2, "missing": 1}
        # Remove the local source to prove import reads only the archive.
        local.unlink()
        shared_path.unlink()
    monkeypatch.setenv(machine_runtime.HOME_ENV, str(dest_home))
    targets = contextlib.ExitStack()
    destination, target_dsn = targets.enter_context(_canonical_universe())
    routing = {
        "bucket": "destination-bucket",
        "prefix": "destination",
        "region": "us-east-1",
    }
    if destination_s3:
        insert_item(
            destination, id=88542, title="Previous universe", workflow_id="issue"
        )
        _configure(destination, routing)
    destination.close()
    try:
        if container:
            with Path(report["artifact"]).open("rb") as stream:
                result = universe_import_cli.import_from_stream(stream, dsn=target_dsn)
        else:
            result = local_universe_import.import_universe(
                report["artifact"], dsn=target_dsn
            )
        assert result["artifacts"] == {"included": 2, "missing": 1, "manifest": True}
        with psycopg.connect(target_dsn) as target:
            restored = parse_handle(
                target.execute(
                    "SELECT artifact_handle FROM qa_artifacts ORDER BY id LIMIT 1"
                ).fetchone()[0]
            )
            with store.read_handle(restored, project="yoke", store=routing) as stream:
                actual = stream.read()
            assert actual == content
            assert hashlib.sha256(actual).digest() == hashlib.sha256(content).digest()
            if destination_s3:
                assert restored["bucket"] == "destination-bucket"
                assert (
                    objects.objects[
                        "destination-bucket",
                        "destination/shared-files/yoke/folder/notes.txt",
                    ]
                    == shared
                )
                from yoke_core.domain.handlers.qa_artifact_presign import (
                    resolve_artifacts_bucket,
                )

                assert resolve_artifacts_bucket(target, 1, None)[1:] == (
                    "destination-bucket",
                    "destination",
                )
            else:
                from yoke_core.domain.handlers.qa_artifact_read import _local_result
                from yoke_core.domain.qa_artifact_owner import requirement_storage_owner
                from yoke_core.domain.db_row import postgres_row_factory

                with target.cursor(row_factory=postgres_row_factory) as cursor:
                    requirement, run_id = target.execute(
                        "SELECT qa_requirement_id,id FROM qa_runs ORDER BY id LIMIT 1"
                    ).fetchone()
                    owner = requirement_storage_owner(cursor, requirement)
                readable = _local_result(
                    {**owner, "run_id": run_id, "metadata": "{}"}, restored
                )
                assert readable["disposition"] == "ready"
                assert str(dest_home) in restored["path"]
                assert (
                    read_shared_file(
                        target, project_id=1, project="yoke", path="folder/notes.txt"
                    )
                    == shared
                )
    finally:
        targets.close()


def test_two_member_archive_imports_without_rewriting_handles(tmp_path):
    with _canonical_universe() as (source, source_dsn):
        from yoke_core.domain.api_tokens import bootstrap_admin_token

        bootstrap_admin_token(source)
        report = universe_export.export_universe(
            dsn=source_dsn,
            out=tmp_path / "legacy.tar",
            exclude_artifacts=True,
        )
    import tarfile

    with tarfile.open(report["artifact"]) as reader:
        assert reader.getnames() == ["freeze-receipt.json", "universe.dump"]
    with _canonical_universe() as (target, target_dsn):
        target.close()
        result = local_universe_import.import_universe(
            report["artifact"], dsn=target_dsn
        )
        assert result["ok"] is True
        assert result["artifacts"] == {"included": 0, "missing": 0, "manifest": False}
