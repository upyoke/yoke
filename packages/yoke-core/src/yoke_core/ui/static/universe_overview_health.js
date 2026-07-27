import {
  el,
  loadScopedSection,
  mergedRows,
  scopeBuckets,
  statePill,
} from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";
import { SUMMARY_ROW_LIMIT } from "./universe_overview_primitives.js";

// The pulse: the most recent state changes. The events read is project-scoped
// and refuses a projectless call, so "all" fans out per roster project.
export function loadEvents(context, panel, scope) {
  const buckets = scopeBuckets(scope, context.projects(), true);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "events.query.run",
      payload: { project: bucket },
    })),
    (body, callResults) => {
      const documentNode = body.ownerDocument;
      const rows = mergedRows(callResults, (result) => result.rows);
      rows.sort((left, right) =>
        String(right.created_at || "").localeCompare(
          String(left.created_at || ""),
        ));
      panel.setCount(rows.length);
      if (!rows.length) {
        body.appendChild(el(documentNode, "p", "empty", "no events yet"));
        return;
      }
      for (const row of rows.slice(0, SUMMARY_ROW_LIMIT + 1)) {
        const pulse = el(documentNode, "div", "overview-pulse-row");
        pulse.appendChild(el(
          documentNode,
          "span",
          "overview-pulse-source",
          row.source_label || row.service || row.actor_id || "system",
        ));
        const content = el(documentNode, "div", "overview-pulse-content");
        content.appendChild(el(
          documentNode,
          "strong",
          "overview-pulse-event",
          row.event_name || "event",
        ));
        content.appendChild(el(
          documentNode,
          "span",
          "overview-pulse-context",
          [row.target_label, row.context_label].filter(Boolean).join(" · ") || "—",
        ));
        pulse.appendChild(content);
        pulse.appendChild(relativeTime(documentNode, row.created_at));
        body.appendChild(pulse);
      }
    },
  );
}

// Whether the floor holds. Doctor findings live only in the events journal, so
// this reads the last run per bucket, aggregates the four counts, and lists
// only what is not passing.
export function loadDoctor(context, panel, scope) {
  const projects = context.projects();
  const buckets = scopeBuckets(scope, projects, true);
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
      if (!ran.length) {
        panel.setCount("not run");
        body.appendChild(el(documentNode, "p", "empty", "doctor has not run yet"));
        return;
      }
      const warnings = sum("warn_count");
      const failures = sum("fail_count");
      panel.setCount(failures
        ? `${failures} failing${warnings ? ` · ${warnings} warnings` : ""}`
        : (warnings ? `${warnings} warnings` : "healthy"));
      const rollup = el(documentNode, "div", "overview-doctor-rollup");
      const rollupFacts = [
        [sum("total"), "checks", null],
        [sum("pass_count"), "passing", "good"],
        [warnings, "warnings", "warn"],
        [failures, "failing", "crit"],
      ];
      for (const [value, label, tone] of rollupFacts) {
        const fact = el(documentNode, "span", "overview-doctor-fact");
        if (tone) fact.setAttribute("data-tone", tone);
        fact.appendChild(el(documentNode, "strong", null, String(value)));
        fact.appendChild(el(documentNode, "span", null, label));
        rollup.appendChild(fact);
      }
      if (!warnings && !failures) {
        rollup.appendChild(el(
          documentNode,
          "span",
          "overview-doctor-summary",
          "all returned invariants passing",
        ));
      }
      body.appendChild(rollup);
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
      for (const row of notPassing.slice(0, SUMMARY_ROW_LIMIT)) {
        const finding = el(documentNode, "div", "overview-health-row");
        const severity = statePill(
          documentNode, row.severity, String(row.severity || "").toUpperCase(),
        );
        if (severity) finding.appendChild(severity);
        const identity = el(documentNode, "div", "overview-health-identity");
        identity.appendChild(el(
          documentNode, "strong", "overview-health-check", row.hc || "check",
        ));
        if (row.name) {
          identity.appendChild(el(
            documentNode, "span", "overview-health-name", row.name,
          ));
        }
        finding.appendChild(identity);
        finding.appendChild(el(
          documentNode, "span", "overview-health-project", row.project || "—",
        ));
        body.appendChild(finding);
      }
      if (!notPassing.length && (warnings || failures)) {
        body.appendChild(el(
          documentNode,
          "p",
          "overview-region-empty",
          "Finding details are unavailable from the truncated report.",
        ));
      }
    },
  );
}
