"""Pure-unit tests for deploy_qa_stage_result.cmd_record_stage_result.

Split out of test_deploy_pipeline_full.py so that module stays under the
authored-file line budget.
"""

from __future__ import annotations

import json
import logging

import pytest

from yoke_core.domain import deploy_qa_recorder


class TestRecordStageResult:
    def test_non_qa_stage_is_debug_only(self, monkeypatch, caplog, capsys):
        from yoke_core.domain import deploy_qa_stage_result

        monkeypatch.setattr(
            deploy_qa_stage_result,
            "resolve_stages_json_for_run",
            lambda run_id, *, db_path=None: json.dumps(
                [
                    {"name": "merged", "step_runner": "auto"},
                ]
            ),
        )

        with caplog.at_level(
            logging.DEBUG,
            logger="yoke_core.domain.deploy_qa_stage_result",
        ):
            result = deploy_qa_recorder.cmd_record_stage_result(
                "run-1", "merged", "pass"
            )

        assert result is None
        assert capsys.readouterr() == ("", "")
        assert "not a QA stage" in caplog.text

    def test_unresolvable_run_raises_instead_of_a_quiet_none(self, monkeypatch):
        """A missing run/flow must not read the same as "not a QA stage"."""
        from yoke_core.domain import deploy_qa_stage_result

        def _raise(run_id, *, db_path=None):
            raise LookupError(f"deployment run {run_id!r} not found or has no flow")

        monkeypatch.setattr(
            deploy_qa_stage_result, "resolve_stages_json_for_run", _raise
        )

        with pytest.raises(RuntimeError, match="run-missing"):
            deploy_qa_recorder.cmd_record_stage_result("run-missing", "merged", "pass")
