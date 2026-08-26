from __future__ import annotations

import json
import sqlite3
from typing import Any

from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
)

from runtime.api.domain.machine_qa_fixture_test_support import (
    FakeRemote,
    fixture_runner,
)
from yoke_core.domain.host_control_runner import HostActionResult
from yoke_core.domain.ssh_mac_full_reset_contract import (
    PRESERVED_HOME_ENTRIES,
    YOKE_ABSENT_RELATIVE_DIRECTORIES,
    YOKE_ABSENT_RELATIVE_FILES,
    YOKE_ABSENT_TEMP_FILES,
)

GOLDEN_BASELINE_PATH = "/Users/Shared/yoke-golden/tester-home"
# What the captured baseline puts back: a real user's shell, their own tools on
# their own PATH, and no Yoke anywhere.
BASELINE_STARTUP_FILES = {
    "/Users/tester/.zprofile": 'export PATH="$HOME/.local/bin:$PATH"\n',
    "/Users/tester/.zshenv": "",
}
BASELINE_PATHS = frozenset(
    {
        "/Users/tester/.local/bin/claude",
        "/Users/tester/.claude.json",
        "/Users/tester/Documents/notes.txt",
    }
)


class FakeHostControl:
    home = "/Users/tester"
    shell = "/bin/zsh"
    xdg_bin_home = None
    golden_baseline_path = GOLDEN_BASELINE_PATH

    def __init__(
        self,
        *,
        refuse_ssh_state: bool = False,
        refuse_full_reset: bool = False,
        refuse_user_equivalence: bool = False,
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
        self.refuse_user_equivalence = refuse_user_equivalence
        self.case_calls = 0
        self.full_reset_calls = 0
        self.fixture_remotes: list[FakeRemote] = []
        self.existing_paths = {
            "/Users/tester/.yoke/config.json",
            "/Users/tester/.ssh/authorized_keys",
            "/Library/Developer/CommandLineTools/usr/bin/git",
            "/Users/tester/code/checkout/.git/config",
            *BASELINE_PATHS,
            *(
                f"/Users/tester/{suffix}"
                for suffix in (
                    *YOKE_ABSENT_RELATIVE_DIRECTORIES,
                    *YOKE_ABSENT_RELATIVE_FILES,
                )
            ),
            *YOKE_ABSENT_TEMP_FILES,
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
        """Model the restore: the home becomes the baseline, minus what is kept."""
        self.full_reset_calls += 1
        if self.refuse_full_reset:
            return HostActionResult(
                False,
                {"paths": [{"path": self.home, "outcome": "reset-failed"}]},
                "test_mac_reset_failed",
            )
        preserved = {
            path
            for path in self.existing_paths
            if any(
                path.startswith(f"{self.home}/{entry}/")
                for entry in PRESERVED_HOME_ENTRIES
            )
            or not path.startswith(f"{self.home}/")
        }
        self.existing_paths = {*BASELINE_PATHS, *preserved}
        self.files = dict(BASELINE_STARTUP_FILES)
        return HostActionResult(
            True,
            {
                "paths": [
                    {"path": self.golden_baseline_path, "outcome": "restored"},
                    {"path": self.home, "outcome": "reset-complete"},
                    *(
                        {"path": f"{self.home}/{entry}", "outcome": "preserved"}
                        for entry in PRESERVED_HOME_ENTRIES
                    ),
                ],
                "baseline_state": {
                    "golden_baseline_path": self.golden_baseline_path,
                    "restored_entries": len(BASELINE_PATHS),
                    "preserved_entries": list(PRESERVED_HOME_ENTRIES),
                },
                "process_state": {
                    "reaped_processes": 0,
                    "surviving_matches": 0,
                    "load_average": 1.0,
                },
            },
        )

    def prove_user_equivalent(self) -> HostActionResult:
        if self.refuse_user_equivalence:
            return HostActionResult(
                False,
                {"probes": [{"name": "harness cli signed in", "ok": False}]},
                "baseline_probe_failed",
            )
        return HostActionResult(
            True,
            {"probes": [{"name": "harness cli signed in", "ok": True}]},
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
            required_capability_kinds TEXT NOT NULL DEFAULT '[]',
            verdict_path TEXT NOT NULL,
            verdict_contract TEXT NOT NULL,
            evidence_contract TEXT NOT NULL,
            success_policy_id TEXT NOT NULL,
            success_policy_params TEXT NOT NULL,
            concurrency_mode TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            actor_id INTEGER,
            ended_at TEXT
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            target_kind TEXT NOT NULL,
            scope TEXT NOT NULL,
            claim_type TEXT NOT NULL DEFAULT 'exclusive',
            claimed_at TEXT NOT NULL,
            last_heartbeat TEXT,
            released_at TEXT,
            release_reason TEXT,
            reason TEXT,
            reason_intent TEXT,
            release_reason_intent TEXT
        );
        CREATE UNIQUE INDEX idx_work_claims_active_qa_admission
        ON work_claims(scope)
        WHERE released_at IS NULL AND target_kind='qa_admission';
        INSERT INTO projects(id,slug,name,public_item_prefix)
        VALUES(1,'yoke','Yoke','YOK');
        """
    )
    return conn


def register_test_machine(
    conn: sqlite3.Connection,
    *,
    project_id: int = 1,
    resource_name: str = "mac-mini-lab",
    created_at: str = "2026-08-01T00:00:00Z",
) -> None:
    """Declare that a project operates a named physical host.

    The registrar is whichever project declared the host first, so callers
    state ``created_at`` rather than relying on wall clock ordering.
    """
    conn.execute(
        "INSERT INTO project_capabilities(project_id,type,settings,created_at) "
        "VALUES(?,?,?,?)",
        (
            project_id,
            TEST_MACHINE_CAPABILITY,
            json.dumps(
                {
                    "resource_name": resource_name,
                    "host": "test-mac.local",
                    "user": "yoke-test",
                    "operating_notes": "Do not interrupt an active lease.",
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            created_at,
        ),
    )
    conn.commit()


__all__ = ["FakeHostControl", "make_conn", "register_test_machine"]
