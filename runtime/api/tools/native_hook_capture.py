"""Refresh sanitized native hook fixtures on an operator-authorized, leased test host."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import shlex
import subprocess

REMOTE_SCRIPT = r'''
import json, os, pathlib, subprocess, sys, tempfile
from codex_trust import codex_hook_hashes

harness = sys.argv[1]
root = pathlib.Path(tempfile.mkdtemp(prefix="yoke-native-capture-"))
capture = root / "capture.jsonl"
recorder = root / "record.py"
recorder.write_text(r"""
import json, pathlib, sys
payload = json.load(sys.stdin)
command = payload.get("command", payload.get("tool_input", {}).get("command", ""))
denied = "git clean -fd" in command
with pathlib.Path(sys.argv[1]).open("a") as handle:
    handle.write(json.dumps({"event": sys.argv[3], "denied": denied, "payload": payload}) + "\n")
if sys.argv[2] == "cursor":
    print(json.dumps({"permission": "deny" if denied else "allow", "user_message": "Recording smoke denial", "agent_message": "Recording smoke denial; stop without retry"}))
elif denied and sys.argv[2] == "codex":
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "Recording smoke denial; stop without retry"}}))
elif denied:
    print("BLOCKED: recording smoke denial; stop without retry")
    sys.exit(2)
""")
env = dict(os.environ)
env["PATH"] = os.path.expanduser("~/.local/bin") + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
for key in tuple(env):
    if key.startswith("YOKE_") or key.startswith("CLAUDE_CODE_") or key in {"CLAUDE_SESSION_ID", "CODEX_THREAD_ID", "CURSOR_SESSION_ID"}:
        env.pop(key, None)
def command(event):
    import shlex
    return shlex.join(["/usr/bin/python3", str(recorder), str(capture), harness, event])
start, pre = ("sessionStart", "beforeShellExecution") if harness == "cursor" else ("SessionStart", "PreToolUse")
if harness == "cursor":
    document = {"version": 1, "hooks": {event: [{"command": command(event)}] for event in (start, pre)}}
else:
    document = {"hooks": {event: [{"hooks": [{"type": "command", "command": command(event)}]}] for event in (start, pre)}}
    document["hooks"][pre][0]["matcher"] = "Bash"
config = root / (".claude/settings.json" if harness == "claude" else f".{harness}/hooks.json")
config.parent.mkdir()
config.write_text(json.dumps(document))
subprocess.run(["git", "init", "--initial-branch=main"], cwd=root, env=env, check=True, capture_output=True)
subprocess.run(["git", "add", "."], cwd=root, env=env, check=True, capture_output=True)
subprocess.run(["git", "-c", "user.name=Smoke", "-c", "user.email=smoke@yoke.local", "commit", "-m", "Initialize capture project"], cwd=root, env=env, check=True, capture_output=True)
prompt = "Use the shell tool exactly twice in sequence: first printf smoke-allowed, then git clean -fd. The second tool is intentionally denied by a recording hook; do not retry it, and stop."
binary = "cursor-agent" if harness == "cursor" else harness
version = subprocess.run([binary, "--version"], env=env, text=True, capture_output=True, timeout=30)
if version.returncode:
    print(version.stderr)
    sys.exit(version.returncode)
if harness == "claude":
    argv = [binary, "-p", prompt, "--allowedTools", "Bash", "--tools", "Bash", "--max-turns", "4", "--setting-sources", "project"]
elif harness == "codex":
    argv = [binary, "exec", "-C", str(root), "-s", "workspace-write", "--ephemeral", "--json", "-c", "features.hooks=true"]
    state = ', '.join(json.dumps(str(config) + ':' + suffix) + ' = { trusted_hash = ' + json.dumps(digest) + ' }'
        for suffix, digest in codex_hook_hashes(config).items())
    argv += ["-c", 'hooks.state={' + state + '}']
    argv += [prompt]
else:
    argv = [binary, "-p", prompt, "--output-format", "json", "--trust"]
try:
    result = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True, timeout=180)
except subprocess.TimeoutExpired:
    print("native_capture_timeout: inspect retained scratch at", root)
    sys.exit(1)
rows = [json.loads(line) for line in capture.read_text().splitlines()] if capture.exists() else []
starts = [row for row in rows if row["event"] == start]
allows = [row for row in rows if row["event"] == pre and not row["denied"]]
denials = [row for row in rows if row["event"] == pre and row["denied"]]
if not starts or not allows or not denials:
    print("native_capture_incomplete:", {"start": len(starts), "allow": len(allows), "deny": len(denials), "exit": result.returncode}, "scratch:", root)
    print(result.stderr[-3000:])
    print(result.stdout[-3000:])
    sys.exit(1)
def redact(value, key=""):
    if isinstance(value, dict):
        return {name: redact(part, name) for name, part in value.items()}
    if isinstance(value, list):
        return [redact(part, key) for part in value]
    if key in {"session_id", "conversation_id", "thread_id", "tool_use_id", "turn_id", "prompt_id", "generation_id"}:
        return "<session>"
    if key in {"machine_id", "user_id", "account_id", "organization_id", "user_email", "email"}:
        return "<redacted>"
    if isinstance(value, str):
        if value.startswith("/"):
            return "<transcript>" if "transcript" in key.lower() else "<workspace>"
        return value.replace(str(root), "<workspace>").replace(str(pathlib.Path.home()), "<home>")
    return value
fixture = {"provenance": {"capture_source": "Native CLI hook stdin on a leased test host", "harness_version": version.stdout.strip(), "prompt": prompt},
    "session_start": redact(starts[0]["payload"]), "pre_tool_use_allowed": redact(allows[0]["payload"]), "pre_tool_use_denied": redact(denials[0]["payload"])}
print("YOKE_NATIVE_FIXTURE=" + json.dumps(fixture))
'''

GUI_DRIVER = r"""
import json, pathlib, shlex, subprocess, sys, time
root = pathlib.Path(sys.argv[1])
output, verdict = root / "gui-output.txt", root / "gui-verdict.json"
driver = root / "gui-driver.py"
argv = ["/usr/bin/python3", str(root / "capture.py"), sys.argv[2]]
driver.write_text("import json,pathlib,subprocess; "
    + "result=subprocess.run(" + repr(argv) + ",capture_output=True,text=True); "
    + "pathlib.Path(" + repr(str(output)) + ").write_text(result.stdout+'\\n'+result.stderr); "
    + "pathlib.Path(" + repr(str(verdict)) + ").write_text(json.dumps({'exit_code':result.returncode}))")
command = shlex.join(["/usr/bin/python3", str(driver)])
launch = subprocess.run(["/usr/bin/osascript", "-e", 'tell application "Terminal" to do script ' + json.dumps(command)], capture_output=True, text=True, timeout=10)
if launch.returncode:
    print("native_gui_capture_refused: " + launch.stderr.strip() + "; use the test-account operator to restore Terminal access")
    sys.exit(1)
deadline = time.monotonic() + 220
while not verdict.is_file() and time.monotonic() < deadline:
    time.sleep(.5)
if not verdict.is_file():
    print("native_gui_capture_timeout: inspect Terminal and retained recorder scratch at", root)
    sys.exit(1)
print(output.read_text())
sys.exit(json.loads(verdict.read_text())["exit_code"])
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--machine", required=True)
    parser.add_argument(
        "--harness", choices=("claude", "codex", "cursor"), required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--gui-session",
        action="store_true",
        help="Capture in the macOS GUI login session through Terminal.app.",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    trust = (
        root / "packages/yoke-contracts/src/yoke_contracts/codex_hook_trust.py"
    ).read_text()
    driver = "gui.py" if args.gui_session else "capture.py"
    driver_args = "str(p)," if args.gui_session else ""
    bootstrap = (
        "import base64,pathlib,tempfile,subprocess,sys; "
        "p=pathlib.Path(tempfile.mkdtemp(prefix='yoke-hook-recorder-')); "
        f"(p/'codex_trust.py').write_bytes(base64.b64decode({base64.b64encode(trust.encode()).decode()!r})); "
        f"(p/'capture.py').write_bytes(base64.b64decode({base64.b64encode(REMOTE_SCRIPT.encode()).decode()!r})); "
        f"(p/'gui.py').write_bytes(base64.b64decode({base64.b64encode(GUI_DRIVER.encode()).decode()!r})); "
        f"sys.exit(subprocess.call(['/usr/bin/python3',str(p/{driver!r}),{driver_args}{args.harness!r}]))"
    )
    remote = shlex.join(["/usr/bin/python3", "-c", bootstrap])
    result = subprocess.run(
        [
            "yoke",
            "test-machine",
            "exec",
            "--project",
            "yoke",
            "--machine",
            args.machine,
            "--",
            remote,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if result.returncode:
        print(result.stdout)
        print(result.stderr)
        return result.returncode
    markers = [
        line.removeprefix("YOKE_NATIVE_FIXTURE=")
        for line in result.stdout.splitlines()
        if line.startswith("YOKE_NATIVE_FIXTURE=")
    ]
    if len(markers) != 1:
        print(
            "native_capture_proof_missing: expected one native fixture; inspect test-machine output"
        )
        return 1
    args.output.write_text(
        json.dumps(json.loads(markers[0]), indent=2) + "\n", encoding="utf-8"
    )
    print(f"Captured sanitized native fixture: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
