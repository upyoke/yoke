"""Rehearse a migration model's pending history against its live databases.

Run this before releasing a build that carries an unapplied history entry. It
answers the only question that matters about such an entry — does it still
apply to the databases that are behind? — by running it against a copy of
each of them, on the local embedded cluster, exactly as a booting server
would. The live databases are only read.

Which databases, and which boot sequence, is the model's declared ``fleet``
on the project's ``migration_model`` capability: the engine's own tenant
databases converged by the engine, or databases the project names converged
by the project's own boot command from its checkout. A model declaring no
fleet is refused with the declaration recipe; one declaring ``none`` has
nothing to rehearse.

A copy installing different extension versions than its source is not evidence
about that source, so each source's versions are pinned into its copy; a
version this machine's engine cannot install refuses before anything is dumped.

An engine tenant fleet is what the release must keep serving, which is
narrower than every engine-schema database on the cluster: the Platform
catalog, scratch databases a test run abandoned, and the validation database
governed migration rehearsal applies history into and leaves behind are all
owned by something other than a tenant, and the latter two have each failed a
release by being converged as one. Every candidate is rostered before it is
copied, naming whether it is a member and why, so the capture answers which
databases this rehearsed without a reader reconstructing the rule.

Ordinary pre-release rehearsal uses the source tree (no ``--engine-wheel``).
The release wheel is produced after tag allocation, so it cannot exist at
the only moment a receipt can be written. The wheel is built from the same
commit; rehearsing that commit's sources proves the history and schema-shape
the wheel will package. ``--engine-wheel`` pins an already-built artifact.

Usage::

    yoke watch preflight -- --project P [--model M] [--checkout PATH]
        <environment> [db ...]
        [--record-receipt [--product-sha SHA] [--receipt-env NAME]]
        [--engine-wheel PATH]

``--project`` names the project whose model is rehearsed; ``--model``
defaults to its ``default_model``. ``--checkout`` names the project checkout
a ``named_databases`` fleet converges from; it defaults to the checkout
registered for the project on this machine. The positional names the project's
registered environment whose fleet to rehearse. The paired admin connection
is that environment's ``release.admin_connection`` setting, not a name
suffix. ``--receipt-env`` names the control plane that records the receipt.
Naming databases limits the run to those, as a diagnostic only: a receipt
covers the model's whole declared fleet, so ``--record-receipt`` refuses a
narrowed run.

``--record-receipt`` records the pass in the control plane, which is what the
release gate reads before allocating a tag; a receipt covers exactly the
environment whose fleet was rehearsed, a release targeting an environment
requires that environment's receipt, and one environment's receipt never satisfies another.
The receipt names the history entries covered, the schema-shape digest of
the boot-converge sources in the selected engine, and whether that engine
was the source tree or a wheel. It is stored on that project environment's own
settings document under ``release.fleet_rehearsal.<model>``, so coverage outlives
telemetry retention and cannot be read for the wrong environment.
Receipts always write to the release-gate control plane.
The selected admin connection changes the covered fleet, not the receipt
plane. Receipts are recorded only on passing runs, so they cannot exist for
fleets this did not clear.

``--engine-wheel`` puts a named already-built artifact at the head of the
import path before any ``yoke_core`` module loads. Omit it for ordinary
pre-release rehearsal.

The watcher keeps output unbuffered, streams the per-database verdicts and
receipt, writes the sentinel consumed by ``yoke watch tail``, and preserves
the preflight exit code. Exits non-zero when any database fails, so a release
step can gate on it.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

from runtime.api.tools.preflight_engine_artifact import (
    EngineArtifactError,
    activate_engine_artifact as _activate_engine_artifact,
)


def _parse(args: List[str]) -> argparse.Namespace:
    """Separate the project, model, and receipt flags from the operands."""
    parser = argparse.ArgumentParser(prog="yoke watch preflight --", add_help=False)
    parser.add_argument("--project", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--checkout", default="")
    parser.add_argument("--record-receipt", action="store_true")
    parser.add_argument("--product-sha", default="")
    parser.add_argument("--receipt-env", default="")
    parser.add_argument("--engine-wheel", default="")
    parser.add_argument("operands", nargs="*")
    parsed, unknown = parser.parse_known_args(args)
    if unknown:
        raise ValueError(f"unrecognized arguments: {' '.join(unknown)}")
    return parsed


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        return 0 if args else 2

    try:
        parsed = _parse(args)
        engine_artifact = _activate_engine_artifact(parsed.engine_wheel)
    except (EngineArtifactError, ValueError) as exc:
        print(f"preflight arguments refused: {exc}", file=sys.stderr)
        return 2
    project, positional = parsed.project.strip(), parsed.operands
    if not project or not positional:
        print(
            "name the project and its registered environment whose fleet to "
            "rehearse: yoke watch preflight -- --project P <environment>",
            file=sys.stderr,
        )
        return 2
    record, product_sha = parsed.record_receipt, parsed.product_sha
    if record and positional[1:]:
        print(
            "--record-receipt records coverage for the model's whole declared "
            f"fleet, so it cannot follow a run narrowed to {positional[1:]}. "
            "Drop the database names to rehearse and record the whole fleet, "
            "or drop --record-receipt for a diagnostic run.",
            file=sys.stderr,
        )
        return 2
    from yoke_core.domain import migration_preflight_receipt as receipt
    from yoke_core.domain.migration_preflight_receipt_store import (
        read_declared_admin_connection,
    )
    from runtime.api.tools import fleet_rehearsal_receipt_write as receipt_write
    from runtime.api.tools import migration_fleet_selection

    covered_env = receipt.target_environment_for_admin_env(positional[0])
    target, unavailable = migration_fleet_selection.resolve(
        project,
        parsed.model.strip() or None,
        checkout=Path(parsed.checkout).expanduser() if parsed.checkout else None,
    )
    if target is None:
        print(unavailable, file=sys.stderr)
        return 2
    admin_env, admin_error = read_declared_admin_connection(
        project=project, environment=covered_env
    )
    if admin_error:
        print(admin_error, file=sys.stderr)
        return 2
    # Read before selecting admin readiness so the receipt remains explicitly
    # bound to the caller's control plane rather than the admin cluster.
    receipt_env = parsed.receipt_env or os.environ.get("YOKE_ENV", "")
    if record and not receipt_env:
        print(
            "--record-receipt needs a control-plane connection to write to, and "
            "YOKE_ENV is unset. Name one with --receipt-env.",
            file=sys.stderr,
        )
        return 2
    if record:
        release_gate_env = receipt_write.release_gate_receipt_env()
        if not release_gate_env:
            print(
                "--record-receipt could not resolve one prod release-gate "
                "authority from the configured connections; mark the owning "
                "connection with prod=true.",
                file=sys.stderr,
            )
            return 2
        if receipt_env != release_gate_env:
            print(
                "--record-receipt must write to the prod release-gate control "
                "plane. Retry: yoke watch preflight -- --project "
                f"{project} {covered_env} "
                "[db ...] --record-receipt --product-sha <sha> "
                f"--receipt-env {release_gate_env}",
                file=sys.stderr,
            )
            return 2

    from yoke_core.domain import (
        connected_env_tunnel_coordination,
        local_universe,
        migration_fleet_preflight,
    )
    from yoke_core.domain.connected_env_readiness import (
        SelectedPostgresError,
        activate_selected_postgres,
    )
    from yoke_core.tools.yoke_migration_fleet import database_dsn

    print(f"engine artifact: {engine_artifact.display()}")
    try:
        authority = activate_selected_postgres(admin_env)
    except SelectedPostgresError as exc:
        print(
            f"fleet rehearsal needs the local-postgres admin connection for "
            f"{covered_env}, which is {admin_env!r}. {exc} "
            f"Retry: yoke watch preflight -- --project {project} {covered_env}",
            file=sys.stderr,
        )
        return 2

    spec = local_universe.cluster_spec(
        bin_dir=local_universe.ensure_engine_binaries(lambda msg: print(f"  {msg}"))
    )

    def dsn_for(database: str) -> str:
        return database_dsn(authority.dsn, database)

    plan = target.plan
    print(f"project: {project} (migration model {target.model_name})")
    print(f"environment: {covered_env} (admin connection {admin_env})")
    print(f"rehearsal cluster: {spec.sock_dir}")
    # Enumerated after the identity lines so the roster the selector emits
    # reads as a fact about this fleet, not a stray preamble.
    databases = positional[1:] or target.databases(dsn_for)

    # The copies run for minutes through whatever path reaches the fleet. When
    # that path is a shared local forward, the lease is what stops another
    # process's readiness check from replacing it out from under a copy.
    lease_reason = f"fleet migration rehearsal of {covered_env}"
    with tempfile.TemporaryDirectory(prefix="yoke-migration-rehearsal-") as work:
        with connected_env_tunnel_coordination.use_lease_for_active_tunnel(
            lease_reason
        ):
            verdicts = migration_fleet_preflight.rehearse_fleet(
                dsn_for,
                databases=databases,
                plan=plan,
                spec=spec,
                work_dir=Path(work),
                source_environment=admin_env,
                emit=print,
            )

    failed = [v for v in verdicts if not v.passed]
    print("\n" + migration_fleet_preflight.format_fleet_summary(verdicts))
    if failed or not record:
        return 1 if failed else 0

    entries = plan.history
    from yoke_core.domain.schema_shape_source import SchemaShapeSourceError

    try:
        schema_digest = target.schema_shape_digest()
    except SchemaShapeSourceError as exc:
        print(
            "fleet rehearsal passed but its schema-shape digest could not be "
            f"computed, so no receipt was recorded: {exc}",
            file=sys.stderr,
        )
        return 1
    run, unwritten = receipt_write.record_receipt(
        project=project,
        model=target.model_name,
        receipt_env=receipt_env,
        environment=covered_env,
        product_sha=product_sha,
        entries=entries,
        engine_artifact=engine_artifact.evidence(),
        schema_shape_digest=schema_digest,
        database_count=len(verdicts),
    )
    if unwritten:
        # A pass nobody recorded reads to the operator as an unblocked release
        # and to the gate as an unrehearsed one. Failing here is what keeps
        # those two from disagreeing.
        print(
            f"fleet rehearsal passed but its receipt was not recorded on "
            f"{receipt_env}, so the release gate will still refuse: {unwritten}",
            file=sys.stderr,
        )
        return 1
    print(
        f"receipt recorded on {receipt_env} covering {project}/{covered_env} "
        f"as {run} "
        f"via {engine_artifact.display()}; {len(entries)} history entries "
        f"and schema-shape {schema_digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
