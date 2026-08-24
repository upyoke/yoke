"""CLI surface probes fall back to well-known app-bundled binaries."""

from __future__ import annotations

from pathlib import Path

from yoke_harness import session_relay_inventory as inventory_module


def _version_script(directory: Path, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "codex"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.stdout.write({text!r})\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_cli_probe_uses_app_bundle_when_command_is_not_on_path(
    monkeypatch, tmp_path: Path
) -> None:
    bundled = _version_script(tmp_path / "bundle", "codex-cli 0.149.0-alpha.4.3\n")
    monkeypatch.setattr(inventory_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(inventory_module, "_CLI_FALLBACKS", {"codex": bundled})

    assert inventory_module.probe_cli_version(("codex", "--version")) == (
        "0.149.0-alpha.4.3"
    )


def test_cli_probe_prefers_path_over_app_bundle(
    monkeypatch, tmp_path: Path
) -> None:
    on_path = _version_script(tmp_path / "path", "codex-cli 1.2.3\n")
    bundled = _version_script(tmp_path / "bundle", "codex-cli 9.9.9\n")
    monkeypatch.setattr(
        inventory_module.shutil, "which", lambda _name: str(on_path)
    )
    monkeypatch.setattr(inventory_module, "_CLI_FALLBACKS", {"codex": bundled})

    assert inventory_module.probe_cli_version(("codex", "--version")) == "1.2.3"


def test_cli_probe_returns_none_when_path_and_bundle_are_absent(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(inventory_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        inventory_module,
        "_CLI_FALLBACKS",
        {"codex": tmp_path / "missing-codex"},
    )

    assert inventory_module.probe_cli_version(("codex", "--version")) is None
