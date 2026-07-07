"""sections — CLI subcommand surfaces (upsert/get/list/delete).

Split out of ``test_sections.py`` to keep authored files under the 350-line
limit.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import sections
from yoke_core.domain.sections_test_helpers import (  # noqa: F401 — fixtures
    _RecordingEmitter,
    _RecordingRenderer,
    _reset_injectables,
    _run_cli,
    db_path,
    emitter,
    renderer,
)


class TestCmdUpsert:
    def test_happy_path_emits_event_and_rerenders(
        self,
        db_path: str,
        renderer: _RecordingRenderer,
        emitter: _RecordingEmitter,
        tmp_path: Path,
    ) -> None:
        content_file = tmp_path / "content.md"
        content_file.write_text("hello body\n", encoding="utf-8")
        rc, out, err = _run_cli(
            sections.cmd_upsert,
            ["42", "Design", "--content-file", str(content_file)],
            db_path=db_path,
        )
        assert rc == 0
        assert "Upserted section: Design for item 42" in out
        assert "Body regenerated for item 42" in out
        assert err == ""
        assert renderer.calls == [(42, db_path)]
        assert len(emitter.calls) == 1
        ev = emitter.calls[0]
        assert ev["event_name"] == "SectionUpserted"
        assert ev["event_kind"] == "system"
        assert ev["event_type"] == "data_mutation"
        assert ev["source_type"] == "script"
        assert ev["severity"] == "INFO"
        assert ev["outcome"] == "completed"
        assert ev["item_id"] == "42"
        assert ev["context"] == {"item_id": "42", "section": "Design"}

    def test_upsert_optional_ordering_and_source_flags(
        self,
        db_path: str,
        renderer: _RecordingRenderer,
        emitter: _RecordingEmitter,
        tmp_path: Path,
    ) -> None:
        content_file = tmp_path / "content.md"
        content_file.write_text("x", encoding="utf-8")
        rc, _out, _err = _run_cli(
            sections.cmd_upsert,
            [
                "42",
                "Plan",
                "--content-file",
                str(content_file),
                "--ordering",
                "12",
                "--source",
                "architect",
            ],
            db_path=db_path,
        )
        assert rc == 0
        rows = sections.list_sections(42, db_path=db_path)
        assert rows == [("Plan", "12", rows[0][2], rows[0][3])]

    def test_upsert_missing_content_file_returns_1(
        self, db_path: str, renderer: _RecordingRenderer, tmp_path: Path
    ) -> None:
        rc, _out, err = _run_cli(
            sections.cmd_upsert,
            ["42", "Design", "--content-file", str(tmp_path / "nope.md")],
            db_path=db_path,
        )
        assert rc == 1
        assert "content file not found" in err
        assert renderer.calls == []

    def test_upsert_missing_required_args_returns_2(
        self, db_path: str, renderer: _RecordingRenderer
    ) -> None:
        rc, _out, err = _run_cli(
            sections.cmd_upsert, ["42", "Design"], db_path=db_path
        )
        assert rc == 2
        assert "python3 -m yoke_core.domain.sections upsert" in err
        assert renderer.calls == []

    def test_upsert_render_failure_returns_1_still_emits_event(
        self,
        db_path: str,
        emitter: _RecordingEmitter,
        tmp_path: Path,
    ) -> None:
        failing_renderer = _RecordingRenderer(rc=1)
        sections.set_renderer(failing_renderer)
        content_file = tmp_path / "content.md"
        content_file.write_text("body", encoding="utf-8")
        rc, out, err = _run_cli(
            sections.cmd_upsert,
            ["42", "Design", "--content-file", str(content_file)],
            db_path=db_path,
        )
        assert rc == 1
        assert "Upserted section: Design for item 42" in out
        assert "body regeneration failed" in err
        assert "Skipping GitHub sync" in err
        # Event still fires — shell uses `|| true` after failed rerender.
        assert len(emitter.calls) == 1
        assert emitter.calls[0]["event_name"] == "SectionUpserted"
        # Row was written even though rerender failed.
        assert sections.get_section(42, "Design", db_path=db_path) == "body"

    def test_upsert_persists_row(
        self,
        db_path: str,
        renderer: _RecordingRenderer,
        tmp_path: Path,
    ) -> None:
        content_file = tmp_path / "content.md"
        content_file.write_text("persisted", encoding="utf-8")
        rc, _out, _err = _run_cli(
            sections.cmd_upsert,
            ["42", "P", "--content-file", str(content_file)],
            db_path=db_path,
        )
        assert rc == 0
        assert sections.get_section(42, "P", db_path=db_path) == "persisted"


class TestCmdGet:
    def test_get_existing_prints_content_with_newline(
        self, db_path: str, renderer: _RecordingRenderer
    ) -> None:
        sections.upsert_section(42, "X", "hello", db_path=db_path)
        rc, out, err = _run_cli(sections.cmd_get, ["42", "X"], db_path=db_path)
        assert rc == 0
        assert err == ""
        assert out == "hello\n"

    def test_get_multiline_content(
        self, db_path: str, renderer: _RecordingRenderer
    ) -> None:
        sections.upsert_section(42, "X", "line 1\nline 2", db_path=db_path)
        rc, out, _err = _run_cli(sections.cmd_get, ["42", "X"], db_path=db_path)
        assert rc == 0
        assert out == "line 1\nline 2\n"

    def test_get_missing_prints_nothing_exit_0(
        self, db_path: str, renderer: _RecordingRenderer
    ) -> None:
        rc, out, err = _run_cli(sections.cmd_get, ["42", "Nope"], db_path=db_path)
        assert rc == 0
        assert out == ""
        assert err == ""

    def test_get_missing_args_returns_2(self, db_path: str) -> None:
        rc, _out, err = _run_cli(sections.cmd_get, ["42"], db_path=db_path)
        assert rc == 2
        assert "python3 -m yoke_core.domain.sections get" in err


class TestCmdList:
    def test_list_prints_pipe_delimited(
        self, db_path: str, renderer: _RecordingRenderer
    ) -> None:
        sections.upsert_section(42, "A", "a", ordering=1, db_path=db_path)
        sections.upsert_section(42, "B", "b", db_path=db_path)
        rc, out, _err = _run_cli(sections.cmd_list, ["42"], db_path=db_path)
        assert rc == 0
        lines = [line for line in out.splitlines() if line]
        assert len(lines) == 2
        assert lines[0].startswith("A|1|")
        assert lines[1].startswith("B||")
        for line in lines:
            assert line.count("|") == 3

    def test_list_empty_item_exits_0_no_output(
        self, db_path: str, renderer: _RecordingRenderer
    ) -> None:
        rc, out, err = _run_cli(sections.cmd_list, ["42"], db_path=db_path)
        assert rc == 0
        assert out == ""
        assert err == ""

    def test_list_missing_arg_returns_2(self, db_path: str) -> None:
        rc, _out, err = _run_cli(sections.cmd_list, [], db_path=db_path)
        assert rc == 2
        assert "python3 -m yoke_core.domain.sections list" in err


class TestCmdDelete:
    def test_delete_happy_path(
        self,
        db_path: str,
        renderer: _RecordingRenderer,
        emitter: _RecordingEmitter,
    ) -> None:
        sections.upsert_section(42, "Gone", "x", db_path=db_path)
        renderer.calls.clear()
        emitter.calls.clear()

        rc, out, err = _run_cli(
            sections.cmd_delete, ["42", "Gone"], db_path=db_path
        )
        assert rc == 0
        assert "Deleted section: Gone for item 42" in out
        assert "Body regenerated for item 42" in out
        assert err == ""
        assert renderer.calls == [(42, db_path)]
        assert len(emitter.calls) == 1
        ev = emitter.calls[0]
        assert ev["event_name"] == "SectionDeleted"
        assert ev["context"] == {"item_id": "42", "section": "Gone"}
        assert sections.get_section(42, "Gone", db_path=db_path) is None

    def test_delete_missing_args_returns_2(self, db_path: str) -> None:
        rc, _out, err = _run_cli(
            sections.cmd_delete, ["42"], db_path=db_path
        )
        assert rc == 2
        assert "python3 -m yoke_core.domain.sections delete" in err

    def test_delete_render_failure_returns_1(
        self,
        db_path: str,
        emitter: _RecordingEmitter,
    ) -> None:
        sections.upsert_section(42, "Gone", "x", db_path=db_path)
        failing = _RecordingRenderer(rc=2)
        sections.set_renderer(failing)
        rc, out, err = _run_cli(
            sections.cmd_delete, ["42", "Gone"], db_path=db_path
        )
        assert rc == 1
        assert "Deleted section: Gone for item 42" in out
        assert "body regeneration failed" in err
        assert len(emitter.calls) == 1
        assert emitter.calls[0]["event_name"] == "SectionDeleted"
