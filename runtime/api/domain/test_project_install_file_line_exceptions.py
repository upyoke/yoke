"""The install exempts the rules files it writes from the line limit.

`yoke project install` writes a managed block well past the authored-file
line limit AND installs the pre-merge gate that enforces it. Without the
exemption the install hands a project a gate that rejects the install's own
output, and the project's first commit fails on files it does not own and
cannot split.
"""

from __future__ import annotations

from pathlib import Path

from yoke_cli.project_install.file_line_managed_exceptions import (
    ensure_managed_file_line_exceptions,
)
from yoke_contracts.project_contract.file_line_policy import (
    FILE_LINE_EXCEPTION_KEY,
    PROJECT_CONFIG_REL,
    read_project_config,
)


MANAGED = ("AGENTS.md", "CLAUDE.md", "CODEX.md")


def _config(root: Path) -> Path:
    return root / PROJECT_CONFIG_REL


def test_exemptions_are_written_for_every_managed_rules_file(tmp_path) -> None:
    report = ensure_managed_file_line_exceptions(tmp_path, MANAGED)

    assert report["status"] == "ok"
    assert report["added"] == list(MANAGED)
    text = _config(tmp_path).read_text(encoding="utf-8")
    for rel in MANAGED:
        assert f"{FILE_LINE_EXCEPTION_KEY}={rel}" in text


def test_the_policy_reader_actually_honors_what_was_written(tmp_path) -> None:
    # Guards the guard: entries the config carries but the policy reader does
    # not parse would leave the gate still rejecting the install's output.
    ensure_managed_file_line_exceptions(tmp_path, MANAGED)

    _config_values, globs = read_project_config(tmp_path)

    for rel in MANAGED:
        assert rel in globs


def test_refresh_does_not_duplicate_entries(tmp_path) -> None:
    ensure_managed_file_line_exceptions(tmp_path, MANAGED)
    first = _config(tmp_path).read_text(encoding="utf-8")

    report = ensure_managed_file_line_exceptions(tmp_path, MANAGED)

    assert report["status"] == "unchanged"
    assert report["added"] == []
    assert _config(tmp_path).read_text(encoding="utf-8") == first


def test_existing_project_config_content_is_preserved(tmp_path) -> None:
    # The config is project-owned the moment it is seeded, so the install may
    # only append to it.
    config = _config(tmp_path)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "file_line_limit=500\n"
        f"{FILE_LINE_EXCEPTION_KEY}=docs/generated/**\n",
        encoding="utf-8",
    )

    ensure_managed_file_line_exceptions(tmp_path, MANAGED)

    values, globs = read_project_config(tmp_path)
    assert values["file_line_limit"] == "500"
    assert "docs/generated/**" in globs
    for rel in MANAGED:
        assert rel in globs


def test_a_path_the_project_already_declared_is_left_alone(tmp_path) -> None:
    config = _config(tmp_path)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(f"{FILE_LINE_EXCEPTION_KEY}=AGENTS.md\n", encoding="utf-8")

    report = ensure_managed_file_line_exceptions(tmp_path, MANAGED)

    assert report["added"] == ["CLAUDE.md", "CODEX.md"]
    text = config.read_text(encoding="utf-8")
    assert text.count(f"{FILE_LINE_EXCEPTION_KEY}=AGENTS.md") == 1


def test_a_bundle_declaring_no_managed_targets_writes_nothing(tmp_path) -> None:
    report = ensure_managed_file_line_exceptions(tmp_path, [])

    assert report["status"] == "unchanged"
    assert not _config(tmp_path).exists()
