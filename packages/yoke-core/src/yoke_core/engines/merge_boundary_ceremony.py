"""Refusing a bare merge of a standalone item branch.

A standalone item branch — one owning no epic lane — carries bookkeeping the
merge engine does not: the execution evidence record, the GitHub sync, and the
terminal lifecycle transition that runs the item's own gates. The boundary
that owns all of it drives the engine in-process, so an engine invoked from a
command line is by construction only half the boundary: it lands the branch,
prints ``Successfully merged``, and leaves the item behind in a state its own
workflow says is still in flight.

The refusal is the same shape the ``status=done`` guard uses, and for the same
reason: a sanctioned path that runs in-process needs no nonce, so requiring
one separates the two callers exactly. An operator who means to run the engine
alone spends a nonce and gets it; anything else is told which entrypoint
completes the boundary it was reaching for.
"""

from __future__ import annotations

from yoke_core.api.service_client_shared_done_ceremony import (
    consume_one_shot_nonce,
)


MERGE_CEREMONY_NONCE_ENV = "YOKE_MERGE_NONCE"


def refuse_bare_standalone_merge(branch: str) -> str:
    """Empty when this invocation may merge ``branch``, else why it may not.

    Lanes are named after the item they carry, so the branch name is what the
    recovery recipe addresses; an operator holding a differently named branch
    still reads the entrypoint to use from it.
    """
    if consume_one_shot_nonce(MERGE_CEREMONY_NONCE_ENV):
        return ""
    item = branch or "<ITEM>"
    return (
        f"Cannot merge standalone item branch '{item}' from the merge engine "
        "directly — missing merge-boundary ceremony nonce.\n"
        "  A standalone item branch lands through the boundary that also "
        "records its evidence and drives its terminal transition.\n"
        "  Merging here reports success for a boundary it did not complete.\n"
        f"  Use: yoke merge item {item} --result \"<what changed>\" "
        "--verification \"<checks run>\"\n"
        f"  Or:  /yoke usher {item}"
    )


__all__ = ["MERGE_CEREMONY_NONCE_ENV", "refuse_bare_standalone_merge"]
