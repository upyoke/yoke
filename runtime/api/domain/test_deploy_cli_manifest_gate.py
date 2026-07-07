"""Tests for Yoke core post-deploy CLI manifest parity."""

from __future__ import annotations

from yoke_core.domain import deploy_cli_manifest_gate as gate


def _manifest(*rows):
    return {"manifest_version": 1, "subcommands": list(rows), "aliases": []}


def _row(function_id: str, *tokens: str) -> dict:
    return {
        "function_id": function_id,
        "tokens": list(tokens),
        "usage": "yoke " + " ".join(tokens),
    }


def test_compare_manifests_passes_when_remote_matches_local() -> None:
    local = _manifest(_row("strategy.doc.create", "strategy", "doc", "create"))

    result = gate._compare_manifests("prod", local, local)

    assert result.ok is True
    assert result.checked is True


def test_compare_manifests_fails_when_remote_missing_function() -> None:
    local = _manifest(_row("strategy.doc.create", "strategy", "doc", "create"))
    remote = _manifest()

    result = gate._compare_manifests("prod", local, remote)

    assert result.ok is False
    assert "strategy.doc.create" in result.message
    assert "Deploy/update the Yoke API" in result.message


def test_compare_manifests_fails_when_tokens_drift() -> None:
    local = _manifest(_row("strategy.doc.create", "strategy", "doc", "create"))
    remote = _manifest(_row("strategy.doc.create", "strategy", "create"))

    result = gate._compare_manifests("prod", local, remote)

    assert result.ok is False
    assert "token mismatch" in result.message


def test_verify_skips_non_https_env(monkeypatch) -> None:
    from yoke_core.domain import machine_config

    monkeypatch.setattr(
        machine_config,
        "active_connection",
        lambda explicit_env=None: {
            "env": explicit_env,
            "transport": "local-postgres",
        },
    )

    result = gate.verify_deployed_cli_manifest("prod-db-admin")

    assert result.ok is True
    assert result.checked is False


def test_verify_surfaces_fetch_failure_reason(monkeypatch) -> None:
    # A failed manifest fetch must name *why* (the 401/auth reason), not just
    # "could not fetch" — the regression that cost a long prod debug session.
    import yoke_cli.manifest as manifest_mod

    monkeypatch.setattr(gate, "_env_is_https", lambda env_name: True)
    monkeypatch.setattr(manifest_mod, "fetch_env_manifest", lambda env_name: None)
    monkeypatch.setattr(
        manifest_mod,
        "diagnose_env_manifest_fetch",
        lambda env_name: 'HTTP 401 authentication_malformed ("API token has invalid syntax")',
    )

    result = gate.verify_deployed_cli_manifest("prod")

    assert result.ok is False
    assert result.checked is True
    assert "could not fetch" in result.message
    assert "HTTP 401 authentication_malformed" in result.message
    assert "API token has invalid syntax" in result.message
