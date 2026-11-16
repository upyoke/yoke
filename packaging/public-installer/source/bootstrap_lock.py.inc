def _bootstrap_locking():
    """Use the shared stdlib OS lock owner before a candidate is installed."""
    locking = {"__name__": "yoke_installer_file_lock"}
    exec(compile(PLATFORM_FILE_LOCK_SOURCE, "<platform_file_lock>", "exec"), locking)
    return locking


@contextmanager
def _bootstrap_publication(root: Path, locking):
    with (root / "publication.lock").open(mode="a+b") as handle:
        deadline = time.monotonic() + 30
        announced = False
        while True:
            try:
                locking["acquire_exclusive_nonblocking"](handle.fileno())
                break
            except BlockingIOError:
                if not announced:
                    print("Waiting by design: CLI publication lock; checking every 50ms; gives up after 30 seconds.", file=sys.stderr)
                    announced = True
                if time.monotonic() >= deadline:
                    raise InstallError("cli_publication_busy: let the active update finish, then retry")
                time.sleep(0.05)
        try:
            yield
        finally:
            locking["release_exclusive"](handle.fileno())
