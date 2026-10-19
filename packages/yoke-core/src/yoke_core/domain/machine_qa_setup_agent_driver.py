"""Play a coding agent through ``yoke setup --agent`` for Machine QA journeys.

Agent-presentation installer cases run this on the test machine with the
installed candidate's interpreter. It follows the documented agent loop: it
shows the person each question the way an agent would (question, detail,
choices, guidance), answers only the scripted choices, shows a browser
step's link and match code once, then plays the person saying "done" by
running ``yoke setup --agent`` again each poll interval until the step moves
on, and hands a secret question to the person in ``yoke setup --tui`` in the
same terminal, then resumes ``yoke setup --agent``. It never reads, receives
or types a secret.

    python -m yoke_core.domain.machine_qa_setup_agent_driver \\
        --connect URL --stop-at KEY [--answer KEY=VALUE ...]

It prints ``agent-presentation-reached: KEY`` when setup asks ``--stop-at``
and exits 0; a refusal, failure or unexpected end prints its reason and
recovery and exits 1.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable

from yoke_contracts.machine_authorization import CODE_TTL_SECONDS, MATCH_CODE_LABEL

REACHED = "agent-presentation-reached:"
_MAX_TURNS = 20


def _yoke() -> str:
    return str(Path(sys.executable).parent / "yoke")


def _show(line: dict[str, Any]) -> None:
    """Print what an agent shows the person for one setup line."""
    state = line.get("state")
    if state == "browser":
        human = line.get("human") or {}
        print(f"{MATCH_CODE_LABEL} {human.get('user_code', '')}")
        print(f"Open: {human.get('url', '')}")
        print(human.get("instructions", ""))
        print(line.get("guidance", ""), flush=True)
        return
    if state in {"refused", "failed"}:
        print(f"{line.get('reason')}: {line.get('recovery')}")
    if line.get("question"):
        print(f"Question: {line['question']}")
    for detail in line.get("detail") or []:
        print(detail.strip())
    for answer in line.get("answers") or []:
        print(f"- {answer.get('label')}: {answer.get('description')}")
    if line.get("guidance"):
        print(f"Guidance: {line['guidance']}")
    print("", flush=True)


def _run_agent(
    argv: list[str], show: Callable[[dict[str, Any]], None] = _show
) -> dict[str, Any] | None:
    """Run one agent call, showing every line; return its last line."""
    process = subprocess.Popen(
        [_yoke(), "setup", "--agent", *argv],
        stdout=subprocess.PIPE,
        text=True,
    )
    last = None
    assert process.stdout is not None
    for raw in process.stdout:
        if not raw.lstrip().startswith("{"):
            continue
        last = json.loads(raw)
        show(last)
    process.wait()
    return last


def _await_approval(line: dict[str, Any]) -> dict[str, Any] | None:
    """Ask setup again each poll interval until its browser step moves on."""
    wait = line.get("wait") or {}
    interval = float(wait.get("poll_interval_seconds") or 5)
    deadline = time.monotonic() + float(wait.get("max_seconds") or CODE_TTL_SECONDS)
    shown = (line.get("human") or {}).get("user_code")

    def show_changes(next_line: dict[str, Any]) -> None:
        nonlocal shown
        code = (next_line.get("human") or {}).get("user_code")
        if next_line.get("state") != "browser" or code != shown:
            shown = code
            _show(next_line)

    while time.monotonic() < deadline:
        time.sleep(interval)
        latest = _run_agent([], show=show_changes)
        if latest is None or latest.get("state") != "browser":
            return latest
    reason = "setup_agent_approval_not_finished"
    recovery = (
        "the browser step was not approved before its match code lapsed; "
        "rerun the case and approve while the code is shown"
    )
    print(f"{reason}: {recovery}")
    return {"state": "failed", "reason": reason, "recovery": recovery}


def drive(connect: str, stop_at: str, answers: dict[str, str]) -> int:
    line = _run_agent(["--connect", connect])
    for _turn in range(_MAX_TURNS):
        if line is None:
            print("setup_agent_no_answer: setup printed no JSON line; rerun the case.")
            return 1
        key = str(line.get("key") or "")
        if line.get("state") in {"refused", "failed"}:
            return 1
        if key == stop_at:
            print(f"{REACHED} {key}", flush=True)
            return 0
        if line.get("state") == "browser":
            line = _await_approval(line)
            continue
        if line.get("secret"):
            print(
                "Handing this step to the person: finish it privately in "
                "`yoke setup --tui`, then quit the wizard to return here.",
                flush=True,
            )
            subprocess.run([_yoke(), "setup", "--tui", "--connect", connect])
            line = _run_agent([])
            continue
        if key not in answers:
            print(
                f"setup_agent_unscripted_question: setup asked {key!r}, which "
                "this journey does not answer; update the case's scripted "
                "answers to match the current setup questions."
            )
            return 1
        line = _run_agent(["--answer", f"{key}={answers.pop(key)}"])
    print("setup_agent_turns_exhausted: setup kept asking; read the transcript.")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connect", required=True)
    parser.add_argument("--stop-at", required=True)
    parser.add_argument("--answer", action="append", default=[])
    parsed = parser.parse_args(argv)
    answers = dict(item.split("=", 1) for item in parsed.answer)
    return drive(parsed.connect, parsed.stop_at, answers)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["REACHED", "drive", "main"]
