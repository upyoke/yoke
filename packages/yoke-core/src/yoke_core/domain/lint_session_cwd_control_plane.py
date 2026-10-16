"""Helpers shared by the session-cwd lint family.

Centralizes:

* The Yoke control-plane carve-out for the Yoke source checkout the
  client's own Yoke code runs from — reported by the client as
  :data:`~yoke_contracts.hook_runner.client_facts.SOURCE_ROOT_KEY`, never
  derived from the evaluating process, which may be another machine.
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
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from yoke_contracts.hook_runner.client_facts import yoke_source_root
from yoke_core.domain.lint_session_cwd_host_command import (
    host_command_exemption_note,
)
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree


_YOKE_INTERNAL_MODULE_PREFIXES: Tuple[str, ...] = (
    "runtime.api.",
    "runtime.harness.",
    "runtime.agents.",
    "yoke_cli.",
    "yoke_core.",
    "yoke_harness.",
)


def is_under_yoke_control_plane(target: str, yoke_root: str) -> bool:
    """Return ``True`` when ``target`` is under the Yoke main repo
    root AND not under that repo's ``.worktrees/`` subtree.

    Sibling-branch worktrees remain claim-gated; only the Yoke repo's
    own control-plane content (``runtime/``, ``data/``, ``docs/``,
    ``.agents/`` and the repo root files) qualifies.
    """
    if not yoke_root or not target:
        return False
    t = os.path.normpath(target)
    r = os.path.normpath(yoke_root)
    if t != r and not t.startswith(r + os.sep):
        return False
    worktrees_dir = str(Path(r) / ".worktrees")
    if t == worktrees_dir or t.startswith(worktrees_dir + os.sep):
        return False
    return True


def extract_pythonpath_yoke_cwd_override(command: str, yoke_root: str) -> Optional[str]:
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
    if not command or not yoke_root:
        return None
    root = yoke_root
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
    resolved_root = os.path.normpath(yoke_root)
    for entry in value.split(":"):
        candidate = entry.strip()
        if not candidate:
            continue
        resolved = os.path.normpath(candidate)
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
    "target path, or use a control-plane path.\n"
    "Cross-repo item (the target is another project's repo): worktree "
    "preparation resolves the ITEM's project checkout from the machine "
    "mapping — register a missing mapping with `yoke project register "
    "<checkout> --project-id <id>`, or repair a wrong-repo lane with "
    "`yoke item-worktrees path-record` — the claim then covers the "
    "recorded lane."
)


def build_scope_mismatch_block(
    *,
    offending_target: str,
    claims: Sequence[ClaimedWorktree],
    repo_roots: Sequence[str],
    command: str = "",
    yoke_root: str = "",
) -> str:
    """Render the BLOCKED message body for a scope-mismatch refusal.

    ``command`` is the Bash body the deny came from, when there is one.
    A refused ``yoke qa mission host-command`` call gets a closing
    clause naming the remote-argv exemption, so a caller whose remote
    paths were already exempted can see that the target above came from
    the locally-running part of the call.
    """
    body = SCOPE_MISMATCH_TEMPLATE.format(
        target=offending_target,
        claims_block=render_claims_block(claims),
        allowed_block=render_allowed_block(repo_roots, yoke_root=yoke_root),
    )
    return body + host_command_exemption_note(command)


def render_claims_block(claims: Sequence[ClaimedWorktree]) -> str:
    from yoke_core.domain.project_identity_item_ref import item_ref_for_id

    if not claims:
        return "  (none)\n"
    lines: List[str] = []
    for c in claims:
        ref = item_ref_for_id(int(c.item_id))
        label = f"{ref} (T{c.task_num})" if c.task_num is not None else ref
        lines.append(f"  - {label}: {c.worktree_path}")
    return "\n".join(lines) + "\n"


def render_allowed_block(repo_roots: Sequence[str], *, yoke_root: str = "") -> str:
    """Render the allowed-targets listing.

    Names every recorded **project** control plane (any checkout's repo
    root, not only the claimed project's) distinctly from the **Yoke**
    control plane (the Yoke main repo root). When the two are the same
    install, the Yoke line is suppressed to avoid a duplicate.
    """
    lines = ["  - Any claimed worktree above"]
    if repo_roots:
        joined = ", ".join(repo_roots)
        lines.append(f"  - Any project control plane: {joined} (excluding .worktrees/)")
    if yoke_root and yoke_root not in repo_roots:
        lines.append(f"  - Yoke control plane: {yoke_root} (excluding .worktrees/)")
    lines.append("  - Free paths: /tmp, /var/folders/...")
    return "\n".join(lines) + "\n"


def resolve_authority_cwd(payload: Mapping[str, Any]) -> str:
    """Return the cwd used as the synthetic target for validation.

    Bash commands shaped as
    ``[env...] PYTHONPATH=<yoke-main-root> python[3] -m runtime.<X>``
    are treated as Yoke-internal regardless of the launching cwd, so
    the override substitutes the Yoke main root. Otherwise the declared
    call workdir wins, then a usable payload cwd or project root. A bare
    app-container root is ignored because it is not a filesystem target.
    """
    from yoke_core.domain.lint_session_cwd_target_extract import (
        extract_payload_command,
        resolve_payload_cwd,
    )

    command = extract_payload_command(payload) if isinstance(payload, Mapping) else ""
    if command:
        override = extract_pythonpath_yoke_cwd_override(
            command, yoke_source_root(payload)
        )
        if override:
            return override
    return resolve_payload_cwd(payload)


__all__ = [
    "SCOPE_MISMATCH_TEMPLATE",
    "build_scope_mismatch_block",
    "extract_pythonpath_yoke_cwd_override",
    "is_under_yoke_control_plane",
    "render_allowed_block",
    "render_claims_block",
    "resolve_authority_cwd",
]
