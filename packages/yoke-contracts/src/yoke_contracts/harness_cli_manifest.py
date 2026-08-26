"""Canonical native CLI facts for every supported harness family."""

from __future__ import annotations

from dataclasses import dataclass

from yoke_contracts.executor_labels import CANONICAL_HARNESS_IDS


@dataclass(frozen=True)
class HarnessCliManifest:
    harness_id: str
    surface_id: str
    executable: str
    version_args: tuple[str, ...] = ("--version",)
    bundled_candidates: tuple[str, ...] = ()

    def to_json(self) -> dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "executable": self.executable,
            "version_args": list(self.version_args),
            "bundled_candidates": list(self.bundled_candidates),
        }


HARNESS_CLI_MANIFESTS = (
    HarnessCliManifest("claude-code", "claude-cli", "claude"),
    HarnessCliManifest(
        "codex",
        "codex-cli",
        "codex",
        bundled_candidates=("/Applications/ChatGPT.app/Contents/Resources/codex",),
    ),
    HarnessCliManifest("cursor", "cursor-cli", "cursor-agent"),
)

if tuple(manifest.harness_id for manifest in HARNESS_CLI_MANIFESTS) != (
    CANONICAL_HARNESS_IDS
):
    raise RuntimeError("native CLI manifests must cover every harness family")

HARNESS_CLI_BY_ID = {
    manifest.harness_id: manifest for manifest in HARNESS_CLI_MANIFESTS
}


def harness_cli_manifest(harness_id: str) -> HarnessCliManifest:
    try:
        return HARNESS_CLI_BY_ID[harness_id]
    except KeyError as exc:
        raise ValueError(f"unknown harness id: {harness_id!r}") from exc


def harness_cli_executables() -> tuple[str, ...]:
    return tuple(manifest.executable for manifest in HARNESS_CLI_MANIFESTS)


def harness_cli_probe_commands() -> dict[str, tuple[str, ...]]:
    return {
        manifest.surface_id: (manifest.executable, *manifest.version_args)
        for manifest in HARNESS_CLI_MANIFESTS
    }


__all__ = [
    "HARNESS_CLI_BY_ID",
    "HARNESS_CLI_MANIFESTS",
    "HarnessCliManifest",
    "harness_cli_executables",
    "harness_cli_manifest",
    "harness_cli_probe_commands",
]
