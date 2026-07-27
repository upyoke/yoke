from __future__ import annotations

import sqlite3

from yoke_core.domain.host_control_executor import HostActionResult


class FakeHostControl:
    home = "/Users/tester"
    shell = "/bin/zsh"
    xdg_bin_home = None

    def __init__(self, *, refuse_ssh_state: bool = False) -> None:
        self.files: dict[str, str] = {
            "/Users/tester/.zprofile": (
                'export PATH="$HOME/.local/bin:$PATH"\n'
                "# >>> BEGIN YOKE MANAGED PATH >>>\nold\n"
                "# <<< END YOKE MANAGED PATH <<<\n"
            ),
            "/Users/tester/.zshenv": "",
        }
        self.refuse_ssh_state = refuse_ssh_state
        self.case_calls = 0

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

    def probe_path(self, surface: str) -> list[str]:
        target = (
            self.files["/Users/tester/.zprofile"]
            if surface == "login"
            else self.files["/Users/tester/.zshenv"]
        )
        present = 'path=("$__yoke_test_bin" $path)' in target
        if surface == "ssh" and self.refuse_ssh_state:
            present = not present
        return ["/Users/tester/.local/bin", "/usr/bin"] if present else ["/usr/bin"]

    def run_terminal_case(self, **kwargs) -> HostActionResult:
        self.case_calls += 1
        return HostActionResult(True, {"transcript": "done"})

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
            executor_id TEXT NOT NULL,
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
