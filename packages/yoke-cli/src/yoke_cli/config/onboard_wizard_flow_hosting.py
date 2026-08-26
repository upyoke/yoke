"""Hosting-provider step for the ``yoke onboard`` wizard.

Sits between the Project step and Review because the credential belongs to a
project: it is stored under that project's slug on this machine. Runs that
onboard no deployable project — machine-only, and developing Yoke itself —
pass straight through to Review.

The step has three answers, not two, because "I run the hosting myself" and
"I have not decided" are different facts. Deciding later strands nothing — the
same capability is reachable from ``/yoke onboard``, from
``yoke projects capability secret set``, or from a wizard re-run — but it also
tells the project nothing, so ``/yoke onboard`` keeps asking. Declaring that
Yoke manages no host settles the question: apply records it on the project and
onboarding stops proposing cloud credentials and infrastructure Packs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Protocol

from yoke_cli.config import aws_admin_capability as hosting
from yoke_cli.config import onboard_project_modes as project_modes
from yoke_cli.config import onboard_wizard_hosting_steps as hosting_steps
from yoke_cli.config.onboard_wizard_state import _FormField
from yoke_cli.config.onboard_wizard_step_ids import STEP_HOSTING
from yoke_contracts import hosting_posture

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any

    def _goto(self, view: "_View") -> None: ...
    def _begin_form(
        self,
        fields: tuple[_FormField, ...],
        *,
        on_done: Callable[[dict[str, str]], None],
    ) -> None: ...
    def _submit_pending_form(self) -> bool: ...
    def _goto_finish(self) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...


class HostingFlow:
    """Hosting-credential screens and their routing."""

    # ── entry ───────────────────────────────────────────────

    def _goto_hosting(self: _Shell) -> None:
        slug = str(self.result.project_slug or "").strip()
        if not slug or not project_modes.offers_hosting_credential(
            self.result.project_mode
        ):
            # No project Yoke deploys for means no owner for a credential.
            self._goto_finish()
            return
        self._goto_hosting_connect()

    def _goto_hosting_connect(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        def builder():
            self._begin_form(
                hosting_steps.HOSTING_CREDENTIAL_FIELDS,
                on_done=self._after_hosting_credentials,
            )
            return hosting_steps.hosting_connect_body(
                quick_create_url=hosting.quick_create_url(
                    region=self._hosting_region(),
                ),
                credential_dir=self._hosting_credential_dir(),
            )

        self._goto(_View(STEP_HOSTING, builder, self._on_hosting_choice))

    def _on_hosting_choice(self: _Shell, choice: str) -> None:
        if choice == "no-managed-host":
            self._goto_hosting_no_managed_host()
            return
        if choice != "connect":
            self._skip_hosting()
            return
        # Both boxes are on this screen, so the row commits what is in them; a
        # rejected value keeps the screen and marks the box it came from.
        self._submit_pending_form()

    def _skip_hosting(self: _Shell) -> None:
        self.result.hosting_choice = hosting_posture.POSTURE_UNDECIDED
        self.result.hosting_provider_note = None
        self.result.hosting_verification = None
        self._goto_finish()

    # ── declared: the operator runs the hosting ─────────────

    def _goto_hosting_no_managed_host(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        def builder():
            self._begin_form(
                hosting_steps.HOSTING_NO_MANAGED_HOST_FIELDS,
                on_done=self._after_no_managed_host_note,
            )
            return hosting_steps.hosting_no_managed_host_body()

        self._goto(_View(
            STEP_HOSTING, builder, self._on_no_managed_host_choice,
        ))

    def _on_no_managed_host_choice(self: _Shell, choice: str) -> None:
        if choice == "back":
            self._goto_hosting_connect()
            return
        # The note is optional, so the row commits whatever the box holds --
        # including nothing.
        self._submit_pending_form()

    def _after_no_managed_host_note(
        self: _Shell, values: dict[str, str],
    ) -> None:
        note = values[hosting_steps.HOSTING_PROVIDER_NOTE_FIELD.key].strip()
        self.result.hosting_choice = hosting_posture.POSTURE_NO_YOKE_MANAGED_HOST
        self.result.hosting_provider_note = note or None
        # Nothing was verified because nothing was collected; the posture is
        # the whole record.
        self.result.hosting_verification = None
        self._goto_finish()

    # ── credential entry ────────────────────────────────────

    def _after_hosting_credentials(self: _Shell, values: dict[str, str]) -> None:
        # The secret lives only in this closure until the store writes it; it
        # is never held on the app or echoed to any screen.
        access_key_id = values[hosting_steps.HOSTING_ACCESS_KEY_FIELD.key]
        secret = values[hosting_steps.HOSTING_SECRET_KEY_FIELD.key]
        slug = str(self.result.project_slug or "").strip()
        region = self._hosting_region()

        def _work() -> hosting.CallerIdentity:
            hosting.store_credential(
                slug,
                access_key_id=access_key_id,
                secret_access_key=secret,
            )
            return hosting.verify_caller_identity(slug, region)

        self._run_checking(
            step=STEP_HOSTING,
            title="Saving and verifying the hosting credential.",
            message="Storing both values on this machine, then checking who they are.",
            detail_lines=[
                "The check reads the credential back the way a deploy will.",
                "Yoke never prints the secret value.",
            ],
            work=_work,
            on_success=self._goto_hosting_verified,
            on_error=self._goto_hosting_error,
            group="onboard-hosting",
            blocks_quit=True,
        )

    # ── outcome screens ─────────────────────────────────────

    def _goto_hosting_verified(
        self: _Shell, identity: hosting.CallerIdentity,
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self.result.hosting_choice = hosting_posture.POSTURE_YOKE_MANAGED_AWS
        self.result.hosting_verification = {
            "checked": True,
            "ok": True,
            "account": identity.account,
            "identity": identity.identity,
        }
        self._goto(_View(
            STEP_HOSTING,
            lambda: hosting_steps.hosting_verified_body(
                account=identity.account,
                identity=identity.identity,
                credential_dir=self._hosting_credential_dir(),
            ),
            lambda _choice: self._goto_finish(),
        ))

    def _goto_hosting_error(self: _Shell, exc: BaseException) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        # AwsCliMissingError is a HostingVerificationError, so it is matched
        # first. Anything that is not a verification verdict — a failed write,
        # or an unexpected failure — reports as a save problem rather than
        # putting words in AWS's mouth.
        if isinstance(exc, hosting.AwsCliMissingError):
            title = "Saved, but Yoke can't verify it here."
            details = [
                "The two values are already stored on this machine.",
                "`yoke aws exec -- sts get-caller-identity` checks them once the CLI is installed.",
            ]
            rows = hosting_steps.HOSTING_UNVERIFIED_ROWS
        elif isinstance(exc, hosting.HostingVerificationError):
            title = "AWS rejected the hosting credential."
            details = [
                "The two values were stored, but they did not pass the identity check.",
                "Re-entering replaces them; a wrong paste is the usual cause.",
            ]
            rows = hosting_steps.HOSTING_RETRY_ROWS
        else:
            title = "Couldn't save the hosting credential."
            details = [
                "Re-entering the two values retries the save.",
                "Deciding later leaves hosting for a `/yoke onboard` run.",
            ]
            rows = hosting_steps.HOSTING_RETRY_ROWS
        self.result.hosting_choice = hosting_posture.POSTURE_UNDECIDED
        self.result.hosting_verification = None
        self._goto(_View(
            STEP_HOSTING,
            lambda: hosting_steps.hosting_error_body(
                title, str(exc), details, rows,
            ),
            self._on_hosting_error_choice,
        ))

    def _on_hosting_error_choice(self: _Shell, choice: str) -> None:
        if choice == "retry":
            self._goto_hosting_connect()
            return
        if choice == "no-managed-host":
            # Reaching an error screen is a common way to discover that AWS was
            # never the right answer, so the declaration is offered here too.
            self._goto_hosting_no_managed_host()
            return
        if choice == "keep":
            # The pair is already on disk; only the proof is missing.
            self.result.hosting_choice = hosting_posture.POSTURE_YOKE_MANAGED_AWS
            self._goto_finish()
            return
        self._skip_hosting()

    # ── shared derivations ──────────────────────────────────

    def _hosting_region(self: _Shell) -> str:
        return hosting.default_region()

    def _hosting_credential_dir(self: _Shell) -> str:
        return hosting.credential_dir_display(self.result.project_slug or "")


__all__ = ["HostingFlow"]
