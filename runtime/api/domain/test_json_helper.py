from __future__ import annotations

import io
import json
from pathlib import Path

from yoke_core.domain.json_helper import dumps_compact, run_command


def test_get_and_set_round_trip(tmp_path):
    target = tmp_path / "sample.json"
    target.write_text('{"name":"old","count":1}\n')

    assert run_command(["set", str(target), "name", "new"], out=io.StringIO(), err=io.StringIO()) == 0

    out = io.StringIO()
    err = io.StringIO()
    assert run_command(["get", str(target), "name"], out=out, err=err) == 0
    assert out.getvalue() == "new\n"
    assert err.getvalue() == ""


def test_set_int_and_increment(tmp_path):
    target = tmp_path / "sample.json"
    target.write_text('{"count":1}\n')

    assert run_command(["set-int", str(target), "count", "5"], out=io.StringIO(), err=io.StringIO()) == 0
    assert run_command(["increment", str(target), "count"], out=io.StringIO(), err=io.StringIO()) == 0

    data = json.loads(target.read_text())
    assert data["count"] == 6


def test_append_and_create(tmp_path):
    target = tmp_path / "sample.json"
    assert run_command(["create", str(target), '{"items": []}'], out=io.StringIO(), err=io.StringIO()) == 0
    assert run_command(
        ["append", str(target), "items", '{"id": 1, "title": "one"}'],
        out=io.StringIO(),
        err=io.StringIO(),
    ) == 0
    data = json.loads(target.read_text())
    assert data["items"] == [{"id": 1, "title": "one"}]


def test_invalid_append_json_fails(tmp_path):
    target = tmp_path / "sample.json"
    target.write_text('{"items":[]}\n')
    err = io.StringIO()
    assert run_command(["append", str(target), "items", "{oops"], out=io.StringIO(), err=err) == 1
    assert "invalid JSON for append value" in err.getvalue()


def test_csv_to_array(tmp_path):
    out = io.StringIO()
    assert run_command(["csv-to-array", "a, b, ,c"], out=out, err=io.StringIO()) == 0
    assert out.getvalue() == '["a", "b", "c"]\n'


def test_dumps_compact_escapes_json_values():
    assert dumps_compact(["self-hosted", 'label"quoted']) == (
        '["self-hosted","label\\"quoted"]'
    )
