"""Append-only diagnostic log for the ``yoke onboard`` wizard.

The wizard runs full-screen, so a failure it recovers from (a browser that
would not open, a cancelled approval wait) has nowhere to print a traceback.
Each such event lands as one timestamped line under the machine's Yoke home,
beside the config file the wizard writes, so the operator can read why after
the screen has moved on. Writing never raises: a log that cannot be written
must not take the wizard down with it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "onboard-wizard.log"


def log_path(config_path: str | Path) -> Path:
    """The wizard log beside the machine config (``~/.yoke/logs/…`` by default)."""
    return Path(config_path).expanduser().parent / LOG_DIR_NAME / LOG_FILE_NAME


def record(config_path: str | Path, event: str, **fields: object) -> Path | None:
    """Append one ``<utc-timestamp> <event> key=value …`` line.

    Returns the log path when the line was written and ``None`` when the log
    could not be written, so a view can name the file only when it exists.
    """
    target = log_path(config_path)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    detail = " ".join(f"{key}={_one_line(value)}" for key, value in fields.items())
    line = f"{stamp} {event} {detail}".rstrip() + "\n"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        return None
    return target


def _one_line(value: object) -> str:
    text = str(value if value is not None else "")
    return " ".join(text.split()) or "-"


__all__ = ["LOG_DIR_NAME", "LOG_FILE_NAME", "log_path", "record"]
