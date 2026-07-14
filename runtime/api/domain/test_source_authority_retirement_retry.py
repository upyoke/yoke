"""Retry proof for a source retirement interrupted before database commit."""

from pathlib import Path

import pytest

from runtime.api.domain.test_source_authority_credential_cutoff import _bundle
from yoke_core.domain import source_authority_credentials as credentials
from yoke_core.domain import source_authority_cutover as cutover
from yoke_core.domain import source_authority_cutover_lifecycle as lifecycle


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
        lifecycle.role_credentials, "role_login_state", lambda *_a: False,
    )

    def state(_conn):
        selected = credentials.load_bound(bundle.path)
        return {
            "retired_at": selected.retired_at,
            "retirement_receipt": selected.retirement_receipt,
        }

    monkeypatch.setattr(lifecycle.connect_fence, "fence_state", state)
    monkeypatch.setattr(lifecycle, "assert_connection_rejected", lambda *_a, **_kw: None)

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
