"""Every ``yoke`` help page renders, and its usage line names its real flags.

A hand-written usage synopsis drifts when a flag is added or renamed; this
renders each command's ``--help`` in-process and compares the synopsis with
the options argparse lists.
"""

from __future__ import annotations

import contextlib
import io
import re
from pathlib import Path

from yoke_cli.commands.command_tree import command_routes
from yoke_cli.main import main

_FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
_OPTION = re.compile(r"\s{2}(-[-\w]+(?:[ =][A-Z_][A-Z0-9_]*)?(?:, -[-\w]+(?:[ =][A-Z_][A-Z0-9_]*)?)*)")


def _render(route: tuple[str, ...]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = main([*route, "--help"])
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


def _usage_drift(text: str) -> tuple[list[str], list[str]]:
    """Flags the options list has but the synopsis omits, and the reverse."""
    if "options:" not in text or "usage: yoke " not in text:
        return [], []
    head, options = text.split("options:", 1)
    usage = re.search(r"usage: (yoke .*?)(?:\n\s*\n|$)", head, re.S)
    if usage is None or "[options]" in usage.group(1):
        return [], []
    named = set(_FLAG.findall(usage.group(1))) - {"--help"}
    listed = {
        flag
        for line in options.splitlines()
        if (m := _OPTION.match(line))
        for flag in _FLAG.findall(m.group(1))
    } - {"--help"}
    return sorted(listed - named), sorted(named - listed)


def audit() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for route in sorted(command_routes()):
        name = "yoke " + " ".join(route)
        rc, out, err = _render(route)
        if rc != 0 or not out.strip():
            found.setdefault("help_fails", []).append(f"{name}: rc={rc} {err[:160]}")
            continue
        missing, unknown = _usage_drift(out)
        if missing:
            found.setdefault("usage_omits", []).append(f"{name}: {missing}")
        if unknown:
            found.setdefault("usage_names_unknown", []).append(f"{name}: {unknown}")
    return found


def test_every_help_page_renders_and_names_its_flags(monkeypatch) -> None:
    def deny(*args, **kwargs):
        raise AssertionError("help attempted execution or network access")

    monkeypatch.setattr("subprocess.Popen", deny)
    monkeypatch.setattr("socket.socket.connect", deny)
    monkeypatch.setattr(Path, "write_text", deny)
    found = audit()
    assert not found, "\n".join(
        f"{kind}: {row}" for kind, rows in found.items() for row in rows[:60]
    )
