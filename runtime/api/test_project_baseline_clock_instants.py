"""Native project and baseline SQL facts cross explicit text and JSON owners."""

from datetime import date, datetime
import json

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.timestamps import format_instant, parse_instant

STAMP = parse_instant("1970-01-01T05:44:59.999999+05:45")
TITLE = "opaque 1969-12-31T23:59:59 project name"


class _KeepOpen:
    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def close(self):
        pass


def test_text_formatter_aliases_preserve_nonclock_cells_and_refuse_naive():
    from yoke_core.domain import items_constants, projects_crud, qa, qa_constants
    from yoke_core.domain import qa_reporting
    from yoke_core.domain.deployment_run_pipe_format import pipe_row
    from yoke_core.domain.project_public_prefix import typed_project_field

    assert qa_reporting._pipe_row is qa_constants._pipe_row
    assert qa_reporting._coalesce is qa_constants._coalesce
    assert qa._pipe_row is qa_constants._pipe_row
    formatters = [
        qa_reporting._pipe_row,
        projects_crud._pipe_row,
        items_constants._pipe_row,
        pipe_row,
    ]
    values = [
        STAMP,
        parse_instant("2026-01-01T00:00:00Z"),
        None,
        TITLE,
        17,
        date(2026, 1, 1),
    ]
    expected = "|".join(
        [
            format_instant(STAMP),
            "2026-01-01T00:00:00.000000Z",
            "",
            TITLE,
            "17",
            "2026-01-01",
        ]
    )
    for formatter in formatters:
        assert formatter(values) == expected
        with pytest.raises(ValueError):
            formatter([datetime(2026, 1, 1)])
    assert qa_reporting._pipe_row(
        {"clock": STAMP, "text": TITLE}, ["clock", "text"]
    ) == (format_instant(STAMP) + "|" + TITLE)
    for field in ("created_at", "retired_at"):
        assert typed_project_field(field, None) is None
        assert typed_project_field(field, "") is None
        assert typed_project_field(field, "1970-01-01T05:44:59.999999+05:45") == STAMP
        with pytest.raises(ValueError):
            typed_project_field(field, "2026-01-01")
    assert typed_project_field("name", TITLE) == TITLE


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_actual_project_and_baseline_readers_keep_native_sql_and_owned_text(
    test_db, monkeypatch, capsys, zone
):
    from runtime.api.domain.handlers.projects_handler_test_support import (
        project_request,
    )
    from yoke_core.domain import (
        db_helpers,
        projects_crud,
        projects_upsert,
        qa_reporting,
    )
    from yoke_core.domain.handlers import projects_get, projects_resolve
    from yoke_core.domain.projects import PROJECT_FIELDS, _PROJECT_LIST_FIELDS

    conn = _KeepOpen(test_db)
    monkeypatch.setattr(projects_crud, "connect", lambda *_args, **_kw: conn)
    monkeypatch.setattr(db_helpers, "connect", lambda *_args, **_kw: conn)
    monkeypatch.setattr(qa_reporting, "connect", lambda *_args, **_kw: conn)
    monkeypatch.setattr(qa_reporting, "_now_iso", lambda: STAMP)
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    test_db.execute(
        "INSERT INTO projects (id,slug,name,public_item_prefix,github_repo,created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (910, "clock-project", TITLE, "CLK", "example/clock-project", STAMP),
    )
    test_db.commit()
    wire_stamp = format_instant(STAMP)
    assert projects_crud.cmd_get("910", "created_at") == wire_stamp
    assert projects_crud.cmd_get("910", "retired_at") == ""
    assert projects_crud.cmd_get("910", "name") == TITLE
    row = projects_crud.cmd_get("910").split("|")
    assert row[PROJECT_FIELDS.index("created_at")] == wire_stamp
    assert row[PROJECT_FIELDS.index("retired_at")] == ""
    line = next(
        line
        for line in projects_crud.cmd_list().splitlines()
        if line.split("|")[0] == "910"
    )
    assert line.split("|")[_PROJECT_LIST_FIELDS.index("created_at")] == wire_stamp

    get = projects_get.handle_projects_get(project_request({"project": "910"}))
    scalar = projects_get.handle_projects_get(
        project_request({"project": "910", "field": "created_at"})
    )
    assert get.primary_success and scalar.primary_success
    assert scalar.result_payload["value"] == STAMP
    assert projects_get.ProjectsGetResponse(**scalar.result_payload).value == STAMP
    outcomes = [get]
    for fields in (None, ["id", "name", "created_at", "retired_at"]):
        payload = {} if fields is None else {"fields": fields}
        listed = projects_get.handle_projects_list(
            project_request(payload, function="projects.list")
        )
        assert listed.primary_success
        native = next(row for row in listed.result_payload["rows"] if row["id"] == 910)
        assert native["created_at"] == STAMP
        assert isinstance(native["created_at"], datetime)
        if fields:
            assert native["retired_at"] is None and native["name"] == TITLE
    resolved = projects_resolve.handle_projects_resolve_by_github_repo(
        project_request(
            {"github_repo": "example/clock-project"},
            function="projects.resolve_by_github_repo",
        ),
        visibility_reader=lambda *_: None,
    )
    assert resolved.primary_success
    outcomes.append(resolved)
    stored = test_db.execute("SELECT * FROM projects WHERE id=910").fetchone()
    native = projects_upsert._row_dict(stored)
    assert native["created_at"] == STAMP and native["retired_at"] is None
    for outcome in outcomes:
        assert outcome.result_payload["row"]["created_at"] == STAMP
        wire = FunctionCallResponse(
            function="projects.get",
            version="v1",
            success=True,
            result=outcome.result_payload,
        ).model_dump(mode="json")
        assert wire["result"]["row"]["created_at"] == wire_stamp
        assert wire["result"]["row"]["retired_at"] is None

    artifact_id = qa_reporting.cmd_baseline_record(
        route="/clock", width=800, height=600, branch="main", screenshot_path="shot.png"
    )
    assert capsys.readouterr().out == str(artifact_id) + "\n"
    assert test_db.execute("SHOW TimeZone").fetchone()[0] == zone
    stored = test_db.execute(
        "SELECT created_at,metadata FROM qa_artifacts WHERE id=%s", (artifact_id,)
    ).fetchone()
    assert stored[0] == STAMP and isinstance(stored[0], datetime)
    metadata = stored[1]
    assert json.loads(metadata)["captured_at"] == wire_stamp
    lines = qa_reporting.cmd_baseline_list()
    assert len(lines) == 1 and lines[0].split("|")[-1] == wire_stamp
    assert capsys.readouterr().out == lines[0] + "\n"
    line = qa_reporting.cmd_baseline_get("/clock", "800x600")
    assert line.split("|")[-1] == wire_stamp
    assert capsys.readouterr().out == line + "\n"
    assert line.split("|")[2] == metadata
    assert (
        test_db.execute(
            "SELECT metadata FROM qa_artifacts WHERE id=%s", (artifact_id,)
        ).fetchone()[0]
        == metadata
    )
