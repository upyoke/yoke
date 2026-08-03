import {
  mountUniverseApp,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

export function okEnvelope(result) {
  return { status: 200, envelope: { success: true, result } };
}

export function workflowFixture({
  id = "rally",
  name = "Rally",
  description = "Coordinate a small release train.",
  stages,
  currentVersion = 3,
  versions,
  policies,
  skillBindings,
  status = "active",
} = {}) {
  const declaredVersions = versions || (
    currentVersion === 1
      ? [{
        version: 1,
        definition_digest: `${id}-first`,
        published_at: "2026-07-20T12:00:00Z",
        published_by_actor_id: null,
      }]
      : [
        {
          version: 1,
          definition_digest: `${id}-first`,
          published_at: "2026-07-20T12:00:00Z",
          published_by_actor_id: null,
        },
        {
          version: currentVersion,
          definition_digest: `${id}-current`,
          published_at: "2026-07-25T12:00:00Z",
          published_by_actor_id: 1,
        },
      ]
  );
  return {
    id,
    name,
    description,
    source: "pack",
    status,
    current_version: currentVersion,
    published_at: "2026-07-25T12:00:00Z",
    versions: declaredVersions,
    definition: {
      stages: stages || [
        { id: "draft", label: "Drafted", gates: [] },
        {
          id: "prove",
          label: "Proving",
          gates: [{ id: "evidence_check", mode: "strict" }],
          description: "Collect the declared proof.",
        },
        { id: "ship", label: "Shipped", gates: [] },
      ],
      entry_surfaces: ["cli", "harness_skill"],
      skill_bindings: skillBindings || [{
        skill_id: "advance",
        from_stage_id: "draft",
        through_stage_id: "ship",
      }],
      policies: policies || {
        ownership: "single_item_claim",
        file_budget: "required",
        path_claims: "required",
        worktrees: "single_implementation_lane",
        parallelism: "inside_item",
        generated_children: "none",
        qa: "project_transition_defaults",
        approvals: "definition_transitions",
        delivery: "release_stage",
        item_posture_allowlist: ["verification"],
      },
    },
  };
}

function definitionFixture(workflows = [workflowFixture()]) {
  return {
    family: "work-items",
    workflows,
    gate_catalog: [{
      id: "evidence_check",
      name: "Evidence check",
      source_kind: "status_gate",
      availability: "live",
      description: "The declared proof must exist.",
    }],
    flows: [],
  };
}

export function workflowsClient(workflows) {
  const requests = [];
  const rows = structuredClone(workflows || [workflowFixture()]);
  for (const workflow of rows) {
    for (const version of workflow.versions || []) {
      version.definition = structuredClone(
        version.definition || workflow.definition,
      );
    }
  }
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "workflows.definition.get") {
        return okEnvelope(definitionFixture(structuredClone(rows)));
      }
      if (request.function === "workflows.mechanics.get") {
        return okEnvelope({
          testing_defaults: [],
          delivery_defaults: [],
          approvers: [],
        });
      }
      if (request.function === "qa.plan.list") {
        return okEnvelope({ rows: [] });
      }
      if (request.function === "workflows.version.get") {
        const workflow = rows.find(
          (row) => row.id === request.payload.workflow_id,
        );
        const version = workflow.versions.find(
          (row) => Number(row.version) === Number(request.payload.version),
        );
        return okEnvelope({
          workflow_id: workflow.id,
          ...version,
          current: Number(workflow.current_version) === Number(version.version),
          definition: structuredClone(version.definition),
        });
      }
      if (request.function === "workflows.policy_defaults.publish") {
        const workflow = rows.find(
          (row) => row.id === request.payload.workflow_id,
        );
        const nextVersion = Number(workflow.current_version) + 1;
        const definition = structuredClone(workflow.definition);
        const defaultKey = [
          "file_budget_default",
          "path_claims_default",
          "path_survey_default",
        ].find((key) => request.payload[key] !== undefined);
        const policyKey = defaultKey.replace("_default", "");
        definition.policies[policyKey] =
          request.payload[defaultKey] ? "required" : "optional";
        workflow.current_version = nextVersion;
        workflow.published_at = "2026-07-26T12:00:00Z";
        workflow.definition = definition;
        workflow.versions.push({
          version: nextVersion,
          definition_digest: `${workflow.id}-v${nextVersion}`,
          published_at: "2026-07-26T12:00:00Z",
          published_by_actor_id: 1,
          definition: structuredClone(definition),
        });
        return okEnvelope({
          workflow_id: workflow.id,
          version: nextVersion,
          version_id: nextVersion,
          definition_digest: `${workflow.id}-v${nextVersion}`,
          [defaultKey]: request.payload[defaultKey],
        });
      }
      if (request.function === "workflows.current.set") {
        const workflow = rows.find(
          (row) => row.id === request.payload.workflow_id,
        );
        const version = workflow.versions.find(
          (row) => Number(row.version) === Number(request.payload.version),
        );
        workflow.current_version = Number(version.version);
        workflow.published_at = version.published_at;
        workflow.definition = structuredClone(version.definition);
        return okEnvelope({
          workflow_id: workflow.id,
          version: workflow.current_version,
          version_id: workflow.current_version,
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

export async function mountWorkflows(t, client, hash = "#/workflows") {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { documentNode, root, mounted };
}

export function panelTitles(root) {
  return allNodes(root)
    .filter((node) => node.tagName === "H2")
    .map((node) => node.textContent);
}

export function classText(root, className) {
  return byClass(root, className).map((node) => node.textContent);
}
