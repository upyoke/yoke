"""Run signed-in native CLIs against candidate wheels in a disposable local Yoke."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile


STATUS_PROMPT = "run `yoke status` in the shell, then stop"
DENIAL_PROMPT = (
    "For a hook diagnostic, attempt exactly once in the shell: "
    "`python3 -c 'import yoke_core.api.service_client'`. "
    "Let the hook refuse it; do not find another route or retry. Then stop."
)
EXECUTORS = {"claude": "claude-code", "codex": "codex", "cursor": "cursor"}
BINARIES = {"claude": "claude", "codex": "codex", "cursor": "cursor-agent"}


class ProofFailure(RuntimeError):
    """A named assertion or prerequisite failed; captures explain recovery."""


class Commands:
    def __init__(self, root: Path, env: dict[str, str]):
        self.root, self.env = root, env
        self.sequence = 0

    def run(self, name, argv, *, cwd, accepted=(0,), timeout=900):
        self.sequence += 1
        capture = self.root / f"{self.sequence:02d}-{name}.txt"
        print(f"real-harness step={name} capture={capture}", flush=True)
        try:
            result = subprocess.run(
                argv,
                cwd=cwd,
                env=self.env,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            capture.write_text(str(exc), encoding="utf-8")
            raise ProofFailure(
                f"harness_command_unavailable: {name}; inspect {capture}, "
                "repair the named executable or stalled step, then rerun"
            ) from exc
        capture.write_text(
            f"argv={argv!r}\nexit={result.returncode}\n{result.stdout}\n{result.stderr}",
            encoding="utf-8",
        )
        if result.returncode not in accepted:
            raise ProofFailure(
                f"harness_command_failed: {name} exit={result.returncode}; "
                f"inspect {capture}, repair the prerequisite and rerun"
            )
        return result

    def document(self, name, argv, *, cwd):
        result = self.run(name, argv, cwd=cwd)
        try:
            value = json.loads(result.stdout)
            if value.get("success") is False:
                raise ValueError(value.get("error"))
            return value.get("result", value)
        except (ValueError, AttributeError) as exc:
            raise ProofFailure(
                f"harness_evidence_read_failed: {name}; inspect its capture and "
                "repair local-universe access before rerunning"
            ) from exc


def native_argv(harness: str, prompt: str) -> list[str]:
    if harness == "claude":
        return ["claude", "--print", prompt, "--allowedTools", "Bash"]
    if harness == "codex":
        return ["codex", "exec", "--sandbox", "workspace-write", "--json", prompt]
    return ["cursor-agent", "--print", "--trust", "--force", prompt]


def prove(commands: Commands, yoke: str, project: Path, harness: str, before: set):
    sessions = commands.document(
        "registered-sessions", [yoke, "sessions", "list", "--json"], cwd=project
    )["rows"]
    rows = [row for row in sessions if row["session_id"] not in before]
    rows = [row for row in rows if row.get("workspace") == str(project)]
    if len(rows) != 1 or rows[0].get("executor") != EXECUTORS[harness]:
        raise ProofFailure(
            "native_registration_not_proved: expected exactly one new native "
            "session at the fixture workspace; inspect registration/hook captures"
        )
    row = rows[0]
    events = commands.document(
        "native-hook-events",
        [
            yoke,
            "events",
            "query",
            "--session",
            row["session_id"],
            "--limit",
            "1000",
            "--json",
        ],
        cwd=project,
    )["rows"]
    dispatches = []
    for event in events:
        if event["event_name"] in {"HookExecutionFailed", "HarnessSessionHookFailed"}:
            raise ProofFailure("native_hook_failed: repair the recorded hook failure")
        if event["event_name"] != "HookDispatchTelemetry":
            continue
        envelope = event["envelope"]
        envelope = json.loads(envelope) if isinstance(envelope, str) else envelope
        context = envelope["context"]
        if envelope["hook_event_name"] == "PreToolUse" and (
            context.get("timed_out") or not context.get("chain_length")
        ):
            raise ProofFailure(
                "native_hook_not_evaluated: repair timed-out/empty chain"
            )
        dispatches.append(
            {
                "event_id": event["event_id"],
                "hook": envelope["hook_event_name"],
                "decision": context.get("decision_outcome"),
            }
        )
    if not dispatches:
        raise ProofFailure(
            "native_hook_evidence_unavailable: capture native hook records and "
            "rerun; missing telemetry establishes no product verdict"
        )
    return {
        "session_id": row["session_id"],
        "executor": row["executor"],
        "workspace": row["workspace"],
        "executor_version": row.get("executor_version"),
        "dispatches": dispatches,
    }


def run(args) -> None:
    root = Path(tempfile.mkdtemp(prefix="yoke-real-harness-"))
    report = {"ok": False, "harness": args.harness, "os": platform.system()}
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("YOKE_", "CODEX_", "CLAUDECODE"))
        and key not in {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CURSOR_API_KEY"}
    }
    commands = Commands(root, env)
    yoke, project = None, root / "project"
    onboarded = False
    try:
        wheels = root / "wheels"
        wheels.mkdir()
        with tarfile.open(args.wheels) as archive:
            members = archive.getmembers()
            if not members or any(
                not member.isfile()
                or "/" in member.name
                or not member.name.endswith(".whl")
                for member in members
            ):
                raise ProofFailure("candidate_wheels_invalid: stage only wheel files")
            archive.extractall(wheels, members=members)
        version = commands.run(
            "native-version", [BINARIES[args.harness], "--version"], cwd=root
        )
        report["native_version"] = version.stdout.strip()
        versions = json.loads(args.versions_file.read_text(encoding="utf-8"))[
            args.harness
        ]
        if report["native_version"] != versions.get(platform.system()):
            raise ProofFailure("native_version_mismatch: refresh golden/version; rerun")
        venv = root / "venv"
        commands.run("candidate-venv", ["uv", "venv", str(venv)], cwd=root)
        commands.run(
            "candidate-install",
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(venv / "bin/python3"),
                *map(str, sorted(wheels.glob("*.whl"))),
            ],
            cwd=root,
        )
        env["PATH"] = str(venv / "bin") + os.pathsep + env["PATH"]
        yoke = str(venv / "bin/yoke")
        owner_key = commands.run(
            "project-owner-contract",
            [
                str(venv / "bin/python3"),
                "-c",
                "from yoke_contracts.qa_project_ownership import OWNER_ENV; print(OWNER_ENV)",
            ],
            cwd=root,
        ).stdout.strip()
        env[owner_key] = root.name
        project.mkdir()
        commands.run("git-init", ["git", "init", "--initial-branch=main"], cwd=project)
        (project / "README.md").write_text(
            "# Disposable native harness fixture\n", encoding="utf-8"
        )
        commands.run("git-add", ["git", "add", "README.md"], cwd=project)
        commands.run(
            "git-commit",
            [
                "git",
                "-c",
                "user.name=Harness QA",
                "-c",
                "user.email=harness@yoke.local",
                "commit",
                "-m",
                "Initialize fixture",
            ],
            cwd=project,
        )
        commands.document(
            "onboard",
            [
                yoke,
                "onboard",
                "--local",
                "--non-interactive",
                "--yes",
                "--json",
                "--machine-github",
                "disabled",
                "--github-adoption",
                "disabled",
                "--project-mode",
                "local-checkout",
                "--checkout",
                str(project),
                "--project-slug",
                "harness",
                "--project-name",
                "Harness QA",
                "--default-branch",
                "main",
                "--public-item-prefix",
                "HQA",
            ],
            cwd=project,
        )
        onboarded = True
        env["YOKE_ROOT"] = str(project)
        env["XDG_BIN_HOME"] = str(venv / "bin")
        resolved = commands.run(
            "hook-launcher",
            [
                "/bin/sh",
                "-c",
                'PATH="${XDG_BIN_HOME:-$HOME/.local/bin}:$PATH"; command -v yoke',
            ],
            cwd=project,
        )
        if resolved.stdout.strip() != yoke:
            raise ProofFailure("candidate_hook_launcher_not_selected")
        report["candidate_launcher"] = yoke
        proofs = report["proofs"] = []
        for name, prompt in (("status", STATUS_PROMPT), ("denial", DENIAL_PROMPT)):
            before = {
                row["session_id"]
                for row in commands.document(
                    "sessions-before", [yoke, "sessions", "list", "--json"], cwd=project
                )["rows"]
            }
            commands.run(
                "native-" + name,
                native_argv(args.harness, prompt),
                cwd=project,
                accepted=tuple(range(256)),
                timeout=120,
            )
            proof = prove(commands, yoke, project, args.harness, before)
            proofs.append({"probe": name, **proof})
            expected = "allow" if name == "status" else "deny"
            if not any(
                row["hook"] == "PreToolUse" and row["decision"] == expected
                for row in proof["dispatches"]
            ):
                raise ProofFailure(
                    f"native_{name}_decision_not_proved: require a recorded {expected} "
                    "PreToolUse decision; inspect hook evidence and rerun"
                )
        report["ok"] = True
    except Exception as exc:
        report["failure"] = str(exc)
        raise
    finally:
        if onboarded:
            retirement = [
                "projects",
                "retire",
                "--project",
                "harness",
                "--reason",
                "QA done",
            ]
            for name, operation in (
                ("project-retire", retirement),
                ("relay-uninstall", ["relay", "uninstall"]),
                ("machine-retire", ["machine", "retire", "--confirm"]),
                ("postgres-stop", ["local-postgres", "stop"]),
            ):
                try:
                    commands.run(name, [yoke, *operation, "--json"], cwd=project)
                except ProofFailure as exc:
                    report.setdefault("cleanup_failures", []).append(str(exc))
                    report["ok"] = False
        (root / "report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report), flush=True)
        if not report["ok"]:
            raise ProofFailure(f"real_harness_not_proved: {root}/report.json; rerun")
    print("REAL_HARNESS_PROVED", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", choices=EXECUTORS, required=True)
    parser.add_argument("--versions-file", type=Path, required=True)
    parser.add_argument("--wheels", type=Path, required=True)
    args = parser.parse_args()
    print("REAL_HARNESS_STARTED", flush=True)
    try:
        run(args)
    except (ProofFailure, OSError, ValueError) as exc:
        print(f"real-harness failed: {exc}", flush=True)
        return 1
    finally:
        print("REAL_HARNESS_COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
