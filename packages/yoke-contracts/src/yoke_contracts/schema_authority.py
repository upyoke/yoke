"""Whether this process may change the schema of the database it is pointed at.

Boot convergence exists so that a container brings its own database up to the
code it is about to run. That is the entire justification for letting a process
rewrite a schema without ceremony: the process *is* the build that will serve
the result, so "deployed" and "migrated" cannot disagree. A workstation pointed
at a shared control plane satisfies none of that — it serves nothing — yet it
runs the same code, so every command it issues carries the same reach.

One instance of that took a production fleet down. A laptop ran an ordinary
migration command against the prod control plane; the ordered history applied;
the database moved ahead of every build reading it, and every request touching
the renamed column failed until a release carrying the matching code shipped.
Nothing objected, because the guards in place asked which *command* was running
rather than which *database* it was pointed at — and the same connection was
still selected minutes later for a note-taking command that had no business
carrying migration authority.

So the refusal lives on the connection. A prod-flagged connection names a
database this machine administers but does not serve, and nothing run against
it may converge or apply. The process that legitimately converges says so with
:func:`serving_build_authority`, and so does a tool that deliberately converges
a database it owns outright — a restored archive, a throwaway fleet-rehearsal
copy. The declaration is the exemption, at the call site, rather than an
allowlist of module paths that rots as files move.

Local and self-hosted universes are untouched: their connections are not
prod-flagged, so they converge their own database exactly as they always have.
A machine with no config at all — a container, which resolves its DSN from its
own environment — is likewise unaffected.

A ContextVar rather than a process global, for the reason
:mod:`yoke_contracts.control_plane_locality` uses one: a server relays many
requests through one interpreter, and a process-wide flag set for one of them
leaks into every concurrent one.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Iterator, Optional

from yoke_contracts.machine_config import runtime as machine_config_runtime
from yoke_contracts.machine_config.schema import connection_is_prod
from yoke_contracts.migration_rehearsal_teaching import CONNECTION_READER


class SchemaAuthorityRefused(BaseException):
    """A schema change was attempted where this process holds no authority.

    Outside the ``Exception`` hierarchy on purpose, the way
    :class:`yoke_contracts.control_plane_locality.RemoteControlPlaneConnectionError`
    is. The failure this guard exists to prevent was silent, and the migration
    and convergence paths are full of blanket ``except Exception`` clauses that
    log and continue; an error any of them could swallow would be swallowed
    exactly where it matters most. A process that means to change this schema
    declares it with :func:`serving_build_authority` instead of catching this.
    """


#: Context-scoped declaration that this process owns the database it changes.
#: The default False means "undeclared", which is the right answer for every
#: ordinary command: only a build that serves the database, or a tool holding
#: a database of its own, has anything to declare.
_serving_build: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "serving_build_authority", default=False,
)


@contextmanager
def serving_build_authority() -> Iterator[None]:
    """Declare that this block changes a database this process owns.

    Two callers are entitled to it: a server converging the database it is
    about to serve, and a tool converging a database it created or restored
    for its own use. Both are making the same claim — that no other build is
    serving what this code is about to rewrite.
    """
    token = _serving_build.set(True)
    try:
        yield
    finally:
        _serving_build.reset(token)


def serving_build_authority_declared() -> bool:
    """Return whether this context declared authority over its database."""
    return _serving_build.get()


def prod_flagged_connection(explicit_env: Optional[str] = None) -> str:
    """Return the selected env's label when it is prod-flagged, else ``""``.

    Reads the explicit marker only. Inferring prod-ness from a label or a DSN
    would be guessing about the most consequential database an operator has,
    and any config problem answers "not prod" so this guard never becomes the
    reason an unrelated misconfiguration is reported.
    """
    try:
        env = machine_config_runtime.active_env(explicit_env=explicit_env)
        connection = machine_config_runtime.active_connection(explicit_env=explicit_env)
    except Exception:  # noqa: BLE001 - config problems surface where they are
        return ""
    return env if connection_is_prod(connection) else ""


def refuse_without_serving_build_authority(operation: str) -> None:
    """Raise when *operation* would change a schema this process does not serve.

    A no-op wherever the selected connection is not prod-flagged, which is
    every local universe, every self-hosted universe converging its own
    database, and every container.
    """
    if _serving_build.get():
        return
    env = prod_flagged_connection()
    if not env:
        return
    raise SchemaAuthorityRefused(
        f"{operation} refused on connection {env!r}: that connection is flagged "
        "prod, and this process is not the build that serves the database it "
        "names. Convergence belongs to the container running the release — "
        "deploy the build carrying this change and let its boot apply it. "
        "Rehearse against the model's validation surface instead. A tool that "
        "converges a database it owns outright declares that with "
        "yoke_contracts.schema_authority.serving_build_authority()."
    )


def refuse_on_prod_control_plane(operation: str) -> Optional[str]:
    """Return a refusal message when the selected control plane is prod, else None.

    Distinct from :func:`refuse_without_serving_build_authority` and
    deliberately not exemptible: rehearsal targets a disposable validation
    surface by definition, so pointing it at a production control plane is
    never the intent, whoever is running it.
    """
    env = prod_flagged_connection()
    if not env:
        return None
    return (
        f"{operation} refused on connection {env!r}: that connection is flagged "
        "prod. Rehearsal executes an unreleased migration and must target the "
        "model's disposable validation surface, never a production control "
        "plane. Rerun under a non-prod local-postgres or db-admin connection; "
        f"`{CONNECTION_READER}` names every registered connection with its "
        "transport and prod flag."
    )


__all__ = [
    "SchemaAuthorityRefused",
    "prod_flagged_connection",
    "refuse_on_prod_control_plane",
    "refuse_without_serving_build_authority",
    "serving_build_authority",
    "serving_build_authority_declared",
]
