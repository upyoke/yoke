"""Small standalone explorer pages and links to the canonical research detail."""

from posixpath import dirname, relpath

from render import badge, esc, href, link, wrap
from render_overview import STATUS_MEANING

ROOT = "explore/index.html"


def location(kind, rid):
    return f"explore/{kind}/{rid}.html"


def shell(path, title, intro, body, crumbs=()):
    trail = [(ROOT, "Sources"), *crumbs]
    nav = ' <span aria-hidden="true">/</span> '.join(
        link(path, target, label) for target, label in trail
    )
    lines = [
        '<!doctype html>', '<html lang="en">', '<head>',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<title>{esc(title)} · Teaching explorer</title>',
        f'<link rel="stylesheet" href="{href(path, "explore/explorer.css")}">',
        '</head>', '<body>',
        '<a class="skip" href="#content">Skip to content</a>',
        '<header><div class="brand">yoke <span>/ teaching explorer</span></div>',
        '<span class="review">Design in review</span></header>',
        '<main id="content">',
        f'<nav aria-label="Breadcrumb">{nav}</nav>',
        f'<h1>{esc(title)}</h1>', f'<p class="intro">{esc(intro)}</p>',
        *body,
        '</main><footer>',
        *wrap('A new reading view over the existing teaching model. '
              'Source observations and proposals retain their recorded status.'),
        link(path, "index.html", "Research catalogue"),
        '</footer></body></html>',
    ]
    return '\n'.join(line for chunk in lines for line in wrap(chunk)) + '\n'


def card(path, target, title, description="", meta="", mark="↗"):
    return (
        f'<a class="card" href="{href(path, target)}">'
        f'<span class="card-top"><span class="mark">{esc(mark)}</span>'
        f'<span class="meta">{esc(meta)}</span></span>'
        f'<h3>{esc(title)}</h3><p>{esc(description)}</p>'
        '<span class="open">Explore <span aria-hidden="true">→</span></span></a>'
    )


def tiles(path, entries):
    return ['<div class="grid">', *[
        card(path, *entry) for entry in entries
    ], '</div>']


def collection(views, path, title, intro, entries, crumbs=(), before=()):
    """Each page has at most twelve choices; never hide a tail of the tree."""
    pages = [entries[i:i + 12] for i in range(0, len(entries), 12)] or [[]]
    for i, group in enumerate(pages):
        here = path if i == 0 else path.removesuffix('.html') + f'-page-{i + 1}.html'
        body = list(before) + tiles(here, group)
        if len(pages) > 1:
            body.append('<nav class="pagination" aria-label="Pages">')
            for n in range(len(pages)):
                target = path if n == 0 else path.removesuffix('.html') + f'-page-{n + 1}.html'
                body.append(f'<strong>Page {n + 1}</strong>' if n == i else
                            link(here, target, f'Page {n + 1}'))
            body.append('</nav>')
        views[here] = shell(here, title, intro, body, crumbs)


def details(pages, path, record):
    """Keep all authored record fields reachable without making a wall of text."""
    status = record.get('status', 'observed')
    out = ['<section class="record">', f'<p>{badge(status)}</p>',
           f'<p>{esc(STATUS_MEANING.get(status, status))}</p>',
           '<details><summary>Full record, sources & evidence</summary>']
    out += pages.details(path, record, {'title', 'status'})
    if record.get('file'):
        target = relpath(record['file'], dirname('docs/teaching/views/' + path))
        out.append(f'<p><a href="{esc(target)}">Open canonical JSON</a></p>')
    out += ['</details></section>']
    return out


def teaching_pages(views, pages, source_by_surface):
    m = pages.m
    for sid, surface in m.surfaces.items():
        here = location('surfaces', sid)
        group = source_by_surface[sid]
        crumbs = [(location('sources', group['id']), group['title'])]
        parts = [m.teaching[rid] for rid in surface['parts']]
        entries = [(location('teachings', part['full_id']), part['title'],
                    '', part['status']) for part in parts]
        before = [f'<p class="callout">{esc(surface.get("encounter", ""))}</p>']
        before += details(pages, here, surface)
        collection(views, here, surface['title'], surface.get('location', ''),
                   entries, crumbs, before)
        for part in parts:
            path = location('teachings', part['full_id'])
            body = details(pages, path, part)
            topics = part.get('topics', [])
            if topics:
                body += ['<h2>Topics this teaching names</h2>']
                body += tiles(path, [(location('topics', cid), m.concepts[cid]['title'])
                                     for cid in topics])
            views[path] = shell(path, part['title'], 'One teaching, with its recorded evidence.',
                                body, crumbs + [(here, surface['title'])])
