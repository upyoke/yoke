"""Shared substitution source boundaries preserve executable and inert spans."""

import unittest

from yoke_core.domain.path_claim_bash_substitution import (
    classify_substitution_bodies,
    executable_substitutions,
)


class TestSubstitutionSources(unittest.TestCase):
    def test_quotes_escapes_and_nested_sources(self):
        for text, bodies in (
            ("echo '$(rm file)'", []),
            ('echo "$(rm file)"', ["rm file"]),
            ('echo $(printf ")")', ['printf ")"']),
            ('echo "$(echo "$(date)")"', ['echo "$(date)"']),
            ("cat <(date)", ["date"]),
            ("echo " + chr(96) + "date" + chr(96), ["date"]),
            ("echo \\$(date)", []),
        ):
            with self.subTest(text=text):
                self.assertEqual(executable_substitutions(text)[1], bodies)

    def test_existing_mutation_contract_and_incomplete_syntax(self):
        self.assertEqual(classify_substitution_bodies('echo "$(rm file)"'), "ambiguous")
        self.assertEqual(classify_substitution_bodies("echo '$(rm file)'"), "ok")
        text = 'echo "$(pytest tests/'
        self.assertEqual(executable_substitutions(text), (text, []))

    def test_unquoted_heredoc_quotes_are_literal(self):
        self.assertEqual(
            executable_substitutions("'$(date)'", literal_quotes=True)[1],
            ["date"],
        )
