"""What must happen the first time an upgraded engine serves this machine.

Upgrading Yoke replaces the code without touching anything the previous code
left behind, and two of those leftovers are load-bearing. The machine-local
universe keeps the schema the *old* engine created, so the new build reads
columns and tables that were never added. The project checkout keeps the
operating layer the old engine generated, so its skills and hooks teach the
previous release. Both showed up as unrelated-looking failures — a schema-drift
health check, a board rebuild that could not run, commands answering with a
refusal naming a release the operator had already replaced.

Neither is detected by asking what command is running. Both are answered by
asking what build last converged this machine, which is what the receipt beside
the machine config records. When the answer differs from the build running now,
this module converges the universe's schema (the local counterpart of a
container's boot converge) and names the project layer that is now behind,
offering the exact refresh rather than letting later commands refuse.

The engine owns the database mechanics
(:mod:`yoke_core.domain.local_universe_convergence`); this module owns the
machine-local bookkeeping and what the operator is told. The engine import is
dynamic on purpose — the client packages hold no static import authority over
the engine, and this runs only on the local-dispatch path where the engine is
already the thing about to serve.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Callable, Dict

from yoke_cli.config import machine_config

#: Machine-local receipt naming the build that last converged each universe.
#: Beside the machine config rather than inside it: this is bookkeeping the
#: client writes for itself, not operator-authored configuration.
RECEIPT_FILE_NAME = "engine-convergence.json"
RECEIPT_SCHEMA = 1

#: ``converge_for_serving`` outcomes.
STATUS_CONVERGED = "converged"
STATUS_CURRENT = "current"
STATUS_FOREIGN_UNIVERSE = "foreign_universe"


class LocalUniverseConvergenceError(RuntimeError):
    """The local universe could not be brought up to the running engine."""


def converge_for_serving(
    *,
    emit: Callable[[str], None] = lambda _line: None,
) -> Dict[str, Any]:
    """Converge this machine's own universe before the engine serves it.

    Returns a report naming the outcome. A universe this machine does not own
    is reported and left alone: a non-prod Postgres connection may perfectly
    well name a cluster somebody else's build is serving, and converging that
    one would move the schema out from under it.
    """
    identity = engine_identity()
    dsn = _ambient_dsn()
    convergence = importlib.import_module("yoke_core.domain.local_universe_convergence")
    if not dsn or not convergence.serves_own_universe(dsn):
        return {"status": STATUS_FOREIGN_UNIVERSE, "engine_identity": identity}
    receipt = _read_receipt()
    universes = receipt.get("universes")
    universes = dict(universes) if isinstance(universes, dict) else {}
    key = _universe_key(dsn)
    status = STATUS_CURRENT
    if not identity or universes.get(key) != identity:
        try:
            convergence.converge_serving_schema()
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # noqa: BLE001 - diagnosed and re-raised
            raise LocalUniverseConvergenceError(
                "the machine-local universe could not be brought up to the "
                f"running engine ({identity or 'unidentified build'}): {exc}. "
                "Start or repair the universe with `yoke onboard --local`, "
                "then retry. Yoke will not serve a database it could not "
                "converge."
            ) from exc
        status = STATUS_CONVERGED
        if identity:
            universes[key] = identity
            receipt["universes"] = universes
    offer, notified_root = _pending_operating_layer_offer(receipt, identity)
    if notified_root:
        notices = receipt.get("operating_layer_notices")
        notices = dict(notices) if isinstance(notices, dict) else {}
        notices[notified_root] = identity
        receipt["operating_layer_notices"] = notices
    if status == STATUS_CONVERGED or notified_root:
        _write_receipt(receipt)
    if offer:
        emit(offer)
    return {
        "status": status,
        "engine_identity": identity,
        "operating_layer_offer": offer,
    }


def engine_identity() -> str:
    """Name the engine build in front of this machine, or ``""`` when unknown.

    A released install is named by its wheel version. A source checkout carries
    no wheel metadata, so it is named by the commit it runs — the same identity
    the client already uses to relate a checkout to a server build. An
    unnamed build converges every time rather than claiming currency it cannot
    demonstrate; over-converging is idempotent, while a wrong "already current"
    is the exact silence this module exists to remove.
    """
    from yoke_contracts.engine_version import installed_engine_version
    from yoke_contracts.install_binding import source_checkout_root
    from yoke_cli.transport import source_build_skew

    version = installed_engine_version().strip()
    if version:
        return f"engine {version}"
    origin = _engine_module_origin()
    checkout = source_checkout_root(origin) if origin else None
    if checkout is None:
        return ""
    head = source_build_skew.head_commit(str(checkout))
    return f"source {head}" if head else ""


def receipt_path() -> Path:
    """The machine-local convergence receipt this client reads and writes."""
    return machine_config.yoke_home() / RECEIPT_FILE_NAME


def _engine_module_origin() -> str:
    """The engine package's file origin without importing the engine."""
    try:
        spec = importlib.util.find_spec("yoke_core")
    except (ImportError, ValueError):
        return ""
    return str(getattr(spec, "origin", "") or "") if spec else ""


def _ambient_dsn() -> str:
    """The Postgres address the engine would serve, or ``""`` when unresolved."""
    try:
        db_backend = importlib.import_module("yoke_core.domain.db_backend")
        return str(db_backend.resolve_pg_dsn() or "").strip()
    except Exception:  # noqa: BLE001 - an unresolvable address owns nothing
        return ""


def _universe_key(dsn: str) -> str:
    """A stable per-universe receipt key that stores no connection string.

    The local universe's DSN carries no password, but a receipt is a plain file
    beside the machine config and has no reason to hold an address at all.
    """
    return hashlib.sha256(dsn.encode("utf-8")).hexdigest()[:32]


def _read_receipt() -> Dict[str, Any]:
    """The stored receipt, or an empty one for any unreadable or foreign shape.

    An unreadable receipt reads as "nothing converged yet", so a corrupted or
    hand-edited file costs one redundant idempotent converge rather than
    stranding the universe behind its own engine.
    """
    try:
        payload = json.loads(receipt_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {"schema": RECEIPT_SCHEMA}
    if not isinstance(payload, dict) or payload.get("schema") != RECEIPT_SCHEMA:
        return {"schema": RECEIPT_SCHEMA}
    return dict(payload)


def _write_receipt(receipt: Dict[str, Any]) -> None:
    """Persist the receipt; an unwritable machine home only costs a re-converge."""
    payload = dict(receipt)
    payload["schema"] = RECEIPT_SCHEMA
    path = receipt_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return


def _pending_operating_layer_offer(
    receipt: Dict[str, Any],
    identity: str,
) -> tuple[str, str]:
    """The layer refresh to offer here, and the checkout it was offered for.

    Tracked per checkout rather than per machine because the operator's first
    command after an upgrade is not reliably inside a project: keying the
    notice to the checkout means each one is named the first time this build
    serves a command from it, instead of the offer being spent on whichever
    directory happened to be current. Both halves are empty when there is
    nothing to say, and an unnamed build says nothing at all — it cannot tell
    a second look from a first.
    """
    from yoke_cli.operating_layer_drift import (
        layer_refresh_advice,
        stale_installed_layer,
    )

    if not identity:
        return "", ""
    installed = stale_installed_layer(Path.cwd())
    if installed is None:
        return "", ""
    root = str(installed.receipt.project_root)
    notices = receipt.get("operating_layer_notices")
    notices = notices if isinstance(notices, dict) else {}
    if notices.get(root) == identity:
        return "", ""
    return layer_refresh_advice(installed), root


__all__ = [
    "LocalUniverseConvergenceError",
    "RECEIPT_FILE_NAME",
    "STATUS_CONVERGED",
    "STATUS_CURRENT",
    "STATUS_FOREIGN_UNIVERSE",
    "converge_for_serving",
    "engine_identity",
    "receipt_path",
]
