"""What proves a fleet rehearsal covered the schema this release would ship.

The fleet preflight answers two questions a release raises: do pending
history entries still apply to the databases behind them, and does this
build's additive schema shape converge on those same aged copies? Answering
either well is worth nothing if a release can ship without asking. This
module is the record that the questions were asked and the predicate a
release gate reads to find out.

A receipt names the history entries covered and the schema-shape digest of
the sources that emit boot-converge DDL, and it is stored on the environment
whose fleet was rehearsed. It is written only on a pass, so a receipt cannot
be produced by a run that failed, and the gate needs no verdict field to
interpret.

**The store is the environment's own settings document, not telemetry.** A
rehearsal is release authority for one environment, so it lives beside the
other per-environment release authority under ``release.fleet_rehearsal``,
written and read through the registered environment-settings surfaces. A
telemetry record expires; a release that shipped because its evidence aged
out is the failure this store exists to prevent.

**Coverage is a union over rehearsals, not the newest one.** A release
carries its whole history, so demanding that one rehearsal cover all of it
would mean re-rehearsing every entry ever written on every release — minutes
per release to re-prove entries the fleet applied long ago. The same union
applies to schema-shape digests: a digest must be rehearsed once per
environment, and never again until the shape changes. Coverage keys
accumulate in the document, so the union is what the store already is.

**Coverage is per environment.** Each environment is a different fleet at a
different ledger position, and an entry that applies cleanly to one says
nothing about another. A rehearsal of one environment is not evidence for
another, and here that is structural: coverage read for one environment can
only ever come from that environment's own row.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Sequence, Tuple

#: Namespace inside ``environments.settings`` owning fleet rehearsal coverage.
SETTINGS_ROOT = "release.fleet_rehearsal"

#: One leaf per covered history entry; the value names the rehearsal run.
ENTRY_PREFIX = f"{SETTINGS_ROOT}.entry"

#: One leaf per covered schema-shape digest; the value names the run.
SCHEMA_SHAPE_PREFIX = f"{SETTINGS_ROOT}.schema_shape"

#: Identity of each rehearsal run the coverage leaves point at.
RUN_PREFIX = f"{SETTINGS_ROOT}.run"

#: Suffix on the admin connection the preflight runs against. The connection
#: names a cluster; a receipt names the environment a release targets, and
#: both use the environment's registered name, so the two vocabularies are
#: one suffix apart.
_ADMIN_SUFFIX = "-db-admin"


class ReceiptPathError(ValueError):
    """A coverage key cannot be addressed as one settings leaf."""


def target_environment_for_admin_env(admin_env: str) -> str:
    """The environment name an admin connection rehearses."""
    name = admin_env.strip()
    if name.endswith(_ADMIN_SUFFIX):
        name = name[: -len(_ADMIN_SUFFIX)]
    return name


def admin_connection_for_environment(environment: str) -> str:
    """The admin connection name a fleet adapter runs against for *environment*."""
    admin_env = environment.strip()
    if admin_env.endswith(_ADMIN_SUFFIX):
        return admin_env
    return f"{admin_env}{_ADMIN_SUFFIX}"


def rehearsed_build_description(
    engine_artifact: Mapping[str, Any] | None,
) -> str:
    """Plain-language identity of the engine a receipt rehearsed."""
    if not engine_artifact:
        return "unspecified engine"
    kind = str(engine_artifact.get("kind") or "").strip()
    name = str(engine_artifact.get("name") or "").strip()
    sha = str(engine_artifact.get("sha256") or "").strip()
    origin = str(engine_artifact.get("schema_origin") or "").strip()
    if kind == "wheel":
        digest = f" sha256:{sha}" if sha else ""
        return f"release wheel {name or 'unnamed.whl'}{digest}"
    if kind == "ambient":
        origin_note = f" schema={origin}" if origin else ""
        return f"source-tree engine{origin_note}"
    return f"engine kind={kind or 'unknown'} name={name or 'unknown'}"


def _leaf_segment(value: str, *, what: str) -> str:
    """One settings key segment, or a refusal naming why it is not one.

    Settings paths split on ``.``, so a segment carrying one would silently
    address a nested key instead of the coverage leaf the caller meant —
    writing coverage nothing reads and reading coverage nothing wrote.
    """
    text = str(value or "").strip()
    if not text:
        raise ReceiptPathError(f"a fleet rehearsal {what} cannot be empty")
    if "." in text:
        raise ReceiptPathError(
            f"a fleet rehearsal {what} cannot contain '.': {text!r} would "
            "address nested settings keys instead of one coverage leaf"
        )
    return text


def entry_coverage_path(entry: str) -> str:
    """The settings leaf recording that one history entry was rehearsed."""
    return f"{ENTRY_PREFIX}.{_leaf_segment(entry, what='history entry name')}"


def schema_shape_coverage_path(digest: str) -> str:
    """The settings leaf recording that one schema-shape digest was rehearsed."""
    return f"{SCHEMA_SHAPE_PREFIX}.{_leaf_segment(digest, what='schema-shape digest')}"


def coverage_paths(
    history: Sequence[str], schema_shape_digest: str = ""
) -> Tuple[str, ...]:
    """Every leaf a gate must read to answer coverage in one request."""
    paths = [
        entry_coverage_path(name) for name in history if str(name or "").strip()
    ]
    digest = str(schema_shape_digest or "").strip()
    if digest:
        paths.append(schema_shape_coverage_path(digest))
    return tuple(dict.fromkeys(paths))


def _is_recorded(value: Any) -> bool:
    """True when a read leaf carries a rehearsal identity rather than nothing.

    An absent leaf reads back as ``None``. Only a non-empty string is
    coverage, so a blanked or placeholder value is uncovered rather than
    quietly passing.
    """
    return isinstance(value, str) and bool(value.strip())


def covered_entries(
    values: Mapping[str, Any], history: Sequence[str]
) -> frozenset:
    """Every history entry this environment's coverage document records."""
    covered = set()
    for name in history:
        text = str(name or "").strip()
        if not text:
            continue
        try:
            path = entry_coverage_path(text)
        except ReceiptPathError:
            continue
        if _is_recorded(values.get(path)):
            covered.add(text)
    return frozenset(covered)


def uncovered(
    history: Sequence[str], values: Mapping[str, Any]
) -> Tuple[str, ...]:
    """History entries no rehearsal covers here, in history order."""
    covered = covered_entries(values, history)
    return tuple(name for name in history if name not in covered)


def uncovered_schema_shape(
    digest: str, values: Mapping[str, Any]
) -> Tuple[str, ...]:
    """The current digest when no rehearsal covers it here, else empty."""
    wanted = str(digest or "").strip()
    if not wanted:
        return ("",)
    if _is_recorded(values.get(schema_shape_coverage_path(wanted))):
        return ()
    return (wanted,)


def receipt_id(moment: datetime | None = None) -> str:
    """Identity of one rehearsal run: sortable, and a legal settings segment."""
    stamped = (moment or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return stamped.strftime("%Y%m%dT%H%M%SZ")


def receipt_assignments(
    product_sha: str,
    entries: Sequence[str],
    *,
    engine_artifact: Mapping[str, Any] | None = None,
    schema_shape_digest: str = "",
    database_count: int | None = None,
    moment: datetime | None = None,
) -> Tuple[str, Dict[str, Any]]:
    """The run identity and settings assignments one passing rehearsal writes."""
    stamped = (moment or datetime.now(timezone.utc)).astimezone(timezone.utc)
    run = receipt_id(stamped)
    digest = str(schema_shape_digest or "").strip()
    assignments: Dict[str, Any] = {
        f"{RUN_PREFIX}.{run}.product_sha": str(product_sha or "").strip(),
        f"{RUN_PREFIX}.{run}.engine": rehearsed_build_description(engine_artifact),
        f"{RUN_PREFIX}.{run}.rehearsed_at": stamped.strftime("%Y-%m-%dT%H:%M:%SZ"),
        f"{RUN_PREFIX}.{run}.schema_shape": digest,
    }
    if database_count is not None:
        assignments[f"{RUN_PREFIX}.{run}.databases"] = int(database_count)
    # Sorted so two rehearsals covering the same entries write comparable
    # assignment sets, where the emission order is meaningless.
    for entry in sorted({str(e or "").strip() for e in entries} - {""}):
        assignments[entry_coverage_path(entry)] = run
    if digest:
        assignments[schema_shape_coverage_path(digest)] = run
    return run, assignments


#: Registered environments a Yoke hosted release can target. Coverage is
#: per environment, so a receipt for one is not evidence for another.
RELEASE_ENVIRONMENTS = ("stage", "prod")


def coverage_by_environment(
    history: Sequence[str],
    values_by_environment: Mapping[str, Mapping[str, Any]],
    environments: Sequence[str] = RELEASE_ENVIRONMENTS,
) -> Dict[str, Tuple[str, ...]]:
    """Uncovered entries for each environment, in history order."""
    coverage: Dict[str, Tuple[str, ...]] = {}
    for env in environments:
        name = target_environment_for_admin_env(env)
        coverage[name] = uncovered(history, values_by_environment.get(name) or {})
    return coverage
