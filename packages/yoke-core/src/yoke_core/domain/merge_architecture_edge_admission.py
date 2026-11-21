"""Refuse a landing that adds an architecture edge the map forbids.

The merge boundary runs on the machine that holds the repository, so it
reads the candidate from git and the map from the control plane. It scans
only the Python files the lane changed, at the candidate and at the merge
base, and refuses an edge that is forbidden at the candidate, absent at the
base, and not frozen in the committed baseline. The baseline is read only
from commits (``git show``), never the working tree, and may only shrink: a
lane whose baseline gains an entry the target's lacks is refused too.

Full-tree scans stay in Doctor (stored snapshot) and in baseline generation
(:mod:`yoke_core.tools.architecture_edge_baseline`). GitHub UI merges and
direct pushes bypass this gate; Doctor reports what they let through.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.runtime_ports.structured_dispatch import get_structured_dispatch

from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.architecture_tree_scan import (
    BASELINE_PATH,
    BaselineError,
    ForbiddenEdge,
    LayerMap,
    forbidden_edges,
    parse_baseline,
)

call_dispatcher = get_structured_dispatch().call_dispatcher

GATE = "architecture edges"
MODEL_FUNCTION_ID = "project_structure.get"
_UNSERVED_ERROR_CODES = frozenset({"function_version_skew", "function_not_registered"})
_LISTED = 20


def _note(message: str) -> None:
    print(f"[phase:admission] {GATE}: {message}", file=sys.stderr, flush=True)


def _git(repo_root: str, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        input=stdin.encode("utf-8") if stdin is not None else None,
        capture_output=True,
        check=False,
    )


def _git_text(repo_root: str, *args: str) -> Optional[str]:
    result = _git(repo_root, *args)
    return result.stdout.decode("utf-8", "replace") if result.returncode == 0 else None


def show(repo_root: str, commit: str, path: str) -> Optional[str]:
    """The file at ``commit:path``, or None when that commit lacks it."""
    return _git_text(repo_root, "show", f"{commit}:{path}")


def tree_paths(repo_root: str, commit: str) -> List[str]:
    listing = _git_text(repo_root, "ls-tree", "-r", "--name-only", "-z", commit)
    if listing is None:
        raise RuntimeError(f"git ls-tree {commit} failed in {repo_root}")
    return [path for path in listing.split("\0") if path]


def read_blobs(repo_root: str, commit: str, paths: Sequence[str]) -> Dict[str, str]:
    """Each path's text at ``commit`` in one ``git cat-file --batch`` call."""
    if not paths:
        return {}
    result = _git(
        repo_root, "cat-file", "--batch",
        stdin="".join(f"{commit}:{path}\n" for path in paths),
    )
    if result.returncode != 0:
        raise RuntimeError(f"git cat-file --batch failed in {repo_root}")
    data, offset, out = result.stdout, 0, {}
    for path in paths:
        end = data.index(b"\n", offset)
        header = data[offset:end].split()
        offset = end + 1
        if len(header) == 3:
            size = int(header[2])
            out[path] = data[offset:offset + size].decode("utf-8", "replace")
            offset += size + 1
    return out


def lane_changes(repo_root: str, base: str, commit: str) -> List[Tuple[str, str]]:
    """``(base path, candidate path)`` for each added, changed or renamed file."""
    listing = _git_text(repo_root, "diff", "--name-status", "-M", "-z", base, commit)
    if listing is None:
        raise RuntimeError(f"git diff {base} {commit} failed in {repo_root}")
    fields, changes, index = listing.split("\0"), [], 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        if status[0] in "RC":
            changes.append((fields[index + 1], fields[index + 2]))
            index += 3
            continue
        if status[0] in "AM":
            changes.append(("" if status[0] == "A" else fields[index + 1], fields[index + 1]))
        index += 2
    return changes


def read_model(project: str, dispatch: Callable[..., Any]) -> Tuple[Optional[dict], str]:
    """``(model, refusal)``; a model of None with no refusal means skip."""
    response = dispatch(
        function_id=MODEL_FUNCTION_ID,
        target=TargetRef(kind="project_structure", project_id=project),
        payload={"project_id": project, "family": "architecture_model"},
    )
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        code = str(getattr(error, "code", "") or "")
        if code in _UNSERVED_ERROR_CODES:
            _note(f"architecture_model read not served ({code}); landing proceeds")
            return None, ""
        detail = getattr(error, "message", None) or code or "read failed"
        return None, compose_refusal(
            f"architecture_model_unreadable: {project}: {detail}. Nothing has been merged",
            recovery="resolve the control-plane read "
            f"(`yoke project-structure get --project {project} --family "
            "architecture_model`), then re-run this merge",
        )
    entries = (getattr(response, "result", None) or {}).get("entries") or []
    payload = entries[0].get("payload") if entries else None
    if not isinstance(payload, Mapping):
        _note(f"{project} declares no architecture_model; skipped")
        return None, ""
    return dict(payload), ""


def _refusal(public_ref: str, project: str, reason: str, lines: List[str], recovery: str) -> str:
    shown = lines[:_LISTED] + (
        [f"... and {len(lines) - _LISTED} more"] if len(lines) > _LISTED else []
    )
    return compose_refusal(
        f"{reason} ({public_ref}). Nothing has been merged",
        evaluated="\n".join(f"- {line}" for line in shown),
        recovery=recovery.format(project=project),
    )


_EDGE_RECOVERY = (
    "change the import to go through a layer the importing layer may depend on, "
    "or, when the dependency is justified, change the map through Project Structure "
    "(`yoke project-structure patch --project {project} --family architecture_model "
    "--help`); then re-run this merge"
)
_GROWTH_RECOVERY = (
    f"remove the added entries from {BASELINE_PATH} (it only shrinks) and fix the "
    "imports, or change the map through Project Structure "
    "(`yoke project-structure patch --project {project} --family architecture_model "
    "--help`); then re-run this merge"
)


def architecture_edge_refusal(
    *,
    item_id: int,
    public_ref: str,
    commit_sha: str,
    target: str,
    repo_root: str,
    project: str,
    dispatch: Callable[..., Any] = call_dispatcher,
) -> str:
    """Why this candidate adds a forbidden edge, or empty when it does not."""
    ref = public_ref or str(item_id)
    commit = str(commit_sha or "").strip()
    if not commit:
        return ""
    candidate_text = show(repo_root, commit, BASELINE_PATH)
    if candidate_text is None:
        _note(f"{commit[:12]} commits no {BASELINE_PATH}; skipped")
        return ""
    model, refusal = read_model(project, dispatch)
    if refusal or model is None:
        return refusal
    base_ref = git.current_base_ref(repo_root, target)
    merge_base = (_git_text(repo_root, "merge-base", base_ref, commit) or "").strip()
    if not merge_base:
        return compose_refusal(
            f"architecture_edges_unscanned: no merge base between {commit[:12]} "
            f"and {base_ref} ({ref}). Nothing has been merged",
            recovery=f"fetch {target} and rebase the lane onto it, then re-run this merge",
        )
    try:
        frozen = parse_baseline(candidate_text)
        target_text = show(repo_root, base_ref, BASELINE_PATH)
        target_frozen = parse_baseline(target_text) if target_text is not None else None
    except BaselineError as exc:
        return compose_refusal(
            f"architecture_baseline_malformed: {exc} ({ref}). Nothing has been merged",
            recovery=f"regenerate it with `python -m yoke_core.tools.architecture_edge_baseline "
            f"--project {project}`, commit it, then re-run this merge",
        )
    changes = lane_changes(repo_root, merge_base, commit)
    renamed = {old: new for old, new in changes if old and old != new}
    if target_frozen is not None:
        carried = {(renamed.get(key[0], key[0]), *key[1:]) for key in target_frozen}
        added = sorted(key for key in frozen if key not in carried)
        if added:
            return _refusal(
                ref, project, f"architecture_baseline_grew: {BASELINE_PATH} gains "
                f"{len(added)} entr{'y' if len(added) == 1 else 'ies'} {base_ref} lacks",
                [f"{path} imports {module} ({src} -> {imp})" for path, module, src, imp in added],
                _GROWTH_RECOVERY,
            )
    python = [(old, new) for old, new in changes if new.endswith(".py")]
    if not python:
        return ""
    layers = LayerMap(model)
    candidate = forbidden_edges(
        model, read_blobs(repo_root, commit, [new for _old, new in python]),
        tree_paths(repo_root, commit), layers=layers,
    )
    if not candidate:
        return ""
    base_paths = [old for old, _new in python if old]
    base = forbidden_edges(
        model, read_blobs(repo_root, merge_base, base_paths),
        tree_paths(repo_root, merge_base), layers=layers,
    )
    present = {(renamed.get(edge.path, edge.path), *edge.key[1:]) for edge in base}
    added_edges: List[ForbiddenEdge] = [
        edge for edge in candidate if edge.key not in frozen and edge.key not in present
    ]
    if not added_edges:
        return ""
    return _refusal(
        ref, project,
        f"architecture_edge_forbidden: the lane adds {len(added_edges)} forbidden "
        "architecture edge(s) missing from the committed baseline",
        [edge.describe() for edge in added_edges], _EDGE_RECOVERY,
    )


__all__ = ["BASELINE_PATH", "GATE", "architecture_edge_refusal", "read_model"]
