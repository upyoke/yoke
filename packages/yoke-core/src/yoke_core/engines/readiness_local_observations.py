"""Run the file-reading readiness checks where the files actually are.

The other end of
:mod:`yoke_core.domain.idea_readiness_local_inputs`. Given that module's
request — which carries the spec, the planned-claim carve-outs and the
declared rehearsal commands, all resolved by the control plane — this
runs the four checkout-dependent checks against this machine's registered
checkout and returns what they found.

Nothing here reads or writes control-plane state: it takes no connection,
and the item facts it needs arrive in the request. The checkout revision
is captured on both sides of the run so a tree edited while the checks
were reading it is reported as moved rather than passed.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def machine_checkout(project_id: Optional[int]) -> Optional[Path]:
    """This machine's registered checkout for a project, or ``None``."""
    from yoke_core.domain.project_checkout_locations import (
        checkout_for_project_id,
    )

    if project_id is None:
        return None
    candidate = checkout_for_project_id(int(project_id))
    if candidate is None or not candidate.is_dir():
        return None
    return candidate


def checkout_revision(repo_root: Path) -> str:
    """A marker that changes whenever the tree's content could have.

    Commit plus working-tree state, because a readiness check reads the
    files as they are on disk, not as they are committed. An empty string
    means the revision could not be established, which the control plane
    treats as unverifiable rather than unchanged.
    """
    head = _git(repo_root, "rev-parse", "HEAD")
    if head is None:
        return ""
    dirty = _git(repo_root, "status", "--porcelain")
    if dirty is None:
        return ""
    digest = hashlib.sha256(dirty.encode("utf-8")).hexdigest()[:16]
    return f"{head}+{digest}"


def _git(repo_root: Path, *args: str) -> Optional[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True, text=True, check=False,
        )
    except (OSError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def collect(request: Dict[str, Any], repo_root: Path) -> Dict[str, Any]:
    """Run every checkout-dependent check named in ``request``."""
    from yoke_core.domain.attestation_rehearsal_command_shape import (
        issue_payloads_for_commands,
    )
    from yoke_core.domain.idea_readiness_check import (
        verify_file_budget_line_counts,
        verify_function_owners,
    )
    from yoke_core.domain.idea_readiness_results import ReadinessOutcome
    from yoke_core.domain.idea_readiness_symlink_advisory import (
        collect_symlink_advisories,
    )

    spec_text = str(request.get("spec_text") or "")
    before = checkout_revision(repo_root)
    issues = ReadinessOutcome(issues=[
        *verify_function_owners(
            spec_text,
            repo_root=repo_root,
            suppressed_refs=set(request.get("suppressed_refs") or ()),
        ),
        *verify_file_budget_line_counts(spec_text, repo_root=repo_root),
    ]).issue_payloads()
    issues.extend(issue_payloads_for_commands(
        [str(cmd) for cmd in (request.get("rehearsal_commands") or ())],
        repo_root=repo_root,
        planned_paths=set(request.get("rehearsal_planned_paths") or ()),
        public_ref=str(request.get("item_ref") or ""),
    ))
    advisories: List[Dict[str, Any]] = (
        collect_symlink_advisories(spec_text, repo_root=repo_root)
        if spec_text else []
    )
    after = checkout_revision(repo_root)
    return {
        "spec_sha256": str(request.get("spec_sha256") or ""),
        "checks": list(request.get("checks") or ()),
        "checkout_path": str(repo_root),
        "checkout_revision": before,
        "checkout_moved": bool(before) and before != after,
        "issues": issues,
        "advisories": advisories,
    }


def collect_for_request(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Collect observations, or ``None`` when this machine has no checkout."""
    repo_root = machine_checkout(request.get("project_id"))
    if repo_root is None:
        return None
    return collect(request, repo_root)


__all__ = [
    "checkout_revision",
    "collect",
    "collect_for_request",
    "machine_checkout",
]
