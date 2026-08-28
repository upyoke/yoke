"""Registered-CLI driver for deterministic Fleet live acceptance."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
import time
from typing import Any

import runtime.api.tools.session_control_live_acceptance_client as acceptance_client
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
    AcceptanceMatrix,
    require_text,
)
from runtime.api.tools.session_control_live_acceptance_evidence import (
    native_wake_evidence,
    one_recipient,
    receipt_count,
    wait_for_ack,
)
from runtime.api.tools.session_control_live_acceptance_launch import create_and_bind
from runtime.api.tools import session_control_live_acceptance_protocol as protocol
from runtime.api.tools.session_control_live_acceptance_reporting import (
    FAILED_STATUS,
    failed_cell_report,
    passed_cell_report,
)
from runtime.api.tools.session_control_live_acceptance_route_selection import (
    resolve_route_selection,
)
from runtime.api.tools import session_control_live_acceptance_roster as roster


class LiveAcceptanceDriver:
    def __init__(
        self,
        client: acceptance_client.CommandClient,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.sleep = sleep
        self.monotonic = monotonic

    def run(
        self,
        matrix: AcceptanceMatrix,
        *,
        run_id: str,
        release_sha: str,
        server_build: str,
        engine_version: str,
        caller_session_id: str,
        timeout_seconds: float,
        poll_seconds: float,
        unsupported_observation_seconds: float,
        qualification: Any | None = None,
    ) -> dict[str, Any]:
        client, sleep, qualification = acceptance_client.bind_acceptance_owner(
            self.client, caller_session_id, self.sleep, self.monotonic, qualification
        )
        bound = LiveAcceptanceDriver(client, sleep=sleep, monotonic=self.monotonic)
        reports: list[dict[str, Any]] = []
        for cell in matrix.cells:
            try:
                reports.append(
                    bound._run_cell(
                        matrix.project,
                        cell,
                        run_id=run_id,
                        timeout=timeout_seconds,
                        poll=poll_seconds,
                        unsupported_observation=unsupported_observation_seconds,
                        qualification=qualification,
                    )
                )
            except AcceptanceContractError as exc:
                reports.append(
                    failed_cell_report(
                        cell, failure_code=exc.code, evidence=exc.evidence
                    )
                )
            except Exception:
                reports.append(
                    failed_cell_report(cell, failure_code="acceptance_internal_error")
                )
        passed = not any(report["status"] == FAILED_STATUS for report in reports)
        return {
            "schema": 1,
            "kind": "fleet_session_control_live_acceptance",
            "run_id": run_id,
            "release_sha": release_sha,
            "server_build": server_build,
            "engine_version": engine_version,
            "project": matrix.project,
            "caller_session_id": caller_session_id,
            "status": "passed" if passed else "failed",
            "cells": reports,
        }

    def _run_cell(
        self,
        project: str,
        cell: AcceptanceCell,
        *,
        run_id: str,
        timeout: float,
        poll: float,
        unsupported_observation: float,
        qualification: Any | None = None,
    ) -> dict[str, Any]:
        if cell.mode == "create":
            session_id, initial_id, launch, baseline = create_and_bind(
                self.client,
                project=project,
                cell=cell,
                run_id=run_id,
                timeout=timeout,
                poll=poll,
                sleep=self.sleep,
                monotonic=self.monotonic,
                validate_roster=partial(
                    roster.validated_stoppable_registration, self.client
                ),
            )
            initial_deduplicated = launch["deduplicated"]
        else:
            session_id = str(cell.session_id)
            allow_ended = roster.wakeable_identify_baseline(cell)
            baseline = roster.validated_registration(
                self.client,
                project=project,
                cell=cell,
                session_id=session_id,
                allow_ended=allow_ended,
            )
            grant = qualification and qualification.open(cell, "message_active")
            try:
                initial_id, initial_deduplicated = self._send_twice(
                    cell,
                    session_id,
                    key=f"fleet-live:{run_id}:{cell.acceptance_key}:initial",
                    phase="initial delivery",
                )
                initial = self._wait_ack(
                    cell,
                    session_id,
                    initial_id,
                    timeout=timeout,
                    poll=poll,
                    expected_route=resolve_route_selection(baseline, cell=cell)[0],
                    require_wake=baseline["liveness"] == "ended",
                )
            finally:
                if qualification is not None:
                    qualification.verify(grant)
            launch = None
        baseline_mode = roster.registration_mode(baseline, cell=cell)
        if cell.mode == "create":
            initial = self._wait_ack(
                cell, session_id, initial_id, timeout=timeout, poll=poll
            )
        candidate = qualification is not None and not cell.wake_supported
        waiting = roster.wait_for_waiting_registration(
            self.client,
            project=project,
            cell=cell,
            session_id=session_id,
            baseline_mode=baseline_mode,
            timeout=timeout,
            poll=poll,
            sleep=self.sleep,
            monotonic=self.monotonic,
            one_shot_private_wake_candidate=candidate and cell.route == "direct",
        )
        route, selection = resolve_route_selection(waiting, cell=cell)
        grant = (
            qualification.open(cell, "message_stopped", route) if candidate else None
        )
        try:
            wake_id, wake_deduplicated = self._send_twice(
                cell,
                session_id,
                key=f"fleet-live:{run_id}:{cell.acceptance_key}:wake",
                phase="stopped-session wake",
            )
            if route != "none":
                wake = self._wait_ack(
                    cell,
                    session_id,
                    wake_id,
                    timeout=timeout,
                    poll=poll,
                    expected_route=route,
                    require_wake=True,
                )
                wake_outcome = "acknowledged"
            else:
                self.sleep(unsupported_observation)
                wake = self._receipt(cell, session_id, wake_id)
                if (
                    wake["state"] != "pending"
                    or wake["injection_count"] != 0
                    or wake["acknowledged_at"]
                ):
                    raise AcceptanceContractError(
                        "unsupported_wake_not_pending", surface=cell.surface
                    )
                wake["native_wake"] = native_wake_evidence(
                    wake.pop("attempt_evidence"),
                    cell=cell,
                    session_id=session_id,
                    message_id=wake_id,
                    expected_route=route,
                )
                if wake["wake_attempt_count"] != wake["native_wake"]["attempt_count"]:
                    raise AcceptanceContractError(
                        "wake_attempt_count_mismatch", surface=cell.surface
                    )
                roster.wait_for_waiting_registration(
                    self.client,
                    project=project,
                    cell=cell,
                    session_id=session_id,
                    baseline_mode=baseline_mode,
                    timeout=timeout,
                    poll=poll,
                    sleep=self.sleep,
                    monotonic=self.monotonic,
                )
                wake_outcome = "expected_unsupported"
        finally:
            if qualification is not None:
                qualification.verify(grant)
        return passed_cell_report(
            cell,
            session_id=session_id,
            baseline=baseline,
            initial=initial,
            initial_deduplicated=initial_deduplicated,
            waiting=waiting,
            wake=wake,
            wake_outcome=wake_outcome,
            wake_deduplicated=wake_deduplicated,
            launch=launch,
            route_selection=selection,
        )

    def _send_twice(
        self,
        cell: AcceptanceCell,
        session_id: str,
        *,
        key: str,
        phase: str,
    ) -> tuple[str, bool]:
        preview = self.client.call(["say", "--preview", "--session", session_id])
        one_recipient(
            preview.get("recipients"), session_id=session_id, surface=cell.surface
        )
        body = (
            protocol.initial_delivery_message(surface=cell.surface, phase=phase)
            if phase == "initial delivery"
            else protocol.wake_delivery_message(surface=cell.surface, phase=phase)
        )
        args = ["say", "--stdin", "--session", session_id, "--idempotency-key", key]
        first = self.client.call(args, stdin=body)
        second = self.client.call(args, stdin=body)
        for result in (first, second):
            one_recipient(
                result.get("recipients"), session_id=session_id, surface=cell.surface
            )
        message_id = require_text(
            first.get("message_id"),
            code="message_id_missing",
            surface=cell.surface,
        )
        if (
            second.get("message_id") != message_id
            or second.get("deduplicated") is not True
        ):
            raise AcceptanceContractError("message_dedupe_failed", surface=cell.surface)
        return message_id, bool(second.get("deduplicated"))

    def _receipt(
        self, cell: AcceptanceCell, session_id: str, message_id: str
    ) -> dict[str, Any]:
        result = self.client.call(["messages", "get", message_id])
        message = result.get("message")
        if not isinstance(message, dict) or message.get("message_id") != message_id:
            raise AcceptanceContractError("receipt_missing", surface=cell.surface)
        row = one_recipient(
            message.get("recipients"), session_id=session_id, surface=cell.surface
        )
        return {
            "message_id": message_id,
            "state": str(row.get("state") or ""),
            "injection_count": receipt_count(
                row.get("injection_count"), surface=cell.surface
            ),
            "wake_attempt_count": receipt_count(
                row.get("wake_attempt_count"), surface=cell.surface
            ),
            "acknowledged_at": str(row.get("acknowledged_at") or ""),
            "last_wake_at": str(row.get("last_wake_at") or ""),
            "attempt_evidence": {
                key: message.get(key)
                for key in ("attempts", "attempt_count", "attempts_truncated")
            },
        }

    def _wait_ack(
        self,
        cell: AcceptanceCell,
        session_id: str,
        message_id: str,
        *,
        timeout: float,
        poll: float,
        expected_route: str = "direct",
        require_wake: bool = False,
    ) -> dict[str, Any]:
        return wait_for_ack(
            self._receipt,
            cell=cell,
            session_id=session_id,
            message_id=message_id,
            timeout=timeout,
            poll=poll,
            sleep=self.sleep,
            monotonic=self.monotonic,
            expected_route=expected_route,
            require_wake=require_wake,
        )
