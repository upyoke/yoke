"""Desktop Chromium state stays live across Linux golden capture and reset."""

SNAP_CHROMIUM_HOME_ENTRY = "snap/chromium/common/chromium"

# Embedded in the owner-only archive program; Chromium has already quit.
BROWSER_SIGN_IN_PROGRAM = r"""
browser_home_entry = __BROWSER_HOME_ENTRY__
browser_stash = None
def browser_sign_in_entry(name):
    path = pathlib.PurePosixPath(name)
    root = pathlib.PurePosixPath(browser_home_entry)
    return path == root or root in path.parents
def browser_sign_in_path():
    path = home
    for part in pathlib.PurePosixPath(browser_home_entry).parts:
        path = path / part
        if path.is_symlink() or path.exists() and (not path.is_dir() or path.stat().st_uid != os.getuid()):
            refuse("linux_browser_sign_in_store_unsafe", browser_home_entry,
                   recovery="Make the Chromium profile and its parents regular directories owned by the test user; the home was not cleared.")
    return path
def stash_browser_sign_in():
    global browser_stash
    source = browser_sign_in_path()
    if not source.exists(): return
    directory = pathlib.Path(tempfile.mkdtemp(prefix="yoke-live-chromium-", dir=baseline.parent))
    try:
        source.rename(directory / "profile")
    except OSError:
        directory.rmdir()
        refuse("linux_browser_sign_in_stash_failed", browser_home_entry,
               recovery="Keep the golden and home on the same filesystem and repair directory access, then retry; the home was not cleared.")
    browser_stash = directory
def restore_browser_sign_in():
    if browser_stash is None: return
    try:
        destination = browser_sign_in_path()
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        (browser_stash / "profile").rename(destination)
        browser_stash.rmdir()
    except OSError:
        refuse("linux_browser_sign_in_restore_failed", browser_home_entry,
               recovery="Restore the private Chromium profile from " + str(browser_stash / "profile") + " to ~/" + browser_home_entry + "; do not recapture or discard that live state.")
""".replace("__BROWSER_HOME_ENTRY__", repr(SNAP_CHROMIUM_HOME_ENTRY))
