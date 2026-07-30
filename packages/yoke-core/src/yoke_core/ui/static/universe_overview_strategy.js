import { buildUniverseRoute } from "./universe_navigation.js";
import {
  el,
  scopeBuckets,
  settledScopedCalls,
} from "./universe_view_support.js";
import { holdScopedSection } from "./universe_held_reads.js";
import { ghostWhenInactive } from "./universe_views_overview_activation.js";
import { relativeAge } from "./universe_time.js";
import { STRATEGY_BADGE_LIMIT } from "./universe_overview_primitives.js";

export async function loadVitals(context, masthead, getScope) {
  const buckets = scopeBuckets("all", context.projects(), true);
  const { callResults } = await settledScopedCalls(
    context,
    buckets.map((bucket) => ({
      functionId: "overview.vitals.get",
      payload: {
        days: 120,
        ...(bucket === null ? {} : { project: bucket }),
      },
    })),
  );
  if (!context.isMounted()) return { timelines: [], paint: () => {} };
  // Hold each project's vitals; paint sums the selected subset so a scope
  // change re-aggregates the masthead from held data with no refetch. The
  // server aggregate stays untouched — the client does the projection.
  const perProject = buckets.map((bucket, index) => ({
    project: String(bucket),
    ok: !!(callResults[index] && callResults[index].status === 200
      && callResults[index].envelope.success),
    result: (callResults[index] && callResults[index].envelope.result) || {},
  }));
  const timelines = perProject.flatMap(
    (entry) => entry.result.strategy_timeline || [],
  );
  const paint = () => {
    if (!context.isMounted()) return;
    const scope = getScope();
    const wanted = scope === "all" ? null : new Set(scope.map(String));
    const chosen = wanted
      ? perProject.filter((entry) => wanted.has(entry.project))
      : perProject;
    // Unavailability reflects only the in-scope projects: a failed read for a
    // project the current scope excludes must not blank the masthead.
    if (chosen.some((entry) => !entry.ok)) {
      masthead.setUnavailable();
      return;
    }
    const stateCounts = {};
    const momentumByDay = new Map();
    let days = 120;
    for (const entry of chosen) {
      const result = entry.result;
      days = Math.max(days, Number(result.days) || 0);
      for (const [key, value] of Object.entries(result.state_counts || {})) {
        stateCounts[key] = (stateCounts[key] || 0) + (Number(value) || 0);
      }
      for (const row of result.momentum || []) {
        const combined = momentumByDay.get(row.day) || {
          day: row.day, activity: 0, code: 0, issues: 0, strategy: 0,
        };
        for (const key of ["activity", "code", "issues", "strategy"]) {
          combined[key] += Number(row[key]) || 0;
        }
        momentumByDay.set(row.day, combined);
      }
    }
    masthead.setVitals({
      stateCounts,
      days,
      momentum: [...momentumByDay.values()].sort(
        (left, right) => String(left.day).localeCompare(String(right.day)),
      ),
    });
  };
  paint();
  return { timelines, paint };
}

// The strategy corpus, project-scoped through the target the same way the full
// Strategy screen reads it: "all" fans out one call per roster project.
export async function loadStrategy(
  context,
  panel,
  getScope,
  activationFacts,
  timelinesRead,
) {
  const timelines = await timelinesRead;
  if (!context.isMounted()) return null;
  const projects = context.projects();
  const buckets = scopeBuckets("all", projects, true);
  const projectById = new Map(projects.map((row) => [String(row.id), row]));
  const timelineByProject = new Map(
    (timelines || []).flatMap((timeline) => [
      [String(timeline.project_id || ""), timeline],
      [String(timeline.project || ""), timeline],
    ]),
  );
  return holdScopedSection(
    context, panel, buckets,
    buckets.map((bucket) => ({
      functionId: "strategy.doc.list",
      payload: {},
      target: { kind: "global", project_id: String(bucket) },
    })),
    getScope,
    (body, callResults, scope, selectedBuckets) => {
      const documentNode = body.ownerDocument;
      const docs = callResults.flatMap((callResult, index) => (
        ((callResult.envelope.result || {}).docs || []).map((doc) => ({
          ...doc,
          project_id: doc.project_id || selectedBuckets[index],
          project: (
            projectById.get(String(selectedBuckets[index]))?.slug
              || selectedBuckets[index]
          ),
        }))
      ));
      if (!docs.length) {
        ghostWhenInactive(context, activationFacts, "strategy", panel);
      }

      // The corpus and vitals reads meet here: docs supply the badges while
      // vitals carries the same landed-work, queue, and VISION facts as the
      // terminal board's timeline.
      panel.setCount(null);
      const zen = el(documentNode, "div", "overview-zen");
      const visibleProjects = projects.filter((project) =>
        scope === "all" || scope.includes(String(project.id)));
      const timelineProjects = visibleProjects.length ? visibleProjects : [{
        id: "scope", slug: "scope", emoji: "◇",
      }];
      for (const project of timelineProjects) {
        const row = el(documentNode, "div", "overview-zen-row");
        const projectNode = el(
          documentNode,
          "span",
          "overview-zen-project",
          project.emoji || "◇",
        );
        projectNode.title = project.slug || project.name || "project";
        row.appendChild(projectNode);
        const track = el(documentNode, "div", "overview-zen-track");
        const timeline = timelineByProject.get(String(project.id))
          || timelineByProject.get(String(project.slug || ""));
        track.setAttribute(
          "aria-label",
          `${project.slug || project.name || "Project"} strategy timeline`,
        );
        const past = el(documentNode, "div", "overview-zen-past");
        for (const position of timeline?.done_positions || []) {
          const dot = el(documentNode, "i", "overview-zen-dot");
          dot.style.left =
            `${Math.max(0, Math.min(100, Number(position) || 0))}%`;
          past.appendChild(dot);
        }
        for (const label of timeline?.labels || []) {
          const marker = el(
            documentNode,
            "em",
            "overview-zen-label",
            label.label || "",
          );
          marker.style.left =
            `${Math.max(0, Math.min(100, Number(label.position) || 0))}%`;
          past.appendChild(marker);
        }
        if (!(timeline?.done_positions || []).length) {
          past.appendChild(el(
            documentNode,
            "span",
            "overview-zen-zone-label",
            "no landed work yet",
          ));
        }
        track.appendChild(past);
        track.appendChild(el(documentNode, "span", "overview-zen-now", "🔸"));
        if (Number(timeline?.queued_count) > 0) {
          const queued = el(documentNode, "div", "overview-zen-queued");
          queued.appendChild(el(
            documentNode,
            "span",
            "overview-zen-zone-label",
            `${Number(timeline.queued_count)} queued`,
          ));
          track.appendChild(queued);
        }
        for (const zone of timeline?.vision_zones || []) {
          const vision = el(documentNode, "div", "overview-zen-vision");
          vision.setAttribute("data-zone", zone.key || "vision");
          vision.appendChild(el(
            documentNode,
            "i",
            "overview-zen-dot overview-zen-vision-dot",
          ));
          vision.appendChild(el(
            documentNode,
            "span",
            "overview-zen-zone-label",
            zone.label || "VISION",
          ));
          track.appendChild(vision);
        }
        row.appendChild(track);
        zen.appendChild(row);
      }
      body.appendChild(zen);

      const docStrip = el(documentNode, "div", "overview-doc-strip");
      const sorted = [...docs].sort((left, right) =>
        String(right.updated_at || "").localeCompare(
          String(left.updated_at || ""),
        ));
      for (const doc of sorted.slice(0, STRATEGY_BADGE_LIMIT)) {
        const badge = el(documentNode, "a", "overview-doc-badge");
        badge.href = buildUniverseRoute(
          "strategy", String(doc.project_id), doc.slug,
        );
        badge.title = [
          doc.title,
          (Array.isArray(scope) && scope.length === 1) ? null : doc.project,
        ].filter(Boolean).join(" · ");
        badge.appendChild(el(
          documentNode, "strong", null, doc.slug || "Strategy",
        ));
        badge.appendChild(el(documentNode, "span", null, " · "));
        badge.appendChild(el(
          documentNode,
          "span",
          "overview-doc-age",
          relativeAge(doc.updated_at),
        ));
        docStrip.appendChild(badge);
      }
      if (!docs.length) {
        docStrip.appendChild(el(
          documentNode, "span", "empty", "no strategy docs yet",
        ));
      }
      const claimFactAvailable = docs.some((doc) =>
        Object.prototype.hasOwnProperty.call(doc, "execution_state"));
      const claimed = docs.filter(
        (doc) => String(doc.execution_state).toLowerCase() === "claimed",
      ).length;
      docStrip.appendChild(el(
        documentNode,
        "span",
        "overview-doc-total",
        `${docs.length} doc${docs.length === 1 ? "" : "s"}` +
          (claimFactAvailable ? ` · ${claimed} claimed` : ""),
      ));
      body.appendChild(docStrip);
    },
  );
}
