"""Where each harness CLI publishes its latest release, and how one is installed.

Test Machine goldens carry the harness CLIs a reset restores. Comparing the
versions recorded beside a golden with these published releases decides
whether the golden must be refreshed before QA resets to it. Each install
command is the vendor's own installer, run as the test user.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Mapping

from yoke_contracts.session_control.surface_versions import (
    surface_version_meets_floor,
)

#: The version token a CLI's ``--version`` output carries.
VERSION_TOKEN_PATTERN = r"\d+(?:\.\d+)+(?:[-+._A-Za-z0-9]*)?"


def _plain_version(body: str) -> str:
    return body.strip()


def _codex_channel_version(body: str) -> str:
    tag = str(json.loads(body).get("tag_name") or "")
    return tag.removeprefix("rust-v") if tag.startswith("rust-v") else ""


_CURSOR_DOWNLOAD = re.compile(
    r"downloads\.cursor\.com/lab/(\d{4}\.\d{1,2}\.\d{1,2}-[0-9a-fA-F]{7,40})/"
)


def _cursor_installer_version(body: str) -> str:
    matched = _CURSOR_DOWNLOAD.search(body)
    return matched.group(1) if matched else ""


@dataclass(frozen=True)
class HarnessCliRelease:
    """One harness CLI's release channel and installer."""

    harness_id: str
    surface_id: str
    #: Executable names in resolution order; ``~/.local/bin`` is searched first.
    executables: tuple[str, ...]
    latest_url: str
    parse_latest: Callable[[str], str]
    #: POSIX shell run with the wanted version as ``$1``.
    install_script: str

    def latest_version(self, body: str) -> str:
        """Return the published version from the channel body, or refuse."""
        try:
            version = self.parse_latest(body)
        except (ValueError, AttributeError):
            version = ""
        if not re.fullmatch(VERSION_TOKEN_PATTERN, version):
            raise ValueError(
                f"harness_cli_latest_unreadable: {self.latest_url} did not name "
                f"a {self.harness_id} version"
            )
        return version


HARNESS_CLI_RELEASES = (
    HarnessCliRelease(
        "claude-code",
        "claude-cli",
        ("claude",),
        "https://downloads.claude.ai/claude-code-releases/latest",
        _plain_version,
        'curl -fsSL https://claude.ai/install.sh | bash -s -- "$1"',
    ),
    HarnessCliRelease(
        "codex",
        "codex-cli",
        ("codex",),
        "https://releases.openai.com/codex/channels/latest",
        _codex_channel_version,
        "curl -fsSL https://chatgpt.com/codex/install.sh"
        ' | CODEX_NON_INTERACTIVE=1 sh -s -- --release "$1"',
    ),
    HarnessCliRelease(
        "cursor",
        "cursor-cli",
        ("agent", "cursor-agent"),
        "https://cursor.com/install",
        _cursor_installer_version,
        # The installer pins the release it was published with: the latest.
        "curl -fsSL https://cursor.com/install | bash",
    ),
)

HARNESS_CLI_RELEASE_BY_ID = {
    release.harness_id: release for release in HARNESS_CLI_RELEASES
}


def outdated_harness_clis(
    recorded: Mapping[str, str | None] | None, latest: Mapping[str, str]
) -> tuple[str, ...]:
    """Return harness ids whose recorded version is absent or below latest."""
    recorded = recorded or {}
    return tuple(
        release.harness_id
        for release in HARNESS_CLI_RELEASES
        if not surface_version_meets_floor(
            release.surface_id,
            recorded.get(release.harness_id),
            latest[release.harness_id],
        )
    )


__all__ = [
    "HARNESS_CLI_RELEASES",
    "HARNESS_CLI_RELEASE_BY_ID",
    "HarnessCliRelease",
    "VERSION_TOKEN_PATTERN",
    "outdated_harness_clis",
]
