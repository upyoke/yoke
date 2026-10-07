"""Product teaching for reachable control-plane command authority."""

from __future__ import annotations

# Shown when `yoke db` lists only `read` — the refusal that previously
# read as "no write path exists anywhere."
DB_GROUP_TEACHING = """\
`yoke db` is read-only diagnostic SQL over the active connection.
Ordinary writes use registered `yoke <subcommand>` surfaces.
When no registered command covers a required mutation, escalate the missing
command to the control-plane operator. Name the required operation and the
registered surfaces checked. `yoke env list` shows configured connections.
"""

# Compact session-packet stanza: kinds of authority, not a config dump.
CONNECTION_AUTHORITY_STANZA = (
    "Connection authority: `yoke env list` prints every configured "
    "connection (name, active, transport, prod). HTTPS is the normal "
    "product/API authority — registered `yoke` commands relay there; "
    "`yoke db` is read-only. Ordinary writes use registered "
    "`yoke <subcommand>`. When no registered command covers a required "
    "mutation, escalate the missing command to the control-plane operator."
)

# Human footer on `yoke env list`. JSON inventory stays sanitized rows.
ENV_LIST_AUTHORITY_FOOTER = (
    "https = normal product/API authority (registered yoke commands; "
    "read-only diagnostic SQL). local-postgres = configured local universe "
    "authority. Ordinary writes use registered yoke commands; `yoke db` "
    "stays read-only. Escalate a missing mutation command to the "
    "control-plane operator."
)


__all__ = [
    "CONNECTION_AUTHORITY_STANZA",
    "DB_GROUP_TEACHING",
    "ENV_LIST_AUTHORITY_FOOTER",
]
