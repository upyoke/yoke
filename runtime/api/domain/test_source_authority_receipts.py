"""Source authority receipt custody, hashing and bounded transfer."""

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

from yoke_core.domain import source_authority_receipts as receipts

FIXTURE = Path(__file__).parents[1] / "fixtures" / "source_freeze_intent_v2.json"


def test_cross_repo_freeze_intent_fixture_has_exact_contract():
    intent = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(intent) == {
        "schema",
        "receipt_id",
        "database",
        "frozen_at",
        "authority_digest",
        "updated_at_watermark",
        "strategy_sha256",
        "archive",
        "zero_writable_app_sessions",
        "project_capabilities",
        "capability_secrets",
    }
    assert set(intent["database"]) == {"name", "oid", "org"}
    # Telemetry figures are deliberately absent: an event count can differ
    # between two receipts of the same authority.
    assert "event_watermark" not in intent
    assert set(intent["archive"]) == {"sha256", "bytes", "catalog_digest"}
    assert intent["schema"] == "yoke.source-freeze/v2"
    receipt_body = {key: value for key, value in intent.items() if key != "receipt_id"}
    assert (
        intent["receipt_id"]
        == hashlib.sha256(
            json.dumps(receipt_body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    for path in (
        ("receipt_id",),
        ("authority_digest",),
        ("strategy_sha256",),
        ("archive", "sha256"),
        ("archive", "catalog_digest"),
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
            self.batches = [[('{"id":1}',), ('{"id":2}',)], []]
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
        receipts,
        "_base_tables",
        lambda _conn: [
            "api_tokens",
            "capability_secrets",
            "deployment_preview_environments",
            "environments",
            "ephemeral_environments",
            "events",
            "items",
            "project_capabilities",
            "sites",
        ],
    )
    monkeypatch.setattr(
        receipts,
        "_table_receipt",
        lambda _conn, table, **_kw: {"count": 1, "digest": table},
    )
    monkeypatch.setattr(receipts, "_strategy_receipts", lambda _conn: [])
    monkeypatch.setattr(
        receipts,
        "project_capabilities_receipt",
        lambda _conn: {"schema": "caps", "types": {}, "sha256": "caps-digest"},
    )
    monkeypatch.setattr(
        receipts,
        "capability_secrets_receipt",
        lambda _conn: {"schema": "secrets", "types": {}, "sha256": "secret-digest"},
    )
    seen = {}

    def sequences(_conn, *, excluded_tables):
        seen["excluded"] = excluded_tables
        return [
            {
                "name": "items_id_seq",
                "owner_table": "items",
                "last_value": 1,
                "is_called": True,
            }
        ]

    monkeypatch.setattr(receipts, "_sequence_receipts", sequences)
    monkeypatch.setattr(
        receipts,
        "fingerprint_portable_postgres_schema",
        lambda _conn: "schema-fingerprint",
    )
    report = receipts.authority_receipt(object(), include_content_digests=True)

    assert report["normalization"]["schema"] == "yoke.portable-authority/v2"
    assert report["normalization"]["project_capability_types"] == (
        "separate-receipt-plane"
    )
    assert report["portable_table_catalog"] == [
        "deployment_preview_environments",
        "environments",
        "ephemeral_environments",
        "items",
        "sites",
    ]
    assert set(report["tables"]) == {
        "deployment_preview_environments",
        "environments",
        "ephemeral_environments",
        "items",
        "sites",
    }
    assert seen["excluded"] == {
        "api_tokens",
        "capability_secrets",
        "events",
        "project_capabilities",
    }
    assert report["project_capabilities"]["sha256"] == "caps-digest"
    assert report["capability_secrets"]["sha256"] == "secret-digest"
    assert re.fullmatch(r"[0-9a-f]{64}", report["receipt_digest"])

    empty_secret_plane = receipts.filter_typed_receipt(
        report["capability_secrets"],
        frozenset(),
    )
    digest_body = {
        key: value for key, value in report.items() if key != "receipt_digest"
    }
    digest_body["capability_secrets"] = empty_secret_plane
    assert (
        report["receipt_digest"]
        == hashlib.sha256(
            json.dumps(digest_body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


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
                    (
                        1,
                        "github",
                        '{"b":2,"a":1}',
                        "2026-07-14T00:00:01.123456Z",
                        "2026-07-14T00:00:00.123456Z",
                    ),
                    (
                        2,
                        "policy",
                        {"enabled": True},
                        None,
                        "2026-07-14T00:00:00.123456Z",
                    ),
                ]
            else:
                rows = [
                    (
                        1,
                        "github",
                        "token",
                        "raw-secret",
                        "literal",
                        "2026-07-14T00:00:00.123456Z",
                    ),
                    (
                        2,
                        "policy",
                        "signing",
                        "other-secret",
                        "literal",
                        "2026-07-14T00:00:00.123456Z",
                    ),
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
