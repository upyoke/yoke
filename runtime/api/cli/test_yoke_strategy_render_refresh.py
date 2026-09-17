"""CLI refresh payload: local known-set and local-edit conflict handling."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)
from yoke_contracts.project_contract.strategy_docs_header import (
    content_sha256,
    render_file_text,
)
from yoke_contracts.project_contract.strategy_docs_io import write_rendered_files
from yoke_cli.commands.adapters.strategy_render_client import (
    apply_and_fill_missing,
    apply_rendered_docs,
)
from yoke_contracts.project_contract.strategy_docs_paths import (
    strategy_view_path,
)


def _identity() -> dict:
    return {"project_id": 1, "project_slug": "yoke", "docs": []}


def _dispatch(results):
    captured: list[FunctionCallRequest] = []

    def _stub(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result=results[request.function],
        )

    return captured, _stub


def _run(tmp_path: Path, *argv: str, results: dict) -> tuple[int, list]:
    captured, stub = _dispatch(results)
    env = {"YOKE_SESSION_ID": "test-session"}
    with patch.dict("os.environ", env):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=stub,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    rc = cli_main([
                        "strategy", "render", "--target-root", str(tmp_path),
                        *argv,
                    ])
    return rc, captured


class TestRenderKnownPayload:
    def test_first_use_omits_known(self, tmp_path: Path) -> None:
        results = {
            "strategy.doc.list": _identity(),
            "strategy.render.run": {
                "project_id": 1, "project_slug": "yoke", "docs": [],
            },
        }
        rc, captured = _run(tmp_path, results=results)
        assert rc == 0
        render = next(
            req for req in captured if req.function == "strategy.render.run"
        )
        assert render.payload == {}

    def test_existing_files_send_header_known(self, tmp_path: Path) -> None:
        text = render_file_text("MISSION", "2026-06-10T00:00:00Z", "# MISSION\n")
        write_rendered_files(tmp_path, [{
            "slug": "MISSION", "file_text": text, "archived": False,
        }])
        results = {
            "strategy.doc.list": _identity(),
            "strategy.render.run": {
                "project_id": 1, "project_slug": "yoke",
                "docs": [{
                    "slug": "MISSION", "updated_at": "2026-06-10T00:00:00Z",
                    "archived": False, "unchanged": True,
                    "content_sha256": content_sha256("# MISSION\n"),
                }],
            },
        }
        rc, captured = _run(tmp_path, results=results)
        assert rc == 0
        render = next(
            req for req in captured if req.function == "strategy.render.run"
        )
        assert render.payload["known"] == [{
            "slug": "MISSION",
            "updated_at": "2026-06-10T00:00:00Z",
            "content_sha256": content_sha256("# MISSION\n"),
            "archived": False,
        }]


class TestSteerNarrowedRead:
    def test_steer_skill_teaches_doc_get_not_corpus_render(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        skill = (root / ".agents/skills/yoke/steer/SKILL.md").read_text(
            encoding="utf-8",
        )
        loop = (root / ".agents/skills/yoke/steer/loop.md").read_text(
            encoding="utf-8",
        )
        assert "narrowed steering read" in loop
        assert "never `yoke strategy render` of the corpus" in skill
    def test_dirty_unchanged_remote_keeps_edit(self, tmp_path: Path) -> None:
        original = render_file_text("MISSION", "ts", "# old\n")
        write_rendered_files(tmp_path, [{
            "slug": "MISSION", "file_text": original, "archived": False,
        }])
        path = tmp_path / ".yoke" / "strategy" / "MISSION.md"
        header, _, _ = path.read_text(encoding="utf-8").partition("\n")
        path.write_text(header + "\n# local edit\n", encoding="utf-8")
        report, conflicts = apply_rendered_docs(tmp_path, [{
            "slug": "MISSION", "unchanged": True, "archived": False,
        }])
        assert conflicts == []
        assert report["MISSION"] == "local-edit"
        assert "# local edit" in path.read_text(encoding="utf-8")

    def test_dirty_changed_remote_is_conflict(self, tmp_path: Path) -> None:
        original = render_file_text("MISSION", "ts", "# old\n")
        write_rendered_files(tmp_path, [{
            "slug": "MISSION", "file_text": original, "archived": False,
        }])
        path = tmp_path / ".yoke" / "strategy" / "MISSION.md"
        header, _, _ = path.read_text(encoding="utf-8").partition("\n")
        path.write_text(header + "\n# local edit\n", encoding="utf-8")
        remote = render_file_text("MISSION", "ts2", "# remote\n")
        report, conflicts = apply_rendered_docs(tmp_path, [{
            "slug": "MISSION", "file_text": remote, "archived": False,
        }])
        assert conflicts == ["MISSION"]
        assert "MISSION" not in report
        assert "# local edit" in path.read_text(encoding="utf-8")


class TestApplyArchiveAndMissing:
    def test_clean_active_moves_to_archive_without_body(
        self, tmp_path: Path,
    ) -> None:
        text = render_file_text("MISSION", "ts", "# body\n")
        write_rendered_files(tmp_path, [{
            "slug": "MISSION", "file_text": text, "archived": False,
        }])
        digest = content_sha256("# body\n")
        report, conflicts = apply_rendered_docs(tmp_path, [{
            "slug": "MISSION", "archived": True, "unchanged": False,
            "updated_at": "ts", "content_sha256": digest,
        }])
        assert conflicts == []
        assert report["MISSION"] == "archived"
        assert not strategy_view_path(tmp_path, "MISSION").is_file()
        assert strategy_view_path(tmp_path, "MISSION", True).is_file()

    def test_dirty_active_stays_on_archive_flip(self, tmp_path: Path) -> None:
        original = render_file_text("MISSION", "ts", "# old\n")
        write_rendered_files(tmp_path, [{
            "slug": "MISSION", "file_text": original, "archived": False,
        }])
        path = tmp_path / ".yoke" / "strategy" / "MISSION.md"
        header, _, _ = path.read_text(encoding="utf-8").partition("\n")
        path.write_text(header + "\n# local edit\n", encoding="utf-8")
        report, conflicts = apply_rendered_docs(tmp_path, [{
            "slug": "MISSION", "archived": True, "unchanged": False,
            "updated_at": "ts",
            "content_sha256": content_sha256("# old\n"),
        }])
        assert conflicts == []
        assert report["MISSION"] == "local-edit"
        assert "# local edit" in path.read_text(encoding="utf-8")

    def test_stale_generated_active_is_removed_not_moved(
        self, tmp_path: Path,
    ) -> None:
        text = render_file_text("MISSION", "ts", "# old\n")
        write_rendered_files(tmp_path, [{
            "slug": "MISSION", "file_text": text, "archived": False,
        }])
        report, conflicts = apply_rendered_docs(tmp_path, [{
            "slug": "MISSION", "archived": True, "unchanged": False,
            "updated_at": "ts2",
            "content_sha256": content_sha256("# new\n"),
        }])
        assert conflicts == []
        assert report["MISSION"] == "removed"
        assert not strategy_view_path(tmp_path, "MISSION").is_file()
        assert not strategy_view_path(tmp_path, "MISSION", True).is_file()

    def test_unchanged_matching_file_stays_unchanged(self, tmp_path: Path) -> None:
        text = render_file_text("MISSION", "ts", "# body\n")
        write_rendered_files(tmp_path, [{
            "slug": "MISSION", "file_text": text, "archived": False,
        }])
        digest = content_sha256("# body\n")
        report, conflicts = apply_rendered_docs(tmp_path, [{
            "slug": "MISSION", "unchanged": True, "archived": False,
            "updated_at": "ts", "content_sha256": digest,
        }])
        assert conflicts == []
        assert report["MISSION"] == "unchanged"
        assert strategy_view_path(tmp_path, "MISSION").is_file()

    def test_unchanged_missing_file_is_not_claimed_present(
        self, tmp_path: Path,
    ) -> None:
        report, conflicts = apply_rendered_docs(tmp_path, [{
            "slug": "MISSION", "unchanged": True, "archived": False,
            "updated_at": "ts",
            "content_sha256": content_sha256("# body\n"),
        }])
        assert conflicts == []
        assert report["MISSION"] == "missing"

    def test_fill_missing_fetches_body(self, tmp_path: Path) -> None:
        remote = render_file_text("MISSION", "ts", "# body\n")

        def _fetch(slugs):
            assert list(slugs) == ["MISSION"]
            return [{
                "slug": "MISSION", "file_text": remote, "archived": False,
            }]

        report, conflicts = apply_and_fill_missing(
            tmp_path,
            [{
                "slug": "MISSION", "unchanged": True, "archived": False,
                "updated_at": "ts",
                "content_sha256": content_sha256("# body\n"),
            }],
            fetch_docs=_fetch,
        )
        assert conflicts == []
        assert report["MISSION"] == "written"
        assert "missing" not in report.values()
        assert "# body" in strategy_view_path(tmp_path, "MISSION").read_text(
            encoding="utf-8",
        )
