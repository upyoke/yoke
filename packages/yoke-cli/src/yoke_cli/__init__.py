"""yoke_cli — the installable `yoke` command: a lightweight local client +
project-file writer.

Owns command parsing/UX, machine config/auth, the API transport (https + local-core
URL), project install/refresh writers, board-art generation, the machine-global
Browser-QA substrate materialization, and the local-core Docker/Colima launcher.

Authority-bearing operations are reached by relaying a function-call envelope over
the transport. May depend only on `yoke_contracts` and the transport client. MUST
NOT import `yoke_core`, `runtime.api.*`, or `psycopg`.
"""

import os as _os
import sys as _sys


def _release_launcher_archive() -> None:
    """Take a console-script launcher archive off ``sys.path``.

    On Windows the ``yoke.exe`` launcher is a zip application whose only module,
    ``__main__``, has already run when this package loads. ``importlib.metadata``
    caches an open ``ZipFile`` for every archive on ``sys.path`` it scans, which
    would pin the launcher for the process's lifetime, and Windows cannot then
    replace it (an editable install, an upgrade). Only the archive being run
    as the program is removed; the standard library's own archive stays.
    """
    if not (_sys.path and _sys.argv and _sys.path[0] and _sys.argv[0]):
        return
    if _os.path.isfile(_sys.path[0]) and _os.path.normcase(
        _os.path.abspath(_sys.path[0])
    ) == _os.path.normcase(_os.path.abspath(_sys.argv[0])):
        del _sys.path[0]


_release_launcher_archive()
