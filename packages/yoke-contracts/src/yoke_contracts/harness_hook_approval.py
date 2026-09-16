"""Per-harness hook-approval gates and the trust teaching they render.

A harness runs Yoke's hook chain only after the operator approves it when
that harness has a readable approval gate. Codex records a per-hook
``trusted_hash`` keyed by the hook file's path and content. Claude Code
does not gate hooks on folder-trust on the probed builds. Cursor is
absent because vendor docs do not declare a hook-specific approval
requirement — not because an unreadable receipt proves there is no
trust gate. That unreadability is why an invented Cursor prompt used
to be declared here. Teaching a prompt the vendor does not document
would invent a hook-approval gate. Workspace trust remains a separate
gate.

Cited 2026-09-16 from https://cursor.com/docs/hooks: project
``.cursor/hooks.json`` automatically loads in a trusted workspace;
hooks require that trust for security; Cursor reloads ``hooks.json`` on
save. The page does not document a hook-specific approval or reapproval
prompt. Desktop and CLI both fire hooks (CLI omits some events);
cloud agents load project hooks; user-level ``~/.cursor/hooks.json``
is not available to cloud agents. Workspace trust
(https://cursor.com/docs/agent/security) is a separate VS Code gate,
disabled by default — not a hook-approval prompt. Absence from docs is
not a runtime guarantee that some build cannot prompt; it is why this
mapping must not invent one. Measured first-run in a never-opened
directory (``docs/harness-cursor-assessment.md``) had zero enablement
ceremony.

A harness with a gate whose approval is missing simply never runs the
hooks, so nothing errors and the session looks ordinary while none of
its telemetry is written.

Two surfaces in different packages have to agree about that gate:

* the installer and onboarding wizard, which name operator-owned approval
  steps after writing hook glue; Yoke's separate install policy mints Codex
  hashes only for the exact hooks file the install authored;
* the Overview's harness activation module, which reports hook health and
  needs the remediation to name the harness's own approval surface.

Both read the declarations below instead of branching on a harness id, so
a harness with no entry has no declared hook-specific approval
requirement, and neither surface invents a hook-approval step for it.
Lives in ``yoke-contracts`` because the installer package and the
engine never import each other, and both render the same wording.
"""

from __future__ import annotations

from typing import Dict, Mapping, Optional


#: Official Cursor hooks page used to keep Cursor out of this mapping.
CURSOR_HOOKS_DOC_URL = "https://cursor.com/docs/hooks"
CURSOR_HOOKS_DOC_RETRIEVED = "2026-09-16"


HARNESS_HOOK_APPROVAL: Dict[str, Mapping[str, str]] = {
    "codex": {
        "trust_surface": "Codex's hook-trust prompt",
        "grant_scope": ("per project checkout and per hook-file content hash"),
    },
}
"""Canonical harness id -> its hook-approval gate.

``trust_surface`` names where the operator grants approval; ``grant_scope``
says what the grant is keyed to, which is what makes an update re-require
it. A harness absent from this mapping has no declared hook-specific
approval requirement.
"""


def hook_approval(harness_id: str) -> Optional[Mapping[str, str]]:
    """Return the declared hook-specific approval gate, or ``None``."""
    return HARNESS_HOOK_APPROVAL.get(str(harness_id or "").strip().lower())


def trust_teaching(harness_id: str) -> Optional[str]:
    """The operator-owned approval sentence for this harness's glue.

    ``None`` when no hook-specific approval requirement is declared, so
    callers stay free of harness-id branching.
    """
    gate = hook_approval(harness_id)
    if gate is None:
        return None
    return (
        f"Trust this project's hooks in {gate['trust_surface']} — trust is "
        f"granted {gate['grant_scope']}, so writing or updating the glue "
        "re-requires it, and untrusted hooks fail silently (no tool "
        "telemetry, no heartbeats)."
    )


__all__ = [
    "CURSOR_HOOKS_DOC_RETRIEVED",
    "CURSOR_HOOKS_DOC_URL",
    "HARNESS_HOOK_APPROVAL",
    "hook_approval",
    "trust_teaching",
]
