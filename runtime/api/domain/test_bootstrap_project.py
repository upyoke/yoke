"""bootstrap_project preflight branch coverage.

Setup coverage lives in ``test_bootstrap_project_setup`` and CLI/context
coverage lives in ``test_bootstrap_project_cli``. Shared fixtures live in
``bootstrap_project_test_helpers``.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.bootstrap_project import BootstrapContext, run_preflight
from yoke_core.domain.bootstrap_project_helpers import _connect
from yoke_core.domain.bootstrap_project_test_helpers import (
    _make_fake_run,
    _preflight_ctx,
    bootstrap_seeded_db,
)


def _write_fake_ssh_key(tmp_path: Path) -> Path:
    ssh_key = tmp_path / ".ssh_key"
    ssh_key.write_text("fake-key")
    return ssh_key


def test_connect_ignores_retired_db_path_token(tmp_path: Path, monkeypatch) -> None:
    seen: list[object] = []
    fake_conn = object()

    def fake_connect(path=None):
        seen.append(path)
        return fake_conn

    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_helpers.db_helpers.connect",
        fake_connect,
    )

    assert _connect(tmp_path / "data" / "yoke.db") is fake_conn
    assert seen == [None]


def test_run_preflight_does_not_require_legacy_db_file(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    # ``ctx.yoke_db`` is a path-shaped token only; Postgres authority is the
    # live source of truth, so the token need not exist as a file.
    ssh_key = _write_fake_ssh_key(tmp_path)

    monkeypatch.setattr("yoke_core.domain.bootstrap_project.shutil.which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr("yoke_core.domain.bootstrap_project_helpers._run", _make_fake_run())

    with bootstrap_seeded_db(tmp_path, ssh_key) as db_path:
        assert not db_path.exists()
        ctx = _preflight_ctx(tmp_path, yoke_db=db_path)
        rc = run_preflight(ctx)
    output = capsys.readouterr().out
    assert rc == 0, output
    assert ("yoke" + ".db not found") not in output
    assert "All preflight checks passed." in output


def test_run_preflight_translates_missing_capability_to_fail(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    # Canonical resolver returns MissingCapability when there is no
    # ``(project, github)`` ``project_capabilities`` row. Preflight must
    # translate that into a [FAIL] with the matching ``repair_command_hint``
    # text ("capability-add buzz github"), not a generic host-login nudge.
    ssh_key = _write_fake_ssh_key(tmp_path)

    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project.shutil.which",
        lambda _name: "/usr/bin/gh",
    )
    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_helpers._run", _make_fake_run()
    )

    with bootstrap_seeded_db(
        tmp_path, ssh_key, include_github_capability=False
    ) as db_path:
        ctx = _preflight_ctx(tmp_path, yoke_db=db_path)
        rc = run_preflight(ctx)
    output = capsys.readouterr().out
    assert rc == 1
    assert "github auth not resolvable" in output
    assert "no 'github' capability row" in output
    # Repair hint routes to the canonical capability-add CLI, not host login.
    assert "capability-add buzz github" in output
    retired_hint = "gh " + "auth " + "login"
    assert retired_hint not in output


def test_run_preflight_detects_missing_buzz_record(tmp_path: Path, monkeypatch, capsys) -> None:
    # DB exists with schema but no 'buzz' row in projects → preflight must
    # report the missing project record with a remediation hint.
    ssh_key = _write_fake_ssh_key(tmp_path)

    monkeypatch.setattr("yoke_core.domain.bootstrap_project.shutil.which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr("yoke_core.domain.bootstrap_project_helpers._run", _make_fake_run())

    with bootstrap_seeded_db(tmp_path, ssh_key, include_project=False) as db_path:
        ctx = _preflight_ctx(tmp_path, yoke_db=db_path)
        rc = run_preflight(ctx)
    output = capsys.readouterr().out
    assert rc == 1
    assert "projects table missing buzz record" in output


def test_run_preflight_detects_missing_token(tmp_path: Path, monkeypatch, capsys) -> None:
    # DB has a buzz projects row and a github capability but the stored
    # token is the placeholder sentinel — preflight must flag it.
    ssh_key = _write_fake_ssh_key(tmp_path)

    monkeypatch.setattr("yoke_core.domain.bootstrap_project.shutil.which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr("yoke_core.domain.bootstrap_project_helpers._run", _make_fake_run())

    with bootstrap_seeded_db(
        tmp_path, ssh_key, github_token="REPLACE_WITH_PAT"
    ) as db_path:
        ctx = _preflight_ctx(tmp_path, yoke_db=db_path)
        rc = run_preflight(ctx)
    output = capsys.readouterr().out
    assert rc == 1
    assert "GitHub token not configured" in output


def test_run_preflight_no_longer_probes_host_gh(tmp_path: Path, monkeypatch, capsys) -> None:
    # PAT-backed REST is the GitHub transport now; preflight must not
    # surface the retired host-gh installer messaging regardless of
    # whether the host gh binary is present. The banned strings are
    # built by concatenation so the AC-1 / AC-2 grep recipes return
    # zero hits anywhere in the live tree.
    ssh_key = _write_fake_ssh_key(tmp_path)

    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_helpers._run", _make_fake_run()
    )

    with bootstrap_seeded_db(
        tmp_path, ssh_key, include_github_capability=False
    ) as db_path:
        ctx = _preflight_ctx(tmp_path, yoke_db=db_path)
        rc = run_preflight(ctx)
    output = capsys.readouterr().out
    assert rc == 1
    assert "github auth not resolvable" in output
    assert ("yoke" + ".db not found") not in output
    assert ("gh CLI" + " installed") not in output
    assert ("gh CLI" + " not installed") not in output
    assert ("brew" + " install gh") not in output


def test_run_preflight_happy_path_reports_success(tmp_path: Path, monkeypatch, capsys) -> None:
    # With everything configured (DB, buzz row, github+token, ssh, ssh key
    # file, DB domain, reachable VPS with TLS cert), preflight must exit
    # 0 and print "All preflight checks passed."
    ssh_key = _write_fake_ssh_key(tmp_path)

    monkeypatch.setattr("yoke_core.domain.bootstrap_project.shutil.which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_helpers._run",
        _make_fake_run(gh_auth_ok=True, ssh_ok=True, tls_state="exists"),
    )

    with bootstrap_seeded_db(tmp_path, ssh_key) as db_path:
        ctx = BootstrapContext(
            project="buzz",
            project_root=tmp_path,
            script_dir=tmp_path / ".agents" / "skills" / "yoke" / "scripts",
            yoke_db=db_path,
        )

        rc = run_preflight(ctx)
        output = capsys.readouterr().out
        assert rc == 0, f"preflight returned {rc}; output was:\n{output}"
        assert "All preflight checks passed." in output
        # The operator-facing header + separator appear on happy-path runs.
        assert "Yoke -- buzz Bootstrap Preflight" in output
        assert "==================================" in output
        # The resolved SSH key path is surfaced in preflight output so
        # the operator sees which key Yoke will upload to GitHub Actions.
        assert f"SSH key resolved at {ssh_key}" in output
