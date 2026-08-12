from __future__ import annotations

import sqlite3

from runtime.api.domain.machine_qa_fixture_test_support import (
    FakeRemote,
    fixture_runner,
)
from yoke_core.domain.host_control_runner import HostActionResult
from yoke_core.domain.ssh_mac_full_reset_contract import (
    EVIDENCE_SOURCE_PATH,
    HOMEBREW_PATH,
    RESET_RELATIVE_DIRECTORIES,
    RESET_RELATIVE_FILES,
    RESET_TEMP_FILES,
    RETAINED_EVIDENCE_DIRECTORY,
    STARTUP_FILE_NAMES,
    TOKEN_BACKUP_DIRECTORY,
    TOKEN_LOCATIONS,
)


def _clean_startup_text(content: str) -> str:
    output: list[str] = []
    skipping = False
    for line in content.splitlines(keepends=True):
        if "BEGIN YOKE MANAGED PATH" in line or "BEGIN YOKE TEST HOST BASELINE" in line:
            skipping = True
            continue
        if "END YOKE MANAGED PATH" in line or "END YOKE TEST HOST BASELINE" in line:
            skipping = False
            continue
        if skipping:
            continue
        if "uv was installed" in line:
            continue
        if '. "$HOME/.local/bin/env"' in line:
            continue
        if 'source "$HOME/.local/bin/env"' in line:
            continue
        if ".local/bin" in line and "PATH" in line:
            continue
        output.append(line)
    return "".join(output)


class FakeHostControl:
    home = "/Users/tester"
    shell = "/bin/zsh"
    xdg_bin_home = None

    def __init__(
        self,
        *,
        refuse_ssh_state: bool = False,
        refuse_full_reset: bool = False,
    ) -> None:
        self.files: dict[str, str] = {
            "/Users/tester/.zprofile": (
                'export PATH="$HOME/.local/bin:$PATH"\n'
                "# >>> BEGIN YOKE MANAGED PATH >>>\nold\n"
                "# <<< END YOKE MANAGED PATH <<<\n"
            ),
            "/Users/tester/.zshenv": "",
        }
        self.refuse_ssh_state = refuse_ssh_state
        self.refuse_full_reset = refuse_full_reset
        self.case_calls = 0
        self.full_reset_calls = 0
        self.fixture_remotes: list[FakeRemote] = []
        self.token_files = {
            source: (label.casefold() + "-token-bytes").encode()
            for source, _backup, label in TOKEN_LOCATIONS
        }
        self.token_backups: dict[str, bytes] = {}
        self.existing_paths = {
            "/Users/tester/.yoke/config.json",
            "/Users/tester/.yoke/installer-smoke-evidence/campaign/report.json",
            "/Users/tester/.ssh/authorized_keys",
            "/Library/Developer/CommandLineTools/usr/bin/git",
            "/Users/tester/code/checkout/.git/config",
            HOMEBREW_PATH,
            *(
                f"/Users/tester/{suffix}"
                for suffix in (*RESET_RELATIVE_DIRECTORIES, *RESET_RELATIVE_FILES)
            ),
            *RESET_TEMP_FILES,
        }

    def check_connection(self) -> HostActionResult:
        return HostActionResult(
            True,
            {"transport": "ssh", "credential_echo": "top-secret"},
        )

    def check_terminal_bridge(self) -> HostActionResult:
        return HostActionResult(True, {"terminal": True, "screenshot": True})

    def read_text(self, path: str) -> str | None:
        return self.files.get(path)

    def write_text(self, path: str, content: str) -> None:
        self.files[path] = content

    def create_fixture_operation_runner(self):
        remote = FakeRemote()
        remote.existing.add("/Users/tester/.yoke/secrets/stage.token")

        def project_product_state(command: str) -> None:
            if " path fix --yes" not in command:
                return
            block = (
                "# >>> BEGIN YOKE MANAGED PATH >>>\n"
                'export PATH="$HOME/.local/bin:$PATH"\n'
                "# <<< END YOKE MANAGED PATH <<<\n"
            )
            self.files["/Users/tester/.zprofile"] = block
            self.files["/Users/tester/.zshenv"] = block

        remote.on_successful_command = project_product_state
        self.fixture_remotes.append(remote)
        return fixture_runner(remote)

    def reset_installer_test_host(self) -> HostActionResult:
        self.full_reset_calls += 1
        if self.refuse_full_reset:
            return HostActionResult(
                False,
                {"paths": [{"path": self.home, "outcome": "reset-failed"}]},
                "test_mac_reset_failed",
            )
        preserved_tokens = dict(self.token_files)
        self.token_backups = {
            f"{self.home}/{TOKEN_BACKUP_DIRECTORY}/{backup}": preserved_tokens[source]
            for source, backup, _label in TOKEN_LOCATIONS
            if source in preserved_tokens
        }
        evidence = f"{self.home}/{EVIDENCE_SOURCE_PATH}"
        retained_evidence = f"{self.home}/{RETAINED_EVIDENCE_DIRECTORY}"
        moved_evidence = {
            retained_evidence
            + "/reset.fake/installer-smoke-evidence"
            + path.removeprefix(evidence)
            for path in self.existing_paths
            if path == evidence or path.startswith(evidence + "/")
        }
        protected = {
            path
            for path in self.existing_paths
            if path.startswith(f"{self.home}/.ssh/")
            or path.startswith("/Library/Developer/CommandLineTools/")
        }
        reset_targets = {
            f"{self.home}/{suffix}"
            for suffix in (*RESET_RELATIVE_DIRECTORIES, *RESET_RELATIVE_FILES)
        }
        reset_targets.update(RESET_TEMP_FILES)
        self.existing_paths = {
            path
            for path in self.existing_paths
            if path in protected
            or (
                not any(
                    path == target or path.startswith(target.rstrip("/") + "/")
                    for target in reset_targets
                )
                and not path.startswith(f"{self.home}/code/")
                and not (
                    path.startswith(f"{self.home}/.yoke/") and path not in protected
                )
            )
        }
        self.existing_paths.update(moved_evidence)
        self.token_files.clear()
        self.token_files.update(preserved_tokens)
        for name in STARTUP_FILE_NAMES:
            path = f"{self.home}/{name}"
            if path in self.files:
                self.files[path] = _clean_startup_text(self.files[path])
        return HostActionResult(
            True,
            {
                "paths": [
                    {"path": self.home, "outcome": "reset-complete"},
                    {
                        "path": f"{self.home}/{TOKEN_BACKUP_DIRECTORY}",
                        "outcome": "mode-0700",
                    },
                    {"path": evidence, "outcome": "moved"},
                    {"path": retained_evidence, "outcome": "preserved"},
                ]
            },
        )

    def probe_path(self, surface: str) -> list[str]:
        target = (
            self.files["/Users/tester/.zprofile"]
            if surface == "login"
            else self.files["/Users/tester/.zshenv"]
        )
        present = ".local/bin" in target and "PATH" in target
        if surface == "ssh" and self.refuse_ssh_state:
            present = not present
        return ["/Users/tester/.local/bin", "/usr/bin"] if present else ["/usr/bin"]

    def run_terminal_case(self, **kwargs) -> HostActionResult:
        self.case_calls += 1
        return HostActionResult(True, {"transcript": "done"})

    def run_terminal_recipe(self, **kwargs) -> HostActionResult:
        self.case_calls += 1
        return HostActionResult(
            True,
            {
                "transcript": "done",
                "actions": list(kwargs["config"]["actions"]),
            },
        )

    def run_machine_assertions(self, assertions) -> HostActionResult:
        self.case_calls += 1
        return HostActionResult(
            True,
            {"output": "credential=top-secret", "assertion_count": len(assertions)},
        )


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            public_item_prefix TEXT NOT NULL
        );
        CREATE TABLE project_capabilities (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            settings TEXT DEFAULT '{}',
            verified_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(project_id, type)
        );
        CREATE TABLE qa_methods (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_ref TEXT,
            project_id INTEGER,
            runner_id TEXT NOT NULL,
            required_capability_kind TEXT,
            verdict_path TEXT NOT NULL,
            verdict_contract TEXT NOT NULL,
            evidence_contract TEXT NOT NULL,
            success_policy_id TEXT NOT NULL,
            success_policy_params TEXT NOT NULL,
            concurrency_mode TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE coordination_leases (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            lease_key TEXT NOT NULL,
            session_id TEXT NOT NULL,
            actor_id TEXT,
            acquired_at TEXT NOT NULL,
            heartbeat_at TEXT,
            released_at TEXT,
            release_reason TEXT
        );
        CREATE UNIQUE INDEX idx_coordination_leases_live
        ON coordination_leases(project_id, lease_key)
        WHERE released_at IS NULL;
        INSERT INTO projects(id,slug,name,public_item_prefix)
        VALUES(1,'yoke','Yoke','YOK');
        """
    )
    return conn


__all__ = ["FakeHostControl", "make_conn"]
