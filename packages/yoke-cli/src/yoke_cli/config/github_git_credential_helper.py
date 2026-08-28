"""Git credential entrypoint backed by a GitHub App user authorization.

Source-dev onboarding copies this file and its credential-store siblings into
site-packages. The fallback import keeps HTTPS clones working while an editable
install is being moved to the checkout that Git is currently cloning.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, TextIO
import urllib.parse

if __package__:
    from yoke_cli.config import github_git_credential_store as credential_store
else:  # pragma: no cover - copied helper always uses its immutable siblings
    import _yoke_github_git_credential_store as credential_store  # type: ignore


def access_token_for_git_request(
    config_path: str | Path | None,
    fields: Mapping[str, str],
    *,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any] | None:
    """Answer a Git credential request for this machine's GitHub host, or decline.

    Git asks every configured helper about every host it contacts, so declining
    a request for anything but the configured HTTPS origin is the normal answer,
    not a failure.
    """

    with credential_store.machine_operation_lock(config_path):
        config = credential_store.load_config(config_path)
        github = config.get("github")
        if not isinstance(github, Mapping) or fields.get("protocol") != "https":
            return None
        expected = urllib.parse.urlsplit(
            credential_store.validated_web_url(
                str(
                    github.get("web_url")
                    or credential_store.DEFAULT_GITHUB_WEB_URL
                )
            )
        ).netloc
        if fields.get("host", "").casefold() != expected.casefold():
            return None
        return credential_store.access_token_from_config(
            config,
            config_path=config_path,
            opener=opener,
        )


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
        credential = access_token_for_git_request(parsed.config_path, fields)
        if credential is None:
            return 0
    except credential_store.GitHubCredentialStoreError as exc:
        # Never advise reconnecting from here. A reconnect rotates the
        # authorization and revokes the token every other local process is
        # holding, and this failure is most often contention that a retry
        # clears. `yoke github status` reads without rotating and says when a
        # reconnect is genuinely the answer.
        print(
            f"yoke GitHub credential unavailable: {exc}. Retry the git "
            "command; run `yoke github status` if it keeps failing",
            file=sys.stderr,
        )
        return 1
    out = stdout or sys.stdout
    print("username=x-access-token", file=out)
    print(f"password={credential['access_token']}", file=out)
    return 0


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


__all__ = ["access_token_for_git_request", "main"]
