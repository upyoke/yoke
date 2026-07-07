"""Terminal-facing board print helpers."""

from __future__ import annotations

import os
import re
from typing import Any, Mapping


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def board_print_content(
    content: str,
    payload: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    lines = [source_banner(payload)]
    reason = plain_board_reason(env)
    if reason:
        lines.append(f"Yoke board terminal mode: plain ({reason})")
        lines.append(
            "Run in Terminal.app or iTerm2 outside GNU Screen for rich board art."
        )
        lines.append("")
        lines.append(simplify_board_text(content))
    else:
        lines.append("")
        lines.append(content)
    text = "\n".join(lines)
    return text if text.endswith("\n") else text + "\n"


def source_banner(payload: Mapping[str, Any]) -> str:
    parts = ["Yoke board source:"]
    for label, key in (
        ("env", "env_name"),
        ("scope", "scope"),
        ("checkout", "repo_root"),
        ("board", "board_path"),
        ("data", "data_source"),
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            parts.append(f"{label}={value}")
    return " ".join(parts)


def format_data_source(connection: Mapping[str, Any]) -> str:
    transport = str(connection.get("transport") or "").strip()
    if not transport:
        return ""
    api_url = str(connection.get("api_url") or "").strip().rstrip("/")
    if api_url:
        return api_url
    return transport


def terminal_needs_plain_board(env: Mapping[str, str] | None = None) -> bool:
    return bool(plain_board_reason(env))


def plain_board_reason(env: Mapping[str, str] | None = None) -> str:
    environ = os.environ if env is None else env
    rich = str(environ.get("YOKE_BOARD_RICH") or "").strip().lower()
    if rich in {"1", "true", "yes", "on"}:
        return ""
    forced = str(environ.get("YOKE_BOARD_PLAIN") or "").strip().lower()
    if forced in {"1", "true", "yes", "on"}:
        return "YOKE_BOARD_PLAIN is set"
    term = str(environ.get("TERM") or "").strip().lower()
    if environ.get("STY"):
        return "GNU Screen session detected"
    if term in {"", "dumb"}:
        return f"TERM={term or '<unset>'}"
    if term == "screen" or term.startswith("screen-"):
        return f"TERM={term}"
    return ""


def simplify_board_text(content: str) -> str:
    """Return an ASCII-width version for terminals with weak Unicode support."""

    replacements = {
        "—": "-",
        "–": "-",
        "·": ".",
        "•": "*",
        "✔": "*",
        "✓": "*",
        "✅": "[done]",
        "🚫": "[x]",
        "🧊": "[frozen]",
        "🏆": "*",
        "🏅": "*",
        "🌻": "*",
        "🔥": "*",
        "🎯": "*",
        "📫": "*",
        "📊": "*",
        "🐝": "*",
        "💻": "*",
        "🪑": "*",
        "👓": "*",
        "🦃": "*",
        "🟢": "*",
        "🔵": "*",
        "🟩": "#",
        "🟨": "#",
        "🟥": "#",
        "🟦": "#",
        "🟧": "#",
        "🟪": "#",
        "🟫": "#",
        "⬛": "#",
        "⬜": ".",
        "╔": "+",
        "╗": "+",
        "╚": "+",
        "╝": "+",
        "╠": "+",
        "╣": "+",
        "╦": "+",
        "╩": "+",
        "╬": "+",
        "═": "=",
        "║": "|",
        "┌": "+",
        "┐": "+",
        "└": "+",
        "┘": "+",
        "├": "+",
        "┤": "+",
        "┬": "+",
        "┴": "+",
        "┼": "+",
        "─": "-",
        "│": "|",
        "▁": "_",
        "▂": "_",
        "▃": "_",
        "▄": "_",
        "▅": "_",
        "▆": "_",
        "▇": "_",
        "█": "#",
        "░": ".",
        "▒": ":",
        "▓": "#",
    }
    simplified = _ANSI_RE.sub("", content)
    for source, target in replacements.items():
        simplified = simplified.replace(source, target)
    return simplified.encode("ascii", "ignore").decode("ascii")


__all__ = [
    "board_print_content",
    "format_data_source",
    "plain_board_reason",
    "simplify_board_text",
    "source_banner",
    "terminal_needs_plain_board",
]
