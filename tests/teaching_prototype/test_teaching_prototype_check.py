"""The teaching prototype stays consistent with its model and live registries."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "docs" / "teaching" / "tools"


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    import model
    import inventory
    import privacy
    import limits

    return model, inventory, privacy, limits


@pytest.mark.parametrize(
    "script, args, expected",
    [
        ("build.py", ["--check"], "check passed"),
        ("convert_model.py", [], "wrote 0 record files"),
    ],
)
def test_standalone_model_tools(script, args, expected):
    result = subprocess.run(
        [sys.executable, "-E", str(TOOLS / script), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert expected in result.stdout


def test_validate_names_dangling_references_and_retired_plan_refs(tools):
    model, *_ = tools
    loaded = model.Model()
    loaded.concepts["a"] = {
        "id": "a",
        "title": "A",
        "status": "draft-copy",
        "gaps": ["missing"],
        "plan_refs": ["PLAN.1"],
        "commands": ["yoke nope"],
        "sources": ["no/such/file.md"],
        "file": "c.json",
    }
    loaded.gaps["g"] = {"id": "g", "status": "open", "file": "gaps/g.json"}
    live = {"commands": {"yoke real"}, "functions": set(), "skills": set()}
    model.validate(loaded, live, {"README.md"})
    codes = sorted(problem.code for problem in loaded.problems)
    assert codes == [
        "DANGLING_REFERENCE",
        "DANGLING_REFERENCE",
        "DANGLING_SOURCE",
        "RETIRED_PLAN_MIRROR",
        "UNKNOWN_STATUS",
    ]


def test_coverage_counts_only_direct_mappings(tools):
    model, *_ = tools
    loaded = model.Model()
    loaded.concepts["parent"] = {}
    loaded.concepts["parent/child"] = {}
    loaded.teaching["entry/lesson"] = {"topics": ["parent"]}
    assert model.coverage(loaded) == {"parent": ["entry/lesson"], "parent/child": []}


@pytest.mark.parametrize(
    "line",
    [
        "see /" + "Users/someone/notes.md",
        "Mobile " + "Documents/Docs",
        "captured at /" + "tmp/capture.txt",
        "session 123e4567-e89b-12d3-a456-426614174000",
    ],
)
def test_privacy_patterns_flag_private_material(tools, line):
    _, _, privacy, _ = tools
    assert any(pattern.search(line) for _, pattern in privacy.PATTERNS)


def test_privacy_patterns_allow_repository_paths(tools):
    _, _, privacy, _ = tools
    line = "docs/teaching/model/gaps/example.json and packages/yoke-core/src"
    assert not any(pattern.search(line) for _, pattern in privacy.PATTERNS)


def test_wrapped_line_count_uses_eighty_columns(tools):
    *_, render = tools
    assert render.wrapped_lines("x" * 80 + "\n" + "y" * 81 + "\n\n") == 4


def test_check_does_not_depend_on_local_views(tools, monkeypatch, tmp_path):
    import build

    local_views = tmp_path / "views"
    monkeypatch.setattr(build, "VIEWS_ROOT", local_views)
    assert build.main(["--check"]) == 0
    assert not local_views.exists()
    local_views.mkdir()
    stale = local_views / "unexpected.html"
    stale.write_text("obsolete output")
    assert build.main(["--check"]) == 0
    assert stale.read_text() == "obsolete output"


def test_build_writes_one_self_contained_page(tools, monkeypatch, tmp_path):
    import build

    monkeypatch.setattr(build, "VIEWS_ROOT", tmp_path / "views")
    monkeypatch.setattr(build, "LIVE_ROOT", tmp_path / "live")
    obsolete = ("views/explore/index.html", "views/explore/nodes-0.json",
                "views/explore/manifest.json", "views/style.css", "live/commands.html")
    for path in obsolete:
        stale = tmp_path / path
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("obsolete")
    record = tmp_path / "record.json"
    original = '{"id":"example"}\n'
    record.write_text(original)
    monkeypatch.setattr(build, "model_files", lambda: [record])
    assert build.main([]) == 0
    assert record.read_text() == original
    assert [path.name for path in (tmp_path / "views").iterdir()] == ["yokepedia.html"]
    page = (tmp_path / "views/yokepedia.html").read_text()
    assert page.startswith("<!doctype html>")
    assert (TOOLS / "explorer.css").read_text() in page
    assert '<link rel="stylesheet"' not in page and "<script src=" not in page
    assert not (tmp_path / "live").exists()


def test_generated_views_are_untracked_and_ignored():
    tracked = subprocess.check_output(
        ["git", "ls-files", "docs/teaching/views"], cwd=REPO, text=True
    )
    assert not tracked
    result = subprocess.run(
        ["git", "check-ignore", "docs/teaching/views/yokepedia.html"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_check_refuses_invalid_model_with_recovery(tools, monkeypatch, capsys):
    import build

    loaded = build.load()
    loaded.concepts["documentation"]["status"] = "invalid"
    monkeypatch.setattr(build, "load", lambda: loaded)
    assert build.main(["--check"]) == 1
    output = capsys.readouterr().out
    assert "UNKNOWN_STATUS" in output
    assert "Fix the model" in output
    assert "--check" in output


def test_conversion_preserves_records_and_is_repeatable(tools, monkeypatch, tmp_path):
    import convert_model

    model, *_ = tools
    teaching = tmp_path / "docs/teaching"
    root = teaching / "model"
    arrays = {
        "concepts/topic.json": {
            "parent": None,
            "nodes": [
                {
                    "id": "topic",
                    "title": "Topic",
                    "children": [{"id": "child", "title": "Child"}],
                }
            ],
        },
        "concepts/topic-more.json": {
            "parent": "topic",
            "nodes": [{"id": "additional", "title": "More"}],
        },
        "surfaces/entry.json": {
            "surface": {"id": "entry"},
            "teaching": [{"id": "second"}, {"id": "first"}],
        },
        "scenarios/work.json": {
            "scenario": {"id": "work"},
            "lessons": [{"id": "lesson"}],
        },
        "evidence/research.json": {"title": "Research", "records": [{"id": "a"}]},
        "gaps.json": {"records": [{"id": "missing"}]},
        "boundaries.json": {"records": [{"id": "rule"}]},
        "docs-graph.json": {},
    }
    for name, value in arrays.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(model.dump(value))
    assert convert_model.convert(root) == 12
    snapshot = {p.relative_to(root): p.read_bytes() for p in root.rglob("*.json")}
    assert convert_model.convert(root) == 0
    assert snapshot == {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*.json")
    }
    assert not (root / "gaps.json").exists()
    monkeypatch.setattr(model, "TEACHING_ROOT", teaching)
    monkeypatch.setattr(model, "MODEL_ROOT", root)
    loaded = model.load()
    assert not loaded.problems
    assert loaded.concepts["topic"]["children"] == ["topic/child", "topic/additional"]
    assert loaded.surfaces["entry"]["parts"] == ["entry/second", "entry/first"]
    assert loaded.lessons["work/lesson"]["owner"] == "work"
    assert loaded.evidence["research/a"]["id"] == "a"
    assert set(loaded.gaps) == {"missing"}
    assert set(loaded.boundaries) == {"rule"}
    # Upstream arrays can be reapplied without touching unrelated record files.
    source = root / "gaps.json"
    source.write_text(
        model.dump({"records": [{"id": "missing", "title": "Updated"}, {"id": "new"}]})
    )
    assert convert_model.convert(root) == 2
    assert model.load().gaps["missing"]["title"] == "Updated"
    assert model.load().gaps["new"]["id"] == "new"
    assert (root / "concepts/topic/child.json").read_bytes() == snapshot[
        Path("concepts/topic/child.json")
    ]


def test_loader_reports_filename_mismatch(tools, monkeypatch, tmp_path):
    model, *_ = tools
    root = tmp_path / "docs/teaching/model"
    (root / "gaps").mkdir(parents=True)
    (root / "gaps/wrong.json").write_text(model.dump({"id": "different"}))
    (root / "docs-graph.json").write_text("{}\n")
    monkeypatch.setattr(model, "MODEL_ROOT", root)
    monkeypatch.setattr(model, "TEACHING_ROOT", root.parent)
    loaded = model.load()
    assert [p.code for p in loaded.problems] == ["MODEL_RECORD_ID"]
    assert "filename" in loaded.problems[0].message


def test_loader_refuses_a_strategy_plan_mirror(tools, monkeypatch, tmp_path):
    model, *_ = tools
    root = tmp_path / "docs/teaching/model"
    (root / "plan").mkdir(parents=True)
    (root / "docs-graph.json").write_text("{}\n")
    monkeypatch.setattr(model, "MODEL_ROOT", root)
    monkeypatch.setattr(model, "TEACHING_ROOT", root.parent)
    loaded = model.load()
    assert [p.code for p in loaded.problems] == ["RETIRED_PLAN_MIRROR"]
    assert "scenario, surface, boundary or gap" in loaded.problems[0].message


def test_independent_additions_merge_without_shared_file_edits(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True)

    git("init", "-b", "base")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    owner = tmp_path / "model/surfaces/entry.json"
    owner.parent.mkdir(parents=True)
    owner.write_text('{"id": "entry"}\n')
    git("add", ".")
    git("commit", "-m", "Collection owner")
    for branch, record_id in [("left", "alpha"), ("right", "beta")]:
        git("checkout", "-b", branch, "base")
        record = owner.with_suffix("") / f"{record_id}.json"
        record.parent.mkdir(exist_ok=True)
        record.write_text(json.dumps({"id": record_id}) + "\n")
        git("add", ".")
        git("commit", "-m", "Add record")
        assert git("diff", "--name-only", "base").strip() == (
            f"model/surfaces/entry/{record_id}.json"
        )
    git("merge", "--no-edit", "left")
    assert {p.stem for p in owner.with_suffix("").glob("*.json")} == {"alpha", "beta"}
    assert git("status", "--porcelain") == ""
