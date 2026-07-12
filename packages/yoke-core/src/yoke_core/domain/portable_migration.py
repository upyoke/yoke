"""Portable execution contract for governed migrations on engine fleets.

The ordinary migration runner owns control-plane project lookup, leases, and
the operator's two-unit command boundary.  A hosted tenant fleet has a
different control plane from every tenant target, so the platform owns those
fleet concerns while this module keeps the safety theorem and executable
migration logic public and single-sourced.

No function here resolves an ambient DSN.  Callers pass an already-authorized
connection for exactly one validation or live target.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.migration_apply_manifest import (
    MigrationManifestError,
    validate_manifest_payload,
)
from yoke_core.domain.migration_apply_verify import run_baseline_verify


_MODULE_NAMESPACE = "yoke_core.domain.migrations"
_SQL_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class PortableMigrationError(RuntimeError):
    """A portable manifest or packaged module is unsafe to execute."""

    def __init__(
        self,
        message: str,
        *,
        baseline_verification: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.baseline_verification = baseline_verification


@dataclass(frozen=True)
class PortableManifest:
    """Validated manifest plus the exact source-file digest."""

    raw_text: str
    sha256: str
    project: str
    profile: Mapping[str, Any]
    attestation: Mapping[str, Any]

    @property
    def module_identifiers(self) -> tuple[str, ...]:
        return tuple(str(value) for value in self.profile["migration_modules"])

    @property
    def affected_tables(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    str(surface["table"])
                    for surface in self.profile.get("affected_surfaces", [])
                    if surface.get("table")
                }
            )
        )


@dataclass(frozen=True)
class PortableApplyResult:
    """Secret-free evidence returned after apply and author invariants."""

    manifest_sha256: str
    modules: tuple[str, ...]
    pre_row_counts: Mapping[str, int]
    post_row_counts: Mapping[str, int]
    baseline_verification: Mapping[str, Any]


def parse_manifest_text(raw_text: str) -> PortableManifest:
    """Parse and validate one exact committed-manifest text payload."""

    if not isinstance(raw_text, str) or not raw_text.strip():
        raise PortableMigrationError("migration manifest text is empty")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise PortableMigrationError(f"cannot parse migration manifest: {exc}") from exc
    try:
        project, profile, attestation = validate_manifest_payload(payload)
    except MigrationManifestError as exc:
        raise PortableMigrationError(str(exc)) from exc
    return PortableManifest(
        raw_text=raw_text,
        sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        project=project,
        profile=profile,
        attestation=attestation,
    )


def load_packaged_modules(manifest: PortableManifest) -> tuple[ModuleType, ...]:
    """Resolve every declared slug from the installed engine wheel."""

    modules: list[ModuleType] = []
    for identifier in manifest.module_identifiers:
        dotted = f"{_MODULE_NAMESPACE}.{identifier}"
        try:
            module = importlib.import_module(dotted)
        except (ImportError, ModuleNotFoundError) as exc:
            raise PortableMigrationError(
                f"packaged migration module {identifier!r} is unavailable"
            ) from exc
        if not callable(getattr(module, "apply", None)):
            raise PortableMigrationError(
                f"packaged migration module {identifier!r} has no apply(conn)"
            )
        modules.append(module)
    return tuple(modules)


def row_counts(conn: Any, tables: tuple[str, ...]) -> dict[str, int]:
    """Return affected-table counts; table names came from validated slugs."""

    counts: dict[str, int] = {}
    for table in tables:
        if _SQL_IDENTIFIER.fullmatch(table) is None:
            raise PortableMigrationError(
                f"affected table {table!r} is not a bare SQL identifier"
            )
        try:
            row = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
            counts[table] = int(row[0]) if row is not None else -1
        except db_backend.operational_error_types(conn):
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001 — best-effort recovery for evidence
                pass
            counts[table] = -1
    return counts


def apply_manifest(conn: Any, manifest: PortableManifest) -> PortableApplyResult:
    """Apply packaged modules, commit, then run every author invariant.

    This deliberately matches the public live runner's commit-before-invariant
    order.  A caller must create and durably receipt its rollback backup before
    entering this function.
    """

    modules = load_packaged_modules(manifest)
    before = row_counts(conn, manifest.affected_tables)
    try:
        for module in modules:
            module.apply(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    baseline, baseline_error = run_baseline_verify(
        conn,
        list(manifest.affected_tables),
        bool(manifest.profile["count_preserving"]),
        dict(before),
    )
    invariant_failures: list[str] = []
    for module in modules:
        invariant = getattr(module, "invariants", None)
        if not callable(invariant):
            continue
        try:
            invariant(conn)
        except Exception as exc:  # noqa: BLE001 — author invariant is evidence
            invariant_failures.append(
                f"{module.__name__}.invariants raised {type(exc).__name__}: {exc}"
            )
    failures = ([baseline_error] if baseline_error else []) + invariant_failures
    if failures:
        raise PortableMigrationError(
            "; ".join(failures), baseline_verification=baseline
        )
    after = dict(baseline["post_row_counts"])
    return PortableApplyResult(
        manifest_sha256=manifest.sha256,
        modules=manifest.module_identifiers,
        pre_row_counts=before,
        post_row_counts=after,
        baseline_verification=baseline,
    )


__all__ = [
    "PortableApplyResult",
    "PortableManifest",
    "PortableMigrationError",
    "apply_manifest",
    "load_packaged_modules",
    "parse_manifest_text",
    "row_counts",
]
