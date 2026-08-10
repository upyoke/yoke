"""Focused tests for schema-convergence failure diagnostics."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yoke_cli.commands import schema_converge as subject


@pytest.fixture
def selected_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subject,
        "_authority_receipt",
        lambda: (
            {"authority_source": "connected_environment", "environment": "local"},
            [],
        ),
    )


def _failing_entrypoint(message: str) -> SimpleNamespace:
    def fail() -> None:
        raise RuntimeError(message)

    return SimpleNamespace(
        ensure_core_schema=fail,
        ensure_permission_catalog=lambda **_kwargs: True,
    )


def test_json_failure_includes_reason_and_preserves_structured_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    selected_authority: None,
) -> None:
    monkeypatch.setattr(
        subject.importlib,
        "import_module",
        lambda _name: _failing_entrypoint("migration 0042 checksum mismatch"),
    )

    assert subject.schema_converge(["--json"]) == 1

    payload = json.loads(capsys.readouterr().err)
    assert payload == {
        "detail": "migration 0042 checksum mismatch",
        "error": "schema_convergence_failed",
        "error_type": "RuntimeError",
        "ok": False,
        "operation": "schema.converge",
    }


def test_human_failure_includes_reason(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    selected_authority: None,
) -> None:
    monkeypatch.setattr(
        subject.importlib,
        "import_module",
        lambda _name: _failing_entrypoint("serving floor is newer than this release"),
    )

    assert subject.schema_converge([]) == 1

    error = capsys.readouterr().err
    assert "(RuntimeError): serving floor is newer than this release" in error
    assert "yoke status --json" in error


@pytest.mark.parametrize(
    "unsafe_detail, secret",
    [
        (
            "could not connect to postgresql://operator:open-sesame@db.example/yoke",
            "postgresql://operator:open-sesame@db.example/yoke",
        ),
        ("migration failed password=open-sesame at revision 42", "open-sesame"),
        ('migration failed dsn="host=db password=open-sesame"', "open-sesame"),
        (
            "could not connect using host=db user=operator password=open-sesame",
            "host=db user=operator password=open-sesame",
        ),
    ],
)
def test_failure_detail_redacts_dsn_and_password_material(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    selected_authority: None,
    unsafe_detail: str,
    secret: str,
) -> None:
    monkeypatch.setattr(
        subject.importlib,
        "import_module",
        lambda _name: _failing_entrypoint(unsafe_detail),
    )

    assert subject.schema_converge(["--json"]) == 1

    payload = json.loads(capsys.readouterr().err)
    assert payload["error_type"] == "RuntimeError"
    assert payload["detail"]
    assert secret not in payload["detail"]
    assert "<redacted" in payload["detail"]


def test_failure_detail_redacts_selected_dsn_even_when_not_url_shaped(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    selected_authority: None,
) -> None:
    dsn = "host=db.example user=operator password=open-sesame dbname=yoke"
    monkeypatch.setenv("YOKE_PG_DSN", dsn)
    monkeypatch.setattr(
        subject.importlib,
        "import_module",
        lambda _name: _failing_entrypoint(f"connection rejected for {dsn}"),
    )

    assert subject.schema_converge(["--json"]) == 1

    detail = json.loads(capsys.readouterr().err)["detail"]
    assert dsn not in detail
    assert "db.example" not in detail
    assert "open-sesame" not in detail
    assert "<redacted>" in detail


def test_human_failure_redacts_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    selected_authority: None,
) -> None:
    secret = "open-sesame"
    monkeypatch.setattr(
        subject.importlib,
        "import_module",
        lambda _name: _failing_entrypoint(
            f"database rejected password={secret} during migration"
        ),
    )

    assert subject.schema_converge([]) == 1

    error = capsys.readouterr().err
    assert secret not in error
    assert "password=<redacted>" in error
