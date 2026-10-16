# Navigation contract

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Documentation](index.md) > Navigation contract
<!-- /yoke:breadcrumbs -->

Public source pages live under `docs/public`; installed projects receive the
same bytes under `.yoke/docs`. The packaged corpus and web publication consume
the same recursive `nav.yaml`. Retired docs URLs have no redirects.

## Tree schema

```yaml
root:
  title: Yoke
  summary: Software delivery from direction through verified delivery.
  path: index.md
  children:
    - title: Documentation
      summary: Write and verify complete, concise teaching.
      path: documentation/index.md
```

The only top-level key is `root`. Each node has non-empty string `title`,
`summary` and `path`, plus an optional ordered `children` list. Unknown and
duplicate keys, anchors, aliases and `<<` merge keys refuse. A category with
children has an `index.md` basename; the root path is `index.md`. Each page has
one parent, and every page must appear in the complete tree.

Paths are UTF-8 POSIX paths relative to the corpus root and end in `.md`.
Absolute paths, backslashes, empty, `.` or `..` segments, queries, fragments
and paths escaping the root refuse. In a source checkout the page must be
git-tracked (`git ls-files`); in a wheel snapshot, container or installed tree
it must be present under the root. Add new source pages to git before checking.

`load_navigation(root)` returns a frozen `NavNode(title, summary, path,
children)`, with children stored as a tuple. `iter_nodes` walks preorder;
`breadcrumbs(tree, path)` includes ancestors and the current node;
`immediate_children(tree, path)` preserves nav order. Unknown paths return an
empty list. Validation returns records with `code`, `target`, `detail` and
`repair`; loading an invalid tree raises `NavigationError` with those records.

## Routes and links

Strip `.md` and then terminal `/index` to derive a page route, prefixed by
`/docs`. Root `index.md` maps to `/docs`; `guide/index.md` maps to `/docs/guide`;
`guide/setup.md` maps to `/docs/guide/setup`. No route has a trailing slash.
`guide.md` and `guide/index.md` collide and cannot coexist in the tree.

Resolve relative links from the **containing page**, normalize parent
segments and refuse escapes. Fragment-only links stay on that page; external
schemes and network URLs pass through. Preserve the query and fragment when
replacing the resolved Markdown path with its route: from `guide/setup.md`,
`../index.md?mode=local#what-yoke-is` becomes
`/docs?mode=local#what-yoke-is`. File targets must exist; Markdown fragments
must match a heading id exactly after one percent-decode, case-sensitive.

`links(markdown)` returns `MarkdownLink(target, text)` records, including image
targets and their alt text. `resolve_link(page, target)` returns
`ResolvedLink(path, query, fragment, external)`; `.target` reconstructs the
local URL or returns the original external URL. Escapes raise `ValueError`.

## Heading fragments

Parse CommonMark with `markdown-it-py`, ignoring fenced and indented code.
Use ATX and setext heading tokens. Visible inline text consists of text,
inline code, link labels and image alt text; drop markup and inline HTML.
Character references in text are decoded by the parser. Transform in order:

1. Normalize to Unicode NFC, then lowercase.
2. Remove characters except Unicode letters (`L*`), marks (`M*`), numbers
   (`N*`), hyphen, underscore and whitespace.
3. Collapse whitespace runs to `-`, trim `-`, and use `section` if empty.
4. Reserve every emitted id in document order. On collision append `-1`,
   `-2`, and so on to the base until the candidate is unused.

`Setup & Run` becomes `setup-run`; its duplicate becomes `setup-run-1`;
a later literal `Setup Run-1` becomes `setup-run-1-1`. `Café` retains `é`;
an empty heading becomes `section`. Explicit HTML heading ids refuse with
`HTML_HEADING_ID`; use Markdown headings and the derived ids.

Shared producer/consumer cases live at
`runtime/api/domain/fixtures/documentation_conformance.json`: `headings` holds
`{markdown, expected_ids}`, `routes` holds `{path, route}`, and `links` holds
`{page, target, resolved}`. Each `resolved` object has `path`, `query`,
`fragment` and `external`. A consumer runs these cases against the same full
candidate commit it builds, including encoded fragments through route conversion.

## Derived blocks

`documentation_render write` places a breadcrumb block directly under the H1
on every non-root page, using ancestor titles linked by relative paths,
` > ` separators and the current title last:

```markdown
<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > Documentation
<!-- /yoke:breadcrumbs -->
```

At each category's end, a contents block lists every immediate child in nav
order as `- [title](relative path) — summary`, between `<!-- yoke:contents -->`
and `<!-- /yoke:contents -->`. These blocks are derived; edit the tree and
rerun `write`. Writes use atomic replacement under the session's work authority.

## Candidate identity

For a source checkout, resolve `git rev-parse HEAD` to a full 40-character
lowercase commit and verify it as a commit. The served checkout must be clean
and its HEAD must equal the declared candidate. An installed corpus receipt
must record the same `source_build` and the release as `source_engine_release`.
Never infer corpus identity from ambient package metadata, a wheel filename's
version or an older corpus on the machine.

For a wheel route, read `migration-history-record.json` and
`migration-history.json` beside the wheel. Authenticate the manifest SHA and
the wheel SHA and filename against that record; use `artifact.source_commit`
and `artifact.engine_version` as identity. Missing, malformed or mismatched
release evidence refuses with `CANDIDATE_IDENTITY_MISMATCH`; repair by rebuilding
from the declared full candidate commit with its matching release evidence.

## Consumer build evidence

The consumer writes one UTF-8 JSON file named `yoke-docs-build-evidence.json`
at the root of its build output. Platform publishes it with its build/release
evidence. It is an object with exactly three string keys:

- `consumer`: the consumer's stable name, for example `platform-docs`.
- `source_commit`: the full 40-character lowercase Yoke commit the corpus was
  materialized from (`git rev-parse HEAD` of that checkout).
- `built_at`: a UTC instant in RFC 3339 format with `Z`.

Unknown or missing keys, other types or an abbreviated commit make the
evidence malformed. Yoke verifies it with:

```text
python3 -m yoke_core.domain.install_bundle_docs_validation verify-candidate --root <yoke checkout> --commit <sha> --consumer-evidence <path>
```

`CONSUMER_PROOF_MISSING` means the file is absent, unreadable, malformed or its
`source_commit` differs from the declared commit. Repair: rebuild the consumer
from the declared full commit and supply its evidence.

`CANDIDATE_IDENTITY_MISMATCH` means the declared commit is not a full resolvable
commit, checkout HEAD differs, the served tree is dirty, installed receipt
`source_build` differs, or published bytes differ. Repair: rebuild from the
declared full candidate commit. For a dirty served tree the target lists the
changed paths and the repair is: commit or discard the listed changes and
rebuild from the declared full candidate commit.

## Named navigation refusals

Each checker prints `CODE target: detail. Repair: ...` and exits 1 for any
refusal. `NAV_SCHEMA`, `NAV_UNKNOWN_KEY`, `NAV_ALIAS` and `NAV_EMPTY_VALUE`
require correcting the node fields. `NAV_PATH_INVALID`, `NAV_PATH_ESCAPES`
and `NAV_PATH_MISSING` require a valid tracked or materialized in-root page.
`NAV_DUPLICATE_PAGE` and `NAV_CYCLE` require one acyclic parent per page.
`NAV_CATEGORY_NOT_INDEX` requires a category index; `NAV_ROUTE_COLLISION`
requires distinct routes; `UNLISTED_PAGE` requires adding the page to the tree.
Link checks name `LINK_ESCAPES`, `LINK_TARGET_MISSING` or
`LINK_FRAGMENT_MISSING` and teach the specific correction. `STALE_NAV_BLOCK`
requires rerunning `documentation_render write`; `LINE_LIMIT` requires a
coherent topic split. Successful checks print their page count.
