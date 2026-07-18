"""Dispatch-path tests for the ``yoke strategy`` family adapters."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import List, Optional
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


_CAPTURED_REQUESTS: List[FunctionCallRequest] = []


def _stub_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True, function=request.function, version=request.version,
        request_id=request.request_id, result={"echo": True},
    )


def _stub_call_dispatcher(**kwargs) -> FunctionCallResponse:
    request = FunctionCallRequest(
        function=kwargs["function_id"],
        actor=kwargs["actor"],
        target=kwargs["target"],
        payload=kwargs.get("payload") or {},
    )
    return _stub_ok(request)


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(
    *argv: str,
    stdin_text: Optional[str] = None,
    session_id: Optional[str] = "test-session",
    extra_env: Optional[dict] = None,
) -> int:
    # Transport isolation (real machine config vs in-process dispatch
    # stub) is owned by the autouse ``_isolate_machine_config`` fixture
    # in this directory's conftest.
    env = {}
    if session_id is not None:
        env["YOKE_SESSION_ID"] = session_id
    if extra_env:
        env.update(extra_env)
    with patch.dict("os.environ", env, clear=session_id is None):
        with patch(
            "yoke_cli.transport.dispatcher."
            "_resolve_session_id",
            return_value=session_id,
        ):
            with patch(
                "yoke_cli.commands._helpers."
                "call_dispatcher",
                side_effect=_stub_call_dispatcher,
            ):
                with patch(
                    "yoke_cli.commands.adapters.strategy."
                    "call_dispatcher",
                    side_effect=_stub_call_dispatcher,
                ):
                    with patch(
                        "yoke_cli.commands.adapters.strategy_render."
                        "call_dispatcher",
                        side_effect=_stub_call_dispatcher,
                    ):
                        with patch(
                            "yoke_cli.commands._helpers."
                            "ensure_handlers_loaded"
                        ):
                            with patch("sys.stdin", io.StringIO(stdin_text or "")):
                                with redirect_stdout(io.StringIO()), \
                                        redirect_stderr(io.StringIO()):
                                    return cli_main(list(argv))


class TestRegistry:
    def test_tokens_resolve_to_function_ids(self) -> None:
        from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

        assert SUBCOMMAND_REGISTRY[("strategy", "doc", "list")][0] == (
            "strategy.doc.list"
        )
        assert SUBCOMMAND_REGISTRY[("strategy", "doc", "get")][0] == (
            "strategy.doc.get"
        )
        assert SUBCOMMAND_REGISTRY[("strategy", "doc", "create")][0] == (
            "strategy.doc.create"
        )
        assert SUBCOMMAND_REGISTRY[("strategy", "doc", "replace")][0] == (
            "strategy.doc.replace"
        )
        assert SUBCOMMAND_REGISTRY[("strategy", "render")][0] == (
            "strategy.render.run"
        )
        assert SUBCOMMAND_REGISTRY[("strategy", "ingest")][0] == (
            "strategy.ingest.run"
        )
        assert SUBCOMMAND_REGISTRY[("strategy", "seed-defaults")][0] == (
            "strategy.seed_defaults.run"
        )


class TestDocList:
    def test_dispatches_empty_payload(self) -> None:
        rc = _run("strategy", "doc", "list")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "strategy.doc.list"
        assert req.target.kind == "global"
        assert req.payload == {}

    def test_explicit_project_rides_on_target(self) -> None:
        rc = _run("strategy", "doc", "list", "--project", "externalwebapp")
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].target.project_id == "externalwebapp"

    def test_env_project_used_when_no_flag(self) -> None:
        rc = _run(
            "strategy", "doc", "list", extra_env={"YOKE_PROJECT": "2"},
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].target.project_id == "2"


class TestDocGet:
    def test_dispatches_with_slug(self) -> None:
        rc = _run("strategy", "doc", "get", "MISSION")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "strategy.doc.get"
        assert req.target.kind == "global"
        assert req.payload == {"slug": "MISSION"}

    def test_missing_slug_returns_two(self) -> None:
        rc = _run("strategy", "doc", "get")
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


def _seed_view(root: Path, slug: str, text: str = "") -> str:
    """Drop a rendered-looking file under root/.yoke/strategy/."""
    docs_dir = root / ".yoke" / "strategy"
    docs_dir.mkdir(parents=True, exist_ok=True)
    body = text or f"<!-- header {slug} -->\n# {slug}\n"
    (docs_dir / f"{slug}.md").write_text(body, encoding="utf-8")
    return body


class TestIngest:
    def test_dispatches_from_direct_terminal_without_session(
        self, tmp_path: Path,
    ) -> None:
        _seed_view(tmp_path, "PAD")
        rc = _run(
            "strategy", "ingest", "PAD", "--target-root", str(tmp_path),
            session_id=None,
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "strategy.ingest.run"
        assert req.actor.session_id == ""

    def test_ships_client_read_files_with_dry_run(
        self, tmp_path: Path,
    ) -> None:
        text_a = _seed_view(tmp_path, "MISSION")
        text_b = _seed_view(tmp_path, "PAD")
        rc = _run(
            "strategy", "ingest", "MISSION", "PAD",
            "--dry-run", "--target-root", str(tmp_path),
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "strategy.ingest.run"
        assert req.target.kind == "global"
        assert req.payload["dry_run"] is True
        assert req.payload["target_root"] == str(tmp_path.resolve())
        files = req.payload["files"]
        assert [f["slug"] for f in files] == ["MISSION", "PAD"]
        assert files[0]["text"] == text_a
        assert files[1]["text"] == text_b
        assert files[0]["path"].endswith("MISSION.md")

    def test_no_slugs_resolves_corpus_via_doc_list(
        self, tmp_path: Path,
    ) -> None:
        _seed_view(tmp_path, "PAD")

        def _stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            result = {"echo": True}
            if request.function == "strategy.doc.list":
                result = {"docs": [{"slug": "PAD", "updated_at": "x"}]}
            return FunctionCallResponse(
                success=True, function=request.function,
                version=request.version, request_id=request.request_id,
                result=result,
            )

        env = {"YOKE_SESSION_ID": "test-session"}
        with patch.dict("os.environ", env):
            with patch(
                "yoke_core.domain.yoke_function_dispatch.dispatch",
                side_effect=_stub,
            ):
                with patch(
                    "yoke_cli.commands._helpers."
                    "ensure_handlers_loaded"
                ):
                    with redirect_stdout(io.StringIO()), \
                            redirect_stderr(io.StringIO()):
                        rc = cli_main(
                            ["strategy", "ingest",
                             "--target-root", str(tmp_path)]
                        )
        assert rc == 0
        assert [r.function for r in _CAPTURED_REQUESTS] == [
            "strategy.doc.list", "strategy.ingest.run",
        ]
        files = _CAPTURED_REQUESTS[-1].payload["files"]
        assert [f["slug"] for f in files] == ["PAD"]

    def test_missing_file_fails_before_dispatch(
        self, tmp_path: Path,
    ) -> None:
        rc = _run(
            "strategy", "ingest", "PAD", "--target-root", str(tmp_path),
        )
        assert rc == 1
        assert _CAPTURED_REQUESTS == []

    def test_commit_flag_is_not_supported(self, tmp_path: Path) -> None:
        rc = _run(
            "strategy", "ingest", "PAD", "--commit", "strategy: edit",
            "--target-root", str(tmp_path),
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_resolution_failure_returns_two(self) -> None:
        with patch(
            "yoke_cli.commands.adapters.strategy_render."
            "resolve_target_root_for_cli",
            side_effect=RuntimeError("no anchor"),
        ):
            rc = _run("strategy", "ingest")
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_help_carries_worked_example(self, capsys) -> None:
        from yoke_cli.commands.adapters.strategy_render import (
            strategy_ingest,
        )

        with pytest.raises(SystemExit):
            strategy_ingest(["--help"])
        out = capsys.readouterr().out
        assert "yoke strategy ingest MASTER-PLAN --dry-run" in out
        assert "compare-and-swap" in out
        assert "--commit" not in out

    def test_json_omits_returned_file_texts(
        self, tmp_path: Path,
    ) -> None:
        doc_text = "<!-- h -->\n# MISSION\n"

        def _stub_call_dispatcher(**kwargs) -> FunctionCallResponse:
            request = FunctionCallRequest(
                function=kwargs["function_id"],
                actor=kwargs["actor"],
                target=kwargs["target"],
                payload=kwargs.get("payload") or {},
            )
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True, function=request.function,
                version=request.version, request_id=request.request_id,
                result={
                    "project_id": 1,
                    "project_slug": "yoke",
                    "target_root": str(tmp_path),
                    "dry_run": False,
                    "written": 1,
                    "unchanged": 0,
                    "conflicts": 0,
                    "docs": [{
                        "slug": "MISSION",
                        "status": "written",
                        "updated_at": "x",
                        "old_lines": 1,
                        "new_lines": 2,
                        "line_delta": 1,
                        "file_text": doc_text,
                        "archived": False,
                    }],
                },
            )

        stdout = io.StringIO()
        env = {"YOKE_SESSION_ID": "test-session"}
        with patch.dict("os.environ", env):
            with patch(
                "yoke_cli.commands.adapters.strategy_render.call_dispatcher",
                side_effect=_stub_call_dispatcher,
            ):
                with patch(
                    "yoke_cli.commands._helpers."
                    "ensure_handlers_loaded"
                ):
                    with patch(
                        "yoke_cli.commands.adapters.strategy_render."
                        "read_ingest_files",
                        return_value=[{
                            "slug": "MISSION", "path": "MISSION.md",
                            "text": "<!-- old -->\n# MISSION\n",
                        }],
                    ):
                        with redirect_stdout(stdout), \
                                redirect_stderr(io.StringIO()):
                            rc = cli_main([
                                "strategy", "ingest", "MISSION",
                                "--target-root", str(tmp_path),
                                "--json",
                            ])
        assert rc == 0
        rendered = tmp_path / ".yoke" / "strategy" / "MISSION.md"
        assert rendered.read_text(encoding="utf-8") == doc_text
        payload = json.loads(stdout.getvalue())
        doc = payload["result"]["docs"][0]
        assert "file_text" not in doc
        assert doc["file_bytes"] == len(doc_text.encode("utf-8"))
        assert doc["file_lines"] == 2
        assert doc["path"] == ".yoke/strategy/MISSION.md"
        assert doc["render_status"] == "written"
        assert payload["result"]["rendered"] == {"unchanged": 0, "written": 1}


class TestRender:
    def test_dispatches_empty_payload(self, tmp_path: Path) -> None:
        rc = _run("strategy", "render", "--target-root", str(tmp_path))
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "strategy.render.run"
        assert req.target.kind == "global"
        assert req.payload == {}

    def test_writes_returned_file_texts_locally(
        self, tmp_path: Path, capsys,
    ) -> None:
        def _stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True, function=request.function,
                version=request.version, request_id=request.request_id,
                result={
                    "project_id": 1, "project_slug": "yoke",
                    "docs": [{
                        "slug": "MISSION", "updated_at": "x",
                        "file_text": "<!-- h -->\n# MISSION\n",
                    }],
                },
            )

        env = {"YOKE_SESSION_ID": "test-session"}
        with patch.dict("os.environ", env):
            with patch(
                "yoke_core.domain.yoke_function_dispatch.dispatch",
                side_effect=_stub,
            ):
                with patch(
                    "yoke_cli.commands._helpers."
                    "ensure_handlers_loaded"
                ):
                    rc = cli_main(
                        ["strategy", "render",
                         "--target-root", str(tmp_path)]
                    )
        assert rc == 0
        rendered = tmp_path / ".yoke" / "strategy" / "MISSION.md"
        assert rendered.read_text(encoding="utf-8") == "<!-- h -->\n# MISSION\n"
        assert "MISSION\twritten" in capsys.readouterr().out

    def test_json_omits_returned_file_texts(
        self, tmp_path: Path,
    ) -> None:
        doc_text = "<!-- h -->\n# MISSION\n"

        def _stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True, function=request.function,
                version=request.version, request_id=request.request_id,
                result={
                    "project_id": 1, "project_slug": "yoke",
                    "docs": [{
                        "slug": "MISSION", "updated_at": "x",
                        "file_text": doc_text,
                    }],
                },
            )

        stdout = io.StringIO()
        env = {"YOKE_SESSION_ID": "test-session"}
        with patch.dict("os.environ", env):
            with patch(
                "yoke_core.domain.yoke_function_dispatch.dispatch",
                side_effect=_stub,
            ):
                with patch(
                    "yoke_cli.commands._helpers."
                    "ensure_handlers_loaded"
                ):
                    with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                        rc = cli_main([
                            "strategy", "render",
                            "--target-root", str(tmp_path),
                            "--json",
                        ])
        assert rc == 0
        rendered = tmp_path / ".yoke" / "strategy" / "MISSION.md"
        assert rendered.read_text(encoding="utf-8") == doc_text
        payload = json.loads(stdout.getvalue())
        doc = payload["result"]["docs"][0]
        assert "file_text" not in doc
        assert doc["file_bytes"] == len(doc_text.encode("utf-8"))
        assert doc["file_lines"] == 2
        assert doc["path"] == ".yoke/strategy/MISSION.md"
        assert doc["render_status"] == "written"
        assert payload["result"]["target_root"] == str(tmp_path.resolve())
        assert payload["result"]["rendered"] == {"unchanged": 0, "written": 1}

    def test_env_var_anchor_used_when_no_flag(self, tmp_path: Path) -> None:
        rc = _run(
            "strategy", "render",
            extra_env={"YOKE_RENDER_TARGET_ROOT": str(tmp_path)},
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload == {}

    def test_resolution_failure_returns_two(self) -> None:
        with patch(
            "yoke_cli.commands.adapters.strategy_render."
            "resolve_target_root_for_cli",
            side_effect=RuntimeError("no anchor"),
        ):
            rc = _run("strategy", "render")
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


class TestSeedDefaults:
    def test_dispatches_empty_payload_with_project(self) -> None:
        rc = _run("strategy", "seed-defaults", "--project", "externalwebapp")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "strategy.seed_defaults.run"
        assert req.target.kind == "global"
        assert req.target.project_id == "externalwebapp"
        assert req.payload == {}
