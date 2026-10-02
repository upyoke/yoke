"""Capture defaults prove usable sessions before a baseline can be registered."""

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_harness.standard_baseline_probes import (
    CHECKLIST,
    capture_probes_document,
    standard_probes,
)
from yoke_harness.ssh_linux_baseline import capture_linux_golden
from yoke_harness.ssh_mac_golden_capture import capture_golden_baseline


@pytest.mark.parametrize("os_name,count", [("macos", 6), ("linux", 5), ("windows", 4)])
def test_defaults_and_supplied_names_cannot_weaken_the_standard_set(os_name, count):
    document, refusal = capture_probes_document(os_name, None)
    assert refusal is None
    standard = json.loads(document)["probes"]
    assert len(standard) == count
    weakened = [{"name": p["name"], "argv": ["/bin/true"]} for p in standard]
    weakened.append({"name": "extra service", "argv": ["/bin/false"]})
    document, refusal = capture_probes_document(
        os_name, json.dumps({"probes": weakened})
    )
    assert refusal is None
    assert json.loads(document)["probes"] == [*standard, weakened[-1]]


@pytest.mark.parametrize("os_name", ["macos", "linux", "windows"])
def test_missing_checks_refuse_by_name(os_name):
    probes = standard_probes(os_name)
    document, refusal = capture_probes_document(
        os_name, json.dumps({"probes": probes[1:]})
    )
    assert document is None
    assert refusal.error_code == "baseline_standard_probes_missing"
    assert refusal.evidence["missing_probes"] == ["Claude real request"]
    assert CHECKLIST in refusal.evidence["recovery"]


def _run_probe(probe, tmp_path):
    return subprocess.run(
        [sys.executable, *probe["argv"][1:]],
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "PATH": str(tmp_path / ".local/bin"),
            "CLAUDE_CONFIG_DIR": str(tmp_path / ".claude"),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.mark.parametrize(
    "name,executable", [("Claude", "claude"), ("Codex", "codex"), ("Cursor", "agent")]
)
@pytest.mark.parametrize("answer", ["OK", "Logged in", "private-account@example.com"])
def test_sealed_request_program_checks_native_completion_without_leaking_output(
    tmp_path, name, executable, answer
):
    path = tmp_path / ".local/bin" / executable
    path.parent.mkdir(parents=True)
    events = (
        [
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": answer},
            },
            {"type": "turn.completed"},
        ]
        if name == "Codex"
        else [{"type": "result", "subtype": "success", "result": answer}]
    )
    output = "\n".join(json.dumps(event) for event in events)
    path.write_text(f"#!{sys.executable}\nprint({output!r})\n")
    path.chmod(0o700)
    probe = next(
        p for p in standard_probes("linux") if p["name"] == f"{name} real request"
    )
    result = _run_probe(probe, tmp_path)
    assert (result.returncode == 0) == (answer == "OK"), result.stderr
    assert result.stdout == result.stderr == ""


@pytest.mark.parametrize("setting", [None, False, "true", True])
def test_bypass_acceptance_is_read_without_setting_it(tmp_path, setting):
    config = tmp_path / ".claude/settings.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"skipDangerousModePermissionPrompt": setting}))
    before = config.read_bytes()
    probe = next(
        p for p in standard_probes("linux") if p["name"] == "Claude bypass accepted"
    )
    result = _run_probe(probe, tmp_path)
    assert (result.returncode == 0) == (setting is True)
    assert config.read_bytes() == before


@pytest.mark.parametrize("readable", [True, False])
def test_keychain_probe_discards_the_credential_and_uses_login_keychain(
    monkeypatch, capsys, readable
):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(
            returncode=0 if readable else 1,
            stdout=b"private-credential",
            stderr=b"private-account",
        )

    monkeypatch.setattr(subprocess, "run", run)
    probe = next(
        p
        for p in standard_probes("macos")
        if p["name"] == "macOS login keychain readable"
    )
    with pytest.raises(SystemExit) as exit_info:
        exec(compile(probe["argv"][2], "keychain-probe", "exec"), {})
    assert exit_info.value.code == (0 if readable else 1)
    assert calls[0][0][0] == "/usr/bin/security"
    assert calls[0][0][-1].endswith("Library/Keychains/login.keychain-db")
    assert calls[0][1]["capture_output"] is True
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "desktop,input_tool,passes",
    [(False, False, True), (True, False, False), (True, True, True)],
)
def test_linux_input_check_distinguishes_headless_and_desktop(
    monkeypatch, desktop, input_tool, passes
):
    import pathlib
    import shutil

    monkeypatch.setattr(
        pathlib.Path, "glob", lambda *a: iter(["xfce.desktop"] if desktop else [])
    )
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: "/usr/bin/xdotool" if name == "xdotool" and input_tool else None,
    )
    probe = next(
        p
        for p in standard_probes("linux")
        if p["name"] == "Linux desktop input available"
    )
    with pytest.raises(SystemExit) as exit_info:
        exec(compile(probe["argv"][2], "desktop-input-probe", "exec"), {})
    assert exit_info.value.code == (0 if passes else 1)


@pytest.mark.parametrize("os_name", ["macos", "linux", "windows"])
@pytest.mark.parametrize("failure_index", range(6))
def test_default_capture_stops_before_archive_on_each_failed_standard_check(
    os_name, failure_index
):
    probes = standard_probes(os_name)
    if failure_index >= len(probes):
        return
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(
            returncode=int(len(calls) - 1 == failure_index), stdout="", stderr=""
        )

    # Archive/upload methods deliberately absent: failure must precede them.
    control = SimpleNamespace(os=os_name, run_command=run)
    result = (
        capture_golden_baseline(control, destination="/srv/golden")
        if os_name == "macos"
        else capture_linux_golden(control, "/srv/golden", None)
    )
    assert not result.ok
    evidence = (
        result.evidence["user_equivalence"] if os_name == "macos" else result.evidence
    )
    assert evidence["probes"][-1]["name"] == probes[failure_index]["name"]
    assert CHECKLIST in evidence["recovery"]
    assert len(calls) == failure_index + 1
    if os_name == "macos":
        assert all(kwargs["required_session_context"] == "gui" for _, kwargs in calls)


@pytest.mark.parametrize("os_name", ["macos", "linux", "windows"])
def test_success_seals_exactly_the_proven_default_document(monkeypatch, os_name):
    from yoke_harness import ssh_linux_baseline, ssh_mac_golden_capture
    from yoke_harness.test_machine_types import HostActionResult

    sealed = {}
    control = SimpleNamespace(
        os=os_name,
        home="/Users/tester" if os_name == "macos" else "/home/tester",
        path_state=None,
        run_remote_command=None,
        run_command=lambda *a, **kw: SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
        upload_remote_text=lambda path, content: sealed.update(
            path=path, content=content
        ),
    )

    def mac_archive(**kwargs):
        sealed.update(content=kwargs["probes_document"])
        return HostActionResult(True, {})

    monkeypatch.setattr(ssh_mac_golden_capture, "execute_golden_capture", mac_archive)
    monkeypatch.setattr(
        ssh_linux_baseline, "archive_operation", lambda *a: HostActionResult(True, {})
    )
    result = (
        capture_golden_baseline(control, destination="/srv/golden")
        if os_name == "macos"
        else capture_linux_golden(control, "/srv/golden", None)
    )
    assert result.ok
    assert json.loads(sealed["content"])["probes"] == standard_probes(os_name)
    assert len(result.evidence["user_equivalence"]["probes"]) == len(
        standard_probes(os_name)
    )


@pytest.mark.parametrize("survives_reset", [True, False])
def test_linux_input_probe_is_replayed_after_the_captured_home_is_reset(
    monkeypatch, survives_reset
):
    import pathlib
    import shutil
    from yoke_harness import ssh_linux_baseline
    from yoke_harness.ssh_host_baselines import SshHostBaselines
    from yoke_harness.ssh_linux_host_operations import SshLinuxHostOperations
    from yoke_harness.test_machine_types import HostActionResult

    state = {"input_present": True, "document": None, "reset": False}
    input_calls = []
    monkeypatch.setattr(pathlib.Path, "glob", lambda *a: iter(["xfce.desktop"]))
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: (
            "/usr/bin/xdotool" if name == "xdotool" and state["input_present"] else None
        ),
    )
    monkeypatch.setattr(
        ssh_linux_baseline, "archive_operation", lambda *a: HostActionResult(True, {})
    )
    program = next(
        p["argv"][2]
        for p in standard_probes("linux")
        if p["name"] == "Linux desktop input available"
    )

    class Control(SshHostBaselines):
        os = "linux"
        golden_baseline_path = "/srv/golden"

        def upload_remote_text(self, path, content):
            assert path == self.golden_baseline_path + ".probes"
            state["document"] = content

        def read_remote_text(self, path):
            assert path == self.golden_baseline_path + ".probes"
            return state["document"]

        def run_command(self, argv, **kwargs):
            code = 0
            if argv[2] == program:
                input_calls.append(state["reset"])
                with pytest.raises(SystemExit) as exit_info:
                    exec(compile(argv[2], "desktop-input-probe", "exec"), {})
                code = exit_info.value.code
            return SimpleNamespace(returncode=code, stdout="", stderr="")

        def reset_installer_test_host(self):
            state.update(reset=True, input_present=survives_reset)
            return HostActionResult(True, {"home_restored": True})

        def prove_user_equivalent(self):
            return SshLinuxHostOperations.prove_user_equivalent(self)

    control = Control()
    captured = capture_linux_golden(control, control.golden_baseline_path, None)
    assert captured.ok
    restored = control.reach_baseline("fresh-host")
    assert restored.ok is survives_reset
    assert input_calls == [False, True]
    proof = restored.evidence["user_equivalence"]
    assert proof["probes"][-1]["name"] == "Linux desktop input available"
    if not survives_reset:
        assert restored.error_code == "baseline_probe_failed"
        assert "baseline package" in proof["recovery"]
        assert "reset roundtrip" in proof["recovery"]
