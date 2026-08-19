"""A rendered Pulumi program must carry every project module it imports."""

from __future__ import annotations

import pytest

from yoke_core.domain.project_renderer_pulumi_files import (
    ENVIRONMENT_PROGRAM_FILES,
    SHARED_PROGRAM_FILES,
)
from yoke_core.domain.project_renderer_pulumi_imports import (
    RenderedProgramIncomplete,
    assert_rendered_program_complete,
    close_rendered_program_imports,
)
from yoke_core.domain.project_renderer_pulumi_scoped import (
    render_scoped_pulumi_config,
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
    assert "project infra tree" in message


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


def test_close_copies_imported_sibling_and_its_transitive_import(tmp_path):
    destination, available = _project(
        tmp_path,
        rendered={
            "webapp_environment_stack.py": (
                "from webapp_log_observability import attach\n"
            ),
        },
        infra={
            "webapp_log_observability.py": (
                "from webapp_log_sink import sink\n"
                "def attach():\n    return sink\n"
            ),
            "webapp_log_sink.py": "sink = None\n",
        },
    )

    added = close_rendered_program_imports(destination, available=available)

    assert added == ["webapp_log_observability.py", "webapp_log_sink.py"]
    assert (destination / "webapp_log_observability.py").is_file()
    assert (destination / "webapp_log_sink.py").is_file()
    assert_rendered_program_complete(destination, available=available)


def test_scoped_render_carries_imported_sibling_absent_from_inventory(tmp_path):
    project_root = tmp_path / "project"
    infra = project_root / "infra"
    infra.mkdir(parents=True)
    (infra / "Pulumi.yaml").write_text("name: acme\nruntime: python\n")
    (infra / "Pulumi.environment-stack.yaml.tmpl").write_text("config: {}\n")
    for name in (*SHARED_PROGRAM_FILES, *ENVIRONMENT_PROGRAM_FILES):
        if not name.endswith(".py"):
            (infra / name).write_text("# requirements\n")
            continue
        body = ""
        if name == "webapp_environment_stack.py":
            body = "from webapp_log_observability import attach\n"
        (infra / name).write_text(body)
    (infra / "webapp_log_observability.py").write_text(
        "def attach():\n    return None\n"
    )

    render_scoped_pulumi_config(
        {
            "config_schema": 2,
            "project_slug": "acme",
            "stack_name": "acme-stage",
            "stack_kind": "environment",
            "render_values": {"project_name": "acme"},
            "operator_state": {
                "secrets_provider": "passphrase",
                "encrypted_key": "encrypted",
            },
        },
        project_root=project_root,
        output_dir=tmp_path / "render",
    )

    assert (
        tmp_path / "render" / "infra" / "webapp_log_observability.py"
    ).is_file()
    assert not (tmp_path / "render" / "infra" / "webapp_unused.py").exists()
