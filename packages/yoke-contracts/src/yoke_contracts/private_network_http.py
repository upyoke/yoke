"""Plain HTTP endpoint policy shared by connection and transport clients."""

from __future__ import annotations

import ipaddress

_PRIVATE_NETWORKS = tuple(
    map(
        ipaddress.ip_network,
        (
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "100.64.0.0/10",
            "fd00::/8",
        ),
    )
)

PRIVATE_HTTP_WARNING = (
    "warning [private_network_http]: the machine token travels unencrypted over HTTP. "
    "Safe on Tailscale or a VPN; use TLS on a shared LAN."
)


def allows_http_host(host: str) -> bool:
    """Allow numeric loopback, the declared private ranges and *.ts.net."""
    host = str(host or "").casefold().rstrip(".")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        labels = host.split(".")
        return (
            len(labels) > 2
            and labels[-2:] == ["ts", "net"]
            and all(
                label
                and len(label) <= 63
                and label[0].isalnum()
                and label[-1].isalnum()
                and all(c.isascii() and (c.isalnum() or c == "-") for c in label)
                for label in labels
            )
        )
    return address.is_loopback or any(
        address.version == network.version and address in network
        for network in _PRIVATE_NETWORKS
    )
