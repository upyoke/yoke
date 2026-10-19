"""Browser approvals in agent mode: print the step, exit, and ask again next call.

Two setup steps wait on a person in their browser: approving this machine for
its Yoke server, and signing in to GitHub. The wizard keeps one process waiting
through each. An agent call has to stay short, and a pending approval that lives
only in a process is lost when that process is stopped. So the agent shell
saves the pending authorization, with its short-lived device code, in the
private setup store, prints the browser step as this call's outcome and exits.
The next ``yoke setup --agent`` asks once: an approval continues setup, a
pending one prints the same browser step again, and a denial, expiry or failure
takes the wizard's own routes. The saved authorization is cleared as soon as it
is used up.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any

from yoke_cli.config import github_device_flow
from yoke_cli.config import hosted_machine_authorization
from yoke_cli.config import setup_agent_response as responses
from yoke_cli.config import yoke_token_verify
from yoke_cli.config.onboard_machine_github import CHOICE_CONNECT
from yoke_cli.config.onboard_wizard_flow_machine_admission import (
    accept_machine_credential,
    save_machine_credential,
)
from yoke_cli.config.onboard_wizard_step_ids import STEP_GITHUB
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT
from yoke_cli.config.setup_prompt import SetupHuman

MACHINE_KEY = "connect.hosted_machine_approval"
GITHUB_KEY = "github.machine"
RESUMED_BROWSER_LINE = "Open this link on any device."
MACHINE_INSTEAD = (
    "To choose another home instead, run `yoke setup --agent --discard` and "
    "start again."
)
GITHUB_INSTEAD = (
    "To leave GitHub for now instead, answer github.machine with another choice."
)

Pending = hosted_machine_authorization.PendingMachineAuthorization
Device = github_device_flow.DeviceAuthorization


class ApprovalPending(Exception):
    """Ends a check whose browser step now waits for the next call."""


class AgentApprovals:
    """Overrides of the wizard's browser waits for one-call-at-a-time setup."""

    # ── machine approval ────────────────────────────────────

    def _start_hosted_machine_authorization(
        self, *, after_denial: bool = False, replace_current: bool = False
    ) -> None:
        saved = self._saved_approval("machine")
        if saved and not after_denial and not replace_current:
            pending = _restore(Pending, saved)
            self._hosted_machine_authorization = pending
            self._hosted_machine_denial_retry_used = bool(saved["after_denial"])
            self._goto_hosted_machine_approval(pending, RESUMED_BROWSER_LINE)
            return
        self._forget_approval("machine")
        super()._start_hosted_machine_authorization(
            after_denial=after_denial, replace_current=replace_current
        )

    def _poll_hosted_machine_authorization(
        self, pending: Pending, _browser_line: str
    ) -> None:
        saved = self._saved_approval("machine")
        if not saved or saved["device_code"] != pending.device_code:
            # A code minted in this call cannot be approved yet.
            record = _record(
                "machine",
                pending,
                after_denial=self._hosted_machine_denial_retry_used,
            )
            self._wait_for_approval(record, STEP_CONNECT, MACHINE_KEY, pending)
            return
        try:
            credential = hosted_machine_authorization.poll_once(pending)
            if credential is None:
                self._wait_for_approval(saved, STEP_CONNECT, MACHINE_KEY, pending)
                return
            verification = yoke_token_verify.verify(
                credential.api_url, credential.token
            )
            value = save_machine_credential(
                credential, verification, self.result.config_path
            )
        except hosted_machine_authorization.HostedMachineAuthorizationDenied as exc:
            self._forget_approval("machine")
            self._goto_hosted_machine_denied(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - the wizard's error route names each cause
            self._forget_approval("machine")
            self._goto_hosted_machine_error(str(exc))
            return
        self._forget_approval("machine")
        accept_machine_credential(self, value)

    # ── GitHub sign-in ──────────────────────────────────────

    def _on_machine_github(self, choice: str) -> None:
        if choice != CHOICE_CONNECT:
            self._forget_approval("github")
        super()._on_machine_github(choice)

    def github_device_authorize(
        self,
        *,
        client_id: str,
        web_url: str,
        opener: Any = None,
        **_wizard_only: Any,
    ) -> github_device_flow.DeviceFlowResult:
        """The device step ``github_machine.connect`` runs in agent mode."""
        saved = self._saved_approval("github")
        if saved and (saved["client_id"], saved["web_url"]) == (client_id, web_url):
            device = _restore(Device, saved)
            try:
                token = github_device_flow.poll_once(
                    device, client_id=client_id, web_url=web_url, opener=opener
                )
            except github_device_flow.GitHubDeviceFlowError:
                self._forget_approval("github")
                raise
            if token is not None:
                self._forget_approval("github")
                return github_device_flow.DeviceFlowResult(token, device, False)
        else:
            device = github_device_flow.start(
                client_id=client_id, web_url=web_url, opener=opener
            )
            saved = _record("github", device, client_id=client_id, web_url=web_url)
        self._wait_for_approval(saved, STEP_GITHUB, GITHUB_KEY, device)
        raise ApprovalPending()

    # ── shared ──────────────────────────────────────────────

    def _saved_approval(self, kind: str) -> dict[str, Any] | None:
        saved = self._answers.pending_approval
        return saved if saved and saved.get("kind") == kind else None

    def _forget_approval(self, kind: str) -> None:
        if self._saved_approval(kind):
            self._answers.keep_pending_approval(None)

    def _wait_for_approval(
        self, record: dict[str, Any], step: str, key: str, pending: Pending | Device
    ) -> None:
        self._refuse_unused_answers(self._history[-1].prompt)
        self._answers.pending_approval = record
        self._answers.flush(waiting_key=key)
        if record["kind"] == "machine":
            human, instead = self._approval_human(pending), MACHINE_INSTEAD
        else:
            human, instead = _github_human(pending), GITHUB_INSTEAD
        self._final = responses.approval_pending(step, key, human, instead=instead)


def _github_human(device: Device) -> SetupHuman:
    return SetupHuman(
        instructions=(
            f"Open the link, enter the code {device.user_code}, and approve "
            "access in GitHub."
        ),
        url=device.verification_uri,
        user_code=device.user_code,
        max_seconds=float(device.expires_in),
        poll_interval_seconds=float(device.interval),
    )


def _record(kind: str, pending: Pending | Device, **extra: Any) -> dict[str, Any]:
    """The store's copy: an absolute expiry, since the next call starts later."""
    record = dataclasses.asdict(pending)
    record["expires_at"] = time.time() + record.pop("expires_in")
    return {"kind": kind, **record, **extra}


def _restore(cls: type, record: dict[str, Any]) -> Any:
    names = {field.name for field in dataclasses.fields(cls)}
    values = {name: value for name, value in record.items() if name in names}
    remaining = float(record["expires_at"]) - time.time()
    return cls(**values, expires_in=max(0, int(remaining)))


__all__ = ["AgentApprovals", "ApprovalPending", "GITHUB_KEY", "MACHINE_KEY"]
