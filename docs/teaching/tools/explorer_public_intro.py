"""Render the public-owned introduction for the teaching preview."""
import base64
import html
import re
from pathlib import Path
from markdown_it import MarkdownIt

PUBLIC = Path(__file__).resolve().parents[2] / 'public'
ASSETS = PUBLIC / 'assets'
CSS = ('getting-started.css', 'hosting.css', 'fleet.css', 'workflow.css',
       'frontier.css', 'qa.css', 'deployment.css')


def public_intro_css():
    return '\n'.join((ASSETS / name).read_text() for name in CSS)


def asset_html(name):
    if not re.fullmatch(r'[a-z-]+', name):
        raise ValueError('invalid public visual name')
    content = (ASSETS / 'visuals' / (name + '.html')).read_text()
    def image(match):
        path = ASSETS / Path(match[1]).name
        encoded = base64.b64encode(path.read_bytes()).decode('ascii')
        return 'src="data:image/svg+xml;base64,' + encoded + '"'
    return re.sub(r'src="([^"]+\.svg)"', image, content)


def public_intro_html():
    source = (PUBLIC / 'index.md').read_text()
    source = re.sub(r'<!-- yoke:(breadcrumbs|contents) -->.*?<!-- /yoke:\1 -->',
                    '', source, flags=re.S)
    rendered = MarkdownIt('commonmark', {'html': True}).render(source)
    rendered = re.sub(r'<!-- yoke:visual ([a-z-]+) -->',
                      lambda m: asset_html(m[1]), rendered)
    rendered = re.sub(r'<p><strong>Open Claude Code, Codex, or Cursor and say:</strong> '
                      r'<code>install upyoke.com</code></p>',
                      lambda m: '<div class="intro-install-row">' + m[0].replace(
                          '<code>', '</p><div class="intro-install-command"><code>', 1
                      ).replace('</code></p>', '</code><button type="button" data-copy="install upyoke.com">Copy</button></div>') + '</div>', rendered)
    rendered = rendered.replace('<p>Run in your Terminal:</p>\n<p><code>yoke ui up</code></p>',
        '<div class="intro-install-row"><p>Run in your Terminal:</p><div class="dashboard-access-command"><code>yoke ui up</code>'
        '<button type="button" data-copy="yoke ui up">Copy</button></div></div>')
    rendered = rendered.replace('<p>Private beta</p>\n<p><a href="https://app.upyoke.com">Log in at app.upyoke.com ↗</a></p>',
        '<div class="dashboard-hosted-access"><a class="dashboard-access-link" href="https://app.upyoke.com">Log in at app.upyoke.com ↗</a>'
        '<span class="dashboard-beta-pill">Private beta</span></div>')
    def more_links(match):
        links = re.findall(r'<p><a href="([^"]+)">More on (.*?)</a></p>', match[0])
        return '<nav class="intro-article-links" aria-label="Read more">' + ''.join(
            '<a href="' + href + '"><span class="intro-link-label">MORE ON</span>'
            '<span>' + title + '</span></a>' for href, title in links) + '</nav>'
    rendered = re.sub(r'(?:<p><a href="[^"]+">More on .*?</a></p>\s*)+',
                      more_links, rendered)
    def page_link(match):
        path = match[1]
        key = 'reference' if path == 'reference/index' else path
        return 'href="#page%3A' + html.escape(key, quote=True) + '" data-public-page="' + html.escape(key, quote=True) + '"'
    rendered = re.sub(r'href="guide/([^"#]+)\.md"', page_link, rendered)
    icon = base64.b64encode((ASSETS / 'steering.svg').read_bytes()).decode('ascii')
    rendered = re.sub(r'<strong>STEERING</strong>',
                      '<span class="intro-steering"><img alt="" src="data:image/svg+xml;base64,'
                      + icon + '">STEERING</span>', rendered)
    return rendered
