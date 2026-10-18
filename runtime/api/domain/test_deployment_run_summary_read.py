"""Summary pages preserve scope and continuation within transport budgets."""

import json

import pytest

from runtime.api.domain.test_deployment_delivery_close_out_notice import _project
from runtime.api.domain.test_run_success_member_settlement import _executing_run
from yoke_core.domain.deployment_run_history_read import decode_cursor
from yoke_core.domain.deployment_run_summary_read import (
    SUMMARY_FIELDS,
    SUMMARY_PAGE_BYTES,
    list_run_summaries,
    summary_page,
)
from yoke_cli.transport.output_limit import READ_OUTPUT_LIMIT_BYTES


def _row(index, label="release"):
    return dict(
        zip(
            SUMMARY_FIELDS,
            [
                f"run-{index:04}",
                "example",
                label,
                "prod",
                "executing",
                "verify",
                "2026-10-18T00:00:00Z",
                "a" * 40,
            ],
        )
    )


def test_default_summary_fits_complete_json_and_human_output():
    from io import StringIO
    from yoke_cli.transport.human_values import write_human

    page = summary_page([_row(index) for index in range(21)], 20)
    assert len(page["rows"]) == 20
    assert decode_cursor(page["next_cursor"])[1] == "run-0019"
    assert "get RUN-ID FIELD ..." in page["detail_recipe"]
    encoded = json.dumps(
        {"success": True, "function": "deployment_runs.list", "result": page}, indent=2
    )
    output = StringIO()
    write_human(page, output)
    assert len(encoded.encode()) < READ_OUTPUT_LIMIT_BYTES
    assert len(output.getvalue().encode()) < READ_OUTPUT_LIMIT_BYTES


def test_byte_bound_keeps_whole_unicode_rows_and_last_emitted_cursor():
    rows = [_row(index, "大" * 200) for index in range(51)]
    page = summary_page(rows, 50)
    assert 0 < len(page["rows"]) < 50
    assert page["rows"] == rows[: len(page["rows"])]
    assert decode_cursor(page["next_cursor"])[1] == page["rows"][-1]["id"]
    assert len(json.dumps(page, indent=2).encode()) <= SUMMARY_PAGE_BYTES


def test_single_oversized_summary_names_recovery():
    with pytest.raises(
        ValueError,
        match="deployment_run_summary_row_too_large.*Read yoke deployment-runs get",
    ):
        summary_page([_row(1, "x" * 30000)], 20)


def test_paging_all_runs_with_equal_timestamps_has_no_skips(test_db, monkeypatch):
    _project(test_db)
    for index in range(23):
        _executing_run(test_db, f"run-summary-{index:03}", ())
    test_db.execute(
        "UPDATE deployment_runs SET created_at=%s", ("2026-10-18T00:00:00Z",)
    )
    test_db.commit()
    import yoke_core.domain.deployment_run_summary_read as reads

    monkeypatch.setattr(reads, "actor_visible_project_ids", lambda *_: None)
    loaded = []
    cursor = None
    while True:
        page = list_run_summaries(
            project=None, status="executing", limit=7, cursor=cursor, actor_id=None
        )
        loaded.extend(row["id"] for row in page["rows"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert loaded == [f"run-summary-{index:03}" for index in reversed(range(23))]


def test_summary_scope_hides_runs_and_project_filters(test_db, monkeypatch):
    _project(test_db)
    _executing_run(test_db, "run-visible", ())
    import yoke_core.domain.deployment_run_summary_read as reads

    monkeypatch.setattr(reads, "actor_visible_project_ids", lambda *_: set())
    page = list_run_summaries(
        project=None, status=None, limit=20, cursor=None, actor_id=9
    )
    assert page["rows"] == []
    assert page["next_cursor"] is None


def test_cli_multi_field_get_and_summary_cursor_dispatch():
    from runtime.api.cli.test_yoke_operations_cli_deployment import (
        _run_capture,
        _CAPTURED_REQUESTS,
    )
    from yoke_contracts.api.function_call import FunctionCallResponse

    def stub(request):
        _CAPTURED_REQUESTS.append(request)
        if request.function == "deployment_runs.get":
            result = {
                "fields": ["status", "release_lineage"],
                "run": {"status": "created", "release_lineage": "a" * 40},
            }
        else:
            result = summary_page([_row(1)], 20)
        return FunctionCallResponse(
            success=True, function=request.function, version="v1", result=result
        )

    rc, out, _ = _run_capture(
        stub, "deployment-runs", "get", "run-example", "status", "release_lineage"
    )
    assert rc == 0
    assert _CAPTURED_REQUESTS[-1].payload == {"fields": ["status", "release_lineage"]}
    assert "carried_work" not in out
    rc, _, _ = _run_capture(stub, "deployment-runs", "list", "--cursor", "cursor-token")
    assert rc == 0
    assert _CAPTURED_REQUESTS[-1].payload == {"summary": True, "cursor": "cursor-token"}


@pytest.mark.parametrize(
    "arguments",
    [
        ["deployment-runs", "get", "run-example", "status", "release_lineage"],
        ["deployment-runs", "list"],
    ],
)
def test_old_serving_contract_refuses_instead_of_returning_unselected_detail(arguments):
    from runtime.api.cli.test_yoke_operations_cli_deployment import (
        _run_capture,
        _stub_ok,
    )

    rc, _, error = _run_capture(_stub_ok, *arguments)
    assert rc != 0
    assert "deployment_run_read_projection_unavailable" in error
    assert "Serving floor" in error
