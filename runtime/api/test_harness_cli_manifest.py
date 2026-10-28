"""The harness manifest is the canonical native-CLI registry."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_cli.config.path_harness_clis import resolve_harness_clis
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
from yoke_core.tools import session_relay_executable
from yoke_harness import session_relay_surface_probes


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_native_cli_consumers_derive_identifiers_from_the_manifest() -> None:
    assert harness_cli_executables() == ("claude", "codex", "cursor-agent")
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
    executable = tmp_path / "example-agent"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    manifest = HarnessCliManifest(
        "example",
        "example-cli",
        executable.name,
        "example_quota",
    )

    resolved = resolve_harness_clis(str(tmp_path), manifests=(manifest,))

    assert len(resolved) == 1
    assert resolved[0].harness_id == "example"
    assert resolved[0].path == str(executable)
    assert tuple(row.harness_id for row in HARNESS_CLI_MANIFESTS) == (
        "claude-code",
        "codex",
        "cursor",
    )


def test_setup_relay_and_doctor_share_path_and_bundled_resolution(
    monkeypatch, tmp_path
):
    from dataclasses import replace
    from yoke_cli.config import path_harness_clis as resolver
    from yoke_core.engines import doctor_install

    manifest = next(row for row in HARNESS_CLI_MANIFESTS if row.harness_id == "codex")
    bundled = tmp_path / "bundled" / "codex"
    standalone = tmp_path / "bin" / "codex"
    for executable in (bundled, standalone):
        executable.parent.mkdir()
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
    manifest = replace(manifest, bundled_candidates=(str(bundled),))
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
        assert resolved.path == str(expected)
        assert resolved.source == source
        assert session_relay_surface_probes.resolve_native_cli("codex") == str(expected)
        assert doctor_install.installed_harness_clis()["codex"] == str(expected)


def test_codex_app_bundle_is_resolved_from_the_declared_path(tmp_path):
    from dataclasses import replace

    manifest = next(m for m in HARNESS_CLI_MANIFESTS if m.harness_id == "codex")
    assert manifest.bundled_candidates == (
        "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
    )
    bundled = tmp_path / manifest.bundled_candidates[0].lstrip("/")
    bundled.parent.mkdir(parents=True)
    bundled.write_text("#!/bin/sh\n")
    bundled.chmod(0o755)
    resolution = resolve_harness_clis(
        "", manifests=(replace(manifest, bundled_candidates=(str(bundled),)),)
    )[0]
    assert (resolution.path, resolution.source) == (str(bundled), "bundled")


def test_versioned_claude_bundles_choose_the_newest_executable(tmp_path, monkeypatch):
    from dataclasses import replace
    from yoke_cli.config.path_harness_clis import managed_path_directories

    manifest = next(m for m in HARNESS_CLI_MANIFESTS if m.harness_id == "claude-code")
    monkeypatch.setenv("HOME", str(tmp_path))
    for pattern in manifest.bundled_patterns:
        selected = None
        for version in ("2.9.9", "2.10.2", "2.11.0"):
            bundled = Path(
                pattern.replace("{version}", version).replace("*", "-darwin-arm64")
            ).expanduser()
            bundled.parent.mkdir(parents=True)
            bundled.write_text("#!/bin/sh\n")
            bundled.chmod(0o755 if version != "2.11.0" else 0o644)
            if version == "2.10.2":
                selected = str(bundled)
        resolution = resolve_harness_clis(
            "", manifests=(replace(manifest, bundled_patterns=(pattern,)),)
        )[0]
        assert (resolution.path, resolution.source) == (selected, "bundled_versioned")
        assert managed_path_directories("/tools", (resolution,)) == ("/tools",)
    resolution = resolve_harness_clis("", manifests=(manifest,))[0]
    assert "2.10.2" in resolution.path
