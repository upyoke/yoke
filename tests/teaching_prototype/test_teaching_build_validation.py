"""Invalid teaching models report all references before rendering or writing."""

from pathlib import Path
import shlex

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "docs/teaching/tools"


@pytest.mark.parametrize("args", [[], ["--check"]])
def test_dangling_references_fail_before_rendering(monkeypatch, tmp_path, capsys, args):
    monkeypatch.syspath_prepend(str(TOOLS))
    import build

    loaded = build.load()
    loaded.concepts["documentation"]["surface_refs"] = [
        "missing-surface",
        "another-missing-surface",
    ]
    loaded.gaps["shared-access"]["related_scenarios"] = ["missing-scenario"]
    monkeypatch.setattr(build, "load", lambda: loaded)
    views = tmp_path / "views"
    views.mkdir()
    existing = views / "index.html"
    existing.write_text("existing views")
    monkeypatch.setattr(build, "VIEWS_ROOT", views)
    monkeypatch.setattr(build, "LIVE_ROOT", tmp_path / "live")

    def refuse_render(*_args, **_kwargs):
        pytest.fail("invalid model reached rendering")

    monkeypatch.setattr(build, "GuideData", refuse_render)
    assert build.main(args) == 1
    output = capsys.readouterr().out
    assert output.count("DANGLING_REFERENCE:") == 3
    for target in ("missing-surface", "another-missing-surface", "missing-scenario"):
        assert target in output
    assert "docs/teaching/model/concepts/documentation.json:documentation" in output
    assert "docs/teaching/model/gaps/shared-access.json:shared-access" in output
    assert "surface_refs" in output
    assert "related_scenarios" in output
    assert "Fix the model" in output
    assert "--check" in output
    assert "Traceback" not in output
    assert existing.read_text() == "existing views"
    assert list(views.iterdir()) == [existing]
    assert not build.LIVE_ROOT.exists()


def test_canonical_recovery_preserves_data_and_makes_check_pass(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.syspath_prepend(str(TOOLS))
    import build
    import convert_model
    import model

    record = tmp_path / "concepts" / "topic.json"
    record.parent.mkdir()
    record.write_text('{"id":"topic","title":"A topic","status":"observed"}')
    value = build.json.loads(record.read_text())
    canonical = {record: model.dump(value)}
    monkeypatch.setattr(build, "TEACHING_ROOT", tmp_path)
    monkeypatch.setattr(build, "MODEL_ROOT", tmp_path)
    loaded = model.Model()
    build.check_canonical_model(loaded, canonical)
    assert build.report(loaded.problems, check=True) == 1
    assert (
        "yoke dev run -- python3 docs/teaching/tools/convert_model.py"
        in capsys.readouterr().out
    )
    assert convert_model.convert(tmp_path) == 1
    assert build.json.loads(record.read_text()) == value
    loaded = model.Model()
    build.check_canonical_model(loaded, canonical)
    assert loaded.problems == []
    assert convert_model.convert(tmp_path) == 0


def test_untracked_source_recovery_stages_the_named_file(monkeypatch, tmp_path):
    import subprocess

    monkeypatch.syspath_prepend(str(TOOLS))
    import inventory
    import model

    teaching = tmp_path / "docs" / "teaching"
    teaching.mkdir(parents=True)
    monkeypatch.setattr(model, "TEACHING_ROOT", teaching)
    monkeypatch.setattr(inventory, "REPO_ROOT", tmp_path)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "new source.md"
    source.write_text("# New source\n")

    def validate():
        loaded = model.Model()
        loaded.concepts["topic"] = {
            "id": "topic",
            "status": "observed",
            "sources": ["new source.md:1"],
        }
        model.validate(
            loaded,
            {"commands": {}, "functions": set(), "skills": set()},
            set(inventory.tracked_files()),
        )
        return loaded.problems

    problems = validate()
    assert len(problems) == 1
    assert problems[0].code == "DANGLING_SOURCE"
    assert (
        "untracked: stage it with `git add -- 'new source.md'`" in problems[0].message
    )
    command = problems[0].message.split("`", 2)[1]
    subprocess.run(shlex.split(command), cwd=tmp_path, check=True)
    assert validate() == []
    source.unlink()
    monkeypatch.setattr(inventory, "tracked_files", lambda: [])
    assert "is missing; create and git-add" in validate()[0].message


def test_generated_views_skip_line_limits_but_stay_privacy_scanned(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(TOOLS))
    import build
    import model

    monkeypatch.setattr(build, "TEACHING_ROOT", tmp_path)
    (tmp_path / "notes.md").write_text("line\n" * 351)
    home = "/" + "Users/someone/"
    loaded = model.Model()
    build.limits_and_privacy(loaded, {"yokepedia.html": "line\n" * 351,
                                      "yokepedia.html#doc:x": f'{{"body":"{home}"}}'})
    found = {(problem.code, problem.where): problem for problem in loaded.problems}
    assert set(found) == {("LINE_LIMIT", "docs/teaching/notes.md"),
                          ("PRIVATE_MATERIAL", "docs/teaching/views/yokepedia.html#doc:x:1")}
    assert "split it into a new file" in found["LINE_LIMIT", "docs/teaching/notes.md"].message


def _owned_model(monkeypatch, tmp_path, part_page):
    monkeypatch.syspath_prepend(str(TOOLS))
    import model

    root = tmp_path / "docs" / "teaching"
    monkeypatch.setattr(model, "TEACHING_ROOT", root)
    monkeypatch.setattr(model, "MODEL_ROOT", root / "model")
    surfaces = root / "model" / "surfaces"
    (root / "model" / "concepts").mkdir(parents=True)
    (surfaces / "help").mkdir(parents=True)
    (root / "model" / "docs-graph.json").write_text("{}")
    for stem in ("help", "other"):
        (surfaces / f"{stem}.json").write_text(
            f'{{"id": "{stem}", "title": "{stem.title()}", "status": "observed"}}'
        )
    for stem, page in (("core", None), ("case", part_page)):
        record = {"id": stem, "title": stem.title(), "status": "observed"}
        if page:
            record["page"] = page
        (surfaces / "help" / f"{stem}.json").write_text(model.json.dumps(record))
    return model.load()


def test_record_identity_is_independent_of_former_page_layout(monkeypatch, tmp_path):
    loaded = _owned_model(monkeypatch, tmp_path, "help-cases")
    assert loaded.problems == []
    assert set(loaded.teaching) == {"help/core", "help/case"}


def test_surface_part_page_cannot_take_another_surface_page(monkeypatch, tmp_path):
    loaded = _owned_model(monkeypatch, tmp_path, "other")
    assert [problem.code for problem in loaded.problems] == ["PAGE_COLLISION"]
    assert "'other'" in loaded.problems[0].message
    assert loaded.problems[0].where.endswith("surfaces/help/case.json")
