"""Preserve old page URLs and record anchors as routes into the unified guide."""
import json
import posixpath
from html import escape


def redirect(here, default, anchors=None):
    anchors = anchors or {}
    target = posixpath.relpath('/views/explore/index.html', posixpath.dirname('/views/' + here))
    # Fragment routes are resolved by the guide after its data is loaded.
    data = json.dumps({'base': target, 'default': default, 'anchors': anchors}).replace('<', '\\u003c')
    ids = '\n'.join('<span id="' + escape(key, quote=True) + '"></span>' for key in anchors)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Teaching guide</title></head>
<body><p>This page is now part of the teaching guide.</p>
<a href="{escape(target)}">Open the teaching guide</a>
{ids}
<script>
const route = {data};
let anchor;
try {{ anchor = decodeURIComponent(location.hash.slice(1)); }} catch {{ anchor = ''; }}
location.replace(route.base + '#' + encodeURIComponent(route.anchors[anchor] || route.default));
</script></body></html>
'''
