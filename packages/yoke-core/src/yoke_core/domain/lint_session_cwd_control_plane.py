"""Helpers shared by the session-cwd lint family.

Centralizes:

* Resolution of the Yoke main repo root (the install location of the
  Python module tree running this hook), so the lint can recognise its
  own control plane without relying on the calling cwd or the claimed
  project's repo path.
* The bounded carve-out predicate that authorises reads under the
  Yoke control plane while keeping sibling-branch worktrees
  (``<yoke-root>/.worktrees/<other-branch>/...``) claim-gated.
* PYTHONPATH equivalence parsing for Yoke-internal Python
  invocations launched from a non-Yoke cwd. A leading
  ``PYTHONPATH=<yoke-main-root>`` paired with ``python[3] -m
  runtime.<X>`` or ``python[3] -c '...runtime.api...'`` is treated as
  cwd-equivalent — the validator authorises the call as if the harness
  cwd were the Yoke main root.

The front door (:mod:`lint_session_cwd`), validator
(:mod:`lint_session_cwd_validate`) and target extractor
(:mod:`lint_session_cwd_target_extract`) each consume the predicates
here instead of restating the rules.
"""

from __future__ import annotations

import os
import shlex
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree


_YOKE_INTERNAL_MODULE_PREFIXES: Tuple[str, ...] = (
    "runtime.api.",
    "runtime.harness.",
    "runtime.agents.",
    "yoke_cli.",
    "yoke_core.",
    "yoke_harness.",
)


def yoke_main_root() -> Optional[str]:
    """Return the Yoke main repo root, or ``None`` on resolution failure.

    The location is derived from this module's own ``__file__`` so the
    answer is independent of harness cwd, ``CLAUDE_PROJECT_DIR`` and
    ``YOKE_ROOT``. A worktree-installed copy of the file is stripped
    back to the main repo root via
    :func:`yoke_core.domain.worktree_paths._strip_worktree_path`.
    The result is cached for the process lifetime — the install root
    cannot change while the interpreter runs.
    """
    return _cached_yoke_main_root()


@lru_cache(maxsize=1)
def _cached_yoke_main_root() -> Optional[str]:
    try:
        from yoke_core.domain.worktree_paths import _strip_worktree_path
    except ImportError:
        return None
    try:
        here = Path(__file__).resolve()
    except OSError:
        return None
    try:
        from yoke_core.api.repo_root import find_repo_root
    except ImportError:
        return None
    try:
        candidate = str(find_repo_root(here))
    except Exception:
        return None
    try:
        stripped = _strip_worktree_path(candidate)
    except Exception:
        return None
    if not stripped:
        return None
    try:
        return str(Path(stripped).resolve())
    except OSError:
        return stripped


def is_under_yoke_control_plane(target: str) -> bool:
    """Return ``True`` when ``target`` is under the Yoke main repo
    root AND not under that repo's ``.worktrees/`` subtree.

    Sibling-branch worktrees remain claim-gated; only the Yoke repo's
    own control-plane content (``runtime/``, ``data/``, ``docs/``,
    ``.agents/`` and the repo root files) qualifies.
    """
    root = yoke_main_root()
    if not root or not target:
        return False
    try:
        t = str(Path(target).resolve())
        r = str(Path(root).resolve())
    except OSError:
        return False
    if t != r and not t.startswith(r + os.sep):
        return False
    worktrees_dir = str(Path(r) / ".worktrees")
    if t == worktrees_dir or t.startswith(worktrees_dir + os.sep):
        return False
    return True


def extract_pythonpath_yoke_cwd_override(command: str) -> Optional[str]:
    """Return the Yoke main root when ``command`` is a Yoke-internal
    Python invocation guarded by ``PYTHONPATH=<yoke-main-root>``.

    Recognized shapes (after the optional ``cd ... &&`` prefix is
    skipped)::

        [other env...] PYTHONPATH=/path/to/yoke python3 -m runtime.api.X
        [other env...] PYTHONPATH=/path/to/yoke python3 -m runtime.harness.X
        [other env...] PYTHONPATH=/path/to/yoke python3 -c "...runtime.api..."

    Returns ``None`` for any other shape (no ``PYTHONPATH``, foreign
    ``PYTHONPATH`` value, non-python head, or a python target that is
    not a Yoke-internal module). Keeping the predicate narrow
    preserves the worktree-isolation invariant: arbitrary commands do
    not gain Yoke authority just because they prefix an env var.
    """
    if not command:
        return None
    root = yoke_main_root()
    if not root:
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None

    # Skip an optional ``cd <dir> &&`` prefix; shlex collapses ``&&``
    # into a literal token between the two clauses, so the second
    # clause starts after the first ``&&`` token in the stream.
    idx = _skip_cd_prefix(tokens)

    pythonpath_value: Optional[str] = None
    while idx < len(tokens):
        tok = tokens[idx]
        if "=" not in tok or tok.startswith("-"):
            break
        head, value = tok.split("=", 1)
        if not _looks_like_env_assignment_head(head):
            break
        if head == "PYTHONPATH":
            pythonpath_value = value
        idx += 1

    if pythonpath_value is None:
        return None
    if idx >= len(tokens):
        return None
    if not _pythonpath_matches_yoke(pythonpath_value, root):
        return None
    if not _is_yoke_internal_python_invocation(tokens[idx:]):
        return None
    return root


def _skip_cd_prefix(tokens: List[str]) -> int:
    """Return the index after an optional leading ``cd <dir> &&`` pair.

    Anything that does not match the exact ``cd <dir> &&`` shape is
    ignored — the caller starts at index 0 instead.
    """
    if len(tokens) >= 3 and tokens[0] == "cd" and tokens[2] == "&&":
        return 3
    return 0


def _looks_like_env_assignment_head(head: str) -> bool:
    if not head:
        return False
    if not head[0].isalpha() and head[0] != "_":
        return False
    return all(ch == "_" or ch.isalnum() for ch in head)


def _pythonpath_matches_yoke(value: str, yoke_root: str) -> bool:
    """Return ``True`` when at least one ``PYTHONPATH`` entry resolves
    to the Yoke main root (or a subdirectory of it)."""
    if not value:
        return False
    try:
        resolved_root = str(Path(yoke_root).resolve())
    except OSError:
        return False
    for entry in value.split(":"):
        candidate = entry.strip()
        if not candidate:
            continue
        try:
            resolved = str(Path(candidate).resolve())
        except OSError:
            continue
        if resolved == resolved_root:
            return True
        if resolved.startswith(resolved_root + os.sep):
            return True
    return False


def _is_yoke_internal_python_invocation(tokens: List[str]) -> bool:
    """Return ``True`` when ``tokens`` starts with ``python[3] -m
    a Yoke package module or ``python[3] -c`` code imports one."""
    if not tokens:
        return False
    head = Path(tokens[0]).name
    if head not in ("python", "python3"):
        return False
    if len(tokens) < 3:
        return False
    flag = tokens[1]
    body = tokens[2]
    if flag == "-m":
        return any(body.startswith(p) for p in _YOKE_INTERNAL_MODULE_PREFIXES)
    if flag == "-c":
        return any(p.rstrip(".") in body for p in _YOKE_INTERNAL_MODULE_PREFIXES)
    return False


SCOPE_MISMATCH_TEMPLATE = (
    "BLOCKED: Tool call targets {target} but the session does not hold "
    "an active claim on a worktree covering this path.\n\n"
    "Active claims this session:\n"
    "{claims_block}"
    "Allowed targets:\n"
    "{allowed_block}"
    "Remediation: Acquire a claim on the intended worktree, correct the "
    "target path, or use a control-plane path."
)


ORIENTATION_HEADING = "## ⚠ session-claim-target-mismatch"


def build_scope_mismatch_block(
    *,
    offending_target: str,
    claims: Sequence[ClaimedWorktree],
    repo_roots: Sequence[str],
) -> str:
    """Render the BLOCKED message body shared by deny + orientation."""
    return SCOPE_MISMATCH_TEMPLATE.format(
        target=offending_target,
        claims_block=render_claims_block(claims),
        allowed_block=render_allowed_block(repo_roots),
    )


def render_claims_block(claims: Sequence[ClaimedWorktree]) -> str:
    if not claims:
        return "  (none)\n"
    lines: List[str] = []
    for c in claims:
        label = (
            f"YOK-{c.item_id} (T{c.task_num})"
            if c.task_num is not None
            else f"YOK-{c.item_id}"
        )
        lines.append(f"  - {label}: {c.worktree_path}")
    return "\n".join(lines) + "\n"


def render_allowed_block(repo_roots: Sequence[str]) -> str:
    """Render the allowed-targets listing.

    Names the **project** control plane (the claimed project repo root)
    distinctly from the **Yoke** control plane (the Yoke main repo
    root). When the two are the same install, the Yoke line is
    suppressed to avoid a duplicate.
    """
    lines = ["  - Any claimed worktree above"]
    if repo_roots:
        joined = ", ".join(repo_roots)
        lines.append(
            f"  - Project control plane: {joined} (excluding .worktrees/)"
        )
    root = yoke_main_root()
    if root and root not in repo_roots:
        lines.append(
            f"  - Yoke control plane: {root} (excluding .worktrees/)"
        )
    lines.append("  - Free paths: /tmp, /var/folders/...")
    return "\n".join(lines) + "\n"


def resolve_authority_cwd(payload: Mapping[str, Any]) -> str:
    """Return the cwd used as the synthetic target for validation.

    Bash commands shaped as
    ``[env...] PYTHONPATH=<yoke-main-root> python[3] -m runtime.<X>``
    are treated as Yoke-internal regardless of the launching cwd, so
    the override substitutes the Yoke main root. Otherwise the
    payload's own ``cwd`` (or ``os.getcwd()``) is returned unchanged.
    """
    from yoke_core.domain.lint_session_cwd_target_extract import (
        extract_payload_command,
    )

    command = extract_payload_command(payload) if isinstance(payload, Mapping) else ""
    if command:
        override = extract_pythonpath_yoke_cwd_override(command)
        if override:
            return override
    if isinstance(payload, Mapping):
        raw = payload.get("cwd")
        if isinstance(raw, str) and raw.strip():
            return raw
    return os.getcwd()


__all__ = [
    "ORIENTATION_HEADING",
    "SCOPE_MISMATCH_TEMPLATE",
    "build_scope_mismatch_block",
    "extract_pythonpath_yoke_cwd_override",
    "is_under_yoke_control_plane",
    "render_allowed_block",
    "render_claims_block",
    "resolve_authority_cwd",
    "yoke_main_root",
]
