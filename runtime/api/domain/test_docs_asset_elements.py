"""Keep public docs assets inside the hosted consumer's published element rules."""

from html.parser import HTMLParser
from pathlib import Path
import re

import pytest

from yoke_contracts.project_contract.docs_corpus_files import CorpusRefusal
from yoke_core.domain.docs_corpus_rule import load_asset_rule

ASSETS = Path(__file__).resolve().parents[3] / "docs/public/assets"


class AssetParser(HTMLParser):
    def __init__(self, target, rule):
        super().__init__(convert_charrefs=False)
        self.target = target
        self.allowed = rule["allowedElements"][target.suffix[1:]]
        self.refused_style = re.compile(rule["refusedStyleTextPattern"], re.IGNORECASE)
        self.style_text = None

    def handle_starttag(self, tag, attrs):
        assert tag in self.allowed, (
            f"{self.target}: unsupported element <{tag}>; "
            "use an element allowed by docs-corpus-files.json"
        )
        if tag == "style":
            self.style_text = ""

    def handle_endtag(self, tag):
        assert tag in self.allowed, (
            f"{self.target}: unsupported element </{tag}>; "
            "use an element allowed by docs-corpus-files.json"
        )
        if tag == "style" and self.style_text is not None:
            match = self.refused_style.search(self.style_text)
            assert match is None, (
                f"{self.target}: unsupported <style> text {match.group()!r}; "
                "remove the refused CSS from the asset"
            )
            self.style_text = None

    def handle_data(self, data):
        if self.style_text is not None:
            self.style_text += data


def test_public_docs_assets_follow_published_element_rules():
    rule = load_asset_rule()
    assert not isinstance(rule, CorpusRefusal), rule
    for target in sorted(ASSETS.rglob("*")):
        if target.suffix in {".svg", ".html"}:
            parser = AssetParser(target.relative_to(ASSETS), rule)
            parser.feed(target.read_text(encoding="utf-8"))
            parser.close()


@pytest.mark.parametrize("suffix,markup,refused", [
    ("svg", '<svg><style>.a { fill: red }</style><path/></svg>', None),
    ("svg", '<svg><script/></svg>', "<script>"),
    ("html", '<div><style>p { color: red }</style></div>', "<style>"),
    ("svg", '<svg><style>.a { fill: URL (x) }</style></svg>', "<style> text"),
    ("svg", '<svg><style>@IMPORT "x";</style></svg>', "<style> text"),
    ("svg", '<svg><style>.a { x: expression (x) }</style></svg>', "<style> text"),
])
def test_asset_refusals_name_file_and_element(suffix, markup, refused):
    rule = load_asset_rule()
    assert not isinstance(rule, CorpusRefusal), rule
    parser = AssetParser(Path(f"example.{suffix}"), rule)
    if refused is None:
        parser.feed(markup)
        parser.close()
    else:
        with pytest.raises(AssertionError) as exc:
            parser.feed(markup)
            parser.close()
        assert f"example.{suffix}" in str(exc.value)
        assert refused in str(exc.value)
