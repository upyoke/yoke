"""Read back the turn records the control plane asked this machine about.

The control plane names the sessions whose wake is stuck — it can see the
recorded skip but not the native's own turn record, which lives on this
machine. This is the other half: read each named session's record through
its surface's reader and report the ones whose turn is already over.

Which surfaces have a record is not decided here. Each harness family
declares it in ``yoke_contracts.harness_turn_record_capability``, and the
reader table below is derived from that declaration — so the contract, the
rendered manifest, the control plane's probe set, and this table can never
disagree about which surfaces are readable. Codex is currently the only
family that declares one; Claude and Cursor declare, with their evidence,
that their turn end fires its hook and so needs no record.

A family that declares a record but binds no reader here fails at import
rather than at the poll: the two halves ship together or the machine says
so, because a relay that quietly reads nothing is indistinguishable from
one whose read found nothing.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable, Mapping

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.harness_turn_record_capability import (
    HARNESS_TURN_RECORD_CAPABILITIES,
)
from yoke_contracts.session_control.function_ids import RELAY_TURN_END_FUNCTION_ID
from yoke_contracts.session_control.native_turn_end import RelayTurnEndProbe
from yoke_harness.session_relay_codex_turn_record import (
    ObservedTurnEnd,
    error_terminal_turn,
)
from yoke_harness.session_relay_report_delivery import RELAY_REPORT_TIMEOUT_SECONDS


_LOGGER = logging.getLogger(__name__)

TurnRecordReader = Callable[[str], ObservedTurnEnd | None]

#: The reader implementation for each harness family that declares a record.
#: Keyed by harness family rather than by surface, because the surface the
#: reader is verified against is the capability's fact to state.
_READERS_BY_HARNESS: dict[str, TurnRecordReader] = {
    "codex": error_terminal_turn,
}


def _readers_by_surface() -> dict[str, TurnRecordReader]:
    """Bind each declared-readable surface to its reader, or refuse to load."""
    readers: dict[str, TurnRecordReader] = {}
    for harness_id, capability in HARNESS_TURN_RECORD_CAPABILITIES.items():
        if capability.turn_record != "readable":
            continue
        reader = _READERS_BY_HARNESS.get(harness_id)
        if reader is None:
            raise RuntimeError(
                f"harness {harness_id!r} declares turn_record='readable' in "
                "yoke_contracts.harness_turn_record_capability but this "
                "module binds no reader for it. Add the reader to "
                "_READERS_BY_HARNESS, or change the capability to 'none' "
                "with the evidence for why no reader is needed."
            )
        readers[capability.verified_on_surface] = reader
    return readers


#: One reader per surface whose native ends a turn with no hook to say so.
TURN_RECORD_READERS: dict[str, TurnRecordReader] = _readers_by_surface()


def observed_turn_ends(
    probes: Iterable[Mapping[str, Any]],
) -> tuple[ObservedTurnEnd, ...]:
    """Read each named session's turn record and keep the ended ones."""
    observed: list[ObservedTurnEnd] = []
    for raw in probes:
        try:
            probe = RelayTurnEndProbe.model_validate(dict(raw))
        except (TypeError, ValueError):
            continue
        reader = TURN_RECORD_READERS.get(probe.executor_surface)
        if reader is None:
            _LOGGER.debug(
                "no turn-record reader for surface %s", probe.executor_surface
            )
            continue
        entry = reader(probe.session_id)
        if entry is not None:
            observed.append(entry)
    return tuple(observed)


def report_native_turn_ends(
    dispatcher: Callable[..., Any],
    inventory: Any,
    probes: Iterable[Mapping[str, Any]] | None,
    *,
    timeout_s: int = RELAY_REPORT_TIMEOUT_SECONDS,
) -> tuple[str, ...]:
    """Report the named sessions whose turn already ended; return those fixed.

    Nothing happens without targets, and nothing is sent when every target's
    turn is still in flight — the common case for a session that is simply
    thinking. A server that does not serve this function yet answers with a
    typed error, which is logged and skipped so the poll it rides on keeps
    working; the next poll re-derives the same targets.
    """
    observed = observed_turn_ends(probes or ())
    if not observed:
        return ()
    response = dispatcher(
        function_id=RELAY_TURN_END_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={
            "relay_id": inventory.relay_id,
            "machine_id": inventory.machine_id,
            "projects": list(inventory.project_ids),
            "turn_ends": [
                {
                    "session_id": entry.session_id,
                    "observed_at": entry.observed_at,
                    "evidence": entry.evidence,
                }
                for entry in observed
            ],
        },
        timeout_s=timeout_s,
    )
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        _LOGGER.warning(
            "relay turn-end report refused (%s): %s",
            getattr(error, "code", "relay_turn_end_failed"),
            getattr(error, "message", ""),
        )
        return ()
    result = getattr(response, "result", None) or {}
    return tuple(str(session_id) for session_id in result.get("reclassified") or [])


__all__ = [
    "TURN_RECORD_READERS",
    "observed_turn_ends",
    "report_native_turn_ends",
]
