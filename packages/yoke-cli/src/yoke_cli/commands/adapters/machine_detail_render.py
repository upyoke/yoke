"""Sectioned machine detail with bounded routine inventories."""

from __future__ import annotations

from typing import Any, TextIO

from yoke_cli.transport.human_values import label, write_human


def write_machine_detail(
    result: dict[str, Any], stdout: TextIO, _stderr: TextIO, *, full: bool = False
) -> None:
    """Keep complete values available through the shared --full read flag."""
    relay = result.get("relay")
    models = (relay or {}).get("native_models") or {}
    sections = dict(result)
    sections["relay"] = (
        {key: value for key, value in relay.items() if key != "native_models"}
        if relay is not None
        else None
    )
    sections["native_models"] = models
    order = (
        "machine",
        "relay",
        "native_models",
        "harnesses",
        "projects",
        "test_machines",
        "running_sessions",
        "recent_sessions",
        "recent_launches",
        "surface_policies",
        "token",
        "credential_presence",
    )
    for key in dict.fromkeys((*order, *sections)):
        if key not in sections:
            continue
        title = (
            "Credentials" if key == "credential_presence" else label(key).capitalize()
        )
        print(f"## {title}", file=stdout)
        value = sections[key]
        if key == "native_models":
            _write_models(value, stdout, full=full)
        elif key in {"running_sessions", "recent_sessions", "recent_launches"}:
            rows = sorted(
                value,
                key=lambda row: str(
                    row.get("created_at" if key == "recent_launches" else "offered_at")
                    or ""
                ),
                reverse=True,
            )
            shown = rows if full else rows[:10]
            print(f"Count: {len(rows)}; showing {len(shown)}.", file=stdout)
            if len(shown) < len(rows):
                print("Use --full to show every entry.", file=stdout)
            write_human(shown, stdout, heading=title)
        else:
            write_human(value, stdout, heading=title)
        print(file=stdout)


def _write_models(models: dict[str, Any], stream: TextIO, *, full: bool) -> None:
    if not models:
        write_human(models, stream, heading="Native models")
        return
    if not full:
        print("Use --full for model names and observation details.", file=stream)
    for surface, reading in models.items():
        print(f"### {surface}", file=stream)
        if full:
            write_human(reading, stream)
        else:
            print(
                f"{surface}: {reading.get('status', 'unknown')}; "
                f"{len(reading.get('models') or [])} models",
                file=stream,
            )
