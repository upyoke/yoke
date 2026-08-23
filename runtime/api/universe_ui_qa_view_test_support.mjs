import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  methods,
  ok,
  planDetail,
  planRow,
} from "./universe_ui_qa_view_data_test_support.mjs";

function qaClient() {
  const requests = [];
  const activityNow = Date.now();
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") return ok({ name: "Yoke" });
      if (request.function === "projects.list") {
        return ok({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "qa.method.list") {
        return ok({ rows: [...methods].reverse() });
      }
      if (request.function === "qa.method.get") {
        return ok({
          method: {
            ...methods.find((row) => row.id === request.payload.method_id),
            plans: [{
              id: 7,
              slug: "release-readiness",
              name: "Release readiness",
              project: "yoke",
              case_keys: ["backend-suite"],
              method_is_complete_plan: false,
              outcome_summary: {
                state: "passed",
                counts: { passed: 1 },
                last_at: null,
              },
            }],
          },
        });
      }
      if (request.function === "qa.plan.list") return ok({ rows: [planRow] });
      if (request.function === "qa.plan.get") return ok({ plan: planDetail });
      if (request.function === "qa.activity.list") {
        return ok({
          summary: {
            day: new Date(activityNow).toISOString().slice(0, 10),
            total: 10,
            counts: { passed: 8, needs_review: 1, running: 1 },
          },
          rows: [
            {
              requirement_id: 32,
              run_id: 92,
              plan_id: 7,
              plan: "release-readiness",
              project: "yoke",
              case_key: "checkout-flow",
              host_baseline: null,
              method_id: "browser-check",
              method_name: "Browser check",
              outcome: "needs_review",
              evidence_count: 4,
              proof_summary: "4 screenshots",
              capture_degraded_reason: null,
              happened_at: new Date(activityNow).toISOString(),
            },
            {
              requirement_id: 33,
              run_id: 93,
              plan_id: 8,
              plan: "installer-campaign",
              project: "yoke",
              case_key: "welcome-frame",
              host_baseline: null,
              method_id: "terminal-inspection",
              method_name: "Terminal inspection",
              outcome: "passed",
              evidence_count: 1,
              proof_summary:
                "text capture + reason — image capture blocked on the host",
              capture_degraded_reason: "image capture blocked on the host",
              happened_at: new Date(
                activityNow - 60 * 60 * 1000,
              ).toISOString(),
            },
            {
              requirement_id: 35,
              run_id: 95,
              plan_id: 8,
              plan: "installer-campaign",
              project: "yoke",
              case_key: "cold-start-hosted",
              host_baseline: "fresh-host",
              method_id: "terminal-check",
              method_name: "Terminal check",
              outcome: "running",
              evidence_count: 3,
              proof_summary: "step transcript · 2 screenshots",
              capture_degraded_reason: null,
              happened_at: new Date(
                activityNow - 21 * 60 * 1000,
              ).toISOString(),
            },
            {
              requirement_id: 36,
              run_id: 96,
              plan_id: 9,
              plan: "full-verification",
              project: "yoke",
              case_key: "backend-suite",
              host_baseline: null,
              method_id: "command",
              method_name: "Command",
              outcome: "passed",
              evidence_count: 1,
              proof_summary: "exit 0 · output tail",
              capture_degraded_reason: null,
              happened_at: new Date(
                activityNow - 2 * 60 * 60 * 1000,
              ).toISOString(),
            },
            {
              requirement_id: 37,
              run_id: 97,
              plan_id: 7,
              plan: "release-readiness",
              project: "yoke",
              case_key: "checkout-flow",
              host_baseline: null,
              method_id: "browser-check",
              method_name: "Browser check",
              outcome: "passed",
              evidence_count: 1,
              proof_summary: "assertions · trace",
              capture_degraded_reason: null,
              happened_at: new Date(
                activityNow - 3 * 60 * 60 * 1000,
              ).toISOString(),
            },
            {
              requirement_id: 34,
              run_id: 94,
              plan_id: 8,
              plan: "installer-campaign",
              project: "yoke",
              case_key: "path-on-shell",
              host_baseline: "fresh-host",
              method_id: "machine-state-check",
              method_name: "Machine state check",
              outcome: "blocked_on_precondition",
              evidence_count: 0,
              proof_summary:
                "baseline fresh-host unverified — capability went error; " +
                "the case never ran",
              capture_degraded_reason: null,
              precondition_reason: "capability went error",
              happened_at: new Date(
                activityNow - 24 * 60 * 60 * 1000,
              ).toISOString(),
            },
          ],
        });
      }
      if (request.function === "qa.artifact.read") {
        return ok({
          artifact_id: 4,
          backend: "local",
          disposition: "ready",
          content_type: "text/plain",
          content_base64: "ZnVsbCBvdXRwdXQ=",
        });
      }
      if (request.function === "qa.case.waive") {
        return ok({
          requirement_id: request.target.qa_requirement_id,
          source: "operator",
          waived: true,
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

export async function mountAt(t, hash) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const client = qaClient();
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { documentNode, root, client, mounted };
}
