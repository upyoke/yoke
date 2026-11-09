"""Keep literal suffix punctuation distinguishable after shlex removes quotes."""

from __future__ import annotations

import shlex


class ShellWord(str):
    """An ordinary argv string with the size of its unquoted shell suffix."""

    def __new__(cls, value: str, shell_suffix: int):
        word = super().__new__(cls, value)
        word.shell_suffix = shell_suffix
        return word

    def __getitem__(self, key):
        value = super().__getitem__(key)
        if isinstance(key, slice):
            start, stop, step = key.indices(len(self))
            if step == 1 and stop == len(self):
                return ShellWord(value, min(self.shell_suffix, stop - start))
        return value


def shell_words(statement: str) -> list[str]:
    """Use shlex's token boundaries to retain each raw word's suffix length."""
    lexer = shlex.shlex(statement, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    words = []
    while True:
        start = lexer.instream.tell()
        value = lexer.get_token()
        if value is None:
            return words
        raw = statement[start:lexer.instream.tell()].rstrip()
        end = len(raw)
        while end and raw[end - 1] in ");&":
            before = raw[:end - 1]
            escapes = len(before) - len(before.rstrip("\\"))
            if escapes % 2:
                break
            end -= 1
        words.append(ShellWord(value, len(raw) - end))
