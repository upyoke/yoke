"""Owner-only source credential file custody and retirement intent."""

from __future__ import annotations
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading
import pytest
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import source_authority_credentials as credentials


def _bundle(tmp_path: Path) -> credentials.SourceCredentialBundle:
    original = (
        "host=source.example dbname=yoke user=source_admin password=original-secret"
    )
    return credentials.prepare_or_load(
        tmp_path / "cutover.json",
        original_dsn=original,
        database="yoke",
        database_oid=42,
        admin_role="source_admin",
        service_stop_receipt="service-stopped",
        original_rolcanlogin=True,
    )


def test_bundle_is_owner_only_bound_and_idempotent(tmp_path: Path):
    bundle = _bundle(tmp_path)
    repeated = credentials.prepare_or_load(
        bundle.path,
        original_dsn=bundle.original_dsn,
        database="yoke",
        database_oid=42,
        admin_role="source_admin",
        service_stop_receipt="service-stopped",
        original_rolcanlogin=True,
    )

    assert repeated.cutover_dsn == bundle.cutover_dsn
    assert repeated.original_dsn == bundle.original_dsn
    assert bundle.path.stat().st_mode & 0o777 == 0o600
    assert "original-secret" not in repr(bundle)


def test_simultaneous_bundle_creation_loads_one_atomic_winner(
    monkeypatch,
    tmp_path: Path,
):
    path = tmp_path / "cutover.json"
    barrier = threading.Barrier(2)
    publish = credentials.credential_file.write_atomic_owner_only

    def synchronized_publish(selected, payload):
        barrier.wait(timeout=5)
        return publish(selected, payload)

    monkeypatch.setattr(
        credentials.credential_file,
        "write_atomic_owner_only",
        synchronized_publish,
    )

    def prepare():
        return credentials.prepare_or_load(
            path,
            original_dsn=(
                "host=source.example dbname=yoke user=source_admin "
                "password=original-secret"
            ),
            database="yoke",
            database_oid=42,
            admin_role="source_admin",
            service_stop_receipt="service-stopped",
            original_rolcanlogin=True,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        bundles = list(executor.map(lambda _index: prepare(), range(2)))

    assert bundles[0].cutover_dsn == bundles[1].cutover_dsn
    assert credentials.load_bound(path).cutover_dsn == bundles[0].cutover_dsn
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".*.tmp"))


def test_losing_bundle_publisher_fsyncs_winner_directory(
    monkeypatch,
    tmp_path: Path,
):
    path = tmp_path / "cutover.json"
    assert (
        credentials.credential_file.write_atomic_owner_only(
            path,
            {"winner": True},
        )
        is True
    )
    fsyncs = []
    monkeypatch.setattr(
        credentials.credential_file,
        "fsync_directory",
        fsyncs.append,
    )

    assert (
        credentials.credential_file.write_atomic_owner_only(
            path,
            {"winner": False},
        )
        is False
    )
    assert fsyncs == [tmp_path, tmp_path]


def test_bundle_publish_write_error_removes_secret_temporary(
    monkeypatch,
    tmp_path: Path,
):
    write = credentials.credential_file.write_new_owner_only

    def fail_after_write(path, payload):
        write(path, payload)
        raise OSError("simulated credential storage failure")

    monkeypatch.setattr(
        credentials.credential_file,
        "write_new_owner_only",
        fail_after_write,
    )

    with pytest.raises(OSError, match="credential storage failure"):
        credentials.credential_file.write_atomic_owner_only(
            tmp_path / "cutover.json",
            {"secret": "redacted"},
        )
    assert list(tmp_path.iterdir()) == []


def test_retirement_intent_is_fsynced_and_reused_before_database_commit(
    tmp_path: Path,
):
    bundle = _bundle(tmp_path)
    prepared = credentials.prepare_retirement(
        bundle,
        retirement_receipt="retirement-gates-green",
        retired_at="2026-07-14T12:00:00Z",
    )
    repeated = credentials.prepare_retirement(
        prepared,
        retirement_receipt="retirement-gates-green",
        retired_at="2099-01-01T00:00:00Z",
    )

    assert repeated.retired_at == parse_instant("2026-07-14T12:00:00Z")
    assert repeated.retirement_receipt == "retirement-gates-green"
    assert repeated.retirement_phase == "intent"
    with pytest.raises(credentials.SourceCredentialError, match="another"):
        credentials.prepare_retirement(
            repeated,
            retirement_receipt="different-gates",
            retired_at=repeated.retired_at,
        )


def test_bundle_rejects_symlink_and_non_owner_mode(tmp_path: Path):
    bundle = _bundle(tmp_path)
    bundle.path.chmod(0o640)
    with pytest.raises(credentials.SourceCredentialError, match="owner-only"):
        credentials.load_bound(bundle.path)

    bundle.path.chmod(0o600)
    link = tmp_path / "linked.json"
    link.symlink_to(bundle.path)
    with pytest.raises(credentials.SourceCredentialError, match="owner-only"):
        credentials.load_bound(link)
