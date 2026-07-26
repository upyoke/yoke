"""Hosting-provider step for the ``yoke onboard`` wizard.

Sits between the Project step and Review because the credential belongs to a
project: it is stored under that project's slug on this machine. Runs that
onboard no deployable project — machine-only, and developing Yoke itself —
pass straight through to Review.

The step is skippable by design. Skipping strands nothing — the same
capability is reachable later from ``/yoke onboard``, from
``yoke projects capability secret set``, or from a wizard re-run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from yoke_cli.config import aws_admin_capability as hosting
from yoke_cli.config import onboard_input_validation as input_validation
from yoke_cli.config import onboard_project_modes as project_modes
from yoke_cli.config import onboard_wizard_hosting_steps as hosting_steps
from yoke_cli.config.onboard_wizard_step_ids import STEP_HOSTING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any

    def _goto(self, view: "_View") -> None: ...
    def _goto_input(self, step, title, subtitle, *, placeholder, on_done,
                    password: bool = False,
                    allow_placeholder: bool = True,
                    validate=None,
                    initial_value: str = "") -> None: ...
    def _goto_finish(self) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...


class HostingFlow:
    """Hosting-credential screens and their routing."""

    # ── entry ───────────────────────────────────────────────

    def _goto_hosting(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        slug = str(self.result.project_slug or "").strip()
        if not slug or not project_modes.offers_hosting_credential(
            self.result.project_mode
        ):
            # No project Yoke deploys for means no owner for a credential.
            self._goto_finish()
            return
        self._goto(_View(
            STEP_HOSTING,
            lambda: hosting_steps.hosting_connect_body(
                quick_create_url=hosting.quick_create_url(
                    region=self._hosting_region(),
                ),
                credential_dir=self._hosting_credential_dir(),
            ),
            self._on_hosting_choice,
        ))

    def _on_hosting_choice(self: _Shell, choice: str) -> None:
        if choice != "connect":
            self._skip_hosting()
            return
        self._goto_hosting_access_key()

    def _skip_hosting(self: _Shell) -> None:
        self.result.hosting_choice = hosting.HOSTING_CHOICE_SKIP
        self.result.hosting_verification = None
        self._goto_finish()

    # ── credential entry ────────────────────────────────────

    def _goto_hosting_access_key(self: _Shell) -> None:
        self._goto_input(
            STEP_HOSTING,
            hosting_steps.HOSTING_ACCESS_KEY_TITLE,
            hosting_steps.HOSTING_ACCESS_KEY_SUBTITLE,
            placeholder="AKIA...",
            allow_placeholder=False,
            validate=input_validation.validate_access_key_id,
            on_done=self._after_hosting_access_key,
        )

    def _after_hosting_access_key(self: _Shell, value: str) -> None:
        self._hosting_access_key_id = value.strip()
        self._goto_input(
            STEP_HOSTING,
            hosting_steps.HOSTING_SECRET_KEY_TITLE,
            hosting_steps.HOSTING_SECRET_KEY_SUBTITLE,
            placeholder="the secret value from the stack",
            allow_placeholder=False,
            password=True,
            validate=input_validation.validate_secret_access_key,
            on_done=self._after_hosting_secret_key,
        )

    def _after_hosting_secret_key(self: _Shell, value: str) -> None:
        # The secret lives only in this closure until the store writes it; it
        # is never held on the app or echoed to any screen.
        secret = value.strip()
        slug = str(self.result.project_slug or "").strip()
        region = self._hosting_region()
        access_key_id = getattr(self, "_hosting_access_key_id", "")

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

        self.result.hosting_choice = hosting.HOSTING_CHOICE_CONNECT
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
                "Skipping leaves hosting for a later `/yoke onboard` run.",
            ]
            rows = hosting_steps.HOSTING_RETRY_ROWS
        self.result.hosting_choice = hosting.HOSTING_CHOICE_SKIP
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
            self._goto_hosting_access_key()
            return
        if choice == "keep":
            # The pair is already on disk; only the proof is missing.
            self.result.hosting_choice = hosting.HOSTING_CHOICE_CONNECT
            self._goto_finish()
            return
        self._skip_hosting()

    # ── shared derivations ──────────────────────────────────

    def _hosting_region(self: _Shell) -> str:
        return hosting.default_region()

    def _hosting_credential_dir(self: _Shell) -> str:
        return hosting.credential_dir_display(self.result.project_slug or "")


__all__ = ["HostingFlow"]
