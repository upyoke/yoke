"""yoke_cli — the installable `yoke` command: a lightweight local client +
project-file writer.

Owns command parsing/UX, machine config/auth, the API transport (https + local-core
URL), project install/refresh writers, board-art generation, the machine-global
Browser-QA substrate materialization, and the local-core Docker/Colima launcher.

Authority-bearing operations are reached by relaying a function-call envelope over
the transport. May depend only on `yoke_contracts` and the transport client. MUST
NOT import `yoke_core`, `runtime.api.*`, or `psycopg`.
"""
