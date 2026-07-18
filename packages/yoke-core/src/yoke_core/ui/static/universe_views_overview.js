// The Overview view: the universe at a glance, as the terminal BOARD.md answers
// it — direction, what can run, who is working, what is shipping, what just
// happened, whether the floor holds. It renders no facts of its own. Every
// section replays the same read the full screen behind it runs, shows the first
// few rows, and links out — you triage here and act there. The board's ASCII
// art and monospace tables stay in the terminal; the web takes the data, not
// the picture, so nothing here is invented and no number is fabricated: a read
// that serves no honest total shows none, and a tile whose read has not
// resolved (or failed) holds an em dash rather than a made-up zero.

import { buildUniverseRoute, serializeScope } from "./universe_navigation.js";
import {
  el,
  loadScopedSection,
  mergedRows,
  renderTable,
  scopeBuckets,
  section,
  whoColumn,
  withProjectColumn,
} from "./universe_view_support.js";

// How many rows a summary section shows before its "Open …" link takes over.
const SUMMARY_ROW_LIMIT = 5;

// The prototype turns the board's section headings into a compact map of the
// page. Keep the labels and order beside the renderer so the jump strip cannot
// drift from the summaries it navigates.
const OVERVIEW_SECTIONS = [
  ["strategy", "❖", "Strategy", "direction and recent strategy"],
  ["frontier", "⚡", "Frontier", "what can run now, and why"],
  ["sessions", "◈", "Sessions", "who is working"],
  ["delivery", "⬈", "Delivery", "what is shipping"],
  ["events", "≋", "Events", "the pulse · newest first"],
  ["doctor", "♥", "Doctor", "the floor · current health"],
];

// One stat tile that fills in when its read resolves. Until then — and if the
// read fails — it holds an em dash, never a zero that reads as a real count.
function statTile(documentNode, label) {
  const tile = el(documentNode, "div", "stat");
  const number = el(documentNode, "div", "n", "—");
  tile.appendChild(number);
  tile.appendChild(el(documentNode, "div", "l", label));
  return {
    node: tile,
    set: (value) => {
      number.textContent =
        value === null || value === undefined ? "—" : String(value);
    },
  };
}

// The link out of a summary and into the full screen, carrying the scope the
// Overview holds so the destination opens on the same projects.
function openLink(documentNode, view, scope, label) {
  const link = el(documentNode, "a", "overview-open", `Open ${label} →`);
  link.href = buildUniverseRoute(view, serializeScope(scope));
  return link;
}

// A titled summary panel that links to its full screen. The link is a sibling
// of the body, so a section load replacing the body leaves it in place.
function summaryPanel(documentNode, title, view, scope, label) {
  const panel = section(documentNode, title);
  panel.classList.add("overview-section");
  panel.setAttribute("id", `overview-${view}`);
  const sectionDefinition = OVERVIEW_SECTIONS.find(([id]) => id === view);
  if (sectionDefinition) {
    panel.children[0].children[0].textContent =
      `${sectionDefinition[1]} ${title}`;
    panel.children[0].appendChild(el(
      documentNode, "span", "overview-section-detail", sectionDefinition[3],
    ));
  }
  panel.appendChild(openLink(documentNode, view, scope, label));
  return panel;
}

// The prototype gives the first live signals one shared masthead instead of
// leaving four unrelated tiles floating between navigation and content. This
// keeps the same honest values while restoring the page's visual hierarchy.
function signalMasthead(documentNode, statRow) {
  const masthead = el(documentNode, "section", "overview-masthead");
  const heading = el(documentNode, "div", "overview-masthead-heading");
  heading.appendChild(el(documentNode, "strong", null, "Live signals"));
  heading.appendChild(el(
    documentNode, "span", null,
    "what can run, who is working, and whether the floor holds",
  ));
  masthead.appendChild(heading);
  masthead.appendChild(statRow);
  return masthead;
}

// A keyboard-accessible section map that stays available while the long
// Overview scrolls. Buttons scroll within this view; the panel-foot links keep
// owning navigation into the full destination screens.
function sectionJumps(documentNode, panels) {
  const nav = el(documentNode, "nav", "overview-jumps");
  nav.setAttribute("aria-label", "Overview sections");
  for (const [view, icon, label] of OVERVIEW_SECTIONS) {
    const panel = panels.get(view);
    const button = el(
      documentNode, "button", "overview-jump", `${icon} ${label}`,
    );
    button.type = "button";
    button.setAttribute("aria-controls", `overview-${view}`);
    button.addEventListener("click", () => {
      if (typeof panel.scrollIntoView === "function") {
        panel.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
    nav.appendChild(button);
  }
  return nav;
}

// The strategy corpus, project-scoped through the target the same way the full
// Strategy screen reads it: "all" fans out one call per roster project.
function loadStrategy(context, panel, scope) {
  const projects = context.projects();
  const buckets = scopeBuckets(scope, projects, true);
  const slugById = new Map(
    projects.map((row) => [String(row.id), row.slug || String(row.id)]),
  );
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "strategy.doc.list",
      payload: {},
      target: { kind: "global", project_id: String(bucket) },
    })),
    (body, callResults) => {
      const docs = callResults.flatMap((callResult, index) => (
        ((callResult.envelope.result || {}).docs || []).map((doc) => ({
          ...doc, project: slugById.get(buckets[index]) || buckets[index],
        }))
      ));
      panel.setCount(docs.length);
      renderTable(body, docs.slice(0, SUMMARY_ROW_LIMIT), withProjectColumn([
        { label: "doc", value: (doc) => doc.slug, mono: true },
        { label: "title", value: (doc) => doc.title },
        { label: "last write", value: (doc) => doc.updated_at },
      ], scope, (doc) => doc.project), "no strategy docs yet");
    },
  );
}

// What can run now and why, plus how much is blocked. One read serves the two
// headline tiles and the ready peek; the blocked count is a fact the tile
// carries, and the full split lives on Frontier.
function loadFrontier(context, panel, scope, tiles) {
  const buckets = scopeBuckets(scope, context.projects(), false);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "frontier.list",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const ready = mergedRows(callResults, (result) => result.ready_rows);
      const blocked = mergedRows(callResults, (result) => result.blocked_rows);
      tiles.ready.set(ready.length);
      tiles.blocked.set(blocked.length);
      renderTable(body, ready.slice(0, SUMMARY_ROW_LIMIT), withProjectColumn([
        { label: "item", value: (row) => row.item_id },
        { label: "next step", value: (row) => row.next_step },
        { label: "run", value: (row) => row.run_command, code: true },
        { label: "why ready", value: (row) => row.why_ready },
      ], scope, (row) => row.project), "nothing ready to run");
    },
  );
}

// Each live session, the terminal board's own columns — who runs it (the
// mode-shaped actor/member column), how alive it is, its lane and mode, and
// what it holds.
function loadSessions(context, panel, scope, tiles) {
  const buckets = scopeBuckets(scope, context.projects(), false);
  const who = whoColumn(context.capabilities);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "sessions.list",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows);
      panel.setCount(rows.length);
      tiles.sessions.set(rows.length);
      renderTable(body, rows.slice(0, SUMMARY_ROW_LIMIT), withProjectColumn([
        { label: "session", value: (row) => row.session_id },
        { label: who.label, value: who.value },
        { label: "liveness", value: (row) => row.liveness, pill: true },
        { label: "lane", value: (row) => row.execution_lane },
        { label: "mode", value: (row) => row.mode },
        { label: "item", value: (row) => row.current_item },
      ], scope, (row) => row.project), "no live sessions");
    },
  );
}

// What is shipping. The engine bounds run history and returns the newest
// receipts first, so the overview keeps that order before taking its summary.
function loadDelivery(context, panel, scope) {
  const buckets = scopeBuckets(scope, context.projects(), false);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "deployment_runs.list",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows);
      panel.setCount(rows.length);
      renderTable(body, rows.slice(0, SUMMARY_ROW_LIMIT), withProjectColumn([
        { label: "run", value: (row) => row.id, mono: true },
        { label: "flow", value: (row) => row.flow },
        { label: "target", value: (row) => row.target_env },
        { label: "status", value: (row) => row.status, pill: true },
        { label: "created", value: (row) => row.created_at },
      ], scope, (row) => row.project), "no runs yet");
      renderLatestEnvironments(body.ownerDocument, body, rows);
    },
  );
}

// A concise answer to the question the run history alone makes surprisingly
// hard: what is the newest receipt for each environment? This mirrors the
// prototype's environment line and prevents an older red run from looking
// like the current state when a newer green run already superseded it.
function renderLatestEnvironments(documentNode, body, rows) {
  const latest = new Map();
  const sorted = [...rows].sort((left, right) =>
    String(right.created_at || "").localeCompare(String(left.created_at || "")),
  );
  for (const row of sorted) {
    const target = String(row.target_env || "").trim();
    if (!target) continue;
    const key = `${row.project || ""}:${target}`;
    if (!latest.has(key)) latest.set(key, row);
  }
  if (!latest.size) return;
  const line = el(documentNode, "div", "overview-environments");
  line.appendChild(el(documentNode, "strong", null, "Latest by environment"));
  for (const row of [...latest.values()].slice(0, 6)) {
    const label = [row.project, row.target_env].filter(Boolean).join(" · ");
    const chip = el(
      documentNode, "span", "overview-environment",
      `${label} · ${row.status || "unknown"} · ` +
      `${row.created_at || "time unknown"}`,
    );
    chip.setAttribute("data-status", String(row.status || "unknown"));
    line.appendChild(chip);
  }
  body.appendChild(line);
}

// The pulse: the most recent state changes. The events read is project-scoped
// and refuses a projectless call, so "all" fans out per roster project. Like
// the full Events screen, this attests no total and so shows no header count.
function loadEvents(context, panel, scope) {
  const buckets = scopeBuckets(scope, context.projects(), true);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "events.query.run",
      payload: { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows);
      renderTable(body, rows.slice(0, SUMMARY_ROW_LIMIT + 1), withProjectColumn([
        { label: "when", value: (row) => row.created_at },
        { label: "event", value: (row) => row.event_name },
        { label: "source", value: (row) => row.actor_id || row.service },
      ], scope, (row) => row.project), "no events yet");
    },
  );
}

// Whether the floor holds. Doctor findings live only in the events journal, so
// this reads the last run per bucket, aggregates the four counts for the tile
// and fact line, and lists only what is not passing — enumerating the passing
// checks is the full Doctor screen's job.
function loadDoctor(context, panel, scope, tiles) {
  const projects = context.projects();
  const buckets = scopeBuckets(scope, projects, false);
  const nameById = new Map(projects.map(
    (row) => [String(row.id), row.name || row.slug || String(row.id)],
  ));
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "doctor.last_run.get",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const documentNode = body.ownerDocument;
      const reports = callResults.map(
        (callResult) => callResult.envelope.result || {},
      );
      const ran = reports.filter((report) => !report.never_run);
      const sum = (key) => ran.reduce(
        (total, report) => total + (Number(report[key]) || 0), 0,
      );
      // Every report is never-run → the tile has no honest number to show.
      const passing = ran.length ? sum("pass_count") : null;
      tiles.checks.set(passing);
      if (!ran.length) {
        body.appendChild(el(documentNode, "p", "empty", "doctor has not run yet"));
        return;
      }
      body.appendChild(el(
        documentNode, "p", "fact-line",
        `${sum("total")} checks · ${sum("pass_count")} passing · ` +
        `${sum("warn_count")} warnings · ${sum("fail_count")} failing`,
      ));
      // Only what is not passing earns a row. A truncated report cannot be
      // read row by row, so it contributes its counts above but no rows here.
      const notPassing = reports.flatMap((report, index) => (
        report.truncated ? [] : (report.results || [])
          .filter((row) => String(row.severity).toLowerCase() !== "pass")
          .map((row) => ({
            ...row,
            project: nameById.get(buckets[index]) || buckets[index],
          }))
      ));
      renderTable(body, notPassing.slice(0, SUMMARY_ROW_LIMIT), withProjectColumn([
        { label: "check", value: (row) => row.hc, mono: true },
        { label: "name", value: (row) => row.name },
        { label: "result", value: (row) => row.severity, pill: true },
      ], scope, (row) => row.project), "all checks passing");
    },
  );
}

// The one entry point the shell calls. It replaces the view host with a stat
// row and the six summary panels, then kicks off each section's read; the
// panels fill independently as their reads settle.
export function renderOverviewView(context, main, scope) {
  const documentNode = context.document;
  const tiles = {
    ready: statTile(documentNode, "ready to run"),
    sessions: statTile(documentNode, "live sessions"),
    blocked: statTile(documentNode, "blocked"),
    checks: statTile(documentNode, "checks passing"),
  };
  const statRow = el(documentNode, "div", "stat-row");
  for (const tile of [tiles.ready, tiles.sessions, tiles.blocked, tiles.checks]) {
    statRow.appendChild(tile.node);
  }

  const strategy = summaryPanel(documentNode, "Strategy", "strategy", scope, "Strategy");
  const frontier = summaryPanel(documentNode, "Frontier", "frontier", scope, "Frontier");
  const sessions = summaryPanel(documentNode, "Sessions", "sessions", scope, "Sessions");
  const delivery = summaryPanel(documentNode, "Delivery", "delivery", scope, "Delivery");
  const events = summaryPanel(documentNode, "Events", "events", scope, "Events");
  const doctor = summaryPanel(documentNode, "Doctor", "doctor", scope, "Doctor");
  const panels = new Map([
    ["strategy", strategy], ["frontier", frontier], ["sessions", sessions],
    ["delivery", delivery], ["events", events], ["doctor", doctor],
  ]);
  const finalPair = el(documentNode, "div", "overview-pair");
  finalPair.appendChild(events);
  finalPair.appendChild(doctor);
  main.replaceChildren(
    sectionJumps(documentNode, panels), signalMasthead(documentNode, statRow),
    strategy, frontier, sessions, delivery, finalPair,
  );

  loadStrategy(context, strategy, scope);
  loadFrontier(context, frontier, scope, tiles);
  loadSessions(context, sessions, scope, tiles);
  loadDelivery(context, delivery, scope);
  loadEvents(context, events, scope);
  loadDoctor(context, doctor, scope, tiles);
}
