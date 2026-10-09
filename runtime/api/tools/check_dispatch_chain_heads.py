"""Prove served chain get/list diagnostics through registered read commands."""

from __future__ import annotations

import argparse
import json
import subprocess


def _read(environment, *args):
    result = subprocess.run(
        ["yoke", "--env", environment, *args],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    args = parser.parse_args()
    try:
        selected = _read(
            args.environment,
            "db",
            "read",
            "SELECT ir.public_ref, iw.branch FROM epic_dispatch_chains c "
            "JOIN item_refs ir ON ir.item_id=c.epic_id "
            "JOIN item_worktrees iw ON iw.id=c.item_worktree_id "
            "ORDER BY c.id DESC LIMIT 1",
            "--format",
            "lines",
        ).strip()
        if not selected:
            raise ValueError(
                "chain_probe_missing: select an environment with a persisted chain and retry"
            )
        epic, worktree = selected.split("|", 1)
        for operation in ("get", "list"):
            command = [
                "workflow-item",
                "epic-dispatch-chain",
                operation,
                "--epic",
                epic,
            ]
            if operation == "get":
                command += ["--worktree", worktree]
            envelope = json.loads(_read(args.environment, *command, "--json"))
            if not envelope.get("success"):
                raise ValueError(
                    f"chain_probe_refused: {envelope.get('error')}; restore the registered read and retry"
                )
            result = envelope["result"]
            if not isinstance(result.get("head_dispatch"), list):
                raise ValueError(
                    "head_dispatch_unserved: deploy the diagnostic response and retry"
                )
            text = _read(args.environment, *command)
            if not text.startswith(result["body"] + "\n"):
                raise ValueError(
                    "chain_body_changed: reconcile the read-only probe with current chain state and retry"
                )
            for head in result["head_dispatch"]:
                if head["decision"] not in {"resumable", "busy", "blocked", "unknown"}:
                    raise ValueError(
                        "head_decision_invalid: inspect the served response and correct it"
                    )
                if not head.get("reason") or "holder_session_id" not in head:
                    raise ValueError(
                        "head_evidence_missing: inspect the served response and correct it"
                    )
                if f"head task {head['task_num']}: " not in text:
                    raise ValueError(
                        "head_diagnostic_missing: update the CLI adapter and retry"
                    )
            print(
                f"{operation}: {epic}/{worktree}; head_dispatch={result['head_dispatch']}; default and JSON reads passed"
            )
        return 0
    except (ValueError, subprocess.SubprocessError) as exc:
        print(f"chain_probe_failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
