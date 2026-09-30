"""Reap only the dedicated test user's Yoke writers before home restore."""

from yoke_harness.ssh_mac_full_reset_contract import (
    COMPOSE_PROJECT_LABEL,
    SELF_HOST_COMPOSE_PROJECT,
)

# Inserted only in the remote operation, after archive validation. Archive-only
# fixture tests never operate the execution machine's service/container daemon.
RESET_WRITERS_PROGRAM = r"""
import signal, subprocess, time

def bounded(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=30)

units = []
if shutil.which("systemctl"):
    observed = bounded(["systemctl", "--user", "list-units", "--all", "--plain", "--no-legend", "yoke*.service"])
    if observed.returncode == 0:
        units = [line.split()[0] for line in observed.stdout.splitlines() if line.strip()]
        for unit in units:
            if bounded(["systemctl", "--user", "disable", "--now", unit]).returncode:
                refuse("linux_yoke_service_stop_failed")
    elif (home / ".config/systemd/user").is_dir() and any((home / ".config/systemd/user").glob("yoke*.service")):
        refuse("linux_yoke_service_manager_unavailable")

if shutil.which("docker"):
    label = "__COMPOSE_LABEL__=__COMPOSE_PROJECT__"
    for kind, listing, removal in (
        ("containers", ["docker", "ps", "-aq", "--filter", "label=" + label], ["docker", "rm", "--force"]),
        ("volumes", ["docker", "volume", "ls", "-q", "--filter", "label=" + label], ["docker", "volume", "rm", "--force"]),
    ):
        observed = bounded(listing)
        if observed.returncode: refuse("linux_self_host_inventory_unavailable")
        ids = observed.stdout.split()
        if ids and bounded([*removal, "--", *ids]).returncode:
            refuse("linux_self_host_remove_failed")
        proof = bounded(listing)
        if proof.returncode or proof.stdout.strip(): refuse("reset_self_host_absence_not_proved")

anchors = [str(home / value) for value in (".yoke", "yoke-server", ".local/bin/yoke")]
writers = []
for directory in pathlib.Path("/proc").iterdir():
    if not directory.name.isdigit() or int(directory.name) == os.getpid(): continue
    try:
        if directory.stat().st_uid != os.getuid(): continue
        args = (directory / "cmdline").read_bytes().decode(errors="replace").split("\x00")
        if any(arg == anchor or arg.startswith(anchor + "/") for arg in args for anchor in anchors):
            writers.append(int(directory.name))
    except (FileNotFoundError, PermissionError): pass
for pid in writers:
    try: os.kill(pid, signal.SIGTERM)
    except ProcessLookupError: pass
end = time.monotonic() + 5
while any(pathlib.Path(f"/proc/{pid}").exists() for pid in writers) and time.monotonic() < end:
    time.sleep(0.1)
for pid in writers:
    try: os.kill(pid, signal.SIGKILL)
    except ProcessLookupError: pass
""".replace("__COMPOSE_LABEL__", COMPOSE_PROJECT_LABEL).replace(
    "__COMPOSE_PROJECT__", SELF_HOST_COMPOSE_PROJECT
)
