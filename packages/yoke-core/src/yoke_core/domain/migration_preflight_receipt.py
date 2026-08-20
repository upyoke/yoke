"""What proves a migration history entry was rehearsed against the fleet.

The fleet preflight answers the one question a migration entry raises: does it
still apply to the databases that are behind it? Answering it well is worth
nothing if a release can ship without asking. This module is the record that
the question was asked and the predicate a release gate reads to find out.

A receipt names an environment and the history entries covered when the
rehearsal passed. It exists only on a pass, so a receipt cannot be produced by
a run that failed, and the gate needs no verdict field to interpret.

**Coverage is a union over receipts, not the newest one.** A release carries
its whole history, so demanding that one receipt cover all of it would mean
re-rehearsing every entry ever written on every release — minutes per release
to re-prove entries the fleet applied long ago. Taking the union instead makes
the obligation exactly what the risk is: an entry must be rehearsed once for an
environment before a build carrying it ships there, and never again.

**Coverage is per environment.** Each environment is a different fleet at a
different ledger position, and an entry that applies cleanly to one says
nothing about another. A rehearsal of one environment is not evidence for
another.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

#: Emitted by a passing fleet preflight; read by the pre-tag release gate.
EVENT_NAME = "FleetMigrationPreflightPassed"
EVENT_KIND = "system"
EVENT_TYPE = "system"

#: Must be a member of ``events_crud.VALID_SOURCE_TYPES`` — the emit surface
#: rejects anything else, and a rejected receipt means a passing rehearsal the
#: gate cannot see. The preflight is a script, so that is what it declares;
#: naming the tool here instead is what an emit refusal looks like in advance.
SOURCE_TYPE = "script"

ENVIRONMENT_KEY = "environment"
ENTRIES_KEY = "entries"
PRODUCT_SHA_KEY = "product_sha"
ENGINE_ARTIFACT_KEY = "engine_artifact"

#: Suffix on the admin connection the preflight runs against. The connection
#: names a cluster; a receipt names the environment a release targets, and
#: both use the environment's registered name, so the two vocabularies are
#: one suffix apart.
_ADMIN_SUFFIX = "-db-admin"


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


def receipt_context(
    environment: str,
    product_sha: str,
    entries: Sequence[str],
    *,
    engine_artifact: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """The event context a passing rehearsal records."""
    context = {
        ENVIRONMENT_KEY: target_environment_for_admin_env(environment),
        PRODUCT_SHA_KEY: product_sha.strip(),
        # Sorted so two receipts covering the same entries are comparable by
        # eye in an audit listing, where the emission order is meaningless.
        ENTRIES_KEY: sorted({e.strip() for e in entries if e.strip()}),
    }
    if engine_artifact:
        context[ENGINE_ARTIFACT_KEY] = dict(engine_artifact)
    return context


def _context_of(row: Mapping[str, Any]) -> Mapping[str, Any]:
    """The context carried by one queried event row, or an empty mapping.

    The query surface returns the envelope as a JSON string, and the context
    lives inside it. A row this cannot read is not evidence, so it yields
    nothing rather than raising — one malformed row must not make an otherwise
    answerable question unanswerable.
    """
    envelope: Any = row.get("envelope")
    if isinstance(envelope, str):
        try:
            envelope = json.loads(envelope)
        except (TypeError, ValueError):
            return {}
    if not isinstance(envelope, Mapping):
        return {}
    context = envelope.get("context")
    if not isinstance(context, Mapping):
        return {}
    # The emit surface nests a supplied context under `detail`. Descend only
    # when the receipt's own keys are not already at this level, so a reader
    # written against the stored shape keeps working if that wrapping ever
    # stops — and an unwrapped receipt is never mistaken for a wrapped one.
    if ENVIRONMENT_KEY not in context:
        detail = context.get("detail")
        if isinstance(detail, Mapping):
            return detail
    return context


def covered_entries(rows: Iterable[Mapping[str, Any]], environment: str) -> frozenset:
    """Every history entry some passing receipt covers for one environment."""
    wanted = target_environment_for_admin_env(environment)
    covered = set()
    for row in rows:
        context = _context_of(row)
        if context.get(ENVIRONMENT_KEY) != wanted:
            continue
        entries = context.get(ENTRIES_KEY)
        # A JSON round-trip always yields a list; a bare string would otherwise
        # be iterated one character at a time into nonsense coverage.
        if isinstance(entries, (list, tuple)):
            covered.update(str(e) for e in entries)
    return frozenset(covered)


def uncovered(
    history: Sequence[str], rows: Iterable[Mapping[str, Any]], environment: str
) -> Tuple[str, ...]:
    """History entries no passing receipt covers, in history order."""
    covered = covered_entries(rows, environment)
    return tuple(name for name in history if name not in covered)


#: Registered environments a Yoke hosted release can target. Coverage is
#: per environment, so a receipt for one is not evidence for another.
RELEASE_ENVIRONMENTS = ("stage", "prod")

#: Project-generic unblock recipe. Callers that own a fleet adapter (for
#: example Yoke's release gate) inject that recipe via ``rehearse_command``;
#: the default must not name any project's source-dev path.
_DEFAULT_REHEARSE_COMMAND = (
    "yoke migration rehearse <item>  # see --help; use the project-owned "
    "fleet binding for fleet coverage before release"
)


def refusal_message(
    environment: str,
    missing: Sequence[str],
    *,
    product_sha: str = "",
    rehearse_command: str = "",
) -> str:
    """Why this release stops, and the one command that unblocks it.

    ``rehearse_command`` is the project-owned fleet recipe when a caller
    has one. Empty keeps the message project-generic so shared domain code
    never teaches a single project's source-dev adapter.
    """
    listed = ", ".join(missing)
    build = f" at {product_sha}" if product_sha.strip() else ""
    command = rehearse_command.strip() or _DEFAULT_REHEARSE_COMMAND
    return (
        f"this build{build} carries {len(missing)} migration history "
        f"entr{'y' if len(missing) == 1 else 'ies'} no passing fleet preflight "
        f"has covered for {target_environment_for_admin_env(environment)}: "
        f"{listed}. Receipts are per environment — a receipt for one is not "
        "coverage for another. An entry exists for the databases that are "
        "behind it, and nothing here has yet run it against one. Rehearse "
        f"the fleet, then re-run this release:\n  {command}"
    )


def coverage_by_environment(
    history: Sequence[str],
    rows: Iterable[Mapping[str, Any]],
    environments: Sequence[str] = RELEASE_ENVIRONMENTS,
) -> Dict[str, Tuple[str, ...]]:
    """Uncovered entries for each environment, in history order."""
    return {
        target_environment_for_admin_env(env): uncovered(history, rows, env)
        for env in environments
    }


def release_refusal_message(
    target_environment: str,
    missing_by_environment: Mapping[str, Sequence[str]],
    *,
    product_sha: str = "",
    rehearse_commands: Mapping[str, str] | None = None,
    engine_wheel_source: str = "",
) -> str:
    """Refuse, naming every environment still missing a receipt.

    The release still fails because *target_environment* is uncovered.
    Sibling environments are listed in the same message so the second gap
    is not discovered by a repeat attempt.
    """
    target = target_environment_for_admin_env(target_environment)
    commands = rehearse_commands or {}
    parts: list[str] = []
    target_missing = tuple(missing_by_environment.get(target) or ())
    parts.append(
        refusal_message(
            target,
            target_missing,
            product_sha=product_sha,
            rehearse_command=commands.get(target, ""),
        )
    )
    others = [
        (env, tuple(missing))
        for env, missing in missing_by_environment.items()
        if target_environment_for_admin_env(env) != target and missing
    ]
    if others:
        extra = "; ".join(
            f"{env}: {', '.join(missing)}" for env, missing in others
        )
        parts.append(
            "Also uncovered (receipts are per environment, so these are "
            f"separate gaps): {extra}."
        )
        for env, _missing in others:
            command = commands.get(env, "").strip()
            if command:
                parts.append(f"  {command}")
    covered = [
        env
        for env in missing_by_environment
        if target_environment_for_admin_env(env) != target
        and not missing_by_environment[env]
    ]
    if covered:
        named = ", ".join(target_environment_for_admin_env(env) for env in covered)
        parts.append(
            f"Covered for {named}; that evidence does not transfer."
        )
    if engine_wheel_source.strip():
        parts.append(engine_wheel_source.strip())
    return "\n".join(parts)


def unreadable_message(environment: str, reason: str) -> str:
    """Refuse when the receipt store could not be read at all.

    Distinguished from having found no receipt on purpose. Those are different
    facts — one says the release is unrehearsed, the other says this gate does
    not know — and reporting an unanswered question as a pass is the exact
    inversion that lets an unrehearsed build ship.
    """
    return (
        "could not read fleet preflight receipts for "
        f"{target_environment_for_admin_env(environment)}, so whether this "
        f"build was rehearsed is unknown rather than answered: {reason}. "
        "Refusing, because a gate that passes when it cannot check is not a "
        "gate."
    )
