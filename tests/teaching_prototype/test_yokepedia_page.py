"""Yokepedia is one safe, self-contained page that replaces only on success."""

from pathlib import Path

import pytest

from tests.teaching_prototype.yokepedia_page import inline_scripts, page_data

TOOLS = Path(__file__).resolve().parents[2] / "docs/teaching/tools"
HOSTILE = 'End </script><script>alert("x")</script> & "quotes" \'single\' café — 東京 <!-- c -->'


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    import build
    import model
    import render_explorer

    return build, model, render_explorer


def test_embedded_data_round_trips_hostile_text(tools):
    _, model, render = tools
    data = dict(
        nodes=[dict(id="n", title=HOSTILE, parent=None, children=[])],
        documents={"../../../x.md": HOSTILE},
        records={"../model/x.json": {"note": HOSTILE}},
        build=dict(commit="c" * 40),
    )
    loaded = model.Model()
    html = render.page_html(data, loaded)
    assert not loaded.problems
    block = html.split('<script id="yokepedia-data" type="application/json">', 1)[1]
    raw = block.split("</script>", 1)[0]
    assert "<" not in raw
    assert raw.count("\\u003c") == HOSTILE.count("<") * 3
    assert page_data(html) == data


def test_page_inlines_assets_and_never_fetches(tools):
    _, model, render = tools
    html = render.page_html(
        dict(nodes=[], documents={}, records={}, build={}), model.Model()
    )
    scripts = inline_scripts(html)
    assert [script for script in scripts] == [
        (TOOLS / name).read_text(encoding="utf-8") for name in render.SCRIPTS
    ]
    assert "fetch(" not in "".join(scripts)
    assert "<script src=" not in html and "<link " not in html


def test_unsafe_inline_asset_is_refused(tools, monkeypatch, tmp_path):
    _, model, render = tools
    for name in ("explorer.css", "explorer_outline.css", *render.SCRIPTS):
        (tmp_path / name).write_text((TOOLS / name).read_text())
    (tmp_path / "explorer.js").write_text("const end = '</" + "script>';")
    monkeypatch.setattr(render, "HERE", tmp_path)
    loaded = model.Model()
    render.page_html(dict(nodes=[], documents={}, records={}, build={}), loaded)
    assert [(p.code, p.where) for p in loaded.problems] == [
        ("GUIDE_ASSET_UNSAFE", "tools/explorer.js")
    ]


def _views(build, monkeypatch, tmp_path):
    views = tmp_path / "views"
    (views / "explore").mkdir(parents=True)
    (views / "explore/manifest.json").write_text("[]")
    (views / "yokepedia.html").write_text("last good page")
    monkeypatch.setattr(build, "VIEWS_ROOT", views)
    monkeypatch.setattr(build, "LIVE_ROOT", tmp_path / "live")
    return views


def test_failed_build_keeps_the_last_good_page(tools, monkeypatch, tmp_path, capsys):
    build, _, _ = tools
    views = _views(build, monkeypatch, tmp_path)
    home = "/" + "Users/someone/"

    def private_page(output, _pages):
        output["yokepedia.html"] = "new page"
        return {"yokepedia.html#doc:x": home}

    monkeypatch.setattr(build, "build_explorer", private_page)
    assert build.main([]) == 1
    assert (
        "PRIVATE_MATERIAL: docs/teaching/views/yokepedia.html#doc:x:1"
        in capsys.readouterr().out
    )
    assert (views / "yokepedia.html").read_text() == "last good page"
    assert (views / "explore/manifest.json").exists()


def test_write_failure_keeps_page_and_obsolete_files(tools, monkeypatch, tmp_path):
    build, model, _ = tools
    views = _views(build, monkeypatch, tmp_path)

    def refuse(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(build.os, "replace", refuse)
    loaded = model.Model()
    build.publish(loaded, {"yokepedia.html": "new page"})
    assert [p.code for p in loaded.problems] == ["VIEWS_WRITE_FAILED"]
    assert "disk full" in loaded.problems[0].message
    assert sorted(p.name for p in views.iterdir()) == ["explore", "yokepedia.html"]
    assert (views / "yokepedia.html").read_text() == "last good page"


def test_successful_swap_removes_obsolete_generated_files(tools, monkeypatch, tmp_path):
    build, model, _ = tools
    views = _views(build, monkeypatch, tmp_path)
    loaded = model.Model()
    build.publish(loaded, {"yokepedia.html": "new page"})
    assert not loaded.problems
    assert [p.name for p in views.iterdir()] == ["yokepedia.html"]
    assert (views / "yokepedia.html").read_text() == "new page"
