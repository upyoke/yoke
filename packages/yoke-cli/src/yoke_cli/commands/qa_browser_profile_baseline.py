"""Explicit private-profile restoration for the browser provisioning command."""

from pathlib import Path
import tarfile

from yoke_cli.config import browser_profile
from yoke_harness import browser_profile_archive


def restore_profile_baseline(project: str, baseline_path: str) -> dict:
    """Restore the requested project's sealed snapshot before daemon startup."""
    try:
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
        raise RuntimeError(str(exc)) from None
    except (OSError, ValueError, tarfile.TarError):
        raise RuntimeError("browser_profile_baseline_restore_refused") from None
