"""Where a test machine's xrdp listens, and the host firewall that confines it.

A Linux host listens on every interface and drops RDP arriving anywhere but
loopback (the SSH forward) and ``tailscale0`` (the direct tailnet route). WSL
keeps xrdp on loopback; Windows exposes it on the tailnet instead.
Stdlib-only: copied beside ``provision_linux_desktop.py`` onto the host.
"""

from __future__ import annotations

import re
from typing import Callable

LOOPBACK = "127.0.0.1"
ANY_ADDRESS = "0.0.0.0"
TAILNET_INTERFACE = "tailscale0"
FIREWALL_TABLE = "yoke_desktop"
FIREWALL_RULES = "/etc/yoke/desktop-firewall.nft"
FIREWALL_UNIT = "/etc/systemd/system/yoke-desktop-firewall.service"


class ProvisionFailure(RuntimeError):
    """A named provisioning refusal with an operator recovery."""


def listener_config(content: str, port: int, address: str) -> str:
    """Change only the listener in Globals, retaining module ports and comments."""
    listen = f"tcp://{'' if address == ANY_ADDRESS else address}:{port}"
    section = ""
    replaced = 0
    lines = []
    for line in content.splitlines(keepends=True):
        match = re.match(r"\s*\[([^]]+)\]", line)
        if match:
            section = match[1].lower()
        if section == "globals" and re.match(r"\s*port\s*=", line):
            line = f"port={listen}\n"
            replaced += 1
        lines.append(line)
    if replaced != 1:
        raise ProvisionFailure(
            "linux_desktop_listener_config_unavailable: expected one Globals port; "
            "inspect /etc/xrdp/xrdp.ini before rerunning"
        )
    return "".join(lines)


def prove_listener(output: str, port: int, address: str) -> None:
    rows = [line.split() for line in output.splitlines() if line.strip()]
    listeners = [row[3] if len(row) >= 5 else "invalid" for row in rows]
    expected = f"{address}:{port}"
    if not listeners or any(value != expected for value in listeners):
        raise ProvisionFailure(
            f"linux_desktop_listener_not_proved: RDP must listen only on {expected}, "
            f"found {', '.join(listeners) or 'nothing'}; repair xrdp's Globals port "
            "and restart xrdp before connecting"
        )


def firewall_rules(port: int) -> str:
    """Recreate the table whole, so a rerun replaces rather than appends."""
    return (
        f"table inet {FIREWALL_TABLE}\n"
        f"delete table inet {FIREWALL_TABLE}\n"
        f"table inet {FIREWALL_TABLE} {{\n"
        "  chain input {\n"
        "    type filter hook input priority filter - 10; policy accept;\n"
        f'    iifname != {{ "lo", "{TAILNET_INTERFACE}" }} tcp dport {port} drop\n'
        "  }\n"
        "}\n"
    )


def firewall_unit() -> str:
    return (
        "[Unit]\n"
        "Description=Yoke desktop firewall: RDP only on loopback and Tailscale\n"
        "Before=xrdp.service\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "RemainAfterExit=yes\n"
        f"ExecStart=/usr/sbin/nft -f {FIREWALL_RULES}\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def install_firewall(
    port: int,
    command: Callable[..., object],
    install_file: Callable[[str, str, str], None],
) -> None:
    """Persist the confinement before xrdp starts listening beyond loopback."""
    command(["sudo", "-n", "install", "-d", "-m", "0755", "/etc/yoke"])
    install_file(firewall_rules(port), FIREWALL_RULES, "0644")
    install_file(firewall_unit(), FIREWALL_UNIT, "0644")
    command(["sudo", "-n", "systemctl", "daemon-reload"])
    command(["sudo", "-n", "systemctl", "enable", "yoke-desktop-firewall.service"])
    command(["sudo", "-n", "systemctl", "restart", "yoke-desktop-firewall.service"])


def prove_firewall(port: int, ruleset: str) -> None:
    """Refuse unless the live table drops RDP from every non-tailnet interface."""
    compact = " ".join(ruleset.split())
    rule = f'iifname != {{ "lo", "{TAILNET_INTERFACE}" }} tcp dport {port} drop'
    if f"table inet {FIREWALL_TABLE}" not in compact or rule not in compact:
        raise ProvisionFailure(
            f"linux_desktop_firewall_not_proved: table inet {FIREWALL_TABLE} must drop "
            f"tcp {port} outside lo and {TAILNET_INTERFACE}; rerun provisioning, or "
            "run sudo systemctl restart yoke-desktop-firewall.service and inspect it"
        )
