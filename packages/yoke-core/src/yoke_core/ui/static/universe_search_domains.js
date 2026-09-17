// What universe search actually searches. One module per concern: this one
// owns the six domains — which read answers for each, how a row becomes a
// result, and where that result goes. The dialog above it owns presentation
// and knows none of this.
//
// Scope is the universe and the operator's permissions. The project selector
// does NOT narrow it: a project-scoped read is asked of every project instead,
// and each result names the project it came from. That is why a search for a
// slug you half-remember finds it wherever it lives.

import { buildUniverseRoute } from "./universe_navigation.js";
import { itemDrillInHref } from "./universe_item_routes.js";

// The chips the empty state shows, in the order it shows them — which is the
// order results appear in: what an operator is most often looking for first.
export const SEARCH_DOMAINS = [
  { key: "items", label: "Items" },
  { key: "sessions", label: "Sessions" },
  { key: "strategy", label: "Strategy docs" },
  { key: "qa-plans", label: "QA plans" },
  { key: "events", label: "Events" },
  { key: "packs", label: "Packs" },
];

// Per domain, so one domain's flood cannot bury the other five.
const PER_DOMAIN_LIMIT = 6;
// Domains with no keyword filter server-side are matched over a bounded
// window of their own catalogue. The cap is that window: newest-first rows,
// so what an operator is working on is what is reachable.
const SESSION_WINDOW = 300;
const EVENT_WINDOW = 300;

function rowsOf(callResult, key) {
  if (!callResult || callResult.status !== 200) return null;
  if (!callResult.envelope?.success) return null;
  const result = callResult.envelope.result || {};
  return Array.isArray(result[key]) ? result[key] : [];
}

// A failed read is reported, never rendered as "nothing matched": an empty
// list where a refusal happened is the lie this whole surface exists to
// avoid.
async function call(client, request) {
  try {
    return await client.call(request);
  } catch (error) {
    return { status: 0, envelope: { success: false, error: String(error) } };
  }
}

function matches(needle, terms) {
  return terms.some(
    (term) => String(term || "").toLowerCase().includes(needle),
  );
}

function meta(parts) {
  return parts.filter(Boolean).join(" · ");
}

// A catalogue read once per dialog session. These rosters do not change while
// somebody is typing, so re-reading them per keystroke would spend a whole
// project fan-out to get the same rows back.
function memoize(load) {
  let pending = null;
  return () => {
    if (!pending) pending = load();
    return pending;
  };
}

// Every project, because a project-scoped read has to be asked of each of
// them for scope to mean the universe.
function projectFanOut(client, projects, request) {
  return Promise.all(
    projects.map((project) => call(client, request(project))),
  );
}

// `null` from a per-project read means every project refused; a project that
// answered contributes its rows tagged with the project they belong to.
function taggedRows(results, projects, key) {
  if (results.every((result) => rowsOf(result, key) === null)) return null;
  return results.flatMap((result, index) => (rowsOf(result, key) || []).map(
    (row) => ({ project: projects[index], row }),
  ));
}

function bounded(entries) {
  return entries.slice(0, PER_DOMAIN_LIMIT);
}

// ---------- items ----------
// The only domain with a real server-side keyword search, so the whole
// backlog stays reachable however far past any browser-held roster it grows.
async function searchItems(client, query) {
  const rows = rowsOf(await call(client, {
    function: "items.search.run",
    payload: { keywords: query, limit: PER_DOMAIN_LIMIT },
  }), "matches");
  if (rows === null) return null;
  return rows.map((row) => {
    // `items.search.run` projects the public ref as `id`; it carries no
    // `public_ref` key, so a row without `id` cannot be linked at all.
    const ref = String(row.id || "");
    const href = itemDrillInHref({ projectId: row.project_id, publicRef: ref });
    if (!href) return null;
    return {
      href,
      label: String(row.title || ref),
      meta: meta([ref, row.project, row.status]),
    };
  }).filter(Boolean);
}

// ---------- sessions ----------
async function searchSessions(client, query, needle, sessionWindow) {
  const [windowRows, exactResult] = await Promise.all([
    sessionWindow(),
    // A session id typed in full is read by id as well, so it stays findable
    // however far outside the recency window it has fallen.
    call(client, { function: "sessions.list", payload: { session_id: query } }),
  ]);
  const exactRows = rowsOf(exactResult, "rows") || [];
  if (windowRows === null && !exactRows.length) return null;
  const seen = new Set();
  const entries = [];
  for (const row of [...exactRows, ...(windowRows || [])]) {
    const sessionId = String(row.session_id || "");
    if (!sessionId || seen.has(sessionId)) continue;
    const exact = sessionId === query;
    if (!exact && !matches(needle, [
      sessionId, row.current_item, row.current_item_title, row.actor_label,
      row.executor, row.model, row.requested_model, row.project,
      row.execution_lane,
    ])) continue;
    seen.add(sessionId);
    entries.push({
      href: buildUniverseRoute(
        "sessions", row.project_id ? String(row.project_id) : null, sessionId,
      ),
      label: sessionId,
      meta: meta([
        row.project, row.current_item, row.current_item_title, row.actor_label,
      ]),
    });
    if (entries.length >= PER_DOMAIN_LIMIT) break;
  }
  return entries;
}

// ---------- strategy docs ----------
async function searchStrategyDocs(needle, catalogue) {
  const tagged = await catalogue();
  if (tagged === null) return null;
  return bounded(tagged
    .filter(({ row }) => matches(needle, [row.slug, row.title, row.summary]))
    .map(({ project, row }) => ({
      href: buildUniverseRoute("strategy", String(project.id), row.slug),
      label: String(row.title || row.slug || ""),
      meta: meta([row.slug, project.slug, row.state]),
    })));
}

// ---------- QA plans ----------
async function searchQaPlans(needle, catalogue) {
  const tagged = await catalogue();
  if (tagged === null) return null;
  return bounded(tagged
    .filter(({ row }) => matches(needle, [row.slug, row.name, row.description]))
    .map(({ project, row }) => ({
      href: buildUniverseRoute("qa-plans", String(project.id), String(row.id)),
      label: String(row.name || row.slug || row.id),
      meta: meta([row.slug, project.slug, row.last_outcome]),
    })));
}

// ---------- events ----------
// The events read filters by exact column, not by keyword, so a name typed in
// full is asked for directly and anything partial is matched over the recent
// window — the same two-read shape sessions use, for the same reason.
async function searchEvents(client, query, needle, eventWindow) {
  const [windowRows, namedResult] = await Promise.all([
    eventWindow(),
    call(client, {
      function: "events.query.run",
      payload: { event_name: query, limit: PER_DOMAIN_LIMIT },
    }),
  ]);
  const namedRows = rowsOf(namedResult, "rows") || [];
  if (windowRows === null && !namedRows.length) return null;
  const entries = [];
  const seen = new Set();
  for (const row of [...namedRows, ...(windowRows || [])]) {
    const name = String(row.event_name || "");
    if (!name || seen.has(name)) continue;
    if (!matches(needle, [name, row.session_id, row.item_ref])) continue;
    seen.add(name);
    entries.push({
      href: buildUniverseRoute(
        "events", row.project_id ? String(row.project_id) : null,
      ),
      label: name,
      meta: meta([row.created_at, row.source_type, row.severity]),
    });
    if (entries.length >= PER_DOMAIN_LIMIT) break;
  }
  return entries;
}

// ---------- packs ----------
async function searchPacks(needle, catalogue) {
  const tagged = await catalogue();
  if (tagged === null) return null;
  const seen = new Set();
  const entries = [];
  for (const { project, row } of tagged) {
    const slug = String(row.slug || "");
    if (!slug || seen.has(slug)) continue;
    if (!matches(needle, [slug, row.name, row.description])) continue;
    seen.add(slug);
    entries.push({
      // Packs has no drill-in of its own; the result still names the project
      // whose installation matched.
      href: buildUniverseRoute("packs", null),
      label: String(row.name || slug),
      meta: meta([
        slug, project.slug,
        row.installed_version ? `installed ${row.installed_version}` : null,
      ]),
    });
    if (entries.length >= PER_DOMAIN_LIMIT) break;
  }
  return entries;
}

// One search session: the catalogues are read once and reused, so the second
// query costs the keyword reads alone rather than another universe-wide
// fan-out.
export function createUniverseSearch(client) {
  const projects = memoize(async () => rowsOf(
    await call(client, { function: "projects.list", payload: {} }), "rows",
  ) || []);
  const perProject = (key, request) => memoize(async () => {
    const roster = await projects();
    return taggedRows(
      await projectFanOut(client, roster, request), roster, key,
    );
  });
  const catalogues = {
    packs: perProject("packs", (project) => ({
      function: "packs.list", payload: { project: String(project.id) },
    })),
    qaPlans: perProject("rows", (project) => ({
      function: "qa.plan.list", payload: { project: String(project.id) },
    })),
    strategy: perProject("docs", (project) => ({
      function: "strategy.doc.list",
      payload: {},
      target: { kind: "global", project_id: String(project.id) },
    })),
  };
  const sessionWindow = memoize(async () => rowsOf(await call(client, {
    function: "sessions.list", payload: { limit: SESSION_WINDOW },
  }), "rows"));
  const eventWindow = memoize(async () => rowsOf(await call(client, {
    function: "events.query.run", payload: { limit: EVENT_WINDOW },
  }), "rows"));

  // Each domain reports the moment it has an answer. Waiting for all six
  // would hold every result hostage to the slowest read, which on a real
  // universe is seconds of a blank panel.
  function run(query, onDomain) {
    const needle = query.toLowerCase();
    const answers = [
      searchItems(client, query),
      searchSessions(client, query, needle, sessionWindow),
      searchStrategyDocs(needle, catalogues.strategy),
      searchQaPlans(needle, catalogues.qaPlans),
      searchEvents(client, query, needle, eventWindow),
      searchPacks(needle, catalogues.packs),
    ];
    return Promise.all(answers.map((answer, index) => answer.then(
      (entries) => onDomain(SEARCH_DOMAINS[index], entries),
      () => onDomain(SEARCH_DOMAINS[index], null),
    )));
  }
  // Start the catalogue reads before the first keystroke needs them.
  run.warm = () => {
    for (const catalogue of Object.values(catalogues)) catalogue();
    sessionWindow();
    eventWindow();
  };
  return run;
}
