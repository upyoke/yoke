"""Scan helpers for HC-terminal-recipe-residue.

Carved out so the HC stays under the 350-line authored-file budget and so
the registry-aware choreography scanner has a clean unit-test target.

Surfaces:

* :func:`iter_scan_paths` — yield Path objects for every live guidance
  surface the HC should scan.
* :func:`path_in_allowlist` — prefix-match check against the allowlist.
* :func:`registry_choreography_findings` — registry-aware second pass that
  flags Yoke CLI adapters wrapped with shell choreography.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Tuple

from yoke_core.api.service_client_structured_api_adapter_inventory import (
    CLI_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_taught import (
    TAUGHT_ADAPTERS,
)


# Single-file scan targets at repo root.
_SCAN_ROOT_FILES: Tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    "CODEX.md",
)

# Directory scan targets keyed by extension.
_SCAN_DIRS_BY_EXT: dict[str, Tuple[str, ...]] = {
    ".md": (
        ".agents/skills/yoke",
        "runtime/agents",
        "runtime/harness/claude/agents",
        "runtime/harness/codex/agents",
        "docs",
    ),
}

# Choreography signatures the registry-aware scanner looks for around a
# Yoke CLI adapter invocation. Same canonical list as the lint module
# (see yoke_core.domain.lint_shell_quoted_function_payload).
_CHOREOGRAPHY_TOKENS: Tuple[str, ...] = (
    "2>&1",
    "; echo $?",
    "&& echo $?",
    " | tee ",
    "$(",
)

_HEREDOC_RE = re.compile(r"<<-?\s*['\"]?\w+['\"]?")

def _readonly_function_ids() -> frozenset[str]:
    return frozenset(
        e.function_id
        for e in (*CLI_ADAPTERS, *TAUGHT_ADAPTERS)
        if e.read_shape
    )


_READONLY_FUNCTION_IDS: frozenset[str] = _readonly_function_ids()


def iter_scan_paths(repo_root: Path) -> Iterable[Path]:
    """Yield every file the HC should scan."""
    for name in _SCAN_ROOT_FILES:
        candidate = repo_root / name
        if candidate.is_file():
            yield candidate
    for ext, dirs in _SCAN_DIRS_BY_EXT.items():
        for rel in dirs:
            base = repo_root / rel
            if not base.is_dir():
                continue
            for f in base.rglob(f"*{ext}"):
                yield f


def path_in_allowlist(rel_str: str, allowlist: Tuple[str, ...]) -> bool:
    """Prefix-match a relative path against allowlist entries."""
    return any(rel_str.startswith(entry) for entry in allowlist)


def _adapter_prefixes() -> List[Tuple[str, str]]:
    """Return exact CLI adapter prefixes from the function inventory."""
    prefixes: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in CLI_ADAPTERS:
        cli = entry.cli_invocation.strip()
        if not cli.startswith("python3 -m "):
            continue
        words: list[str] = []
        for word in cli.split():
            if (
                word.startswith("<")
                or word in {"|", "--body-file", "PATH"}
                or word.endswith("|")
            ):
                break
            if word.startswith("YOK-N"):
                break
            words.append(word)
        prefix = " ".join(words).strip()
        if prefix and prefix not in seen:
            prefixes.append((entry.function_id, prefix))
            seen.add(prefix)
    return prefixes


def _captures_mutating_adapter(line: str, function_id: str) -> bool:
    """Return true for shell capture around an adapter with write semantics."""
    if not re.search(r"\b\w+=\$\(\s*python3?", line):
        return False
    return function_id not in _READONLY_FUNCTION_IDS


def _line_has_transport_choreography(line: str) -> bool:
    if _HEREDOC_RE.search(line):
        return True
    for token in _CHOREOGRAPHY_TOKENS:
        if token != "$(" and token in line:
            return True
    return False


def registry_choreography_findings(
    repo_root: Path,
    *,
    allowlist: Tuple[str, ...],
    test_file_re: re.Pattern,
) -> List[str]:
    """Return findings for adapter invocations wrapped with shell choreography.

    The HC fails on any registry-covered Yoke CLI invocation
    that appears in live guidance with shell choreography around it. This is
    the "function_covered_recipe" class.
    """
    findings: List[str] = []
    prefixes = _adapter_prefixes()
    if not prefixes:
        return findings

    for path in iter_scan_paths(repo_root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = path.resolve().relative_to(repo_root.resolve())
        except ValueError:
            rel = path
        rel_str = str(rel)
        if path_in_allowlist(rel_str, allowlist):
            continue
        if test_file_re.search(rel_str):
            continue
        # Skip the HC's own scan + messages modules; their source contains
        # the listed shapes by design.
        if (
            rel_str.endswith(
                "lint_structured_field_transform_shell_messages.py"
            )
            or rel_str.endswith("doctor_hc_terminal_recipe_residue.py")
            or rel_str.endswith("doctor_hc_terminal_recipe_residue_scan.py")
        ):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            has_transport_choreography = _line_has_transport_choreography(line)
            for function_id, prefix in prefixes:
                if prefix in line and (
                    has_transport_choreography
                    or _captures_mutating_adapter(line, function_id)
                ):
                    snippet = line.rstrip()[:160]
                    findings.append(
                        f"{rel_str}:{line_no}: [function-covered "
                        f"recipe; adapter={prefix}] {snippet}"
                    )
                    break  # one hit per line.
    return findings


__all__ = [
    "iter_scan_paths",
    "path_in_allowlist",
    "registry_choreography_findings",
]
