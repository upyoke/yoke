"""Remove only Yoke-owned user services before clearing a Linux test home."""

# Runs remotely with the archive program's home, bounded, os, pathlib and refuse.
YOKE_SERVICE_PATTERNS = ("yoke*.service", "com.upyoke.*.service")
RESET_SERVICES_PROGRAM = r"""
import fnmatch
service_cleanup = {"removed_units": [], "linger": None}
service_patterns = __YOKE_SERVICE_PATTERNS__
def yoke_service(name):
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in service_patterns)
def inventory_failed(result, verb):
    # systemctl list-unit-files returns EXIT_FAILURE for an empty match (ENOENT).
    empty_files = (verb == "list-unit-files" and result.returncode == 1
                   and not result.stdout.strip() and not result.stderr.strip())
    return result.returncode != 0 and not empty_files
if shutil.which("systemctl"):
    observed = bounded(["systemctl", "--user", "list-units", "--all", "--plain", "--no-legend", *service_patterns])
    if observed.returncode: refuse("linux_yoke_service_manager_unavailable")
    loaded = {line.split()[0] for line in observed.stdout.splitlines() if line.strip()}
    observed = bounded(["systemctl", "--user", "list-unit-files", "--no-legend", *service_patterns])
    if inventory_failed(observed, "list-unit-files"): refuse("linux_yoke_service_inventory_unavailable")
    definitions = {line.split()[0] for line in observed.stdout.splitlines() if line.strip()}
    observed = bounded(["systemd-analyze", "--user", "unit-paths"])
    if observed.returncode: refuse("linux_yoke_service_paths_unavailable")
    roots = [pathlib.Path(line) for line in observed.stdout.splitlines() if line.startswith("/")]
    files = {path for root in roots if root.is_dir() for path in root.rglob("*")
             if yoke_service(path.name) and (path.is_file() or path.is_symlink())}
    definitions.update(path.name for path in files)
    units = loaded | definitions
    for path in files:
        if path.lstat().st_uid != os.getuid():
            refuse("linux_yoke_service_foreign_owner", str(path))
    for unit in sorted(units):
        if bounded(["systemctl", "--user", "stop", unit]).returncode:
            refuse("linux_yoke_service_stop_failed")
        if unit in definitions and bounded(["systemctl", "--user", "disable", unit]).returncode:
            refuse("linux_yoke_service_disable_failed")
    for path in files:
        try: path.unlink()
        except FileNotFoundError: pass # disable may already remove a wants link
        except OSError: refuse("linux_yoke_service_remove_failed", str(path))
    # Clear failed state while fileless units are still loaded, before reloading.
    # A stop may already unload a unit; final inventories prove cleanup either way.
    if units: bounded(["systemctl", "--user", "reset-failed", *sorted(units)])
    # A deleted FragmentPath remains loaded and can restart until this reload.
    if bounded(["systemctl", "--user", "daemon-reload"]).returncode:
        refuse("linux_yoke_service_reload_failed")
    for verb in ("list-units", "list-unit-files"):
        proof = bounded(["systemctl", "--user", verb, "--no-legend", *service_patterns])
        if inventory_failed(proof, verb) or proof.stdout.strip(): refuse("linux_yoke_service_absence_not_proved")
    proof = bounded(["loginctl", "show-user", str(os.getuid()), "--property=Linger", "--value"])
    if proof.returncode or proof.stdout.strip() not in {"yes", "no"}:
        refuse("linux_yoke_linger_unknown")
    service_cleanup = {"removed_units": sorted(units), "linger": proof.stdout.strip()}
""".replace("__YOKE_SERVICE_PATTERNS__", repr(YOKE_SERVICE_PATTERNS))
