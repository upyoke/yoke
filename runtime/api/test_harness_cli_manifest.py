"""The harness manifest is the canonical native-CLI registry."""

from __future__ import annotations

from yoke_contracts.testing.real_home_isolation import set_home

import json
import os
from pathlib import Path
import shutil
import sys

from yoke_contracts.path_harness_clis import resolve_harness_clis
from yoke_contracts.harness_cli_manifest import (
    HARNESS_CLI_MANIFESTS,
    HarnessCliManifest,
    harness_cli_executables,
    harness_cli_probe_commands,
)
from yoke_core.domain.agents_render_manifests import (
    CLAUDE_MANIFEST,
    CODEX_MANIFEST,
    CURSOR_MANIFEST,
)
from yoke_core.domain import session_relay_executable
from yoke_harness import session_relay_surface_probes


REPO_ROOT = Path(__file__).resolve().parents[2]


def _native_executable(path: Path) -> Path:
    if os.name == "nt":
        path = path.with_name(path.name + ".exe")
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sys.executable, path)
    return path


def test_native_cli_consumers_derive_identifiers_from_the_manifest() -> None:
    assert harness_cli_executables() == ("claude", "codex", "cursor-agent")
    assert tuple(session_relay_surface_probes.CLI_SURFACE_PROBES) == (
        "claude-cli", "codex-cli", "cursor-cli",
    )
    assert session_relay_surface_probes.CLI_SURFACE_PROBES == (
        harness_cli_probe_commands()
    )
    assert session_relay_executable._RELAY_CLI_EXECUTABLES == (
        harness_cli_executables()
    )


def test_rendered_harness_manifests_carry_the_canonical_cli_sections() -> None:
    expected = {
        "claude": CLAUDE_MANIFEST,
        "codex": CODEX_MANIFEST,
        "cursor": CURSOR_MANIFEST,
    }
    for directory, rendered in expected.items():
        payload = json.loads(
            (REPO_ROOT / "runtime" / "harness" / directory / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert payload["cli"] == rendered["cli"]
        assert payload["session_control"] == rendered["session_control"]


def test_new_manifest_entry_is_resolved_without_a_hardcoded_cli_list(
    tmp_path,
) -> None:
    executable = _native_executable(tmp_path / "example-agent")
    manifest = HarnessCliManifest(
        "example",
        "example-cli",
        "example-agent",
        "example_quota",
    )

    resolved = resolve_harness_clis(str(tmp_path), manifests=(manifest,))

    assert len(resolved) == 1
    assert resolved[0].harness_id == "example"
    # Windows resolution spells the PATHEXT suffix its own case; the path is one file.
    assert Path(resolved[0].path) == executable
    assert tuple(row.harness_id for row in HARNESS_CLI_MANIFESTS) == (
        "claude-code",
        "codex",
        "cursor",
    )


def test_setup_relay_and_doctor_share_path_and_bundled_resolution(
    monkeypatch, tmp_path
):
    from dataclasses import replace
    from yoke_contracts import path_harness_clis as resolver
    from yoke_core.engines import doctor_install

    manifest = next(row for row in HARNESS_CLI_MANIFESTS if row.harness_id == "codex")
    bundled = _native_executable(tmp_path / "bundled" / "codex")
    standalone = _native_executable(tmp_path / "bin" / "codex")
    manifest = replace(manifest, bundled_candidates=(str(bundled),),
                       windows_bundled_candidates=(str(bundled),))
    original = resolver.resolve_native_cli_source
    monkeypatch.setattr(resolver, "HARNESS_CLI_MANIFESTS", (manifest,))
    monkeypatch.setattr(
        resolver,
        "resolve_native_cli_source",
        lambda name, **kw: original(name, **{**kw, "manifests": (manifest,)}),
    )
    for directory, expected, source in (
        (standalone.parent, standalone, "path"),
        (tmp_path / "empty", bundled, "bundled"),
    ):
        monkeypatch.setenv("PATH", str(directory))
        resolved = resolve_harness_clis(str(directory), manifests=(manifest,))[0]
        assert Path(resolved.path) == expected
        assert resolved.source == source
        assert Path(session_relay_surface_probes.resolve_native_cli("codex")) == expected
        assert Path(doctor_install.installed_harness_clis()["codex"]) == expected


def test_codex_app_bundle_is_resolved_from_the_declared_path(tmp_path, monkeypatch):
    from dataclasses import replace

    manifest = next(m for m in HARNESS_CLI_MANIFESTS if m.harness_id == "codex")
    assert manifest.install_for_platform(windows=False) == (
        "curl -fsSL https://chatgpt.com/codex/install.sh | sh"
    )
    assert manifest.bundled_candidates == (
        "~/.local/bin/codex",
        "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
    )
    bundled = _native_executable(tmp_path / manifest.bundled_candidates[1].lstrip("/"))
    monkeypatch.setattr(
        HarnessCliManifest, "bundles_for_platform",
        lambda self, **kw: (self.bundled_candidates, self.bundled_patterns),
    )
    resolution = resolve_harness_clis(
        "", manifests=(replace(manifest, bundled_candidates=(str(bundled),)),)
    )[0]
    assert (resolution.path, resolution.source) == (str(bundled), "bundled")


def test_versioned_claude_bundles_choose_the_newest_executable(tmp_path, monkeypatch):
    from dataclasses import replace
    from yoke_contracts.path_harness_clis import managed_path_directories

    manifest = next(m for m in HARNESS_CLI_MANIFESTS if m.harness_id == "claude-code")
    set_home(monkeypatch, str(tmp_path))
    for pattern in manifest.bundles_for_platform()[1]:
        selected = None
        for version in ("2.9.9", "2.10.2", "2.11.0"):
            bundled = Path(
                pattern.replace("{version}", version).replace("*", "-darwin-arm64")
            ).expanduser()
            bundled.parent.mkdir(parents=True)
            if version == "2.11.0":
                bundled.mkdir()
            else:
                bundled.write_text("#!/bin/sh\n")
                bundled.chmod(0o755)
            if version == "2.10.2":
                selected = str(bundled)
        resolution = resolve_harness_clis(
            "", manifests=(replace(manifest, bundled_patterns=(pattern,), windows_bundled_patterns=(pattern,)),)
        )[0]
        assert (resolution.path, resolution.source) == (selected, "bundled_versioned")
        tools = str(tmp_path / "tools")
        assert managed_path_directories(tools, (resolution,)) == (tools,)
    resolution = resolve_harness_clis("", manifests=(manifest,))[0]
    assert "2.10.2" in resolution.path


def test_every_cli_names_the_update_its_operator_runs() -> None:
    assert {m.surface_id: m.update_command for m in HARNESS_CLI_MANIFESTS} == {
        "claude-cli": "claude update",
        "codex-cli": "codex update",
        "cursor-cli": "cursor-agent update",
    }
