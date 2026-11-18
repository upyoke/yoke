"""Import a named Test Machine's credential on this controller."""

import argparse
import sys

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_contracts.machine_config.capability_secret_store import (
    MachineCapabilitySecretError,
    store_test_machine_secret,
)
from yoke_contracts.machine_config.secret_files import (
    MachineSecretError,
    read_secret_file,
    read_stdin_secret,
)

SECRET_USAGE = (
    "yoke test-machine secret set --test-machine NAME --key "
    "ssh_private_key|desktop_password (--value-file FILE | --value-stdin)"
)


def test_machine_secret_set(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke test-machine secret set",
        description="Import one credential into this controller's private Test Machine store.",
    )
    parser.add_argument("--test-machine", required=True, metavar="NAME", help="Registered Test Machine name.")
    parser.add_argument("--key", choices=("ssh_private_key", "desktop_password"), required=True, help="Credential to import on this controller.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--value-file", help="Read the credential from a private file.")
    source.add_argument("--value-stdin", action="store_true", help="Read the credential from standard input.")
    parsed = parse_or_usage_error(parser, args, SECRET_USAGE)
    if parsed is None:
        return 2
    try:
        value = (
            read_secret_file(parsed.value_file, parsed.key)
            if parsed.value_file
            else read_stdin_secret(parsed.key)
        )
        store_test_machine_secret(parsed.test_machine, parsed.key, value)
    except (MachineSecretError, MachineCapabilitySecretError, OSError, ValueError) as exc:
        print(f"error: {exc}. Correct the secret input or directory permissions and retry.", file=sys.stderr)
        return 1
    print(f"Stored {parsed.key} for Test Machine {parsed.test_machine} on this controller.")
    return 0


TOOL_SHAPED_SUBCOMMANDS = {("test-machine", "secret", "set"): test_machine_secret_set}
TOOL_SHAPED_USAGE = {"yoke test-machine secret set": SECRET_USAGE}
