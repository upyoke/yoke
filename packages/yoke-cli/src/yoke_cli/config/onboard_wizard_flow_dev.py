"""Public Edit Yoke source flow: choose a checkout or clone any fork."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import yoke_dev_detect as dev_detect
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT, SelectionRow

if TYPE_CHECKING:  # pragma: no cover
    from yoke_cli.config.onboard_wizard_app import _View

_USE_CHECKOUT = "checkout"
_CLONE_SOURCE = "clone"


class _Shell(Protocol):
    result: Any
    _preset_dev_checkout: str | None

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(self, step, title, subtitle, rows, on_select) -> "_View": ...
    def _goto_input(
        self,
        step,
        title,
        subtitle,
        *,
        placeholder,
        on_done,
        password: bool = False,
        allow_placeholder: bool = True,
        initial_value: str = "",
    ) -> None: ...
    def _goto_hosting(self) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...


class DevFlow:
    """Select source without requiring official project or repository access."""

    def _start_dev_flow(self: _Shell) -> None:
        self._goto_dev_checkout()

    def _goto_dev_checkout(self: _Shell) -> None:
        if self._preset_dev_checkout:
            checkout = self._preset_dev_checkout
            self._preset_dev_checkout = None
            self._use_dev_checkout(checkout)
            return
        self._run_checking(
            step=STEP_PROJECT,
            title="Checking local Yoke source.",
            message="Looking for Yoke source checkouts on this machine.",
            work=dev_detect.detect_yoke_checkouts,
            on_success=self._show_dev_checkout,
            on_error=lambda exc: self._goto_dev_error(str(exc)),
            group="onboard-yoke-source-checkout",
        )

    def _show_dev_checkout(self: _Shell, checkouts: Any) -> None:
        if len(checkouts) == 1:
            self._use_dev_checkout(str(checkouts[0]))
            return
        rows = [
            SelectionRow(str(path), str(path), "use this Yoke source checkout")
            for path in checkouts
        ]
        rows.extend(
            [
                SelectionRow(
                    _USE_CHECKOUT,
                    "Choose another checkout",
                    "any local Yoke source checkout",
                ),
                SelectionRow(
                    _CLONE_SOURCE,
                    "Clone Yoke source",
                    "use any public repository or your fork",
                ),
            ]
        )
        self._goto(
            self._selection_view(
                STEP_PROJECT,
                "Edit Yoke source.",
                "Use a local checkout or clone any source-available fork. No official Yoke access is required.",
                rows,
                self._on_dev_checkout_pick,
            )
        )

    def _on_dev_checkout_pick(self: _Shell, choice: str) -> None:
        if choice == _USE_CHECKOUT:
            self._goto_input(
                STEP_PROJECT,
                "Where is the Yoke source checkout?",
                "The folder must contain Yoke's pyproject.toml and runtime/harness source.",
                placeholder="~/code/yoke",
                allow_placeholder=False,
                on_done=self._use_dev_checkout,
            )
            return
        if choice == _CLONE_SOURCE:
            self._goto_input(
                STEP_PROJECT,
                "Which Yoke source repository?",
                "Paste a public Git URL for Yoke or your fork.",
                placeholder="https://github.com/you/yoke.git",
                allow_placeholder=False,
                on_done=self._after_dev_clone_url,
            )
            return
        self._use_dev_checkout(choice)

    def _after_dev_clone_url(self: _Shell, value: str) -> None:
        self.result.project_remote_url = value
        self._goto_input(
            STEP_PROJECT,
            "Where should Yoke source be cloned?",
            "Choose a new or empty local folder.",
            placeholder="~/code/yoke",
            allow_placeholder=False,
            on_done=self._use_dev_checkout,
        )

    def _use_dev_checkout(self: _Shell, checkout: str) -> None:
        error = dev_detect.preflight_dev_checkout(
            checkout,
            cloning=bool(self.result.project_remote_url),
        )
        if error is not None:
            self._goto_dev_error(error)
            return
        self.result.project_checkout = checkout
        self._goto_hosting()

    def _goto_dev_error(self: _Shell, message: str) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(
            _View(
                STEP_PROJECT,
                lambda: steps.verification_body(
                    "Yoke source is not ready.",
                    message,
                    [
                        "Choose an existing Yoke source checkout, or an empty folder plus its clone URL."
                    ],
                    [SelectionRow("back", "Back", "choose the source again")],
                    ok=False,
                ),
                lambda _choice: self._goto_dev_checkout(),
            )
        )


__all__ = ["DevFlow"]
