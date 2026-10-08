"""Exact repository access recovery after manual GitHub creation."""

from __future__ import annotations

from typing import Any

from yoke_contracts import github_app_snapshot
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT, SelectionRow


MISSING_REPOSITORY = "manual-missing-repository"
GRANT_ACCESS = "manual-grant-access"


def _repository_identity_error(value: str) -> str | None:
    try:
        github_app_snapshot.repository_full_name(value)
    except github_app_snapshot.GitHubAppSnapshotError:
        return "Enter the exact GitHub repository as owner/repo."
    return None


class ManualRepositoryAccessFlow:
    """Offer settings only after live access excludes an identified repository."""

    def _identify_manual_repository(self) -> None:
        self._goto_input(
            STEP_PROJECT,
            "Which repository did you create?",
            "Enter its exact owner/repo so Yoke checks only that repository.",
            placeholder="owner/repo",
            allow_placeholder=False,
            validate=_repository_identity_error,
            on_done=self._after_manual_repository_identity,
        )

    def _after_manual_repository_identity(self, value: str) -> None:
        error = _repository_identity_error(value)
        if error:
            self._manual_publish_refresh_error(RuntimeError(error))
            return
        self._manual_publish_expected_repository = value
        self._after_manual_publish_refresh(
            getattr(self, "_manual_publish_live_report", None)
        )

    def _manual_repository_unavailable(self, report: Any) -> None:
        expected = self._manual_publish_expected_repository
        # Visibility without write permission is not proof of missing repo access.
        if any(
            isinstance(repo, dict)
            and str(repo.get("full_name") or "").casefold() == expected.casefold()
            for repo in report["access"].get("repositories") or []
        ):
            self._manual_publish_refresh_error(
                RuntimeError(
                    "repository_not_writable: the App can see this repository but "
                    "cannot publish to it. Restore its installation's Contents write "
                    "permission and active status, then Check repositories again."
                )
            )
            return
        self._show_manual_repository_access()

    def _grant_manual_repository_access(self) -> None:
        # A subsequent refresh clears this proof before starting its worker.
        if not getattr(self, "_manual_publish_access_missing", False):
            return
        owner = self._manual_publish_expected_repository.split("/", 1)[0]
        self._open_project_github_access(owner=owner)
        self._show_manual_repository_access(opened=True)

    def _show_manual_repository_access(self, *, opened: bool = False) -> None:
        from yoke_cli.config.onboard_wizard_app import _View
        from yoke_cli.config.onboard_wizard_flow_publish_manual import (
            BACK,
            CHECK_REPOSITORIES,
            DISABLED,
        )
        from yoke_cli.config import onboard_github_copy

        self._manual_publish_access_missing = True
        details = [
            "repository_access_missing: the live check did not find this repo in App access.",
            "Grant repo access, add this repository to the App, then return and choose Check repositories.",
        ]
        if opened:
            details.extend(
                [
                    (
                        "GitHub opened the App access page."
                        if self._project_github_access_opened
                        else "The browser did not open; copy the App access URL below."
                    ),
                    f"GitHub App access URL: {self._project_github_access_opened_url}",
                ]
            )
        self._goto(
            _View(
                STEP_PROJECT,
                lambda: steps.verification_body(
                    "Give the Yoke GitHub App access to the new repository.",
                    self._manual_publish_expected_repository,
                    details,
                    [
                        SelectionRow(
                            CHECK_REPOSITORIES,
                            "Check repositories",
                            "refresh live App access",
                        ),
                        SelectionRow(
                            GRANT_ACCESS,
                            "Grant repo access",
                            "open GitHub App repository settings",
                        ),
                        SelectionRow(
                            DISABLED,
                            onboard_github_copy.MACHINE_GITHUB_SKIP_LABEL,
                            onboard_github_copy.MACHINE_GITHUB_SKIP_DESC,
                        ),
                        SelectionRow(BACK, "Back", "return to the prior screen"),
                    ],
                    ok=False,
                ),
                self._on_manual_publish_recovery,
            )
        )
