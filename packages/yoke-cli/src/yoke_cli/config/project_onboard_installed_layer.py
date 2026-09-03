"""Act on the operator's decision about a layer the checkout already carries.

Onboarding materializes the checkout before Review so the operator can see
what the repository actually contains, and records keep-or-remove with the
clone plan. Apply reaches this module once the folder exists and before the
project install writes anything: it removes the layer when that was the
decision, and refuses when no decision was ever made — installing over a
repository nobody looked at is how a "first install" silently converges
hundreds of files somebody else's install left behind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import onboard_apply_progress
from yoke_cli.config import project_installed_layer as layer
from yoke_cli.config import project_installed_layer_removal
from yoke_cli.config.project_onboard_support import ProjectOnboardError
from yoke_cli.project_install.source_dev import is_yoke_source_checkout

REMOVE_LAYER_ACTION = "project-remove-installed-layer"


def apply_decision(
    root: Path,
    decision: str,
    *,
    progress: onboard_apply_progress.ProgressCallback | None = None,
) -> dict[str, Any] | None:
    """Remove, keep, or refuse — return the removal report when one ran.

    A checkout carrying no layer needs no decision, and the Yoke source
    checkout is exempt: the layer there is the repository's own tracked
    content, not an installed copy.
    """
    scan = layer.scan(root)
    if not scan.present or is_yoke_source_checkout(root):
        return None
    selected = str(decision or "").strip()
    if selected == layer.LAYER_DECISION_KEEP:
        return None
    if selected != layer.LAYER_DECISION_REMOVE:
        raise ProjectOnboardError(uninspected_message(scan))
    with onboard_apply_progress.step(progress, REMOVE_LAYER_ACTION, str(root)):
        return project_installed_layer_removal.remove(root)


def uninspected_message(scan: layer.InstalledLayerScan) -> str:
    """Name the layer found and both ways past it."""
    release = (
        f" installed by Yoke {scan.source_engine_release}"
        if scan.source_engine_release
        else ""
    )
    listed = ", ".join(
        f"{group.rel} ({group.file_count})" for group in scan.groups
    )
    return (
        f"{scan.root} already carries a Yoke operating layer{release}: "
        f"{scan.file_count} files across {listed}. Onboarding will not install "
        "over a repository nobody inspected. Choose what happens to it: pass "
        f"--existing-yoke-layer {layer.LAYER_DECISION_REMOVE} to strip it "
        f"first, or --existing-yoke-layer {layer.LAYER_DECISION_KEEP} to "
        "install over it. The wizard asks the same question on its checkout "
        "inspection screen."
    )


__all__ = ["REMOVE_LAYER_ACTION", "apply_decision", "uninspected_message"]
