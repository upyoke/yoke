"""Local-destination restore coverage for portable universe archives."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest

from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from runtime.api.fixtures.operating_actor import record_fixture_operating_actor
from yoke_core.domain.actors import seed_human_actor, sole_human_actor_id
from yoke_core.domain.local_universe import pinned_authority
from yoke_core.domain.session_actor_binding import resolve_operating_actor
from yoke_core.domain.yoke_function_dispatch import dispatch

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.file_test_db import booted_universe_database
from yoke_core.domain import local_universe_import
from yoke_core.domain import universe_export
from yoke_core.domain.api_tokens import bootstrap_admin_token, hash_token
from yoke_core.domain.web_sessions import hash_web_session_token, mint_web_session


@contextmanager
def _universe():
    with booted_universe_database() as name:
        dsn = pg_testdb.dsn_for_test_database(name)
        with psycopg.connect(dsn) as conn:
            yield conn, dsn


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
            # The archive's own human is the owner this machine adopts.
            # Renaming it after the local login would rename a real person
            # on the strength of an OS account, which is exactly what the
            # identity model refuses to do.
            assert report["actor_id"] == token.actor_id
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
                    "JOIN actors a ON a.id = aor.actor_id "
                    "JOIN roles r ON r.id = aor.role_id "
                    "WHERE a.kind = 'human' AND r.name = 'admin'"
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


@pytest.mark.parametrize("active_human", [True, False])
def test_import_skips_disabled_human_and_owner_can_list_tokens(
    tmp_path, monkeypatch, active_human
):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    with _universe() as (source, source_dsn):
        placeholder = sole_human_actor_id(source, oldest=True)
        assert placeholder == 1
        source.execute("UPDATE actors SET status = 'disabled' WHERE id = %s", (placeholder,))
        admin = seed_human_actor(source, "Active admin") if active_human else None
        if admin is not None:
            source.execute(
                "INSERT INTO actor_org_roles "
                "(actor_id, org_id, role_id, granted_at, granted_by_actor_id) "
                "SELECT %s, o.id, r.id, now(), %s "
                "FROM organizations o CROSS JOIN roles r WHERE r.name = 'admin'",
                (admin, admin),
            )
        source.commit()
        record_fixture_operating_actor(source, placeholder)
        archive = Path(universe_export.export_universe(dsn=source_dsn, out=tmp_path)["artifact"])
        target_name = pg_testdb.create_test_database()
        target_dsn = pg_testdb.dsn_for_test_database(target_name)
        try:
            if not active_human:
                with pytest.raises(local_universe_import.LocalUniverseImportError) as refused:
                    local_universe_import.import_universe(archive, dsn=target_dsn)
                assert "local_import_no_active_human" in str(refused.value)
                assert "enable a human actor" in str(refused.value)
                assert "export a new archive" in str(refused.value)
                return
            report = local_universe_import.import_universe(archive, dsn=target_dsn)
            assert report["actor_id"] == admin
            assert not report.get("binding_error")
            with psycopg.connect(target_dsn) as target:
                binding = resolve_operating_actor(target, env="local")
                assert binding.actor_id == admin
                assert target.execute(
                    "SELECT status FROM actors WHERE id = %s", (placeholder,)
                ).fetchone() == ("disabled",)
            # profile.get is the registered function behind `yoke tokens list`.
            with pinned_authority(target_dsn):
                response = dispatch(
                    FunctionCallRequest(
                        function="profile.get", version="v1",
                        target=TargetRef(kind="global"),
                        actor=ActorContext(actor_id=str(binding.actor_id), session_id=""),
                        payload={},
                    ),
                    ambient_session_id="",
                )
            assert response.success, response.error
            assert response.result["actor"]["id"] == admin
            assert response.result["tokens"] == []
        finally:
            pg_testdb.drop_test_database(target_name)
