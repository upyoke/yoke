"""Fetch the repository during the Project step, then show what is in it.

The clone used to happen at Apply, so the first time anyone saw the repository
was after onboarding had already begun writing into it — a repo carrying
somebody else's Yoke layer converged hundreds of files while presenting itself
as a first install. The clone now runs here, as a visible Project step, and
the operator decides what happens to any layer it brought before Review lists
a single write.

Fetching is the only thing that runs early. Creating or re-homing a repository
still belongs to Apply: those change GitHub, while cloning only fills the new
folder the operator just named.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from yoke_cli.config import onboard_wizard_github_state as github_state
from yoke_cli.config import onboard_wizard_checkout_inspection_screen as screen
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import project_installed_layer as layer
from yoke_cli.config import project_onboard_clone
from yoke_cli.config.onboard_wizard import github_connected
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT
from yoke_cli.config.project_clone_support import ClonePlan

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any

    def _goto(self, view: "_View") -> None: ...
    def _run_checking(self, **kwargs) -> None: ...
    def _goto_clone_folder(self) -> None: ...
    def _goto_clone_outcome(self) -> None: ...
    def _goto_existing_project_ready(self) -> None: ...


class CheckoutInspectionFlow:
    """Materialize the clone, scan it, and record the operator's decision."""

    def _materialize_and_inspect_checkout(self: _Shell) -> None:
        self._run_checking(
            step=STEP_PROJECT,
            title="Fetching the repository.",
            message=(
                "Cloning it into your folder so you can see what is in there "
                "before anything is installed."
            ),
            work=self._materialize_checkout,
            on_success=self._show_checkout_inspection,
            on_error=self._goto_checkout_fetch_error,
            group="onboard-checkout-fetch",
            blocks_quit=True,
        )

    def _materialize_checkout(self: _Shell) -> layer.InstalledLayerScan:
        """Clone into the chosen folder, reusing a clone already there."""
        root = Path(str(self.result.project_checkout)).expanduser()
        project_onboard_clone.resumable_clone_with_machine_access(
            root,
            str(self.result.project_remote_url or ""),
            plan=ClonePlan(
                use_machine_github=github_connected(self.result),
                fork_web_url=github_state.clone_web_url(self.result),
            ),
            config_path=self.result.config_path,
            service_api_url=self.result.api_url or None,
            local_connection_selected=not self.result.api_url,
        )
        return layer.scan(root)

    def _show_checkout_inspection(
        self: _Shell, scan: layer.InstalledLayerScan
    ) -> None:
        """Ask only when there is something to decide.

        A clean repository has no layer to keep or remove, so a screen there
        would be a click with one answer. The fetch itself was visible, and
        Review reports the clean scan, so nothing is hidden by moving on.
        """
        from yoke_cli.config.onboard_wizard_app import _View

        if not scan.present:
            self._after_checkout_inspected()
            return
        self._goto(_View(
            STEP_PROJECT,
            lambda: screen.inspection_body(scan),
            self._on_checkout_inspection,
        ))

    def _on_checkout_inspection(self: _Shell, choice: str) -> None:
        if choice in layer.LAYER_DECISIONS:
            self.result.project_clone_existing_layer_decision = choice
        self._after_checkout_inspected()

    def _after_checkout_inspected(self: _Shell) -> None:
        if self.result.existing_project_id:
            self._goto_existing_project_ready()
            return
        self._goto_clone_outcome()

    def _goto_checkout_fetch_error(self: _Shell, exc: BaseException) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "Couldn't fetch the repository.",
                str(exc),
                [
                    "Check the repository URL, your GitHub access, and the "
                    "network connection.",
                    "Choosing a different folder starts the fetch again.",
                ],
                screen.FETCH_ERROR_ROWS,
                ok=False,
            ),
            self._on_checkout_fetch_error,
        ))

    def _on_checkout_fetch_error(self: _Shell, choice: str) -> None:
        if choice == "retry":
            self._materialize_and_inspect_checkout()
            return
        self._goto_clone_folder()


__all__ = ["CheckoutInspectionFlow"]
