"""Tests that depend on a changed pytest fixture owner.

Conftests load implicitly and tests request fixtures by parameter name, so
a fixture owner's dependents are invisible to import reachability. An owner
is reached when it changed, or when it imports a module the change reaches
(the caller supplies both).
Its affected fixtures are every fixture for a changed owner, otherwise the
ones referencing a reached import; fixtures requesting an affected fixture
are affected in turn. Dependents are the in-scope tests requesting one —
or every in-scope test when an affected fixture is autouse, a hook is
affected, or collection-time module code is. Descendant conftests that
request an affected fixture carry the effect into their own scopes.

Every reached owner also keeps one collection probe: a test under it, so
collection stays covered even when its dependents are deferred.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass

from yoke_core.tools._impacted_fixture_graph import FixtureOwner
from yoke_core.tools._impacted_import_index import ImportIndex, is_test_file


@dataclass(frozen=True)
class FixtureDependents:
    #: Reached owner -> the tests depending on it.
    by_owner: dict[str, frozenset[str]]
    #: One collection probe per reached owner.
    probes: frozenset[str]


def _affected(
    owner: FixtureOwner, triggers: "frozenset[str] | None"
) -> tuple[set[str], bool]:
    """Affected fixture names and whether the whole scope is affected.

    ``triggers=None`` means the owner itself changed.
    """
    if triggers is None:
        affected = set(owner.fixtures)
        whole = owner.has_hooks
    else:
        affected = {
            name
            for name, fixture in owner.fixtures.items()
            if (fixture.refs | fixture.params) & triggers
        }
        whole = bool((owner.hook_refs | owner.module_refs) & triggers)
    grew = True
    while grew:
        grew = False
        for name, fixture in owner.fixtures.items():
            if name not in affected and fixture.params & affected:
                affected.add(name)
                grew = True
    whole = whole or any(owner.fixtures[name].autouse for name in affected)
    return affected, whole


def _dependents(
    owner: FixtureOwner,
    triggers: "frozenset[str] | None",
    index: ImportIndex,
    seen: set[str],
) -> set[str]:
    seen.add(owner.path)
    affected, whole = _affected(owner, triggers)
    if not affected and not whole:
        return set()
    found: set[str] = set()
    for path, requested in index.fixtures.uses.items():
        if not path.startswith(owner.scope):
            continue
        if is_test_file(path) and (whole or requested & affected):
            found.add(path)
        child = index.fixtures.owners.get(path)
        if child and path not in seen and (whole or requested & affected):
            found |= _dependents(child, frozenset(affected), index, seen)
    return found


def fixture_dependents(
    changed_owners: Iterable[str], reached: Collection[str], index: ImportIndex
) -> FixtureDependents:
    """Dependents of owners that changed or import a *reached* module."""
    owners = index.fixtures.owners
    changed_set = set(changed_owners)
    by_owner: dict[str, frozenset[str]] = {}
    for path, owner in owners.items():
        if path in changed_set:
            triggers = None
        else:
            names = {n for n, mods in owner.bindings.items() if mods & reached}
            references = (
                owner.hook_refs
                | owner.module_refs
                | frozenset().union(*(f.refs for f in owner.fixtures.values()))
            )
            if not (names or references & reached):
                continue
            triggers = frozenset(names) | (references & reached)
        by_owner[path] = frozenset(_dependents(owner, triggers, index, set()))
    tests = sorted(path for path in index.fixtures.uses if is_test_file(path))
    probes = {
        probe
        for owner in by_owner
        if (
            probe := next((t for t in tests if t.startswith(owners[owner].scope)), None)
        )
    }
    return FixtureDependents(by_owner=by_owner, probes=frozenset(probes))


__all__ = ["FixtureDependents", "fixture_dependents"]
