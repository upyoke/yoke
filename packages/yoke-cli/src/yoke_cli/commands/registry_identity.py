"""Sign-in identity admin entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters


AdapterFn = Callable[[List[str]], int]


IDENTITY_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("identity", "invite", "create"):
        ("identity.invite.create", _adapters.identity_invite_create),
    ("identity", "invite", "list"):
        ("identity.invite.list", _adapters.identity_invite_list),
    ("identity", "invite", "revoke"):
        ("identity.invite.revoke", _adapters.identity_invite_revoke),
    ("identity", "link", "set"):
        ("identity.link.set", _adapters.identity_link_set),
    ("identity", "autojoin", "set"):
        ("identity.autojoin.set", _adapters.identity_autojoin_set),
}


__all__ = ["IDENTITY_SUBCOMMAND_REGISTRY"]
