"""Shared helpers for the bootstrap_project pytest suites."""

from __future__ import annotations

import contextlib
import json
import subprocess
from pathlib import Path

from yoke_core.domain import db_backend
from yoke_core.domain.bootstrap_project import BootstrapContext
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout


class _FakeRestResponse:
    """Mimic urlopen() context-manager return for gh_rest_transport tests."""

    def __init__(self, status: int, body) -> None:
        self.status = status
        self.headers = {}
        if isinstance(body, (bytes, bytearray)):
            self._body = bytes(body)
        else:
            self._body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _fake_repo_public_key_b64() -> str:
    """Generate a real ed25519 public key (base64) so PyNaCl encryption succeeds."""
    import base64
    from nacl.public import PrivateKey
    private = PrivateKey.generate()
    return base64.b64encode(bytes(private.public_key)).decode("ascii")


def _install_fake_rest(monkeypatch) -> list[tuple[str, str]]:
    """Install a urlopen fake covering setup's /user, public-key, PUT secret,
    and PUT environment calls.

    Returns a list of ``(method, path)`` tuples for routing assertions.
    """
    seen: list[tuple[str, str]] = []
    public_key_b64 = _fake_repo_public_key_b64()

    def fake_urlopen(request, timeout):
        method = (getattr(request, "method", None) or request.get_method()).upper()
        url = request.full_url
        path = url.split("api.github.com", 1)[-1] if "api.github.com" in url else url
        seen.append((method, path))
        if method == "GET" and path == "/user":
            return _FakeRestResponse(200, {"login": "tester", "id": 123})
        if method == "GET" and path.endswith("/actions/secrets/public-key"):
            return _FakeRestResponse(200, {"key_id": "kid-1", "key": public_key_b64})
        if method == "PUT" and "/actions/secrets/" in path:
            return _FakeRestResponse(204, b"")
        if method == "PUT" and "/environments/production" in path:
            return _FakeRestResponse(200, {"name": "production"})
        return _FakeRestResponse(200, {})

    monkeypatch.setattr(
        "yoke_core.domain.gh_rest_transport.urlopen", fake_urlopen
    )
    return seen


def install_fake_project_github_auth(monkeypatch) -> None:
    """Patch bootstrap modules to resolve a shaped GitHub App auth bundle."""

    def fake_resolve(project: str, **_kwargs) -> ProjectGithubAuth:
        return ProjectGithubAuth(
            project=project,
            repo="example-org/buzz",
            token="ghs_installation_token",
            env={"GH_TOKEN": "ghs_installation_token"},
            installation_id="12345",
            token_source="github_app_installation",
        )

    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_preflight.resolve_project_github_auth",
        fake_resolve,
    )
    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_setup.resolve_project_github_auth",
        fake_resolve,
    )


_BOOTSTRAP_SCHEMA_DDL = """
    CREATE TABLE projects (
      id INTEGER PRIMARY KEY,
      slug TEXT NOT NULL UNIQUE,
      name TEXT NOT NULL,
      github_repo TEXT,
      public_item_prefix TEXT NOT NULL DEFAULT 'YOK'
    );
    CREATE TABLE project_capabilities (
      id INTEGER PRIMARY KEY,
      project_id INTEGER NOT NULL REFERENCES projects(id),
      type TEXT NOT NULL,
      settings TEXT DEFAULT '{}',
      created_at TEXT,
      UNIQUE(project_id, type)
    );
    CREATE TABLE sites (
      id TEXT PRIMARY KEY,
      project_id INTEGER NOT NULL REFERENCES projects(id),
      name TEXT NOT NULL,
      settings TEXT DEFAULT '{}'
    );
    CREATE TABLE environments (
      id TEXT PRIMARY KEY,
      site TEXT NOT NULL,
      name TEXT NOT NULL,
      settings TEXT DEFAULT '{}'
    );
    CREATE TABLE capability_secrets (
      id INTEGER PRIMARY KEY,
      project_id INTEGER NOT NULL REFERENCES projects(id),
      type TEXT NOT NULL,
      key TEXT NOT NULL,
      value TEXT NOT NULL,
      source TEXT NOT NULL DEFAULT 'literal' CHECK(source = 'literal'),
      UNIQUE(project_id, type, key)
    );
"""


def _apply_bootstrap_seed(
    conn,
    *,
    key_path: str,
    include_project: bool = True,
    include_github_capability: bool = True,
    include_ssh_capability: bool = True,
) -> None:
    """Apply the bootstrap schema + selected buzz rows to a connection."""
    execute_schema_script(conn, _BOOTSTRAP_SCHEMA_DDL)
    p = _p(conn)
    if include_project:
        conn.execute(
            "INSERT INTO projects (id, slug, name, github_repo) "
            f"VALUES ({p}, {p}, {p}, {p})",
            (2, "buzz", "Buzz", "example-org/buzz"),
        )
        conn.execute(
            "INSERT INTO sites (id, project_id, name, settings) "
            f"VALUES ({p}, {p}, {p}, {p})",
            (
                "buzz-web",
                2,
                "Buzz Web",
                json.dumps({
                    "domains": [{"domain_name": "buzz.example.com"}],
                }),
            ),
        )
        conn.execute(
            "INSERT INTO environments (id, site, name, settings) "
            f"VALUES ({p}, {p}, {p}, {p})",
            (
                "buzz-web-production",
                "buzz-web",
                "production",
                json.dumps({
                    "hosts": {"origin": "origin.buzz.example.com"},
                    "servers": [{"host": "45.55.157.144"}],
                }),
            ),
        )
    if include_project and include_ssh_capability:
        conn.execute(
            "INSERT INTO project_capabilities (project_id, type, settings) "
            f"VALUES ({p}, {p}, {p})",
            (
                2,
                "ssh",
                '{{"user":"openclaw","host":"45.55.157.144","key_path":"{0}"}}'.format(key_path),
            ),
        )
    # The canonical project_github_auth resolver requires a github capability
    # row plus a GitHub App repository binding. Bootstrap tests that exercise
    # successful GitHub setup patch the resolver directly; this seed covers the
    # DB rows unrelated to installation-token minting.
    if include_project and include_github_capability:
        conn.execute(
            "INSERT INTO project_capabilities (project_id, type, settings) "
            f"VALUES ({p}, {p}, {p})",
            (
                2,
                "github",
                '{"repo_owner":"example-org","repo_name":"buzz"}',
            ),
        )
    if include_project:
        conn.execute(
            "INSERT INTO project_capabilities (project_id, type, settings) "
            f"VALUES ({p}, {p}, {p})",
            (2, "ci_workflow_file", json.dumps({"workflow_file": "ci.yml"})),
        )
    conn.commit()


def register_bootstrap_backend_checkout(db_path: Path, checkout: Path) -> None:
    conn = connect_test_db(str(db_path))
    try:
        register_machine_checkout(checkout.parent / "machine-config", checkout, 2)
        conn.commit()
    finally:
        conn.close()


def update_bootstrap_backend_ssh_settings(db_path: Path, settings: str) -> None:
    conn = connect_test_db(str(db_path))
    try:
        p = _p(conn)
        conn.execute(
            f"UPDATE project_capabilities SET settings={p} "
            f"WHERE project_id={p} AND type={p}",
            (settings, 2, "ssh"),
        )
        conn.commit()
    finally:
        conn.close()


def seed_bootstrap_backend_db(key_path: str, **seed_options):
    """Return an ``apply_schema`` strategy for the disposable bootstrap DB."""
    from yoke_core.domain import db_backend

    def _apply() -> None:
        conn = db_backend.connect()
        try:
            _apply_bootstrap_seed(conn, key_path=key_path, **seed_options)
        finally:
            conn.close()

    return _apply


def _preflight_ctx(
    tmp_path: Path, *, db_missing: bool = False, yoke_db: Path | None = None
) -> BootstrapContext:
    if yoke_db is None:
        yoke_dir = tmp_path / "runtime"
        yoke_dir.mkdir(parents=True, exist_ok=True)
        db_path = yoke_dir / "yoke.db"
    else:
        db_path = yoke_db
    if db_missing:
        db_path = tmp_path / "missing-yoke-db-token"
    return BootstrapContext(
        project="buzz",
        project_root=tmp_path,
        script_dir=tmp_path / ".agents" / "skills" / "yoke" / "scripts",
        yoke_db=db_path,
    )


def _make_fake_run(
    *,
    gh_auth_ok: bool = True,
    ssh_ok: bool = True,
    tls_state: str = "exists",
):
    """Return a fake _run that mocks GitHub CLI auth, SSH, and the TLS probe.

    ``gh_auth_ok`` is retained for legacy callers but no longer drives any
    gh subprocess — preflight resolves project github auth via the
    canonical resolver (DB-backed), not via a host-credential probe.
    """

    _unused_gh_auth_ok = gh_auth_ok  # retained for callsite back-compat

    def fake_run(cmd, *, stdin=None, cwd=None, env=None):
        if cmd and cmd[0] == "ssh":
            tls_payload = " ".join(cmd)
            if "letsencrypt" in tls_payload:
                return subprocess.CompletedProcess(
                    cmd, 0 if ssh_ok else 1, tls_state + "\n", ""
                )
            return subprocess.CompletedProcess(cmd, 0 if ssh_ok else 1, "ok\n", "")
        raise AssertionError(f"Unexpected command in preflight fake_run: {cmd}")

    return fake_run


@contextlib.contextmanager
def bootstrap_seeded_db(tmp_path: Path, ssh_key: Path, **seed_options):
    """Context manager yielding a seeded ``ctx.yoke_db`` token (PG-portable).

    Enters :func:`init_test_db` so a disposable per-test Postgres database is
    created and ``YOKE_PG_DSN`` repointed at it for the body (dropped on
    exit). The :func:`seed_bootstrap_backend_db` strategy lands the bootstrap
    rows in that DB so the canonical ``resolve_project_github_auth`` resolver
    reads real state instead of the shared ``dbname=postgres`` database. Yields
    the ``db_path`` compatibility token; the caller threads it into
    ``BootstrapContext(yoke_db=...)`` while all reads go through Postgres.
    """
    with init_test_db(
        tmp_path,
        apply_schema=seed_bootstrap_backend_db(str(ssh_key), **seed_options),
    ) as token:
        yield Path(token)


@contextlib.contextmanager
def setup_validation_ctx(tmp_path: Path):
    """Yield a ``(ctx, db_path, ssh_key)`` tuple for setup validation tests."""
    repo_path, ssh_key = _validation_fixture_layout(tmp_path)
    with bootstrap_seeded_db(tmp_path, ssh_key) as db_path:
        register_bootstrap_backend_checkout(db_path, repo_path)
        ctx = BootstrapContext(
            project="buzz", project_root=tmp_path,
            script_dir=tmp_path / ".agents" / "skills" / "yoke" / "scripts",
            yoke_db=db_path,
        )
        yield ctx, db_path, ssh_key


def _validation_fixture_layout(tmp_path: Path) -> tuple[Path, Path]:
    """Lay down the repo dir + ssh key the setup-validation suites need."""
    repo_path = tmp_path / "buzz-repo"
    repo_path.mkdir()
    ssh_key = tmp_path / ".ssh_key"
    ssh_key.write_text("fake-ssh-key")
    return repo_path, ssh_key


def write_fake_rendered_workflows(cmd: list[str]) -> None:
    """Populate the --output-dir workflow files for mocked render_project calls."""

    if "--output-dir" not in cmd:
        raise AssertionError(f"render_project command missing --output-dir: {cmd}")
    output_dir = Path(cmd[cmd.index("--output-dir") + 1])
    workflows_dir = output_dir / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / "buzz-deploy.yml").write_text("name: Buzz Deploy\n")
    (workflows_dir / "buzz-smoke.yml").write_text("name: Buzz Smoke Test\n")
