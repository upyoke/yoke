"""Identify command data arguments without hiding local file operands."""

from __future__ import annotations


def gh_api_argument_roles(
    command: str, tokens: list[str]
) -> tuple[set[int], dict[int, str]]:
    """Separate API routes and option data from input and uploaded files."""
    if command != "gh":
        return set(), {}
    values = {
        "-X", "--method", "-H", "--header", "-f", "--raw-field",
        "-F", "--field", "-q", "--jq", "-t", "--template",
        "-p", "--preview", "--hostname", "--cache", "--input",
    }
    ignored: set[int] = set()
    files: dict[int, str] = {}
    api = route = False
    options = True
    index = 1
    while index < len(tokens):
        token = tokens[index]
        flag, separator, value = token.partition("=")
        if token[:2] in values and len(token) > 2 and not token.startswith("--"):
            flag, separator, value = token[:2], "attached", token[2:]
        if options and token == "--":
            options = False
        elif token in {">", ">>", "1>", "1>>", "2>", "2>>", "&>", "&>>", "<"}:
            index += 1
        elif options and flag in values:
            if not separator:
                index += 1
                value = tokens[index] if index < len(tokens) else ""
            ignored.add(index)
            if flag == "--input" and value and value != "-":
                files[index] = value
            elif flag in {"-F", "--field"}:
                _, equals, field = value.partition("=")
                if equals and field.startswith("@") and field[1:] not in {"", "-"}:
                    files[index] = field[1:]
        elif options and token.startswith("-"):
            pass
        elif not api:
            if token != "api":
                return set(), {}
            api = True
        elif not route:
            ignored.add(index)
            route = True
        index += 1
    return (ignored, files) if api else (set(), {})


def non_path_argument_indexes(command: str, tokens: list[str]) -> set[int]:
    """Return argv indexes carrying programs or non-file option values.

    File-valued -f/--file arguments remain paths. With an explicit script
    option there is no implicit positional program. Redirect operands are
    handled first by the caller and never inherit the script exemption.
    """
    if command == "gh":
        return gh_api_argument_roles(command, tokens)[0]
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
