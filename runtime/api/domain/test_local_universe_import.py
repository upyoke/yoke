"""Local-destination restore coverage for portable universe archives."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import psycopg

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import local_universe_import
from yoke_core.domain import universe_export
from yoke_core.domain.api_tokens import bootstrap_admin_token, hash_token
from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn
from yoke_core.domain.web_sessions import hash_web_session_token, mint_web_session


@contextmanager
def _universe():
    name = pg_testdb.create_test_database()
    dsn = pg_testdb.dsn_for_test_database(name)
    try:
        run_init_chain_at_dsn(dsn, emit=lambda _line: None)
        with psycopg.connect(dsn) as conn:
            yield conn, dsn
    finally:
        pg_testdb.drop_test_database(name)


def test_local_import_replaces_data_revokes_remote_auth_and_grants_owner(
    tmp_path: Path,
    monkeypatch,
):
    with _universe() as (source, source_dsn):
        token = bootstrap_admin_token(source)
        session = mint_web_session(source, actor_id=token.actor_id)
        source.execute(
            "INSERT INTO projects "
            "(id, slug, name, public_item_prefix, created_at) "
            "VALUES (98001, 'portable', 'Portable', 'POR', now())"
        )
        source.commit()
        archive = Path(
            universe_export.export_universe(dsn=source_dsn, out=tmp_path)["artifact"]
        )

        target_name = pg_testdb.create_test_database()
        target_dsn = pg_testdb.dsn_for_test_database(target_name)
        try:
            monkeypatch.setattr(
                local_universe_import.getpass,
                "getuser",
                lambda: "machine-owner",
            )
            report = local_universe_import.import_universe(archive, dsn=target_dsn)
            assert report["ok"] is True
            assert report["org"] == "default"
            assert report["actor_label"] == "machine-owner"
            assert report["revoked_token_count"] == 1
            assert report["revoked_web_session_count"] == 1

            with psycopg.connect(target_dsn) as target:
                assert target.execute(
                    "SELECT COUNT(*) FROM projects WHERE slug = 'portable'"
                ).fetchone() == (1,)
                assert target.execute(
                    "SELECT status FROM api_tokens WHERE token_hash = %s",
                    (hash_token(token.raw_token),),
                ).fetchone() == ("revoked",)
                assert target.execute(
                    "SELECT revoked_at IS NOT NULL FROM web_sessions "
                    "WHERE token_hash = %s",
                    (hash_web_session_token(session.raw_token),),
                ).fetchone() == (True,)
                assert target.execute(
                    "SELECT COUNT(*) FROM actor_org_roles aor "
                    "JOIN actor_labels al ON al.actor_id = aor.actor_id "
                    "JOIN roles r ON r.id = aor.role_id "
                    "WHERE al.surface = 'github_label' "
                    "AND al.label = 'machine-owner' AND r.name = 'admin'"
                ).fetchone() == (1,)
                assert target.execute(
                    "SELECT COUNT(*) FROM api_tokens WHERE status = 'active'"
                ).fetchone() == (0,)
        finally:
            pg_testdb.drop_test_database(target_name)


def test_local_import_requires_exactly_one_org(tmp_path: Path, monkeypatch):
    with _universe() as (source, source_dsn):
        source.execute(
            "INSERT INTO organizations (slug, name, created_at) "
            "VALUES ('second', 'Second', now())"
        )
        source.commit()
        archive = Path(
            universe_export.export_universe(dsn=source_dsn, out=tmp_path)["artifact"]
        )
        target_name = pg_testdb.create_test_database()
        target_dsn = pg_testdb.dsn_for_test_database(target_name)
        try:
            monkeypatch.setattr(local_universe_import.getpass, "getuser", lambda: "x")
            try:
                local_universe_import.import_universe(archive, dsn=target_dsn)
            except local_universe_import.LocalUniverseImportError as exc:
                assert "exactly one organization" in str(exc)
            else:
                raise AssertionError("multi-org archive should be refused")
        finally:
            pg_testdb.drop_test_database(target_name)


def test_local_import_authority_refuses_nonlocal_connection(monkeypatch):
    monkeypatch.setattr(
        local_universe_import.yoke_connected_env,
        "load_active",
        lambda: SimpleNamespace(
            environment="self-host",
            backend="https",
            config={"transport": "https"},
        ),
    )
    try:
        local_universe_import.resolve_local_import_dsn()
    except local_universe_import.LocalUniverseImportError as exc:
        assert "not the machine-local universe" in str(exc)
    else:
        raise AssertionError("nonlocal connection should be refused")


def test_local_import_refuses_nonprivate_archive(tmp_path):
    archive = tmp_path / "archive.tar"
    archive.write_bytes(b"not relevant")
    archive.chmod(0o644)
    try:
        local_universe_import.import_universe(
            archive,
            dsn="postgresql://not-reached",
        )
    except local_universe_import.LocalUniverseImportError as exc:
        assert "chmod 600" in str(exc)
    else:
        raise AssertionError("nonprivate archive should be refused")
