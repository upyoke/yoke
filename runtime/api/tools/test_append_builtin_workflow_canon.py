"""Declaring a new published generation, and refusing to rewrite an old one.

Appending is the only sanctioned way a repo change to a current definition
becomes canon. Everything here guards the same property from a different side:
what this tool writes is additive, and what it will not do is touch a
generation some universe already holds.

The write tests drive a synthetic scan rather than the real one, so appending a
generation to the live canon later does not turn them red -- what they are about
is the writing, not which definitions currently need it.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.tools import append_builtin_workflow_canon as appender

_APPENDED_NAME = "a-workflow.02.json"


@pytest.fixture()
def canon_checkout(tmp_path):
    """A throwaway checkout with an empty canon directory.

    Empty is enough: the real scan reads its generations from the installed
    package, so this directory only has to exist to be written into.
    """
    (tmp_path / appender.CANON_SUBPATH).mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def one_pending(monkeypatch):
    """Replace the scan with one workflow whose definition is not yet canon."""
    definition = {"policies": {"a_key_no_generation_carries": "value"}}

    def _scan(canon_dir):
        return [{
            "workflow_id": "a-workflow",
            "definition": definition,
            "digest": "0" * 64,
            "canon_version": 2,
            "recognized_as": None,
            "path": canon_dir / _APPENDED_NAME,
        }]

    monkeypatch.setattr(appender, "_appendable", _scan)
    return definition


def _run(root, *extra):
    return appender.main([
        "--target-root", str(root),
        "--published-at", "2026-08-09T00:00:00Z",
        *extra,
    ])


def _files(root) -> set[str]:
    return {
        path.name
        for path in (root / appender.CANON_SUBPATH).glob("*.json")
    }


def test_the_live_tree_has_nothing_to_append(canon_checkout, capsys):
    """Shipping a current definition means appending it, so an unmodified
    checkout is a no-op -- and this says so through the real scan."""
    assert _run(canon_checkout) == 0

    assert _files(canon_checkout) == set()
    output = capsys.readouterr().out
    assert "nothing to append" in output
    assert "would append" not in output


def test_a_pending_definition_is_appended_as_the_next_number(
    canon_checkout, one_pending,
):
    """Version numbers are positions in the canon's own sequence, so the new
    generation lands at the number the scan resolved for its workflow."""
    assert _run(canon_checkout) == 0

    assert _files(canon_checkout) == {_APPENDED_NAME}
    payload = json.loads(
        (canon_checkout / appender.CANON_SUBPATH / _APPENDED_NAME).read_text(
            encoding="utf-8",
        )
    )
    assert payload["canon_version"] == 2
    assert payload["workflow_id"] == "a-workflow"
    assert payload["published_at"] == "2026-08-09T00:00:00Z"
    assert payload["definition"] == one_pending
    # Nothing has run this definition yet, so naming an observation would be
    # inventing provenance.
    assert payload["observed_as"] == []


def test_the_appended_file_carries_the_shape_the_loader_requires(
    canon_checkout, one_pending,
):
    """Written by a different path than the founding extraction, so the keys
    the canon loader reads are asserted here rather than assumed."""
    _run(canon_checkout)

    payload = json.loads(
        (canon_checkout / appender.CANON_SUBPATH / _APPENDED_NAME).read_text(
            encoding="utf-8",
        )
    )
    for key in ("workflow_id", "canon_version", "published_at", "definition"):
        assert key in payload


def test_a_dry_run_writes_nothing(canon_checkout, one_pending, capsys):
    assert _run(canon_checkout, "--dry-run") == 0

    assert _files(canon_checkout) == set()
    assert "would append" in capsys.readouterr().out


def test_an_occupied_generation_number_refuses_rather_than_rewriting(
    canon_checkout, one_pending, capsys,
):
    """A stored digest that moves is indistinguishable from corruption to every
    universe holding it, so the collision stops the run."""
    occupied = canon_checkout / appender.CANON_SUBPATH / _APPENDED_NAME
    occupied.write_text('{"canon_version": 2}', encoding="utf-8")

    assert _run(canon_checkout) == 1

    assert occupied.read_text(encoding="utf-8") == '{"canon_version": 2}'
    assert "refusing to rewrite" in capsys.readouterr().err


def test_a_checkout_without_a_canon_directory_is_refused(tmp_path, capsys):
    assert _run(tmp_path) == 2

    assert "no canon directory" in capsys.readouterr().err
