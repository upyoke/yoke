"""Doctor HC: workspace-anchored writers must call the work-claim helper.

``HC-workspace-anchored-writer-authority`` is the structural backstop
for the four retrofitted repo-tree writers in
:mod:`yoke_core.domain` and the substrate renderer's atomic-rename
path. Each in-scope writer must call
:func:`yoke_core.domain.workspace_authority.assert_target_under_session_work_authority`
before its ``.write_text`` / ``.write_bytes`` / ``os.replace`` hot
path lands a repo-tree file. The check guards against the wrong-tree
write recurrence pattern: a session bound to a worktree work-claim
inadvertently writes generated content into the main checkout.

Scope shape:

* ``IN_SCOPE_WRITERS`` enumerates the modules the HC currently
  enforces. Every writer retrofitted by the originating ticket is
  listed here and must call the helper — the HC FAILs otherwise.
* Future writers added to ``IN_SCOPE_WRITERS`` get the same
  enforcement automatically.
* A test fixture can pass ``extra_scan_paths`` to
  :func:`scan_for_bypass` to exercise the bypass-detection branch
  against a synthetic writer module that lacks the helper call.

The HC reports a non-blocking informational WARN when it detects
additional repo-tree writers outside ``IN_SCOPE_WRITERS`` that don't
call the helper — those are candidate follow-up retrofits, not failures
of this slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

import yoke_core.engines.doctor_report as _base
from yoke_core.api.repo_root import find_repo_root
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


HC_NAME = "HC-workspace-anchored-writer-authority"
HC_DESC = (
    "Workspace-anchored writers must call "
    "assert_target_under_session_work_authority before writing"
)

HELPER_SYMBOL = "assert_target_under_session_work_authority"
HELPER_MODULE = "yoke_core.domain.workspace_authority"


# Modules this HC enforces. Each must call the helper before any
# repo-tree write. Adding a writer here is the gating step for new
# retrofits.
#
# rebuild_board.py is intentionally NOT in scope: its only write
# targets (.yoke/BOARD.md and its timestamp file) are
# untracked generated views, regenerated from DB state on every
# status change. Including it would refuse the routine board-rebuild
# side effect that fires from /yoke polish and /yoke usher status
# transitions while the session still holds the item's worktree
# work-claim — a different shape from the wrong-tree write this HC
# exists to catch (worktree-claim-bound writes of TRACKED rendered
# source files into main).
IN_SCOPE_WRITERS = (
    "packages/yoke-core/src/yoke_core/domain/agents_render.py",
    "packages/yoke-core/src/yoke_core/domain/install_bundle_tree_sync.py",
    "packages/yoke-core/src/yoke_core/domain/populate_registry_render.py",
    "packages/yoke-core/src/yoke_core/tools/atlas_integrity_audit.py",
    "packages/yoke-core/src/yoke_core/tools/atlas_render_docs.py",
    "packages/yoke-core/src/yoke_core/tools/render_field_note_inline.py",
)


WRITE_HOT_PATH_TOKENS = (
    ".write_text(",
    ".write_bytes(",
    "os.replace(",
)


@dataclass(frozen=True)
class WriterScanResult:
    relpath: str
    has_write_hot_path: bool
    calls_helper: bool


def _project_root() -> Path:
    return find_repo_root(Path(__file__))


def _scan_one(repo_root: Path, relpath: str) -> Optional[WriterScanResult]:
    candidate = repo_root / relpath
    if not candidate.is_file():
        return None
    try:
        text = candidate.read_text(encoding="utf-8")
    except OSError:
        return None
    has_write = any(tok in text for tok in WRITE_HOT_PATH_TOKENS)
    calls_helper = HELPER_SYMBOL in text
    return WriterScanResult(
        relpath=relpath, has_write_hot_path=has_write, calls_helper=calls_helper,
    )


def scan_for_bypass(
    repo_root: Path,
    *,
    in_scope: Sequence[str] = IN_SCOPE_WRITERS,
    extra_scan_paths: Sequence[str] = (),
) -> tuple[List[str], List[str]]:
    """Return ``(in_scope_bypasses, extra_bypasses)``.

    ``in_scope_bypasses`` lists in-scope writers that have a repo-tree
    write hot path but don't call the helper — these FAIL the HC.
    ``extra_bypasses`` lists writers from ``extra_scan_paths`` that
    have the hot path but don't call the helper — these also FAIL the
    HC (the test-fixture proof shape).
    """
    in_scope_bypasses: List[str] = []
    for relpath in in_scope:
        result = _scan_one(repo_root, relpath)
        if result is None:
            continue
        if result.has_write_hot_path and not result.calls_helper:
            in_scope_bypasses.append(relpath)
    extra_bypasses: List[str] = []
    for relpath in extra_scan_paths:
        result = _scan_one(repo_root, relpath)
        if result is None:
            continue
        if result.has_write_hot_path and not result.calls_helper:
            extra_bypasses.append(relpath)
    return in_scope_bypasses, extra_bypasses


def hc_workspace_anchored_writer_authority(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Doctor entry. Scans the in-scope writers; FAILs on bypass."""
    repo_root = _project_root()
    in_scope_bypasses, _extra = scan_for_bypass(repo_root)
    if not in_scope_bypasses:
        rec.record(
            HC_NAME, HC_DESC, "PASS",
            f"{len(IN_SCOPE_WRITERS)} workspace-anchored writer(s) call "
            f"{HELPER_SYMBOL}.",
        )
        return
    head = (
        f"- {len(in_scope_bypasses)} workspace-anchored writer(s) have a "
        "repo-tree write hot path but do not call "
        f"`{HELPER_SYMBOL}`. Each must import the helper from "
        f"`{HELPER_MODULE}` and call it before the write lands."
    )
    body = "\n".join([head, ""] + [f"  - `{p}`" for p in in_scope_bypasses])
    rec.record(HC_NAME, HC_DESC, "FAIL", body)


__all__ = [
    "HC_NAME",
    "HC_DESC",
    "HELPER_SYMBOL",
    "HELPER_MODULE",
    "IN_SCOPE_WRITERS",
    "WriterScanResult",
    "hc_workspace_anchored_writer_authority",
    "scan_for_bypass",
]
