"""Closed stdout parsing for the macOS golden-capture receipt."""

from __future__ import annotations

from yoke_harness.ssh_mac_golden_capture_contract import (
    CAPTURE_ENTRIES_PREFIX,
    CAPTURE_FAILURE_PREFIX,
    CAPTURE_KILOBYTES_PREFIX,
    CAPTURE_MANIFEST_DIGEST_PREFIX,
    CAPTURE_PHASES,
    CAPTURE_REFUSAL_KINDS,
    CAPTURE_REFUSAL_PREFIX,
    GOLDEN_CAPTURE_MARKER,
    capture_refusal_recovery,
)


def closed_capture_outcomes(stdout: str) -> dict[str, str | int] | None:
    """Parse the counted success receipt the capture program emits."""
    lines = tuple(line.strip() for line in stdout.splitlines() if line.strip())
    parsed: dict[str, str | int] = {}
    for line in lines:
        if line == GOLDEN_CAPTURE_MARKER:
            continue
        if line.startswith(CAPTURE_ENTRIES_PREFIX):
            value = line.removeprefix(CAPTURE_ENTRIES_PREFIX)
            if not value.isdigit():
                return None
            parsed["captured_entries"] = int(value)
        elif line.startswith(CAPTURE_KILOBYTES_PREFIX):
            value = line.removeprefix(CAPTURE_KILOBYTES_PREFIX)
            if not value.isdigit():
                return None
            parsed["captured_kilobytes"] = int(value)
        elif line.startswith(CAPTURE_MANIFEST_DIGEST_PREFIX):
            digest = line.removeprefix(CAPTURE_MANIFEST_DIGEST_PREFIX)
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                return None
            parsed["manifest_digest"] = digest
        else:
            return None
    if (
        len(lines) != 4
        or lines.count(GOLDEN_CAPTURE_MARKER) != 1
        or set(parsed) != {"captured_entries", "captured_kilobytes", "manifest_digest"}
        or int(parsed["captured_entries"]) < 1
    ):
        return None
    return parsed


def capture_failure_outcome(stdout: str) -> tuple[str, dict[str, str] | None] | None:
    """Parse a closed failure marker, optionally with its named refusal."""
    lines = tuple(line.strip() for line in stdout.splitlines() if line.strip())
    if len(lines) not in {1, 2} or not lines[0].startswith(CAPTURE_FAILURE_PREFIX):
        return None
    phase = lines[0].removeprefix(CAPTURE_FAILURE_PREFIX)
    phase_names = {value: name for name, value in CAPTURE_PHASES.items()}
    if phase not in phase_names:
        return None
    if len(lines) == 1:
        return phase_names[phase], None
    detail = lines[1]
    if not detail.startswith(CAPTURE_REFUSAL_PREFIX):
        return None
    kind, separator, path = detail.removeprefix(CAPTURE_REFUSAL_PREFIX).partition(" ")
    if not separator or kind not in CAPTURE_REFUSAL_KINDS or not path.startswith("/"):
        return None
    return phase_names[phase], {
        "reason": kind,
        "path": path,
        "recovery": capture_refusal_recovery(kind, path),
    }


__all__ = ["capture_failure_outcome", "closed_capture_outcomes"]
