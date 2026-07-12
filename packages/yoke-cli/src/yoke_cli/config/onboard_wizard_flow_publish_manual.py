"""Same-run continuation after an operator manually creates a GitHub repo."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

from yoke_contracts import github_app_snapshot
from yoke_cli.config import github_machine
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard_widgets import (
    STEP_PROJECT,
    SelectionRow,
)


CHECK_REPOSITORIES = "manual-check-repositories"
BACKLOG_ONLY = "manual-backlog-only"
BACK = "manual-back"


class ManualPublishFlow:
    """Refresh, select, and attach one exact manually created repository."""

    def _goto_publish_cannot_create(self) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        url = str(getattr(self, "_manual_repository_url", "") or "")
        if not url:
            from yoke_cli.config.onboard_wizard_github_state import endpoint_pair

            url = endpoint_pair(self.result).new_repository_url()
            self._manual_repository_url = url
        opened = bool(getattr(self, "_manual_repository_opened", False))
        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "Create the repository in GitHub.",
                self._cannot_publish_reason(),
                [
                    (
                        "GitHub opened the repository page."
                        if opened
                        else "The browser did not open; copy the repository URL below."
                    ),
                    f"Repository URL: {url}",
                    "After creating it, grant the Yoke GitHub App access.",
                    "Return here and choose Check repositories.",
                ],
                [
                    SelectionRow(
                        CHECK_REPOSITORIES,
                        "Check repositories",
                        "refresh App access and pick the exact repo",
                    ),
                    SelectionRow(
                        BACKLOG_ONLY,
                        "Use backlog only",
                        "leave this project local",
                    ),
                    SelectionRow(BACK, "Back", "change the publish choice"),
                ],
                ok=False,
            ),
            self._on_manual_publish_guidance,
        ))

    def _on_manual_publish_guidance(self, choice: str) -> None:
        if choice == BACK:
            asyncio.ensure_future(self.action_back())
            return
        if choice == CHECK_REPOSITORIES:
            self._check_manual_publish_repositories(replace_current=False)
            return
        self._on_manual_publish_recovery(choice)

    def _on_manual_publish_recovery(self, choice: str) -> None:
        if choice == CHECK_REPOSITORIES:
            self._check_manual_publish_repositories(replace_current=True)
            return
        if choice == BACKLOG_ONLY:
            steps.reset_project_publish_fields(self.result)
            self.result.project_github_repository_id = None
            self.result.project_github_installation_id = None
            self._after_repo("")
            return
        if choice == BACK:
            asyncio.ensure_future(self.action_back())
            return
        self._goto_publish_cannot_create()

    def _check_manual_publish_repositories(
        self,
        *,
        replace_current: bool,
    ) -> None:
        service_api_url = str(self.result.api_url or "")
        self._run_checking(
            step=STEP_PROJECT,
            title="Checking GitHub repositories.",
            message="Refreshing live GitHub App access.",
            work=lambda: github_machine.status(
                config_path=self.result.config_path,
                check=True,
                service_api_url=(
                    service_api_url
                    if service_api_url.startswith("https://")
                    else None
                ),
            ),
            on_success=self._after_manual_publish_refresh,
            on_error=self._manual_publish_refresh_error,
            group="onboard-manual-publish-repositories",
            replace_current=replace_current,
            blocks_quit=True,
        )

    def _after_manual_publish_refresh(self, report: Any) -> None:
        repositories = _live_writable_app_repositories(report)
        if repositories is None:
            self._manual_publish_refresh_error(RuntimeError(
                "GitHub repository access could not be verified live."
            ))
            return
        self.result.machine_github_verification = report
        self.result.machine_github_api_url = str(
            report.get("api_url") or self.result.machine_github_api_url or ""
        )
        identity = report.get("identity")
        self._manual_publish_user_login = str(
            identity.get("login") if isinstance(identity, Mapping) else ""
        )
        self._manual_publish_repositories = {
            str(repo["full_name"]).casefold(): repo for repo in repositories
        }
        self._show_manual_publish_repositories(repositories)

    def _show_manual_publish_repositories(
        self, repositories: list[dict[str, Any]],
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        rows = [
            SelectionRow(
                str(repo["full_name"]),
                str(repo["full_name"]),
                (
                    "private · live App-visible repository"
                    if repo["private"]
                    else "public · live App-visible repository"
                ),
            )
            for repo in repositories
        ]
        rows.extend((
            SelectionRow(CHECK_REPOSITORIES, "Check again", "refresh GitHub access"),
            SelectionRow(BACKLOG_ONLY, "Use backlog only", "leave this project local"),
            SelectionRow(BACK, "Back", "return to manual-create guidance"),
        ))
        subtitle = (
            "Pick the exact repository Yoke should attach and push to."
            if repositories
            else "No usable App-visible repositories were found yet."
        )
        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.selection_body(
                "Select the repository you created.", subtitle, rows,
            ),
            self._on_manual_publish_repository,
        ))

    def _on_manual_publish_repository(self, choice: str) -> None:
        if choice in {CHECK_REPOSITORIES, BACKLOG_ONLY, BACK}:
            self._on_manual_publish_recovery(choice)
            return
        repository = getattr(self, "_manual_publish_repositories", {}).get(
            choice.casefold()
        )
        if not isinstance(repository, Mapping):
            self._manual_publish_refresh_error(RuntimeError(
                "The selected GitHub repository changed; check repositories again."
            ))
            return
        full_name = str(repository["full_name"])
        owner, name = full_name.split("/", 1)
        self.result.project_publish_to_github = True
        self.result.project_publish_create_repository = False
        self.result.project_publish_owner = owner
        self.result.project_publish_owner_login = str(
            getattr(self, "_manual_publish_user_login", "") or ""
        )
        self.result.project_publish_repo_name = name
        self.result.project_publish_private = bool(repository["private"])
        self.result.project_publish_repository_id = int(
            repository["repository_id"]
        )
        self.result.project_publish_installation_id = int(
            repository["installation_id"]
        )
        self.result.project_github_repository_id = int(
            repository["repository_id"]
        )
        self.result.project_github_installation_id = int(
            repository["installation_id"]
        )
        self.result.project_github_repo = full_name
        self._after_repo(full_name)

    def _manual_publish_refresh_error(self, exc: BaseException) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "Couldn't verify the new repository.",
                str(exc),
                ["Finish creating the repo and granting App access, then retry."],
                [
                    SelectionRow(CHECK_REPOSITORIES, "Check again", "retry live access"),
                    SelectionRow(BACKLOG_ONLY, "Use backlog only", "leave it local"),
                    SelectionRow(BACK, "Back", "return to the prior screen"),
                ],
                ok=False,
            ),
            self._on_manual_publish_recovery,
        ))


def _live_writable_app_repositories(
    report: Any,
) -> list[dict[str, Any]] | None:
    """Return exact repos from one successful live App refresh, else None."""

    if not isinstance(report, Mapping):
        return None
    identity = report.get("identity")
    access = report.get("access")
    if (
        not isinstance(identity, Mapping)
        or identity.get("checked") is not True
        or identity.get("ok") is not True
        or not isinstance(access, Mapping)
        or access.get("repo_listing_ok") is not True
    ):
        return None
    installations = {
        row.get("installation_id")
        for row in access.get("installations") or []
        if isinstance(row, Mapping)
        and isinstance(row.get("installation_id"), int)
        and not row.get("suspended")
        and isinstance(row.get("permissions"), Mapping)
        and row["permissions"].get("contents") == "write"
    }
    selected: list[dict[str, Any]] = []
    for raw in access.get("repositories") or []:
        if not isinstance(raw, Mapping):
            continue
        repository_id = raw.get("repository_id")
        installation_id = raw.get("installation_id")
        if (
            not isinstance(repository_id, int)
            or repository_id <= 0
            or installation_id not in installations
            or not isinstance(raw.get("private"), bool)
        ):
            continue
        try:
            full_name = github_app_snapshot.repository_full_name(
                raw.get("full_name")
            )
        except github_app_snapshot.GitHubAppSnapshotError:
            continue
        selected.append({
            "repository_id": repository_id,
            "installation_id": installation_id,
            "full_name": full_name,
            "private": raw["private"],
        })
    return sorted(selected, key=lambda item: item["full_name"].casefold())


__all__ = [
    "BACK",
    "BACKLOG_ONLY",
    "CHECK_REPOSITORIES",
    "ManualPublishFlow",
]
