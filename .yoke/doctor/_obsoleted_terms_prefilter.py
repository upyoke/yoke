"""Prefilters that let the retired-term scan skip files cheaply.

Each one only ever answers "this file cannot match"; the per-line scan in
``check_obsoleted_terms`` still decides every finding.
"""

from __future__ import annotations

import re


def _required_literal_prefix(pattern: re.Pattern) -> str:
    """Conservatively recognize a mandatory literal at the pattern's start.

    Unknown syntax yields no filter. Top-level alternatives and verbose mode
    cannot establish one common prefix here. Optional repetition drops its
    preceding literal so the filter cannot discard a valid shorter match.
    """
    source = pattern.pattern
    if (
        pattern.flags & re.VERBOSE
        or "(?#" in source
        or re.search(r"\(\?[aiLmsu-]*x", source)
        or re.search(r"\[\^?\]", source)
    ):
        return ""
    depth = 0
    in_class = escaped = False
    for char in source:
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "|" and depth == 0:
            return ""
    source = re.sub(r"^\(\?[aiLmsux]+\)", "", source)
    source = source.removeprefix(r"\b").removeprefix("^")
    literal = []
    index = 0
    while index < len(source):
        char = source[index]
        if char in "*?{":
            if literal:
                literal.pop()
            break
        if char in ".+[]()^$|":
            break
        if char == "\\":
            index += 1
            if index == len(source) or source[index] not in r".\-_/(){}[]+*?^$|#":
                break
            char = source[index]
        literal.append(char)
        index += 1
    return "".join(literal)


def _required_candidate(pattern):
    """A leading literal or a complete choice of literal words is mandatory."""
    prefix = _required_literal_prefix(pattern)
    if prefix:
        required = re.escape(prefix)
        source = re.sub(r"^\(\?[aiLmsux]+\)", "", pattern.pattern)
        source = source.removeprefix(r"\b").removeprefix("^")
        marker = source.find(r"\s+")
        if marker >= 0 and source[:marker] in {prefix, required}:
            try:
                tail = re.compile(source[marker + 3 :], pattern.flags)
            except re.error:
                tail = None
            suffix = _required_literal_prefix(tail) if tail is not None else ""
            if suffix:
                required += r"\s+" + re.escape(suffix)
        return re.compile(required, pattern.flags)
    source = re.sub(r"^\(\?[aiLmsux]+\)", "", pattern.pattern)
    leading = source.removeprefix(r"\b").removeprefix("^")
    removable = re.match(
        r"^(?:[A-Za-z`_]\?|\[[A-Za-z]+\]|\(\?:[A-Za-z\\+ ]+\)\?)", leading
    )
    if removable:
        try:
            tail = re.compile(leading[removable.end() :], pattern.flags)
        except re.error:
            tail = None
        suffix = _required_literal_prefix(tail) if tail is not None else ""
        if suffix:
            return re.compile(re.escape(suffix), pattern.flags)
    choice = re.fullmatch(r"\\b\(([A-Za-z0-9_|]+)\)\\b", source)
    if choice:
        words = choice.group(1).split("|")
        if all(words):
            return re.compile(
                "(?:" + "|".join(map(re.escape, words)) + ")", pattern.flags
            )
    return None


def _whole_text_gate(source: str):
    """The pattern over a whole file, or None when line context could differ.

    A line's match is a substring of the file, so a file with no match has
    no matching line. Anchors, lookaround, and ``\\A``/``\\Z`` read line
    context a whole-file search sees differently, so those patterns keep the
    per-line scan alone.
    """
    # A negated class contains a caret without anchoring the match. Treating
    # it as an anchor forced common SQL candidates through every file line.
    if "(?#" in source or re.search(r"\(\?[aiLmsux-]*x", source):
        return None
    index = 0
    while index < len(source):
        char = source[index]
        if char == "\\":
            if source[index + 1 : index + 2] in {"A", "Z", "z"}:
                return None
            index += 2
            continue
        if char == "[":
            index += 1
            if source[index : index + 1] == "^":
                index += 1
            if source[index : index + 1] == "]":
                index += 1
            while index < len(source) and source[index] != "]":
                index += 2 if source[index] == "\\" else 1
        elif char in "^$" or source.startswith(("(?=", "(?!", "(?<=", "(?<!"), index):
            return None
        index += 1
    return re.compile(source, re.MULTILINE)


def _literal_choices(required: re.Pattern):
    """The literal strings *required* matches exactly, or None if it is a regex."""
    choice = re.fullmatch(r"\(\?:(.*)\)", required.pattern)
    alternatives = choice.group(1).split("|") if choice else [required.pattern]
    literals = []
    for alternative in alternatives:
        literal = re.sub(r"\\(.)", r"\1", alternative)
        if re.escape(literal) != alternative:
            return None
        literals.append(literal)
    return literals


def required_test(required):
    """A text -> bool presence check for *required*, or None when there is none.

    Literal candidates use substring checks, which answer the same question
    as the regex far faster across a whole file; anything else keeps the regex.
    """
    if required is None:
        return None
    literals = _literal_choices(required)
    if literals is None:
        return required.search
    if required.flags & re.IGNORECASE:
        folded = [literal.lower() for literal in literals]
        return lambda text: any(literal in text.lower() for literal in folded)
    return lambda text: any(literal in text for literal in literals)
