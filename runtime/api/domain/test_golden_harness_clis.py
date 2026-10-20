"""Goldens record the harness CLI versions they restore; refreshes install newer."""

import json
import subprocess

import pytest

from yoke_harness import golden_harness_clis as clis

LATEST = {"claude-code": "2.1.300", "codex": "0.163.0", "cursor": "2026.10.16-e3cb207"}


class FakeHost:
    def __init__(self, versions, *, install_exit=0, installs_update=True):
        self.versions = dict(versions)
        self.install_exit = install_exit
        self.installs_update = installs_update
        self.files = {}
        self.commands = []
        self.contexts = []

    def run_command(self, argv, timeout, **context):
        self.commands.append(list(argv))
        self.contexts.append(context)
        if argv[4] == "probe":
            probes = {
                h: {
                    "version": v,
                    "exit_code": 0 if v else -6,
                    "stderr": "" if v else "dyld: Symbol not found",
                }
                for h, v in self.versions.items()
            }
            return subprocess.CompletedProcess(argv, 0, json.dumps(probes), "")
        harness, names, script, wanted = json.loads(argv[5])
        if self.install_exit == 0 and self.installs_update:
            self.versions[harness] = wanted
        receipt = {
            "install_exit_code": self.install_exit,
            "install_stderr": "installer error",
            "probe": {"version": self.versions[harness], "exit_code": 0, "stderr": ""},
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(receipt), "")

    def upload_remote_text(self, path, text):
        self.files[path] = text

    def read_remote_text(self, path):
        return self.files.get(path)


def test_capture_records_versions_beside_the_golden():
    host = FakeHost(LATEST)
    recorded = clis.record_golden_harness_clis(host, "/golden/testy-home-1")
    assert recorded.ok
    assert recorded.evidence["harness_cli_versions"] == LATEST
    sidecar = "/golden/testy-home-1" + clis.GOLDEN_HARNESS_CLIS_SUFFIX
    assert json.loads(host.files[sidecar]) == LATEST
    assert clis.read_golden_harness_clis(host, "/golden/testy-home-1") == LATEST


def test_probe_searches_local_bin_and_each_executable_name():
    host = FakeHost(LATEST)
    clis.probe_harness_cli_versions(host)
    argv = host.commands[0]
    assert argv[:2] == ["/usr/bin/python3", "-c"]
    assert ".local/bin" in argv[2]
    assert json.loads(argv[5]) == [
        ["claude-code", ["claude"]],
        ["codex", ["codex"]],
        ["cursor", ["agent", "cursor-agent"]],
    ]


def test_capture_refuses_a_cli_whose_version_cannot_be_read():
    host = FakeHost({**LATEST, "cursor": None})
    recorded = clis.record_golden_harness_clis(host, "/golden/home")
    assert not recorded.ok
    assert recorded.error_code == "golden_harness_cli_version_unreadable"
    assert "cursor" in recorded.evidence["recovery"]
    assert host.files == {}


def test_an_old_golden_has_no_record():
    assert clis.read_golden_harness_clis(FakeHost(LATEST), "/golden/home") is None


def test_install_runs_each_vendor_installer_with_the_latest_version():
    host = FakeHost({**LATEST, "codex": "0.149.1"})
    installed = clis.install_harness_clis(host, LATEST, ["codex"])
    assert installed.ok, installed.evidence
    install = host.commands[0]
    assert install[:2] == ["/usr/bin/python3", "-c"]
    assert "chatgpt.com/codex/install.sh" in json.loads(install[5])[2]
    assert json.loads(install[5])[3] == "0.163.0"
    assert installed.evidence["harness_cli_versions"]["codex"] == "0.163.0"


@pytest.mark.parametrize(
    "host,code",
    [
        (
            FakeHost({**LATEST, "codex": "0.149.1"}, install_exit=1),
            "harness_cli_install_failed",
        ),
        (
            FakeHost({**LATEST, "codex": "0.149.1"}, installs_update=False),
            "harness_cli_install_unverified",
        ),
    ],
)
def test_install_refuses_when_the_latest_cli_does_not_resolve(host, code):
    installed = clis.install_harness_clis(host, LATEST, ["codex"])
    assert not installed.ok
    assert installed.error_code == code
    assert installed.evidence["recovery"]


@pytest.mark.parametrize("os_name,context", [("macos", "gui"), ("linux", None)])
def test_macos_reads_versions_in_the_gui_session(os_name, context):
    # Cursor's agent refuses even --version over plain SSH on macOS while the
    # login keychain is locked to that session.
    host = FakeHost(LATEST)
    host.os = os_name
    assert {
        h: p["version"] for h, p in clis.probe_harness_cli_versions(host).items()
    } == LATEST
    assert host.contexts[0].get("required_session_context") == context
