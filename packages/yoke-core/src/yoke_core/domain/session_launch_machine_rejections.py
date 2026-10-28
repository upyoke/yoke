"""Per-machine reasons a launch could not use a machine.

Eligibility judges every relay row, but a refusal that merges all rows'
reasons into one set lets long-dead machines hide the real cause on a live
one. Each rejection here belongs to exactly one machine and carries the
reasons of that machine's freshest relay, so a refusal can say which machine
failed which rule. Machines that have not reported for a day are collapsed
into one unnamed count so they cannot drown out the machines that matter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

from yoke_contracts.harness_cli_manifest import HARNESS_CLI_MANIFESTS
from yoke_contracts.timestamps import as_utc, parse_instant

#: A machine silent for longer than this is reported as offline, not by rule.
OFFLINE_AFTER = timedelta(days=1)
LIVENESS_EXPIRED = "liveness_expired"


@dataclass(frozen=True)
class MachineRejection:
    """Why one machine offered no usable relay for the requested surface."""

    machine_id: str
    hostname: str
    codes: tuple[str, ...]
    last_seen_at: datetime | None
    #: Silent past ``OFFLINE_AFTER`` when eligibility judged it.
    offline: bool = False
    recovery: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.hostname or self.machine_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "hostname": self.hostname,
            "codes": list(self.codes),
            "last_seen_at": _instant(self.last_seen_at),
            "offline": self.offline,
            "recovery": list(self.recovery),
        }


def _instant(value: datetime | None) -> str | None:
    if value is None:
        return None
    return as_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def rejection_from_row(
    *,
    machine_id: str,
    hostname: str,
    codes: Iterable[str],
    last_seen_at: Any,
    now: datetime,
    surface: str | None = None,
) -> MachineRejection:
    codes = tuple(sorted(set(codes)))
    recovery = []
    for manifest in HARNESS_CLI_MANIFESTS:
        if manifest.surface_id != surface:
            continue
        if "surface_absent" in codes:
            recovery.append(manifest.missing_cli_recovery())
        if "harness_signed_out" in codes:
            recovery.append(manifest.sign_in_recovery())
    seen = parse_instant(last_seen_at) if last_seen_at else None
    return MachineRejection(
        machine_id=machine_id,
        hostname=hostname,
        codes=codes,
        recovery=tuple(recovery),
        last_seen_at=seen,
        offline=seen is not None and as_utc(now) - seen > OFFLINE_AFTER,
    )


def merge_machine_rejections(
    groups: Iterable[Sequence[MachineRejection]],
    *,
    exclude: Iterable[str] = (),
) -> tuple[MachineRejection, ...]:
    """One rejection per machine across several snapshots (e.g. surfaces).

    A machine named in ``exclude`` found a usable relay somewhere and is not
    a rejection at all.
    """
    skipped = set(exclude)
    merged: dict[str, MachineRejection] = {}
    for group in groups:
        for entry in group:
            if entry.machine_id in skipped:
                continue
            prior = merged.get(entry.machine_id)
            if prior is None:
                merged[entry.machine_id] = entry
                continue
            seen = [v for v in (prior.last_seen_at, entry.last_seen_at) if v]
            merged[entry.machine_id] = MachineRejection(
                machine_id=entry.machine_id,
                hostname=prior.hostname or entry.hostname,
                codes=tuple(sorted(set(prior.codes) | set(entry.codes))),
                last_seen_at=max(seen) if seen else None,
                offline=prior.offline and entry.offline,
                recovery=tuple(dict.fromkeys((*prior.recovery, *entry.recovery))),
            )
    return tuple(merged[machine] for machine in sorted(merged))


def _machine_clause(entry: MachineRejection) -> str:
    text = f"{entry.name}: {', '.join(entry.codes)}"
    if LIVENESS_EXPIRED in entry.codes and entry.last_seen_at is not None:
        text += f" (last seen {_instant(entry.last_seen_at)})"
    return text + (" " + " ".join(entry.recovery) if entry.recovery else "")


def describe_machine_rejections(rejections: Sequence[MachineRejection]) -> list[str]:
    """One clause per live machine, then one count for all offline ones."""
    offline = [entry for entry in rejections if entry.offline]
    clauses = [_machine_clause(entry) for entry in rejections if not entry.offline]
    if offline:
        newest = max(entry.last_seen_at for entry in offline if entry.last_seen_at)
        noun = "machine" if len(offline) == 1 else "machines"
        clauses.append(
            f"{len(offline)} {noun} offline (newest last seen {_instant(newest)})"
        )
    return clauses


def ineligibility_clauses(snapshot: Any) -> list[str]:
    """Every reason a snapshot or preview found no relay, per machine.

    Codes no machine carries (``relay_absent``, an access denial) and
    rejection details still appear once, after the machine clauses.
    """
    rejections = snapshot.machine_rejections
    attributed = {code for entry in rejections for code in entry.codes}
    leftover = [code for code in snapshot.rejection_codes if code not in attributed]
    parts = [
        *describe_machine_rejections(rejections),
        *leftover,
        *snapshot.rejection_details,
    ]
    return list(dict.fromkeys(str(part) for part in parts if part))


def ineligible_reason(snapshot: Any, surface: str, denials: dict[str, str]) -> str:
    """Why no machine could take ``surface``, one clause per machine."""
    parts = ineligibility_clauses(snapshot)
    parts.extend(f"{machine}: {why}" for machine, why in sorted(denials.items()))
    detail = "; ".join(dict.fromkeys(parts))
    return f"no usable machine offers {surface}" + (f" ({detail})" if detail else "")


__all__ = [
    "LIVENESS_EXPIRED",
    "MachineRejection",
    "OFFLINE_AFTER",
    "describe_machine_rejections",
    "ineligibility_clauses",
    "ineligible_reason",
    "merge_machine_rejections",
    "rejection_from_row",
]
