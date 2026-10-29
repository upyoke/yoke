"""Tenant import remaps stored addresses and the byte-copy contract together."""

import pytest

from runtime.api.domain._universe_import_test_helpers import _canonical_universe
from yoke_core.domain.qa_artifact_handle import (
    parse_handle,
    s3_handle,
    serialize_handle,
)
from yoke_core.domain.universe_import_artifacts import (
    UniverseImportArtifactError,
    rewrite_imported_artifacts,
)


def _rewrite(conn):
    return rewrite_imported_artifacts(
        conn,
        source_bucket="source",
        source_tenant_id="old",
        destination_bucket="destination",
        destination_tenant_id="new",
    )


def _handles(conn, keys):
    conn.execute("CREATE TEMP TABLE qa_artifacts (id INTEGER, artifact_handle TEXT)")
    for index, key in enumerate(keys):
        conn.execute(
            "INSERT INTO qa_artifacts VALUES (%s, %s)",
            (index, serialize_handle(s3_handle("source", key, "image/png"))),
        )
    conn.commit()


def test_rewrites_both_kinds_preserving_suffix_and_metadata():
    with _canonical_universe() as (conn, _dsn):
        suffixes = [
            "qa-artifacts/project/subject/1/proof.png",
            "shared-files/project/a.png",
        ]
        _handles(conn, ["tenants/old/" + suffix for suffix in suffixes])
        mapping = _rewrite(conn)
        assert mapping == {
            "s3://source/tenants/old/qa-artifacts/": "s3://destination/tenants/new/qa-artifacts/",
            "s3://source/tenants/old/shared-files/": "s3://destination/tenants/new/shared-files/",
        }
        handles = [
            parse_handle(row[0])
            for row in conn.execute(
                "SELECT artifact_handle FROM qa_artifacts ORDER BY id"
            ).fetchall()
        ]
        assert handles == [
            s3_handle("destination", "tenants/new/" + suffix, "image/png")
            for suffix in suffixes
        ]
        conn.rollback()
        assert all(
            parse_handle(row[0])["bucket"] == "source"
            for row in conn.execute(
                "SELECT artifact_handle FROM qa_artifacts"
            ).fetchall()
        )


def test_shared_prefix_is_returned_without_any_evidence_rows():
    with _canonical_universe() as (conn, _dsn):
        _handles(conn, [])
        assert _rewrite(conn)["s3://source/tenants/old/shared-files/"] == (
            "s3://destination/tenants/new/shared-files/"
        )


def test_wrong_namespace_refuses_and_rolls_back_only_helper_writes():
    with _canonical_universe() as (conn, _dsn):
        _handles(conn, ["tenants/old/qa-artifacts/a", "tenants/other/shared-files/b"])
        conn.execute("INSERT INTO qa_artifacts VALUES (5, NULL)")
        with pytest.raises(UniverseImportArtifactError, match="rehome"):
            _rewrite(conn)
        assert conn.execute("SELECT COUNT(*) FROM qa_artifacts").fetchone() == (3,)
        raw = conn.execute(
            "SELECT artifact_handle FROM qa_artifacts WHERE id=0"
        ).fetchone()[0]
        assert parse_handle(raw)["bucket"] == "source"
