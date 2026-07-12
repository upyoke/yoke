"""Machine GitHub App step for the ``yoke onboard`` wizard."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Protocol

from rich.markup import escape

from yoke_contracts import github_origin
from yoke_cli.config import github_machine
from yoke_cli.config import onboard_github_copy
from yoke_cli.config import onboard_machine_github
from yoke_cli.config import onboard_wizard_github_state as github_state
from yoke_cli.config import onboard_wizard_github_repair
from yoke_cli.config import onboard_wizard_saved_github as saved_github
from yoke_cli.config.onboard_destinations import DESTINATION_LOCAL
from yoke_cli.config.onboard_wizard_step_ids import STEP_GITHUB


def _wizard_steps():
    from yoke_cli.config import onboard_wizard_steps as steps

    return steps


def _bounded_summary(values: list[str], *, total: int | None = None) -> str:
    """Render a terminal-sized sample without hiding the omitted count."""

    display_limit = 4
    actual_total = max(len(values), total or 0)
    if not values:
        return "none"
    visible = ", ".join(values[:display_limit])
    omitted = actual_total - min(len(values), display_limit)
    return f"{visible}, and {omitted} more" if omitted > 0 else visible


def _success_message(report: Mapping[str, Any]) -> str:
    identity = report.get("identity")
    login = str(
        identity.get("login")
        if isinstance(identity, Mapping) else ""
    ).strip()
    return (
        f"Success! Yoke GitHub App connected for {login}."
        if login else
        "Success! Yoke GitHub App connected."
    )


def _success_details(report: Mapping[str, Any]) -> list[str]:
    details: list[str] = []
    identity = report.get("identity")
    if isinstance(identity, Mapping) and identity.get("login"):
        details.append(f"GitHub username: {identity['login']}")
    app = report.get("app")
    if isinstance(app, Mapping) and app.get("slug"):
        details.append(f"GitHub App: {app['slug']}")
    access = report.get("access")
    if isinstance(access, Mapping):
        installations = [
            item for item in access.get("installations") or []
            if isinstance(item, Mapping)
        ]
        installation_labels = []
        for item in installations:
            account = str(item.get("account_login") or "").strip()
            if not account:
                continue
            selection = str(item.get("repository_selection") or "selected")
            state = "suspended" if item.get("suspended") else f"{selection} repositories"
            installation_labels.append(f"{account} ({state})")
        details.append(
            "Installed for: " + _bounded_summary(installation_labels)
        )
        repositories = [
            str(item) for item in access.get("repos") or [] if str(item)
        ]
        repo_count = access.get("repo_count")
        total = repo_count if isinstance(repo_count, int) else len(repositories)
        details.append(
            f"Repositories available: {total} — "
            f"{_bounded_summary(repositories, total=total)}"
        )
    permissions = report.get("permissions")
    if isinstance(permissions, Mapping) and permissions.get("usable") is True:
        details.append("Required GitHub App permissions: ready.")
    details.append(
        "Saved on this machine. Use `yoke github disconnect` to remove it."
    )
    return details


if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    _stored_github_attempted: bool
    _stored_machine_github_api_url: str | None
    _history: list[Any]

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(self, step, title, subtitle, rows, on_select) -> "_View": ...
    def _goto_input(self, step, title, subtitle, *, placeholder, on_done,
                    password: bool = False,
                    allow_placeholder: bool = True,
                    initial_value: str = "") -> None: ...
    def _goto_project_mode(self) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...
    async def action_back(self) -> None: ...
    def _render_current(self) -> None: ...


class MachineGithubFlow:
    """Machine GitHub App routing screens."""

    def _goto_machine_github(self: _Shell) -> None:
        steps = _wizard_steps()
        self._goto(self._selection_view(
            STEP_GITHUB,
            onboard_github_copy.MACHINE_GITHUB_TITLE,
            onboard_github_copy.MACHINE_GITHUB_SUBTITLE + (
                " The existing machine connection stays saved if this run "
                "continues backlog-only."
                if self.result.machine_github_saved else ""
            ),
            steps.MACHINE_GITHUB_ROWS, self._on_machine_github,
        ))
        saved_github.auto_recheck_authorized(self)

    def _on_machine_github(self: _Shell, choice: str) -> None:
        self.result.machine_github_choice = choice
        if choice != onboard_machine_github.CHOICE_CONNECT:
            self._choose_machine_github_backlog()
            self._goto_project_mode()
            return
        reuse = saved_github.connection_exists(self.result.config_path)
        self._stored_github_attempted = reuse
        self._check_machine_github(reuse=reuse)

    def _check_machine_github(
        self: _Shell,
        *,
        reuse: bool,
        replace_current: bool = False,
        replace_profile: bool = False,
    ) -> None:
        def _notify(event: Any) -> None:
            if not isinstance(event, dict):
                return
            try:
                if event.get("phase") == "device_authorization":
                    self.call_from_thread(self._show_github_device_code, event)
                elif event.get("phase") == "app_installation":
                    self.call_from_thread(self._show_github_install_url, event)
            except RuntimeError:
                return

        def _work() -> dict[str, Any]:
            selected_service = str(self.result.api_url or "").strip() or None
            if reuse:
                return github_machine.status(
                    config_path=self.result.config_path,
                    check=True,
                    **github_state.connection_scope(self.result),
                )
            return github_machine.connect(
                config_path=self.result.config_path,
                service_api_url=selected_service,
                use_local_product_profile=(
                    getattr(self.result, "destination", None) == DESTINATION_LOCAL
                ),
                replace_profile=replace_profile,
                notify=_notify,
            )

        self._run_checking(
            step=STEP_GITHUB,
            title="Connecting the Yoke GitHub App.",
            message=(
                "Refreshing the saved authorization."
                if reuse
                else "A browser will open. Enter the one-time code shown here."
            ),
            detail_lines=[
                "Authorization happens in GitHub; Yoke never asks you to paste a GitHub secret."
            ],
            work=_work,
            on_success=self._after_machine_github_check,
            on_error=self._goto_machine_github_error,
            group="onboard-github-app",
            replace_current=replace_current,
            blocks_quit=True,
        )

    def _show_github_device_code(self: _Shell, event: dict[str, Any]) -> None:
        code = str(event.get("user_code") or "").strip()
        uri = str(event.get("verification_uri") or "").strip()
        if not (code and uri):
            return
        try:
            body = self.query_one("#onboard-body")
            lines = [
                widget for widget in body.children
                if getattr(widget, "has_class", lambda _name: False)("onboard-plan-line")
            ]
            if lines:
                lines[-1].update(escape(f"Enter code {code} at {uri}"))
        except Exception:
            return

    def _show_github_install_url(self: _Shell, event: dict[str, Any]) -> None:
        install_url = str(event.get("install_url") or "").strip()
        if not install_url:
            return
        try:
            body = self.query_one("#onboard-body")
            lines = [
                widget for widget in body.children
                if getattr(widget, "has_class", lambda _name: False)("onboard-plan-line")
            ]
            if lines:
                lines[-1].update(
                    escape(f"Install or configure the App at {install_url}")
                )
        except Exception:
            return

    def _after_machine_github_check(self: _Shell, report: Any) -> None:
        if isinstance(report, dict) and report.get("configured"):
            self.result.machine_github_saved = True
        if isinstance(report, dict) and (
            onboard_wizard_github_repair.needs_installation_repair(report)
        ):
            self._goto_machine_github_pending(report)
            return
        if isinstance(report, dict) and (
            onboard_wizard_github_repair.retryable_live_check(report)
        ):
            self._goto_machine_github_live_check_retry(report)
            return
        if not isinstance(report, dict) or not report.get("ok"):
            issues = report.get("issues") if isinstance(report, dict) else []
            message = next(
                (
                    str(issue.get("message"))
                    for issue in issues or []
                    if isinstance(issue, dict) and issue.get("message")
                ),
                "GitHub App authorization is not ready.",
            )
            self._goto_machine_github_error(
                RuntimeError(message),
                install_url=str(report.get("install_url") or "").strip() or None,
            )
            return
        if not report.get("ready"):
            self._goto_machine_github_pending(report)
            return
        self.result.machine_github_choice = onboard_machine_github.CHOICE_CONNECT
        self.result.machine_github_api_url = str(
            report.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL
        )
        self.result.machine_github_verification = report
        self._goto_machine_github_success(report)

    def _goto_machine_github_success(
        self: _Shell,
        report: Mapping[str, Any],
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        steps = _wizard_steps()
        self._goto(_View(
            STEP_GITHUB,
            lambda: steps.verification_body(
                "GitHub connected.",
                _success_message(report),
                _success_details(report),
                steps.VERIFY_OK_ROWS,
                ok=True,
            ),
            lambda _choice: self._goto_project_mode(),
        ))

    def _goto_machine_github_pending(self: _Shell, report: dict[str, Any]) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        steps = _wizard_steps()
        repair = onboard_wizard_github_repair.needs_installation_repair(report)
        details = (
            [
                "Repair the suspended installation or approve the required App permissions in GitHub.",
                "Then choose Check access; Yoke will not continue as connected until it is ready.",
                *onboard_wizard_github_repair.url_lines(report),
            ]
            if repair
            else [
                "Finish the installation or repository selection in GitHub.",
                "Then choose Check access; Yoke will not continue as connected until it is ready.",
            ]
        )
        if self.result.machine_github_saved:
            details.append(
                "The machine GitHub authorization is already saved. Use "
                "`yoke github disconnect` to remove it."
            )
        install_url = str(report.get("install_url") or "").strip()
        if install_url:
            details.insert(0, f"Install or configure the App: {install_url}")
        self._goto(_View(
            STEP_GITHUB,
            lambda: steps.verification_body(
                (
                    "GitHub App access needs repair."
                    if repair
                    else "GitHub authorization is waiting for App access."
                ),
                (
                    "The authorization is saved, but every App installation is suspended or missing required permissions."
                    if repair
                    else "The GitHub user is authorized, but no usable App installation is ready yet."
                ),
                details,
                steps.GITHUB_APP_PENDING_ROWS,
                ok=False,
            ),
            self._on_machine_github_pending,
        ))

    def _goto_machine_github_live_check_retry(
        self: _Shell, report: dict[str, Any],
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        steps = _wizard_steps()
        issue = next(
            (
                str(item.get("message") or "")
                for item in report.get("issues") or []
                if isinstance(item, dict)
                and item.get("code") == "github_live_check_failed"
            ),
            "GitHub access could not be checked.",
        )
        self._goto(_View(
            STEP_GITHUB,
            lambda: steps.verification_body(
                "GitHub authorization was saved.",
                issue,
                [
                    "Choose Check access to retry without repeating browser authorization.",
                    "Reconnect only if GitHub reports that authorization was revoked.",
                ],
                steps.GITHUB_APP_PENDING_ROWS,
                ok=False,
            ),
            self._on_machine_github_pending,
        ))

    def _on_machine_github_pending(self: _Shell, choice: str) -> None:
        if choice == "check":
            self._check_machine_github(reuse=True, replace_current=True)
            return
        if choice == "backlog":
            self._choose_machine_github_backlog()
            self._goto_project_mode()
            return
        self._return_to_machine_github_choice()

    def _goto_machine_github_error(
        self: _Shell,
        exc: BaseException,
        *,
        install_url: str | None = None,
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        steps = _wizard_steps()
        details = [
            "Retry after completing browser authorization or App installation.",
            "Backlog-only keeps GitHub automation off for this run.",
        ]
        if self.result.machine_github_saved:
            details.append(
                "The machine GitHub authorization is already saved. Use "
                "`yoke github disconnect` to remove it."
            )
        if install_url:
            details.insert(0, f"Install or configure the App: {install_url}")
        self._goto(_View(
            STEP_GITHUB,
            lambda: steps.verification_body(
                "GitHub App connection is not ready.",
                str(exc),
                details,
                steps.GITHUB_APP_UNAVAILABLE_ROWS,
                ok=False,
            ),
            self._on_machine_github_error,
        ))

    def _on_machine_github_error(self: _Shell, choice: str) -> None:
        if choice == "reconnect":
            self._check_machine_github(
                reuse=False,
                replace_current=True,
                replace_profile=True,
            )
            return
        if choice == "backlog":
            self._choose_machine_github_backlog()
            self._goto_project_mode()
            return
        self._return_to_machine_github_choice()

    def _return_to_machine_github_choice(self: _Shell) -> None:
        """Return synchronously so the Back row cannot reselect the error view."""

        if len(self._history) > 1:
            self._history.pop()
            self._render_current()
            return
        self._goto_machine_github()

    def _choose_machine_github_backlog(self: _Shell) -> None:
        self.result.machine_github_choice = onboard_machine_github.CHOICE_SKIP
        self.result.machine_github_verification = None
        self.result.machine_github_api_url = None


__all__ = ["MachineGithubFlow"]
