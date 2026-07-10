"""Universal-ordering parity tests + structural reachability backstop.

Owns AC-T1, AC-T2, AC-T3, AC-T8 (line cap), and AC-T9 (deleted-module
grep) from epic task 014. Every ``(event_name, matcher)`` key in
:data:`yoke_contracts.hook_runner.hook_ordering.HOOK_ORDERING` is
exercised, both for chain equality (claude / codex modulo the runner's
``_apply_omissions`` filter) and for structural reachability (every
chained module id must be either typed-evaluable or an explicit
``subprocess_modules`` carve-out — no third state).

The runner-behavior band (timeout, subprocess carve-out exit-code paths,
dry-run CLI, real-chain ``sqlite3`` denial smoke test) lives in
``test_hook_runner.py`` so the parity surface here can stay narrow. The
chain registry, runner core, and adapter capability tests live in their
own files (``test_hook_runner_chain_registry.py``,
``test_hook_runner_runner.py``, ``test_hook_runner_decision_render.py``).
"""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

import pytest

from yoke_contracts.hook_runner.chain_registry import chain_for
from yoke_contracts.hook_runner.hook_ordering import HOOK_ORDERING, ordered_pipeline_for
from runtime.harness.claude.adapter import CAPABILITY as CLAUDE_CAPABILITY
from runtime.harness.codex.adapter import CAPABILITY as CODEX_CAPABILITY
from runtime.harness.hook_runner import runner as runner_module
from runtime.harness.hook_runner.adapter_capability import AdapterCapability


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _runner_filtered_chain(
    event_name: str,
    matcher: str,
    capability: AdapterCapability,
) -> list[str]:
    """Apply the runner's ``_apply_omissions`` exactly as the runner would.

    Coupling the parity test to ``runner_module._apply_omissions`` means
    that if the omission semantics shift (e.g. Codex starts honoring
    ``apply_patch_chain_omissions`` for ``PreToolUse[apply_patch]``
    directly), this helper picks up the change without test edits.
    """
    return runner_module._apply_omissions(
        chain_for(event_name, matcher),
        event_name=event_name,
        capability=capability,
    )


def _all_chain_keys() -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for event_name, matchers in HOOK_ORDERING.items():
        for matcher in matchers:
            keys.append((event_name, matcher))
    return keys


def _module_ids_in_registry() -> set[str]:
    ids: set[str] = set()
    for matchers in HOOK_ORDERING.values():
        for chain in matchers.values():
            for module_id in chain:
                ids.add(module_id)
    return ids


# ---------------------------------------------------------------------------
# AC-T1, AC-T2: chain equality across every (event, matcher)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("event_name", "matcher"), _all_chain_keys())
def test_claude_chain_matches_universal_ordering(event_name: str, matcher: str) -> None:
    """AC-T1: Claude's filtered chain equals the universal-source chain (list equality)."""
    expected = list(ordered_pipeline_for(event_name, matcher))
    actual = _runner_filtered_chain(event_name, matcher, CLAUDE_CAPABILITY)
    assert actual == expected


@pytest.mark.parametrize(("event_name", "matcher"), _all_chain_keys())
def test_codex_chain_matches_universal_ordering_modulo_omissions(
    event_name: str, matcher: str,
) -> None:
    """AC-T2: Codex's filtered chain equals expected minus omitted modules.

    The runner's ``_apply_omissions`` only drops Codex's
    ``apply_patch_chain_omissions`` when ``event_name == "apply_patch"``;
    for every other ``(event, matcher)`` the codex chain equals the
    expected chain because the omission filter does not fire.
    """
    expected = list(ordered_pipeline_for(event_name, matcher))
    actual = _runner_filtered_chain(event_name, matcher, CODEX_CAPABILITY)
    if event_name == "apply_patch":
        expected = [
            m for m in expected
            if m not in CODEX_CAPABILITY.apply_patch_chain_omissions
        ]
    assert actual == expected


# ---------------------------------------------------------------------------
# AC-T3: every chain module is typed-evaluable OR a subprocess carve-out
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_id", sorted(_module_ids_in_registry()))
def test_chain_module_is_typed_or_subprocess_carveout(module_id: str) -> None:
    """AC-T3: structural backstop preventing the runner-broken failure mode.

    A module that is neither typed-evaluable nor an explicit
    ``subprocess_modules`` carve-out crashes the runner at first dispatch
    with ``failure="missing_evaluate"`` and floods the events table with
    ``HookExecutionFailed``. This test fails closed before that lands.
    """
    in_subprocess_carveout = (
        module_id in CLAUDE_CAPABILITY.subprocess_modules
        or module_id in CODEX_CAPABILITY.subprocess_modules
    )
    if in_subprocess_carveout:
        return
    module = importlib.import_module(module_id)
    evaluator = getattr(module, "evaluate", None)
    assert callable(evaluator), (
        f"{module_id} is neither in any capability.subprocess_modules nor "
        f"exposes a callable evaluate(); the runner would emit "
        f"HookExecutionFailed{{failure='missing_evaluate'}} on first dispatch."
    )


# ---------------------------------------------------------------------------
# AC-T9: the deleted Codex service-bridge module has no live consumers
# ---------------------------------------------------------------------------


def test_obsoleted_service_bridge_has_no_live_references() -> None:
    """AC-T9: ``codex_hooks_service_bridge`` is gone from the live runtime tree.

    The target term is split at construction time so this enforcement test
    is not itself a grep hit. The hit-filter additionally excludes (a) any
    ``docs/archive/`` decision records that legitimately preserve history,
    (b) this file (the term must appear here to be searched for), and (c)
    ``doctor_hc_obsoleted_terms.py`` — the canonical registry where retired
    terms are enumerated by name so the HC scanner can detect them in other
    files. References inside the registry are the contract surface; they
    are not "live" consumers.
    """
    target = "codex_hooks_service" + "_bridge"
    repo_root = Path(__file__).resolve().parents[2]
    runtime_dir = repo_root / "runtime"
    completed = subprocess.run(
        ["grep", "-rn", "--exclude-dir=__pycache__", target, str(runtime_dir)],
        capture_output=True, text=True, check=False,
    )
    if completed.returncode == 1:
        return  # grep exit 1 = no matches at all
    hits = [
        line for line in completed.stdout.splitlines()
        if line.strip()
        and "/docs/archive/" not in line
        and Path(__file__).name not in line
        and "doctor_hc_obsoleted_terms.py" not in line
    ]
    assert hits == [], (
        f"{target} still referenced in live runtime tree:\n" + "\n".join(hits)
    )


# ---------------------------------------------------------------------------
# AC-T8: file-line cap (this file <= 350 lines; matches the project hard cap)
# ---------------------------------------------------------------------------


def test_parity_file_under_350_lines() -> None:
    """AC-T8: parity file at or below the 350-line hard cap."""
    here = Path(__file__).resolve()
    with here.open("rb") as fh:
        line_count = sum(1 for _ in fh)
    assert line_count <= 350, f"{here.name} is {line_count} lines"
