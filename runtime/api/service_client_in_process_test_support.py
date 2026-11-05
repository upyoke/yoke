"""Exercise service-client dispatch without paying for a Python interpreter."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
import subprocess
import sys
from unittest.mock import patch


def run_client(args, db_path=None, *, env=None):
    """Return the same observable result as the subprocess test helper.

    Scope argv and environment changes to this call, including commands that
    exit through argparse. Database handlers still use their real connections.
    """
    from yoke_core.api import service_client

    child_env = os.environ.copy() if env is None else env.copy()
    if db_path:
        child_env["YOKE_DB"] = str(db_path)
    if "--session-id" in args:
        index = args.index("--session-id") + 1
        if index < len(args):
            child_env["YOKE_SESSION_ID"] = args[index]
    out, err = StringIO(), StringIO()
    argv = ["service_client", *args]
    with patch.dict(os.environ, child_env, clear=True), patch.object(sys, "argv", argv):
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = service_client.main()
            except SystemExit as exc:
                code = exc.code
    return subprocess.CompletedProcess(argv, code, out.getvalue(), err.getvalue())


def run_parity_client(db_path, *args):
    """Use parity's database and entry-surface environment in process."""
    env = os.environ.copy()
    if args and args[0] == "create-item":
        env["YOKE_ITEM_ENTRY_SURFACE"] = "harness_skill"
    return run_client(list(args), db_path, env=env)
