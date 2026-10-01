"""Quiesce the dedicated test user's home-resident programs before restore."""

from yoke_harness.ssh_linux_reset_services import RESET_SERVICES_PROGRAM
from yoke_harness.ssh_mac_full_reset_contract import (
    COMPOSE_PROJECT_LABEL,
    SELF_HOST_COMPOSE_PROJECT,
)

# Inserted only in the remote operation, after archive validation. Archive-only
# fixture tests never operate the execution machine's service/container daemon.
RESET_WRITERS_PROGRAM = (
    r"""
import signal, subprocess, time

def bounded(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=30)

# STOP_YOKE_SERVICES

if shutil.which("docker"):
    label = "__COMPOSE_LABEL__=__COMPOSE_PROJECT__"
    images = set()
    for kind, listing, removal in (
        ("containers", ["docker", "ps", "-aq", "--filter", "label=" + label], ["docker", "rm", "--force"]),
        ("volumes", ["docker", "volume", "ls", "-q", "--filter", "label=" + label], ["docker", "volume", "rm", "--force"]),
    ):
        observed = bounded(listing)
        if observed.returncode: refuse("linux_self_host_inventory_unavailable")
        ids = observed.stdout.split()
        if kind == "containers":
            for container in ids:
                image = bounded(["docker", "inspect", "--format", "{{.Image}}", "--", container])
                if image.returncode: refuse("linux_self_host_inventory_unavailable")
                images.update(image.stdout.split())
        if ids and bounded([*removal, "--", *ids]).returncode:
            refuse("linux_self_host_remove_failed")
        proof = bounded(listing)
        if proof.returncode or proof.stdout.strip(): refuse("reset_self_host_absence_not_proved")
    # Non-force removal preserves images still used by any other workload.
    for image in sorted(images): bounded(["docker", "image", "rm", "--", image])

def process_record(pid):
    directory = pathlib.Path(f"/proc/{pid}")
    try:
        if directory.stat().st_uid != os.getuid(): return None
        fields = (directory / "stat").read_text().rsplit(")", 1)[1].split()
        args = (directory / "cmdline").read_bytes().decode(errors="replace").split("\x00")
        try: executable = os.readlink(directory / "exe")
        except OSError: executable = ""
        return {"parent": int(fields[1]), "start": fields[19], "state": fields[0], "args": args, "executable": executable}
    except (FileNotFoundError, PermissionError, ProcessLookupError): return None

def home_program(record):
    # /proc/exe still identifies a daemon whose executable the last reset deleted.
    return any(arg == str(home) or arg.startswith(str(home) + "/")
               for arg in [*record["args"], record["executable"]])
def process_inventory():
    processes = {}
    for directory in pathlib.Path("/proc").iterdir():
        if directory.name.isdigit() and int(directory.name) != os.getpid():
            record = process_record(int(directory.name))
            if record: processes[int(directory.name)] = record
    return processes
processes = process_inventory()
writers = {pid: record["start"] for pid, record in processes.items()
           if home_program(record) and record["state"] != "Z"}
while True:
    children = {pid: record["start"] for pid, record in processes.items()
                if record["parent"] in writers and pid not in writers}
    if not children: break
    writers.update(children)
def still_writing(pid, start):
    record = process_record(pid)
    return record is not None and record["start"] == start and record["state"] != "Z"
def stop_writers(signal_number):
    for pid, start in writers.items():
        if still_writing(pid, start):
            try: os.kill(pid, signal_number)
            except ProcessLookupError: pass
def writers_stopped(timeout):
    end = time.monotonic() + timeout
    while any(still_writing(pid, start) for pid, start in writers.items()):
        if time.monotonic() >= end: return False
        time.sleep(0.1)
    return True
stop_writers(signal.SIGTERM)
if not writers_stopped(5):
    stop_writers(signal.SIGKILL)
    if not writers_stopped(1): refuse("linux_home_writers_stop_not_proved")
if any(home_program(record) and record["state"] != "Z"
       for record in process_inventory().values()):
    refuse("linux_home_writers_stop_not_proved")

""".replace("# STOP_YOKE_SERVICES", RESET_SERVICES_PROGRAM)
    .replace("__COMPOSE_LABEL__", COMPOSE_PROJECT_LABEL)
    .replace("__COMPOSE_PROJECT__", SELF_HOST_COMPOSE_PROJECT)
)
