"""The public tree refuses ambiguous ownership, unsafe YAML and invalid routes."""

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from yoke_core.domain import documentation_navigation as nav

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def corpus(tmp_path):
    shutil.copytree(FIXTURES / "documentation_corpus", tmp_path, dirs_exist_ok=True)
    return tmp_path


def _document(root, value):
    (root / "nav.yaml").write_text(yaml.safe_dump(value), encoding="utf-8")


def _node(path, **extra):
    return dict(title="Page", summary="Read this page.", path=path, **extra)


def _codes(root, complete=False):
    return {r.code for r in nav.validate_navigation(root, complete=complete)}


def test_order_routes_breadcrumbs_and_frozen_nodes(corpus):
    tree = nav.load_navigation(corpus)
    assert [n.path for n in nav.iter_nodes(tree)] == [
        "index.md",
        "guide/index.md",
        "guide/setup.md",
    ]
    assert [n.title for n in nav.breadcrumbs(tree, "guide/setup.md")] == [
        "Corpus",
        "Guide",
        "Setup",
    ]
    assert nav.breadcrumbs(tree, "absent.md") == []
    assert nav.immediate_children(tree, "index.md") == list(tree.children)
    assert nav.immediate_children(tree, "guide/setup.md") == []
    with pytest.raises(FrozenInstanceError):
        tree.title = "Changed"
    cases = json.loads((FIXTURES / "documentation_conformance.json").read_text())
    for case in cases["routes"]:
        assert nav.route_for(case["path"]) == case["route"]
    assert nav.validate_navigation(corpus, complete=True) == []


@pytest.mark.parametrize(
    "document,code",
    [
        ({"sections": []}, "NAV_UNKNOWN_KEY"),
        ({}, "NAV_SCHEMA"),
        ({"root": []}, "NAV_SCHEMA"),
        ({"root": {"title": "Root", "path": "index.md"}}, "NAV_SCHEMA"),
        ({"root": _node("index.md", extra=True)}, "NAV_UNKNOWN_KEY"),
        ({"root": dict(title="", summary="Read", path="index.md")}, "NAV_EMPTY_VALUE"),
        ({"root": dict(title="Root", summary=3, path="index.md")}, "NAV_EMPTY_VALUE"),
        ({"root": _node("index.md", children={})}, "NAV_SCHEMA"),
        ({"root": _node("guide/setup.md")}, "NAV_PATH_INVALID"),
        (
            {"root": _node("index.md", children=[_node("missing.md")])},
            "NAV_PATH_MISSING",
        ),
        (
            {
                "root": _node(
                    "index.md",
                    children=[
                        _node("guide/setup.md", children=[_node("guide/index.md")])
                    ],
                )
            },
            "NAV_CATEGORY_NOT_INDEX",
        ),
        (
            {
                "root": _node(
                    "index.md",
                    children=[_node("guide/setup.md"), _node("guide/setup.md")],
                )
            },
            "NAV_DUPLICATE_PAGE",
        ),
        (
            {
                "root": _node(
                    "index.md",
                    children=[_node("guide/index.md", children=[_node("index.md")])],
                )
            },
            "NAV_CYCLE",
        ),
    ],
)
def test_schema_refusals(corpus, document, code):
    _document(corpus, document)
    assert code in _codes(corpus)
    with pytest.raises(nav.NavigationError) as refusal:
        nav.load_navigation(corpus)
    assert all(r.target and r.detail and r.repair for r in refusal.value.refusals)


@pytest.mark.parametrize(
    "path,code",
    [
        ("/outside.md", "NAV_PATH_ESCAPES"),
        ("../outside.md", "NAV_PATH_ESCAPES"),
        ("guide/../index.md", "NAV_PATH_ESCAPES"),
        ("guide//setup.md", "NAV_PATH_INVALID"),
        ("./index.md", "NAV_PATH_INVALID"),
        ("guide\\setup.md", "NAV_PATH_INVALID"),
        ("index.md#heading", "NAV_PATH_INVALID"),
        ("index.md?q=1", "NAV_PATH_INVALID"),
        ("page.txt", "NAV_PATH_INVALID"),
    ],
)
def test_invalid_paths(corpus, path, code):
    _document(corpus, {"root": _node("index.md", children=[_node(path)])})
    assert code in _codes(corpus)
    with pytest.raises(ValueError):
        nav.route_for(path)


@pytest.mark.parametrize(
    "text,code",
    [
        ("root: &root {title: Root, summary: Read, path: index.md}", "NAV_ALIAS"),
        (
            "root: {title: Root, summary: Read, path: index.md, children: [*root]}",
            "NAV_ALIAS",
        ),
        (
            "root: {title: Root, title: Other, summary: Read, path: index.md}",
            "NAV_SCHEMA",
        ),
        ("root: {<<: {title: Root}, summary: Read, path: index.md}", "NAV_SCHEMA"),
        ("root: [invalid", "NAV_SCHEMA"),
    ],
)
def test_yaml_refusals(corpus, text, code):
    (corpus / "nav.yaml").write_text(text)
    assert code in _codes(corpus)
    assert all(
        len(str(r).splitlines()) == 1
        for r in nav.validate_navigation(corpus, complete=False)
    )


def test_collision_complete_partial_and_cli(corpus, capsys):
    (corpus / "guide.md").write_text("# Guide\n")
    _document(
        corpus,
        {
            "root": _node(
                "index.md", children=[_node("guide.md"), _node("guide/index.md")]
            )
        },
    )
    assert "NAV_ROUTE_COLLISION" in _codes(corpus)
    assert "UNLISTED_PAGE" in _codes(corpus, complete=True)
    assert nav.main(["check", "--root", str(corpus)]) == 1
    assert "Repair:" in capsys.readouterr().out
    _document(corpus, {"root": _node("index.md")})
    assert nav.main(["check", "--root", str(corpus), "--partial"]) == 0
    assert "1 pages" in capsys.readouterr().out


def test_tracked_source_pages_and_symlink_escape(tmp_path):
    repo = tmp_path / "source"
    root = repo / "docs/public"
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (root / "index.md").write_text("# Root\n")
    _document(root, {"root": _node("index.md")})
    assert "NAV_PATH_MISSING" in _codes(root)
    subprocess.run(["git", "-C", str(repo), "add", "docs/public"], check=True)
    assert nav.validate_navigation(root, complete=True) == []
    (root / "untracked.md").write_text("# Untracked\n")
    assert nav.validate_navigation(root, complete=True) == []
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n")
    (root / "escape.md").symlink_to(outside)
    _document(root, {"root": _node("index.md", children=[_node("escape.md")])})
    assert "NAV_PATH_ESCAPES" in _codes(root)


def test_snapshots_do_not_require_git(corpus, monkeypatch):
    def absent_git(*args, **kwargs):
        raise FileNotFoundError("git unavailable")

    monkeypatch.setattr(nav.subprocess, "run", absent_git)
    assert nav.validate_navigation(corpus, complete=True) == []


def test_source_git_failure_has_named_recovery(tmp_path, monkeypatch):
    root = tmp_path / "docs/public"
    root.mkdir(parents=True)
    (tmp_path / ".git").mkdir()
    _document(root, {"root": _node("index.md")})

    def absent_git(*args, **kwargs):
        raise FileNotFoundError("git unavailable")

    monkeypatch.setattr(nav.subprocess, "run", absent_git)
    refusals = nav.validate_navigation(root, complete=True)
    assert [r.code for r in refusals] == ["NAV_SCHEMA"]
    assert "restore git access" in refusals[0].repair


def test_path_must_encode_as_utf8(corpus):
    _document(corpus, {"root": _node("index.md", children=[_node("\ud800.md")])})
    refusals = nav.validate_navigation(corpus, complete=False)
    assert [r.code for r in refusals] == ["NAV_PATH_INVALID"]
    assert "UTF-8" in refusals[0].detail
    assert str(refusals[0]).encode("utf-8")
