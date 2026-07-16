"""Self-host universe import coverage: one-file archive in, one credential out."""

from __future__ import annotations

import io
import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import json_helper
from yoke_core.domain import universe_archive
from yoke_core.domain import universe_export
from yoke_core.domain import universe_import_credentials as credentials
from yoke_core.domain import universe_import_cli as importer
from yoke_core.domain import universe_portability
from yoke_core.domain.api_tokens import (
    bootstrap_admin_token,
    hash_token,
    mint_token,
)
from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn
from yoke_core.domain.web_sessions import (
    WebSessionRevoked,
    mint_web_session,
    verify_web_session,
)


@contextmanager
def _canonical_universe():
    name = pg_testdb.create_test_database()
    dsn = pg_testdb.dsn_for_test_database(name)
    try:
        run_init_chain_at_dsn(dsn, emit=lambda _line: None)
        with psycopg.connect(dsn) as conn:
            yield conn, dsn
    finally:
        pg_testdb.drop_test_database(name)


def _exported_archive(source_dsn: str, tmp_path: Path) -> Path:
    return Path(
        universe_export.export_universe(dsn=source_dsn, out=tmp_path)["artifact"]
    )


def test_import_stream_rotates_every_credential_and_returns_one_admin(tmp_path):
    with _canonical_universe() as (source, source_dsn):
        first = bootstrap_admin_token(source)
        second = mint_token(source, actor_id=first.actor_id, name="doorman:portable")
        web_session = mint_web_session(source, actor_id=first.actor_id)
        archive = _exported_archive(source_dsn, tmp_path)

        target_name = pg_testdb.create_test_database()
        target_dsn = pg_testdb.dsn_for_test_database(target_name)
        try:
            with archive.open("rb") as stream:
                result = importer.import_from_stream(stream, dsn=target_dsn)
            assert result["ok"] is True
            assert result["org"] == "default"
            assert result["revoked_token_count"] == 2
            assert result["revoked_web_session_count"] == 1
            # Checksum verification is derived from the enclosed receipt.
            assert len(str(result["archive"]["sha256"])) == 64
            raw_token = str(result["raw_token"])
            assert raw_token.startswith("yoke_v1_")

            with psycopg.connect(target_dsn) as target:
                rows = target.execute(
                    "SELECT token_hash, status FROM api_tokens ORDER BY id"
                ).fetchall()
                by_hash = {str(row[0]): str(row[1]) for row in rows}
                assert by_hash[hash_token(first.raw_token)] == "revoked"
                assert by_hash[hash_token(second.raw_token)] == "revoked"
                assert by_hash[hash_token(raw_token)] == "active"
                assert sum(status == "active" for status in by_hash.values()) == 1
                assert raw_token not in {str(row[0]) for row in rows}
                assert target.execute(
                    "SELECT COUNT(*) FROM actor_org_roles aor "
                    "JOIN roles r ON r.id = aor.role_id "
                    "WHERE aor.actor_id = %s AND r.name = 'admin'",
                    (int(result["actor_id"]),),
                ).fetchone() == (1,)
                assert (
                    target.execute(
                        "SELECT COUNT(*) FROM api_token_audit "
                        "WHERE event_type = 'revoked' AND outcome = 'success'"
                    ).fetchone()[0]
                    >= 2
                )
                with pytest.raises(WebSessionRevoked):
                    verify_web_session(target, web_session.raw_token)
        finally:
            pg_testdb.drop_test_database(target_name)


def test_import_replaces_whatever_universe_the_destination_holds(tmp_path):
    """Empty and lived-in destinations take one identical restore path."""
    with _canonical_universe() as (source, source_dsn):
        bootstrap_admin_token(source)
        source.execute(
            "INSERT INTO projects "
            "(id, slug, name, public_item_prefix, created_at) "
            "VALUES (92001, 'incoming', 'Incoming', 'INC', now())"
        )
        source.commit()
        archive = _exported_archive(source_dsn, tmp_path)

        with _canonical_universe() as (target, target_dsn):
            bootstrap_admin_token(target)
            target.execute(
                "INSERT INTO projects "
                "(id, slug, name, public_item_prefix, created_at) "
                "VALUES (92002, 'previous', 'Previous', 'PRV', now())"
            )
            target.commit()
            target.close()

            with archive.open("rb") as stream:
                result = importer.import_from_stream(stream, dsn=target_dsn)
            assert result["ok"] is True

            with psycopg.connect(target_dsn) as restored:
                slugs = {
                    str(row[0])
                    for row in restored.execute(
                        "SELECT slug FROM projects"
                    ).fetchall()
                }
                assert "incoming" in slugs
                assert "previous" not in slugs


def test_import_refuses_mismatched_receipt_before_touching_destination(tmp_path):
    with _canonical_universe() as (source, source_dsn):
        bootstrap_admin_token(source)
        artifact = _exported_archive(source_dsn, tmp_path)
    with universe_archive.unpacked_universe_archive(
        artifact,
        max_dump_bytes=universe_portability.DEFAULT_MAX_ARCHIVE_BYTES,
    ) as (dump, receipt):
        receipt["freeze_intent"]["archive"]["sha256"] = "0" * 64
        forged = tmp_path / "forged.tar"
        universe_archive.pack_universe_archive(dump, receipt, forged)

    target_name = pg_testdb.create_test_database()
    target_dsn = pg_testdb.dsn_for_test_database(target_name)
    try:
        with forged.open("rb") as stream:
            with pytest.raises(
                universe_archive.UniverseArchiveError, match="does not match"
            ):
                importer.import_from_stream(stream, dsn=target_dsn)
        with psycopg.connect(target_dsn) as target:
            assert target.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = current_schema()"
            ).fetchone() == (0,)
    finally:
        pg_testdb.drop_test_database(target_name)


def test_credential_handoff_rolls_back_as_one_transaction():
    with _canonical_universe() as (conn, _dsn):
        original = bootstrap_admin_token(conn)
        replacement = None
        with pytest.raises(RuntimeError, match="force rollback"):
            with conn.transaction():
                replacement = credentials.replace_imported_credentials(conn)
                raise RuntimeError("force rollback")
        assert replacement is not None
        assert conn.execute(
            "SELECT status FROM api_tokens WHERE token_hash = %s",
            (hash_token(original.raw_token),),
        ).fetchone() == ("active",)
        assert (
            conn.execute(
                "SELECT 1 FROM api_tokens WHERE token_hash = %s",
                (hash_token(replacement.raw_token),),
            ).fetchone()
            is None
        )


def test_staged_archive_is_private_and_removed_after_size_refusal(
    tmp_path, monkeypatch
):
    staged = tmp_path / "staged.tar"

    def make_stage(*_args, **_kwargs):
        descriptor = os.open(staged, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        return descriptor, str(staged)

    monkeypatch.setattr(importer.tempfile, "mkstemp", make_stage)
    with pytest.raises(universe_portability.ArchiveTooLargeError):
        importer._stage_archive(io.BytesIO(b"12345"), max_bytes=4)
    assert not staged.exists()


def test_import_finalizer_requires_exactly_one_organization():
    with _canonical_universe() as (conn, _dsn):
        conn.execute(
            "INSERT INTO organizations (slug, name, created_at) "
            "VALUES ('second', 'Second', now())"
        )
        conn.commit()
        with pytest.raises(
            credentials.UniverseImportCredentialError, match="exactly one"
        ):
            credentials.replace_imported_credentials(conn)


def test_recovery_revokes_every_prior_import_recovery_token():
    with _canonical_universe() as (conn, dsn):
        original = bootstrap_admin_token(conn)
        imported = credentials.replace_imported_credentials(conn)
        conn.commit()
        recovered = importer.recover_credential(dsn=dsn)
        recovered_again = importer.recover_credential(dsn=dsn)

        rows = conn.execute(
            "SELECT token_hash, status FROM api_tokens ORDER BY id"
        ).fetchall()
        by_hash = {str(row[0]): str(row[1]) for row in rows}
        assert by_hash[hash_token(original.raw_token)] == "revoked"
        assert by_hash[hash_token(imported.raw_token)] == "revoked"
        assert by_hash[hash_token(str(recovered["raw_token"]))] == "revoked"
        assert by_hash[hash_token(str(recovered_again["raw_token"]))] == "active"
        assert recovered["revoked_token_count"] == 1
        assert recovered_again["revoked_token_count"] == 1


@pytest.mark.parametrize("slug", ("unsafe\nsummary", "a" * 129))
def test_credential_handoff_rejects_unsafe_org_slug_before_rotation(slug):
    with _canonical_universe() as (conn, _dsn):
        original = bootstrap_admin_token(conn)
        conn.execute("UPDATE organizations SET slug = %s", (slug,))
        conn.commit()
        with pytest.raises(
            credentials.UniverseImportCredentialError,
            match="bounded safe identifier",
        ):
            credentials.replace_imported_credentials(conn)
        conn.rollback()
        assert conn.execute(
            "SELECT status FROM api_tokens WHERE token_hash = %s",
            (hash_token(original.raw_token),),
        ).fetchone() == ("active",)


def test_archive_with_control_character_org_slug_rolls_back_before_output(tmp_path):
    with _canonical_universe() as (source, source_dsn):
        bootstrap_admin_token(source)
        source.execute(
            "UPDATE organizations SET slug = %s",
            ("unsafe\ncredential-summary",),
        )
        source.commit()
        archive = _exported_archive(source_dsn, tmp_path)

        target_name = pg_testdb.create_test_database()
        target_dsn = pg_testdb.dsn_for_test_database(target_name)
        try:
            with archive.open("rb") as stream:
                with pytest.raises(
                    credentials.UniverseImportCredentialError,
                    match="bounded safe identifier",
                ):
                    importer.import_from_stream(stream, dsn=target_dsn)
            with psycopg.connect(target_dsn) as target:
                assert target.execute(
                    "SELECT COUNT(*) FROM organizations"
                ).fetchone() == (0,)
                assert target.execute("SELECT COUNT(*) FROM api_tokens").fetchone() == (
                    0,
                )
        finally:
            pg_testdb.drop_test_database(target_name)


def test_internal_cli_keeps_progress_off_credential_stdout(monkeypatch, capsys):
    def fake_import(_stream):
        print("trusted schema progress")
        return {"ok": True, "raw_token": "yoke_v1_OnlyJsonOnStdout"}

    monkeypatch.setattr(importer, "import_from_stream", fake_import)
    assert importer.main(["--stdin"]) == 0
    output = capsys.readouterr()
    assert json_helper.loads_text(output.out)["raw_token"] == (
        "yoke_v1_OnlyJsonOnStdout"
    )
    assert "trusted schema progress" not in output.out
    assert "trusted schema progress" in output.err
