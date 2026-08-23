"""Registered-CLI driver for deterministic Fleet live acceptance."""

from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any

from runtime.api.tools.session_control_live_acceptance_client import CommandClient
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
    AcceptanceMatrix,
    require_text,
)
from runtime.api.tools.session_control_live_acceptance_evidence import (
    one_recipient,
    receipt_count,
)
from runtime.api.tools.session_control_live_acceptance_launch import create_and_bind


class LiveAcceptanceDriver:
    def __init__(
        self,
        client: CommandClient,
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
        caller_session_id: str,
        timeout_seconds: float,
        poll_seconds: float,
        unsupported_observation_seconds: float,
    ) -> dict[str, Any]:
        reports: list[dict[str, Any]] = []
        for cell in matrix.cells:
            try:
                reports.append(
                    self._run_cell(
                        matrix.project,
                        cell,
                        run_id=run_id,
                        timeout=timeout_seconds,
                        poll=poll_seconds,
                        unsupported_observation=unsupported_observation_seconds,
                    )
                )
            except AcceptanceContractError as exc:
                reports.append(
                    {
                        "surface": cell.surface,
                        "expected_version": cell.expected_version,
                        "mode": cell.mode,
                        "status": "failed",
                        "failure_code": exc.code,
                    }
                )
            except Exception:
                reports.append(
                    {
                        "surface": cell.surface,
                        "expected_version": cell.expected_version,
                        "mode": cell.mode,
                        "status": "failed",
                        "failure_code": "acceptance_internal_error",
                    }
                )
        passed = all(report["status"] == "passed" for report in reports)
        return {
            "schema": 1,
            "kind": "fleet_session_control_live_acceptance",
            "run_id": run_id,
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
    ) -> dict[str, Any]:
        if cell.mode == "create":
            session_id, initial_message, launch = create_and_bind(
                self.client,
                project=project,
                cell=cell,
                run_id=run_id,
                timeout=timeout,
                poll=poll,
                sleep=self.sleep,
                monotonic=self.monotonic,
                validate_roster=self._roster,
            )
            initial_deduplicated = launch["deduplicated"]
        else:
            session_id = str(cell.session_id)
            self._roster(project, cell, session_id)
            initial_message, initial_deduplicated = self._send_twice(
                cell,
                session_id,
                key=f"fleet-live:{run_id}:{cell.surface}:initial",
                phase="initial delivery",
            )
            launch = None
        initial = self._wait_ack(
            cell, session_id, initial_message, timeout=timeout, poll=poll
        )
        waiting = self._wait_waiting(
            project, cell, session_id, timeout=timeout, poll=poll
        )
        wake_message, wake_deduplicated = self._send_twice(
            cell,
            session_id,
            key=f"fleet-live:{run_id}:{cell.surface}:wake",
            phase="stopped-session wake",
        )
        if cell.wake_supported:
            wake = self._wait_ack(
                cell,
                session_id,
                wake_message,
                timeout=timeout,
                poll=poll,
                require_wake=True,
            )
            wake_outcome = "acknowledged"
        else:
            self.sleep(unsupported_observation)
            wake = self._receipt(cell, session_id, wake_message)
            if (
                wake["state"] != "pending"
                or wake["injection_count"] != 0
                or wake["wake_attempt_count"] != 0
                or wake["acknowledged_at"]
            ):
                raise AcceptanceContractError(
                    "unsupported_wake_not_pending", surface=cell.surface
                )
            self._wait_waiting(project, cell, session_id, timeout=timeout, poll=poll)
            wake_outcome = "expected_pending"
        report: dict[str, Any] = {
            "surface": cell.surface,
            "expected_version": cell.expected_version,
            "observed_version": waiting["executor_version"],
            "mode": cell.mode,
            "status": "passed",
            "session_id": session_id,
            "registration_identity_matched": True,
            "initial_message": initial,
            "initial_deduplicated": initial_deduplicated,
            "turn_posture": waiting["turn_posture"],
            "wake_supported": cell.wake_supported,
            "wake_outcome": wake_outcome,
            "wake_message": wake,
            "wake_deduplicated": wake_deduplicated,
        }
        if launch is not None:
            report["launch_id"] = launch["launch_id"]
        return report

    def _roster(
        self, project: str, cell: AcceptanceCell, session_id: str
    ) -> dict[str, Any]:
        result = self.client.call(
            ["sessions", "list", "--project", project, "--limit", "500"]
        )
        rows = result.get("rows")
        matches = (
            [
                row
                for row in rows
                if isinstance(row, dict) and row.get("session_id") == session_id
            ]
            if isinstance(rows, list)
            else []
        )
        if len(matches) != 1:
            raise AcceptanceContractError("registration_missing", surface=cell.surface)
        row = matches[0]
        if row.get("project") != project:
            raise AcceptanceContractError(
                "registration_project_mismatch", surface=cell.surface
            )
        if row.get("executor_surface") != cell.surface:
            raise AcceptanceContractError(
                "registration_surface_mismatch", surface=cell.surface
            )
        if row.get("executor_version") != cell.expected_version:
            raise AcceptanceContractError(
                "registration_version_mismatch", surface=cell.surface
            )
        if cell.machine_id and row.get("machine_id") != cell.machine_id:
            raise AcceptanceContractError(
                "registration_machine_mismatch", surface=cell.surface
            )
        if cell.model and row.get("model") != cell.model:
            raise AcceptanceContractError(
                "registration_model_mismatch", surface=cell.surface
            )
        if row.get("liveness") != "active":
            raise AcceptanceContractError(
                "registration_not_active", surface=cell.surface
            )
        return row

    def _wait_waiting(
        self,
        project: str,
        cell: AcceptanceCell,
        session_id: str,
        *,
        timeout: float,
        poll: float,
    ) -> dict[str, Any]:
        deadline = self.monotonic() + timeout
        while True:
            row = self._roster(project, cell, session_id)
            if row.get("turn_posture") == "waiting":
                routing = row.get("messageability")
                if (
                    not isinstance(routing, dict)
                    or routing.get("wake_operation") != "message_stopped"
                ):
                    raise AcceptanceContractError(
                        "waiting_route_missing", surface=cell.surface
                    )
                available = routing.get("wake_available") is True
                if available != cell.wake_supported:
                    raise AcceptanceContractError(
                        "waiting_wake_mismatch", surface=cell.surface
                    )
                return row
            if self.monotonic() >= deadline:
                raise AcceptanceContractError("waiting_timeout", surface=cell.surface)
            self.sleep(poll)

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
            f"Fleet live acceptance {phase} for {cell.surface}. "
            "Acknowledge this exact Fleet receipt using the command in its "
            "model-visible wrapper, then finish the top-level turn and wait."
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
        }

    def _wait_ack(
        self,
        cell: AcceptanceCell,
        session_id: str,
        message_id: str,
        *,
        timeout: float,
        poll: float,
        require_wake: bool = False,
    ) -> dict[str, Any]:
        deadline = self.monotonic() + timeout
        while True:
            receipt = self._receipt(cell, session_id, message_id)
            if receipt["state"] == "acknowledged":
                if receipt["injection_count"] < 1 or not receipt["acknowledged_at"]:
                    raise AcceptanceContractError(
                        "ack_evidence_invalid", surface=cell.surface
                    )
                if require_wake and (
                    receipt["wake_attempt_count"] < 1 or not receipt["last_wake_at"]
                ):
                    raise AcceptanceContractError(
                        "wake_evidence_missing", surface=cell.surface
                    )
                return receipt
            if receipt["state"] in {"expired", "cancelled"}:
                raise AcceptanceContractError(
                    "receipt_terminal_without_ack", surface=cell.surface
                )
            if self.monotonic() >= deadline:
                raise AcceptanceContractError("ack_timeout", surface=cell.surface)
            self.sleep(poll)


__all__ = ["LiveAcceptanceDriver"]
