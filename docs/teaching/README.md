# Yoke teaching prototype

The catalog of every kind of context Yoke gives agents and people, up front
and in each situation, so the right things are taught in the right places.
It holds only lasting teaching facts: the concept tree, the surfaces that
carry teaching, the scenarios (situations an agent or person is in), locked
boundaries, evidence and gaps. It never copies or reconciles against a
strategy document; plans change outside any item, so a lasting fact a plan
names belongs in one of these records instead. It is internal contributor
material: it lives only in the Yoke source repository and never ships in the
install bundle.

Build the local views with `yoke dev run -- python3 docs/teaching/tools/build.py`,
then open `docs/teaching/views/index.html` in a browser from that checkout.
This registered scanner works on the mapped main checkout without a work claim
and in a claimed lane. It writes only ignored views (and `live/` with `--live`);
it never rewrites the model.
Agents read the model JSON directly. If a review tool refuses `file:` URLs,
serve this directory locally (`python3 -m http.server` from `docs/teaching`).
The gap index links to one generated page per gap; existing index anchors stay
valid. The overview links to each record home; aggregate model counts stay out of
that shared page so independent model edits can land together.

## Canonical source and access

### Human reading view

Open `views/explore/index.html` after building for the single-page context
map. Drag to pan, scroll to zoom, or click a node to focus it. Zooming reveals
nested sources, surfaces, teachings, command branches and concept branches
in place; leaf detail loads the canonical record. Whole map and Up one level
move the camera without opening another page.

The top level separates homepage, public docs, setup, global/project hooks,
project rules, skills, roles, command help, command replies, context packets,
scoped instructions and project documentation. Website and installed docs
link to shared content; agent replies and terminal screens sit under setup.
Dashboard teaching stays with the dashboard prototype. Instructions for
resuming work sit under Skills; changing work state is not teaching content.
Abandoned proposals are omitted from this reading view but remain in the
research catalogue. Research notes sit beneath plain-language explanations.

Source groups in `tools/explorer_sources.py` are editorial navigation, not
new authorities. New surfaces must be assigned to a group; the build reports
`EXPLORER_SOURCE` otherwise. Included nodes retain their recorded status. Availability never establishes actual context receipt.

Serve the checkout root over loopback: `python3 -m http.server 8765 --bind
127.0.0.1` from the checkout, then open
`/docs/teaching/views/explore/index.html`. This is a local design review, not
product-delivery proof. Search highlighting across related context chains is
reserved for after the operator locks the map structure.

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
| `views/` | Untracked generated HTML and CSS; build locally to read |
| `tools/` | The builder and check |
| `live/` | Untracked live pages, written by `--live` |

Every record has a stable `id`; it is the HTML anchor of the record's view.
A concept's full id is its path (`context/hooks`), stored at
`model/concepts/context/hooks.json`. Teaching and lesson ids are prefixed by
their owner (`setup-agent/desired-01`), stored at
`model/surfaces/setup-agent/desired-01.json`. Each filename matches its
record's local `id`. Add a record by creating its file; claim that concrete
path without changing or claiming its parent record. Optional `position`
sets display order (then filename). `page` names the generated page a record
renders on: give a large concept branch its own page by setting `page` on the
child and each descendant; surface and scenario parts move the same way.
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
them, and the check resolves every name against the live registries. The
command crosswalk and documentation graph read live state, so they are written
only to the untracked `live/` directory; generated views depend on the model
alone and are also untracked. The stylesheet source lives in `tools/style.css`.

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

## Live pages

```text
yoke dev run -- python3 docs/teaching/tools/build.py --live
```

writes `live/commands.html` (live totals and every unmapped command, function
and skill) and `live/docs-graph.html` (every tracked document by area, with
inbound and outbound link counts).

## Check failures

Every build validates the model before rendering. Invalid models exit 1 and
report every problem by file, record and field, without replacing local views.
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
| `LINE_LIMIT` | For a view, move a large child branch or part group to its own page with `page`; for another file, split it at a meaningful boundary. Keep record content; rebuild |
| `PAGE_COLLISION` | Give the part a `page` name no other surface or scenario uses |
| `PRIVATE_MATERIAL` | Remove the private path or id |

Every file here obeys the shared 350-line hard limit, counted at 80 columns;
300 is the design target. `--check` validates the model and builds views in
memory, checking links, privacy and limits without reading or writing local
views. CI runs this build validation through
`tests/teaching_prototype/test_teaching_prototype_check.py`.

The homepage contains the agent request and install command. Named connections
lead from that command to agent and interactive setup; the connection panel
also shows incoming routes and the connections inherited from a parent source.
Setup, hooks, rules, feedback and working guidance group individual instructions
by purpose. Skills group by work type, roles by responsibility, and nested skills
sit below their parent procedure. Public topics and command help retain their
existing trees. These connections describe context routes, not live execution.

Clicking a node reflows its subtree to the viewport and hides neighboring trees.
Nested nodes expand while their children have readable space; click a smaller
node to give it the full viewport. Breadcrumbs and Whole map restore context.
Node headings omit research-status and node-type labels.

The explorer includes a persistent source navigator and a separate connection
panel. Hover or keyboard-focus a visible node to highlight its connected sources;
Show connections displays the named routes between visible groups. Collapsed
children map their connections to the visible parent. Command nodes come from
the registered command inventory, with teaching references attached where known.

Node types describe content form, not review status. Every node carries a short
label, icon and form-specific card treatment: pages, files, conceptual groups,
concepts, CLI groups/commands, screens, replies, hooks, packets and scoped rules.
Teaching records are explicitly summaries or guidance about those surfaces;
they are not presented as captured runtime payloads. Skill and role files show
their actual source path. A command that also has children is marked as both.
