"""The public machine facts a relay advertises: native CLIs and its name."""

from __future__ import annotations

from pathlib import Path

from yoke_harness import session_relay_inventory as inventory_module
from yoke_harness import session_relay_surface_probes as probe_module


def _version_script(directory: Path, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "codex"
    script.write_text(
        f"#!/usr/bin/env python3\nimport sys\nsys.stdout.write({text!r})\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_cli_probe_uses_app_bundle_when_command_is_not_on_path(
    monkeypatch, tmp_path: Path
) -> None:
    bundled = _version_script(tmp_path / "bundle", "codex-cli 0.149.0-alpha.4.3\n")
    monkeypatch.setattr(probe_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(probe_module, "_CLI_FALLBACKS", {"codex": (bundled,)})

    assert inventory_module.probe_cli_version(("codex", "--version")) == (
        "0.149.0-alpha.4.3"
    )


def test_cli_probe_prefers_path_over_app_bundle(monkeypatch, tmp_path: Path) -> None:
    on_path = _version_script(tmp_path / "path", "codex-cli 1.2.3\n")
    bundled = _version_script(tmp_path / "bundle", "codex-cli 9.9.9\n")
    monkeypatch.setattr(probe_module.shutil, "which", lambda _name: str(on_path))
    monkeypatch.setattr(probe_module, "_CLI_FALLBACKS", {"codex": (bundled,)})

    assert inventory_module.probe_cli_version(("codex", "--version")) == "1.2.3"


def test_cli_probe_returns_none_when_path_and_bundle_are_absent(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        probe_module,
        "_CLI_FALLBACKS",
        {"codex": (tmp_path / "missing-codex",)},
    )

    assert inventory_module.probe_cli_version(("codex", "--version")) is None


def test_launch_transports_resolve_the_binary_the_probe_advertised(
    monkeypatch, tmp_path: Path
) -> None:
    # A probe that finds the app bundle while the transport searches only
    # PATH advertises a launchable surface that then fails every create.
    from yoke_harness.session_relay_codex_app_server import (
        CodexAppServerTransport,
    )
    from yoke_harness.session_relay_codex_cli import CodexCliTransport

    bundled = _version_script(tmp_path / "bundle", "codex-cli 0.149.0-alpha.4.3\n")
    monkeypatch.setattr(probe_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(probe_module, "_CLI_FALLBACKS", {"codex": (bundled,)})

    assert inventory_module.probe_cli_version(("codex", "--version"))
    resolved = CodexCliTransport()._resolve_binary()
    assert resolved is not None and resolved.path == str(bundled)
    assert resolved.source == "bundled"
    assert CodexAppServerTransport().binary == "codex"
    assert inventory_module.resolve_native_cli("codex") == str(bundled)


def test_a_standalone_install_on_path_wins_over_the_desktop_bundle(
    monkeypatch, tmp_path: Path
) -> None:
    # Both codex builds ship separately, so an attempt has to be able to say
    # which one ran it.
    standalone = _version_script(tmp_path / "path", "codex-cli 0.150.0\n")
    bundled = _version_script(tmp_path / "bundle", "codex-cli 0.149.0-alpha.4.3\n")
    monkeypatch.setattr(probe_module, "_CLI_FALLBACKS", {"codex": (bundled,)})
    monkeypatch.setattr(probe_module.shutil, "which", lambda _name: str(standalone))

    resolved = inventory_module.resolve_native_cli_source("codex")

    assert resolved == inventory_module.ResolvedNativeCli(str(standalone), "path")
    assert inventory_module.probe_cli_version(("codex", "--version")) == "0.150.0"


def test_an_absolute_binary_resolves_only_when_it_is_executable(
    tmp_path: Path,
) -> None:
    executable = _version_script(tmp_path / "explicit", "codex-cli 1.0.0\n")
    plain = tmp_path / "explicit" / "not-executable"
    plain.write_text("", encoding="utf-8")

    assert inventory_module.resolve_native_cli(str(executable)) == str(executable)
    assert inventory_module.resolve_native_cli_source(str(executable)) == (
        inventory_module.ResolvedNativeCli(str(executable), "explicit")
    )
    assert inventory_module.resolve_native_cli(str(plain)) is None
    assert inventory_module.resolve_native_cli(str(tmp_path / "absent")) is None


def test_cached_inventory_does_not_probe_during_initial_registration(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        inventory_module,
        "ensure_machine_id",
        lambda: "11111111-1111-4111-8111-111111111111",
    )
    monkeypatch.setattr(
        inventory_module.machine_config,
        "configured_projects",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(inventory_module, "local_handshake_version", lambda: "source")

    observed = inventory_module.collect_cached_inventory(state_dir=tmp_path)

    assert observed.surface_versions == {}


def test_relay_reports_the_operator_set_machine_name(monkeypatch) -> None:
    # A Mac whose owner named it reports "Mac" through gethostname, which
    # makes two default-named laptops indistinguishable on the roster.
    from yoke_contracts.machine_config import machine_name as machine_name_module

    monkeypatch.setattr(machine_name_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        machine_name_module,
        "_probe",
        lambda command: (
            "beebauman-macbook-pro-16"
            if command == ("scutil", "--get", "ComputerName")
            else ""
        ),
    )
    monkeypatch.setattr(machine_name_module.socket, "gethostname", lambda: "Mac")

    assert machine_name_module.machine_display_name() == "beebauman-macbook-pro-16"


def test_machine_name_falls_back_to_the_host_name_when_unset(monkeypatch) -> None:
    # The systemd pretty hostname is routinely unset, and a probe that cannot
    # run at all must still leave the relay with a usable name.
    from yoke_contracts.machine_config import machine_name as machine_name_module

    monkeypatch.setattr(machine_name_module.sys, "platform", "linux")
    monkeypatch.setattr(machine_name_module, "_probe", lambda _command: "")
    monkeypatch.setattr(
        machine_name_module.socket, "gethostname", lambda: "build-runner-3"
    )

    assert machine_name_module.machine_display_name() == "build-runner-3"


def test_a_probe_that_fails_or_is_missing_does_not_raise(monkeypatch) -> None:
    from yoke_contracts.machine_config import machine_name as machine_name_module

    def absent(_command, **_kwargs):
        raise FileNotFoundError("scutil")

    monkeypatch.setattr(machine_name_module.subprocess, "run", absent)
    monkeypatch.setattr(machine_name_module.socket, "gethostname", lambda: "fallback")

    assert machine_name_module.machine_display_name() == "fallback"
