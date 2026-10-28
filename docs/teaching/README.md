# Yoke teaching prototype

Yokepedia catalogs the context Yoke gives people and agents. Its model records
concepts, teaching surfaces, scenarios, boundaries, evidence, and gaps. It
records lasting teaching facts, not copies of strategy documents or plans.
This contributor tool lives only in source and never ships in the install bundle.

Read it as Yokepedia: run `yoke dev yokepedia` anywhere inside a Yoke source
checkout or worktree. It builds `docs/teaching/views/yokepedia.html` from that
checkout and opens it in your browser; `--no-open` prints the path instead.
The page is one self-contained file that works from a `file:` URL with no
server. Agents and CI run the same build with
`yoke dev run -- python3 docs/teaching/tools/build.py` (and `--check`) from
the checkout they mean to build. This registered scanner needs no harness
session or work claim. It writes only the ignored page; it never rewrites the model.
Public pages, navigation, and visuals belong to `docs/public`. Yokepedia reads
that corpus for its map. Public docs never depend on teaching;
removing `docs/teaching` leaves them working. Agents can read model JSON directly.
Model JSON files retain their identities and remain the editable source of
research truth.

## Canonical source and access

### Human reading view

`yoke dev yokepedia` opens the responsive context guide.
Each page shows its immediate children in a normal CSS grid. Cards grow with
content and the browser scrolls naturally. Open a card to read or explore it;
breadcrumbs, the source navigator and browser Back preserve navigation.

The top level separates homepage, public docs, setup, global/project hooks,
project rules, skills, roles, command help, command replies, context packets,
scoped instructions and project documentation. Public docs has three children: Website docs page, Installed docs directory,
and The docs. Both access points link to The docs; the website also links to
the overview it displays on entry. Under The docs, the overview and actual
category/file tree appear once; agent replies and terminal screens sit under setup.
Dashboard teaching stays with the dashboard prototype. Instructions for
resuming work sit under Skills; changing work state is not teaching content.
Topics, Journeys and Research are not included in Yokepedia.

Source groups in `tools/explorer_sources.py` are editorial navigation, not
new authorities. New surfaces must be assigned to a group; the build reports
`EXPLORER_SOURCE` otherwise. The explorer reads source definitions, not captured session data. Availability never establishes actual context receipt.

Yokepedia is a local design review, not product-delivery proof. Search
highlighting across related context chains is reserved for after the operator
locks the map structure.

### Source access

Ordinary repository access is the canonical route. Every machine and worker
reads this directory from a Yoke checkout, or from the public repository at an
exact commit: `https://github.com/upyoke/yoke/tree/<commit>/docs/teaching`.
No shared-drive copy is a source. Private research stays outside this public
repository: no private operator state, user or session ids, recordings or
machine paths. The check refuses private paths and identifiers.

## Layout

| Path | Contents |
|---|---|
| `model/concepts/` | One concept per file; child concepts in matching directories |
| `model/surfaces/` | Surface record plus one teaching record per child file |
| `model/scenarios/` | Scenario record plus one lesson per child file |
| `model/evidence/` | Collection metadata plus one evidence record per child file |
| `model/boundaries/`, `model/gaps/` | One locked rule or open gap per file |
| `model/docs-graph.json` | Documentation areas for the live docs graph |
| `views/` | Untracked generated `yokepedia.html`; build locally to read |
| `tools/` | The builder and check |

Every record has a stable `id`; the guide uses it to identify the record's node.
A concept's full id is its path (`context/hooks`), stored at
`model/concepts/context/hooks.json`. Teaching and lesson ids are prefixed by
their owner (`setup-agent/desired-01`), stored at
`model/surfaces/setup-agent/desired-01.json`. Each filename matches its
record's local `id`. Add a record by creating its file; claim that concrete
path without changing or claiming its parent record. Optional `position`
sets display order (then filename). Legacy `page` metadata does not create pages or routes in the guide.
Evidence collection metadata lives at
`model/evidence/<collection>.json`, with records in the matching directory.
`docs-graph.json` remains the documentation graph configuration.

To reapply the mechanical conversion after taking upstream array files:

```text
yoke dev run -- python3 docs/teaching/tools/convert_model.py
```

The converter removes consumed arrays, preserves ids and content, and can be
rerun safely. An upstream array is authoritative for its converted records;
existing record files without an array source retain their data and receive
canonical formatting. Rebuild and check afterwards.

Commands, functions and skills are never copied here. Concept records name
them, and the check resolves every name against the live registries. The guide reads current command registries and tracked-document inventories at build time; it does not capture live session state. All generated views are untracked. The stylesheet source lives in `tools/explorer.css`.

## Record status

| Status | Meaning |
|---|---|
| `observed` | Seen in source or a capture; scope stated, behavior unproven |
| `verified-live` | Proven against running Yoke with recorded evidence |
| `candidate` | Reviewed proposal, not approved scope |
| `approved` | Approved scope or a locked boundary |
| `deferred` | Approved direction whose execution waits |
| `draft-copy` | Research outline or draft wording; not a shipped recipe |
| `superseded` | Replaced proposal kept for provenance |

Coverage counts direct teaching mappings only: a concept is mapped when a
teaching record names it in `topics`. A mapped parent never covers its
children, and a mapping never proves that the teaching works. Unmapped
concepts stay visible as gaps.

## Update the affected topics

Do this while planning and finishing any Yoke item that changes what Yoke
teaches. Review only the topics the work touches.

1. Find the concept, surface, scenario or boundary in the views.
2. Edit its record under `model/`. Keep its `id`.
3. Add missing topics or surfaces beside their peers and link them. Keep
   current state and desired state distinct through `status`. Record
   unfinished teaching as a `gaps/<id>.json` record with its evidence.
4. Rebuild and check:

   ```text
   yoke dev run -- python3 docs/teaching/tools/build.py
   yoke dev run -- python3 docs/teaching/tools/build.py --check
   ```

5. Commit the model in the item's own lane; build views locally to read them.
   Report the node links you changed in the item. Route gaps that need a
   decision to steering.

**Platform items never edit this directory.** When Platform work needs a
prototype change, file a linked Yoke item (`/yoke idea` in the yoke project)
that names the exact node ids, the requested change, the evidence and the
producer/consumer relationship.

## Source inventories

Every build refreshes registry entries with topic coverage and documents with
incoming/outgoing links inside the guide. It removes obsolete generated files
and the retired `live/` directory; no compatibility pages are produced.

## Check failures

Every build validates the model, renders in memory, then checks links and
privacy before it writes. Any problem exits 1 and reports every problem by file,
record and field, keeping the last good page. A successful build swaps the new
page in, then deletes obsolete generated files.
Fix the named records, rebuild, then run `--check`:

| Code | Repair |
|---|---|
| `UNKNOWN_STATUS` | Use one of the seven statuses above |
| `DUPLICATE_ID`, `DANGLING_PARENT` | Make ids unique; add the missing parent record |
| `DANGLING_REFERENCE` | Fix each named field's id or add its missing record; remove retired registry names |
| `DANGLING_SOURCE` | For an untracked file, stage it with `git add -- <path>`; for a missing file, create and stage it or cite an existing tracked path |
| `RETIRED_PLAN_MIRROR` | Delete `model/plan/` or the record's `plan_refs`; move any lasting fact into a scenario, surface, boundary or gap |
| `DANGLING_ANCHOR`, `DANGLING_LINK` | Fix the target id or path, then rebuild |
| `MODEL_NOT_CANONICAL` | Run `yoke dev run -- python3 docs/teaching/tools/convert_model.py`, then rebuild and check |
| `MODEL_RECORD_ID` | Store one record with an `id` matching its filename |
| `LINE_LIMIT` | Split the authored file at a meaningful boundary. Keep record content; rebuild |
| `PAGE_COLLISION` | Give the part a `page` name no other surface or scenario uses |
| `PRIVATE_MATERIAL` | Remove the private path or id |
| `GUIDE_SOURCE_UNREADABLE` | Restore the named document or record, or stop citing it |
| `GUIDE_ASSET_UNSAFE` | Build the named closing-tag or comment text in `tools/` from parts |
| `VIEWS_WRITE_FAILED` | Make `docs/teaching/views` writable; the last good page is kept |

Every authored file here obeys the shared 350-line hard limit, counted at 80
columns; 300 is the design target. The generated page is exempt from line limits
but privacy-scanned: its shell, every node and build data. Embedded document and
record text are verbatim copies of tracked files that their owners check.
`--check` validates the model and builds the page in memory, checking links,
privacy and limits without reading or writing local views. CI runs this build validation through
`tests/teaching_prototype/test_teaching_prototype_check.py`.

The homepage contains the agent request and install command. Named connections
lead from that command to agent and interactive setup; the connection panel
also shows incoming routes and the connections inherited from a parent source.
Public docs follow the actual directories, category index headings and document
names in `docs/public`, including the root overview and contents. Project docs
show this repository's current documentation, excluding public docs, archives
and teaching research. Rules, skills and roles expose their files and named
sections. Setup questions and literal answer choices are extracted from
`SetupPrompt` definitions; dynamic values remain in the folded source definition.
Hooks show orientation blocks, registered events, tool matchers and handlers.
Packets show the registered roles, topics and table references. Command results
show the shared envelope and declared response models with their actual fields.
Scoped instructions show the shipped text and the command that reads privately
scoped instructions; no private records or live session payloads are copied.
These connections describe source routes, not proof of live delivery.

Each page keeps the title, summary, applicability and output size above its cards.
Leaf pages show their full content; parents provide a Read full content disclosure.
Related-source links appear below the grid. Hash URLs restore the selected node
on refresh, including alternate representations with their arrival breadcrumbs.
There is no canvas, pan/zoom, hover tracing, clipped card preview or floating control.

Node types describe content form, not review status. Every node carries a short
label, icon and form-specific card treatment: pages, files, conceptual groups,
concepts, CLI groups/commands, screens, replies, hooks, packets and scoped rules.
Research teaching records do not appear as source nodes. Files show their actual
source path; code definitions are folded beneath the visible content or fields. A command that also has children is marked as both.

The AGENTS.md source opens directly onto shared topics and repository additions,
with no duplicate file level. Shared topics come from the shipped template;
repository topics come only from outside the local managed block. This includes
level-one headings and the shipped preamble, not just level-two sections.
Audience scope is independent of content form: green globe labels mean All Yoke
projects; purple branch labels mean Yoke repo only. Repository documentation
inherits the latter; product docs, skills, roles and runtime definitions retain
the shared label. A shared label describes distribution, not unconditional
applicability of every instruction. Private user/project instructions are not
invented or loaded into this map.

Hook message cards expose their concrete message sections. Both hook views show events directly, with their messages, checks and background
actions nested inside. Global contents use the runtime applicability filter;
project and global event cards link as two views of the same hook. Message sections
use a neutral text style, distinct from purple event containers. Message bodies are descriptions of templates, not live
session captures. Readable guidance shows exact UTF-8 byte and line counts (character
counts on hover); implementation code has no size badge. Generated messages show
output estimates in lines and bytes, or explicitly variable output when bodies are unbounded. Containers total their child output estimates; an exact document or whole-message
sample already includes its children and is counted once. Links do not add text.
Variable hook messages also show estimates from offline examples: synthetic IDs,
zero to five project folders, and explicit allowances for setup or other variable
fields. Hover for each estimate's assumptions. These are illustrative ranges, not
observed percentiles or hard limits; open-ended instruction bodies show a base size
plus variable content. Every card has a line/byte range or an explicit variable remainder. Incoming message
parts are measured from output templates with synthetic IDs and optional notices.
Unsampled output uses visibly labelled rough planning bands, documented on hover;
these are not measured renders. Parent totals are an inventory, not a claim that
all conditional messages are delivered together.
Long Markdown leaves (80 words or more) expose headings or original passages as
subnodes. Incoming-message and resume-message topics describe the delivered prose.

Reading order follows the encounter sequence: public entry and installation,
global context, project rules and context, then work procedures and command use.
Both hook views use session start → prompt → before tool → permission → tool
success/failure → stop → session end. These are lifecycle positions, not a promise
that every event fires in every harness. Setup keeps its declared step order;
public documents follow nav.yaml; skills and roles follow their workflow groups.

Harness-specific orientation cards show prominent applicability badges and delivery timing: Codex / Claude Code on the first prompt, Cursor only at session start.

Alternate install-mode cards expose the actual setup subtree in place. Cross-map navigation retains a Back button to the previous view.

Command help separates root output from the command-group tree. Every group has its own rendered help output alongside child commands; all groups remain available through normal page scrolling.

Cards have no fixed heights or nested preview layers; each title and Explore link opens the next level.


## Sources guide

Sources catalogs the teaching surfaces; Index lists curated terms. Pack documentation and Decisions sit
alongside the other context sources. The guide does not generate topic trees,
journeys, research pages, coverage inventories or links to those pages.
Approved decisions remain readable under Decisions, with their original fields
and citations. Shared model records remain available to repository tooling;
they are not additional browsing sections.

The Index is owned by `model/terms/*.json`, one term per file with an id,
term, definition, draft status and source paths. `explorer_terms.py` checks
unique names and source links; Yokepedia renders an alphabetical searchable
list. Optional `aliases` hold alternate or plural names on the same canonical term; search matches them and the index displays them as “Also called.” Term and alias names must be unique across records. Page titles that combine concepts do not create combined index terms. Terms link into Sources. The index is internal teaching material and
is not published in `docs/public` or the install bundle.

Source freshness shows the build time, checkout commit, dirty state and a digest
of inspected files plus registry identities. Each build re-reads documents, runtime
definitions, command help formatters, model references and inventories. No copied
research text becomes authoritative current behavior. Editorial group names and
research judgements remain authored; historical evidence is not reverified by a
build. Rebuild and refresh after source changes; this local preview is a snapshot,
not a background monitor of main or a released installation.

## Public docs map

The Docs map reads page titles, routes, headings, and related-page links from
`docs/public`. The public corpus owns the documentation structure and content.
`model/docs-map/*.json` adds teaching associations: index terms, commands,
sources, reader needs, and open questions. It does not own a separate page tree.
Getting started lives only in public docs; Yokepedia maps it without a preview.

Command groups and source groups expand to their existing descendants.
Root CLI help is orientation only and never maps every command.
Coverage compares detailed-page mappings with the current index, command
leaves, and source documents/outputs; overview references do not close gaps.
It reports unmapped entries, terms on several pages, and sizing prompts.
Mapped means related for review, not verified or delivered.
All pages should start with a human summary; detailed agent teaching can
remain in the linked context chain, skills, packets, and command feedback.
