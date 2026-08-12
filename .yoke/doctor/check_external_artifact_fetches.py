"""Inventory external artifact fetches in Docker and GitHub workflow surfaces."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from yoke_project_checks._declare import self_project_checks


HC_ID = "HC-external-artifact-fetch-inventory"
HC_NAME = "External artifact fetch gateway inventory"


@dataclass(frozen=True)
class InventoryEntry:
    path: str
    line: int
    shape: str
    classification: str
    reason: str


@dataclass(frozen=True)
class Allowance:
    path: str
    shape: str
    needle: str
    reason: str


_RAW_PATTERNS = (
    ("curl", re.compile(r"\bcurl\b[^\n]*(?:https?://|\$\{?[A-Z][A-Z0-9_]*)")),
    ("wget", re.compile(r"\bwget\b[^\n]*(?:https?://|\$\{?[A-Z][A-Z0-9_]*)")),
    ("pip-url", re.compile(r"\bpip(?:3)?\s+install\b[^\n]*https?://")),
    ("release-url", re.compile(r"https?://[^\s'\"]+/releases/download/")),
    ("docker-build", re.compile(r"(?m)^\s*(?:-\s+run:\s*)?docker\s+build\b")),
    ("docker-pull", re.compile(r"(?m)^\s*(?:-\s+run:\s*)?docker\s+pull\b")),
)
_GATEWAY_PATTERN = re.compile(r"\b(?:resilient_fetch|postgres_binaries\.py)\b")
_INLINE_ALLOWANCE = re.compile(r"artifact-fetch-allow:\s*(.+)")

_SANCTIONED = (
    Allowance(
        ".github/workflows/yoke-ci.yml",
        "docker-build",
        "docker build \\",
        "workflow-only image construction uses the shared 3-attempt "
        "15s/60s retry before the image can contain the Python gateway",
    ),
    Allowance(
        ".github/workflows/yoke-server-image.yml",
        "docker-pull",
        'docker pull "$image_ref"',
        "the Docker daemon owns content-addressed layer-transfer retries and "
        "the step verifies the immutable digest and native architecture",
    ),
)


def _resolve_repo_root() -> str | None:
    from yoke_core.engines.doctor_report import _resolve_repo_root as resolve

    return resolve()


def _source_files(root: Path) -> Iterable[Path]:
    yield from sorted(path for path in root.rglob("Dockerfile*") if path.is_file())
    workflows = root / ".github/workflows"
    if workflows.is_dir():
        yield from sorted((*workflows.rglob("*.yml"), *workflows.rglob("*.yaml")))


def inventory(root: Path) -> list[InventoryEntry]:
    entries: list[InventoryEntry] = []
    for path in _source_files(root):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        rel = path.relative_to(root).as_posix()
        seen: set[tuple[int, str]] = set()
        for match in _GATEWAY_PATTERN.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            key = (line, "gateway")
            if key not in seen:
                entries.append(
                    InventoryEntry(
                        rel,
                        line,
                        "gateway",
                        "gateway-fetched",
                        "the source delegates artifact transfer and verification "
                        "to the resilient fetch gateway",
                    )
                )
                seen.add(key)
        for shape, pattern in _RAW_PATTERNS:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                key = (line, shape)
                if key in seen:
                    continue
                classification, reason = _classification(
                    rel, line, shape, lines[line - 1], lines
                )
                entries.append(
                    InventoryEntry(rel, line, shape, classification, reason)
                )
                seen.add(key)
    return sorted(entries, key=lambda entry: (entry.path, entry.line, entry.shape))


def _classification(
    path: str,
    line: int,
    shape: str,
    source_line: str,
    lines: list[str],
) -> tuple[str, str]:
    for allowance in _SANCTIONED:
        if (
            allowance.path == path
            and allowance.shape == shape
            and allowance.needle in source_line
        ):
            return "allowlisted-with-justification", allowance.reason
    for candidate in reversed(lines[max(0, line - 4):line - 1]):
        stripped = candidate.strip().lstrip("#").strip()
        if not stripped:
            continue
        inline = _INLINE_ALLOWANCE.search(stripped)
        if inline:
            return "allowlisted-with-justification", inline.group(1).strip()
        if not candidate.lstrip().startswith("#"):
            break
    return (
        "unclassified-bare-fetch",
        "route this fetch through the gateway or add a narrow documented allowance",
    )


def hc_external_artifact_fetch_inventory(_conn, _args, rec) -> None:
    """External artifact fetches use the gateway or a justified allowance."""
    resolved = _resolve_repo_root()
    if not resolved:
        rec.record(HC_ID, HC_NAME, "WARN", "repository root could not be resolved")
        return
    entries = inventory(Path(resolved))
    bare = [entry for entry in entries if entry.classification.startswith("unclassified")]
    detail = "\n".join(
        f"- {entry.path}:{entry.line} [{entry.classification}] "
        f"{entry.shape} — {entry.reason}"
        for entry in entries
    ) or "No external artifact fetch shapes found."
    rec.record(HC_ID, HC_NAME, "WARN" if bare else "PASS", detail)


PROJECT_HEALTH_CHECKS = self_project_checks(
    ("external-artifact-fetch-inventory", HC_NAME, hc_external_artifact_fetch_inventory),
)


__all__ = [
    "InventoryEntry",
    "PROJECT_HEALTH_CHECKS",
    "hc_external_artifact_fetch_inventory",
    "inventory",
]
