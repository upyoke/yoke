"""Failures and test timeouts cannot become unchanged-input recovery."""

from types import SimpleNamespace

import pytest

from yoke_contracts.function_serving_floors import FUNCTION_MINIMUM_SERVING_VERSIONS
from yoke_core.domain import ci_run_redispatch, qa_case_ci_conclusion
from yoke_core.domain.merge_queue_landing_timeout import merge_item_resume_command
from yoke_core.domain.standalone_item_merge_cli_parser import build_parser


def test_removed_retry_flag_is_rejected_and_never_resumed():
    args = SimpleNamespace(retry_flake="old reason")
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["ITEM", "--retry-flake", "reason"])
    assert exc.value.code == 2
    assert "--retry-flake" not in merge_item_resume_command("ITEM", args)


def test_retired_retry_function_has_no_registry_floor_or_authority():
    from yoke_core.domain.yoke_function_registry import list_entries
    from yoke_core.domain.function_authz_product_scopes import PRODUCT_AUTHZ_BY_ID

    from yoke_core.domain.handlers.__init_register__ import register_all_handlers

    register_all_handlers()
    retired = "merge_queue.flake_retry.claim"
    assert retired not in FUNCTION_MINIMUM_SERVING_VERSIONS
    assert retired not in PRODUCT_AUTHZ_BY_ID
    assert retired not in {entry.function_id for entry in list_entries()}


def test_test_timeout_is_red_and_wait_timeout_has_no_verdict(monkeypatch):
    assert "timed_out" in ci_run_redispatch.VERDICT_CONCLUSIONS
    assert "timed_out" in qa_case_ci_conclusion.BINDING_CONCLUSIONS
    assert qa_case_ci_conclusion.failure_verdict("timed_out") == (
        "fail",
        "test_failure",
    )
    assert (
        qa_case_ci_conclusion.conclusion_from_poll(1, "failed:timed_out") == "timed_out"
    )
    assert (
        qa_case_ci_conclusion.conclusion_from_poll(1, "poll timed out on live run")
        == "error"
    )
    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_reporting._github_actions",
        lambda *a, **kw: SimpleNamespace(
            returncode=1, stdout="failed:timed_out", stderr=""
        ),
    )
    assert (
        ci_run_redispatch.concluded_without_verdict(
            project="app", repo="org/app", run_id="1"
        )
        == ""
    )
    assert ci_run_redispatch.REPLAY_CHAIN_LIMIT == 20
