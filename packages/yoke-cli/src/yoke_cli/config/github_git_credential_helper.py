"""Git credential entrypoint backed by a GitHub App user authorization.

Yoke copies this file and its credential-store siblings into the CLI
environment's ``github-credential-helper`` directory. The fallback import keeps HTTPS clones working while an editable
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

    config = credential_store.load_config(config_path)
    github = credential_store.github_service_profile_proof.selected_github(config)
    if not isinstance(github, Mapping) or fields.get("protocol") != "https":
        return None
    expected = urllib.parse.urlsplit(
        credential_store.validated_web_url(
            str(github.get("web_url") or credential_store.DEFAULT_GITHUB_WEB_URL)
        )
    ).netloc
    if fields.get("host", "").casefold() != expected.casefold():
        return None
    _assert_checkout_connection(config)
    return credential_store.access_token_from_config(
        config,
        config_path=config_path,
        opener=opener,
    )


def _assert_checkout_connection(config):
    """Never answer Git using another connection's checkout registration."""
    cwd = Path.cwd().resolve()
    primary = cwd
    try:
        for parent in (cwd, *cwd.parents):
            gitfile = parent / ".git"
            if not gitfile.is_file():
                continue
            text = gitfile.read_text().strip()
            if text.startswith("gitdir: "):
                gitdir = (parent / text.removeprefix("gitdir: ")).resolve()
                common = gitdir / "commondir"
                if common.is_file():
                    primary = (gitdir / common.read_text().strip()).resolve().parent
            break
    except OSError as exc:
        raise credential_store.GitHubCredentialStoreError(
            "checkout connection could not be checked; repair Git metadata and retry"
        ) from exc
    groups = config.get("connection_projects") or {}
    selected = credential_store.token_contract.github_connection_label(
        config,
        credential_store.github_service_profile_proof.os.environ.get("YOKE_ENV")
        or config.get("active_env", ""),
    )
    if not isinstance(groups, Mapping):
        return
    matches = []
    for label, entries in groups.items():
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, Mapping) or not entry.get("checkout"):
                continue
            root = Path(entry["checkout"]).expanduser().resolve()
            if cwd.is_relative_to(root) or primary == root:
                matches.append((len(root.parts), label))
    if matches:
        depth = max(size for size, _ in matches)
        labels = {label for size, label in matches if size == depth}
        if selected not in labels:
            label = sorted(labels)[0]
            raise credential_store.GitHubCredentialStoreError(
                credential_store.github_service_profile_proof.missing_authorization(config, label)
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
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Machine config file to read; default: the standard config path.",
    )
    parser.add_argument(
        "operation",
        nargs="?",
        default="",
        help="Git credential operation; only get answers, others do nothing.",
    )
    parsed = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    if parsed.operation != "get":
        return 0
    fields = _read_fields(stdin or sys.stdin)
    try:
        credential = access_token_for_git_request(parsed.config_path, fields)
        if credential is None:
            return 0
    except credential_store.GitHubCredentialStoreError as exc:
        if str(exc).startswith("no GitHub authorization for connection "):
            print(str(exc), file=sys.stderr)
            return 1
        # The store's own message can name the credential path, and this
        # stderr goes to whoever ran git, so the text here is fixed rather
        # than interpolated. It also never advises reconnecting: a reconnect
        # rotates the authorization and revokes the token every other local
        # process is holding, while this failure is most often contention a
        # retry clears. `yoke github status` reads without rotating and says
        # when a reconnect is genuinely the answer.
        print(
            "yoke GitHub credential unavailable. Retry the git command; run "
            "`yoke github status` if it keeps failing",
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
