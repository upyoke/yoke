"""Git credential entrypoint backed by a GitHub App user authorization.

Source-dev onboarding copies this file and its credential-store sibling into
site-packages. The fallback import keeps HTTPS clones working while an editable
install is being moved to the checkout that Git is currently cloning.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Mapping, TextIO
import urllib.parse

try:
    from yoke_cli.config import github_git_credential_store as credential_store
except Exception:  # pragma: no cover - copied helper survives broken editable import
    import _yoke_github_git_credential_store as credential_store  # type: ignore


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m yoke_cli.config.github_git_credential_helper",
    )
    parser.add_argument("--config", dest="config_path", default=None)
    parser.add_argument("operation", nargs="?", default="")
    parsed = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    if parsed.operation != "get":
        return 0
    fields = _read_fields(stdin or sys.stdin)
    try:
        config = credential_store.load_config(parsed.config_path)
        if not _request_matches_github(fields, config):
            return 0
        credential = credential_store.access_token_from_config(
            config, opener=None
        )
    except credential_store.GitHubCredentialStoreError:
        print(
            "yoke GitHub credential unavailable; run `yoke github status` "
            "and reconnect with `yoke github connect`",
            file=sys.stderr,
        )
        return 1
    out = stdout or sys.stdout
    print("username=x-access-token", file=out)
    print(f"password={credential['access_token']}", file=out)
    return 0


def _request_matches_github(
    fields: Mapping[str, str], config: Mapping[str, Any]
) -> bool:
    if fields.get("protocol") != "https":
        return False
    github = config.get("github")
    if not isinstance(github, Mapping):
        return False
    web_url = str(
        github.get("web_url") or credential_store.DEFAULT_GITHUB_WEB_URL
    )
    expected_authority = urllib.parse.urlsplit(
        credential_store.validated_web_url(web_url)
    ).netloc
    return fields.get("host", "").lower() == expected_authority.lower()


def _read_fields(stream: TextIO) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw in stream:
        line = raw.rstrip("\n")
        if not line:
            break
        key, separator, value = line.partition("=")
        if separator:
            fields[key] = value
    return fields


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main"]
