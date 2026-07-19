"""Bootstrap suite: GitHub App auth-only behavior and no-gh-on-laptop coverage.

Companion to ``test_bootstrap_project.py`` /
``test_bootstrap_project_setup.py``. Verifies current bootstrap behavior:

- Preflight PASSes with GitHub App auth only — no host ``gh`` probe anywhere in
  the run.
- ``run_setup`` succeeds against the bearer-token REST transport without
  calling a user-only endpoint from an installation token. Environment writes
  are skipped by default and require the optional Administration grant.
- ``run_setup`` surfaces typed REST failure modes (missing GitHub App auth, 401,
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
)
from yoke_core.domain.bootstrap_project_pack_test_helpers import (
    install_fake_pack_operations,
)
from yoke_core.domain.project_github_auth import MissingPermission, ProjectGithubAuth


def _resolved_auth(
    project: str = "externalwebapp", *, administration: bool = False,
) -> ProjectGithubAuth:
    token = "ghs_admin_token" if administration else "ghs_baseline_token"
    return ProjectGithubAuth(
        project=project,
        repo="example-org/externalwebapp",
        token=token,
        installation_id="12345",
        token_source="github_app_installation",
        permissions={"administration": "write"} if administration else {},
    )


def _patch_preflight_auth(monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_preflight.resolve_project_github_auth",
        lambda project, **_kw: _resolved_auth(project),
    )


def _patch_setup_auth(monkeypatch, *, administration: bool = False) -> None:
    def fake_resolve(project, **kwargs):
        required = dict(kwargs.get("required_permissions") or {})
        if required == {"secrets": "write"}:
            return _resolved_auth(project)
        if required:
            assert required == {"administration": "write"}
            if not administration:
                raise MissingPermission(project, "Administration: write not granted")
            return _resolved_auth(project, administration=True)
        return _resolved_auth(project)

    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_setup.resolve_project_github_auth",
        fake_resolve,
    )


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
    if cmd[:2] == ["git", "status"]:
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return subprocess.CompletedProcess(cmd, 0, "", "")


def _fake_repo_public_key_b64() -> str:
    """Generate a real ed25519 public key (base64) so PyNaCl encryption succeeds."""
    import base64
    from nacl.public import PrivateKey
    private = PrivateKey.generate()
    return base64.b64encode(bytes(private.public_key)).decode("ascii")


def _install_setup_rest(
    monkeypatch,
    authorizations: list[tuple[str, str | None]] | None = None,
) -> list[tuple[str, str]]:
    """REST fake covering public-key, secret, and optional environment calls."""
    seen: list[tuple[str, str]] = []
    public_key_b64 = _fake_repo_public_key_b64()

    def fake_urlopen(request, timeout):
        method = (getattr(request, "method", None) or request.get_method()).upper()
        path = request.full_url.split("api.github.com", 1)[-1]
        seen.append((method, path))
        if authorizations is not None:
            authorizations.append((path, request.get_header("Authorization")))
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


def test_preflight_github_app_auth_only_success_no_host_gh_probe(
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
    _patch_preflight_auth(monkeypatch)

    with bootstrap_seeded_db(tmp_path, ssh_key) as db_path:
        ctx = BootstrapContext(
            project="externalwebapp",
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
        # The canonical GitHub App auth resolution PASS line should appear instead.
        assert "github auth resolved (canonical)" in out


def test_setup_skips_optional_environment_without_administration(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """Default App permissions avoid user-only and Administration endpoints."""
    with setup_validation_ctx(tmp_path) as (ctx, _, _):
        monkeypatch.setattr(
            "yoke_core.domain.bootstrap_project_helpers._run", _no_gh_run,
        )
        _patch_setup_auth(monkeypatch)
        install_fake_pack_operations(monkeypatch)
        rest_calls = _install_setup_rest(monkeypatch)

        assert run_setup(ctx) == 0
        methods_paths = set(rest_calls)
        assert ("GET", "/user") not in methods_paths
        assert not any(
            method == "PUT" and "/environments/production" in path
            for method, path in rest_calls
        )
        out = capsys.readouterr().out
        assert "default Yoke GitHub App grant does not request Administration" in out
        assert "Settings → Environments" in out


def test_setup_creates_environment_with_optional_administration(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """An explicit Administration grant enables the environment mutation."""
    with setup_validation_ctx(tmp_path) as (ctx, _, _):
        monkeypatch.setattr(
            "yoke_core.domain.bootstrap_project_helpers._run", _no_gh_run,
        )
        _patch_setup_auth(monkeypatch, administration=True)
        install_fake_pack_operations(monkeypatch)
        authorizations: list[tuple[str, str | None]] = []
        rest_calls = _install_setup_rest(monkeypatch, authorizations)

        assert run_setup(ctx) == 0
        assert ("GET", "/user") not in set(rest_calls)
        assert any(
            method == "PUT" and "/environments/production" in path
            for method, path in rest_calls
        )
        assert all(
            auth == "Bearer ghs_baseline_token"
            for path, auth in authorizations
            if "/actions/secrets" in path
        )
        assert [
            auth for path, auth in authorizations
            if "/environments/production" in path
        ] == ["Bearer ghs_admin_token"]
        assert "Creating production environment... done" in capsys.readouterr().out


def test_setup_surfaces_401_when_github_auth_invalid(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """REST 401 surfaces via typed RestAuthError; setup returns 2 cleanly."""
    with setup_validation_ctx(tmp_path) as (ctx, _, _):
        monkeypatch.setattr(
            "yoke_core.domain.bootstrap_project_helpers._run", _no_gh_run,
        )
        _patch_setup_auth(monkeypatch, administration=True)

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
        _patch_setup_auth(monkeypatch, administration=True)
        public_key_b64 = _fake_repo_public_key_b64()

        def fake_urlopen(request, timeout):
            # Secret operations succeed; the optional environment write trips 403.
            if request.full_url.endswith("/actions/secrets/public-key"):
                return _FakeRestResponse(200, {"key_id": "kid-1", "key": public_key_b64})
            if "/actions/secrets/" in request.full_url and request.get_method() == "PUT":
                return _FakeRestResponse(204, b"")
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


def test_setup_surfaces_missing_github_app_binding(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """When the project lacks a repo binding, setup exits before REST."""
    with setup_validation_ctx(tmp_path) as (ctx, _, _):
        monkeypatch.setattr(
            "yoke_core.domain.bootstrap_project_helpers._run", _no_gh_run,
        )

        def explode_urlopen(_request, _timeout):
            raise AssertionError("REST must not be called when GitHub App auth is missing")

        monkeypatch.setattr(
            "yoke_core.domain.gh_rest_transport.urlopen", explode_urlopen,
        )

        rc = run_setup(ctx)
        err = capsys.readouterr().err
        assert rc == 2
        assert "not bound to a GitHub App repository" in err


def test_setup_emits_zero_gh_shellouts(
    tmp_path: Path, monkeypatch,
) -> None:
    """Every GitHub mutation in run_setup goes through bearer-token REST;
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
        _patch_setup_auth(monkeypatch)
        install_fake_pack_operations(monkeypatch)
        _install_setup_rest(monkeypatch)

        assert run_setup(ctx) == 0
        assert seen_gh == [], f"run_setup invoked the host gh CLI: {seen_gh}"
