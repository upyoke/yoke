"""Rehearse a release the fleet receipts do not yet cover.

Every GitHub workflow a deployment run dispatches is a release of the
databases of each project it ships: the run's own project at its release
commit, and each project a stage binds through ``input_bindings`` at the
commit the run recorded for it (``deploy_pipeline_fleet_rehearsal_sources``).
So before it dispatches, the fleet each shipped project's models declare in
``migration_fleet`` is checked against what that project's commit carries,
once per project, model and target environment. A model whose fleet is ``none`` is skipped with its declared
reason; a model that declares no fleet at all refuses the dispatch with the
declaration recipe, because an undeclared fleet and an empty one are
different facts.

Coverage is decided from what the release commit carries: its ordered
migration history entries and its boot-converge schema shape. An entry that
transforms rows without touching a table, column or index moves no schema
shape, so a shape-only question answers "covered" for precisely the entries a
rehearsal exists to catch — the ones that must be idempotent against their own
output and must write through their readers' canonical serializer. Asking both
questions makes an unrehearsed entry visible the way an unrehearsed shape
already was.

A receipt is stale for an environment when that project environment's
coverage document does not record something this release commit carries: any
history entry name, or the schema-shape digest. It is not stale because the
shape moved, and it does not age out — coverage is the union the store
accumulates, so entries the fleet rehearsed on an earlier release stay covered
and are not rehearsed again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from yoke_core.domain import deploy_pipeline_environment
from yoke_core.domain import deploy_pipeline_fleet_release_source as release_source
from yoke_core.domain import deploy_pipeline_fleet_rehearsal_sources as sources
from yoke_core.domain import migration_model_fleet as fleets
from yoke_core.domain import migration_preflight_receipt as receipt
from yoke_core.domain.migration_model_fleet_read import read_declared
from yoke_core.domain.migration_preflight_receipt_store import read_coverage
from yoke_core.domain.schema_shape_source import SchemaShapeSourceError

DeclaredFleet = Tuple[str, Mapping[str, Any], Mapping[str, Any]]


def ensure_before_dispatch(
    bound_inputs: Mapping[str, str],
    *,
    project: str,
    environment: str,
    repository: str,
    release_lineage: str,
    input_bindings: Optional[Mapping[str, Any]] = None,
) -> tuple[int, str]:
    """Rehearse and record what each project this dispatch ships is missing.

    ``bound_inputs`` is the commit the run holds for each bound input; the
    dispatch calls again with the prepared values when preparation re-bound
    one, and covered projects then skip.
    """
    bound, refusal = sources.bound_commits(input_bindings, bound_inputs)
    if refusal:
        return 1, refusal
    for source_project in sources.shipped_projects(project, bound):
        due, refusal = _declared_fleets(source_project)
        if refusal:
            return 1, refusal
        if not due:
            continue
        if not environment.strip():
            return 1, (
                f"release fleet rehearsal for project {source_project!r} "
                "requires a target environment"
            )
        source, error = sources.resolve_source(
            source_project,
            project=project,
            repository=repository,
            release_lineage=release_lineage,
            bound=bound,
        )
        if error or source is None:
            return 1, error
        for model_name, model, fleet in due:
            rc, diagnostic = _ensure_model(
                source.project,
                model_name,
                model,
                fleet,
                environment=environment,
                repository=source.repository,
                release_sha=source.release_sha,
            )
            if rc != 0:
                return rc, diagnostic
    return 0, ""


def _declared_fleets(project: str) -> tuple[List[DeclaredFleet], str]:
    """The project's models owing a fleet rehearsal, or why none can be named."""
    declared, unreadable = read_declared(project)
    if unreadable:
        return [], unreadable
    due: List[DeclaredFleet] = []
    for name, model in sorted(declared.models.items()):
        fleet = declared.fleet(name)
        if fleet is None:
            return [], fleets.undeclared_refusal(project, name)
        if fleet["kind"] == fleets.FLEET_NONE:
            print(
                f"  Fleet rehearsal: {project} model {name} declares no live "
                f"fleet ({fleet['reason']}); skipping"
            )
            continue
        due.append((name, model, fleet))
    return due, ""


def _ensure_model(
    project: str,
    model_name: str,
    model: Mapping[str, Any],
    fleet: Mapping[str, Any],
    *,
    environment: str,
    repository: str,
    release_sha: str,
) -> tuple[int, str]:
    modules_dir = str(
        ((model.get("runner") or {}).get("config") or {}).get("modules_dir") or ""
    )
    history, history_error = _release_history(repository, release_sha, modules_dir)
    if history_error:
        return 1, history_error
    try:
        schema_digest = fleets.schema_shape_digest_at(
            fleet, Path(repository or "."), release_sha
        )
    except SchemaShapeSourceError as exc:
        return 1, f"release schema digest unavailable: {exc}"

    values, read_error = _coverage(
        project, model_name, environment, history, schema_digest
    )
    if read_error:
        return 1, read_error
    target = f"{project}/{receipt.target_environment_for_admin_env(environment)}"
    missing = _uncovered_summary(model_name, history, schema_digest, values)
    if not missing:
        print(
            f"  Fleet rehearsal: covered for {target} model {model_name} "
            f"({len(history)} history entries, schema shape {schema_digest}); "
            "skipping"
        )
        return 0, ""

    receipt_environment = deploy_pipeline_environment.release_control_plane_env()
    if not receipt_environment or receipt_environment == "unbound":
        return 1, "release fleet rehearsal has no release control plane"
    print(
        f"  Fleet rehearsal: uncovered for {target} model {model_name} "
        f"({missing}); running before dispatch"
    )
    rc, refusal = _rehearse_release_source(
        project,
        model_name,
        fleet,
        environment=environment,
        repository=repository,
        release_sha=release_sha,
        modules_dir=modules_dir,
        history=history,
        schema_digest=schema_digest,
        receipt_environment=receipt_environment,
    )
    if refusal:
        return 1, refusal
    if rc != 0:
        return rc, (
            f"release fleet rehearsal of {target} model {model_name} failed "
            f"before dispatch (exit code {rc})"
        )

    values, read_error = _coverage(
        project, model_name, environment, history, schema_digest
    )
    if read_error:
        return 1, read_error
    still_missing = _uncovered_summary(model_name, history, schema_digest, values)
    if still_missing:
        return 1, (
            "fleet rehearsal passed but its receipt does not cover "
            f"{still_missing}; the receipt was not recorded where this gate reads"
        )
    print(
        f"  Fleet rehearsal: receipt covers this release for {target} model "
        f"{model_name} ({len(history)} history entries, schema shape "
        f"{schema_digest})"
    )
    return 0, ""


def _rehearse_release_source(
    project: str,
    model_name: str,
    fleet: Mapping[str, Any],
    *,
    environment: str,
    repository: str,
    release_sha: str,
    modules_dir: str,
    history: Sequence[str],
    schema_digest: str,
    receipt_environment: str,
) -> tuple[int, str]:
    """Run the preflight on exactly the release commit's code.

    Returns the preflight's exit code, or a refusal when the release
    commit's source cannot be the code that rehearses.
    """
    args = [
        "--project",
        project,
        "--model",
        model_name,
        environment,
        "--record-receipt",
        "--product-sha",
        release_sha,
        "--receipt-env",
        receipt_environment,
    ]
    try:
        if fleet["kind"] == fleets.FLEET_ENGINE_TENANTS:
            mismatch = release_source.engine_source_mismatch(
                repository, release_sha, modules_dir, history, schema_digest
            )
            if mismatch:
                return 1, f"release fleet rehearsal refused: {mismatch}"
            return _run_preflight(args), ""
        with release_source.release_checkout(repository, release_sha) as checkout:
            return _run_preflight(["--checkout", str(checkout), *args]), ""
    except release_source.ReleaseSourceError as exc:
        return 1, f"release fleet rehearsal refused: {exc}"


def _uncovered_summary(
    model: str,
    history: Sequence[str],
    schema_digest: str,
    values: Mapping[str, Any],
) -> str:
    """Name what this environment has never rehearsed; empty when nothing."""
    missing_entries = receipt.uncovered(model, history, values)
    missing_shape = receipt.uncovered_schema_shape(model, schema_digest, values)
    parts = []
    if missing_entries:
        parts.append(
            f"{len(missing_entries)} history "
            f"{'entry' if len(missing_entries) == 1 else 'entries'} "
            f"({', '.join(missing_entries)})"
        )
    if missing_shape:
        parts.append(f"schema shape {schema_digest}")
    return " and ".join(parts)


def _coverage(
    project: str,
    model: str,
    environment: str,
    history: Sequence[str],
    schema_digest: str,
) -> tuple[dict[str, Any], str]:
    """The environment's coverage for this release, or why it is unknown."""
    values, unreadable = read_coverage(
        project=project,
        environment=environment,
        paths=receipt.coverage_paths(model, history, schema_digest),
    )
    if unreadable:
        return {}, (
            f"could not read fleet rehearsal receipts of {project}/{environment} "
            f"model {model}: {unreadable}. Each shipped project needs an "
            f"environment named {environment!r} the release control plane can "
            "read; register it or grant the read, then re-drive the run"
        )
    return values, ""


def _release_history(
    repository: str, release_sha: str, modules_dir: str
) -> tuple[tuple[str, ...], str]:
    """Ordered history entry names the release commit carries, or why not.

    Read from the commit rather than from this process's installed history,
    for the same reason the schema-shape digest is: the control plane
    dispatching a release is not necessarily running the build it dispatches.
    The directory is the model's declared one, never a guess: a guess that
    missed it would report a release as carrying no entries — the same silent
    pass this gate exists to remove.
    """
    from yoke_core.domain.migration_history import HistoryError
    from yoke_core.domain.migration_history_integration import history_names_at_ref

    if not modules_dir:
        return (), "the declared migration model has no runner.config.modules_dir"
    try:
        return (
            history_names_at_ref(Path(repository or "."), release_sha, modules_dir),
            "",
        )
    except HistoryError as exc:
        return (), (
            f"migration history unavailable for release commit {release_sha}: {exc}"
        )


def _run_preflight(args: list[str]) -> int:
    """Execute through the same raw/progress watcher operators use directly."""
    from yoke_core.tools import watch_preflight

    from yoke_core.domain.deployment_start_timing import current_run_id

    run_id = current_run_id()
    identity = ["--run-id", run_id] if run_id else []
    return watch_preflight.main(["--", *identity, *args])


__all__ = ["ensure_before_dispatch"]
