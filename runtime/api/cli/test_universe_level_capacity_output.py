"""`yoke universe level-capacity get` prints each project's previewed launch."""

from __future__ import annotations

import io

from yoke_cli.commands.adapters.universe_levels import write_capacity


def _result(level: dict) -> dict:
    return {
        "read_at": "2026-10-08T12:00:00Z",
        "usable_machines": 1,
        "live_workers": {"claude-cli": 1},
        "levels": [{"name": "SENIOR", "glyph": "*", "options": [], **level}],
        "projects": [],
    }


def _print(level: dict) -> str:
    out = io.StringIO()
    write_capacity(_result(level), out)
    return out.getvalue()


def test_each_project_names_its_placed_launch_or_its_refusal():
    text = _print(
        {
            "launchable_surfaces": ["codex-cli"],
            "next_launches": [
                {
                    "project": "yoke",
                    "launchable": True,
                    "option_index": 1,
                    "fallback": True,
                    "surface": "codex-cli",
                    "model": "gpt-6.1-sol",
                    "machine_id": "m-codex",
                    "reason": "level SENIOR: most headroom",
                },
                {
                    "project": "buzz",
                    "launchable": False,
                    "code": "permission_denied",
                    "reason": "actor 1 is not an operator for this project",
                },
            ],
        }
    )
    assert (
        "  next launch in yoke -> codex-cli gpt-6.1-sol (option 2, fallback) on "
        "m-codex: level SENIOR: most headroom\n"
    ) in text
    assert (
        "  next launch in buzz -> refused (permission_denied): actor 1 is not an "
        "operator for this project\n"
    ) in text
    assert "NO CAPACITY" not in text


def test_no_capacity_and_a_server_without_previews_are_named():
    text = _print({"launchable_surfaces": []})
    assert "  NO CAPACITY: no option can launch on any machine\n" in text
    assert "next launch: not reported; the serving build predates" in text
    assert "yoke session-control launch preview --project P --level L" in text
