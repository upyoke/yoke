"""Default ingest includes all active docs and locally rendered archives."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from yoke_cli.commands.adapters import strategy_render as adapter
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.project_contract.strategy_docs_header import render_file_text
from yoke_contracts.project_contract.strategy_docs_io import write_rendered_files
from yoke_contracts.project_contract.strategy_docs_paths import strategy_view_path


@pytest.fixture
def dispatch(monkeypatch):
    docs = []
    calls = []

    def call(**kwargs):
        calls.append(kwargs)
        function = kwargs["function_id"]
        result = {"docs": docs} if function == "strategy.doc.list" else {}
        if function == "strategy.render.run":
            selected = kwargs["payload"]["slugs"]
            result = {
                "docs": [
                    dict(
                        doc,
                        file_text=render_file_text(
                            doc["slug"], "2026-06-10T00:00:00Z", "# archived\n"
                        ),
                    )
                    for doc in docs
                    if doc["slug"] in selected
                ]
            }
        return FunctionCallResponse(
            success=True, function=function, version="v1", result=result
        )

    monkeypatch.setattr(adapter, "call_dispatcher", call)
    monkeypatch.setattr(adapter._helpers, "ensure_handlers_loaded", lambda: None)
    return docs, calls


def seed(root, slug, *, archived=False):
    text = render_file_text(slug, "2026-06-10T00:00:00Z", "# original\n")
    write_rendered_files(
        root, [{"slug": slug, "archived": archived, "file_text": text}]
    )
    return strategy_view_path(root, slug, archived)


def test_default_ingests_more_than_one_cli_page_and_skips_missing_archive(
    tmp_path: Path,
    dispatch,
):
    docs, calls = dispatch
    slugs = [f"DOC-{index}" for index in range(30)]
    docs.extend({"slug": slug, "archived": False} for slug in slugs)
    docs.insert(0, {"slug": "OLD", "archived": True})
    for slug in slugs:
        seed(tmp_path, slug)
    assert adapter.strategy_ingest(["--target-root", str(tmp_path), "--dry-run"]) == 0
    assert calls[0]["payload"] == {}
    assert [file["slug"] for file in calls[-1]["payload"]["files"]] == slugs


@pytest.mark.parametrize("archive_directory", [False, True])
def test_default_preserves_edited_archive_at_either_location(
    tmp_path: Path,
    dispatch,
    archive_directory,
):
    docs, calls = dispatch
    docs.extend([{"slug": "CURRENT"}, {"slug": "OLD", "archived": True}])
    seed(tmp_path, "CURRENT")
    path = seed(tmp_path, "OLD", archived=archive_directory)
    edited = path.read_text().replace("# original", "# local archive edit")
    path.write_text(edited)
    assert adapter.strategy_ingest(["--target-root", str(tmp_path)]) == 0
    files = calls[-1]["payload"]["files"]
    assert [file["slug"] for file in files] == ["CURRENT", "OLD"]
    assert files[-1]["text"] == edited
    assert files[-1]["path"] == str(path)


def test_explicit_missing_archive_recovery_renders_then_ingests(
    tmp_path: Path,
    dispatch,
    capsys,
):
    docs, calls = dispatch
    docs.append({"slug": "OLD", "archived": True})
    args = ["OLD", "--target-root", str(tmp_path)]
    assert adapter.strategy_ingest(args) == 1
    message = capsys.readouterr().err
    recovery = message.split("render it first: ", 1)[1].strip()
    assert shlex.split(recovery) == ["yoke", "strategy", "render", *args]
    assert [call["function_id"] for call in calls] == ["strategy.doc.list"]
    assert adapter.strategy_render(shlex.split(recovery)[3:]) == 0
    assert strategy_view_path(tmp_path, "OLD", archived=True).is_file()
    assert adapter.strategy_ingest(args) == 0
    assert calls[-1]["payload"]["files"][0]["slug"] == "OLD"


def test_missing_active_doc_still_refuses(tmp_path: Path, dispatch, capsys):
    docs, calls = dispatch
    docs.extend([{"slug": "OLD", "archived": True}, {"slug": "CURRENT"}])
    assert adapter.strategy_ingest(["--target-root", str(tmp_path)]) == 1
    assert "ingest_file_missing" in capsys.readouterr().err
    assert [call["function_id"] for call in calls] == ["strategy.doc.list"]


def test_only_unrendered_archives_is_noop(tmp_path: Path, dispatch, capsys):
    docs, calls = dispatch
    docs.append({"slug": "OLD", "archived": True})
    assert adapter.strategy_ingest(["--target-root", str(tmp_path), "--json"]) == 0
    response = json.loads(capsys.readouterr().out)
    assert response["success"] is True
    assert response["function"] == "strategy.ingest.run"
    assert response["result"]["docs"] == []
    assert response["result"]["written"] == 0
    assert [call["function_id"] for call in calls] == ["strategy.doc.list"]
