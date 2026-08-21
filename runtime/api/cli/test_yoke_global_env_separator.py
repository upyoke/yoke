"""Global ``--env`` must not be taken from argv after ``--``."""

from __future__ import annotations

from yoke_cli.main import _extract_global_env


def test_inner_env_after_separator_is_left_for_the_inner_process() -> None:
    remaining, selected, ok = _extract_global_env([
        "dev", "run", "--",
        "env", "YOKE_MACHINE_HOME=/tmp/iso",
        "yoke", "--env", "relay-check",
        "events", "query", "--limit", "1",
    ])
    assert ok
    assert selected is None
    assert remaining == [
        "dev", "run", "--",
        "env", "YOKE_MACHINE_HOME=/tmp/iso",
        "yoke", "--env", "relay-check",
        "events", "query", "--limit", "1",
    ]


def test_outer_env_before_separator_is_still_extracted() -> None:
    remaining, selected, ok = _extract_global_env([
        "--env", "prod", "dev", "run", "--",
        "yoke", "--env", "relay-check",
    ])
    assert ok
    assert selected == "prod"
    assert remaining == [
        "dev", "run", "--", "yoke", "--env", "relay-check",
    ]


def test_env_equals_form_after_separator_is_not_extracted() -> None:
    remaining, selected, ok = _extract_global_env([
        "dev", "run", "--", "yoke", "--env=relay-check", "events", "query",
    ])
    assert ok
    assert selected is None
    assert "--env=relay-check" in remaining
