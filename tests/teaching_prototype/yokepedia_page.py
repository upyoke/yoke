"""Read the data and scripts embedded in a generated Yokepedia page."""

import json
import re

_DATA = re.compile(
    r'<script id="yokepedia-data" type="application/json">(.*?)</script>', re.S
)
_INLINE = re.compile(r"<script>\n(.*?)</script>", re.S)


def page_data(html):
    """Parse the embedded JSON exactly as the browser's JSON.parse would."""
    match = _DATA.search(html)
    assert match, "yokepedia page has no embedded data block"
    return json.loads(match.group(1))


def page_nodes(html):
    return {node["id"]: node for node in page_data(html)["nodes"]}


def inline_scripts(html):
    return _INLINE.findall(html)
