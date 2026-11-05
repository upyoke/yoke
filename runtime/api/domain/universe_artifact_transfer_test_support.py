# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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
