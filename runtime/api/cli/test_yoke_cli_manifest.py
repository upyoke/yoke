"""Tests for the CLI command/help manifest (build, cache, drift)."""

from __future__ import annotations

import json
import os
import time

import pytest

from yoke_cli import manifest as manifest_mod
from yoke_cli.manifest import (
    active_env_manifest,
    build_manifest,
    fetch_env_manifest,
    manifest_knows,
    server_only_subcommands,
)
from yoke_cli.commands.registry import (
    SUBCOMMAND_ALIAS_REGISTRY,
    SUBCOMMAND_REGISTRY,
)
from yoke_cli.transport.https import HttpsConnection


class TestBuildManifest:
    def test_covers_every_registry_row_with_usage(self) -> None:
        manifest = build_manifest()

        assert manifest["manifest_version"] == manifest_mod.MANIFEST_VERSION
        tokens = {tuple(row["tokens"]) for row in manifest["subcommands"]}
        assert tokens == set(SUBCOMMAND_REGISTRY)
        assert all(row["usage"] for row in manifest["subcommands"])
        by_tokens = {
            tuple(row["tokens"]): row
            for row in [*manifest["subcommands"], *manifest["aliases"]]
        }
        assert by_tokens[("agents", "render")]["help_label"] == (
            "source-dev/admin"
        )
        assert "help_label" not in by_tokens[("status",)]
        alias_tokens = {tuple(row["tokens"]) for row in manifest["aliases"]}
        assert alias_tokens == set(SUBCOMMAND_ALIAS_REGISTRY)

    def test_manifest_knows_resolves_token_prefix(self) -> None:
        manifest = build_manifest()

        row = manifest_knows(manifest, ["env", "use", "stage"])
        assert row is not None
        assert row["function_id"] == "env.use.run"
        assert manifest_knows(manifest, ["zz", "top"]) is None

    def test_server_only_diff(self) -> None:
        manifest = build_manifest()
        assert server_only_subcommands(manifest) == []

        manifest["subcommands"].append({
            "tokens": ["zz", "top"], "function_id": "zz.top.run",
            "usage": "yoke zz top",
        })
        extra = server_only_subcommands(manifest)
        assert [row["function_id"] for row in extra] == ["zz.top.run"]


@pytest.fixture()
def https_env(monkeypatch, tmp_path):
    cache_root = tmp_path / "cache"
    monkeypatch.setattr(
        "yoke_cli.config.machine_config.cache_dir",
        lambda path=None: cache_root,
    )
    monkeypatch.setattr(
        "yoke_cli.config.machine_config.active_env",
        lambda path=None, explicit_env=None: "stage",
    )
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda path=None: HttpsConnection(
            api_url="https://api.example", token="tok",
        ),
    )
    return cache_root / manifest_mod.CACHE_SUBDIR / "stage.json"


class TestActiveEnvManifest:
    def test_local_transport_returns_none(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "yoke_cli.transport.https.resolve_https_connection",
            lambda path=None: None,
        )
        assert active_env_manifest() is None

    def test_fresh_cache_skips_fetch(self, monkeypatch, https_env) -> None:
        https_env.parent.mkdir(parents=True)
        https_env.write_text(json.dumps({
            "manifest_version": manifest_mod.MANIFEST_VERSION,
            "subcommands": [],
            "aliases": [],
        }))

        def _boom(connection):
            raise AssertionError("fetch must not run on fresh cache")

        monkeypatch.setattr(manifest_mod, "_fetch", _boom)
        assert active_env_manifest() == {
            "manifest_version": manifest_mod.MANIFEST_VERSION,
            "subcommands": [], "aliases": [],
        }

    def test_stale_cache_refetches_and_rewrites(
        self, monkeypatch, https_env,
    ) -> None:
        https_env.parent.mkdir(parents=True)
        https_env.write_text(json.dumps({"manifest_version": 0}))
        old = time.time() - manifest_mod.CACHE_TTL_S - 10
        os.utime(https_env, (old, old))
        fresh = {
            "manifest_version": manifest_mod.MANIFEST_VERSION,
            "subcommands": [],
            "aliases": [],
        }
        monkeypatch.setattr(manifest_mod, "_fetch", lambda connection: fresh)

        assert active_env_manifest() == fresh
        assert json.loads(https_env.read_text()) == fresh

    def test_fetch_failure_falls_back_to_stale_cache(
        self, monkeypatch, https_env,
    ) -> None:
        https_env.parent.mkdir(parents=True)
        stale = {
            "manifest_version": manifest_mod.MANIFEST_VERSION,
            "subcommands": [],
            "aliases": [],
        }
        https_env.write_text(json.dumps(stale))
        old = time.time() - manifest_mod.CACHE_TTL_S - 10
        os.utime(https_env, (old, old))
        monkeypatch.setattr(manifest_mod, "_fetch", lambda connection: None)

        assert active_env_manifest() == stale

    def test_no_cache_no_fetch_returns_none(
        self, monkeypatch, https_env,
    ) -> None:
        monkeypatch.setattr(manifest_mod, "_fetch", lambda connection: None)

        assert active_env_manifest() is None

    def test_old_manifest_version_is_refetched_even_when_cache_is_fresh(
        self, monkeypatch, https_env,
    ) -> None:
        https_env.parent.mkdir(parents=True)
        https_env.write_text(json.dumps({
            "manifest_version": manifest_mod.MANIFEST_VERSION - 1,
            "subcommands": [{
                "tokens": ["templates", "list"],
                "function_id": "templates.list.run",
            }],
            "aliases": [],
        }))
        fresh = {
            "manifest_version": manifest_mod.MANIFEST_VERSION,
            "subcommands": [],
            "aliases": [],
        }
        monkeypatch.setattr(manifest_mod, "_fetch", lambda connection: fresh)

        assert active_env_manifest() == fresh
        assert json.loads(https_env.read_text()) == fresh

    def test_fetch_env_manifest_uses_explicit_env(self, monkeypatch) -> None:
        seen = {}

        def _resolve(path=None, *, explicit_env=None):
            seen["explicit_env"] = explicit_env
            return HttpsConnection(
                api_url="https://api.example", token="tok",
            )

        monkeypatch.setattr(
            "yoke_cli.transport.https.resolve_https_connection",
            _resolve,
        )
        monkeypatch.setattr(
            manifest_mod,
            "_fetch",
            lambda connection: {
                "manifest_version": manifest_mod.MANIFEST_VERSION,
                "subcommands": [],
            },
        )

        assert fetch_env_manifest("prod") == {
            "manifest_version": manifest_mod.MANIFEST_VERSION,
            "subcommands": [],
        }
        assert seen["explicit_env"] == "prod"


def test_manifest_request_accepts_versioned_api_url() -> None:
    request = manifest_mod._manifest_request(
        HttpsConnection(api_url="https://api.example/v1", token="tok")
    )

    assert request.full_url == "https://api.example/v1/cli/manifest"


def test_diagnose_fetch_failure_reports_http_401(monkeypatch) -> None:
    import io
    import urllib.error
    from types import SimpleNamespace

    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda explicit_env=None: SimpleNamespace(
            api_url="https://api.example.test", token="bad",
        ),
    )

    def _raise(request, timeout=None):
        raise urllib.error.HTTPError(
            "https://api.example.test/v1/cli/manifest", 401, "Unauthorized", None,
            io.BytesIO(
                b'{"success":false,"error":'
                b'{"code":"authentication_malformed",'
                b'"message":"API token has invalid syntax"}}'
            ),
        )

    monkeypatch.setattr(manifest_mod.urllib.request, "urlopen", _raise)

    reason = manifest_mod.diagnose_env_manifest_fetch("prod")

    assert "HTTP 401" in reason
    assert "authentication_malformed" in reason
    assert "API token has invalid syntax" in reason
