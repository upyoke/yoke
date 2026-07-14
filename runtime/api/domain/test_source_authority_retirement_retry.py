"""Retry proof for a source retirement interrupted before database commit."""

from pathlib import Path

import psycopg
import pytest

from runtime.api.domain.test_source_authority_credential_cutoff import _bundle
from yoke_core.domain import source_authority_credentials as credentials
from yoke_core.domain import source_authority_cutover as cutover
from yoke_core.domain import source_authority_cutover_lifecycle as lifecycle


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


def test_retire_reuses_precommit_marker_after_failure_before_commit(
    monkeypatch, tmp_path: Path,
):
    bundle = _bundle(tmp_path)

    class Connection:
        def __init__(self):
            self.commits = 0

        def commit(self):
            self.commits += 1

        def close(self):
            pass

    first = Connection()
    second = Connection()
    probes = iter((first, second))
    monkeypatch.setattr(lifecycle, "connection_or_none", lambda _dsn: next(probes))
    monkeypatch.setattr(
        lifecycle, "retirement_connection_or_none",
        lambda *_a, **_kw: next(probes),
    )
    monkeypatch.setattr(lifecycle, "validate_bundle_authority", lambda *_a: {})
    monkeypatch.setattr(
        lifecycle, "database_identity",
        lambda _conn: {"database": "yoke", "database_oid": 42, "org": "yoke"},
    )
    monkeypatch.setattr(
        lifecycle, "authority_receipt", lambda _conn: {"receipt_digest": "a" * 64},
    )
    retirement_attempts = []

    def mark(_conn, **kwargs):
        retirement_attempts.append(kwargs)
        if len(retirement_attempts) == 1:
            raise RuntimeError("simulated failure before retirement commit")

    monkeypatch.setattr(lifecycle, "mark_source_retired", mark)
    monkeypatch.setattr(
        lifecycle.role_credentials, "retire_role_credential", lambda *_a: None,
    )
    monkeypatch.setattr(
        lifecycle.role_credentials, "prove_role_retired", lambda *_a: None,
    )

    def state(_conn):
        selected = credentials.load_bound(bundle.path)
        return {
            "retired_at": selected.retired_at,
            "retirement_receipt": selected.retirement_receipt,
        }

    monkeypatch.setattr(lifecycle.connect_fence, "fence_state", state)

    with pytest.raises(RuntimeError, match="before retirement commit"):
        cutover.retire(
            credential_file=bundle.path,
            retirement_receipt="retirement-gates-green",
        )
    prepared = credentials.load_bound(bundle.path)
    assert prepared.retirement_receipt == "retirement-gates-green"
    assert prepared.retired_at
    assert first.commits == 0

    report = cutover.retire(
        credential_file=bundle.path,
        retirement_receipt="retirement-gates-green",
    )

    assert report["retired_at"] == prepared.retired_at
    assert retirement_attempts[0] == retirement_attempts[1]
    assert second.commits == 1
    assert not bundle.path.exists()


def test_retire_recovers_after_commit_before_bundle_delete(
    monkeypatch, tmp_path: Path,
):
    bundle = _bundle(tmp_path)

    class Connection:
        def __init__(self):
            self.commits = 0

        def commit(self):
            self.commits += 1

        def close(self):
            pass

    conn = Connection()
    monkeypatch.setattr(lifecycle, "connection_or_none", lambda _dsn: conn)
    monkeypatch.setattr(
        lifecycle, "retirement_connection_or_none", lambda *_a, **_kw: None,
    )
    monkeypatch.setattr(lifecycle, "validate_bundle_authority", lambda *_a: {})
    monkeypatch.setattr(
        lifecycle, "database_identity",
        lambda _conn: {"database": "yoke", "database_oid": 42, "org": "yoke"},
    )
    monkeypatch.setattr(
        lifecycle, "authority_receipt", lambda _conn: {"receipt_digest": "a" * 64},
    )
    monkeypatch.setattr(lifecycle, "mark_source_retired", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        lifecycle.role_credentials, "retire_role_credential", lambda *_a: None,
    )
    monkeypatch.setattr(
        lifecycle.role_credentials, "prove_role_retired", lambda *_a: None,
    )

    def state(_conn):
        selected = credentials.load_bound(bundle.path)
        return {
            "retired_at": selected.retired_at,
            "retirement_receipt": selected.retirement_receipt,
        }

    monkeypatch.setattr(lifecycle.connect_fence, "fence_state", state)
    delete = credentials.delete_bundle
    delete_calls = 0

    def crash_once(selected):
        nonlocal delete_calls
        delete_calls += 1
        if delete_calls == 1:
            raise OSError("simulated crash before local cleanup")
        delete(selected)

    monkeypatch.setattr(lifecycle.source_credentials, "delete_bundle", crash_once)

    with pytest.raises(OSError, match="simulated crash"):
        cutover.retire(
            credential_file=bundle.path,
            retirement_receipt="retirement-gates-green",
        )
    assert conn.commits == 1
    assert bundle.path.exists()

    report = cutover.retire(
        credential_file=bundle.path,
        retirement_receipt="retirement-gates-green",
    )

    assert report["recovered_after_commit"] is True
    assert report["retired_at"]
    assert not bundle.path.exists()


def test_both_rejected_before_validated_retirement_is_indeterminate(
    monkeypatch, tmp_path: Path,
):
    bundle = _bundle(tmp_path)
    monkeypatch.setattr(lifecycle, "connection_or_none", lambda _dsn: None)
    monkeypatch.setattr(
        lifecycle, "retirement_connection_or_none", lambda *_a, **_kw: None,
    )

    with pytest.raises(
        cutover.SourceAuthorityCutoverError,
        match="before a validated retirement transaction",
    ):
        cutover.retire(
            credential_file=bundle.path,
            retirement_receipt="retirement-gates-green",
        )

    prepared = credentials.load_bound(bundle.path)
    assert prepared.retirement_phase == "intent"
    assert prepared.retirement_receipt == "retirement-gates-green"


def test_abort_recovers_after_commit_with_inconclusive_cutover_probe(
    monkeypatch, tmp_path: Path,
):
    bundle = _bundle(tmp_path)

    class Restored:
        def execute(self, _statement):
            return _Result((bundle.admin_role,))

        def close(self):
            pass

    restored = Restored()

    def connect(dsn):
        if dsn == bundle.cutover_dsn:
            raise psycopg.OperationalError(
                'FATAL: password authentication failed for user "source_admin"'
            )
        return restored

    monkeypatch.setattr(lifecycle, "connection_or_none", connect)
    monkeypatch.setattr(
        lifecycle, "database_identity",
        lambda _conn: {"database": "yoke", "database_oid": 42, "org": "yoke"},
    )
    monkeypatch.setattr(lifecycle.connect_fence, "fence_state", lambda _conn: None)

    report = cutover.abort(credential_file=bundle.path)

    assert report["recovered"] is True
    assert report["cutover_connection_rejection"] == "not-used-as-evidence"
    assert not bundle.path.exists()


def test_abort_does_not_hide_original_authority_network_failure(
    monkeypatch, tmp_path: Path,
):
    bundle = _bundle(tmp_path)

    def connect(dsn):
        if dsn == bundle.cutover_dsn:
            raise psycopg.OperationalError("text-only authentication failure")
        raise psycopg.OperationalError("TLS negotiation failed")

    monkeypatch.setattr(lifecycle, "connection_or_none", connect)

    with pytest.raises(
        cutover.SourceAuthorityCutoverError,
        match="database operation failed",
    ):
        cutover.abort(credential_file=bundle.path)
