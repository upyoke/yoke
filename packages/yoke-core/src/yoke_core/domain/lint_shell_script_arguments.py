"""Identify inline sed/awk programs without hiding input or script files."""

from __future__ import annotations


def non_path_argument_indexes(command: str, tokens: list[str]) -> set[int]:
    """Return argv indexes carrying programs or non-file option values.

    File-valued -f/--file arguments remain paths. With an explicit script
    option there is no implicit positional program. Redirect operands are
    handled first by the caller and never inherit the script exemption.
    """
    if command not in {"sed", "awk", "gawk", "mawk", "nawk"}:
        return set()
    awk = command != "sed"
    inline = {"-e", "--source"} if awk else {"-e", "--expression"}
    files = {"-f", "--file"}
    values = {"-v", "-F", "--assign", "--field-separator"} if awk else set()
    ignored: set[int] = set()
    positionals = []
    explicit = False
    options = True
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if options and token == "--":
            options = False
        elif options and token in inline | files | values:
            explicit = explicit or token in inline | files
            if token not in files and index + 1 < len(tokens):
                ignored.add(index + 1)
            index += 1
        elif options and token.startswith("-"):
            if any(token.startswith(flag + "=") for flag in inline | values):
                ignored.add(index)
                explicit = explicit or token.split("=", 1)[0] in inline
            elif any(token.startswith(flag + "=") for flag in files):
                explicit = True
            elif token.startswith(("-e", "-f")):
                explicit = True
            elif (
                command == "sed"
                and token == "-i"
                and index + 1 < len(tokens)
                and tokens[index + 1] == ""
            ):
                ignored.add(index + 1)
                index += 1
            # Other options stay in the normal operand walk.
        else:
            positionals.append(index)
        index += 1
    if not explicit and positionals:
        ignored.add(positionals[0])
    return ignored
