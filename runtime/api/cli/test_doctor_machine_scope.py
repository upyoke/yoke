"""Doctor runs machine-scope checks outside every project and names the rest."""

import json
from pathlib import Path

import pytest

from yoke_cli.commands.adapters import doctor, doctor_install, doctor_machine_scope
from yoke_contracts.project_defaults import MissingProjectError
from yoke_core.engines import doctor_https_compose
from yoke_core.engines.doctor_applicability_declarations import machine_scope_slugs

REFUSAL = (
    "project_required: no project given — pass --project P. Accessible projects: alpha."
)


@pytest.fixture
def outside_project(monkeypatch):
    def refuse(project):
        raise MissingProjectError(REFUSAL)

    monkeypatch.setattr(doctor, "required_project_context", refuse)
    monkeypatch.setattr(doctor, "connection_failure", lambda: None)
    monkeypatch.setattr(
        doctor_https_compose, "local_connection_or_none", lambda c: None
    )


@pytest.fixture
def bare_machine(monkeypatch, tmp_path):
    """A machine with Claude Code installed but no Yoke setup in its home."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    from yoke_contracts import global_skill_install
    from yoke_contracts.harness_machine_hooks import HarnessMachineHooks
    from yoke_harness import harness_setup_reconcile as setup

    dirs = {"codex": ".codex", "claude-code": ".claude", "cursor": ".cursor"}
    monkeypatch.setattr(
        HarnessMachineHooks,
        "home_path",
        lambda self, environ=None: home / dirs[self.harness_id],
    )
    monkeypatch.setattr(global_skill_install, "user_home", lambda environ=None: home)
    monkeypatch.setattr(setup, "all_registered_checkouts", lambda **kw: [])
    from yoke_core.engines import doctor_hc_harness_setup

    monkeypatch.setattr(doctor_hc_harness_setup, "read_reconcile_state", lambda: {})
    monkeypatch.setattr(
        doctor_hc_harness_setup, "remember_reconcile_result", lambda result: None
    )
    return home


def test_harness_setup_fix_repairs_machine_setup_outside_a_project(
    outside_project, bare_machine, capsys
):
    assert doctor.doctor_run(["--only", "harness-setup", "--json"]) == 1
    capsys.readouterr()

    assert doctor.doctor_run(["--only", "harness-setup", "--fix", "--json"]) == 0

    envelope = json.loads(capsys.readouterr().out)
    [row] = envelope["result"]["results"]
    assert row["severity"] == "PASS"
    assert (bare_machine / ".claude/skills/yoke-global/SKILL.md").is_file()
    settings = (bare_machine / ".claude/settings.json").read_text()
    assert "yoke hook evaluate" in settings


def test_project_scope_checks_outside_a_project_are_named_skips(
    outside_project, monkeypatch, capsys
):
    ran = []

    def run_local(*, project, quick, fix, slugs):
        ran.append(list(slugs))
        return [
            {"hc": "harness-setup", "name": "setup", "severity": "PASS", "detail": ""}
        ]

    monkeypatch.setattr(doctor_https_compose, "run_local_runtime_checks", run_local)

    code = doctor.doctor_run(["--only", "harness-setup,HC-project-gh-auth", "--json"])

    assert code == 0 and ran == [["harness-setup"]]
    rows = json.loads(capsys.readouterr().out)["result"]["results"]
    skipped = [row for row in rows if row["hc"] == "HC-project-gh-auth"]
    assert skipped and skipped[0]["severity"] == "N/A"
    assert skipped[0]["detail"] == doctor_machine_scope.PROJECT_SKIP_DETAIL


def test_only_project_scope_checks_refuse_and_name_them(outside_project, capsys):
    assert doctor.doctor_run(["--only", "project-gh-auth"]) == 2
    err = capsys.readouterr().err
    assert REFUSAL in err and "project-gh-auth" in err


def test_full_outside_a_project_runs_machine_checks_and_names_project_checks(
    outside_project, monkeypatch, capsys
):
    ran = []

    def run_local(*, project, quick, fix, slugs):
        ran.extend(slugs)
        return []

    monkeypatch.setattr(doctor_https_compose, "run_local_runtime_checks", run_local)

    assert doctor.doctor_run(["--full", "--json"]) == 0

    assert set(ran) == machine_scope_slugs()
    rows = json.loads(capsys.readouterr().out)["result"]["results"]
    assert [row["hc"] for row in rows] == ["HC-project-checks"]


def test_machine_scope_excludes_checks_that_read_a_project():
    machine = machine_scope_slugs()
    assert {"harness-setup", "machine-hooks", "connections"} <= machine
    assert not {"project-gh-auth", "installed-guidance", "install-residue"} & machine


def test_setup_readiness_without_a_project_names_project_install_checks(
    monkeypatch,
):
    def run_local(*, project, quick, fix, slugs):
        return [
            {"hc": slug, "name": slug, "severity": "PASS", "detail": ""}
            for slug in slugs
        ]

    monkeypatch.setattr(doctor_https_compose, "run_local_runtime_checks", run_local)

    result = doctor_install.setup_readiness({}, {})

    assert result["ready"]
    skipped = {row["hc"] for row in result["results"] if row["severity"] == "N/A"}
    assert skipped == {
        f"HC-{slug}"
        for slug in doctor_install.install_slugs()
        if slug not in machine_scope_slugs()
    }
