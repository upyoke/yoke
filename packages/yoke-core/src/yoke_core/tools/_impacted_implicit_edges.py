"""Tests a change reaches without importing it: fixtures and dispatch.

Two dependency edges sit beside the import graph. A test requests a
conftest fixture by parameter name, and a caller reaches a registered
handler by naming its function id. Both hang off the modules above the
change, found by one layered walk up the importers that stops at the
dispatch registration hub and at fixture owners.

The full set follows every module the walk reaches. Yoke's import graph is
dense enough that this is near-total for most core edits, so a bounded run
follows the edges only from modules within :data:`BOUNDED_IMPLICIT_HOPS`
import hops of the change — the handlers and fixtures that sit closest to
it, where its callers are. Farther edges are the deferred coverage the final
gate runs.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass

from yoke_core.tools._impacted_conftest_dependencies import fixture_dependents
from yoke_core.tools._impacted_dispatch_edges import (
    DISPATCH_HUB_MODULE,
    dispatch_caller_files,
    function_ids_for,
)
from yoke_core.tools._impacted_import_index import (
    ImportIndex,
    direct_importer_tests,
    is_test_file,
)
from yoke_core.tools._impacted_selection import is_effectively_full

#: Import hops above the change a bounded run follows implicit edges from.
BOUNDED_IMPLICIT_HOPS = 3


@dataclass(frozen=True)
class ImplicitDependents:
    #: Every test reached through a fixture or dispatch edge.
    full: frozenset[str]
    #: What a bounded run keeps: the edges near the change, each dropped when
    #: it alone is near-total, plus one collection probe per reached owner.
    bounded: frozenset[str]


def _upward_hops(changed: Iterable[str], index: ImportIndex) -> dict[str, int]:
    """Hop distance of each module at or above the change.

    Fixture owners end the walk: a module that imports one does not run
    its fixtures, and the owner's dependents are read from fixture use.
    """
    owners = index.fixtures.owners
    hops = {
        module: 0
        for path in changed
        if path not in owners and (module := index.module_of.get(path)) is not None
    }
    frontier = list(hops)
    while frontier:
        layer, frontier = frontier, []
        for module in layer:
            for importer in index.importers.get(module, ()):
                above = index.module_of.get(importer)
                if importer in owners or above in (None, DISPATCH_HUB_MODULE):
                    continue
                if above in hops:
                    continue
                hops[above] = hops[module] + 1
                frontier.append(above)
    return hops


def _dispatch_tests(modules: Iterable[str], index: ImportIndex) -> frozenset[str]:
    """Tests naming a reached handler's function id, or importing a caller that does."""
    function_ids = function_ids_for(modules, index.dispatch)
    callers = dispatch_caller_files(function_ids, index.importers)
    adapters = [caller for caller in callers if not is_test_file(caller)]
    return frozenset(callers - set(adapters)) | direct_importer_tests(adapters, index)


def _edges(
    changed_owners: Iterable[str], modules: Collection[str], index: ImportIndex
) -> tuple[list[frozenset[str]], frozenset[str]]:
    fixtures = fixture_dependents(changed_owners, modules, index)
    return [
        *fixtures.by_owner.values(),
        _dispatch_tests(modules, index),
    ], fixtures.probes


def implicit_dependents(
    changed: Iterable[str], index: ImportIndex, *, total_files: int
) -> ImplicitDependents:
    paths = tuple(changed)
    changed_owners = [path for path in paths if path in index.fixtures.owners]
    hops = _upward_hops(paths, index)
    edges, probes = _edges(changed_owners, hops.keys(), index)
    near = {module for module, hop in hops.items() if hop <= BOUNDED_IMPLICIT_HOPS}
    near_edges, _near_probes = _edges(changed_owners, near, index)
    kept = [t for t in near_edges if not is_effectively_full(len(t), total_files)]
    bounded = probes.union(*kept)
    if is_effectively_full(len(bounded), total_files):
        bounded = probes
    return ImplicitDependents(full=probes.union(*edges), bounded=bounded)


__all__ = ["BOUNDED_IMPLICIT_HOPS", "ImplicitDependents", "implicit_dependents"]
