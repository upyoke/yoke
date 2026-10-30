"""Self-host initialization next steps, without credential values."""

import ipaddress
from typing import Dict

from yoke_cli.self_host import first_boot_token
from yoke_contracts.self_host_bootstrap_output import connect_url_from_publish_spec


def print_summary(report: Dict[str, object]) -> None:
    directory = report.get("directory")
    if report.get("paused"):
        print(
            "Source remains paused; run `yoke universe resume` against its connection to restore writers."
        )
    if report.get("mode") == "protect-existing":
        print(f"self-host bundle protected: {directory}")
        state = "updated" if report.get("gitignore_changed") else "already current"
        print(f"secret ignore rules: {state}")
        print("database credentials: preserved (not regenerated)")
        if report.get("github_app_private_key_installed"):
            print("GitHub App private key: installed atomically as mode 0600")
        return
    print(f"self-host bundle written: {directory}")
    print(f"server image: {report.get('image')}")
    publish = str(report.get("publish") or "")
    print(f"api publish: {publish}")
    host, _, port = publish.rpartition(":")
    if host.strip("[]") in {"0.0.0.0", "::"}:
        print(f"teammates: yoke connect http://<server-private-address>:{port}")
        print(
            "Replace <server-private-address> with this server's LAN or Tailscale IP."
        )
    elif not ipaddress.ip_address(host.strip("[]")).is_loopback:
        print(f"teammates: yoke connect {connect_url_from_publish_spec(publish)}")
    if report.get("listen_hint"):
        print(f"hint: {report['listen_hint']}")
    print(f"first admin: {report.get('admin_name')}")
    token_file = first_boot_token.token_drop_path(str(directory))
    connect_url = connect_url_from_publish_spec(str(report.get("publish") or ""))
    print("next steps:")
    print(f"  1. yoke self-host init --dir {directory} --protect-existing --start")
    print("  2. first boot writes the reusable administrator token to:")
    print(f"       {token_file}")
    print("  3. connect this machine's CLI; keep that owner-only file, since")
    print("     rerunning `yoke setup` on this host reconnects with it:")
    print(f"       yoke connect {connect_url} --token-stdin < {token_file}")
