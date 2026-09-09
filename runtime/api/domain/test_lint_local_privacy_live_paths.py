"""Live hook behaviour for the operator-machine privacy guard.

The engine guard and the product-local HTTPS-fallback guard must agree: a
scoped personal-folder read or a GUI automation call passes both untouched, a
broad home scan advises on both, and only the system privacy database denies.
The automated-test tripwire is the counterweight — it blocks every category,
including the ones a live call is allowed.

Every path here is synthetic; the suite must not read the folders it describes.
"""

from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess
import time
from unittest.mock import patch

import pytest

from yoke_contracts.hook_runner.hook_guard_catalog import GUARD_CATALOG
from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for
from yoke_contracts.hook_runner.local_privacy_messages import LIVE_ADVISORY
from yoke_core.domain import lint_local_privacy
from yoke_core.hooks.types import Outcome
from yoke_harness.hooks import local_policies, local_subset
from yoke_harness.hooks.deadline import HookDeadline
from yoke_harness.hooks.local_policy_common import ADVISORY, DENY, NOOP


HOME = Path("/Users/synthetic-operator")
REPO = "/Users/synthetic-operator/checkout"
# Captured at import time, before the autouse privacy guard replaces the name.
_REAL_POPEN = subprocess.Popen


def _quote(path: str) -> str:
    return shlex.quote(path)


# ---------------------------------------------------------------------------
# Live hook paths: engine and product-local
# ---------------------------------------------------------------------------


def _payload(command: str) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": REPO,
    }


@pytest.mark.parametrize(
    "command",
    [
        "cat ~/Documents/notes.txt",
        "cat ~/Downloads/reference/synthesis.md",
        "osascript -e 'tell app \"Finder\" to activate'",
        "screencapture /tmp/screen.png",
    ],
)
def test_scoped_access_and_gui_automation_pass_both_live_paths(command: str) -> None:
    with patch.object(lint_local_privacy.Path, "home", return_value=HOME):
        assert lint_local_privacy.evaluate_payload(_payload(command)) is None
        with patch.object(local_policies.Path, "home", return_value=HOME):
            assert local_policies.lint_local_privacy(_payload(command)).outcome == NOOP


def test_broad_discovery_advises_on_both_live_paths() -> None:
    payload = _payload("find $HOME -maxdepth 4 -name python3")

    with patch.object(lint_local_privacy.Path, "home", return_value=HOME):
        engine_verdict = lint_local_privacy.evaluate_payload(payload)
        decision = lint_local_privacy.evaluate(lint_local_privacy._context(payload))
    with patch.object(local_policies.Path, "home", return_value=HOME):
        product_verdict = local_policies.lint_local_privacy(payload)

    assert engine_verdict is not None
    assert engine_verdict[2] == "advisory"
    assert decision.outcome is Outcome.WARN
    assert decision.block is False
    assert decision.audit_fields["additionalContext"] == engine_verdict[1]
    assert product_verdict.outcome == ADVISORY
    assert product_verdict.additional_context in engine_verdict[1]


def test_an_operator_deny_setting_does_not_escalate_the_advisory() -> None:
    payload = _payload("find $HOME -maxdepth 4 -name python3")

    with patch.object(lint_local_privacy.Path, "home", return_value=HOME):
        with patch.object(lint_local_privacy, "_read_mode", return_value="deny"):
            verdict = lint_local_privacy.evaluate_payload(payload)

    assert verdict is not None
    assert verdict[0] == LIVE_ADVISORY
    assert verdict[2] == "advisory"


def test_privacy_database_still_denies_on_both_live_paths() -> None:
    payload = _payload("cat '/Library/Application Support/com.apple.TCC/TCC.db'")

    with patch.object(lint_local_privacy.Path, "home", return_value=HOME):
        with patch.object(lint_local_privacy, "_read_mode", return_value="deny"):
            engine_verdict = lint_local_privacy.evaluate_payload(payload)
    with patch.object(local_policies.Path, "home", return_value=HOME):
        product_verdict = local_policies.lint_local_privacy(payload)

    assert engine_verdict is not None
    assert engine_verdict[0] == "deny"
    assert product_verdict.outcome == DENY
    assert product_verdict.message in engine_verdict[1]


def test_engine_and_product_local_policy_share_safe_outcome() -> None:
    payload = _payload(f"find {_quote(REPO)} -name codex")

    with patch.object(lint_local_privacy.Path, "home", return_value=HOME):
        assert lint_local_privacy.evaluate_payload(payload) is None
    with patch.object(local_policies.Path, "home", return_value=HOME):
        assert local_policies.lint_local_privacy(payload).outcome == NOOP


def test_guard_is_protected_and_ordered_before_unmatched_globs() -> None:
    spec = next(spec for spec in GUARD_CATALOG if spec.guard == "lint_local_privacy")
    chain = ordered_pipeline_for("PreToolUse", "Bash")

    assert spec.protected is True
    assert spec.module == "yoke_core.domain.lint_local_privacy"
    assert chain.index(spec.module) < chain.index(
        "yoke_core.domain.lint_unmatched_path_glob"
    )


def test_product_local_subset_denies_the_privacy_database_before_https_relay() -> None:
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "cat '/Library/Application Support/com.apple.TCC/TCC.db'"
                ),
            },
            "cwd": REPO,
        }
    )
    with patch.object(local_policies.Path, "home", return_value=HOME):
        result = local_subset.evaluate_local_subset(
            "PreToolUse",
            payload,
            "codex",
            None,
            HookDeadline(budget_ms=3000, started_at=time.monotonic()),
            lint_config_snapshot={"lint_local_privacy": {"mode": "deny"}},
        )

    assert result.denied is True
    assert result.denial_audit is not None
    assert result.denial_audit["guard_key"] == "yoke_core.domain.lint_local_privacy"


def test_product_local_subset_lets_gui_automation_through() -> None:
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "screencapture /tmp/screen.png"},
            "cwd": REPO,
        }
    )
    with patch.object(local_policies.Path, "home", return_value=HOME):
        result = local_subset.evaluate_local_subset(
            "PreToolUse",
            payload,
            "codex",
            None,
            HookDeadline(budget_ms=3000, started_at=time.monotonic()),
            lint_config_snapshot={"lint_local_privacy": {"mode": "deny"}},
        )

    assert result.denied is False


# ---------------------------------------------------------------------------
# Automated-test isolation
# ---------------------------------------------------------------------------


def test_repo_fixture_stops_local_automation_before_popen() -> None:
    with pytest.raises(pytest.fail.Exception, match="operator's machine"):
        subprocess.run(["osascript", "-e", "beep"], check=False)


def test_repo_fixture_stops_a_real_personal_folder_read_before_popen() -> None:
    target = str(Path.home() / "Documents" / "does-not-need-to-exist.txt")

    with pytest.raises(pytest.fail.Exception, match="operator's machine"):
        subprocess.run(["cat", target], check=False)


def test_the_installed_guard_keeps_the_real_popen_type_surface() -> None:
    # The autouse guard replaces subprocess.Popen for the whole session.
    # Production modules annotate factories as subprocess.Popen[bytes] at
    # module scope, so a replacement that is not subscriptable turns the
    # first in-test import of such a module into a TypeError that has
    # nothing to do with the test.
    assert subprocess.Popen is not _REAL_POPEN
    assert subprocess.Popen[bytes] is not None
    assert issubclass(subprocess.Popen, _REAL_POPEN)
