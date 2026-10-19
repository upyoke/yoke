"""Browser approval in agent mode: print the step, exit, and ask again next call.

The wizard keeps one process waiting while the person approves this machine in
their browser. An agent call has to stay short, and a pending approval that
lives only in a process is lost when that process is stopped. So the agent
shell saves the pending authorization in the private setup store, prints the
browser step as this call's outcome, and exits. The next ``yoke setup --agent``
asks the server once: an approval continues setup, a pending one prints the
same browser step again, and a denial, expiry or failure takes the wizard's own
routes. The saved authorization is cleared as soon as it is used up.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any

from yoke_cli.config import hosted_machine_authorization
from yoke_cli.config import setup_agent_response as responses
from yoke_cli.config import yoke_token_verify
from yoke_cli.config.onboard_wizard_flow_machine_admission import (
    accept_machine_credential,
    save_machine_credential,
)
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT

APPROVAL_KEY = "connect.hosted_machine_approval"
RESUMED_BROWSER_LINE = "Open this link on any device."

Pending = hosted_machine_authorization.PendingMachineAuthorization


class AgentHostedApproval:
    """Overrides of the wizard's approval wait for one-call-at-a-time setup."""

    def _start_hosted_machine_authorization(
        self, *, after_denial: bool = False, replace_current: bool = False
    ) -> None:
        saved = self._answers.pending_approval
        if saved and not after_denial and not replace_current:
            pending = pending_from_record(saved)
            self._hosted_machine_authorization = pending
            self._hosted_machine_denial_retry_used = bool(saved.get("after_denial"))
            self._goto_hosted_machine_approval(pending, RESUMED_BROWSER_LINE)
            return
        self._answers.keep_pending_approval(None)
        super()._start_hosted_machine_authorization(
            after_denial=after_denial, replace_current=replace_current
        )

    def _poll_hosted_machine_authorization(
        self, pending: Pending, _browser_line: str
    ) -> None:
        saved = self._answers.pending_approval
        if not saved or saved.get("device_code") != pending.device_code:
            # A code minted in this call cannot be approved yet.
            self._wait_for_approval(pending)
            return
        try:
            credential = hosted_machine_authorization.poll_once(pending)
            if credential is None:
                self._wait_for_approval(pending)
                return
            verification = yoke_token_verify.verify(
                credential.api_url, credential.token
            )
            value = save_machine_credential(
                credential, verification, self.result.config_path
            )
        except hosted_machine_authorization.HostedMachineAuthorizationDenied as exc:
            self._answers.keep_pending_approval(None)
            self._goto_hosted_machine_denied(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - the wizard's error route names each cause
            self._answers.keep_pending_approval(None)
            self._goto_hosted_machine_error(str(exc))
            return
        self._answers.keep_pending_approval(None)
        accept_machine_credential(self, value)

    def _wait_for_approval(self, pending: Pending) -> None:
        prompt = self._history[-1].prompt
        self._refuse_unused_answers(prompt)
        saved = self._answers.pending_approval
        if not saved or saved.get("device_code") != pending.device_code:
            saved = pending_record(
                pending, after_denial=self._hosted_machine_denial_retry_used
            )
        self._answers.pending_approval = saved
        self._answers.flush(waiting_key=APPROVAL_KEY)
        self._final = responses.approval_pending(
            STEP_CONNECT, APPROVAL_KEY, self._approval_human(pending)
        )


def pending_record(pending: Pending, *, after_denial: bool) -> dict[str, Any]:
    """The store's copy: an absolute expiry, since the next call starts later."""
    record = dataclasses.asdict(pending)
    record["expires_at"] = time.time() + record.pop("expires_in")
    record["after_denial"] = after_denial
    return record


def pending_from_record(record: dict[str, Any]) -> Pending:
    fields = {field.name for field in dataclasses.fields(Pending)}
    values = {name: value for name, value in record.items() if name in fields}
    remaining = float(record["expires_at"]) - time.time()
    return Pending(**values, expires_in=max(0, int(remaining)))


__all__ = [
    "APPROVAL_KEY",
    "AgentHostedApproval",
    "pending_from_record",
    "pending_record",
]
