"""Capacity CLI prints model thresholds, native standing and the two Cursor pools."""

import io
from yoke_cli.commands.adapters.universe_levels import write_capacity


def test_capacity_is_model_based_without_preview_or_machine_cruft():
    result = {
        "cursor_quota_order": ["Cursor Models", "Other Models"],
        "levels": [
            {
                "name": "SENIOR",
                "glyph": "🦉",
                "launchable_surfaces": ["cursor-cli"],
                "options": [
                    {
                        "model": "claude-opus-5-5",
                        "min_effort": "medium",
                        "now": {"state": "can_launch"},
                    }
                ],
            }
        ],
    }
    out = io.StringIO()
    write_capacity(result, out)
    text = out.getvalue()
    assert "1. claude-opus-5-5  min_effort=medium [can launch]" in text
    assert "Launchable on: cursor-cli" in text
    assert "Cursor quota order: Cursor Models -> Other Models" in text
    assert "next launch" not in text
    assert "machine" not in text


def test_blocked_capacity_names_the_repair():
    out = io.StringIO()
    write_capacity(
        {
            "levels": [
                {
                    "name": "INTERN",
                    "options": [
                        {
                            "model": "grok-4.7",
                            "min_effort": "low",
                            "now": {
                                "state": "blocked",
                                "blockers": [
                                    {
                                        "label": "native_models_unknown: refresh native listing"
                                    }
                                ],
                            },
                        }
                    ],
                }
            ]
        },
        out,
    )
    assert "blocked: native_models_unknown: refresh native listing" in out.getvalue()
