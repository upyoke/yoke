"""bootstrap_project preflight SSH key-path coverage."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain.bootstrap_project import BootstrapContext, run_preflight
from yoke_core.domain.bootstrap_project_test_helpers import (
    _make_fake_run,
    bootstrap_seeded_db,
    update_bootstrap_backend_ssh_settings,
)


def test_run_preflight_no_ssh_key_path_uses_canonical_repair_hint(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    placeholder = tmp_path / ".placeholder-key"
    monkeypatch.delenv("EXT_SSH_KEY_PATH", raising=False)

    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project.shutil.which", lambda _name: "/usr/bin/gh"
    )
    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_helpers._run", _make_fake_run()
    )

    with bootstrap_seeded_db(tmp_path, placeholder) as db_path:
        update_bootstrap_backend_ssh_settings(
            db_path, json.dumps({"host": "h", "user": "u"})
        )
        ctx = BootstrapContext(
            project="externalwebapp",
            project_root=tmp_path,
            script_dir=tmp_path / ".agents" / "skills" / "yoke" / "scripts",
            yoke_db=db_path,
        )
        rc = run_preflight(ctx)
    output = capsys.readouterr().out
    assert rc == 1
    assert "No SSH key path configured" in output
    assert "capability-merge-settings externalwebapp ssh" in output
    assert "UPDATE project_capabilities SET config" not in output


def test_run_preflight_ssh_failure_blocks_setup_path(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    ssh_key = tmp_path / ".ssh_key"
    ssh_key.write_text("fake-key")

    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project.shutil.which", lambda _name: "/usr/bin/gh"
    )
    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_helpers._run",
        _make_fake_run(ssh_ok=False, tls_state="missing"),
    )

    with bootstrap_seeded_db(tmp_path, ssh_key) as db_path:
        ctx = BootstrapContext(
            project="externalwebapp",
            project_root=tmp_path,
            script_dir=tmp_path / ".agents" / "skills" / "yoke" / "scripts",
            yoke_db=db_path,
        )
        rc = run_preflight(ctx)
    output = capsys.readouterr().out
    assert rc == 1
    assert "Cannot SSH to openclaw@45.55.157.144" in output
    assert "UPDATE project_capabilities SET config" not in output
    if "SSH key not found" in output or "No SSH key path configured" in output:
        assert "capability-merge-settings" in output
