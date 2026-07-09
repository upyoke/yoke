"""bootstrap_project setup validation coverage."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from yoke_core.domain.bootstrap_project import (
    BootstrapContext,
    _load_setup_config,
    run_setup,
)
from yoke_core.domain.bootstrap_project_helpers import SshKeyResolutionError
from yoke_core.domain.bootstrap_project_test_helpers import (
    _install_fake_rest,
    bootstrap_seeded_db,
    install_fake_project_github_auth,
    setup_validation_ctx,
    update_bootstrap_backend_ssh_settings,
    write_fake_rendered_workflows,
)
from runtime.api.fixtures.file_test_db import connect_test_db


def test_load_setup_config_prefers_db_key_path_when_env_unset(
    tmp_path: Path, monkeypatch
) -> None:
    db_key = tmp_path / ".db-key"
    db_key.write_text("from-db")
    monkeypatch.delenv("BUZZ_SSH_KEY_PATH", raising=False)

    with bootstrap_seeded_db(tmp_path, db_key) as db_path:
        ctx = BootstrapContext(
            project="buzz",
            project_root=tmp_path,
            script_dir=tmp_path,
            yoke_db=db_path,
        )
        cfg = _load_setup_config(ctx)
    assert cfg.ssh_key_path == db_key


def test_load_setup_config_raises_when_env_and_db_both_missing(
    tmp_path: Path, monkeypatch
) -> None:
    placeholder = tmp_path / ".placeholder-key"
    monkeypatch.delenv("BUZZ_SSH_KEY_PATH", raising=False)

    with bootstrap_seeded_db(tmp_path, placeholder) as db_path:
        update_bootstrap_backend_ssh_settings(
            db_path, json.dumps({"host": "h", "user": "u"})
        )
        ctx = BootstrapContext(
            project="buzz",
            project_root=tmp_path,
            script_dir=tmp_path,
            yoke_db=db_path,
        )
        with pytest.raises(SshKeyResolutionError) as exc_info:
            _load_setup_config(ctx)
    assert "BUZZ_SSH_KEY_PATH" in str(exc_info.value)
    assert "project_capabilities.ssh" in str(exc_info.value)


@pytest.mark.parametrize(
    "mode,keygen_rc,keygen_err,probe_rc,probe_err,expected_msgs",
    [
        (
            "unparseable_key",
            1,
            "invalid format",
            0,
            "",
            ["did not parse", "invalid format"],
        ),
        (
            "vps_probe_failure",
            0,
            "ssh-rsa AAA",
            255,
            "Permission denied (publickey).",
            ["SSH probe to openclaw@45.55.157.144", "Permission denied"],
        ),
    ],
)
def test_run_setup_aborts_before_upload(
    tmp_path: Path,
    monkeypatch,
    capsys,
    mode,
    keygen_rc,
    keygen_err,
    probe_rc,
    probe_err,
    expected_msgs,
) -> None:
    with setup_validation_ctx(tmp_path) as (ctx, _, _):
        gh_calls: list[list[str]] = []

        def fake_run(cmd, *, stdin=None, cwd=None, env=None):
            if cmd[:2] == ["ssh-keygen", "-y"]:
                return subprocess.CompletedProcess(cmd, keygen_rc, "", keygen_err)
            if cmd and cmd[0] == "ssh" and cmd[-1] == "true":
                return subprocess.CompletedProcess(cmd, probe_rc, "", probe_err)
            if cmd and cmd[0] == "gh" and cmd[:3] == ["gh", "secret", "set"]:
                gh_calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(
            "yoke_core.domain.bootstrap_project_helpers._run", fake_run
        )
        install_fake_project_github_auth(monkeypatch)
        rc = run_setup(ctx)
        err = capsys.readouterr().err
        assert rc == 2, f"mode={mode}: expected rc=2, got {rc}; stderr was:\n{err}"
        for expected in expected_msgs:
            assert expected in err, f"mode={mode}: missing {expected!r} in stderr:\n{err}"
        assert gh_calls == [], f"mode={mode}: secret was uploaded before validation"


def test_run_setup_persists_key_path_back_to_db(tmp_path: Path, monkeypatch) -> None:
    env_key = tmp_path / "env-override-key"
    env_key.write_text("env-secret")
    monkeypatch.setenv("BUZZ_SSH_KEY_PATH", str(env_key))

    def fake_run(cmd, *, stdin=None, cwd=None, env=None):
        if cmd[:2] == ["ssh-keygen", "-y"]:
            return subprocess.CompletedProcess(cmd, 0, "ssh-rsa AAA\n", "")
        if cmd and cmd[0] == "ssh":
            return subprocess.CompletedProcess(
                cmd, 0, "" if cmd[-1] == "true" else "exists\n", ""
            )
        if len(cmd) >= 3 and cmd[1:3] == ["-m", "yoke_core.tools.render_project"]:
            write_fake_rendered_workflows(cmd)
            return subprocess.CompletedProcess(cmd, 0, "rendered\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with setup_validation_ctx(tmp_path) as (ctx, db_path, _):
        monkeypatch.setattr(
            "yoke_core.domain.bootstrap_project_helpers._run", fake_run
        )
        install_fake_project_github_auth(monkeypatch)
        _install_fake_rest(monkeypatch)
        assert run_setup(ctx) == 0

        # _persist_resolved_ssh_key_path writes the merged settings through
        # cmd_capability_merge_settings -> db_helpers.connect, i.e. the
        # per-test database on Postgres. connect_test_db targets that same DB
        # so the read-back is visible on both backends.
        conn = connect_test_db(db_path)
        try:
            row = conn.execute(
                "SELECT settings FROM project_capabilities "
                "WHERE project_id=(SELECT id FROM projects WHERE slug='buzz') "
                "AND type='ssh'"
            ).fetchone()
        finally:
            conn.close()
    settings = json.loads(row[0])
    # env-var override wins over DB; host/user survive the merge.
    assert settings["key_path"] == str(env_key)
    assert settings["host"] == "45.55.157.144"
    assert settings["user"] == "openclaw"
