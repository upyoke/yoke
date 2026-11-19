"""Uninstall backups write one labeled archive per owned universe."""

import json
import subprocess
from pathlib import Path

import pytest

from yoke_cli.config import machine_uninstall_backup as backups
from yoke_cli.config.machine_uninstall_inventory import Inventory, UninstallError

_REAL_COMMAND = backups.steps.command


@pytest.fixture
def machine(tmp_path, monkeypatch):
    home = tmp_path / "machine"
    home.mkdir()
    out = tmp_path / "backups"
    out.mkdir()
    monkeypatch.chdir(out)
    value = Inventory(
        home,
        home / "config.json",
        (),
        (),
        True,
        "local",
        ((tmp_path / "server", "self-host"),),
    )
    calls = []

    def command(args, org="acme", forward_stderr=True):
        calls.append(args)
        target = Path(args[args.index("--out") + 1])
        target.write_bytes(b"archive")
        return json.dumps({"artifact": str(target), "org": org})

    monkeypatch.setattr(backups.steps, "command", command)
    return value, calls, out.resolve()


def test_each_target_gets_a_distinct_labeled_archive_named_in_its_line(machine):
    value, calls, out = machine
    output = []
    backups.back_up(value, output.append)
    assert [args[1] for args in calls] == ["local", "self-host"]
    assert all(args[2:4] == ["universe", "export"] for args in calls)
    assert all(args[-1] == "--json" for args in calls)
    local, server = (Path(args[args.index("--out") + 1]) for args in calls)
    assert local != server and local.parent == server.parent == out
    assert local.name.startswith("local-universe-")
    assert server.name.startswith("self-host-server-universe-")
    archives = sorted(out.iterdir())
    assert [p.name.split("-universe-")[0] for p in archives] == [
        "local-acme",
        "self-host-server-acme",
    ]
    assert output == [
        f"backup local universe: done ({archives[0]})",
        f"backup self-host {value.bundles[0][0]}: done ({archives[1]})",
    ]


def test_report_without_org_keeps_the_labeled_name(machine, monkeypatch):
    value, _, out = machine
    original = backups.steps.command
    monkeypatch.setattr(backups.steps, "command", lambda args, **kw: original(args, org="", **kw))
    output = []
    backups.back_up(value, output.append)
    names = sorted(p.name for p in out.iterdir())
    assert names[0].startswith("local-universe-")
    assert names[1].startswith("self-host-server-universe-")
    assert all(str(out / name) in "\n".join(output) for name in names)


def test_existing_archive_path_is_refused_by_name(machine, monkeypatch):
    value, calls, out = machine
    monkeypatch.setattr(backups, "utc_now", lambda: _Fixed())
    (out / "local-universe-20261118T192728Z.tar").write_bytes(b"older")
    output = []
    with pytest.raises(UninstallError, match="uninstall_backup_failed"):
        backups.back_up(value, output.append)
    assert "uninstall_backup_archive_exists" in output[0]
    assert [args[1] for args in calls] == ["self-host"]


def test_backup_failure_stops_destructive_removal(machine, monkeypatch):
    value, _, _ = machine
    monkeypatch.setattr(
        backups.steps,
        "command",
        lambda args, **_kw: backups.steps._fail("export refused"),
    )
    output = []
    with pytest.raises(UninstallError, match="uninstall_backup_failed"):
        backups.back_up(value, output.append)
    assert len([line for line in output if "failed" in line]) == 2


def test_backup_never_lands_inside_deleted_home(machine, monkeypatch):
    value, _, _ = machine
    monkeypatch.chdir(value.home)
    with pytest.raises(UninstallError, match="uninstall_backup_inside_home"):
        backups.back_up(value, lambda line: None)


def test_export_progress_never_prints_the_staged_path(machine, monkeypatch, capsys):
    value, _, out = machine
    monkeypatch.setattr(backups.steps, "command", _REAL_COMMAND)

    def run(argv, **_kwargs):
        staged = Path(argv[argv.index("--out") + 1])
        staged.write_bytes(b"archive")
        progress = f"[universe-export] dumping org 'acme' universe -> {staged}\n"
        report = json.dumps({"artifact": str(staged), "org": "acme"})
        return subprocess.CompletedProcess(argv, 0, report, progress)

    monkeypatch.setattr(backups.steps.subprocess, "run", run)
    output = []
    backups.back_up(value, output.append)
    printed = capsys.readouterr()
    shown = "\n".join([*output, printed.out, printed.err])
    assert "[universe-export]" not in shown
    assert "-universe-" in shown and "local-universe-" not in shown
    finals = [Path(line.rsplit("(", 1)[1].rstrip(")")) for line in output]
    assert all(path.is_file() and path.parent == out for path in finals)


def test_failed_export_still_reports_child_stderr(monkeypatch):
    def run(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 3, "", "export refused: disk full")

    monkeypatch.setattr(backups.steps.subprocess, "run", run)
    with pytest.raises(UninstallError, match="disk full"):
        _REAL_COMMAND(["universe", "export"], forward_stderr=False)


class _Fixed:
    def strftime(self, _format):
        return "20261118T192728Z"
