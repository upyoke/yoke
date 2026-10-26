"""Product teaching for reachable control-plane command authority."""

from __future__ import annotations

# Shown when `yoke db` lists only `read` — the refusal that previously
# read as "no write path exists anywhere."
DB_GROUP_TEACHING = """\
`yoke db` is read-only diagnostic SQL over the active connection.
Ordinary writes use registered `yoke <subcommand>` surfaces.
Human org administrators use `yoke operator data-repair --help` for reviewed,
transactional row repair without a work lane; raw SQL writes are refused.
When no registered command covers a required mutation, escalate the missing
command to the control-plane operator. Name the required operation and the
registered surfaces checked. `yoke env list` shows configured connections.
"""

# Human footer on `yoke env list`. JSON inventory stays sanitized rows.
ENV_LIST_AUTHORITY_FOOTER = (
    "https = normal product/API authority (registered yoke commands; "
    "read-only diagnostic SQL). local-postgres = configured local universe "
    "authority. Ordinary writes use registered yoke commands; `yoke db` "
    "stays read-only. Escalate a missing mutation command to the "
    "control-plane operator."
)


__all__ = [
    "DB_GROUP_TEACHING",
    "ENV_LIST_AUTHORITY_FOOTER",
]
