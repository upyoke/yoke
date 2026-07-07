"""Regression tests for AC-38: nearest-match denial hints.

Covers the pure ranker, the formatted hint string, and the two
operator-facing emitters used by ``db_router``'s unknown-domain and
unknown-items-subcommand denial paths. The 24-line subcommand wall the
ticket targets must not return.
"""

from __future__ import annotations

import io

import pytest

from yoke_core.cli import db_router_suggestions as sugg


def _pin_router_env(monkeypatch):
    """Mark init done so db_router hits the denial paths without bootstrap
    side effects; the ambient per-worker test DB is the connection target."""
    monkeypatch.setenv("YOKE_DB_INIT_DONE", "1")


# ---------- nearest_matches (pure) ------------------------------------------


def test_nearest_match_returns_close_typo():
    matches = sugg.nearest_matches("projeect", ["projects", "epic", "events"])
    assert matches[0] == "projects"


def test_nearest_match_returns_empty_when_no_candidate_close():
    assert sugg.nearest_matches("zzzzzz", ["projects", "epic"]) == []


def test_nearest_match_empty_target():
    assert sugg.nearest_matches("", ["a", "b"]) == []


def test_nearest_match_caps_at_max_results():
    matches = sugg.nearest_matches(
        "item", ["items", "events", "envs", "epic"], max_results=2,
    )
    assert len(matches) <= 2


def test_nearest_match_is_case_insensitive():
    matches = sugg.nearest_matches("PROJECTS", ["projects"])
    assert matches == ["projects"]


def test_nearest_match_short_token_uses_tight_threshold():
    # Single-char target rejects anything more than 1 edit away.
    matches = sugg.nearest_matches("a", ["abc", "abcd", "abcde"])
    assert matches == []
    # But a one-letter edit is allowed.
    assert sugg.nearest_matches("a", ["ab"]) == ["ab"]


def test_nearest_match_ranks_by_distance():
    matches = sugg.nearest_matches(
        "ger", ["get", "set", "got"], max_results=3,
    )
    # 'get' (1 edit) ranks above 'set' (2) / 'got' (2)
    assert matches[0] == "get"


# ---------- format_unknown_token_hint ---------------------------------------


def test_format_hint_single_match():
    out = sugg.format_unknown_token_hint(
        "projeect", "domain", ["projects", "epic"]
    )
    assert "Did you mean: 'projects'?" in out
    assert "epic" not in out


def test_format_hint_multiple_matches():
    out = sugg.format_unknown_token_hint(
        "getx", "items subcommand", ["get", "gets", "got"]
    )
    assert out.startswith("Did you mean one of:")
    assert "'get'" in out


def test_format_hint_no_close_match():
    out = sugg.format_unknown_token_hint("xyz", "domain", ["aaa", "bbb"])
    assert "No close match for domain 'xyz'." in out


def test_format_hint_includes_list_subcommands_fallback():
    out = sugg.format_unknown_token_hint(
        "xyz", "domain", ["aaa"],
        list_subcommands_hint="See `db_router help` for the full list.",
    )
    assert "See `db_router help`" in out


# ---------- emit_unknown_domain_hint -----------------------------------------


def test_emit_unknown_domain_hint_targets_projects():
    buf = io.StringIO()
    sugg.emit_unknown_domain_hint("projeect", stream=buf)
    out = buf.getvalue()
    assert "Error: unknown domain 'projeect'" in out
    assert "Did you mean: 'projects'?" in out
    # The 19-domain wall must not be inlined here.
    assert "Backlog item reads and writes" not in out
    # The list-fallback pointer is present.
    assert "db_router help" in out


def test_emit_unknown_domain_hint_no_match_falls_through():
    buf = io.StringIO()
    sugg.emit_unknown_domain_hint("zzzzzz", stream=buf)
    out = buf.getvalue()
    assert "Error: unknown domain 'zzzzzz'" in out
    assert "No close match for domain 'zzzzzz'." in out
    assert "db_router help" in out


# ---------- emit_unknown_items_subcmd_hint -----------------------------------


def test_emit_unknown_items_subcmd_hint_targets_get():
    buf = io.StringIO()
    sugg.emit_unknown_items_subcmd_hint("getx", stream=buf)
    out = buf.getvalue()
    assert "Error: unknown items subcommand 'getx'" in out
    assert "Did you mean: 'get'?" in out
    # The previous 23-subcommand wall (Reads + Writes inlined) must not
    # appear here. The list-fallback pointer should appear instead.
    assert "Reads  (in-process via query_items_cli):" not in out
    assert "items --list-subcommands" in out


def test_emit_unknown_domain_subcmd_hint_targets_projects_get():
    buf = io.StringIO()
    emitted = sugg.emit_unknown_domain_subcmd_hint(
        "projects", "yoke_core.domain.projects", ["ger"], stream=buf,
    )
    out = buf.getvalue()
    assert emitted is True
    assert "Error: unknown projects subcommand 'ger'" in out
    assert "Did you mean: 'get'?" in out
    assert "Project-domain CRUD" not in out
    assert "projects --help" in out


def test_emit_unknown_domain_subcmd_hint_known_subcommand_returns_false():
    buf = io.StringIO()
    emitted = sugg.emit_unknown_domain_subcmd_hint(
        "projects", "yoke_core.domain.projects", ["get"], stream=buf,
    )
    assert emitted is False
    assert buf.getvalue() == ""


# ---------- end-to-end via the db_router CLI shape ---------------------------


def test_db_router_unknown_domain_emits_nearest_hint(monkeypatch, capsys):
    _pin_router_env(monkeypatch)
    from yoke_core.cli import db_router

    rc = db_router.main(["projeect"])
    out, err = capsys.readouterr()
    assert rc == 2
    combined = out + err
    assert "unknown domain 'projeect'" in combined
    assert "Did you mean: 'projects'?" in combined
    # The full domain table dump must not surface here.
    assert "Backlog item reads and writes" not in combined


def test_db_router_unknown_items_subcmd_emits_nearest_hint(
    monkeypatch, capsys,
):
    _pin_router_env(monkeypatch)
    from yoke_core.cli import db_router

    rc = db_router.main(["items", "getx", "1"])
    out, err = capsys.readouterr()
    assert rc == 2
    combined = out + err
    assert "unknown items subcommand 'getx'" in combined
    assert "Did you mean: 'get'?" in combined
    assert "Reads  (in-process via query_items_cli):" not in combined


def test_db_router_unknown_routed_subcmd_emits_nearest_hint(
    monkeypatch, capsys,
):
    _pin_router_env(monkeypatch)
    from yoke_core.cli import db_router

    rc = db_router.main(["projects", "ger", "yoke"])
    out, err = capsys.readouterr()
    assert rc == 2
    combined = out + err
    assert "unknown projects subcommand 'ger'" in combined
    assert "Did you mean: 'get'?" in combined
    assert "Project-domain CRUD" not in combined


def test_db_router_items_list_subcommands_prints_full_inventory(
    monkeypatch, capsys,
):
    _pin_router_env(monkeypatch)
    from yoke_core.cli import db_router

    rc = db_router.main(["items", "--list-subcommands"])
    out, err = capsys.readouterr()
    assert rc == 0
    combined = out + err
    assert "items subcommands:" in combined
    assert "Reads  (in-process via query_items_cli):" in combined
    assert "Writes (via service_client backlog-cli):" in combined
