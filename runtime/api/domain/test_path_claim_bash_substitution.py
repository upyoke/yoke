"""Shared substitution source boundaries preserve executable and inert spans."""

import unittest

from yoke_core.domain.path_claim_bash_parser import extract_mutations
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


class TestSubstitutionStages(unittest.TestCase):
    def test_every_stage_of_every_substitution_body_is_checked(self):
        for text in (
            "x=$(cat f | tee docs/out.md)",
            "x=$(ls; rm docs/a.md)",
            "echo " + chr(96) + "cat f | tee docs/b.md" + chr(96),
            "diff a >(sort | tee docs/c.md)",
            "echo $(echo $(cat f | rm docs/d.md))",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify_substitution_bodies(text), "ambiguous")

    def test_read_only_substitution_pipelines_stay_ok(self):
        for text in (
            "count=$(ls src | wc -l)",
            "pytest $(find tests -name x.py | head -1)",
            "f=$(mktemp); echo hi",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify_substitution_bodies(text), "ok")

    def test_path_claim_parser_keeps_substitution_pipes_in_one_segment(self):
        self.assertEqual(extract_mutations("count=$(ls src | wc -l) && echo $count"), [])
        self.assertEqual(
            [m.verb for m in extract_mutations("x=$(cat f | tee docs/out.md)")],
            ["ambiguous"],
        )
        muts = extract_mutations("cat $(ls | head -1) | tee docs/x.md")
        self.assertEqual([(m.verb, m.target_path) for m in muts], [("tee", "docs/x.md")])
