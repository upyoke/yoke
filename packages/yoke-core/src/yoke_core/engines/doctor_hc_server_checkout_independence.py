"""Doctor HC: server-reachable code must stay checkout-independent.

``HC-server-checkout-independence`` is the read-side counterpart to
``HC-workspace-anchored-writer-authority`` (which guards the write side).

The function-call handlers run on the control-plane server over the HTTPS
transport, which has no git checkout — no ``.git`` ancestor, no
``YOKE_REPO_ROOT``, and ``git rev-parse`` fails. So code on that path must
not resolve a repo root from ambient context: walking ``.git`` via
``find_repo_root``, ``Path.cwd`` / ``os.getcwd``, or shelling out to
``git rev-parse``. A handler that needs a root takes it from the request (a
client resolves it where the checkout lives and ships it); a server-side
resolver reads from the request or the DB. This HC caught its motivating bug
class: a label-sync side-effect resolving ``.yoke/labels`` via
``find_repo_root(Path(__file__))`` and crashing server-side.

Scope:

* Every function-call handler module under ``domain/handlers/`` —
  server-reachable by definition; new handlers are enrolled automatically.
* ``CHECKOUT_INDEPENDENT_MODULES`` — specific resolver modules that were made
  checkout-independent and must stay that way (regression guard).

The canonical resolvers (``resolve_main_root``, ``resolve_yoke_root``,
``resolve_main_repo_root``) are called *by name* with an explicit root
argument; the forbidden tokens below deliberately do not match those names, so
"resolve from a root the caller supplied" stays allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from yoke_core.api.repo_root import find_repo_root
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


HC_NAME = "HC-server-checkout-independence"
HC_DESC = (
    "Server-reachable code must not resolve a repo root from ambient context "
    "(find_repo_root / cwd / git rev-parse)"
)

# Ambient-resolution tokens forbidden on the server-reachable surface.
FORBIDDEN_TOKENS = (
    "find_repo_root(",
    "Path.cwd(",
    "os.getcwd(",
    "rev-parse",
)

HANDLERS_RELDIR = "packages/yoke-core/src/yoke_core/domain/handlers"

# Non-handler resolver modules made checkout-independent; regression-guarded.
CHECKOUT_INDEPENDENT_MODULES = (
    "packages/yoke-core/src/yoke_core/domain/project_label_policy.py",
)


@dataclass(frozen=True)
class AmbientResolutionFinding:
    relpath: str
    token: str


def _project_root() -> Path:
    return find_repo_root(Path(__file__))


def _scan_one(repo_root: Path, relpath: str) -> Optional[AmbientResolutionFinding]:
    candidate = repo_root / relpath
    if not candidate.is_file():
        return None
    try:
        text = candidate.read_text(encoding="utf-8")
    except OSError:
        return None
    for token in FORBIDDEN_TOKENS:
        if token in text:
            return AmbientResolutionFinding(relpath=relpath, token=token)
    return None


def _in_scope_relpaths(repo_root: Path) -> List[str]:
    paths: List[str] = list(CHECKOUT_INDEPENDENT_MODULES)
    handlers_dir = repo_root / HANDLERS_RELDIR
    if handlers_dir.is_dir():
        for candidate in sorted(handlers_dir.glob("*.py")):
            if candidate.name == "__init__.py" or candidate.name.startswith("test_"):
                continue
            paths.append(candidate.relative_to(repo_root).as_posix())
    return paths


def scan_for_ambient_resolution(
    repo_root: Path,
    *,
    extra_scan_paths: Sequence[str] = (),
) -> List[AmbientResolutionFinding]:
    """Return findings: server-reachable modules that resolve a root from cwd/git."""
    findings: List[AmbientResolutionFinding] = []
    for relpath in list(_in_scope_relpaths(repo_root)) + list(extra_scan_paths):
        result = _scan_one(repo_root, relpath)
        if result is not None:
            findings.append(result)
    return findings


def hc_server_checkout_independence(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Doctor entry. Scans the server-reachable surface; FAILs on ambient resolution."""
    repo_root = _project_root()
    findings = scan_for_ambient_resolution(repo_root)
    if not findings:
        rec.record(
            HC_NAME, HC_DESC, "PASS",
            "Server-reachable handlers and checkout-independent resolvers resolve "
            "no repo root from ambient context.",
        )
        return
    head = (
        f"- {len(findings)} server-reachable module(s) resolve a repo root from "
        "ambient context. Take the root from the request (resolved client-side, "
        "where the checkout lives) instead of walking .git / cwd / git rev-parse."
    )
    body = "\n".join(
        [head, ""] + [f"  - `{f.relpath}` contains `{f.token}`" for f in findings]
    )
    rec.record(HC_NAME, HC_DESC, "FAIL", body)


__all__ = [
    "HC_NAME",
    "HC_DESC",
    "FORBIDDEN_TOKENS",
    "CHECKOUT_INDEPENDENT_MODULES",
    "AmbientResolutionFinding",
    "hc_server_checkout_independence",
    "scan_for_ambient_resolution",
]
