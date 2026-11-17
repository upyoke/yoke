"""Exercise resolved-question replacement through the deployed Stage CLI.

The probe owns disposable fixture records. It never registers or changes the
worker's launch session; its separate fixture session is ended on completion.
"""

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    if args.environment != "stage":
        parser.error(
            "supersession_proof_disposable_only: select Stage for fixture writes"
        )
    fixture_session = str(uuid.uuid4())
    item_ref = new_id = None
    registered = False

    def call(*command, stdin=None, fixture=True):
        argv = ["yoke", "--env", args.environment, *command, "--json"]
        if fixture:
            argv.extend(["--session-id", fixture_session])
        result = subprocess.run(
            argv, input=stdin, text=True, capture_output=True, check=False
        )
        try:
            reply = json.loads(result.stdout)
        except ValueError:
            reply = {}
        if result.returncode or not reply.get("success"):
            raise RuntimeError(
                f"supersession_proof_command_failed: {command!r}: "
                f"{result.stdout} {result.stderr}; inspect the named refusal and "
                "restore the Stage QA fixture access before rerunning this case"
            )
        return reply["result"]

    try:
        # This is a fresh test identity, separate from the launched worker.
        call(
            "sessions",
            "begin",
            "--executor",
            "codex",
            "--provider",
            "openai",
            "--requested-model",
            "gpt-6.1-sol",
            "--workspace",
            str(Path.cwd()),
        )
        registered = True
        print(f"Stage fixture session: {fixture_session}", flush=True)
        call(
            "workflow",
            "execution-instruction",
            "resolve",
            "--workflow",
            "dash",
            "--project",
            args.project,
            "--full",
        )
        created = call(
            "items",
            "create",
            "--project",
            args.project,
            "--workflow",
            "dash",
            "--title",
            "Disposable decision replacement QA fixture",
            "--stdin",
            "--execution-instructions-considered",
            stdin="Disposable Stage fixture for resolved operator question replacement; cancel after the probe.",
        )
        item_ref = created.get("public_ref") or created.get("item", {}).get(
            "public_ref"
        )
        if not item_ref:
            raise RuntimeError(
                "supersession_proof_fixture_missing: inspect the item create receipt and cancel its Stage fixture"
            )
        print(f"Stage fixture item: {item_ref}", flush=True)
        old = call(
            "decision-requests",
            "ask",
            "--project",
            args.project,
            "--item",
            item_ref,
            "--key",
            "replace-proof",
            "--question",
            "Disposable QA: which color?",
            "--option",
            "blue=Blue",
            "--no-freeform",
        )["request"]
        resolved = call(
            "decision-requests",
            "resolve",
            str(old["id"]),
            "blue",
            "--note",
            "Original QA resolution",
        )["request"]
        new = call(
            "decision-requests",
            "ask",
            "--project",
            args.project,
            "--item",
            item_ref,
            "--key",
            "replace-proof",
            "--question",
            "Disposable QA: revised color?",
            "--replaces",
            str(old["id"]),
        )["request"]
        new_id = new["id"]
        prior = call("decision-requests", "get", str(old["id"]))["request"]
        current = call("decision-requests", "get", str(new_id))["request"]
        assert prior["status"] == "superseded", prior
        assert prior["superseded_by_request_id"] == new_id, prior
        for field in (
            "resolution_action",
            "resolution_note",
            "resolution_actor_id",
            "resolved_at",
        ):
            assert prior[field] == resolved[field], (field, prior)
        assert current["status"] == "pending", current
        history = call("decision-requests", "list", "--mine", "--status", "superseded")[
            "questions"
        ]
        assert any(
            row["id"] == old["id"] and row["superseded_by_request_id"] == new_id
            for row in history
        ), history
        print(
            json.dumps(
                {
                    "old_request_id": old["id"],
                    "new_request_id": new_id,
                    "old_status": prior["status"],
                    "new_status": current["status"],
                    "resolution_preserved": True,
                    "fixture_item": item_ref,
                }
            )
        )
    finally:
        if new_id is not None:
            call(
                "decision-requests",
                "withdraw",
                str(new_id),
                "--reason",
                "Disposable QA completed",
            )
        if item_ref:
            call(
                "items",
                "cancel",
                item_ref,
                "--reason",
                "Disposable Stage QA fixture completed",
            )
        if registered:
            call("sessions", "end-if-empty")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, RuntimeError) as exc:
        sys.exit(
            f"supersession_proof_failed: {exc}; retain the printed fixture identities, fix the failed deployed behavior or setup, then rerun the case"
        )
