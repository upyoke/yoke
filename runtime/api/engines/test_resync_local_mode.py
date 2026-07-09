"""GitHub sync through a machine-config local-postgres connection.

Local mode inherits GitHub sync by construction: the resync engine runs
in-process wherever the engine dispatches, resolves the project GitHub
App auth from the CONNECTED universe's DB, and talks to GitHub over
bearer-token REST with that token. These tests prove the
construction end to end against a real disposable Postgres universe:

- the control-plane authority is reached exclusively through the machine
  config's ``local`` connection (transport ``local-postgres``, dsn_file
  credential) — ``YOKE_PG_DSN`` is unset for the engine run and the
  scratch machine config carries NO https/hosted connection;
- the token on the wire is exactly the universe-only GitHub App auth token
  (asserted on every ``Authorization`` header; the token exists nowhere else
  — not in env, config, or secret files);
- detect reads linkage rows from the universe DB, repair writes
  ``items.github_issue`` back into the same universe DB.

The config is authored through the same writer ``yoke init --local``
uses, so the connection entry shape under test is local mode's shape.
"""

from __future__ import annotations

import json
import urllib.parse
from types import SimpleNamespace

import pytest

import yoke_core.engines.resync as resync_mod
from yoke_core.domain import (
    connected_env_readiness,
    db_backend,
    gh_rest_transport,
    projects,
    yoke_connected_env,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from yoke_core.domain.cloud_db_secret_dsn import DB_SECRET_ARN_ENV
from yoke_core.domain.render_body import build_body
from yoke_contracts.machine_config import runtime as machine_runtime
from yoke_contracts.machine_config import schema as machine_contract
from yoke_cli.config import writer as machine_config_writer
from yoke_cli.config.local_universe_setup import LOCAL_ENV

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema

# The user's own GitHub App auth token for the local universe — a request
# authenticated with it proves resolution came from that universe.
UNIVERSE_ONLY_TOKEN = "ghs_local_universe_only_token"

# Repo the fixture schema seeds on the yoke project row.
PROJECT_REPO = "upyoke/yoke"

# Issue number the fake GitHub "creates" during repair.
CREATED_ISSUE_NUMBER = 555


class _FakeHttpResponse:
    """Minimal urlopen response: context manager + status/headers/read."""

    def __init__(self, payload) -> None:
        self._payload = payload
        self.status = 200
        self.headers: dict[str, str] = {}

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *_exc) -> bool:
        return False


class _RecordingGithubApi:
    """Replacement for ``gh_rest_transport.urlopen``.

    Records (method, url, Authorization) for every request and routes to
    canned GitHub-shaped responses. ``issues`` feeds the repo issue list;
    ``graphql_bodies`` maps issue number -> body for the heavy fetch.
    """

    def __init__(self, *, issues=None, graphql_bodies=None) -> None:
        self.requests: list[SimpleNamespace] = []
        self._issues = issues or []
        self._graphql_bodies = graphql_bodies or {}

    def __call__(self, request, timeout=None):
        url = request.full_url
        method = request.get_method()
        self.requests.append(SimpleNamespace(
            method=method, url=url,
            authorization=request.get_header("Authorization"),
        ))
        assert url.startswith(gh_rest_transport.GITHUB_API_BASE), url
        api_path = urllib.parse.urlsplit(url).path
        if method == "GET" and api_path == "/search/issues":
            return _FakeHttpResponse({"total_count": 0, "items": []})
        if method == "GET" and api_path.endswith("/issues"):
            return _FakeHttpResponse(self._issues)
        if method == "POST" and api_path == "/graphql":
            repository = {
                f"issue_{num}": {
                    "number": num, "body": body, "comments": {"nodes": []},
                }
                for num, body in self._graphql_bodies.items()
            }
            return _FakeHttpResponse({"data": {"repository": repository}})
        if method == "POST" and api_path.endswith("/labels"):
            return _FakeHttpResponse({"name": "label", "color": "ededed"})
        if method == "POST" and api_path.endswith("/issues"):
            return _FakeHttpResponse({
                "number": CREATED_ISSUE_NUMBER,
                "html_url": (
                    f"https://github.com/{PROJECT_REPO}"
                    f"/issues/{CREATED_ISSUE_NUMBER}"
                ),
            })
        return _FakeHttpResponse({})


@pytest.fixture
def local_universe(tmp_path, monkeypatch):
    """A disposable Postgres universe reached only via machine config.

    Seeds the universe the way local mode holds it — full fixture schema,
    a ``github`` capability row, and the user's own token as a
    ``capability_secrets`` row — then removes every ambient DSN binding so
    the ONLY route to the universe is the machine config's ``local``
    connection (transport ``local-postgres``, dsn_file credential).
    """
    db_name = pg_testdb.create_test_database()
    dsn = pg_testdb.dsn_for_test_database(db_name)
    try:
        # Universe-creation phase: pin the authority directly, mirroring
        # local_universe.pinned_authority during birth/bootstrap.
        monkeypatch.setenv(db_backend.PG_DSN_ENV, dsn)
        conn = db_backend.connect()
        try:
            apply_fixture_schema(conn)
            # A local universe holds only the user's own projects; blank
            # the second seeded project's repo so the multi-project fetch
            # loop skips it.
            conn.execute(
                "UPDATE projects SET github_repo = '' WHERE slug <> 'yoke'"
            )
            conn.commit()
        finally:
            conn.close()

        # The github capability + the user's own token, written through the
        # canonical capability surfaces into the universe DB.
        base = projects.cmd_capability_get_settings("yoke", "github")
        projects.cmd_capability_set_settings(
            "yoke", "github", "{}",
            base_settings_json=base, create=base is None,
        )
        projects.cmd_capability_set_secret(
            "yoke", "github", "token", UNIVERSE_ONLY_TOKEN, source="literal",
        )

        # Machine config: ONLY the local connection, authored through the
        # same writer `yoke init --local` uses. Point the config-file env at
        # a per-test scratch home (the engines conftest pins it to a shared
        # session-scoped stub; writing there would leak across tests).
        monkeypatch.setenv(
            machine_runtime.CONFIG_FILE_ENV,
            str(tmp_path / "machine-home" / "config.json"),
        )
        machine_config_writer.set_connection(
            LOCAL_ENV,
            transport=machine_contract.DEFAULT_TRANSPORT,
            dsn=dsn, prod=False, replace=True,
        )

        # Engine-run phase: drop every ambient authority binding. From here
        # on, reaching the universe REQUIRES the machine-config chain.
        monkeypatch.delenv(db_backend.PG_DSN_ENV, raising=False)
        monkeypatch.delenv(db_backend.PG_DSN_FILE_ENV, raising=False)
        monkeypatch.delenv(DB_SECRET_ARN_ENV, raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv(yoke_connected_env.DISABLE_ENV, raising=False)
        monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
        connected_env_readiness.reset_cache()

        state_root = tmp_path / "state"
        (state_root / "backlog").mkdir(parents=True)
        monkeypatch.setenv("YOKE_ROOT", str(state_root))

        config = json.loads(
            machine_runtime.config_path().read_text(encoding="utf-8")
        )
        yield SimpleNamespace(
            db_name=db_name, dsn=dsn,
            token=UNIVERSE_ONLY_TOKEN, config=config,
        )
    finally:
        connected_env_readiness.reset_cache()
        pg_testdb.drop_test_database(db_name)


def _seed_item(universe, item_id: int, github_issue) -> str:
    """Insert one backlog item into the universe; return its rendered body."""
    conn = pg_testdb.connect_test_database(universe.db_name)
    try:
        conn.execute(
            "INSERT INTO items (id, title, status, priority, type, source, "
            "spec, frozen, github_issue, project_id, project_sequence, "
            "created_at, updated_at) "
            "VALUES (%s, 'Local mode sync item', 'implementing', 'high', "
            "'issue', 'manual', 'Spec body', 0, %s, 1, %s, "
            "'2026-01-01', '2026-01-01')",
            (item_id, github_issue, item_id),
        )
        conn.commit()
        body = build_body(conn, item_id) or ""
    finally:
        conn.close()
    return body


def _read_github_issue(universe, item_id: int):
    conn = pg_testdb.connect_test_database(universe.db_name)
    try:
        row = conn.execute(
            "SELECT github_issue FROM items WHERE id = %s", (item_id,),
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row is not None else None


def _patch_project_github_auth(monkeypatch, universe) -> None:
    def _resolve(project: str, **_kwargs) -> ProjectGithubAuth:
        return ProjectGithubAuth(
            project=project,
            repo=PROJECT_REPO,
            token=universe.token,
            env={"GH_TOKEN": universe.token},
            installation_id="12345",
            token_source="github_app_installation",
        )

    for target in (
        "yoke_core.engines.resync.resolve_project_github_auth",
        "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
        "yoke_core.engines.resync_detect_linkage.resolve_project_github_auth",
        "yoke_core.engines.resync_repair.resolve_project_github_auth",
        "yoke_core.engines.resync_runtime.resolve_project_github_auth",
        "yoke_core.domain.github_rest.resolve_project_github_auth",
        "yoke_core.domain.backlog_github_body_title_sync.resolve_project_github_auth",
        "yoke_core.domain.backlog_github_comments.resolve_project_github_auth",
        "yoke_core.domain.backlog_github_done_sync.resolve_project_github_auth",
        "yoke_core.domain.backlog_github_fetch.resolve_project_github_auth",
        "yoke_core.domain.backlog_github_item_create.resolve_project_github_auth",
        "yoke_core.domain.backlog_github_label_sync.resolve_project_github_auth",
        "yoke_core.domain.backlog_github_state_sync.resolve_project_github_auth",
        "yoke_core.domain.backlog_github_transport.resolve_project_github_auth",
    ):
        monkeypatch.setattr(target, _resolve)


class TestLocalConnectionShape:
    def test_machine_config_holds_only_the_local_connection(
        self, local_universe,
    ):
        """The scratch config has no https/hosted entry to consult."""
        config = local_universe.config
        assert set(config["connections"]) == {LOCAL_ENV}
        assert config["active_env"] == LOCAL_ENV
        entry = config["connections"][LOCAL_ENV]
        assert entry["transport"] == machine_contract.DEFAULT_TRANSPORT
        assert entry[machine_contract.PROD_FLAG_KEY] is False
        source = entry["credential_source"]
        assert source["kind"] == machine_contract.CREDENTIAL_KIND_DSN_FILE
        assert "api_url" not in entry

    def test_github_token_lives_only_in_the_universe_db(self, local_universe):
        """The GitHub App auth is a capability_secrets row, never machine-config state."""
        assert local_universe.token not in json.dumps(local_universe.config)
        conn = pg_testdb.connect_test_database(local_universe.db_name)
        try:
            row = conn.execute(
                "SELECT value, source FROM capability_secrets cs "
                "JOIN projects p ON p.id = cs.project_id "
                "WHERE p.slug = 'yoke' AND cs.type = 'github' "
                "AND cs.key = 'token'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row[0] == local_universe.token
        assert row[1] == "literal"


class TestDetectUnderLocalDispatch:
    def test_detect_pairs_items_with_the_universe_db_token(
        self, local_universe, monkeypatch, capsys,
    ):
        """Detect resolves the universe DB through the local connection.

        Zero drift end state: linkage pairs the seeded item against the
        mirrored GitHub issue, and every GitHub request carries the token
        that exists only in the universe's capability_secrets row.
        """
        item_id = 4501
        body = _seed_item(local_universe, item_id, "#100")
        gh_issue = {
            "number": 100,
            "title": f"[YOK-{item_id}] Local mode sync item",
            "labels": [
                {"name": "type:issue"},
                {"name": "priority:high"},
                {"name": "status:implementing"},
                {"name": "source:manual"},
            ],
            "state": "open",
            "body": body,
        }
        api = _RecordingGithubApi(
            issues=[gh_issue], graphql_bodies={100: body},
        )
        monkeypatch.setattr(gh_rest_transport, "urlopen", api)
        _patch_project_github_auth(monkeypatch, local_universe)

        rc = resync_mod.main(["--detect-only"])
        out = capsys.readouterr().out

        assert rc == 0, out
        assert "Paired: 1" in out
        assert "Local orphans: 0" in out
        assert "GitHub orphans: 0" in out
        assert "Drifts found: 0" in out

        assert api.requests, "engine made no GitHub requests"
        for req in api.requests:
            assert req.authorization == f"Bearer {local_universe.token}", (
                f"{req.method} {req.url} did not use the universe-DB token"
            )


class TestRepairUnderLocalDispatch:
    def test_fix_creates_issue_and_writes_linkage_into_universe(
        self, local_universe, monkeypatch, capsys,
    ):
        """Repair round-trips through the machine-config-resolved universe.

        A local orphan (no github_issue) is repaired by creating a GitHub
        issue with the universe-DB token, and the resulting issue number is
        written back to ``items.github_issue`` in the SAME universe DB —
        the read and the write side of sync both land in the local universe.
        """
        item_id = 4502
        _seed_item(local_universe, item_id, None)
        api = _RecordingGithubApi()
        monkeypatch.setattr(gh_rest_transport, "urlopen", api)
        _patch_project_github_auth(monkeypatch, local_universe)

        rc = resync_mod.main(["--fix"])
        out = capsys.readouterr().out

        assert rc == 0, out
        assert f"FIXED: YOK-{item_id}" in out
        assert (
            _read_github_issue(local_universe, item_id)
            == f"#{CREATED_ISSUE_NUMBER}"
        )

        creates = [
            req for req in api.requests
            if req.method == "POST"
            and urllib.parse.urlsplit(req.url).path.endswith("/issues")
        ]
        assert len(creates) == 1
        for req in api.requests:
            assert req.authorization == f"Bearer {local_universe.token}", (
                f"{req.method} {req.url} did not use the universe-DB token"
            )
