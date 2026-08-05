"""Three-way merge of a workflow definition against a newer published one.

Taking an update must not mean discarding what a universe changed. The three
sides are the recorded baseline (the generation the universe edited from),
what the universe runs now, and what Yoke has since published. Anything only
Yoke changed is taken; anything only the universe changed is kept; anything
both changed is a conflict and is reported rather than silently resolved.

This deliberately merges at the *structure* level, not the text level. A
workflow definition is data with named parts -- stages, gates, policies,
bindings -- and a line-oriented merge of its JSON would conflict on formatting
while missing that two edits touched the same gate.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional


class MergeConflict:
    """One place the universe and Yoke changed the same thing differently."""

    __slots__ = ("path", "baseline", "mine", "theirs")

    def __init__(
        self,
        path: str,
        baseline: Any,
        mine: Any,
        theirs: Any,
    ) -> None:
        self.path = path
        self.baseline = baseline
        self.mine = mine
        self.theirs = theirs

    def as_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "baseline": self.baseline,
            "mine": self.mine,
            "theirs": self.theirs,
        }


class MergeResult:
    """The merged definition, plus what was taken, kept, and conflicted."""

    __slots__ = ("definition", "taken", "kept", "conflicts")

    def __init__(
        self,
        definition: Dict[str, Any],
        taken: List[str],
        kept: List[str],
        conflicts: List[MergeConflict],
    ) -> None:
        self.definition = definition
        self.taken = taken
        self.kept = kept
        self.conflicts = conflicts

    @property
    def clean(self) -> bool:
        return not self.conflicts

    def as_dict(self) -> Dict[str, Any]:
        return {
            "definition": self.definition,
            "taken": self.taken,
            "kept": self.kept,
            "conflicts": [conflict.as_dict() for conflict in self.conflicts],
            "clean": self.clean,
        }


def _merge_value(
    path: str,
    baseline: Any,
    mine: Any,
    theirs: Any,
    taken: List[str],
    kept: List[str],
    conflicts: List[MergeConflict],
) -> Any:
    """Resolve one value by who moved it away from the baseline."""
    if mine == theirs:
        return deepcopy(mine)
    if mine == baseline:
        taken.append(path)
        return deepcopy(theirs)
    if theirs == baseline:
        kept.append(path)
        return deepcopy(mine)
    conflicts.append(MergeConflict(path, baseline, mine, theirs))
    # Keep the universe's value in the proposed definition. A conflict is
    # surfaced for a human to resolve, and until they do, not silently
    # overwriting what they wrote is the safer default.
    return deepcopy(mine)


_MISSING = object()


def _merge_mapping(
    prefix: str,
    baseline: Mapping[str, Any],
    mine: Mapping[str, Any],
    theirs: Mapping[str, Any],
    taken: List[str],
    kept: List[str],
    conflicts: List[MergeConflict],
) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    keys = list(mine) + [key for key in theirs if key not in mine]
    for key in keys:
        path = f"{prefix}.{key}" if prefix else key
        mine_value = mine.get(key, _MISSING)
        theirs_value = theirs.get(key, _MISSING)
        base_value = baseline.get(key, _MISSING)
        if mine_value is _MISSING and theirs_value is not _MISSING:
            # Yoke added it and the universe never had it: take it. If the
            # universe *removed* it, that is a real disagreement.
            if base_value is _MISSING:
                taken.append(path)
                merged[key] = deepcopy(theirs_value)
            else:
                conflicts.append(
                    MergeConflict(path, base_value, None, theirs_value)
                )
            continue
        if theirs_value is _MISSING:
            if base_value is _MISSING or base_value == mine_value:
                if base_value is not _MISSING:
                    # Yoke removed it and the universe left it alone.
                    taken.append(path)
                    continue
                kept.append(path)
                merged[key] = deepcopy(mine_value)
            else:
                conflicts.append(
                    MergeConflict(path, base_value, mine_value, None)
                )
                merged[key] = deepcopy(mine_value)
            continue
        base = None if base_value is _MISSING else base_value
        if (
            isinstance(mine_value, Mapping)
            and isinstance(theirs_value, Mapping)
            and isinstance(base, Mapping)
        ):
            merged[key] = _merge_mapping(
                path, base, mine_value, theirs_value, taken, kept, conflicts,
            )
            continue
        merged[key] = _merge_value(
            path, base, mine_value, theirs_value, taken, kept, conflicts,
        )
    return merged


def merge_definitions(
    baseline: Optional[Mapping[str, Any]],
    mine: Mapping[str, Any],
    theirs: Mapping[str, Any],
) -> MergeResult:
    """Merge *theirs* into *mine* using *baseline* as the common ancestor.

    Without a baseline there is no way to tell "the universe changed this"
    from "Yoke changed this", so every difference is a conflict. That is the
    honest outcome for a universe whose baseline was never recorded, and it is
    why the baseline is recorded at publish time rather than inferred later.
    """
    taken: List[str] = []
    kept: List[str] = []
    conflicts: List[MergeConflict] = []
    if baseline is None:
        merged = deepcopy(dict(mine))
        for key in set(mine) | set(theirs):
            if mine.get(key) != theirs.get(key):
                conflicts.append(
                    MergeConflict(key, None, mine.get(key), theirs.get(key))
                )
        return MergeResult(merged, taken, kept, conflicts)
    merged = _merge_mapping(
        "", baseline, mine, theirs, taken, kept, conflicts,
    )
    return MergeResult(merged, taken, kept, conflicts)


__all__ = ["MergeConflict", "MergeResult", "merge_definitions"]
