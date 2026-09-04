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

from yoke_contracts import hosting_posture
from yoke_cli.config import aws_admin_capability as hosting
from yoke_cli.config import onboard_project_modes as project_modes
from yoke_cli.config import onboard_wizard_hosting_steps as hosting_steps
from yoke_cli.config.onboard_wizard_state import CopyTarget, _FormField
from yoke_cli.config.onboard_wizard_step_ids import STEP_HOSTING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View

STACK_LINK_LABEL = "the AWS stack link"


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
    async def action_back(self) -> None: ...


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
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(
            _View(
                STEP_HOSTING,
                hosting_steps.hosting_provider_body,
                self._on_hosting_provider_choice,
            )
        )

    def _on_hosting_provider_choice(self: _Shell, choice: str) -> None:
        if choice == "aws":
            self._goto_hosting_aws_sign_in()
            return
        if choice == "no-managed-host":
            self._goto_hosting_no_managed_host()
            return
        self._skip_hosting()

    # ── AWS sign-in choice ─────────────────────────────────

    def _goto_hosting_aws_sign_in(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(
            _View(
                STEP_HOSTING,
                hosting_steps.hosting_aws_sign_in_body,
                self._on_hosting_aws_sign_in_choice,
            )
        )

    def _on_hosting_aws_sign_in_choice(self: _Shell, choice: str) -> None:
        if choice == "create-key":
            self._goto_hosting_credentials(guided=True)
            return
        if choice == "existing-key":
            self._goto_hosting_credentials(guided=False)
            return
        self._skip_hosting()

    def _goto_hosting_credentials(self: _Shell, *, guided: bool) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        quick_create_url = (
            hosting.quick_create_url(region=self._hosting_region()) if guided else None
        )

        def builder():
            self._begin_form(
                hosting_steps.HOSTING_CREDENTIAL_FIELDS,
                on_done=lambda values: self._after_hosting_credentials(
                    values,
                    guided=guided,
                ),
            )
            if guided:
                return hosting_steps.hosting_guided_key_body(
                    quick_create_url=quick_create_url,
                    credential_dir=self._hosting_credential_dir(),
                )
            return hosting_steps.hosting_existing_key_body(
                credential_dir=self._hosting_credential_dir(),
            )

        self._goto(
            _View(
                STEP_HOSTING,
                builder,
                self._on_hosting_credential_choice,
                # The stack link is the longest string onboarding shows, and
                # this screen's text boxes hold focus, so the copy and open
                # chords are how it leaves the terminal intact.
                copy_targets=(
                    (CopyTarget(STACK_LINK_LABEL, quick_create_url, is_url=True),)
                    if quick_create_url
                    else ()
                ),
            )
        )

    def _on_hosting_credential_choice(self: _Shell, choice: str) -> None:
        if choice != "connect":
            self._skip_hosting()
            return
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

        self._goto(
            _View(
                STEP_HOSTING,
                builder,
                self._on_no_managed_host_choice,
            )
        )

    def _on_no_managed_host_choice(self: _Shell, choice: str) -> None:
        if choice == "back":
            import asyncio

            asyncio.ensure_future(self.action_back())
            return
        # The note is optional, so the row commits whatever the box holds --
        # including nothing.
        self._submit_pending_form()

    def _after_no_managed_host_note(
        self: _Shell,
        values: dict[str, str],
    ) -> None:
        note = values[hosting_steps.HOSTING_PROVIDER_NOTE_FIELD.key].strip()
        self.result.hosting_choice = hosting_posture.POSTURE_NO_YOKE_MANAGED_HOST
        self.result.hosting_provider_note = note or None
        # Nothing was verified because nothing was collected; the posture is
        # the whole record.
        self.result.hosting_verification = None
        self._goto_finish()

    # ── credential entry ────────────────────────────────────

    def _after_hosting_credentials(
        self: _Shell,
        values: dict[str, str],
        *,
        guided: bool,
    ) -> None:
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
            on_error=lambda exc: self._goto_hosting_error(exc, guided=guided),
            group="onboard-hosting",
            blocks_quit=True,
        )

    # ── outcome screens ─────────────────────────────────────

    def _goto_hosting_verified(
        self: _Shell,
        identity: hosting.CallerIdentity,
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self.result.hosting_choice = hosting_posture.POSTURE_YOKE_MANAGED_AWS
        self.result.hosting_verification = {
            "checked": True,
            "ok": True,
            "account": identity.account,
            "identity": identity.identity,
            # The region the probe authenticated in becomes the capability
            # row's region at apply, so a later `yoke aws exec` runs where the
            # operator was just verified rather than in a default they never saw.
            "region": self._hosting_region(),
        }
        self._goto(
            _View(
                STEP_HOSTING,
                lambda: hosting_steps.hosting_verified_body(
                    account=identity.account,
                    identity=identity.identity,
                    credential_dir=self._hosting_credential_dir(),
                ),
                lambda _choice: self._goto_finish(),
            )
        )

    def _goto_hosting_error(
        self: _Shell,
        exc: BaseException,
        *,
        guided: bool,
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        if isinstance(exc, hosting.HostingVerificationError):
            title = "Yoke couldn't verify the AWS credential."
            details = [
                "The two values were stored, but no verified identity was recorded.",
                "Re-enter the values or choose Not now to continue without AWS.",
            ]
        else:
            title = "Couldn't save the hosting credential."
            details = [
                "Re-entering the two values retries the save.",
                "Not now leaves hosting for a later `/yoke onboard` run.",
            ]
        self.result.hosting_choice = hosting_posture.POSTURE_UNDECIDED
        self.result.hosting_verification = None
        self._goto(
            _View(
                STEP_HOSTING,
                lambda: hosting_steps.hosting_error_body(
                    title,
                    str(exc),
                    details,
                    hosting_steps.HOSTING_RETRY_ROWS,
                ),
                lambda choice: self._on_hosting_error_choice(
                    choice,
                    guided=guided,
                ),
            )
        )

    def _on_hosting_error_choice(
        self: _Shell,
        choice: str,
        *,
        guided: bool,
    ) -> None:
        if choice == "retry":
            self._goto_hosting_credentials(guided=guided)
            return
        self._skip_hosting()

    # ── shared derivations ──────────────────────────────────

    def _hosting_region(self: _Shell) -> str:
        return hosting.default_region()

    def _hosting_credential_dir(self: _Shell) -> str:
        return hosting.credential_dir_display(self.result.project_slug or "")


__all__ = ["HostingFlow"]
