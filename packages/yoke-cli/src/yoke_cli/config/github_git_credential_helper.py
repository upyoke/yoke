"""Git credential entrypoint backed by a GitHub App user authorization.

Yoke copies this file and its credential-store siblings into the CLI
environment's ``github-credential-helper`` directory. Connection selection uses
YOKE_ENV, then the deepest registered checkout, then active_env. An explicit
YOKE_ENV conflicting with the checkout refuses before credentials are read.
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
    label = _git_connection_label(config)
    github = credential_store.github_service_profile_proof.selected_github(config, label)
    if not isinstance(github, Mapping) or fields.get("protocol") != "https":
        return None
    expected = urllib.parse.urlsplit(
        credential_store.validated_web_url(
            str(github.get("web_url") or credential_store.DEFAULT_GITHUB_WEB_URL)
        )
    ).netloc
    if fields.get("host", "").casefold() != expected.casefold():
        return None
    return credential_store.access_token_from_config(
        config,
        config_path=config_path,
        opener=opener,
        connection_env=label,
    )


def _git_connection_label(config: Mapping[str, Any]) -> str:
    """Select like the CLI, refusing an explicit override of the checkout."""
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
    connection_label = credential_store.token_contract.github_connection_label
    override = credential_store.github_service_profile_proof.os.environ.get(
        "YOKE_ENV", ""
    ).strip()
    selected = connection_label(config, override or config.get("active_env", ""))
    matches = []
    for label, entries in groups.items() if isinstance(groups, Mapping) else []:
        label = connection_label(config, label)
        if label not in (config.get("connections") or {}):
            continue
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, Mapping) or not entry.get("checkout"):
                continue
            root = Path(entry["checkout"]).expanduser().resolve()
            if cwd.is_relative_to(root) or primary == root:
                matches.append((len(root.parts), label, root, entry.get("project_id")))
    if matches:
        depth = max(match[0] for match in matches)
        deepest = [match for match in matches if match[0] == depth]
        labels = {match[1] for match in deepest}
        registered = sorted(labels)[0]
        _, _, root, project_id = next(m for m in deepest if m[1] == registered)
        if override and selected not in labels:
            raise credential_store.GitHubCredentialStoreError(
                "checkout connection mismatch: this checkout is registered to Yoke "
                f"connection '{registered}' but YOKE_ENV selects '{selected}'; "
                f"unset YOKE_ENV or set YOKE_ENV={registered} for git here, or move "
                f"the checkout with `yoke --env {selected} project register {root} "
                f"--project-id {project_id} --reassign`"
            )
        if not override:
            if len(labels) == 1:
                return registered
            raise credential_store.GitHubCredentialStoreError(
                "checkout connection ambiguous: this checkout is registered to Yoke "
                f"connections {', '.join(sorted(labels))}; set YOKE_ENV for git here, "
                "or move the duplicate with `yoke --env ENV project register "
                f"{root} --project-id N --reassign`"
            )
    return selected


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
        if str(exc).startswith((
            "no GitHub authorization for connection ",
            "checkout connection mismatch: ",
            "checkout connection ambiguous: ",
        )):
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
