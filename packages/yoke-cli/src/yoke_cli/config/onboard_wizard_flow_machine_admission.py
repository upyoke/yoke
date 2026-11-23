"""Choose own-machine approval, a teammate invite, or an explicit token."""

from yoke_contracts.refusal_recovery import compose_refusal

from yoke_cli.config import hosted_machine_authorization as authorization
from yoke_cli.config import local_reachability, teammate_invite_redemption
from yoke_cli.config import writer, yoke_token_verify
from yoke_cli.config import onboard_wizard_run_connection as run_connection
from yoke_cli.config import setup_release_start


def approval_hint(code: str) -> str:
    return (
        "Approve it from a machine already connected to this server: "
        f"`yoke machines approve {code}`, or Approve under "
        "Machines → Waiting for approval. The machine belongs to the approver."
    )


def store_machine_credential(credential, verification, config_path):
    """Save verified delivered credentials through the existing private writer."""
    connection = writer.set_connection(
        credential.org,
        transport="https",
        api_url=credential.api_url,
        token=credential.token,
        activate=True,
        path=config_path,
    )
    token_file = str(connection["connection"]["credential_source"]["path"])
    return credential, verification, token_file


def follow_stored_credential(stored):
    """The first moment a fresh setup knows its server: move onto its release.

    This runs before any project question; the rerun reuses the saved
    connection. A refusal here is an install failure, not a sign-in failure.
    """
    credential, verification, token_file = stored
    followed = setup_release_start.follow_after_sign_in(credential.api_url)
    return credential, verification, token_file, followed


def save_machine_credential(credential, verification, config_path):
    return follow_stored_credential(
        store_machine_credential(credential, verification, config_path)
    )


def exit_with_follow_refusal(shell, refusal):
    """Close the shell; ``raise_carried_follow`` re-raises once it has closed."""
    shell.follow_refused = refusal
    shell.exit()


def raise_carried_follow(shell):
    """Raise the release follow or its refusal that the closed shell carries."""
    for carried in (shell.release_followed, getattr(shell, "follow_refused", None)):
        if carried is not None:
            raise carried


def exit_on_followed_release(shell, followed):
    """Close the shell so `yoke setup` reruns on the installed release."""
    if getattr(shell, "_project_mode_preset", False) and shell.result.project_mode:
        # The wizard asks where the code lives before sign-in; keep it.
        followed.carried_args = ["--project-mode", shell.result.project_mode]
    shell.release_followed = followed
    shell.exit()


def accept_machine_credential(shell, value):
    credential, verification, token_file, followed = value
    if followed is not None:
        exit_on_followed_release(shell, followed)
        return
    shell.result.env_name = credential.org
    shell.result.api_url = credential.api_url
    shell.result.token = None
    shell.result.token_file = token_file
    shell.result.token_source_kind = "token_file"
    shell.result.yoke_token_verification = verification
    run_connection.record_approved(shell)
    shell._goto_yoke_verify_success(verification)


class MachineAdmissionChoiceFlow:
    def _follow_saved_connection(self, on_current):
        """Move onto a chosen saved server's release before any later step."""
        from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT

        def finished(followed):
            if followed is not None:
                exit_on_followed_release(self, followed)
                return
            on_current()

        def failed(error):
            if not isinstance(error, setup_release_start.StartFollowRefused):
                error = setup_release_start.StartFollowRefused(
                    compose_refusal(
                        f"setup_release_install_failed: {error}",
                        recovery="fix the named cause, then run this setup command again",
                    )
                )
            exit_with_follow_refusal(self, error)

        self._run_checking(
            step=STEP_CONNECT,
            title="Checking this server's Yoke release.",
            message="Setup installs the release it serves if this machine differs.",
            work=lambda: setup_release_start.follow_after_sign_in(self.result.api_url),
            on_success=finished,
            on_error=failed,
            group="onboard-saved-release-follow",
        )

    def _machine_admission_notice(self):
        if local_reachability.active_connection_is_local(self.result.config_path):
            return local_reachability.LOCAL_REACHABILITY_NOTICE
        return ""

    def _goto_machine_admission(self):
        from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT
        from yoke_cli.config.setup_prompt import SelectionRow

        self._goto(
            self._selection_view(
                "connect.machine_admission",
                STEP_CONNECT,
                "How should this machine join your team server?",
                " ".join(
                    filter(
                        None,
                        [
                            self._machine_admission_notice(),
                            "Approve your own machine, or connect as the invited teammate.",
                        ],
                    )
                ),
                [
                    SelectionRow(
                        "own",
                        "This is my own machine",
                        "approve from a connected machine",
                    ),
                    SelectionRow(
                        "invite",
                        "Enter invite code",
                        "join as the teammate your admin invited",
                    ),
                    SelectionRow(
                        "token",
                        "Use an API token",
                        "an existing credential for first boot or recovery",
                    ),
                    SelectionRow("back", "Back", "return to the server URL"),
                ],
                self._after_machine_admission,
            )
        )

    def _after_machine_admission(self, choice):
        if choice == "own":
            self._machine_authorization_server = self.result.api_url
            self._start_hosted_machine_authorization()
        elif choice == "invite":
            self._goto_invite_code()
        elif choice == "token":
            self._machine_authorization_server = None
            self._goto_server_connection_form()
        else:
            self._step_back()

    def _goto_invite_code(self):
        from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT

        self._goto_input(
            "connect.invite_code",
            STEP_CONNECT,
            "Enter invite code.",
            "Enter invite code, or ask an admin to run `yoke invite <name>` and send you the code",
            placeholder="invite code",
            password=True,
            allow_placeholder=False,
            guidance="The invite is a secret. Enter it in `yoke setup --tui`; Esc returns without connecting.",
            on_done=self._redeem_invite_code,
        )

    def _redeem_invite_code(self, code):
        from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT

        def work():
            credential = teammate_invite_redemption.redeem(
                self.result.api_url,
                code,
                machine={
                    **authorization._machine_identity(),
                    "platform": "macOS"
                    if authorization.platform.system() == "Darwin"
                    else authorization.platform.system(),
                },
            )
            verification = yoke_token_verify.verify(
                credential.api_url, credential.token
            )
            return save_machine_credential(
                credential, verification, self.result.config_path
            )

        self._run_checking(
            step=STEP_CONNECT,
            title="Connecting your invited machine.",
            message="Redeeming the invite once and verifying the teammate's connection.",
            work=work,
            on_success=lambda value: accept_machine_credential(self, value),
            on_error=self._goto_invite_error,
            group="onboard-invite-redemption",
            replace_current=True,
        )

    def _goto_invite_error(self, error):
        from yoke_cli.config.onboard_wizard_state import _View

        if isinstance(error, setup_release_start.StartFollowRefused):
            exit_with_follow_refusal(self, error)
            return
        from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT
        from yoke_cli.config.setup_prompt import SelectionRow, SetupPrompt, TONE_ERROR

        self._goto(
            _View(
                SetupPrompt(
                    key="connect.invite_error",
                    step=STEP_CONNECT,
                    title="The invite did not connect this machine.",
                    message=str(error),
                    choices=(
                        SelectionRow("back", "Back", "return to connection choices"),
                    ),
                    tone=TONE_ERROR,
                ),
                lambda _: self._step_back(),
            )
        )
