"""Server startup supplies one declared trust boundary to Uvicorn."""

from contextlib import nullcontext
import sys
from types import SimpleNamespace

import pytest

from yoke_cli.self_host import bundle
from yoke_core.api import server_entrypoint
from yoke_core.domain import db_backend, universe_startup_lock


def test_proxy_setting_defaults_and_explicit_values():
    resolve = server_entrypoint.resolve_settings
    assert resolve([], env={}).trusted_proxies == "127.0.0.1"
    assert resolve([], env={"FORWARDED_ALLOW_IPS": "*"}).trusted_proxies == "127.0.0.1"
    assert resolve([], env={"YOKE_API_TRUSTED_PROXIES": ""}).trusted_proxies == ""
    assert (
        resolve([], env={"YOKE_API_TRUSTED_PROXIES": "10.0.0.0/24,::1"}).trusted_proxies
        == "10.0.0.0/24,::1"
    )
    assert (
        resolve(
            ["--trusted-proxies", "192.0.2.10"],
            env={"YOKE_API_TRUSTED_PROXIES": "127.0.0.1"},
        ).trusted_proxies
        == "192.0.2.10"
    )


@pytest.mark.parametrize("hosted", [False, True])
def test_startup_wires_proxy_trust_only_for_self_host(monkeypatch, hosted):
    captured = {}
    monkeypatch.setenv("YOKE_API_TRUSTED_PROXIES", "192.0.2.10")
    monkeypatch.setattr(
        universe_startup_lock, "hosted_tenant_container_process", lambda: hosted
    )
    monkeypatch.setattr(
        universe_startup_lock, "server_startup_guard", lambda _: nullcontext()
    )
    monkeypatch.setattr(db_backend, "resolve_pg_dsn", lambda: "unused")
    for name in ("universe_is_born", "admin_credential_exists"):
        monkeypatch.setattr(server_entrypoint, name, lambda: True)
    for name in ("ensure_core_schema", "ensure_permission_catalog"):
        monkeypatch.setattr(server_entrypoint, name, lambda: None)
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=lambda *args, **kwargs: captured.update(kwargs)),
    )
    assert server_entrypoint.main([]) == 0
    if hosted:
        assert "forwarded_allow_ips" not in captured
    else:
        assert captured["forwarded_allow_ips"] == "192.0.2.10"


def test_bundle_exposes_setting_and_preserves_empty_value():
    assert "YOKE_API_TRUSTED_PROXIES=127.0.0.1" in bundle._env_text(
        image="test", publish_spec="127.0.0.1:8765"
    )
    assert (
        "YOKE_API_TRUSTED_PROXIES: ${YOKE_API_TRUSTED_PROXIES-127.0.0.1}"
        in bundle._compose_text()
    )
