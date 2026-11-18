"""Seal a Linux or WSL golden's probes sidecar and read it back as reset will.

Capture writes ``GOLDEN.probes`` through the host transport, reads it back and
compares byte count and sha256 before the golden can be registered, then seals
the verified digest as ``GOLDEN.probes.sha256``. Reset reads both and names why
the probes cannot be used: missing or empty, unreadable, or unparseable with
the observed and expected digests. Evidence never carries program contents.
"""

from __future__ import annotations

import hashlib
from typing import Any

from yoke_contracts.ssh_mac_full_reset_contract import GOLDEN_PROBES_SUFFIX
from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness.ssh_mac_baseline_probes import parse_baseline_probes

GOLDEN_PROBES_DIGEST_SUFFIX = GOLDEN_PROBES_SUFFIX + ".sha256"
_RECAPTURE = "capture a new golden to a new destination; keep the existing golden and its sidecars for inspection."


def probes_fingerprint(document: str | None) -> dict[str, Any]:
    """Return the UTF-8 byte count and sha256 of one probes document."""
    if document is None:
        return {"bytes": 0, "sha256": None}
    data = document.encode("utf-8")
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def parse_failure(exc: ValueError) -> dict[str, str]:
    """Name a parse refusal and its underlying cause, e.g. a JSON position."""
    cause = exc.__cause__
    return {
        "exception_type": type(cause or exc).__name__,
        "exception_message": f"{exc}: {cause}" if cause else str(exc),
    }


def _unverified(evidence: dict[str, Any]) -> HostActionResult:
    return HostActionResult(
        False,
        {
            **evidence,
            "recovery": "The probes written beside the golden did not read back as sent; "
            "compare sent_bytes/sent_sha256 with read_bytes/read_sha256, repair the "
            "host transport, then " + _RECAPTURE,
        },
        "golden_probes_write_unverified",
    )


def seal_golden_probes(
    control: Any, destination: str, document: str
) -> HostActionResult:
    """Write the probes, prove the host holds exactly them, then seal the digest."""
    path = destination + GOLDEN_PROBES_SUFFIX
    sent = probes_fingerprint(document)
    evidence: dict[str, Any] = {
        "probes_path": path,
        "sent_bytes": sent["bytes"],
        "sent_sha256": sent["sha256"],
    }
    try:
        control.upload_remote_text(path, document)
    except RuntimeError as exc:
        return HostActionResult(
            False,
            {
                **evidence,
                "write_error": str(exc),
                "recovery": "Repair the probes write named in write_error, then "
                + _RECAPTURE,
            },
            "golden_probes_write_failed",
        )
    try:
        readback = control.read_remote_text(path)
    except RuntimeError as exc:
        return _unverified({**evidence, "read_error": str(exc)})
    observed = probes_fingerprint(readback)
    evidence.update(read_bytes=observed["bytes"], read_sha256=observed["sha256"])
    if readback is None or observed != sent:
        return _unverified(evidence)
    try:
        parse_baseline_probes(readback)
    except ValueError as exc:
        return _unverified({**evidence, **parse_failure(exc)})
    digest_path = destination + GOLDEN_PROBES_DIGEST_SUFFIX
    try:
        control.upload_remote_text(digest_path, str(sent["sha256"]))
    except RuntimeError as exc:
        return HostActionResult(
            False,
            {
                **evidence,
                "write_error": str(exc),
                "recovery": f"Repair the write of {digest_path} named in write_error, then "
                + _RECAPTURE,
            },
            "golden_probes_write_failed",
        )
    return HostActionResult(
        True, {"probes_bytes": sent["bytes"], "probes_sha256": sent["sha256"]}
    )


def read_sealed_probes(control: Any, destination: str) -> HostActionResult:
    """Read and parse the sealed probes, naming exactly why they are unusable."""
    path = destination + GOLDEN_PROBES_SUFFIX
    try:
        document = control.read_remote_text(path)
    except RuntimeError as exc:
        return HostActionResult(
            False,
            {
                "probes_path": path,
                "read_error": str(exc),
                "recovery": f"Repair access to {path} (an absolute regular file, not a symlink), then retry.",
            },
            "baseline_probes_unavailable",
        )
    if document is None:
        return HostActionResult(
            False,
            {
                "probes_path": path,
                "recovery": f"{path} is missing or empty; " + _RECAPTURE,
            },
            "baseline_probes_unavailable",
        )
    try:
        probes = parse_baseline_probes(document)
    except ValueError as exc:
        observed = probes_fingerprint(document)
        return HostActionResult(
            False,
            {
                "probes_path": path,
                **parse_failure(exc),
                "bytes": observed["bytes"],
                "sha256": observed["sha256"],
                "expected_sha256": _sealed_digest(control, destination),
                "recovery": "Compare sha256 with expected_sha256: a mismatch means the "
                "file changed or was truncated after capture; " + _RECAPTURE,
            },
            "baseline_probes_invalid",
        )
    return HostActionResult(True, {"sealed_probe_count": len(probes)})


def _sealed_digest(control: Any, destination: str) -> str | None:
    """Return the digest capture sealed, or None when none was sealed or readable."""
    try:
        text = control.read_remote_text(destination + GOLDEN_PROBES_DIGEST_SUFFIX)
    except RuntimeError:
        return None
    return text.strip() if text else None
