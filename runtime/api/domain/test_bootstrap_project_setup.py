"""bootstrap_project — load_setup_config + run_setup coverage.

Split out of ``test_bootstrap_project.py`` to keep authored files under the
350-line limit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_SECRETS_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain.bootstrap_project import (
    BootstrapContext,
    _load_setup_config,
    run_setup,
)
from yoke_core.domain.bootstrap_project_test_helpers import (
    _install_fake_rest,
    bootstrap_seeded_db,
    install_fake_project_github_auth,
    register_bootstrap_backend_checkout,
    write_fake_rendered_workflows,
)


def test_load_setup_config_prefers_env_key_path(tmp_path: Path, monkeypatch) -> None:
    db_key = tmp_path / ".db-key"
    db_key.write_text("db-secret")
    env_key = tmp_path / ".env-key"
    env_key.write_text("secret")
    monkeypatch.setenv("EXTERNALWEBAPP_SSH_KEY_PATH", str(env_key))
    repo_path = tmp_path / "externalwebapp-repo"
    repo_path.mkdir()

    with bootstrap_seeded_db(tmp_path, db_key) as db_path:
        register_bootstrap_backend_checkout(db_path, repo_path)
        ctx = BootstrapContext(
            project="externalwebapp",
            project_root=tmp_path,
            script_dir=tmp_path,
            yoke_db=db_path,
        )
        cfg = _load_setup_config(ctx)

    # Resolves to the registered machine-local checkout, never the cwd.
    assert cfg.repo_path == repo_path
    assert cfg.display_name == "ExternalWebapp"
    assert cfg.ssh_key_path == env_key


def test_load_setup_config_refuses_cwd_fallback_when_unmapped(
    tmp_path: Path, monkeypatch
) -> None:
    """A project with no machine-local checkout mapping must NOT silently
    resolve to the current directory (which used to let setup render workflow
    files into whatever unrelated checkout the process ran from)."""
    import pytest

    db_key = tmp_path / ".db-key"
    db_key.write_text("db-secret")
    empty_config = tmp_path / "machine-config" / "config.json"
    empty_config.parent.mkdir(parents=True)
    empty_config.write_text('{"projects": []}')
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(empty_config))

    with bootstrap_seeded_db(tmp_path, db_key) as db_path:
        ctx = BootstrapContext(
            project="externalwebapp",
            project_root=tmp_path,
            script_dir=tmp_path,
            yoke_db=db_path,
        )
        with pytest.raises(FileNotFoundError, match="no machine-local checkout mapping"):
            _load_setup_config(ctx)


def test_run_setup_resolves_auth_with_active_connection(
    tmp_path: Path, monkeypatch
) -> None:
    ssh_key = tmp_path / ".ssh_key"
    ssh_key.write_text("fake-ssh-key")
    repo_path = tmp_path / "externalwebapp-repo"
    repo_path.mkdir()
    seen: dict[str, object] = {}

    class Resolved:
        repo = "example-org/externalwebapp"
        token = "ghs_fake_token_123"
        installation_id = "12345"

    def fake_resolve(
        project, *, db_path=None, conn=None, required_permissions=None,
    ):
        seen["project"] = project
        seen["db_path"] = db_path
        seen["conn"] = conn
        seen["required_permissions"] = required_permissions
        return Resolved()

    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_setup.resolve_project_github_auth",
        fake_resolve,
    )

    with bootstrap_seeded_db(tmp_path, ssh_key) as db_path:
        register_bootstrap_backend_checkout(db_path, repo_path)
        ctx = BootstrapContext(
            project="externalwebapp",
            project_root=tmp_path,
            script_dir=tmp_path,
            yoke_db=db_path,
        )

        rc = run_setup(ctx)

    assert rc == 2
    assert seen["project"] == "externalwebapp"
    assert seen["db_path"] is None
    assert seen["conn"] is not None
    assert seen["required_permissions"] is GITHUB_SECRETS_WRITE_PERMISSION_LEVELS


def test_run_setup_copies_workflows_and_pushes(tmp_path: Path, monkeypatch, capsys) -> None:
    # bootstrap_project.run_setup invokes the Python render CLI directly.

    repo_path = tmp_path / "externalwebapp-repo"
    repo_path.mkdir()
    ssh_key = tmp_path / ".ssh_key"
    ssh_key.write_text("fake-ssh-key")

    def fake_run(cmd, *, stdin=None, cwd=None, env=None):
        # Every GitHub interaction routes through bearer-token REST — the
        # host gh CLI is never invoked.
        if cmd and cmd[0] == "gh":
            raise AssertionError(f"unexpected gh shell-out: {cmd}")
        if len(cmd) >= 3 and cmd[1:3] == ["-m", "yoke_core.tools.render_project"]:
            write_fake_rendered_workflows(cmd)
            return subprocess.CompletedProcess(cmd, 0, "rendered\n", "")
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(cmd, 0, " M .github/workflows/externalwebapp-deploy.yml\n", "")
        if cmd[:2] == ["git", "add"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:2] == ["git", "commit"]:
            return subprocess.CompletedProcess(cmd, 0, "[main abc123] commit\n", "")
        if cmd[:3] == ["git", "push", "origin"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:2] == ["ssh-keygen", "-y"]:
            return subprocess.CompletedProcess(cmd, 0, "ssh-rsa AAAA fake\n", "")
        if cmd and cmd[0] == "ssh":
            # auth probe ends with literal "true"; TLS probe ends with the test pipeline
            if cmd[-1] == "true":
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0, "exists\n", "")
        raise AssertionError(f"Unexpected command: {cmd}")

    with bootstrap_seeded_db(tmp_path, ssh_key) as db_path:
        register_bootstrap_backend_checkout(db_path, repo_path)

        ctx = BootstrapContext(
            project="externalwebapp",
            project_root=tmp_path,
            script_dir=tmp_path / ".agents" / "skills" / "yoke" / "scripts",
            yoke_db=db_path,
        )

        monkeypatch.setattr("yoke_core.domain.bootstrap_project_helpers._run", fake_run)
        install_fake_project_github_auth(monkeypatch)
        rest_calls = _install_fake_rest(monkeypatch)

        assert run_setup(ctx) == 0
        assert (repo_path / ".github" / "workflows" / "externalwebapp-deploy.yml").read_text() == "name: ExternalWebapp Deploy\n"
        assert (repo_path / ".github" / "workflows" / "externalwebapp-smoke.yml").read_text() == "name: ExternalWebapp Smoke Test\n"
        output = capsys.readouterr().out
        assert "Step 2: Creating GitHub Secrets" in output
        assert "Push successful" in output
        # The installation token never calls the user-only endpoint, and the
        # least-privilege default skips optional environment administration.
        methods_paths = {(m, p) for m, p in rest_calls}
        assert ("GET", "/user") not in methods_paths
        assert not any(
            m == "PUT" and "/environments/production" in p for m, p in rest_calls
        )
        assert "default Yoke GitHub App grant does not request Administration" in output


def test_run_setup_prints_tls_instructions_when_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    repo_path = tmp_path / "externalwebapp-repo"
    repo_path.mkdir()
    ssh_key = tmp_path / ".ssh_key"
    ssh_key.write_text("fake-ssh-key")

    def fake_run(cmd, *, stdin=None, cwd=None, env=None):
        # Every GitHub interaction routes through bearer-token REST — the
        # host gh CLI is never invoked.
        if cmd and cmd[0] == "gh":
            raise AssertionError(f"unexpected gh shell-out: {cmd}")
        if len(cmd) >= 3 and cmd[1:3] == ["-m", "yoke_core.tools.render_project"]:
            write_fake_rendered_workflows(cmd)
            return subprocess.CompletedProcess(cmd, 0, "rendered\n", "")
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:2] == ["ssh-keygen", "-y"]:
            return subprocess.CompletedProcess(cmd, 0, "ssh-rsa AAAA fake\n", "")
        if cmd and cmd[0] == "ssh":
            if cmd[-1] == "true":
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0, "missing\n", "")
        raise AssertionError(f"Unexpected command: {cmd}")

    with bootstrap_seeded_db(tmp_path, ssh_key) as db_path:
        register_bootstrap_backend_checkout(db_path, repo_path)

        ctx = BootstrapContext(
            project="externalwebapp",
            project_root=tmp_path,
            script_dir=tmp_path / ".agents" / "skills" / "yoke" / "scripts",
            yoke_db=db_path,
        )

        monkeypatch.setattr("yoke_core.domain.bootstrap_project_helpers._run", fake_run)
        install_fake_project_github_auth(monkeypatch)
        _install_fake_rest(monkeypatch)

        assert run_setup(ctx) == 0
        output = capsys.readouterr().out
        assert "Wildcard TLS certificate needed" in output
        # The TLS guidance references provision-tls.sh in the scratch-backed
        # rendered output location.
        assert "provision-tls.sh" in output
        # And the guidance must name the new Python render CLI before the scp step.
        assert "python3 -m yoke_core.tools.render_project" in output
