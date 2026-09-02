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
