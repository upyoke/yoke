"""What a verification tree-binding verdict says to the reader.

Split from :mod:`yoke_core.domain.verification_tree_binding` so the decision
logic and the words it renders can be read and changed separately. The
decision is small; the wording carries the weight, because every one of these
strings is the last thing an agent or a person sees before they act.

The governing rule for all of them: **name a recovery that exists.** A refusal
that points at a deleted directory, or advertises a flag no surface accepts,
converts a blocked run into a hunt for an exit that was never there. Each
refusal here is paired with the state that makes its advice true — a live
worktree to ``cd`` into, or a removed one to re-materialize.
"""

from __future__ import annotations

#: Wrapper/CLI flag that runs a deliberate cross-tree verification. Accepted
#: by ``yoke watch pytest``, ``yoke qa case run``, and ``yoke qa plan run`` —
#: every surface whose refusal advertises it.
ALLOW_TREE_MISMATCH_FLAG = "--allow-tree-mismatch"

#: Refusal for a claimed lane that still exists on disk: the reader can go
#: there, so the recovery is to go there.
TREE_BINDING_REFUSAL_TEMPLATE = (
    "{surface} TREE-BINDING REFUSAL: session {sid} holds an active "
    "work-claim with worktree '{wt}', but this run would execute in "
    "'{tree}', outside that worktree. Verification that runs in the wrong "
    "tree reports a green for code nobody changed.\n"
    "To verify the claimed worktree:\n"
    '  cd "{wt}"\n'
    f"and re-run, or pass {ALLOW_TREE_MISMATCH_FLAG} for a deliberate "
    "cross-tree run."
)

#: Refusal for a claimed lane whose directory is gone while its row is still
#: active. ``cd`` into the recorded path would name a directory that does not
#: exist, so this names the two recoveries that do work: re-materialize the
#: lane, or verify the tree as it stands.
MISSING_LANE_REFUSAL_TEMPLATE = (
    "{surface} TREE-BINDING REFUSAL: session {sid} holds an active "
    "work-claim whose recorded worktree '{wt}' no longer exists on disk, "
    "and this run would execute in '{tree}'. An active lane row pointing "
    "at a removed directory is stale bookkeeping, not a tree to verify.\n"
    "Re-materialize the lane and re-run there:\n"
    "  yoke direct-workflow worktree prepare {item} --workflow <workflow>\n"
    f"or pass {ALLOW_TREE_MISMATCH_FLAG} to verify '{{tree}}' as it stands."
)

ALLOW_TREE_MISMATCH_NOTICE = (
    f"{{surface}}: {ALLOW_TREE_MISMATCH_FLAG} — verifying '{{tree}}' while "
    "the claimed worktree is '{wt}'."
)

UNVERIFIED_BINDING_NOTICE = (
    "{surface}: could not confirm '{tree}' is this session's claimed "
    "worktree — the control plane did not answer ({detail}). Proceeding "
    "unverified; if this run matters, confirm the tree yourself."
)


__all__ = [
    "ALLOW_TREE_MISMATCH_FLAG",
    "ALLOW_TREE_MISMATCH_NOTICE",
    "MISSING_LANE_REFUSAL_TEMPLATE",
    "TREE_BINDING_REFUSAL_TEMPLATE",
    "UNVERIFIED_BINDING_NOTICE",
]
