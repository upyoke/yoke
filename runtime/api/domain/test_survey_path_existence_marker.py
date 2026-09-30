"""A surveyed path says whether it exists yet, so readers stop guessing.

Regression: size alone could not distinguish a file the work will create
from an existing empty one — both count zero lines — so agents opened and
selected files that were not there yet.
"""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

from yoke_cli.commands.adapters.file_line_sizing import (
    path_existence_label,
    survey_path_sizes,
)
from yoke_core.domain.handlers.direct_workflow_survey import SurveyPathSize


def test_sizing_marks_an_existing_path_and_a_path_still_to_be_created(
    tmp_path: Path,
) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "present.py").write_text("x = 1\n")

    sizes = survey_path_sizes(
        ["pkg/present.py", "pkg/planned.py"], tree_root=str(tmp_path)
    )

    assert [(size["path"], size["exists"]) for size in sizes] == [
        ("pkg/present.py", True),
        ("pkg/planned.py", False),
    ]


def test_an_empty_existing_file_is_not_reported_as_new(tmp_path: Path) -> None:
    (tmp_path / "empty.py").write_text("")

    [size] = survey_path_sizes(["empty.py"], tree_root=str(tmp_path))

    assert size["current_line_count"] == 0
    assert size["exists"] is True
    assert path_existence_label(size) == "existing"


def test_the_label_distinguishes_new_from_an_unanswered_marker() -> None:
    assert path_existence_label({"exists": True}) == "existing"
    assert path_existence_label({"exists": False}) == "new"
    assert path_existence_label({}) == "unknown"
    assert path_existence_label({"exists": None}) == "unknown"


def test_an_echo_without_the_marker_keeps_the_clients_own_measurement() -> None:
    echo = {"path": "pkg/planned.py"}

    assert path_existence_label(echo, {"pkg/planned.py": False}) == "new"
    assert path_existence_label(echo, {"pkg/present.py": True}) == "unknown"
    assert path_existence_label({"path": "p", "exists": True}, {"p": False}) == (
        "existing"
    )


def test_a_request_composed_without_the_marker_is_still_accepted() -> None:
    row = SurveyPathSize.model_validate({
        "path": "pkg/file.py",
        "current_line_count": 10,
        "remaining_headroom": 340,
        "at_or_over_limit": False,
        "limit": 350,
        "classification": "authored",
    })

    assert row.exists is None
    assert path_existence_label(row.model_dump()) == "unknown"


def test_the_receipt_line_ends_with_the_existence_of_each_path(monkeypatch) -> None:
    from yoke_cli.commands.adapters import dash

    sized = {
        "path": "pkg/planned.py",
        "current_line_count": 0,
        "remaining_headroom": 350,
        "at_or_over_limit": False,
        "limit": 350,
        "classification": "authored",
        "exists": False,
    }
    captured: dict = {}

    def _dispatch(*, human_writer, **_kwargs):
        captured["human_writer"] = human_writer
        return 0

    monkeypatch.setattr(dash, "dispatch_and_emit", _dispatch)
    monkeypatch.setattr(
        dash, "item_lane_tree",
        lambda *_a, **_k: SimpleNamespace(live=False, checkout=None),
    )
    monkeypatch.setattr(dash, "survey_path_sizes", lambda _paths, **_k: [sized])

    assert dash.dash_survey(["YOK-9", "--path", "pkg/planned.py"]) == 0

    out = io.StringIO()
    captured["human_writer"](
        SimpleNamespace(
            result={"touch_path_update": "replace", "path_sizes": [sized]}
        ),
        out,
        io.StringIO(),
    )

    assert out.getvalue().rstrip().endswith("|authored|new")
