import {
  el,
  loadScopedSection,
  renderTable,
  scopeBuckets,
  section,
} from "./universe_view_support.js";

// The stat-tile row above a report: one number that matters per tile. A
// count the journal could not preserve renders as an em dash, never a
// made-up zero.
function statRow(documentNode, stats) {
  const row = el(documentNode, "div", "stat-row");
  for (const [label, value] of stats) {
    const tile = el(documentNode, "div", "stat");
    tile.appendChild(el(
      documentNode, "div", "n",
      value === null || value === undefined ? "—" : String(value),
    ));
    tile.appendChild(el(documentNode, "div", "l", label));
    row.appendChild(tile);
  }
  return row;
}

// One doctor report body: fact line, stat tiles, then the checks table.
// The three degraded states render honestly — never ran (with the command
// to run, as copyable text), truncated in the journal, or a plain report.
function renderDoctorReport(body, result) {
  const documentNode = body.ownerDocument;
  if (result.never_run) {
    body.appendChild(el(
      documentNode, "p", "empty", "doctor has not run yet",
    ));
    const hint = el(documentNode, "p", "fact-line", "run it with ");
    hint.appendChild(el(
      documentNode, "code", null, "yoke doctor run --quick",
    ));
    body.appendChild(hint);
    return;
  }
  const facts = [`last run ${result.ran_at}`];
  if (result.scope) facts.push(`scope ${result.scope}`);
  body.appendChild(el(documentNode, "p", "fact-line", facts.join(" · ")));
  body.appendChild(statRow(documentNode, [
    ["total", result.total],
    ["passing", result.pass_count],
    ["warnings", result.warn_count],
    ["failing", result.fail_count],
  ]));
  if (result.truncated) {
    body.appendChild(el(
      documentNode, "p", "empty",
      "detail truncated in the journal; run doctor again for a fresh report",
    ));
    return;
  }
  renderTable(body, result.results || [], [
    { label: "check", value: (row) => row.hc, mono: true },
    { label: "name", value: (row) => row.name },
    { label: "result", value: (row) => row.severity, pill: true },
  ], "no checks recorded");
}

// The last completed doctor run — doctor findings persist nowhere but the
// events journal, so this reads the journal, not a table of runs. "all"
// serves the newest run regardless of project in one call; a project set
// asks per member and labels each report with the project it answers for.
export function renderDoctorView(context, main, scope) {
  const panel = section(context.document, "Doctor");
  main.replaceChildren(panel);
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
      callResults.forEach((callResult, index) => {
        if (buckets.length > 1) {
          body.appendChild(el(
            body.ownerDocument, "h3", "report-heading",
            nameById.get(buckets[index]) || String(buckets[index]),
          ));
        }
        renderDoctorReport(body, callResult.envelope.result || {});
      });
    },
  );
}
