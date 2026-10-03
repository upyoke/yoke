"""Explicit private-profile restoration for the browser provisioning command."""

from pathlib import Path

from yoke_cli.config import browser_profile
from yoke_harness import browser_profile_archive
from yoke_harness.browser_profile_archive_validation import archive_step


class ProfileBaselineRestoreError(RuntimeError):
    """A closed restore refusal with safe diagnostics for CLI rendering."""

    def __init__(self, error):
        super().__init__(str(error))
        self.details = error.details


def restore_profile_baseline(project: str, baseline_path: str) -> dict:
    """Restore the requested project's sealed snapshot before daemon startup."""
    try:
        with archive_step("profile_resolution"):
            key = browser_profile.profile_project_key(project)
            home = Path.home()
            profile = browser_profile.profile_dir(key)
            relative = str(profile.relative_to(home))
            return browser_profile_archive.restore(
                browser_profile_archive.literal_path(str(home)),
                browser_profile_archive.literal_path(baseline_path),
                key,
                relative,
            )
    except browser_profile_archive.ProfileArchiveError as exc:
        raise ProfileBaselineRestoreError(exc) from None
