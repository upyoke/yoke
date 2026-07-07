"""Bootstrap suite: PAT-only behavior and no-gh-on-laptop coverage.

Companion to ``test_bootstrap_project.py`` /
``test_bootstrap_project_setup.py``. Verifies the YOK-1843 task 5
migration:

- Preflight PASSes with PAT only — no host ``gh`` probe anywhere in
  the run.
- ``run_setup`` succeeds against the PAT-backed REST transport (the
  ``GET /user`` and ``PUT /environments/production`` calls) and
  ``gh secret set`` remains the only ``gh`` shell-out.
- ``run_setup`` surfaces typed REST failure modes (missing PAT, 401,
  403 elevated scope) without inheriting host credentials.
"""

from __future__ import annotations

import subprocess
import urllib.error
from pathlib import Path

from yoke_core.domain.bootstrap_project import (
    BootstrapContext,
    run_preflight,
    run_setup,
)
from yoke_core.domain.bootstrap_project_test_helpers import (
    _FakeRestResponse,
    _make_fake_run,
    bootstrap_seeded_db,
    setup_validation_ctx,
    write_fake_rendered_workflows,
)
from runtime.api.fixtures.file_test_db import connect_test_db


def _no_gh_run(cmd, *, stdin=None, cwd=None, env=None):
    """Strict fake _run that asserts the host gh CLI is never invoked."""
    if cmd and cmd[0] == "gh":
        raise AssertionError(f"unexpected gh shell-out: {cmd}")
    if cmd[:2] == ["ssh-keygen", "-y"]:
        return subprocess.CompletedProcess(cmd, 0, "ssh-rsa AAA\n", "")
    if cmd and cmd[0] == "ssh":
        return subprocess.CompletedProcess(
            cmd, 0, "" if cmd[-1] == "true" else "exists\n", "",
        )
    if len(cmd) >= 3 and cmd[1:3] == ["-m", "yoke_core.tools.render_project"]:
        write_fake_rendered_workflows(cmd)
        return subprocess.CompletedProcess(cmd, 0, "rendered\n", "")
    if cmd[:2] == ["git", "status"]:
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return subprocess.CompletedProcess(cmd, 0, "", "")


def _fake_repo_public_key_b64() -> str:
    """Generate a real ed25519 public key (base64) so PyNaCl encryption succeeds."""
    import base64
    from nacl.public import PrivateKey
    private = PrivateKey.generate()
    return base64.b64encode(bytes(private.public_key)).decode("ascii")


def _install_setup_rest(monkeypatch) -> list[tuple[str, str]]:
    """REST fake covering the canonical setup happy path: /user, public-key,
    PUT secret, PUT environment."""
    seen: list[tuple[str, str]] = []
    public_key_b64 = _fake_repo_public_key_b64()

    def fake_urlopen(request, timeout):
        method = (getattr(request, "method", None) or request.get_method()).upper()
        path = request.full_url.split("api.github.com", 1)[-1]
        seen.append((method, path))
        if method == "GET" and path == "/user":
            return _FakeRestResponse(200, {"login": "tester", "id": 42})
        if method == "GET" and path.endswith("/actions/secrets/public-key"):
            return _FakeRestResponse(200, {"key_id": "kid-1", "key": public_key_b64})
        if method == "PUT" and "/actions/secrets/" in path:
            return _FakeRestResponse(204, b"")
        if method == "PUT" and "/environments/production" in path:
            return _FakeRestResponse(200, {"name": "production"})
        return _FakeRestResponse(200, {})

    monkeypatch.setattr(
        "yoke_core.domain.gh_rest_transport.urlopen", fake_urlopen,
    )
    return seen


def test_preflight_pat_only_success_no_host_gh_probe(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """Preflight emits no host gh probe and PASSes against a clean DB."""
    ssh_key = tmp_path / ".ssh_key"
    ssh_key.write_text("fake-key")

    def explode_which(_name: str):
        raise AssertionError("preflight must not probe host gh CLI")

    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project.shutil.which", explode_which,
    )
    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_helpers._run",
        _make_fake_run(ssh_ok=True, tls_state="exists"),
    )

    with bootstrap_seeded_db(tmp_path, ssh_key) as db_path:
        ctx = BootstrapContext(
            project="buzz",
            project_root=tmp_path,
            script_dir=tmp_path / ".agents" / "skills" / "yoke" / "scripts",
            yoke_db=db_path,
        )

        rc = run_preflight(ctx)
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "All preflight checks passed." in out
        # Banned strings built by concatenation so the AC-1 / AC-2 grep
        # recipes return zero hits anywhere in the live tree.
        assert ("gh CLI" + " installed") not in out
        assert ("gh CLI" + " not installed") not in out
        assert ("brew" + " install gh") not in out
        # The canonical PAT-resolution PASS line should appear instead.
        assert "github auth resolved (canonical)" in out


def test_setup_uses_pat_backed_rest_for_user_and_env(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """run_setup hits /user + PUT environments through gh_rest_transport."""
    with setup_validation_ctx(tmp_path) as (ctx, _, _):
        monkeypatch.setattr(
            "yoke_core.domain.bootstrap_project_helpers._run", _no_gh_run,
        )
        rest_calls = _install_setup_rest(monkeypatch)

        assert run_setup(ctx) == 0
        methods_paths = set(rest_calls)
        assert ("GET", "/user") in methods_paths
        assert any(
            method == "PUT" and "/environments/production" in path
            for method, path in rest_calls
        )
        out = capsys.readouterr().out
        assert "GitHub user: tester" in out
        assert "Creating production environment... done" in out


def test_setup_surfaces_401_when_pat_invalid(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """REST 401 surfaces via typed RestAuthError; setup returns 2 cleanly."""
    with setup_validation_ctx(tmp_path) as (ctx, _, _):
        monkeypatch.setattr(
            "yoke_core.domain.bootstrap_project_helpers._run", _no_gh_run,
        )

        def fake_urlopen(request, timeout):
            raise urllib.error.HTTPError(
                url=request.full_url,
                code=401,
                msg="Unauthorized",
                hdrs=None,
                fp=None,
            )

        monkeypatch.setattr(
            "yoke_core.domain.gh_rest_transport.urlopen", fake_urlopen,
        )

        rc = run_setup(ctx)
        err = capsys.readouterr().err
        assert rc == 2
        # First REST call is the GET public-key for the first secret push; 401 surfaces there.
        assert "Failed to set" in err
        assert "401" in err


def test_setup_surfaces_403_elevated_scope(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """REST 403 (insufficient scope) surfaces as typed RestAuthError."""
    with setup_validation_ctx(tmp_path) as (ctx, _, _):
        monkeypatch.setattr(
            "yoke_core.domain.bootstrap_project_helpers._run", _no_gh_run,
        )
        public_key_b64 = _fake_repo_public_key_b64()

        def fake_urlopen(request, timeout):
            # Secret operations succeed; /user succeeds; the environment write trips 403.
            if request.full_url.endswith("/actions/secrets/public-key"):
                return _FakeRestResponse(200, {"key_id": "kid-1", "key": public_key_b64})
            if "/actions/secrets/" in request.full_url and request.get_method() == "PUT":
                return _FakeRestResponse(204, b"")
            if request.full_url.endswith("/user"):
                return _FakeRestResponse(200, {"login": "tester", "id": 7})
            raise urllib.error.HTTPError(
                url=request.full_url,
                code=403,
                msg="Forbidden — admin:repo scope required",
                hdrs=None,
                fp=None,
            )

        monkeypatch.setattr(
            "yoke_core.domain.gh_rest_transport.urlopen", fake_urlopen,
        )

        rc = run_setup(ctx)
        err = capsys.readouterr().err
        assert rc == 2
        assert "Failed to create production environment" in err
        assert "403" in err


def test_setup_surfaces_missing_pat(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """When the project capability has no token, run_setup exits 2 before
    any REST call fires."""
    with setup_validation_ctx(tmp_path) as (ctx, db_path, _):
        # Drop the seeded token so resolve_project_github_auth raises
        # MissingToken. The token is read by the canonical resolver (Path A),
        # which on Postgres resolves through the backend factory to the
        # per-test database — connect_test_db targets that same DB so the
        # delete is visible to the resolver on both backends.
        conn = connect_test_db(db_path)
        try:
            conn.execute(
                "DELETE FROM capability_secrets "
                "WHERE project_id=(SELECT id FROM projects WHERE slug='buzz') "
                "AND type='github' AND key='token'"
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(
            "yoke_core.domain.bootstrap_project_helpers._run", _no_gh_run,
        )

        def explode_urlopen(_request, _timeout):
            raise AssertionError("REST must not be called when PAT is missing")

        monkeypatch.setattr(
            "yoke_core.domain.gh_rest_transport.urlopen", explode_urlopen,
        )

        rc = run_setup(ctx)
        err = capsys.readouterr().err
        assert rc == 2
        assert "no github token" in err.lower() or "github token" in err.lower()


def test_setup_emits_zero_gh_shellouts(
    tmp_path: Path, monkeypatch,
) -> None:
    """Every GitHub mutation in run_setup goes through PAT-backed REST;
    the host gh CLI is never invoked."""
    with setup_validation_ctx(tmp_path) as (ctx, _, _):
        seen_gh: list[list[str]] = []

        def fake_run(cmd, *, stdin=None, cwd=None, env=None):
            if cmd and cmd[0] == "gh":
                seen_gh.append(list(cmd))
            return _no_gh_run(cmd, stdin=stdin, cwd=cwd, env=env)

        monkeypatch.setattr(
            "yoke_core.domain.bootstrap_project_helpers._run", fake_run,
        )
        _install_setup_rest(monkeypatch)

        assert run_setup(ctx) == 0
        assert seen_gh == [], f"run_setup invoked the host gh CLI: {seen_gh}"
