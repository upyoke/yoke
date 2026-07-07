#!/usr/bin/env python3
import glob
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request

region = os.environ["REGION"]
repo = os.environ["GITHUB_REPO"]
token_param = os.environ["GITHUB_TOKEN_PARAMETER"]
asg_name = os.environ["ASG_NAME"]
prefix = os.environ["HOST_PREFIX"]
idle_minutes = int(os.environ["IDLE_MINUTES"])
labels = set(v.lower() for v in os.environ["RUNNER_LABELS"].split(",") if v)
state = "/var/lib/yoke-runner-fleet/idle-since"
runner_root = "/opt/actions-runner"
tmp_root = "/tmp"


def run(args):
    return subprocess.check_output(args, text=True).strip()


def run_best_effort(args, timeout=120):
    subprocess.run(
        args,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
    )


def reset():
    try:
        os.unlink(state)
    except FileNotFoundError:
        pass


token = run([
    "aws", "ssm", "get-parameter", "--with-decryption", "--name",
    token_param, "--query", "Parameter.Value", "--output", "text",
    "--region", region,
])


def github_api(path, method="GET"):
    req = urllib.request.Request(
        "https://api.github.com/repos/" + repo + path,
        headers=dict([
            ("Authorization", "Bearer " + token),
            ("Accept", "application/vnd.github+json"),
            ("X-GitHub-Api-Version", "2022-11-28"),
        ]),
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if method == "DELETE" and exc.code == 404:
            return {}
        raise
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def list_runners():
    return github_api("/actions/runners?per_page=100").get("runners", [])


def matching_runners():
    matching = []
    for runner in list_runners():
        if not str(runner.get("name", "")).startswith(prefix):
            continue
        names = set(
            label.get("name", "").lower()
            for label in runner.get("labels", [])
        )
        if labels.issubset(names):
            matching.append(runner)
    return matching


def stop_local_runner_services():
    for directory in sorted(glob.glob(os.path.join(runner_root, "runner-*"))):
        svc = os.path.join(directory, "svc.sh")
        if os.path.exists(svc):
            subprocess.run(
                ["./svc.sh", "stop"],
                cwd=directory,
                check=False,
                timeout=60,
            )


def remove_path(path):
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def reclaim_runner_disk():
    for pattern in (
        os.path.join(runner_root, "runner-*", "_diag", "*.log"),
        os.path.join(runner_root, "runner-*", "_work", "*"),
        os.path.join(tmp_root, "pip-*"),
        os.path.join(tmp_root, "buildkit-*"),
        os.path.join(tmp_root, "buildx-*"),
        os.path.join(tmp_root, "docker-*"),
    ):
        for path in sorted(glob.glob(pattern)):
            if os.path.basename(path).startswith("_"):
                continue
            remove_path(path)
    for args in (
        ["docker", "buildx", "prune", "-af"],
        ["docker", "builder", "prune", "-af"],
        ["docker", "system", "prune", "-af", "--volumes"],
        ["docker", "volume", "prune", "-f"],
    ):
        try:
            run_best_effort(args)
        except OSError:
            pass


def wait_for_github_removal(runner_ids, runner_names):
    deadline = time.time() + 60
    while time.time() < deadline:
        remaining = []
        for runner in list_runners():
            runner_id = str(runner.get("id", ""))
            runner_name = str(runner.get("name", ""))
            if runner_id in runner_ids or runner_name in runner_names:
                remaining.append(runner_name or runner_id)
        if not remaining:
            return
        time.sleep(5)
    raise RuntimeError(
        "timed out waiting for GitHub runner de-registration: "
        + ", ".join(sorted(runner_names))
    )


def drain_runners(runners):
    stop_local_runner_services()
    reclaim_runner_disk()
    runner_ids = set(
        str(runner.get("id"))
        for runner in runners
        if runner.get("id") is not None
    )
    runner_names = set(str(runner.get("name", "")) for runner in runners)
    for runner_id in sorted(runner_ids):
        github_api("/actions/runners/" + runner_id, method="DELETE")
    wait_for_github_removal(runner_ids, runner_names)


matching = matching_runners()
if not matching or any(r.get("busy") for r in matching):
    reset()
    raise SystemExit(0)
if any(r.get("status") != "online" for r in matching):
    reset()
    raise SystemExit(0)

now = int(time.time())
if idle_minutes <= 0:
    idle_since = now
elif os.path.exists(state):
    idle_since = int(open(state).read().strip() or now)
else:
    os.makedirs(os.path.dirname(state), exist_ok=True)
    open(state, "w").write(str(now))
    raise SystemExit(0)

if now - idle_since >= idle_minutes * 60:
    drain_runners(matching)
    run([
        "aws", "autoscaling", "set-desired-capacity",
        "--auto-scaling-group-name", asg_name,
        "--desired-capacity", "0",
        "--honor-cooldown",
        "--region", region,
    ])
