"""File navigation retains its destination across browser admission doors."""

import pytest

from runtime.api import web_sign_in_door_test_support as door
from runtime.api.token_browser_sign_in_test_support import (
    _mint,
    _redeem,
    context as context,
)
from runtime.api.universe_ui_server_test_support import _TOKEN, ui_client as ui_client
from yoke_contracts.machine_authorization import APPROVAL_RETURN_COOKIE
from yoke_core.api.browser_return import browser_return_path
from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.shared_file_storage import put_shared_file

_clean_oidc_env = door._clean_oidc_env
db_conn = door.db_conn
client = door.client
door_env = door.door_env
provider = door.provider

FILE = "/v1/files/yoke/plans/sign-in.html?download=1"
BROWSER = {"Accept": "text/html", "Sec-Fetch-Mode": "navigate"}


def _seed_file(conn, actor_id):
    seed_roles_and_permissions(conn)
    project = resolve_project(conn, "yoke", required=True)
    grant_actor_project_role(
        conn,
        actor_id=actor_id,
        project_id=project.id,
        role_name=ROLE_ADMIN,
        granted_by_actor_id=actor_id,
    )
    put_shared_file(
        conn,
        project_id=project.id,
        project="yoke",
        path="plans/sign-in.html",
        content=b"file contents",
    )
    conn.commit()


@pytest.mark.parametrize("cookie", ["", "invalid"])
def test_oidc_browser_returns_to_original_file(
    db_conn, client, door_env, provider, cookie
):
    door._enable_domain_admission(db_conn, domain="example.com")
    if cookie:
        client.cookies.set("yoke_web_session", cookie)
    response = client.get(FILE, headers=BROWSER, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert response.headers["cache-control"] == "no-store"
    assert client.cookies.get(APPROVAL_RETURN_COOKIE).strip('"') == FILE
    assert "Sign in" in client.get("/").text
    signed_in = door._sign_in(client, provider)
    assert signed_in.headers["location"] == FILE
    assert not client.cookies.get(APPROVAL_RETURN_COOKIE)
    from yoke_core.domain.external_identities import resolve_external_identity

    actor_id = resolve_external_identity(
        db_conn, issuer=provider.issuer, subject="subject-1"
    )
    _seed_file(db_conn, actor_id)
    opened = client.get(signed_in.headers["location"])
    assert opened.content == b"file contents"
    assert opened.headers["content-disposition"].startswith("attachment")


def test_token_browser_returns_to_original_file(context):
    conn, actor_id, token, client = context
    _seed_file(conn, actor_id)
    redirect = client.get(FILE, headers=BROWSER, follow_redirects=False)
    assert redirect.status_code == 303
    assert "yoke ui up" in client.get("/").text
    response = _redeem(client, _mint(client, token))
    assert response.json()["return_path"] == FILE
    assert not client.cookies.get(APPROVAL_RETURN_COOKIE)
    assert client.get(response.json()["return_path"]).content == b"file contents"


def test_local_browser_returns_after_private_token_exchange(ui_client, monkeypatch):
    from fastapi.responses import Response
    from yoke_core.api.routes import shared_files

    monkeypatch.setattr(
        shared_files, "shared_file_response", lambda *a, **k: Response(b"local file")
    )
    redirect = ui_client.get(FILE, headers=BROWSER, follow_redirects=False)
    assert redirect.status_code == 303
    page = ui_client.get(redirect.headers["location"])
    assert "session_token_required" in page.text and "yoke ui up" in page.text
    admitted = ui_client.get(f"/?token={_TOKEN}", follow_redirects=False)
    assert admitted.headers["location"] == FILE
    assert ui_client.get(FILE).content == b"local file"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Accept": "application/json"},
        {**BROWSER, "Authorization": "Bearer invalid"},
    ],
)
def test_api_clients_keep_structured_401(client, headers):
    response = client.get(FILE, headers=headers, follow_redirects=False)
    assert response.status_code == 401
    assert response.json()["error"]["code"]
    assert "location" not in response.headers


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.example/v1/files/yoke/a.html",
        "//evil.example/v1/files/yoke/a.html",
        "/v1/files/yoke/../a.html",
        "/v1/files/yoke/a.html#fragment",
        "/v1/files/yoke/a.html?x=%0d%0aLocation:evil",
        "/v1/files/yoke/a.html?x=%5c",
        "/v1/functions/call",
        "/v1/files/yoke/%2f%2fevil",
    ],
)
def test_return_cookie_cannot_redirect_outside_supported_pages(value):
    assert browser_return_path(value) == ""


def test_return_cookie_preserves_encoded_query():
    assert browser_return_path(FILE + "&label=a%20b") == FILE + "&label=a%20b"
