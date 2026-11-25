"""Canonical native CLI facts for every supported harness family."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shlex

from yoke_contracts.executor_labels import CANONICAL_HARNESS_IDS
from yoke_contracts.watch_cli_forms import WATCHER_MAX_DURATION_SECONDS

CLAUDE_AGENTS_MINIMUM_VERSION = "2.1.281"
_CLAUDE_VSCODE_BINARY = "anthropic.claude-code-{version}*/resources/native-binary/claude"
_CODEX_VSCODE_BINARY = "openai.chatgpt-{version}*/bin/*/codex"


def _vscode_patterns(relative_path: str) -> tuple[str, ...]:
    return tuple(
        f"~/{host}/extensions/{relative_path}" for host in (".vscode", ".vscode-server")
    )


_CLAUDE_VSCODE_PATTERNS = _vscode_patterns(_CLAUDE_VSCODE_BINARY)
_WINDOWS_CLAUDE_VSCODE_PATTERNS = _vscode_patterns(f"{_CLAUDE_VSCODE_BINARY}.exe")


@dataclass(frozen=True)
class HarnessCliManifest:
    harness_id: str
    surface_id: str
    executable: str
    quota_source: str
    minimum_engine_version: str = "0.0.0"
    version_args: tuple[str, ...] = ("--version",)
    bundled_candidates: tuple[str, ...] = ()
    bundled_patterns: tuple[str, ...] = ()
    install_command: str = ""
    #: The operator runs this on their machine; Yoke never runs it unattended,
    #: because it replaces a binary that live sessions may be running.
    update_command: str = ""
    auth_args: tuple[str, ...] = ()
    auth_signed_in_key: str = ""
    login_args: tuple[str, ...] = ("login",)
    launch_environment: tuple[tuple[str, str], ...] = ()
    background_time_limit: str = ""
    windows_install_command: str = ""
    windows_bundled_candidates: tuple[str, ...] = ()
    windows_bundled_patterns: tuple[str, ...] = ()
    vscode_surface_id: str = ""
    vscode_binary_patterns: tuple[str, ...] = ()
    windows_vscode_binary_patterns: tuple[str, ...] = ()

    def vscode_binaries_for_platform(self, *, windows: bool | None = None) -> tuple[str, ...]:
        native = os.name == "nt" if windows is None else windows
        return self.windows_vscode_binary_patterns if native else self.vscode_binary_patterns

    def install_for_platform(self, *, windows: bool | None = None) -> str:
        native = os.name == "nt" if windows is None else windows
        return self.windows_install_command if native else self.install_command

    def bundles_for_platform(self, *, windows: bool | None = None):
        native = os.name == "nt" if windows is None else windows
        if native:
            return self.windows_bundled_candidates, self.windows_bundled_patterns
        return self.bundled_candidates, self.bundled_patterns

    def missing_cli_recovery(self) -> str:
        candidates, patterns = self.bundles_for_platform()
        bundles = (*candidates, *patterns)
        bundled = (
            f" Check the bundled CLI at {' or '.join(bundles)}." if bundles else ""
        )
        return f"{bundled} Install with `{self.install_for_platform()}` if needed.".strip()

    def sign_in_recovery(self, executable: str | None = None) -> str:
        return f"Run `{shlex.join((executable or self.executable, *self.login_args))}`."

    def to_json(self) -> dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "executable": self.executable,
            "quota_source": self.quota_source,
            "launch_environment": dict(self.launch_environment),
            "background_time_limit": self.background_time_limit,
            "version_args": list(self.version_args),
            "vscode_surface_id": self.vscode_surface_id,
            "vscode_binary_patterns": list(self.vscode_binary_patterns),
            "bundled_candidates": list(self.bundled_candidates),
            "bundled_patterns": list(self.bundled_patterns),
            "install_command": self.install_command,
            "windows": {
                "install_command": self.windows_install_command,
                "bundled_candidates": list(self.windows_bundled_candidates),
                "bundled_patterns": list(self.windows_bundled_patterns),
                "vscode_binary_patterns": list(self.windows_vscode_binary_patterns),
            },
            "authentication": {
                "status_args": list(self.auth_args),
                "signed_in_key": self.auth_signed_in_key,
                "login_args": list(self.login_args),
            },
            "project_discovery": {
                "instruction_file": "AGENTS.md",
                "skill_source": ".agents/skills/yoke",
                "native_skill_entry": (
                    ".claude/skills/yoke"
                    if self.harness_id == "claude-code"
                    else ".agents/skills/yoke"
                ),
                "minimum_engine_version": self.minimum_engine_version,
                "recovery_doc": ".yoke/docs/agents/harness-discovery.md",
            },
        }


HARNESS_CLI_MANIFESTS = (
    HarnessCliManifest(
        "claude-code",
        "claude-cli",
        "claude",
        "anthropic_oauth_usage",
        CLAUDE_AGENTS_MINIMUM_VERSION,
        bundled_patterns=(
            "~/Library/Application Support/Claude/claude-code/{version}/*/claude.app/Contents/MacOS/claude",
            _CLAUDE_VSCODE_PATTERNS[0],
        ),
        install_command="curl -fsSL https://claude.ai/install.sh | bash",
        update_command="claude update",
        windows_install_command="winget install --id Anthropic.ClaudeCode -e",
        windows_bundled_candidates=("~/.local/bin/claude.exe",),
        windows_bundled_patterns=_WINDOWS_CLAUDE_VSCODE_PATTERNS[:1],
        vscode_surface_id="claude-vscode",
        vscode_binary_patterns=_CLAUDE_VSCODE_PATTERNS,
        windows_vscode_binary_patterns=_WINDOWS_CLAUDE_VSCODE_PATTERNS,
        auth_args=("auth", "status", "--json"),
        auth_signed_in_key="loggedIn",
        login_args=("auth", "login"),
        launch_environment=tuple(
            (name, str(WATCHER_MAX_DURATION_SECONDS * 1000))
            for name in ("BASH_DEFAULT_TIMEOUT_MS", "BASH_MAX_TIMEOUT_MS")
        ),
        background_time_limit=(
            "Interactive background Bash has no time limit. Text-prompt -p "
            "runs default to 10 minutes; explicit timeout selects the lifetime "
            "up to 2 hours. BASH_MAX_TIMEOUT_MS raises that ceiling; "
            "BASH_DEFAULT_TIMEOUT_MS raises the default for moved commands. "
            "Yoke launches set both to the longest wrapper duration; recipes "
            "pass the wrapper duration as timeout. Limits do not depend on plan. "
            "Docs checked 2026-11-06: "
            "https://code.claude.com/docs/en/tools-reference"
        ),
    ),
    HarnessCliManifest(
        "codex",
        "codex-cli",
        "codex",
        "codex_account_rate_limits",
        "0.161.0",
        bundled_candidates=(
            "~/.local/bin/codex",
            "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
        ),
        install_command="curl -fsSL https://chatgpt.com/codex/install.sh | sh",
        update_command="codex update",
        windows_install_command="irm https://chatgpt.com/codex/install.ps1 | iex",
        windows_bundled_candidates=("%LOCALAPPDATA%/Programs/OpenAI/Codex/bin/codex.exe",),
        vscode_surface_id="codex-vscode",
        vscode_binary_patterns=_vscode_patterns(_CODEX_VSCODE_BINARY),
        windows_vscode_binary_patterns=_vscode_patterns(f"{_CODEX_VSCODE_BINARY}.exe"),
        auth_args=("login", "status"),
        background_time_limit=(
            "Designed deferral: no equivalent unattended background time limit "
            "is documented. Codex uses long-lived exec_command sessions and "
            "write_stdin continuations; no Claude timeout variable is applied. "
            "Docs checked 2026-10-20: https://developers.openai.com/cookbook/"
            "examples/gpt-5/codex_prompting_guide"
        ),
    ),
    HarnessCliManifest(
        "cursor",
        "cursor-cli",
        "cursor-agent",
        "cursor_dashboard_usage",
        "2026.10.01",
        install_command="curl https://cursor.com/install -fsS | bash",
        update_command="cursor-agent update",
        windows_install_command="irm 'https://cursor.com/install?win32=true' | iex",
        windows_bundled_candidates=(
            "%LOCALAPPDATA%/cursor-agent/cursor-agent.exe",
            "%LOCALAPPDATA%/cursor-agent/cursor-agent.cmd",
        ),
        windows_bundled_patterns=(
            "%LOCALAPPDATA%/cursor-agent/versions/{version}*/cursor-agent.exe",
        ),
        auth_args=("status", "--format", "json"),
        auth_signed_in_key="isAuthenticated",
        background_time_limit=(
            "Designed deferral: no equivalent unattended background time limit "
            "is documented for Cursor CLI print mode. No Claude timeout "
            "variable is applied. Docs checked 2026-10-20: "
            "https://cursor.com/docs/cli/headless"
        ),
    ),
)

if tuple(manifest.harness_id for manifest in HARNESS_CLI_MANIFESTS) != (
    CANONICAL_HARNESS_IDS
):
    raise RuntimeError("native CLI manifests must cover every harness family")

HARNESS_CLI_BY_ID = {
    manifest.harness_id: manifest for manifest in HARNESS_CLI_MANIFESTS
}


def harness_cli_manifest(harness_id: str) -> HarnessCliManifest:
    try:
        return HARNESS_CLI_BY_ID[harness_id]
    except KeyError as exc:
        raise ValueError(f"unknown harness id: {harness_id!r}") from exc


def harness_cli_executables() -> tuple[str, ...]:
    return tuple(manifest.executable for manifest in HARNESS_CLI_MANIFESTS)


VSCODE_CLI_BY_SURFACE = {
    manifest.vscode_surface_id: manifest
    for manifest in HARNESS_CLI_MANIFESTS
    if manifest.vscode_surface_id
}


def harness_vscode_surfaces() -> tuple[str, ...]:
    return tuple(VSCODE_CLI_BY_SURFACE)


def harness_cli_probe_commands() -> dict[str, tuple[str, ...]]:
    return {
        manifest.surface_id: (manifest.executable, *manifest.version_args)
        for manifest in HARNESS_CLI_MANIFESTS
    }


__all__ = [
    "HARNESS_CLI_BY_ID",
    "HARNESS_CLI_MANIFESTS",
    "HarnessCliManifest",
    "VSCODE_CLI_BY_SURFACE",
    "harness_vscode_surfaces",
    "harness_cli_executables",
    "harness_cli_manifest",
    "harness_cli_probe_commands",
]
