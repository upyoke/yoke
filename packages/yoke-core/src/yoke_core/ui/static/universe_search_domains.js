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

// The chips the empty state shows, in the order it shows them. The order is
// the order results appear in: what an operator is most often looking for
// first.
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
// recent window. The cap is that window: newest-first rows, so what an
// operator is working on today is what is reachable.
const RECENT_WINDOW = 500;
const EVENT_WINDOW = 400;

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

function joinMeta(parts) {
  return parts.filter(Boolean).join(" · ");
}

// ---------- items ----------
// The only domain with a real server-side keyword search, so the whole
// backlog stays reachable however far past any browser-held roster it grows.
async function searchItems(client, query) {
  const result = await call(client, {
    function: "items.search.run",
    payload: { keywords: query, limit: PER_DOMAIN_LIMIT },
  });
  const rows = rowsOf(result, "matches");
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
      meta: joinMeta([ref, row.project, row.status]),
    };
  }).filter(Boolean);
}

// ---------- sessions ----------
async function searchSessions(client, query, needle) {
  const [windowResult, exactResult] = await Promise.all([
    call(client, {
      function: "sessions.list", payload: { limit: RECENT_WINDOW },
    }),
    // A session id typed in full is read by id as well, so it stays findable
    // however far outside the recency window it has fallen.
    call(client, { function: "sessions.list", payload: { session_id: query } }),
  ]);
  const windowRows = rowsOf(windowResult, "rows");
  const exactRows = rowsOf(exactResult, "rows") || [];
  if (windowRows === null && !exactRows.length) return null;
  const seen = new Set();
  const entries = [];
  for (const row of [...exactRows, ...(windowRows || [])]) {
    const sessionId = String(row.session_id || "");
    if (!sessionId || seen.has(sessionId)) continue;
    const terms = [
      sessionId, row.current_item, row.current_item_title, row.actor_label,
      row.executor, row.model, row.requested_model, row.project,
      row.execution_lane,
    ];
    if (!exactRows.includes(row) && !matches(needle, terms)) continue;
    seen.add(sessionId);
    entries.push({
      href: buildUniverseRoute(
        "sessions", row.project_id ? String(row.project_id) : null, sessionId,
      ),
      label: sessionId,
      meta: joinMeta([
        row.project, row.current_item, row.current_item_title, row.actor_label,
      ]),
    });
    if (entries.length >= PER_DOMAIN_LIMIT) break;
  }
  return entries;
}

// ---------- strategy docs ----------
async function searchStrategyDocs(client, needle, projects) {
  const results = await Promise.all(projects.map((project) => call(client, {
    function: "strategy.doc.list",
    payload: {},
    target: { kind: "global", project_id: String(project.id) },
  })));
  if (results.every((result) => rowsOf(result, "docs") === null)) return null;
  const entries = [];
  for (const [index, result] of results.entries()) {
    const project = projects[index];
    for (const doc of rowsOf(result, "docs") || []) {
      if (!matches(needle, [doc.slug, doc.title, doc.summary])) continue;
      entries.push({
        href: buildUniverseRoute("strategy", String(project.id), doc.slug),
        label: String(doc.title || doc.slug || ""),
        meta: joinMeta([doc.slug, project.slug, doc.state]),
      });
      if (entries.length >= PER_DOMAIN_LIMIT) return entries;
    }
  }
  return entries;
}

// ---------- QA plans ----------
async function searchQaPlans(client, needle, projects) {
  const results = await Promise.all(projects.map((project) => call(client, {
    function: "qa.plan.list", payload: { project: String(project.id) },
  })));
  if (results.every((result) => rowsOf(result, "rows") === null)) return null;
  const entries = [];
  for (const [index, result] of results.entries()) {
    const project = projects[index];
    for (const plan of rowsOf(result, "rows") || []) {
      if (!matches(needle, [plan.slug, plan.name, plan.description])) continue;
      entries.push({
        href: buildUniverseRoute(
          "qa-plans", String(project.id), String(plan.id),
        ),
        label: String(plan.name || plan.slug || plan.id),
        meta: joinMeta([plan.slug, project.slug, plan.last_outcome]),
      });
      if (entries.length >= PER_DOMAIN_LIMIT) return entries;
    }
  }
  return entries;
}

// ---------- events ----------
// The events read filters by exact column, not by keyword, so a name typed in
// full is asked for directly and anything partial is matched over the recent
// window — the same two-read shape sessions use, for the same reason.
async function searchEvents(client, query, needle) {
  const [windowResult, namedResult] = await Promise.all([
    call(client, {
      function: "events.query.run", payload: { limit: EVENT_WINDOW },
    }),
    call(client, {
      function: "events.query.run",
      payload: { event_name: query, limit: PER_DOMAIN_LIMIT },
    }),
  ]);
  const windowRows = rowsOf(windowResult, "rows");
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
      meta: joinMeta([row.created_at, row.source_type, row.severity]),
    });
    if (entries.length >= PER_DOMAIN_LIMIT) break;
  }
  return entries;
}

// ---------- packs ----------
async function searchPacks(client, needle, projects) {
  const results = await Promise.all(projects.map((project) => call(client, {
    function: "packs.list", payload: { project: String(project.id) },
  })));
  if (results.every((result) => rowsOf(result, "packs") === null)) return null;
  const entries = [];
  const seen = new Set();
  for (const [index, result] of results.entries()) {
    const project = projects[index];
    for (const pack of rowsOf(result, "packs") || []) {
      const slug = String(pack.slug || "");
      if (!slug || seen.has(slug)) continue;
      if (!matches(needle, [slug, pack.name, pack.description])) continue;
      seen.add(slug);
      entries.push({
        href: buildUniverseRoute("packs", null),
        label: String(pack.name || slug),
        meta: joinMeta([
          slug, project.slug,
          pack.installed_version ? `installed ${pack.installed_version}` : null,
        ]),
      });
      if (entries.length >= PER_DOMAIN_LIMIT) return entries;
    }
  }
  return entries;
}

// The universe's projects, read once per dialog and reused: a project-scoped
// read has to be asked of each of them, and the list does not change while
// somebody is typing.
export function createProjectRoster(client) {
  let pending = null;
  return () => {
    if (!pending) {
      pending = call(client, { function: "projects.list", payload: {} })
        .then((result) => rowsOf(result, "rows") || rowsOf(result, "projects"));
    }
    return pending;
  };
}

// Every domain, in parallel, reported per domain. A domain that refused is
// named in `unavailable` rather than contributing an empty group, so a
// permission or transport failure reads as a failure.
export async function searchUniverse(client, query, projects) {
  const needle = query.toLowerCase();
  const roster = projects || [];
  const settled = await Promise.all([
    searchItems(client, query),
    searchSessions(client, query, needle),
    searchStrategyDocs(client, needle, roster),
    searchQaPlans(client, needle, roster),
    searchEvents(client, query, needle),
    searchPacks(client, needle, roster),
  ]);
  const groups = [];
  const unavailable = [];
  for (const [index, entries] of settled.entries()) {
    const domain = SEARCH_DOMAINS[index];
    if (entries === null) unavailable.push(domain.label);
    else if (entries.length) groups.push({ ...domain, entries });
  }
  return { groups, unavailable };
}
