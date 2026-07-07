"""Tests for persist_simulation.py — simulation persistence.

Covers: verdict parsing, persist-and-verify flow with mocked in-process
``epic.simulation_upsert``/``simulation_get`` owners, edge cases (empty input,
unparseable verdicts, mismatches), and epic-ID attestation cross-check
(wrong-epic body, missing-epic body, legacy heading fallback).
"""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.domain import persist_simulation
from yoke_core.domain.persist_simulation import (
    SimulationParseResult,
    parse_verdict,
    persist_and_verify,
)


# ---------------------------------------------------------------------------
# parse_verdict
# ---------------------------------------------------------------------------

class TestParseVerdict:
    def test_explicit_clean(self):
        result = parse_verdict("blah SIMULATION: CLEAN blah")
        assert result.verdict == "CLEAN"
        assert result.epic_id is None
        assert result.epic_id_source is None

    def test_explicit_gaps(self):
        result = parse_verdict("SIMULATION: GAPS FOUND")
        assert result.verdict == "GAPS FOUND"

    def test_bare_clean(self):
        result = parse_verdict("some text CLEAN more text")
        assert result.verdict == "CLEAN"

    def test_bare_gaps(self):
        result = parse_verdict("Result: GAPS FOUND in task 3")
        assert result.verdict == "GAPS FOUND"

    def test_prefers_prefixed_clean_over_bare(self):
        result = parse_verdict("SIMULATION: CLEAN and also GAPS FOUND")
        assert result.verdict == "CLEAN"

    def test_no_verdict(self):
        result = parse_verdict("no verdict here")
        assert result.verdict is None

    def test_empty_string(self):
        result = parse_verdict("")
        assert result.verdict is None

    def test_epic_line_extracted(self):
        body = "SIMULATION: CLEAN\nEPIC: YOK-1234\n\n# Simulation Report"
        result = parse_verdict(body)
        assert result.epic_id == 1234
        assert result.epic_id_source == "epic_line"

    def test_epic_line_with_leading_whitespace(self):
        body = "SIMULATION: GAPS FOUND\n  EPIC: YOK-42\n"
        result = parse_verdict(body)
        assert result.epic_id == 42
        assert result.epic_id_source == "epic_line"

    def test_heading_fallback_when_epic_line_absent(self):
        body = "SIMULATION: CLEAN\n\n# Simulation Report: YOK-7 — integration\n"
        result = parse_verdict(body)
        assert result.epic_id == 7
        assert result.epic_id_source == "heading"

    def test_epic_line_preferred_over_heading(self):
        body = (
            "SIMULATION: CLEAN\n"
            "EPIC: YOK-99\n\n"
            "# Simulation Report: YOK-1 — plan\n"
        )
        result = parse_verdict(body)
        assert result.epic_id == 99
        assert result.epic_id_source == "epic_line"

    def test_no_epic_attestation(self):
        body = "SIMULATION: CLEAN\n\nSome prose without epic identity."
        result = parse_verdict(body)
        assert result.epic_id is None
        assert result.epic_id_source is None

    def test_returns_simulation_parse_result_dataclass(self):
        result = parse_verdict("SIMULATION: CLEAN\nEPIC: YOK-5")
        assert isinstance(result, SimulationParseResult)


# ---------------------------------------------------------------------------
# persist_and_verify
# ---------------------------------------------------------------------------

class TestPersistAndVerify:
    def test_empty_input_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            persist_and_verify("42", "plan", "")
        assert exc_info.value.code == 2

    def test_whitespace_only_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            persist_and_verify("42", "plan", "   \n  ")
        assert exc_info.value.code == 2

    def test_no_parseable_verdict(self):
        with pytest.raises(SystemExit) as exc_info:
            persist_and_verify("42", "plan", "some text without any verdict keywords")
        assert exc_info.value.code == 14

    def _patch_owners(self, upsert_side_effect=None, get_side_effect=None):
        """Return mocks for the two in-process owners and the DB connect."""
        conn = mock.MagicMock()
        conn.__enter__ = mock.MagicMock(return_value=conn)
        conn.__exit__ = mock.MagicMock(return_value=False)
        return (
            mock.patch.object(persist_simulation, "connect", return_value=conn),
            mock.patch.object(
                persist_simulation._epic_domain,
                "simulation_upsert",
                side_effect=upsert_side_effect,
            ),
            mock.patch.object(
                persist_simulation._epic_domain,
                "simulation_get",
                side_effect=get_side_effect,
            ),
        )

    def test_success_clean(self):
        sim_output = "SIMULATION: CLEAN\nEPIC: YOK-42\n\nNo gaps found."
        connect_patch, upsert_patch, get_patch = self._patch_owners(
            upsert_side_effect=[None],
            get_side_effect=["1|42|plan|CLEAN|body text|2026-04-09"],
        )
        with connect_patch, upsert_patch, get_patch:
            verdict = persist_and_verify("42", "plan", sim_output)
        assert verdict == "CLEAN"

    def test_success_gaps_found(self):
        sim_output = "SIMULATION: GAPS FOUND\nEPIC: YOK-42\n\n- Gap 1\n- Gap 2"
        connect_patch, upsert_patch, get_patch = self._patch_owners(
            upsert_side_effect=[None],
            get_side_effect=["1|42|integration|GAPS FOUND|body|2026-04-09"],
        )
        with connect_patch, upsert_patch, get_patch:
            verdict = persist_and_verify("42", "integration", sim_output)
        assert verdict == "GAPS FOUND"

    def test_legacy_heading_fallback_accepted(self):
        sim_output = (
            "SIMULATION: CLEAN\n\n"
            "# Simulation Report: YOK-42 — plan\n\nNo gaps."
        )
        connect_patch, upsert_patch, get_patch = self._patch_owners(
            upsert_side_effect=[None],
            get_side_effect=["1|42|plan|CLEAN|body|2026-04-09"],
        )
        with connect_patch, upsert_patch, get_patch:
            verdict = persist_and_verify("42", "plan", sim_output)
        assert verdict == "CLEAN"

    def test_wrong_epic_body_rejected(self):
        sim_output = (
            "SIMULATION: GAPS FOUND\n"
            "EPIC: YOK-1513\n\n"
            "# Simulation Report: YOK-1513 — plan\n"
        )
        with pytest.raises(SystemExit) as exc_info:
            persist_and_verify("1511", "plan", sim_output)
        assert exc_info.value.code == 16

    def test_wrong_epic_via_heading_fallback_rejected(self):
        sim_output = (
            "SIMULATION: GAPS FOUND\n\n"
            "# Simulation Report: YOK-1513 — plan\n"
        )
        with pytest.raises(SystemExit) as exc_info:
            persist_and_verify("1511", "plan", sim_output)
        assert exc_info.value.code == 16

    def test_wrong_epic_error_names_both_ids_and_phase(self, capsys):
        sim_output = (
            "SIMULATION: CLEAN\n"
            "EPIC: YOK-1513\n"
        )
        with pytest.raises(SystemExit):
            persist_and_verify("1511", "integration", sim_output)
        err = capsys.readouterr().err
        assert "YOK-1511" in err
        assert "YOK-1513" in err
        assert "integration" in err

    def test_missing_epic_body_rejected(self):
        sim_output = (
            "SIMULATION: GAPS FOUND\n\n"
            "## Gaps Found\n\nGap 1: ...\n"
        )
        with pytest.raises(SystemExit) as exc_info:
            persist_and_verify("1511", "integration", sim_output)
        assert exc_info.value.code == 17

    def test_missing_epic_error_names_cli_epic(self, capsys):
        sim_output = "SIMULATION: CLEAN\n\nNo gaps."
        with pytest.raises(SystemExit):
            persist_and_verify("1511", "plan", sim_output)
        err = capsys.readouterr().err
        assert "YOK-1511" in err
        assert "EPIC: YOK-1511" in err

    def test_epic_check_runs_before_upsert(self):
        """Wrong-epic must reject BEFORE simulation_upsert is invoked."""
        sim_output = (
            "SIMULATION: CLEAN\n"
            "EPIC: YOK-7\n"
        )
        connect_patch, upsert_patch, get_patch = self._patch_owners(
            upsert_side_effect=RuntimeError("upsert should never be called"),
            get_side_effect=["1|42|plan|CLEAN|body|2026-04-09"],
        )
        with connect_patch, upsert_patch, get_patch:
            with pytest.raises(SystemExit) as exc_info:
                persist_and_verify("42", "plan", sim_output)
        assert exc_info.value.code == 16

    def test_upsert_failure(self):
        sim_output = "SIMULATION: CLEAN\nEPIC: YOK-42"
        connect_patch, upsert_patch, get_patch = self._patch_owners(
            upsert_side_effect=RuntimeError("db broken"),
        )
        with connect_patch, upsert_patch, get_patch:
            with pytest.raises(SystemExit) as exc_info:
                persist_and_verify("42", "plan", sim_output)
        assert exc_info.value.code == 10

    def test_readback_missing(self):
        sim_output = "SIMULATION: CLEAN\nEPIC: YOK-42"
        connect_patch, upsert_patch, get_patch = self._patch_owners(
            upsert_side_effect=[None],
            get_side_effect=LookupError("not found"),
        )
        with connect_patch, upsert_patch, get_patch:
            with pytest.raises(SystemExit) as exc_info:
                persist_and_verify("42", "plan", sim_output)
        assert exc_info.value.code == 11

    def test_parser_mismatch(self):
        sim_output = "SIMULATION: CLEAN\nEPIC: YOK-42"
        connect_patch, upsert_patch, get_patch = self._patch_owners(
            upsert_side_effect=[None],
            get_side_effect=["1|42|plan|GAPS FOUND|body|2026-04-09"],
        )
        with connect_patch, upsert_patch, get_patch:
            with pytest.raises(SystemExit) as exc_info:
                persist_and_verify("42", "plan", sim_output)
        assert exc_info.value.code == 13

    def test_inconclusive_verdict(self):
        sim_output = "SIMULATION: CLEAN\nEPIC: YOK-42"
        connect_patch, upsert_patch, get_patch = self._patch_owners(
            upsert_side_effect=[None],
            get_side_effect=["1|42|plan||body|2026-04-09"],
        )
        with connect_patch, upsert_patch, get_patch:
            with pytest.raises(SystemExit) as exc_info:
                persist_and_verify("42", "plan", sim_output)
        assert exc_info.value.code == 12

    def test_integration_clean_triggers_auto_handoff(self):
        sim_output = "SIMULATION: CLEAN\nEPIC: YOK-42"
        connect_patch, upsert_patch, get_patch = self._patch_owners(
            upsert_side_effect=[None],
            get_side_effect=["1|42|integration|CLEAN|body|2026-04-09"],
        )
        with connect_patch, upsert_patch, get_patch, \
             mock.patch("yoke_core.domain.conduct_reviewed_handoff.run", return_value=0) as handoff:
            verdict = persist_and_verify("42", "integration", sim_output)
        assert verdict == "CLEAN"
        handoff.assert_called_once_with(42)

    def test_plan_clean_does_not_trigger_handoff(self):
        sim_output = "SIMULATION: CLEAN\nEPIC: YOK-42"
        connect_patch, upsert_patch, get_patch = self._patch_owners(
            upsert_side_effect=[None],
            get_side_effect=["1|42|plan|CLEAN|body|2026-04-09"],
        )
        with connect_patch, upsert_patch, get_patch, \
             mock.patch("yoke_core.domain.conduct_reviewed_handoff.run") as handoff:
            verdict = persist_and_verify("42", "plan", sim_output)
        assert verdict == "CLEAN"
        handoff.assert_not_called()

    def test_integration_gaps_does_not_trigger_handoff(self):
        sim_output = "SIMULATION: GAPS FOUND\nEPIC: YOK-42\n- Gap 1"
        connect_patch, upsert_patch, get_patch = self._patch_owners(
            upsert_side_effect=[None],
            get_side_effect=["1|42|integration|GAPS FOUND|body|2026-04-09"],
        )
        with connect_patch, upsert_patch, get_patch, \
             mock.patch("yoke_core.domain.conduct_reviewed_handoff.run") as handoff:
            verdict = persist_and_verify("42", "integration", sim_output)
        assert verdict == "GAPS FOUND"
        handoff.assert_not_called()

    def test_handoff_failure_exits_partial_success(self):
        sim_output = "SIMULATION: CLEAN\nEPIC: YOK-42"
        connect_patch, upsert_patch, get_patch = self._patch_owners(
            upsert_side_effect=[None],
            get_side_effect=["1|42|integration|CLEAN|body|2026-04-09"],
        )
        with connect_patch, upsert_patch, get_patch, \
             mock.patch("yoke_core.domain.conduct_reviewed_handoff.run", return_value=3):
            with pytest.raises(SystemExit) as exc_info:
                persist_and_verify("42", "integration", sim_output)
        assert exc_info.value.code == 15
