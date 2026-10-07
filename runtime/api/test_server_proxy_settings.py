"""Server startup supplies one declared trust boundary to Uvicorn."""

from contextlib import contextmanager
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import Request

from yoke_cli.self_host import bundle
from yoke_cli.self_host.env_template import env_text
from yoke_core.api import server_entrypoint, trusted_proxy
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
    assert (
        resolve(["--trusted-proxies", " 10.0.0.0/24, ::1 "], env={}).trusted_proxies
        == "10.0.0.0/24,::1"
    )


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "127.0.0.1,*",
        "10.0.0.0/33",
        "::/129",
        "proxy.example",
        "127.0.0.1,",
        ",",
        "10.0.0.1/24",
    ],
)
@pytest.mark.parametrize("source", ["env", "flag"])
def test_invalid_proxy_setting_refuses_with_recovery(value, source, capsys):
    env = {trusted_proxy.TRUSTED_PROXIES_ENV: value} if source == "env" else {}
    argv = ["--trusted-proxies", value] if source == "flag" else []
    with pytest.raises(SystemExit) as refused:
        server_entrypoint.resolve_settings(argv, env=env)
    assert refused.value.code == 2
    error = capsys.readouterr().err
    assert "trusted_proxies_invalid" in error
    assert trusted_proxy.TRUSTED_PROXIES_ENV in error
    assert "yoke self-host init --dir PATH --protect-existing --start" in error


def test_invalid_proxy_setting_refuses_before_database_startup(monkeypatch, capsys):
    monkeypatch.setenv(trusted_proxy.TRUSTED_PROXIES_ENV, "*")
    monkeypatch.setattr(
        db_backend, "resolve_pg_dsn", lambda: pytest.fail("must not reach database")
    )
    with pytest.raises(SystemExit):
        server_entrypoint.main([])
    assert "trusted_proxies_invalid" in capsys.readouterr().err


@pytest.mark.parametrize("hosted", [False, True])
def test_startup_wires_proxy_trust_in_every_serving_mode(monkeypatch, hosted):
    captured = {}
    guard = {"held": False}
    monkeypatch.setenv(trusted_proxy.TRUSTED_PROXIES_ENV, "127.0.0.1")
    monkeypatch.setattr(
        universe_startup_lock, "hosted_tenant_container_process", lambda: hosted
    )

    @contextmanager
    def startup_guard(_dsn):
        guard["held"] = True
        yield
        guard["held"] = False

    monkeypatch.setattr(universe_startup_lock, "server_startup_guard", startup_guard)
    monkeypatch.setattr(db_backend, "resolve_pg_dsn", lambda: "unused")
    for name in ("universe_is_born", "admin_credential_exists"):
        monkeypatch.setattr(server_entrypoint, name, lambda: True)
    for name in ("ensure_core_schema", "ensure_permission_catalog"):
        monkeypatch.setattr(server_entrypoint, name, lambda: None)

    def run(app, **kwargs):
        worker_env = {
            key: os.environ.get(key)
            for key in (trusted_proxy.TRUSTED_PROXIES_ENV, server_entrypoint.APP_ENV)
        }
        captured.update(kwargs, app=app, worker_env=worker_env, locked=guard["held"])

    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=run),
    )
    assert (
        server_entrypoint.main(["--trusted-proxies", "192.0.2.10", "--workers", "2"])
        == 0
    )
    assert captured["app"] == "yoke_core.api.trusted_proxy:create_app"
    assert captured["proxy_headers"] is False
    assert captured["factory"] is True
    assert captured["worker_env"][trusted_proxy.TRUSTED_PROXIES_ENV] == "192.0.2.10"
    assert captured["worker_env"]["YOKE_API_APP"] == server_entrypoint.DEFAULT_APP
    # Hosted tenants release the startup lock before serving; others hold it.
    assert captured["locked"] == (not hosted)
    assert os.environ[trusted_proxy.TRUSTED_PROXIES_ENV] == "127.0.0.1"


def test_worker_factory_uses_inherited_app_and_proxy_settings(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/peer")
    def peer(request: Request):
        return {"client": request.client.host, "scheme": request.url.scheme}

    monkeypatch.setitem(sys.modules, "proxy_test_app", SimpleNamespace(app=app))
    monkeypatch.setenv("YOKE_API_APP", "proxy_test_app:app")
    # The worker app must not reparse listener values overridden by parent flags.
    monkeypatch.setenv("YOKE_API_PORT", "invalid-port")
    monkeypatch.setenv(trusted_proxy.TRUSTED_PROXIES_ENV, "192.0.2.0/24")
    client = TestClient(trusted_proxy.create_app(), client=("192.0.2.10", 54321))
    response = client.get(
        "/peer",
        headers={"X-Forwarded-For": "198.51.100.7", "X-Forwarded-Proto": "https"},
    )
    assert response.json() == {"client": "198.51.100.7", "scheme": "https"}


def test_bundle_exposes_setting_and_preserves_empty_value():
    assert "YOKE_API_TRUSTED_PROXIES=127.0.0.1" in env_text(
        image="test", publish_spec="127.0.0.1:8765", admin_name="Ada Lovelace"
    )
    assert (
        "YOKE_API_TRUSTED_PROXIES: ${YOKE_API_TRUSTED_PROXIES-127.0.0.1}"
        in bundle._compose_text()
    )
