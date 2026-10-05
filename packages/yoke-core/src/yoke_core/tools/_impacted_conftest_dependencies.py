"""Keep one collection probe for every reached pytest fixture owner.

Conftests load implicitly, so test modules need not import their dependencies.
A representative descendant keeps collection covered even when bounded
selection defers broad reachability; it does not claim full fixture coverage.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePosixPath

from yoke_core.tools._impacted_import_index import ImportIndex, is_test_file


def conftest_collection_probes(changed: Iterable[str], index: ImportIndex) -> set[str]:
    pending = list(changed)
    seen: set[str] = set()
    owners: set[str] = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        if PurePosixPath(path).name == "conftest.py":
            owners.add(path)
        module = index.module_of.get(path)
        if module:
            pending.extend(index.importers.get(module, ()))
    tests = sorted(path for path in index.module_of if is_test_file(path))
    probes: set[str] = set()
    for owner in owners:
        prefix = str(PurePosixPath(owner).parent) + "/"
        descendant = next((path for path in tests if path.startswith(prefix)), None)
        if descendant:
            probes.add(descendant)
    return probes
