"""Every local read a server-run hook policy can reach is classified.

A policy whose home is not ``CLIENT`` may evaluate on the control-plane
authority, which cannot see the client machine. Any read of machine-local
state it can reach must either be gone, come from a named client fact, or
carry a written reason in :mod:`local_read_reasons`.
"""

from __future__ import annotations

import collections

from yoke_contracts.hook_runner.policy_home import POLICY_HOMES, PolicyHome

from tests.hook_policy_homes.local_read_reasons import REASONS
from tests.hook_policy_homes.reach import local_reads, reach


def _server_run_reads():
    seeds = [
        (module, "evaluate")
        for module, placement in POLICY_HOMES.items()
        if placement.home is not PolicyHome.CLIENT
    ]
    return local_reads(reach(seeds))


def test_every_reached_local_read_is_classified() -> None:
    classified = {key for _reason, keys in REASONS for key in keys}
    unclassified = collections.defaultdict(set)
    for read in _server_run_reads():
        if read.key not in classified:
            unclassified[read.key].add(f"{read.kind}@{read.line}")
    assert not unclassified, (
        "server-run hook policies reach unclassified local reads; move the "
        "policy to the client, feed it a named client fact, or add a written "
        "reason in tests/hook_policy_homes/local_read_reasons.py:\n"
        + "\n".join(f"  {key}: {sorted(v)}" for key, v in sorted(unclassified.items()))
    )


def test_every_reason_names_a_reached_local_read() -> None:
    reached = {read.key for read in _server_run_reads()}
    stale = sorted(
        key for _reason, keys in REASONS for key in keys if key not in reached
    )
    assert not stale, (
        "local_read_reasons.py names functions that no server-run policy "
        f"reaches or that no longer read local state; remove them: {stale}"
    )


def test_each_function_has_one_reason() -> None:
    counts = collections.Counter(key for _reason, keys in REASONS for key in keys)
    assert [key for key, n in counts.items() if n > 1] == []
