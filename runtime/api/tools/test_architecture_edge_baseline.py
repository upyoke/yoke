"""The baseline generator writes, and checks, a full scan of a commit."""

from __future__ import annotations

import pytest

from runtime.api.domain.architecture_edge_test_support import (
    SRC,
    commit,
    dispatch_returning,
    init_repo,
    model_response,
)
from yoke_core.domain.architecture_tree_scan import BASELINE_PATH, parse_baseline
from yoke_core.tools import architecture_edge_baseline as tool


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    init_repo(root, {
        f"{SRC}/low/a.py": "from yoke_core.high import b\n",
        f"{SRC}/high/b.py": "from yoke_core.low import a\n",
    })
    monkeypatch.setattr(tool, "call_dispatcher", dispatch_returning(model_response()))
    return root


def test_write_then_check_round_trips(repo, capsys):
    assert tool.main(["--project", "demo", "--repo", str(repo)]) == 0
    written = (repo / BASELINE_PATH).read_text(encoding="utf-8")
    assert parse_baseline(written) == {
        (f"{SRC}/low/a.py", "yoke_core.high", "low", "high")
    }
    assert "1 edges" in capsys.readouterr().out
    commit(repo, {})
    assert tool.main(["--project", "demo", "--repo", str(repo), "--check"]) == 0


def test_check_names_drift(repo, capsys):
    (repo / BASELINE_PATH).parent.mkdir(parents=True)
    (repo / BASELINE_PATH).write_text("[]\n", encoding="utf-8")
    assert tool.main(["--project", "demo", "--repo", str(repo), "--check"]) == 1
    assert "differs from a scan of HEAD (1 edges)" in capsys.readouterr().err


def test_a_project_without_a_model_refuses(repo, monkeypatch):
    monkeypatch.setattr(tool, "call_dispatcher", dispatch_returning(model_response(None)))
    with pytest.raises(SystemExit, match="architecture_model_missing: demo"):
        tool.scan_commit(str(repo), "HEAD", "demo")
