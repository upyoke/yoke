"""Native browser state, harness sign-ins and harness installations stay live.

Each entry is left out of every captured golden and kept live through reset,
so a reset never restores a rotated sign-in or an older harness install.
"""

SNAP_CHROMIUM_HOME_ENTRY = "snap/chromium/common/chromium"

# Embedded in the owner-only archive program; Chromium has already quit.
PRESERVED_HOME_PROGRAM = r"""
browser_home_entry = __BROWSER_HOME_ENTRY__
live_home_entries = (
    browser_home_entry,
    ".local/bin/claude", ".local/bin/codex",
    ".local/bin/agent", ".local/bin/cursor-agent",
    ".local/share/claude", ".local/share/cursor-agent",
    ".local/lib/node_modules/@openai",
    ".codex/packages",
    ".claude/.credentials.json", ".codex/auth.json", ".config/cursor/auth.json",
)
live_home_stashes = []
live_home_stash_root = None
def preserved_home_entry(name):
    path = pathlib.PurePosixPath(name)
    return any(path == root or root in path.parents
               for root in map(pathlib.PurePosixPath, live_home_entries))
def preserved_home_path(relative):
    path = home
    parts = pathlib.PurePosixPath(relative).parts
    reason = "linux_browser_sign_in_store_unsafe" if relative == browser_home_entry else "linux_preserved_home_entry_unsafe"
    for index, part in enumerate(parts):
        path = path / part
        if not path.exists() and not path.is_symlink(): continue
        if path.lstat().st_uid != os.getuid() or index < len(parts) - 1 and (path.is_symlink() or not path.is_dir()) or relative == browser_home_entry and not path.is_dir():
            refuse(reason, relative,
                   recovery="Repair the named live entry ownership and regular parent directories; the home was not cleared.")
        if path.is_symlink() and (not path.exists() or relative == browser_home_entry or not path.resolve().is_relative_to(home) or not preserved_home_entry(str(path.resolve().relative_to(home)))):
            refuse(reason, relative,
                   recovery="Keep harness links within the preserved installation roots; the home was not cleared.")
    return path
def stash_live_home_entries():
    global live_home_stash_root
    sources = [(relative, preserved_home_path(relative)) for relative in live_home_entries]
    sources = [(relative, source) for relative, source in sources if source.exists() or source.is_symlink()]
    if not sources: return
    directory = pathlib.Path(tempfile.mkdtemp(prefix="yoke-live-home-", dir=baseline.parent))
    live_home_stash_root = directory
    try:
        for relative, source in sources:
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            source.rename(target)
            live_home_stashes.append((relative, target))
    except OSError:
        restore_live_home_entries()
        refuse("linux_preserved_home_stash_failed", relative,
               recovery="Keep golden and home on the same filesystem and repair access; the home was not cleared.")
def restore_live_home_entries():
    global live_home_stash_root
    try:
        for relative, source in live_home_stashes:
            destination = preserved_home_path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            source.rename(destination)
        if live_home_stash_root is not None: shutil.rmtree(live_home_stash_root)
        live_home_stashes.clear()
        live_home_stash_root = None
    except OSError:
        refuse("linux_preserved_home_restore_failed", relative,
               recovery="Restore the retained live entry from " + str(source) + " to ~/" + relative + "; preserve every recovery stash and never capture the mixed home.")
""".replace("__BROWSER_HOME_ENTRY__", repr(SNAP_CHROMIUM_HOME_ENTRY))
