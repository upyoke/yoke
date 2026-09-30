"""Client-local authored-file sizing for path-selection surfaces."""

from __future__ import annotations

import pathlib
import subprocess
from typing import Any, Mapping


def _repo_root() -> pathlib.Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        errors="replace",
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return pathlib.Path(result.stdout.strip()).resolve()


def survey_path_sizes(
    paths: list[str], *, tree_root: str | None = None,
) -> list[dict[str, Any]]:
    """Describe current line pressure for every surveyed project path.

    ``tree_root`` names the tree to measure. Callers that know which tree
    the survey is about — the Dash survey knows its item's lane — pass it,
    because the ambient checkout answers about main and so reports a lane's
    grown file at its pre-change size and a lane's new file at zero. Only
    when no tree is named does this fall back to the working directory.
    """
    try:
        from yoke_harness.git_hooks import file_line_check
    except ImportError as exc:
        raise RuntimeError(
            "Dash survey sizing requires yoke-harness; install/repair the "
            f"product helper package ({exc})."
        ) from exc
    root = pathlib.Path(tree_root) if tree_root else _repo_root()
    if root is None:
        raise RuntimeError("Dash survey sizing requires a local git checkout.")
    policy = file_line_check.resolved_policy(root)
    results: list[dict[str, Any]] = []
    for raw_path in paths:
        path = raw_path.removeprefix("./")
        classification = file_line_check.classify_path(path, repo_root=root)
        count = file_line_check.line_count_file(root / path)
        results.append({
            "path": path,
            "current_line_count": count,
            "remaining_headroom": policy.limit - count,
            "at_or_over_limit": count >= policy.limit,
            "limit": policy.limit,
            "classification": classification.value,
            # A surveyed path the work will CREATE is indistinguishable from
            # an existing one by size alone: both a new file and an empty
            # file count zero lines. Saying so stops the next reader from
            # opening a file that is not there yet, or selecting it as a
            # test target before the change authors it.
            "exists": (root / path).exists(),
        })
    return results


EXISTENCE_LABELS = {True: "existing", False: "new", None: "unknown"}


def path_existence_label(
    size: Mapping[str, Any],
    local: Mapping[str, bool] | None = None,
) -> str:
    """How a receipt names one sized path: ``existing``, ``new``, ``unknown``.

    Whether a path exists is a fact only the client holding the tree can
    measure, so a response echo that carries no marker — a server build
    that predates the field drops it — falls back to *local*, the rows
    this client sized. ``unknown`` is what remains when neither answered,
    and is deliberately not ``new``: a missing answer is not the claim
    that the work will create the file.
    """
    exists = size.get("exists")
    if exists is None and local is not None:
        exists = local.get(str(size.get("path") or ""))
    return EXISTENCE_LABELS.get(exists, "unknown")


__all__ = ["EXISTENCE_LABELS", "path_existence_label", "survey_path_sizes"]
