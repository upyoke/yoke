"""Bind Dash sizing and evidence to the item's own lane, not the caller's cwd.

Both surfaces answer a question about *a specific tree*: how large is this
file right now, and which tree did verification cover? Reading either from
the working directory the command happens to run in answers about whichever
checkout the harness left the shell in — usually main. The lane's own
changes then go unmeasured and unnamed, which is the failure both facts
exist to prevent.

The item's registered lane is the authority, and it is read through the
registered ``items.detail.get`` function so the answer follows the active
connection: relayed over https, dispatched in process against a local
universe. That read returns released lanes too, so evidence recorded after
the lane directory is gone still names the lane rather than main.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from yoke_cli.commands._helpers import ensure_handlers_loaded, item_target
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_core.domain.workflow_behavior import runs_without_git_lane


@dataclass(frozen=True)
class LaneTree:
    """The item's recorded implementation lane, as this machine sees it.

    ``path`` is empty when the item has no lane recorded at all — a survey
    run before the lane exists is the ordinary case. ``live`` separates a
    lane whose directory is still on disk (readable for sizing) from one
    that has been removed but still names the tree verification covered.
    ``checkout`` is this machine's mapped checkout for the item's project,
    used to size a pre-lane survey against the right repo rather than the
    caller's cwd. ``laneless`` separates "no lane yet" from "no lane ever":
    a workflow whose worktrees policy provisions none never gets a path,
    so callers must not read an empty one as a missing prerequisite.
    """

    path: str = ""
    live: bool = False
    checkout: str = ""
    laneless: bool = False


def _lane_path(item: dict[str, Any]) -> str:
    """The implementation lane's recorded path, preferring an active one."""
    lanes = [
        lane
        for lane in (item.get("worktrees") or [])
        if str(lane.get("path") or "").strip()
    ]
    if not lanes:
        return ""
    implementation = [
        lane for lane in lanes if lane.get("lane_role") == "implementation"
    ] or lanes
    active = [lane for lane in implementation if lane.get("state") == "active"]
    return str((active or implementation)[-1]["path"]).strip()


def item_lane_tree(
    raw_ref: Any,
    project: Optional[str] = None,
    session_id: Optional[str] = None,
) -> LaneTree:
    """Resolve the item's lane. An unreachable read reports no lane.

    Failing soft is deliberate: the callers each keep a local fallback, so
    a control plane that cannot be reached degrades to the previous
    behaviour instead of blocking a survey or a close-out.
    """
    ensure_handlers_loaded()
    try:
        response = call_dispatcher(
            function_id="items.detail.get",
            target=item_target("item", raw_ref, project),
            payload={},
            actor=build_actor(session_id=session_id),
        )
    except Exception:
        return LaneTree()
    if not response.success:
        return LaneTree()
    item = ((response.result or {}).get("item")) or {}
    path = _lane_path(item)
    checkout = _mapped_checkout(item)
    laneless = runs_without_git_lane(item.get("workflow") or {})
    if not path:
        return LaneTree(checkout=checkout, laneless=laneless)
    return LaneTree(
        path=path,
        live=Path(path).is_dir(),
        checkout=checkout,
        laneless=laneless,
    )


def _mapped_checkout(item: dict[str, Any]) -> str:
    """This machine's checkout for the item's project, if one is mapped."""
    project_id = (item.get("project") or {}).get("id")
    if project_id is None:
        return ""
    from yoke_cli.config.machine_config import configured_projects

    try:
        target = int(project_id)
    except (TypeError, ValueError):
        return ""
    for configured in configured_projects(existing_only=True):
        if configured.project_id == target and configured.checkout.is_dir():
            return str(configured.checkout)
    return ""


def verification_tree(
    root_override: str,
    head_override: str,
    *,
    lane_path: str,
    commit_sha: str,
) -> tuple[str, str]:
    """Name the tree a Dash evidence record describes.

    The lane is the tree that was verified and the commit being recorded is
    its head, so neither half needs the caller's working directory. The
    local resolver stays as the last fallback for an item with no recorded
    lane; when it too finds nothing the caller asks for the halves
    explicitly rather than recording an invented identity.
    """
    import importlib

    root = str(root_override).strip() or str(lane_path).strip()
    head = str(head_override).strip() or str(commit_sha).strip()
    if root and head:
        return root, head
    try:
        module = importlib.import_module(
            "yoke_core.domain.verification_tree_binding"
        )
        identity = module.resolve_tree_identity()
    except Exception:
        identity = None
    if identity is None:
        return root, head
    return root or identity.root, head or identity.head_sha


__all__ = ["LaneTree", "item_lane_tree", "verification_tree"]
