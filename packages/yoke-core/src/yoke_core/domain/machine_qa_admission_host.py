"""Serve the installed candidate's real machine admission on a test machine.

The Machine QA admission fixture runs this module on a controlled test
machine with the installed candidate's own interpreter, so the exact
candidate under test serves the journey:

    python -m yoke_core.domain.machine_qa_admission_host start|stop MODE

``self-hosted`` and ``self-hosted-company-sign-in`` start a disposable
embedded Postgres cluster under the fixture root and boot the real self-host
server entrypoint against it on loopback. The real first boot creates the
universe, its first admin (the fixture owner) and the owner's one-time token,
delivered over the same private handoff a self-host bundle uses; this module
saves it owner-only beside an approver machine config, so the person can act
as the already-connected owner with ``YOKE_MACHINE_HOME`` set to that
directory. Company sign-in adds the disposable stub identity provider, whose
only identity is the teammate,
and the owner invites that email as the journey's precondition. ``local`` creates a disposable local universe
with the real ``yoke init --local`` in a fixture-only machine home.

Nothing here approves, invites or redeems anything; the journey under test
does that. ``stop`` ends the server, removes the cluster and deletes the
fixture root.
"""

from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from yoke_contracts.machine_config.paths import HOME_ENV as MACHINE_HOME_ENV

from yoke_core.domain.machine_qa_fixture_paths import FIXTURE_ROOT

MODULE = "yoke_core.domain.machine_qa_admission_host"
ADMISSION_ROOT = f"{FIXTURE_ROOT}/machine-admission"
MODE_PORTS = {
    "local": None,
    "self-hosted": 19121,
    "self-hosted-company-sign-in": 19122,
}
OWNER_NAME = "Fixture Owner"
TEAMMATE_SUBJECT = "machine-qa-teammate"
TEAMMATE_EMAIL = "teammate@machine-qa.invalid"
APPROVER_ENV = "fixture"
READY_TIMEOUT_SECONDS = 300.0


class AdmissionFixtureError(RuntimeError):
    """A named fixture refusal; its message carries the recovery."""


def mode_root(mode: str) -> Path:
    if mode not in MODE_PORTS:
        raise AdmissionFixtureError(
            f"machine_admission_mode_unknown: {mode!r}; use one of {sorted(MODE_PORTS)}"
        )
    return Path(ADMISSION_ROOT) / mode


def api_url(mode: str) -> str:
    return f"http://127.0.0.1:{MODE_PORTS[mode]}"


def approver_home(mode: str) -> Path:
    return mode_root(mode) / "approver"


def universe_spec(mode: str, *, bin_dir: Path | None = None):
    """The disposable cluster this mode's journey reads and writes."""
    from yoke_core.domain import local_universe, postgres_binaries

    if mode != "local":
        selected = bin_dir or postgres_binaries.installed_bin_dir()
        return local_universe.cluster_spec(
            root=mode_root(mode) / "universe", bin_dir=selected
        )
    # yoke init --local fetched its engine into the fixture machine home.
    home = mode_root(mode) / "home"
    previous = os.environ.get(MACHINE_HOME_ENV)
    os.environ[MACHINE_HOME_ENV] = str(home)
    try:
        selected = bin_dir or postgres_binaries.installed_bin_dir()
    finally:
        if previous is None:
            os.environ.pop(MACHINE_HOME_ENV, None)
        else:
            os.environ[MACHINE_HOME_ENV] = previous
    return local_universe.cluster_spec(
        root=home / local_universe.LOCAL_UNIVERSE_DIR_NAME, bin_dir=selected
    )


def universe_dsn(mode: str) -> str:
    from yoke_core.domain import local_universe

    return local_universe.local_dsn(universe_spec(mode))


def _private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def write_private(path: Path, text: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)


def server_methods(mode: str) -> dict | None:
    from yoke_contracts.machine_authorization import START_PATH

    connection = http.client.HTTPConnection("127.0.0.1", MODE_PORTS[mode], timeout=2)
    try:
        connection.request("GET", START_PATH)
        response = connection.getresponse()
        body = response.read()
        return json.loads(body) if response.status == 200 else None
    except (OSError, ValueError):
        return None
    finally:
        connection.close()


def _log_tail(mode: str) -> str:
    log = mode_root(mode) / "server.log"
    if not log.is_file():
        return ""
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-20:])


def _wait_ready(mode: str, process: subprocess.Popen) -> None:
    expected_company = mode == "self-hosted-company-sign-in"
    ready = mode_root(mode) / "ready"
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AdmissionFixtureError(
                f"machine_admission_server_exited: exit {process.returncode}; "
                f"read {mode_root(mode)}/server.log, repair the named boot "
                f"failure, then rerun the case.\n{_log_tail(mode)}"
            )
        methods = server_methods(mode)
        if (
            methods is not None
            and methods.get("company_sign_in") is expected_company
            and ready.is_file()
        ):
            return
        time.sleep(1.0)
    raise AdmissionFixtureError(
        "machine_admission_server_not_ready: the server did not answer "
        f"{api_url(mode)} within {int(READY_TIMEOUT_SECONDS)} seconds; read "
        f"{mode_root(mode)}/server.log, then rerun the case.\n{_log_tail(mode)}"
    )


def _birth_local(mode: str) -> None:
    launcher = Path(sys.executable).parent / "yoke"
    result = subprocess.run(
        [str(launcher), "init", "--local", "--admin-name", OWNER_NAME],
        env={
            **{key: value for key, value in os.environ.items() if key != "YOKE_ENV"},
            MACHINE_HOME_ENV: str(mode_root(mode) / "home"),
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=READY_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise AdmissionFixtureError(
            f"machine_admission_local_birth_failed: yoke init --local exited "
            f"{result.returncode}; repair it on the test machine, then rerun "
            f"the case.\n{detail}"
        )


def start(mode: str) -> dict:
    """Prepare the mode's disposable universe and wait until it serves."""
    from yoke_core.domain.machine_qa_admission_state import save_baseline

    stop(mode)
    root = _private_dir(mode_root(mode))
    if mode == "local":
        _birth_local(mode)
    else:
        with open(root / "server.log", "ab", buffering=0) as log:
            process = subprocess.Popen(
                [sys.executable, "-m", MODULE, "serve", mode],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        write_private(
            root / "identity.json",
            json.dumps({"mode": mode, "pid": process.pid}) + "\n",
        )
        try:
            _wait_ready(mode, process)
        except AdmissionFixtureError:
            stop(mode)
            raise
    baseline = save_baseline(mode)
    return {
        "mode": mode,
        "api_url": None if mode == "local" else api_url(mode),
        "approver_home": None if mode == "local" else str(approver_home(mode)),
        "machine_home": str(root / "home") if mode == "local" else None,
        "baseline": baseline,
    }


def stop(mode: str) -> None:
    """End the server, remove the disposable cluster and the fixture root."""
    from yoke_core.domain import postgres_cluster

    root = mode_root(mode)
    identity = root / "identity.json"
    if identity.is_file():
        pid = int(json.loads(identity.read_text(encoding="utf-8"))["pid"])
        try:
            os.killpg(pid, signal.SIGTERM)
            for _ in range(100):
                os.killpg(pid, 0)
                time.sleep(0.1)
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    spec = universe_spec(mode)
    if spec.bin_dir is not None and spec.data_dir.exists():
        postgres_cluster.destroy(spec)
    shutil.rmtree(root, ignore_errors=True)
    if root.exists():
        raise AdmissionFixtureError(
            f"machine_admission_cleanup_failed: {root} remains; remove it on "
            "the test machine, then rerun the case."
        )


def serve(mode: str) -> int:
    """Supervise one real self-host server on the disposable cluster."""
    from yoke_core.domain.machine_qa_admission_server import run_server

    return run_server(mode)


def main(argv: list[str]) -> int:
    if not (
        (len(argv) == 2 and argv[0] in {"start", "stop", "serve"})
        or (len(argv) == 3 and argv[0] == "assert")
    ):
        print(
            "usage: machine_qa_admission_host start|stop|serve MODE | "
            "assert MODE EXPECT",
            file=sys.stderr,
        )
        return 2
    action, mode = argv[:2]
    try:
        if action == "assert":
            from yoke_core.domain.machine_qa_admission_state import assert_state

            print(json.dumps(assert_state(mode, argv[2]), sort_keys=True), flush=True)
            return 0
        if action == "serve":
            return serve(mode)
        if action == "stop":
            stop(mode)
            print(json.dumps({"mode": mode, "stopped": True}), flush=True)
            return 0
        print(json.dumps(start(mode), sort_keys=True), flush=True)
        return 0
    except AdmissionFixtureError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    # Run the imported module so its refusal type is the one its helpers raise.
    from yoke_core.domain import machine_qa_admission_host as _host

    raise SystemExit(_host.main(sys.argv[1:]))


__all__ = [
    "ADMISSION_ROOT",
    "APPROVER_ENV",
    "AdmissionFixtureError",
    "MODE_PORTS",
    "OWNER_NAME",
    "TEAMMATE_EMAIL",
    "TEAMMATE_SUBJECT",
    "api_url",
    "approver_home",
    "mode_root",
    "server_methods",
    "start",
    "stop",
    "universe_dsn",
    "universe_spec",
    "write_private",
]
