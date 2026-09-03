"""The closed contract for capturing one macOS host's golden baseline.

A capture is the mirror image of the reset: the reset restores a directory
over a home, so this copies a home into a directory the reset will later
restore from. Both run as one bounded program on the host with a closed output
contract, because a capture that is only mostly complete produces a baseline
that is only mostly restorable, and nothing downstream can tell the difference.

What the capture refuses is as much of the contract as what it does. A home
holding Yoke residue captures that residue into the baseline every later reset
restores, so every declared-absent path is asserted absent first. A home
holding files another account owns captures files the test user cannot clear or
restore, so ownership is asserted too. Both refusals name the exact path.
"""

from __future__ import annotations


GOLDEN_CAPTURE_REMOTE_PATH = "/tmp/yoke-machine-qa-golden-capture.zsh"
GOLDEN_CAPTURE_MARKER = "YOKE_MAC_CAPTURE_OK"
CAPTURE_FAILURE_PREFIX = "YOKE_CAPTURE_FAILED_"
CAPTURE_PHASES = {
    "validate_home": "VALIDATE_HOME",
    "assert_full_disk_access": "ASSERT_FULL_DISK_ACCESS",
    "validate_destination": "VALIDATE_DESTINATION",
    "assert_home_ownership": "ASSERT_HOME_OWNERSHIP",
    "assert_no_yoke_residue": "ASSERT_NO_YOKE_RESIDUE",
    "copy_home": "COPY_HOME",
    "seal_permissions": "SEAL_PERMISSIONS",
    "write_manifest": "WRITE_MANIFEST",
    "emit_outcomes": "EMIT_OUTCOMES",
    "complete": "COMPLETE",
}

# Counted outcomes the successful capture emits, one line each.
CAPTURE_ENTRIES_PREFIX = "YOKE_CAPTURE_ENTRIES_"
CAPTURE_KILOBYTES_PREFIX = "YOKE_CAPTURE_KILOBYTES_"
CAPTURE_MANIFEST_DIGEST_PREFIX = "YOKE_CAPTURE_MANIFEST_DIGEST_"

# Closed failure detail. Kind plus the exact path ride stdout; the recovery
# sentence is reconstructed from the same kind, so the contract stays closed.
CAPTURE_REFUSAL_PREFIX = "YOKE_CAPTURE_REFUSED_"
CAPTURE_REFUSAL_KIND_RESIDUE = "yoke_residue"
CAPTURE_REFUSAL_KIND_FOREIGN_OWNER = "foreign_owner"
CAPTURE_REFUSAL_KIND_DESTINATION_OCCUPIED = "destination_occupied"
CAPTURE_REFUSAL_KINDS = (
    CAPTURE_REFUSAL_KIND_RESIDUE,
    CAPTURE_REFUSAL_KIND_FOREIGN_OWNER,
    CAPTURE_REFUSAL_KIND_DESTINATION_OCCUPIED,
)
CAPTURE_REFUSAL_RECOVERY = {
    CAPTURE_REFUSAL_KIND_RESIDUE: (
        "Yoke state is present at {path}; reset the host to its current "
        "golden baseline before capturing a new one, so the capture does not "
        "bake Yoke into the baseline every later reset restores."
    ),
    CAPTURE_REFUSAL_KIND_FOREIGN_OWNER: (
        "{path} inside the test home belongs to another account; the test "
        "user cannot clear or restore it. Repair its owner, then capture "
        "again."
    ),
    CAPTURE_REFUSAL_KIND_DESTINATION_OCCUPIED: (
        "Something already exists at {path}. Choose a new destination; a "
        "capture never overwrites a baseline another host may still restore "
        "from."
    ),
}

# The manifest is a bounded document rather than a per-file digest listing: a
# whole-home listing is gigabytes of names, and the facts that make a baseline
# checkable are its identity, size, shape, and the probes sealed beside it.
MANIFEST_FIELDS = (
    "captured_at",
    "source_home",
    "host_user",
    "top_level_entry_count",
    "kilobyte_count",
    "probes_digest",
)
# The golden directory and its sidecars are read-only once sealed, so a later
# restore cannot be corrupted by something writing into the baseline.
GOLDEN_DIRECTORY_MODE = "0555"
GOLDEN_SIDECAR_MODE = "0444"


def capture_refusal_recovery(kind: str, path: str) -> str:
    """Return the sentence naming what to change, or refuse an unknown kind."""
    try:
        return CAPTURE_REFUSAL_RECOVERY[kind].format(path=path)
    except KeyError:
        raise ValueError(f"unknown golden-capture refusal kind {kind!r}") from None


__all__ = [
    "CAPTURE_ENTRIES_PREFIX",
    "CAPTURE_FAILURE_PREFIX",
    "CAPTURE_KILOBYTES_PREFIX",
    "CAPTURE_MANIFEST_DIGEST_PREFIX",
    "CAPTURE_PHASES",
    "CAPTURE_REFUSAL_KINDS",
    "CAPTURE_REFUSAL_KIND_DESTINATION_OCCUPIED",
    "CAPTURE_REFUSAL_KIND_FOREIGN_OWNER",
    "CAPTURE_REFUSAL_KIND_RESIDUE",
    "CAPTURE_REFUSAL_PREFIX",
    "CAPTURE_REFUSAL_RECOVERY",
    "GOLDEN_CAPTURE_MARKER",
    "GOLDEN_CAPTURE_REMOTE_PATH",
    "GOLDEN_DIRECTORY_MODE",
    "GOLDEN_SIDECAR_MODE",
    "MANIFEST_FIELDS",
    "capture_refusal_recovery",
]
