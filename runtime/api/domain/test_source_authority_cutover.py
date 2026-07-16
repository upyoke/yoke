import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import source_authority_cutover as cutover
from yoke_core.domain import source_authority_cutover_lifecycle as lifecycle
from yoke_core.domain import source_authority_receipts as receipts


FIXTURE = Path(__file__).parents[1] / "fixtures" / "source_freeze_intent_v1.json"


class _Result:
    def __init__(self, row=(0,)):
        self.row = row

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self):
        self.statements = []
        self.closed = False
        self.autocommit = False
        self.commits = 0

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        return _Result((3,))

    def close(self):
        self.closed = True

    def commit(self):
        self.commits += 1


def test_begin_sets_database_boundary_drains_and_proves_stability(
    monkeypatch, tmp_path: Path,
):
    original = _Conn()
    rotated = _Conn()
    connections = iter((original, rotated))
    monkeypatch.setattr(
        cutover, "_admin_connection", lambda _dsn: next(connections),
    )
    staged = {"database": "source", "database_oid": 7, "staged": True}
    proved = {
        "database": "source", "database_oid": 7, "active": True,
        "terminated_other_sessions": 3,
        "provider_superuser_bypass_roles": ["rdsadmin"],
    }
    monkeypatch.setattr(
        cutover.connect_fence, "install_connect_fence",
        lambda *_args, **_kwargs: staged,
    )

    def prove(_conn):
        assert original.commits == 1
        return proved

    monkeypatch.setattr(
        cutover.connect_fence, "drain_and_prove_connect_fence", prove,
    )
    monkeypatch.setattr(
        cutover, "_database_identity",
        lambda _conn: {"database": "source", "database_oid": 7, "org": "yoke"},
    )
    monkeypatch.setattr(
        cutover, "authority_receipt", lambda _conn, **_kw: {
            "receipt_digest": "stable", "tables": {}, "strategy_rows": [],
            "project_capabilities": {"schema": "caps", "types": {}, "sha256": "c"},
            "capability_secrets": {"schema": "secrets", "types": {}, "sha256": "s"},
        },
    )
    bundle = SimpleNamespace(
        path=tmp_path / "cutover.json", database="source", database_oid=7,
        admin_role="3", service_stop_receipt="service-stopped",
        original_dsn="secret-dsn", cutover_dsn="rotated-dsn",
        original_rolcanlogin=True,
    )
    monkeypatch.setattr(
        cutover.source_credentials, "prepare_or_load", lambda *_a, **_kw: bundle,
    )
    monkeypatch.setattr(
        cutover.role_credentials, "role_login_state", lambda *_a: True,
    )
    monkeypatch.setattr(
        cutover.role_credentials, "rotate_role_password", lambda *_a: None,
    )
    monkeypatch.setattr(
        cutover, "_validate_bundle_authority", lambda *_a: {
            "frozen_at": "then", "service_stop_receipt": "service-stopped",
        },
    )
    monkeypatch.setattr(cutover, "_connection_or_none", lambda _dsn: None)
    monkeypatch.setattr(
        cutover, "_prove_original_credential_cutoff",
        lambda *_a, **_kw: {"method": "test-verifier"},
    )

    report = cutover.begin(
        service_stop_receipt="service-stopped",
        credential_file=bundle.path, dsn="secret-dsn",
    )

    assert report["quiesced"] is True
    assert report["terminated_connections"] == 3
    assert report["admin_fence"]["provider_superuser_bypass_roles"] == [
        "rdsadmin"
    ]
    assert report["stable_watermarks"] is True
    assert original.commits == 1
    assert "secret-dsn" not in str(report)
    assert original.closed is True
    assert rotated.closed is True


def test_begin_refuses_existing_boundary(monkeypatch, tmp_path: Path):
    conn = _Conn()
    monkeypatch.setattr(cutover, "_admin_connection", lambda _dsn: conn)
    monkeypatch.setattr(
        cutover, "_database_identity",
        lambda _conn: {"database": "source", "database_oid": 7, "org": "yoke"},
    )
    monkeypatch.setattr(
        cutover.connect_fence, "install_connect_fence",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            cutover.connect_fence.SourceConnectFenceError(
                "source authority is already quiesced"
            )
        ),
    )
    monkeypatch.setattr(
        cutover.role_credentials, "role_login_state", lambda *_a: True,
    )
    monkeypatch.setattr(
        cutover.source_credentials, "prepare_or_load",
        lambda *_a, **_kw: SimpleNamespace(),
    )

    with pytest.raises(cutover.SourceAuthorityCutoverError, match="already quiesced"):
        cutover.begin(
            service_stop_receipt="service-stopped",
            credential_file=tmp_path / "cutover.json", dsn="secret-dsn",
        )


def test_abort_restores_policy_and_original_credential(monkeypatch, tmp_path: Path):
    conn = _Conn()
    proof = _Conn()
    bundle = SimpleNamespace(
        path=tmp_path / "cutover.json", database="source", database_oid=7,
        admin_role="admin", service_stop_receipt="stopped",
        original_dsn="secret-dsn", cutover_dsn="rotated-dsn",
        original_rolcanlogin=True,
    )
    monkeypatch.setattr(lifecycle, "load_bundle", lambda *_a, **_kw: bundle)
    connections = iter((conn, proof))
    monkeypatch.setattr(
        lifecycle, "connection_or_none", lambda _dsn: next(connections),
    )
    monkeypatch.setattr(
        lifecycle.connect_fence, "fence_state",
        lambda _conn: {
            "policy": {}, "frozen_at": "then",
            "service_stop_receipt": "stopped",
        },
    )
    monkeypatch.setattr(
        lifecycle.connect_fence, "restore_connect_fence",
        lambda _conn: {
            "active": False, "database": "source", "database_oid": 7,
            "effective_connect_policy_restored": True,
        },
    )
    monkeypatch.setattr(
        lifecycle, "database_identity",
        lambda _conn: {"database": "source", "database_oid": 7, "org": "yoke"},
    )
    monkeypatch.setattr(
        lifecycle, "authority_receipt", lambda _conn, **_kw: {
            "receipt_digest": "stable", "tables": {}, "strategy_rows": [],
            "project_capabilities": {"schema": "caps", "types": {}, "sha256": "c"},
            "capability_secrets": {"schema": "secrets", "types": {}, "sha256": "s"},
        },
    )
    monkeypatch.setattr(
        lifecycle, "validate_bundle_authority", lambda *_a: {
            "frozen_at": "then", "service_stop_receipt": "stopped",
        },
    )
    monkeypatch.setattr(
        lifecycle.role_credentials, "restore_role_credential", lambda *_a: None,
    )
    deleted = []
    monkeypatch.setattr(
        lifecycle.source_credentials, "delete_bundle", deleted.append,
    )

    report = cutover.abort(credential_file=bundle.path)

    assert report["quiesced"] is False
    assert report["admin_fence"]["effective_connect_policy_restored"] is True
    assert conn.commits == 1
    assert deleted == [bundle]


def test_quiesced_export_emits_one_receipt_carrying_tar_and_refuses_mutable_source(
    monkeypatch, tmp_path: Path,
):
    import tarfile

    conn = _Conn()
    archive = tmp_path / "source.tar"
    from yoke_core.domain import source_authority_export_cutover as export_cutover
    from yoke_core.domain import universe_archive

    monkeypatch.setattr(
        export_cutover, "authority_receipt", lambda _conn, **_kw: {
            "receipt_digest": "stable", "tables": {}, "strategy_rows": [],
            "project_capabilities": {"schema": "caps", "types": {}, "sha256": "c"},
            "capability_secrets": {"schema": "secrets", "types": {}, "sha256": "s"},
        },
    )

    monkeypatch.setattr(cutover, "_admin_connection", lambda _dsn: conn)
    bundle = SimpleNamespace(
        database="source", database_oid=7, admin_role="admin",
        service_stop_receipt="service-stopped", original_dsn="secret-dsn",
        cutover_dsn="rotated-dsn",
    )
    monkeypatch.setattr(cutover, "_load_bundle", lambda *_a, **_kw: bundle)
    monkeypatch.setattr(
        cutover, "_validate_bundle_authority", lambda *_a: {
            "frozen_at": "2026-07-14T00:00:00Z",
            "service_stop_receipt": "service-stopped", "policy": {},
        },
    )
    fence_active = {"active": True, "unauthorized_sessions": []}
    monkeypatch.setattr(
        cutover.connect_fence, "connect_fence_status", lambda _conn: fence_active,
    )
    monkeypatch.setattr(
        cutover.connect_fence, "fence_state",
        lambda _conn: {
            "frozen_at": "2026-07-14T00:00:00Z",
            "service_stop_receipt": "service-stopped", "policy": {},
        },
    )
    monkeypatch.setattr(
        cutover, "authority_receipt", lambda _conn, **_kw: {
            "receipt_digest": "stable", "tables": {}, "strategy_rows": [],
            "project_capabilities": {"schema": "caps", "types": {}, "sha256": "c"},
            "capability_secrets": {"schema": "secrets", "types": {}, "sha256": "s"},
        },
    )

    def dump_universe(_dsn, destination, **_kwargs):
        staged = Path(destination)
        staged.write_bytes(b"PGDMPportable")
        return SimpleNamespace(
            path=staged,
            archive_sha256=export_cutover.file_sha256(staged),
            size_bytes=staged.stat().st_size,
            catalog_tables=("items",), catalog_sequences=("items_id_seq",),
            catalog_digest="catalog", table_entries=2,
        )

    monkeypatch.setattr(
        export_cutover.universe_portability, "dump_universe", dump_universe,
    )
    monkeypatch.setattr(
        cutover, "_database_identity",
        lambda _conn: {"database": "source", "database_oid": 7, "org": "yoke"},
    )
    original_execute = conn.execute

    def execute(statement, params=None):
        if "pg_export_snapshot" in str(statement):
            return _Result(("00000003-0000001B-1",))
        return original_execute(statement, params)

    conn.execute = execute

    report = cutover.export_quiesced(
        out=archive, credential_file=tmp_path / "cutover.json",
    )

    assert report["stable_watermarks"] is True
    assert report["source_authority"]["receipt_digest"] == "stable"
    assert report["snapshot_proof"]["isolation"] == "repeatable-read-read-only"
    assert len(report["sha256"]) == 64
    assert report["freeze_intent"]["schema"] == "yoke.source-freeze/v1"
    assert report["freeze_intent"]["zero_writable_app_sessions"] is True
    assert "capability_secrets" not in report["catalog"]["tables"]
    assert set(report["freeze_intent"]) == {
        "schema", "receipt_id", "database", "frozen_at", "authority_digest",
        "event_watermark", "updated_at_watermark", "strategy_sha256", "archive",
        "zero_writable_app_sessions", "project_capabilities",
        "capability_secrets",
    }
    assert "secret-dsn" not in str(report)

    # One artifact, no sidecars: the receipt travels inside the tar.
    assert report["artifact"] == str(archive)
    assert report["bytes"] == archive.stat().st_size
    assert sorted(entry.name for entry in tmp_path.iterdir()) == [
        archive.name,
    ]
    with tarfile.open(archive, mode="r:") as reader:
        # Receipt first: streaming readers verify intent before the payload.
        assert [member.name for member in reader.getmembers()] == [
            universe_archive.ARCHIVE_MEMBER_RECEIPT,
            universe_archive.ARCHIVE_MEMBER_DUMP,
        ]
    dump, receipt = universe_archive.unpack_universe_archive(
        archive, tmp_path / "unpacked", max_dump_bytes=1 << 20,
    )
    assert dump.read_bytes() == b"PGDMPportable"
    assert receipt["freeze_intent"] == report["freeze_intent"]
    assert universe_archive.verify_receipt_binds_dump(receipt, dump)[
        "sha256"
    ] == report["sha256"]

    monkeypatch.setattr(
        cutover.connect_fence, "connect_fence_status",
        lambda _conn: {"active": False},
    )
    archive.unlink()
    with pytest.raises(cutover.SourceAuthorityCutoverError, match="active quiesce"):
        cutover.export_quiesced(
            out=archive, credential_file=tmp_path / "cutover.json",
        )
    assert not archive.exists()


def test_cross_repo_freeze_intent_fixture_has_exact_contract():
    intent = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(intent) == {
        "schema", "receipt_id", "database", "frozen_at", "authority_digest",
        "event_watermark", "updated_at_watermark", "strategy_sha256", "archive",
        "zero_writable_app_sessions", "project_capabilities",
        "capability_secrets",
    }
    assert set(intent["database"]) == {"name", "oid", "org"}
    assert set(intent["event_watermark"]) == {"count", "max_id", "max_created_at"}
    assert set(intent["archive"]) == {"sha256", "bytes", "catalog_digest"}
    assert intent["schema"] == "yoke.source-freeze/v1"
    receipt_body = {
        key: value
        for key, value in intent.items()
        if key != "receipt_id"
    }
    assert intent["receipt_id"] == hashlib.sha256(
        json.dumps(receipt_body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    for path in (
        ("receipt_id",), ("authority_digest",), ("strategy_sha256",),
        ("archive", "sha256"), ("archive", "catalog_digest"),
        ("project_capabilities", "sha256"),
        ("capability_secrets", "sha256"),
    ):
        value = intent
        for part in path:
            value = value[part]
        assert re.fullmatch(r"[0-9a-f]{64}", value)


def test_full_table_digest_streams_in_bounded_batches():
    class Cursor:
        def __init__(self):
            self.batches = [[("{\"id\":1}",), ("{\"id\":2}",)], []]
            self.fetch_sizes = []
            self.closed = False

        def execute(self, _query):
            return None

        def fetchmany(self, size):
            self.fetch_sizes.append(size)
            return self.batches.pop(0)

        def fetchall(self):
            raise AssertionError("content digest must not fetchall")

        def close(self):
            self.closed = True

    class Transaction:
        def __init__(self):
            self.entered = False
            self.exited = False

        def __enter__(self):
            self.entered = True

        def __exit__(self, *_exc):
            self.exited = True

    cursor = Cursor()
    transaction = Transaction()
    conn = SimpleNamespace(
        autocommit=True,
        cursor=lambda **_kwargs: cursor,
        transaction=lambda: transaction,
    )

    digest = receipts.streaming_table_digest(conn, "events")

    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert cursor.fetch_sizes == [1000, 1000]
    assert cursor.closed is True
    assert transaction.entered is True
    assert transaction.exited is True


def test_authority_streaming_receipts_support_autocommit(test_db):
    test_db.commit()
    test_db.autocommit = True

    digest = receipts.streaming_table_digest(test_db, "actors")
    capabilities = receipts.project_capabilities_receipt(test_db)
    secrets = receipts.capability_secrets_receipt(test_db)

    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert capabilities["schema"] == "yoke.project-capabilities/v1"
    assert secrets["schema"] == "yoke.capability-secrets/v1"


def test_portable_authority_digest_preserves_environment_tables(
    monkeypatch,
):
    monkeypatch.setattr(
        receipts, "_base_tables",
        lambda _conn: [
            "api_tokens", "capability_secrets", "deployment_preview_environments",
            "environments", "ephemeral_environments", "events", "items",
            "project_capabilities", "sites",
        ],
    )
    monkeypatch.setattr(
        receipts, "_table_receipt",
        lambda _conn, table, **_kw: {"count": 1, "digest": table},
    )
    monkeypatch.setattr(receipts, "_strategy_receipts", lambda _conn: [])
    monkeypatch.setattr(
        receipts, "project_capabilities_receipt",
        lambda _conn: {"schema": "caps", "types": {}, "sha256": "caps-digest"},
    )
    monkeypatch.setattr(
        receipts, "capability_secrets_receipt",
        lambda _conn: {"schema": "secrets", "types": {}, "sha256": "secret-digest"},
    )
    seen = {}

    def sequences(_conn, *, excluded_tables):
        seen["excluded"] = excluded_tables
        return [{
            "name": "items_id_seq", "owner_table": "items",
            "last_value": 1, "is_called": True,
        }]

    monkeypatch.setattr(receipts, "_sequence_receipts", sequences)
    monkeypatch.setattr(
        receipts, "fingerprint_portable_postgres_schema",
        lambda _conn: "schema-fingerprint",
    )
    monkeypatch.setattr(receipts, "_event_max_created_at", lambda _conn: "now")

    report = receipts.authority_receipt(object(), include_content_digests=True)

    assert report["normalization"]["schema"] == "yoke.portable-authority/v1"
    assert report["normalization"]["project_capability_types"] == (
        "separate-receipt-plane"
    )
    assert report["portable_table_catalog"] == [
        "deployment_preview_environments", "environments",
        "ephemeral_environments", "events", "items", "sites",
    ]
    assert set(report["tables"]) == {
        "deployment_preview_environments", "environments",
        "ephemeral_environments", "events", "items", "sites",
    }
    assert seen["excluded"] == {
        "api_tokens", "capability_secrets", "project_capabilities",
    }
    assert report["project_capabilities"]["sha256"] == "caps-digest"
    assert report["capability_secrets"]["sha256"] == "secret-digest"
    assert re.fullmatch(r"[0-9a-f]{64}", report["receipt_digest"])

    empty_secret_plane = receipts.filter_typed_receipt(
        report["capability_secrets"], frozenset(),
    )
    digest_body = {
        key: value
        for key, value in report.items()
        if key != "receipt_digest"
    }
    digest_body["capability_secrets"] = empty_secret_plane
    assert report["receipt_digest"] == hashlib.sha256(
        json.dumps(digest_body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_capability_receipts_are_secret_free_and_detect_type_mismatch():
    class Cursor:
        def __init__(self, rows):
            self.rows = rows
            self.fetch_sizes = []
            self.closed = False

        def execute(self, _statement):
            return None

        def fetchmany(self, size):
            self.fetch_sizes.append(size)
            if not self.rows:
                return []
            rows, self.rows = self.rows, []
            return rows

        def fetchall(self):
            raise AssertionError("compact capability receipt must not fetchall")

        def close(self):
            self.closed = True

    class Conn:
        def __init__(self):
            self.cursors = []
            self.transactions = 0

        class Transaction:
            def __init__(self, conn):
                self.conn = conn

            def __enter__(self):
                self.conn.transactions += 1

            def __exit__(self, *_exc):
                return None

        def transaction(self):
            return self.Transaction(self)

        def cursor(self, *, name):
            if name == "source_project_capabilities":
                rows = [
                    (1, "github", '{"b":2,"a":1}', "verified", "created"),
                    (2, "policy", {"enabled": True}, None, "created"),
                ]
            else:
                rows = [
                    (1, "github", "token", "raw-secret", "literal", "created"),
                    (2, "policy", "signing", "other-secret", "literal", "created"),
                ]
            cursor = Cursor(rows)
            self.cursors.append(cursor)
            return cursor

    conn = Conn()
    capabilities = receipts.project_capabilities_receipt(conn)
    secrets = receipts.capability_secrets_receipt(conn)
    selected = receipts.filter_typed_receipt(capabilities, {"github"})
    nonselected = receipts.filter_typed_receipt(capabilities, {"policy"})

    assert set(capabilities["types"]) == {"github", "policy"}
    assert selected["types"]["github"]["projects"].keys() == {"1"}
    assert set(nonselected["types"]) == {"policy"}
    assert selected["sha256"] != nonselected["sha256"]
    assert "raw-secret" not in json.dumps(secrets)
    assert "other-secret" not in json.dumps(secrets)
    assert "token" not in json.dumps(secrets)
    assert all(cursor.fetch_sizes == [256, 256] for cursor in conn.cursors)
    assert all(cursor.closed for cursor in conn.cursors)
    assert conn.transactions == 2

    changed = json.loads(json.dumps(nonselected))
    changed["types"]["policy"]["projects"]["2"] = "0" * 64
    changed = receipts.filter_typed_receipt(changed, {"policy"})
    assert changed["sha256"] != nonselected["sha256"]
