"""Layered human navigation over the teaching model, generated beside the catalogue."""

from pathlib import Path
from urllib.parse import quote

from explorer_records import ROOT, card, collection, details, location, shell, teaching_pages, tiles
from explorer_sources import SOURCES, STAGES
from render import esc, link


def build_explorer(views, pages):
    m = pages.m
    owners = {}
    for source in SOURCES:
        for sid in source['surfaces']:
            if sid not in m.surfaces or sid in owners:
                m.problem('EXPLORER_SOURCE', 'tools/explorer_sources.py',
                          f'{sid}: assign each existing surface to one source')
            owners[sid] = source
    for sid in m.surfaces.keys() - owners.keys():
        m.problem('EXPLORER_SOURCE', 'tools/explorer_sources.py',
                  f'{sid}: add this surface to its human-facing source group')
    if m.problems:
        return
    views['explore/explorer.css'] = Path(__file__).with_name('explorer.css').read_text()
    overview(views)
    for source in SOURCES:
        source_page(views, pages, source)
    teaching_pages(views, pages, owners)
    topic_pages(views, pages)
    command_pages(views, pages)


def overview(views):
    body = ['<div class="journey" aria-label="Reading path">',
            '<span>Read the website</span><b>→</b><span>Run setup</span><b>→</b>',
            '<span>Enter a session</span><b>→</b><span>Do the work</span></div>']
    for number, (stage, description) in enumerate(STAGES.items(), 1):
        body += [f'<section><div class="section-title"><span>0{number}</span>',
                 f'<div><h2>{stage}</h2><p>{esc(description)}</p></div></div>',
                 '<div class="grid">']
        for source in SOURCES:
            if source['stage'] == stage:
                body.append(card(ROOT, location('sources', source['id']),
                                 source['title'], source['summary'],
                                 source['timing'], source['mark']))
        body += ['</div></section>']
    body += ['<aside class="callout"><strong>Available ≠ received.</strong> '
             'A file or hook can be installed before this session actually '
             'loads it. Open a source to inspect its delivery and evidence.</aside>',
             '<div class="browse"><div><h2>Looking for a topic instead?</h2>',
             '<p>Browse the underlying concept tree one level at a time.</p></div>',
             link(ROOT, 'explore/topics.html', 'Browse topics →'), '</div>']
    views[ROOT] = shell(ROOT, 'Where does context come from?',
                        'Start with a source. Open its tree. Follow it down to the exact teaching.', body)


def source_page(views, pages, source):
    path = location('sources', source['id'])
    body = ['<section class="delivery"><span class="eyebrow">When it enters</span>',
            f'<h2>{esc(source["timing"])}</h2>',
            f'<p>{esc(source["delivery"])}</p></section>']
    if source['id'] == 'help':
        body += tiles(path, [(command_path('yoke'), 'Command tree',
                              'Root → group → operation → mapped concept. Browse one level at a time.',
                              'From model command references', '?')])
    body += ['<h2>Inside this source</h2>', '<div class="grid">']
    archived = []
    for sid in source['surfaces']:
        record = pages.m.surfaces[sid]
        tile = card(path, location('surfaces', sid), record['title'],
                    record.get('encounter', ''), record['status'])
        if record['status'] == 'superseded':
            archived.append(tile)
        else:
            body.append(tile)
    body += ['</div>']
    if archived:
        body += ['<details class="history"><summary>Earlier proposals</summary>',
                 '<p>Kept for research history; these are not active sources.</p>',
                 '<div class="grid">', *archived, '</div></details>']
    views[path] = shell(path, source['title'], source['summary'], body)


def topic_pages(views, pages):
    m = pages.m
    root = 'explore/topics.html'
    roots = [(location('topics', cid), node['title'], '',
              f'{len(node["children"])} branches')
             for cid, node in m.concepts.items() if node['parent'] is None]
    collection(views, root, 'What does Yoke teach?',
               'Choose a subject, then follow its branches. Only one level is shown at a time.', roots)
    for cid, node in m.concepts.items():
        path = location('topics', cid)
        crumbs = [(root, 'Topics')]
        if node['parent']:
            parent = m.concepts[node['parent']]
            crumbs.append((location('topics', node['parent']), parent['title']))
        before = details(pages, path, node)
        mapped = pages.cov[cid]
        if mapped:
            before += ['<details><summary>Where this topic is taught</summary>']
            before += ['<p>' + link(path, location('teachings', rid),
                                    m.teaching[rid]['title']) + '</p>' for rid in mapped]
            before += ['</details>']
        else:
            before += ['<p class="quiet">No direct surface teaching is mapped to this topic.</p>']
        entries = [(location('topics', child), m.concepts[child]['title'], '',
                    m.concepts[child]['status']) for child in node['children']]
        if entries:
            before += ['<h2>Go deeper</h2>']
        collection(views, path, node['title'],
                   'A concept in the teaching map; mapping alone does not prove delivery.',
                   entries, crumbs, before)


def command_path(command):
    return location('commands', '/'.join(quote(word, safe='') for word in command.split()))


def command_pages(views, pages):
    commands, children = {}, {}
    for cid, concept in pages.m.concepts.items():
        for command in concept.get('commands', []):
            commands.setdefault(command, []).append(cid)
            words = command.split()
            for n in range(1, len(words) + 1):
                prefix = ' '.join(words[:n])
                children.setdefault(prefix, set())
                if n < len(words):
                    children[prefix].add(' '.join(words[:n + 1]))
    children.setdefault('yoke', set())
    for command, descendants in children.items():
        path = command_path(command)
        crumbs = [(location('sources', 'help'), 'Command help')]
        parent = command.rpartition(' ')[0]
        if parent:
            crumbs.append((command_path(parent), parent))
        before = [f'<p class="callout"><code>{esc(command)} --help</code></p>']
        if command in commands:
            before += ['<details><summary>Mapped concepts &amp; source references</summary>']
            before += ['<p>' + link(path, location('topics', cid),
                                    pages.m.concepts[cid]['title']) + '</p>'
                       for cid in commands[command]]
            before += ['</details>']
        entries = [(command_path(child), child, '',
                    'Group' if children[child] else 'Operation')
                   for child in sorted(descendants)]
        collection(views, path, command,
                   'Command names referenced by the model, validated against the registry at build time. '
                   'Run help for current options and recipes.', entries, crumbs, before)
