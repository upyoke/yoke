"""Read-only per-OS process inventory for private browser snapshots."""

WRITER_INVENTORY_PROGRAM = r"""
import json, os, subprocess, sys
from pathlib import Path
uid, profile, caller = int(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
def refuse(code):
    print(json.dumps({"ok": False, "reason": code})); sys.exit(64)
if sys.platform == "darwin":
    try:
        processes = subprocess.run(["/bin/ps", "-U", str(uid), "-ww", "-o", "pid=,command="], capture_output=True, text=True, timeout=20)
        if processes.returncode: refuse("browser_profile_writer_inventory_unavailable")
        for line in processes.stdout.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0] not in {caller, str(os.getpid())} and str(profile) in parts[1]:
                refuse("browser_profile_writer_active")
        if profile.exists():
            files = subprocess.run(["/usr/sbin/lsof", "-n", "-P", "-a", "-u", str(uid), "+D", str(profile), "-F", "p"], capture_output=True, text=True, timeout=20)
            if files.stderr or files.returncode not in {0, 1}: refuse("browser_profile_writer_inventory_unavailable")
            if any(line.startswith("p") for line in files.stdout.splitlines()): refuse("browser_profile_writer_active")
    except (OSError, subprocess.SubprocessError):
        refuse("browser_profile_writer_inventory_unavailable")
    print(json.dumps({"ok": True})); sys.exit(0)
if os.geteuid() != 0: refuse("browser_profile_writer_inventory_unavailable")
proc = Path("/proc")
if not proc.is_dir(): refuse("browser_profile_os_unsupported")
try:
    for process in proc.iterdir():
        if not process.name.isdigit() or process.name == caller:
            continue
        try:
            if process.stat().st_uid != uid:
                continue
            command = (process / "cmdline").read_bytes()
            if os.fsencode(profile) in command: refuse("browser_profile_writer_active")
            for fd in (process / "fd").iterdir():
                try:
                    target = Path(os.readlink(fd).removesuffix(" (deleted)"))
                except FileNotFoundError:
                    continue
                if target == profile or profile in target.parents:
                    refuse("browser_profile_writer_active")
        except FileNotFoundError:
            continue
except OSError:
    refuse("browser_profile_writer_inventory_unavailable")
print(json.dumps({"ok": True}))
"""
