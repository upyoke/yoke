"""Snapshot pre-warm helper for the done-transition engine.

Extracted from :mod:`yoke_core.engines.done_transition_runner` to keep
that module under its 350-line file-line cap. The single responsibility
is: after a commit lands, build (or look up) the ``path_snapshots`` row
for the project's new HEAD so subsequent activate / boundary callers do
not hit a cold-start miss before the global ``post-commit`` hook has
fired.

Failures here are advisory — a snapshot miss does not roll back the
done-transition; the next ``path-claim-activate`` call will surface a
clearer error if it matters.
"""

from __future__ import annotations

import subprocess


def ensure_snapshot_for_item(item_id: int) -> None:
    """Pre-warm the path-snapshot cache for the item's project at HEAD.

    The DB touches route through the connected transport: the item's
    project slug relays through ``done_transition.item_field``, the
    machine-local checkout resolves through the transport-aware
    ``checkout_for_project_slug`` (``projects.get`` relay + local checkout
    map), the new HEAD is resolved locally with git, and the snapshot write
    relays through ``project.snapshot.ensure_at`` (which walks the commit
    tree server-side). Failures stay advisory — a snapshot miss does not
    roll back the done-transition; the next activate call surfaces a
    clearer error if it matters.
    """
    try:
        from yoke_contracts.api.function_call import TargetRef
        from yoke_core.api.service_client_structured_api_adapter import (
            call_dispatcher,
        )
        from yoke_core.domain.project_checkout_locations import (
            checkout_for_project_slug,
        )
        from yoke_core.engines.done_transition_runtime import _query_item_field

        project_slug = _query_item_field(item_id, "project")
        if not project_slug:
            return
        checkout = checkout_for_project_slug(project_slug)
        if checkout is None:
            return
        head = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False,
        )
        if head.returncode != 0 or not head.stdout.strip():
            return
        resp = call_dispatcher(
            function_id="project.snapshot.ensure_at",
            target=TargetRef(kind="global"),
            payload={"project": project_slug, "commit_sha": head.stdout.strip()},
        )
        if not resp.success:
            message = resp.error.message if resp.error else "unknown error"
            print(f"  Note: ensure_snapshot_at advisory: {message}")
    except Exception as exc:  # noqa: BLE001
        print(f"  Note: ensure_snapshot_at advisory: {exc}")


__all__ = ["ensure_snapshot_for_item"]
