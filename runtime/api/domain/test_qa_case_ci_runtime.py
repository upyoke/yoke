"""Source gate continuation keeps one authorization and one lane update."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import qa_case_ci_runtime as runtime
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


def test_updated_source_continues_in_fresh_interpreter(tmp_path, monkeypatch):
    domain = tmp_path / "yoke_core" / "domain"
    domain.mkdir(parents=True)
    (domain.parent / "__init__.py").touch()
    (domain / "__init__.py").touch()
    source = Path(runtime.__file__).read_text()
    (domain / "qa_case_ci_runtime.py").write_text(source)
    (domain / "qa_case_execution.py").write_text(
        "class QaCaseExecutionError(RuntimeError): pass\n"
    )
    (domain / "qa_case_ci_lane.py").write_text("")
    (domain / "qa_case_ci_resume.py").write_text("")
    (domain / "qa_case_ci_run.py").write_text(
        "from .current_contract import CURRENT\n"
        "def execute_ci_case(case, **options):\n"
        "    assert options['_prepared']['queue_target'] == 'main'\n"
        "    assert options['_prepared']['previous_head_sha'] == 'old'\n"
        "    assert options['actor'].session_id == 'session-fixture'\n"
        "    return {'verdict': CURRENT, 'case': case, 'expected_sha': options['expected_sha']}\n"
    )
    (domain / "current_contract.py").write_text("CURRENT = 'pass'\n")
    monkeypatch.setattr(runtime, "__file__", str(domain / "qa_case_ci_runtime.py"))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setattr(runtime.qa_case_ci_lane, "ref_sha", lambda *_: "new")
    case = {"requirement_id": 42, "execution_authority": {"opaque": "retained"}}
    result = runtime.continue_updated_source(
        tmp_path,
        "old",
        SimpleNamespace(queue_target="main"),
        case,
        prepared=None,
        actor=ActorContext(session_id="session-fixture"),
        expected_sha="old",
        expected_branch="feature",
        timeout_seconds=120,
        allow_tree_mismatch=False,
    )
    assert result == {"verdict": "pass", "case": case, "expected_sha": "old"}


@pytest.mark.parametrize(
    "prepared,previous,current,source_inside",
    [
        ({"queue_target": "main"}, "old", "new", True),
        (None, "old", "old", True),
        (None, "", "new", True),
        (None, "old", "new", False),
    ],
)
def test_unchanged_installed_or_already_continued_gate_stays_in_process(
    tmp_path,
    monkeypatch,
    prepared,
    previous,
    current,
    source_inside,
):
    monkeypatch.setattr(
        runtime, "__file__", str(tmp_path / "runtime.py") if source_inside else __file__
    )
    monkeypatch.setattr(runtime.qa_case_ci_lane, "ref_sha", lambda *_: current)
    launch = Mock(side_effect=AssertionError("must not launch"))
    monkeypatch.setattr(runtime.subprocess, "run", launch)
    assert (
        runtime.continue_updated_source(
            tmp_path,
            previous,
            SimpleNamespace(queue_target=None),
            {},
            prepared=prepared,
            actor=None,
        )
        is None
    )
    launch.assert_not_called()


def test_restart_failure_names_preserved_lane_and_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "__file__", str(tmp_path / "runtime.py"))
    monkeypatch.setattr(runtime.qa_case_ci_lane, "ref_sha", lambda *_: "new")
    monkeypatch.setattr(
        runtime.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=9)
    )
    with pytest.raises(
        QaCaseExecutionError,
        match="qa_ci_source_restart_failed:.*rerun the same QA case",
    ):
        runtime.continue_updated_source(
            tmp_path,
            "old",
            SimpleNamespace(queue_target=None),
            {},
            prepared=None,
            actor=None,
        )


def test_prepared_candidate_skips_covering_lookup_and_second_update(monkeypatch):
    prepare = Mock(side_effect=AssertionError("must not prepare twice"))
    monkeypatch.setattr(
        runtime.qa_case_ci_resume, "prepare_lane_preserving_covering_run", prepare
    )
    result = runtime.prepare_lane(Path.cwd(), prepared={"queue_target": "main"})
    assert result.queue_target == "main"
    assert result.resumed_run is None
