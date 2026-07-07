"""sections — main dispatcher and event-fallback coverage.

Split out of ``test_sections.py`` to keep authored files under the 350-line
limit.
"""

from __future__ import annotations

import io
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

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


class TestMainDispatcher:
    def test_no_args_returns_2_and_prints_usage(self, tmp_path: Path) -> None:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = sections.main([])
        assert rc == 2
        assert "sections subcommands:" in err.getvalue()

    def test_unknown_subcommand_returns_2(self, tmp_path: Path) -> None:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = sections.main(["bogus"])
        assert rc == 2
        assert "unknown sections subcommand 'bogus'" in err.getvalue()

    def test_main_upsert_roundtrip_via_subprocess_style(
        self,
        db_path: str,
        renderer: _RecordingRenderer,
        emitter: _RecordingEmitter,
        tmp_path: Path,
    ) -> None:
        content_file = tmp_path / "content.md"
        content_file.write_text("cli content\n", encoding="utf-8")
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"YOKE_DB": db_path}), \
             redirect_stdout(out), redirect_stderr(err):
            rc = sections.main(
                [
                    "upsert",
                    "42",
                    "Design",
                    "--content-file",
                    str(content_file),
                ]
            )
        assert rc == 0
        assert "Upserted section: Design for item 42" in out.getvalue()
        assert "Body regenerated for item 42" in out.getvalue()
        assert sections.get_section(42, "Design", db_path=db_path) == "cli content\n"


class TestEventFallback:
    def test_emitter_exception_does_not_abort_op(
        self,
        db_path: str,
        renderer: _RecordingRenderer,
        tmp_path: Path,
    ) -> None:
        def boom(*_args, **_kwargs):
            raise RuntimeError("emitter dead")

        sections.set_event_emitter(boom)
        content_file = tmp_path / "content.md"
        content_file.write_text("body", encoding="utf-8")
        rc, out, err = _run_cli(
            sections.cmd_upsert,
            ["42", "Design", "--content-file", str(content_file)],
            db_path=db_path,
        )
        assert rc == 0
        assert "Upserted section: Design for item 42" in out
        assert sections.get_section(42, "Design", db_path=db_path) == "body"
