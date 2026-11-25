"""VS Code reports the CLI bundled by each extension."""

import os
from pathlib import Path
import subprocess

import pytest

from yoke_contracts.harness_cli_manifest import VSCODE_CLI_BY_SURFACE
from yoke_contracts.path_harness_clis import resolve_native_cli_source
from yoke_contracts.testing.real_home_isolation import set_home
from yoke_harness import session_relay_inventory as inventory
from yoke_harness import session_relay_surface_probe_cache as cache
from yoke_harness import session_relay_surface_probes as probes
from yoke_harness.hooks.identity_observed import client_executor_version


def test_vscode_surfaces_are_declared() -> None:
    assert {"claude-vscode", "codex-vscode"} <= set(probes.KNOWN_SURFACE_PROBES)
    assert "cursor-vscode" not in probes.KNOWN_SURFACE_PROBES


def _bundled_cli(home: Path, surface: str, version: str, *, remote=False) -> Path:
    patterns = VSCODE_CLI_BY_SURFACE[surface].vscode_binaries_for_platform()
    pattern = patterns[int(remote)]
    relative = pattern.removeprefix("~/").replace("{version}*", f"{version}-host")
    codex_platform = "windows-x86_64" if os.name == "nt" else "macos-aarch64"
    binary = home / relative.replace("/bin/*/", f"/bin/{codex_platform}/")
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"fake executable")
    binary.chmod(0o700)
    return binary


def _inject_runner(monkeypatch, runner) -> None:
    probe_cli_surface = probes.probe_cli_surface

    def run(surface, command, **kwargs):
        return probe_cli_surface(surface, command, runner=runner, **kwargs)

    monkeypatch.setattr(probes, "probe_cli_surface", run)


@pytest.mark.parametrize(
    ("surface", "older", "newer", "output", "expected"),
    [
        ("claude-vscode", "2.1.329", "2.1.331", "2.1.331 (Claude Code)", "2.1.331"),
        ("codex-vscode", "26.1120.41243", "26.1120.50957",
         "codex-cli 0.161.0-alpha.1", "0.161.0-alpha.1"),
    ],
)
@pytest.mark.parametrize("remote", [False, True])
def test_probes_newest_extension_across_hosts(
    monkeypatch, tmp_path, surface, older, newer, output, expected, remote,
):
    set_home(monkeypatch, tmp_path)
    _bundled_cli(tmp_path, surface, older, remote=remote)
    _bundled_cli(tmp_path, surface, older, remote=not remote)
    binary = _bundled_cli(tmp_path, surface, newer, remote=remote)
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    _inject_runner(monkeypatch, runner)
    result = probes.probe_surface(surface)

    assert (result.verdict, result.version, result.source) == ("ok", expected, "exec")
    assert calls == [[str(binary), "--version"]]


@pytest.mark.parametrize("surface", ["claude-vscode", "codex-vscode"])
def test_missing_extension_names_the_platform_patterns(monkeypatch, tmp_path, surface):
    set_home(monkeypatch, tmp_path)

    result = probes.probe_surface(surface)

    assert (result.verdict, result.source) == ("missing", "exec")
    for pattern in VSCODE_CLI_BY_SURFACE[surface].vscode_binaries_for_platform():
        assert pattern in result.error
    observed = cache.observe_surface_version(surface, state_dir=tmp_path / "state")
    assert observed.version is None
    assert "probe missing" in observed.reason
    assert "unknown relay surface" not in observed.reason


def test_bounded_extension_probe_passes_registration_timeout(monkeypatch, tmp_path):
    set_home(monkeypatch, tmp_path)
    surface = "claude-vscode"
    _bundled_cli(tmp_path, surface, "2.1.331")

    def runner(command, *, timeout, **_kwargs):
        assert timeout == 1.0
        raise subprocess.TimeoutExpired(command, timeout)

    _inject_runner(monkeypatch, runner)
    assert cache.bounded_surface_probe(surface, timeout=1.0).verdict == "timeout"


def test_registration_probes_vscode_version_from_empty_cache(monkeypatch, tmp_path):
    set_home(monkeypatch, tmp_path)
    monkeypatch.setattr(cache, "relay_state_dir", lambda: tmp_path / "state")
    _bundled_cli(tmp_path, "claude-vscode", "2.1.331")
    _inject_runner(
        monkeypatch,
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout="2.1.331 (Claude Code)", stderr="",
        ),
    )

    assert client_executor_version("claude-code", "claude-vscode") == "2.1.331"


def test_claude_cli_still_resolves_the_local_vscode_bundle(monkeypatch, tmp_path):
    set_home(monkeypatch, tmp_path)
    binary = _bundled_cli(tmp_path, "claude-vscode", "2.1.331")

    assert resolve_native_cli_source("claude", path_value="").path == str(binary)


def test_live_inventory_includes_vscode_surface(monkeypatch):
    monkeypatch.setattr(inventory, "_inventory", lambda versions, _limits: versions)
    monkeypatch.setattr(inventory, "observe_plan_limits", lambda _surfaces: {})

    assert inventory.collect_inventory(
        cli_probe=lambda _command: None,
        app_probe=lambda surface: "2.1.331" if surface == "claude-vscode" else None,
    ) == {"claude-vscode": "2.1.331"}
