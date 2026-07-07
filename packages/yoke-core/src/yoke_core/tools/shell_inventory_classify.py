"""Per-file classification for the shell migration inventory.

Owns the ``ShellFile`` dataclass and the helpers that translate a path into
the inventory's ``(category, owner, disposition, ticket, why_not_python)``
columns. The routing tables this consumes live in ``shell_inventory_rules``;
the zero-shell closeout lane map lives in ``shell_inventory_closeout``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from yoke_core.tools.shell_inventory_rules import (
    COMPATIBILITY_SHIMS,
    DB_WRAPPER_TICKETS,
    EXTERNAL_ARTIFACT_PREFIXES,
    FUNCTION_HOME_OVERRIDES,
    FUNCTION_RATIONALE_OVERRIDES,
    HARNESS_BOUNDARY_PREFIXES,
    KEEP_BOUNDARY,
    ORCHESTRATION_TARGETS,
    ORCHESTRATION_TICKETS,
    OWNER_LABELS,
    PYTHON_HOME,
    THIN_COMPATIBILITY_SHIMS,
    THIN_MARKERS,
    UTILITY_TICKET_OVERRIDES,
    WRITE_AUTHORITY,
    WRITE_AUTHORITY_TICKETS,
)
from yoke_core.tools.shell_inventory_closeout import (
    ZERO_SHELL_CLOSEOUT_RUNNER_RELPATHS,
    closeout_ticket_for_non_test,
    closeout_ticket_for_test,
)


@dataclass
class ShellFile:
    path: Path
    relpath: str
    basename: str
    line_count: int
    caller_count: int
    category: str
    owner: str
    disposition: str
    ticket: str
    why_not_python: str
    candidate_home: str
    function_rows: list[tuple[str, str, str, str]]


def _header_text(path: Path, *, max_lines: int = 160) -> str:
    try:
        with path.open(encoding="utf-8", errors="ignore") as handle:
            return "\n".join(handle.read().splitlines()[:max_lines]).lower()
    except OSError:
        return ""


def _is_external_artifact(relpath: str) -> bool:
    return relpath.startswith(EXTERNAL_ARTIFACT_PREFIXES)


def _is_harness_runtime_boundary(relpath: str) -> bool:
    return (
        relpath.startswith(HARNESS_BOUNDARY_PREFIXES)
        or relpath == "runtime/install.sh"
        or relpath == "packaging/public-installer/install"
    )


def _looks_like_thin_launcher(path: Path, relpath: str) -> bool:
    if path.name in THIN_COMPATIBILITY_SHIMS:
        return True
    if _is_external_artifact(relpath):
        return False
    header = _header_text(path)
    if "intentionally shell-owned" in header:
        return False
    return any(marker in header for marker in THIN_MARKERS)


_CLOSEOUT_DISPOSITIONS = {
    "test": ("delete or port during shell closeout", "Shell closeout owns deleting this shell test or replacing it with Python-backed coverage."),
    "external": ("replace tracked artifact", "Shell closeout owns converting this tracked .sh artifact into a generated asset or non-shell template so the repo stops tracking shell here."),
    "runtime": ("eliminate during shell closeout", "Shell closeout owns moving this runtime launch path behind a Python entrypoint and deleting the tracked shell file."),
    "shim": ("eliminate during shell closeout", "Shell closeout owns moving direct callers onto Python/API entrypoints and deleting this compatibility shell shim."),
}


def _closeout_disposition(ticket: str | None, flavor: str) -> tuple[str, str] | None:
    return _CLOSEOUT_DISPOSITIONS.get(flavor, _CLOSEOUT_DISPOSITIONS["shim"]) if ticket else None


def classify(path: Path, relpath: str) -> tuple[str, str, str, str, str]:
    basename = path.name
    lower = basename.lower()
    closeout_ticket = closeout_ticket_for_non_test(relpath)

    if relpath.startswith(".agents/skills/yoke/scripts/tests/"):
        disposition, note = _closeout_disposition(closeout_ticket_for_test(relpath), "test")
        return (
            "shell test",
            "Shell test harness",
            disposition,
            closeout_ticket_for_test(relpath),
            note,
        )

    if relpath in ZERO_SHELL_CLOSEOUT_RUNNER_RELPATHS:
        disposition, note = _closeout_disposition(closeout_ticket, "shim") or (
            "contingent shell coverage",
            "Shell-native test harness coverage still exists here today.",
        )
        return (
            "shell test harness",
            "Shell test harness",
            disposition,
            closeout_ticket or "n/a",
            note,
        )

    if _is_external_artifact(relpath):
        disposition, note = _closeout_disposition(closeout_ticket, "external") or (
            "exempt external artifact",
            "Template, vendored, or emitted external/runtime shell artifact; not repo-internal control-plane migration scope.",
        )
        return (
            "external shell artifact",
            "Project/runtime artifact",
            disposition,
            closeout_ticket or "n/a",
            note,
        )

    if _is_harness_runtime_boundary(relpath):
        disposition, note = _closeout_disposition(closeout_ticket, "runtime") or (
            "keep shell boundary",
            "Harness/install runtime entrypoints remain a legitimate shell boundary even after Python owns the semantics.",
        )
        return (
            "runtime shell boundary",
            "Hook runtime",
            disposition,
            closeout_ticket or "n/a",
            note,
        )

    if basename == "browser-worker.sh":
        disposition, note = _closeout_disposition(closeout_ticket, "runtime") or (
            "keep shell boundary",
            "SSH tunnel lifecycle and remote daemon bootstrap are intentionally shell-owned runtime boundary work.",
        )
        return (
            "runtime shell boundary",
            "Browser QA",
            disposition,
            closeout_ticket or "n/a",
            note,
        )

    if _looks_like_thin_launcher(path, relpath):
        owner = infer_owner(path)
        disposition, note = _closeout_disposition(closeout_ticket, "shim") or (
            "keep shell boundary",
            "Semantic ownership is already in Python; keep this shell shim only while direct shell callers still exist.",
        )
        return (
            "shell compatibility shim",
            owner,
            disposition,
            closeout_ticket or "n/a",
            note,
        )

    if basename in WRITE_AUTHORITY:
        return (
            "control-plane write orchestration",
            "Backlog write path" if basename != "emit-event.sh" else "Event platform",
            "migrate to Python",
            WRITE_AUTHORITY_TICKETS.get(basename, "github-sync-write-authority-retirement"),
            "Still owns write-side side effects, lifecycle mutation orchestration, or GitHub sync glue.",
        )

    if basename in COMPATIBILITY_SHIMS:
        if basename in {"browser-run-scenario.sh", "qa-gate-check.sh"}:
            owner = "Browser QA"
        elif basename in {"deploy-pipeline.sh", "deploy-qa-recorder.sh"}:
            owner = "Deployment pipeline"
        else:
            owner = "Domain DB wrapper"
        return (
            "shell compatibility shim",
            owner,
            "keep shell boundary",
            "n/a",
            "Semantic ownership is already in Python; keep this shell shim only while direct shell callers still exist.",
        )

    if basename in ORCHESTRATION_TARGETS:
        if basename in {"browser-exec.sh", "browser-run-scenario.sh", "browser-snapshot.sh", "persist-epic-simulation.sh", "qa-gate-check.sh"}:
            owner = "Browser QA"
        elif basename in {"deploy-pipeline.sh", "deploy-qa-recorder.sh"}:
            owner = "Deployment pipeline"
        else:
            owner = "Worktree merge"
        return (
            "shell orchestration",
            owner,
            "migrate to Python",
            ORCHESTRATION_TICKETS.get(basename, "unmapped-shell-retirement"),
            "Still bundles multi-step orchestration and should be decomposed before a Python cutover.",
        )

    if basename in KEEP_BOUNDARY or relpath.startswith(".agents/skills/yoke/scripts/executors/"):
        if basename == "repair-status.sh":
            owner = "Backlog registry"
        elif basename == "emit-event.sh":
            owner = "Event platform"
        elif basename in {
            "done-transition.sh",
            "sync-progress.sh",
            "sync-task-body.sh",
            "sync-task-label.sh",
            "update-status.sh",
        }:
            owner = "Backlog registry"
        else:
            owner = "Hook runtime" if "observe" in lower or "doctor" in lower else "Deployment pipeline"
        disposition, note = _closeout_disposition(closeout_ticket, "runtime") or (
            "keep shell boundary",
            "Shell is still the right boundary for process launch, hooks, or host-level execution.",
        )
        return (
            "runtime shell boundary",
            owner,
            disposition,
            closeout_ticket or "n/a",
            note,
        )

    if basename.endswith("-db.sh"):
        disposition, note = _closeout_disposition(closeout_ticket, "runtime") or (
            (
                "keep shell boundary"
                if basename == "yoke-db.sh"
                else "migrate to Python"
            ),
            (
                "Stable shell-facing DB router; keep as the public CLI boundary while domain modules stay Python-owned."
                if basename == "yoke-db.sh"
                else "Domain logic still lives in shell and needs decomposition before migration."
            ),
        )
        return (
            "shell-native DB wrapper",
            "Domain DB wrapper",
            disposition,
            closeout_ticket
            or ("n/a" if basename == "yoke-db.sh" else DB_WRAPPER_TICKETS.get(basename, "unmapped-shell-retirement")),
            note,
        )

    if "test" in basename:
        return (
            "shell test",
            "Shell test harness",
            "contingent shell coverage",
            closeout_ticket_for_test(relpath),
            "Exercises shell-native entrypoints and wrapper contracts that still exist today, but should be deleted or replaced as shell authority disappears.",
        )

    return (
        "shell utility",
        "Yoke runtime",
        "migrate to Python",
        closeout_ticket or UTILITY_TICKET_OVERRIDES.get(basename, "TBD"),
        "No permanent shell-boundary justification is documented yet.",
    )


def candidate_home(path: Path) -> str:
    basename = path.name
    if basename in PYTHON_HOME:
        return PYTHON_HOME[basename]
    stem = basename.removesuffix(".sh").replace("-", "_")
    if path.parent.name == "executors":
        return f"yoke_core.engines.executors.{stem}"
    if path.name.startswith("test-"):
        return f"pytest shell coverage for {stem.removeprefix('test_')}"
    return f"yoke_core.engines.{stem}"


def infer_owner(path: Path) -> str:
    rel = str(path)
    if "/scripts/tests/" in rel:
        return OWNER_LABELS["test"]
    if "browser" in path.name:
        return OWNER_LABELS["browser"]
    if "deploy" in path.name or "github-actions" in path.name:
        return OWNER_LABELS["deploy"]
    if "event" in path.name or "observe" in path.name:
        return OWNER_LABELS["event"]
    if "hook" in path.name or "doctor" in path.name:
        return OWNER_LABELS["hook"]
    if "merge" in path.name:
        return OWNER_LABELS["merge"]
    if "qa" in path.name:
        return OWNER_LABELS["qa"]
    if any(token in path.name for token in {"backlog", "status", "sync"}):
        return OWNER_LABELS["registry"]
    return "Yoke runtime"


def parse_functions(
    path: Path, candidate: str, disposition: str
) -> list[tuple[str, str, str, str]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []

    functions: list[tuple[str, str, str, str]] = []
    pattern = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{$")
    for idx, line in enumerate(lines):
        match = pattern.match(line.strip())
        if not match:
            continue
        name = match.group(1)
        comment_lines: list[str] = []
        lookback = idx - 1
        while lookback >= 0 and lines[lookback].lstrip().startswith("#"):
            comment_lines.append(lines[lookback].lstrip("# ").strip())
            lookback -= 1
        comment_lines.reverse()
        purpose = " ".join(comment_lines[-2:]).strip() or name.replace("_", " ")
        function_candidate_home = FUNCTION_HOME_OVERRIDES.get((path.name, name), candidate)
        rationale = FUNCTION_RATIONALE_OVERRIDES.get((path.name, name)) or (
            "Keep in shell until the file-level boundary is retired."
            if disposition == "keep shell boundary"
            else "Candidate for Python extraction once the owning script is decomposed."
        )
        functions.append((name, purpose, function_candidate_home, rationale))
    return functions
