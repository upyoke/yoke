"""Reset runs the controller's current standard probes, not a golden's stale ones."""

from __future__ import annotations

import json
from types import SimpleNamespace

from yoke_contracts.ssh_mac_full_reset_contract import GOLDEN_PROBES_SUFFIX
from yoke_harness.ssh_mac_baseline_probes import prove_declared_probes
from yoke_harness.standard_baseline_probes import (
    current_standard_document,
    standard_probes,
)

_DESKTOP = "Claude desktop signed in"
_EXTRA = {"name": "operator check", "argv": ["/usr/bin/true"]}


class _Host:
    """A Mac host whose golden carries one sealed probe document."""

    def __init__(self, document: str) -> None:
        self.golden_baseline_path = "/Users/Shared/golden/home"
        self.document = document
        self.ran: list[list[str]] = []

    def read_remote_text(self, path: str) -> str | None:
        assert path == self.golden_baseline_path + GOLDEN_PROBES_SUFFIX
        return self.document

    def run_command(self, argv, *, required_session_context=None, timeout=60):
        self.ran.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def _sealed_by_older_controller() -> str:
    probes = standard_probes("macos")
    for probe in probes:
        if probe["name"] == _DESKTOP:
            probe["argv"] = [*probe["argv"][:2], "import sys; sys.exit(15)"]
    return json.dumps({"probes": [*probes, _EXTRA]})


def test_reset_runs_current_standard_probes_over_older_sealed_ones() -> None:
    host = _Host(_sealed_by_older_controller())

    proven = prove_declared_probes(host)

    current = {p["name"]: p["argv"] for p in standard_probes("macos")}
    assert proven.ok, proven.evidence
    assert host.ran[: len(current)] == list(current.values())
    assert "import sys; sys.exit(15)" not in json.dumps(host.ran)
    # Sealed extra probes still run, after the current standard set.
    assert host.ran[len(current):] == [_EXTRA["argv"]]
    assert [row["name"] for row in proven.evidence["probes"]] == [
        *current,
        _EXTRA["name"],
    ]
    digests = proven.evidence["standard_probes"]
    assert digests["refreshed"] is True
    assert digests["sealed_sha256"] != digests["current_sha256"]
    assert len(digests["sealed_sha256"]) == len(digests["current_sha256"]) == 64


def test_current_sealed_document_runs_unchanged_with_matching_digests() -> None:
    document = json.dumps({"probes": [*standard_probes("macos"), _EXTRA]})

    refreshed, digests = current_standard_document("macos", document)

    assert refreshed == document
    assert digests["refreshed"] is False
    assert digests["sealed_sha256"] == digests["current_sha256"]


def test_refresh_keeps_the_interpreter_capture_resolved_on_the_host() -> None:
    python = r"C:\Python313\python.exe"
    sealed = standard_probes("windows")
    for probe in sealed:
        probe["argv"] = [python, probe["argv"][1], "old program"]

    refreshed, digests = current_standard_document(
        "windows", json.dumps({"probes": sealed})
    )

    assert digests["refreshed"] is True
    probes = json.loads(refreshed)["probes"]
    assert {p["argv"][0] for p in probes} == {python}
    assert "old program" not in refreshed
