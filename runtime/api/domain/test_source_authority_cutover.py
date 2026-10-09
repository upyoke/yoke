from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import parse_instant, format_instant

from yoke_core.domain import source_authority_cutover as cutover
from yoke_core.domain import source_authority_cutover_lifecycle as lifecycle


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
    monkeypatch,
    tmp_path: Path,
):
    original = _Conn()
    rotated = _Conn()
    connections = iter((original, rotated))
    monkeypatch.setattr(
        cutover,
        "_admin_connection",
        lambda _dsn: next(connections),
    )
    moment = parse_instant("2026-10-09T15:00:00.123456Z")
    monkeypatch.setattr(cutover, "utc_now", lambda: moment)
    staged = {"database": "source", "database_oid": 7, "staged": True}
    proved = {
        "database": "source",
        "database_oid": 7,
        "active": True,
        "terminated_other_sessions": 3,
        "provider_superuser_bypass_roles": ["rdsadmin"],
    }

    def install(_conn, *, frozen_at, service_stop_receipt):
        assert frozen_at == moment
        assert isinstance(frozen_at, type(moment))
        assert service_stop_receipt == "service-stopped"
        return staged

    monkeypatch.setattr(cutover.connect_fence, "install_connect_fence", install)

    def prove(_conn):
        assert original.commits == 1
        return proved

    monkeypatch.setattr(
        cutover.connect_fence,
        "drain_and_prove_connect_fence",
        prove,
    )
    monkeypatch.setattr(
        cutover,
        "_database_identity",
        lambda _conn: {"database": "source", "database_oid": 7, "org": "yoke"},
    )
    monkeypatch.setattr(
        cutover,
        "authority_receipt",
        lambda _conn, **_kw: {
            "receipt_digest": "stable",
            "tables": {},
            "strategy_rows": [],
            "project_capabilities": {"schema": "caps", "types": {}, "sha256": "c"},
            "capability_secrets": {"schema": "secrets", "types": {}, "sha256": "s"},
        },
    )
    bundle = SimpleNamespace(
        path=tmp_path / "cutover.json",
        database="source",
        database_oid=7,
        admin_role="3",
        service_stop_receipt="service-stopped",
        original_dsn="secret-dsn",
        cutover_dsn="rotated-dsn",
        original_rolcanlogin=True,
    )
    monkeypatch.setattr(
        cutover.source_credentials,
        "prepare_or_load",
        lambda *_a, **_kw: bundle,
    )
    monkeypatch.setattr(
        cutover.role_credentials,
        "role_login_state",
        lambda *_a: True,
    )
    monkeypatch.setattr(
        cutover.role_credentials,
        "rotate_role_password",
        lambda *_a: None,
    )
    monkeypatch.setattr(
        cutover,
        "_validate_bundle_authority",
        lambda *_a: {
            "frozen_at": "2026-10-09T15:00:00.123456Z",
            "service_stop_receipt": "service-stopped",
        },
    )
    monkeypatch.setattr(cutover, "_connection_or_none", lambda _dsn: None)
    monkeypatch.setattr(
        cutover,
        "_prove_original_credential_cutoff",
        lambda *_a, **_kw: {"method": "test-verifier"},
    )

    report = cutover.begin(
        service_stop_receipt="service-stopped",
        credential_file=bundle.path,
        dsn="secret-dsn",
    )

    assert report["quiesced"] is True
    assert report["frozen_at"] == format_instant(moment)
    assert report["terminated_connections"] == 3
    assert report["admin_fence"]["provider_superuser_bypass_roles"] == ["rdsadmin"]
    assert report["stable_watermarks"] is True
    assert original.commits == 1
    assert "secret-dsn" not in str(report)
    assert original.closed is True
    assert rotated.closed is True


def test_begin_refuses_existing_boundary(monkeypatch, tmp_path: Path):
    conn = _Conn()
    monkeypatch.setattr(cutover, "_admin_connection", lambda _dsn: conn)
    monkeypatch.setattr(
        cutover,
        "_database_identity",
        lambda _conn: {"database": "source", "database_oid": 7, "org": "yoke"},
    )
    monkeypatch.setattr(
        cutover.connect_fence,
        "install_connect_fence",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            cutover.connect_fence.SourceConnectFenceError(
                "source authority is already quiesced"
            )
        ),
    )
    monkeypatch.setattr(
        cutover.role_credentials,
        "role_login_state",
        lambda *_a: True,
    )
    monkeypatch.setattr(
        cutover.source_credentials,
        "prepare_or_load",
        lambda *_a, **_kw: SimpleNamespace(),
    )

    with pytest.raises(cutover.SourceAuthorityCutoverError, match="already quiesced"):
        cutover.begin(
            service_stop_receipt="service-stopped",
            credential_file=tmp_path / "cutover.json",
            dsn="secret-dsn",
        )


def test_abort_restores_policy_and_original_credential(monkeypatch, tmp_path: Path):
    conn = _Conn()
    proof = _Conn()
    bundle = SimpleNamespace(
        path=tmp_path / "cutover.json",
        database="source",
        database_oid=7,
        admin_role="admin",
        service_stop_receipt="stopped",
        original_dsn="secret-dsn",
        cutover_dsn="rotated-dsn",
        original_rolcanlogin=True,
    )
    monkeypatch.setattr(lifecycle, "load_bundle", lambda *_a, **_kw: bundle)
    connections = iter((conn, proof))
    monkeypatch.setattr(
        lifecycle,
        "connection_or_none",
        lambda _dsn: next(connections),
    )
    monkeypatch.setattr(
        lifecycle.connect_fence,
        "fence_state",
        lambda _conn: {
            "policy": {},
            "frozen_at": "2026-10-09T15:00:00.123456Z",
            "service_stop_receipt": "stopped",
        },
    )
    monkeypatch.setattr(
        lifecycle.connect_fence,
        "restore_connect_fence",
        lambda _conn: {
            "active": False,
            "database": "source",
            "database_oid": 7,
            "effective_connect_policy_restored": True,
        },
    )
    monkeypatch.setattr(
        lifecycle,
        "database_identity",
        lambda _conn: {"database": "source", "database_oid": 7, "org": "yoke"},
    )
    monkeypatch.setattr(
        lifecycle,
        "authority_receipt",
        lambda _conn, **_kw: {
            "receipt_digest": "stable",
            "tables": {},
            "strategy_rows": [],
            "project_capabilities": {"schema": "caps", "types": {}, "sha256": "c"},
            "capability_secrets": {"schema": "secrets", "types": {}, "sha256": "s"},
        },
    )
    monkeypatch.setattr(
        lifecycle,
        "validate_bundle_authority",
        lambda *_a: {
            "frozen_at": "2026-10-09T15:00:00.123456Z",
            "service_stop_receipt": "stopped",
        },
    )
    monkeypatch.setattr(
        lifecycle.role_credentials,
        "restore_role_credential",
        lambda *_a: None,
    )
    deleted = []
    monkeypatch.setattr(
        lifecycle.source_credentials,
        "delete_bundle",
        deleted.append,
    )

    report = cutover.abort(credential_file=bundle.path)

    assert report["quiesced"] is False
    assert report["admin_fence"]["effective_connect_policy_restored"] is True
    assert conn.commits == 1
    assert deleted == [bundle]
