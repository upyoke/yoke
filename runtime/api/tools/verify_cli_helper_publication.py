"""Verify production publishes the candidate credential-helper implementation."""

import io
import os
from pathlib import Path
import sys
import urllib.request
import zipfile

from yoke_cli.config import (
    cli_release_runtime,
    cli_release_resident,
    github_credential_helper_check,
    github_git_credentials,
    github_repo_helper_reconnect,
    operator_cli_release_follow,
)
from yoke_cli.self_host import release_target


def main() -> int:
    try:
        target = release_target.channel_release_target(base_url=os.environ["BASE_URL"])
        url = (
            f"{target.base_url}/dist/releases/{target.version}/wheels/"
            f"yoke_cli-{target.version}-py3-none-any.whl"
        )
        with urllib.request.urlopen(url, timeout=30) as response:
            wheel = zipfile.ZipFile(io.BytesIO(response.read()))
        with wheel:
            for module in (
                cli_release_runtime,
                cli_release_resident,
                github_credential_helper_check,
                github_git_credentials,
                github_repo_helper_reconnect,
                operator_cli_release_follow,
            ):
                member = module.__name__.replace(".", "/") + ".py"
                if wheel.read(member) != Path(module.__file__).read_bytes():
                    raise ValueError(
                        f"published {member} differs from the verified candidate"
                    )
    except (
        OSError,
        ValueError,
        KeyError,
        zipfile.BadZipFile,
        release_target.ReleaseTargetError,
    ) as exc:
        print(
            f"cli_helper_publication_unverified: {exc}; finish publishing this candidate's CLI wheel, then rerun the case",
            file=sys.stderr,
        )
        return 1
    print(
        f"Verified credential-helper checks, relay failure handling and publication rollback in {url}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
