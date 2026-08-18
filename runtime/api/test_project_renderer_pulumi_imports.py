"""A rendered Pulumi program must carry every project module it imports."""

from __future__ import annotations

import pytest

from yoke_core.domain.project_renderer_pulumi_imports import (
    RenderedProgramIncomplete,
    assert_rendered_program_complete,
)


def _project(tmp_path, *, rendered: dict[str, str], infra: dict[str, str]):
    destination = tmp_path / "render"
    available = tmp_path / "infra"
    destination.mkdir()
    available.mkdir()
    for name, body in rendered.items():
        (destination / name).write_text(body, encoding="utf-8")
    for name, body in infra.items():
        (available / name).write_text(body, encoding="utf-8")
    return destination, available


def test_program_carrying_every_sibling_it_imports_passes(tmp_path):
    destination, available = _project(
        tmp_path,
        rendered={
            "__main__.py": "from webapp_stack import build\n",
            "webapp_stack.py": "def build():\n    return None\n",
        },
        infra={"webapp_stack.py": "", "webapp_unused.py": ""},
    )

    assert_rendered_program_complete(destination, available=available)


def test_missing_sibling_names_the_module_and_its_importer(tmp_path):
    destination, available = _project(
        tmp_path,
        rendered={"__main__.py": "from webapp_binding import converge\n"},
        infra={"webapp_binding.py": ""},
    )

    with pytest.raises(RenderedProgramIncomplete) as excinfo:
        assert_rendered_program_complete(destination, available=available)

    message = str(excinfo.value)
    assert "webapp_binding.py" in message
    assert "__main__.py" in message
    assert "project_renderer_pulumi_files.py" in message


def test_deferred_import_inside_a_function_is_still_checked(tmp_path):
    # A stack defers an optional dependency to the point of use, which is
    # exactly where an omission hides until the program runs.
    destination, available = _project(
        tmp_path,
        rendered={
            "webapp_environment_stack.py": (
                "def build():\n"
                "    from webapp_binding import converge\n"
                "    return converge\n"
            )
        },
        infra={"webapp_binding.py": ""},
    )

    with pytest.raises(RenderedProgramIncomplete):
        assert_rendered_program_complete(destination, available=available)


def test_third_party_imports_are_not_this_check_s_business(tmp_path):
    destination, available = _project(
        tmp_path,
        rendered={"__main__.py": "import pulumi\nimport pulumi_aws as aws\n"},
        infra={},
    )

    assert_rendered_program_complete(destination, available=available)


def test_plain_import_of_a_sibling_is_caught(tmp_path):
    destination, available = _project(
        tmp_path,
        rendered={"__main__.py": "import webapp_records\n"},
        infra={"webapp_records.py": ""},
    )

    with pytest.raises(RenderedProgramIncomplete):
        assert_rendered_program_complete(destination, available=available)


def test_unparseable_program_defers_to_its_own_failure(tmp_path):
    # A program that does not parse reports that better than this check can.
    destination, available = _project(
        tmp_path,
        rendered={"__main__.py": "def broken(\n"},
        infra={"webapp_binding.py": ""},
    )

    assert_rendered_program_complete(destination, available=available)
