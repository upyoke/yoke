"""Regression: ``idea_readiness_check`` CLI JSON includes ``classification``.

Field-note 8727: the refine SKILL.md recipe extracted the readiness
classification by piping the readiness JSON into ``python3 -c "from
yoke_core.domain.idea_readiness_repair import classify_readiness_issues
..."`` — a runtime import from a one-liner the Codex PreToolUse lint
``lint-no-agent-runtime-api-import-from-c`` blocks. The fix surfaces
``classification`` directly in the CLI JSON so agents can read it via
stdlib ``python3 -c "import json"`` (which the lint allows). This test
locks the field in place so future changes do not silently regress the
SKILL recipe.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

import pytest

from yoke_core.domain import idea_readiness_check
from yoke_core.domain.idea_readiness_check import Issue


def _run_main_and_capture(item_id: int, *, issues, advisories):
    """Drive ``idea_readiness_check.main()`` and return the parsed JSON."""
    # The checks are mocked, so the connection is a closable stand-in only.
    conn = MagicMock()
    with patch.object(idea_readiness_check, "run_all_checks", return_value=issues), \
         patch.object(idea_readiness_check, "run_all_advisories", return_value=advisories), \
         patch(
             "yoke_core.domain.schema_common._connect_raw",
             return_value=conn,
         ), \
         patch(
             "yoke_core.domain.schema_common._resolve_db_path",
             return_value="",
         ):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = idea_readiness_check.main([str(item_id)])
    return rc, json.loads(buf.getvalue())


def test_payload_carries_classification_pass_when_no_issues():
    rc, payload = _run_main_and_capture(42, issues=[], advisories=[])
    assert rc == 0
    assert payload["verdict"] == "pass"
    # Classification must be present so the SKILL recipe can read it
    # without importing yoke_core.domain.idea_readiness_repair.
    assert "classification" in payload
    assert payload["classification"] == "pass"


def test_payload_carries_classification_pure_stale_count():
    stale = Issue(
        code="STALE_LINE_COUNT",
        message="recorded line count drifted",
        remediation="rerun line-count repair",
        context={"path": "runtime/api/foo.py", "recorded": 200, "actual": 220},
    )
    rc, payload = _run_main_and_capture(42, issues=[stale], advisories=[])
    assert rc == 1
    assert payload["verdict"] == "block"
    assert payload["classification"] == "pure_stale_count"


def test_payload_carries_classification_unrecoverable():
    other = Issue(
        code="MISSING_FILE_BUDGET",
        message="no File Budget section",
        remediation="add ## File Budget",
        context={},
    )
    rc, payload = _run_main_and_capture(42, issues=[other], advisories=[])
    assert rc == 1
    assert payload["verdict"] == "block"
    # Anything that is not pure stale-count classifies as unrecoverable
    # (or mixed_stale_count for combinations).
    assert payload["classification"] in {
        "unrecoverable", "mixed_stale_count",
    }
