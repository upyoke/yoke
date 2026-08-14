"""Hook health beside the Overview's harness activation targets.

Session presence alone cannot separate a harness whose hooks run from one
whose approval was never granted — both write a ``harness_sessions`` row.
These cover the sub-signal that can, and the declaration that decides which
harnesses report it at all.
"""

from __future__ import annotations

from yoke_contracts.harness_hook_approval import HARNESS_HOOK_APPROVAL
from yoke_core.domain.overview_harness_hook_health import (
    HOOK_HEALTH_LIVE,
    HOOK_HEALTH_NOT_SEEN,
    HOOK_HEALTH_SILENT,
    harness_targets,
)


def _by_key(identities):
    return {target["key"]: target for target in harness_targets(identities)}


def test_sessions_without_hook_telemetry_report_silent_and_their_surface():
    targets = _by_key([("codex", "codex-desktop", 0)])

    assert targets["codex"]["hit"] is True
    assert targets["codex"]["hook_health"] == HOOK_HEALTH_SILENT
    assert targets["codex"]["trust_surface"] == (
        HARNESS_HOOK_APPROVAL["codex"]["trust_surface"]
    )


def test_one_session_with_hook_telemetry_reports_live():
    targets = _by_key([("codex", "codex-desktop", 0), ("codex", "", 2)])

    # The family target spans both identities, so the live one carries it.
    assert targets["codex"]["hook_health"] == HOOK_HEALTH_LIVE
    assert targets["codex-cli"]["hook_health"] == HOOK_HEALTH_LIVE
    assert targets["claude-code"]["hook_health"] == HOOK_HEALTH_NOT_SEEN


def test_a_target_no_session_ever_matched_reports_not_seen():
    targets = _by_key([("codex", "", 1)])

    assert targets["cursor"]["hit"] is False
    assert targets["cursor"]["hook_health"] == HOOK_HEALTH_NOT_SEEN
    assert targets["cursor"]["trust_surface"] == (
        HARNESS_HOOK_APPROVAL["cursor"]["trust_surface"]
    )


def test_applicability_follows_the_declaration_not_the_harness_id(monkeypatch):
    monkeypatch.delitem(HARNESS_HOOK_APPROVAL, "cursor")

    targets = _by_key([("cursor", "cursor-desktop", 0)])

    # Undeclared: hit still reports, health has nothing to remediate.
    assert targets["cursor"]["hit"] is True
    assert targets["cursor"]["hook_health"] is None
    assert targets["cursor"]["trust_surface"] is None
    # Still-declared harnesses are untouched by the removal.
    assert targets["codex"]["hook_health"] == HOOK_HEALTH_NOT_SEEN
