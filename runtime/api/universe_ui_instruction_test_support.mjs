import { allNodes, byClass, FakeDocument, settle } from "./universe_ui_dom_test_support.mjs";
import { okEnvelope } from "./universe_ui_workflows_test_support.mjs";
import { workflowInstructionsPanel } from "../../packages/yoke-core/src/yoke_core/ui/static/workflow_instructions_panel.js";

function instructionsClient(seed = []) {
  const requests = [];
  const store = seed.map((row) => ({ ...row }));
  let nextId = 900;
  const find = (id) => store.find((row) => Number(row.id) === Number(id));
  return {
    requests,
    async call(request) {
      requests.push(request);
      const payload = request.payload || {};
      switch (request.function) {
        case "workflow.execution_instruction.list":
          return okEnvelope({ instructions: store.map((row) => ({ ...row })) });
        case "workflow.execution_instruction.create": {
          const id = nextId;
          nextId += 1;
          store.push({ id, ...payload });
          return okEnvelope({ instruction_id: id });
        }
        case "workflow.execution_instruction.update":
          Object.assign(find(payload.instruction_id), payload);
          return okEnvelope({});
        case "workflow.execution_instruction.set_scope": {
          const row = find(payload.instruction_id);
          row.applies_to_all_workflows = payload.applies_to_all_workflows;
          row.workflow_ids = payload.workflow_ids;
          row.applies_to_all_projects = payload.applies_to_all_projects;
          row.project_ids = payload.project_ids;
          return okEnvelope({});
        }
        case "workflow.execution_instruction.delete": {
          const index = store.findIndex(
            (row) => Number(row.id) === Number(payload.instruction_id),
          );
          if (index >= 0) store.splice(index, 1);
          return okEnvelope({});
        }
        default:
          throw new Error(`unexpected function ${request.function}`);
      }
    },
  };
}

export function functionsCalled(client) {
  return client.requests.map((request) => request.function);
}

export async function mountPanel({
  seed = [],
  workflows = [{ id: "dash", name: "Dash" }],
  projects = [],
} = {}) {
  const documentNode = new FakeDocument();
  const client = instructionsClient(seed);
  const host = documentNode.createElement("div");
  host.appendChild(
    workflowInstructionsPanel(documentNode, client, { workflows, projects }),
  );
  await settle();
  return { documentNode, client, host };
}

export function buttonByText(host, text) {
  return allNodes(host).find(
    (node) => node.tagName === "BUTTON" && node.textContent === text,
  );
}

export function checkboxRows(host, className) {
  return byClass(host, className).map((row) => ({
    input: row.children[0],
    label: row.children[1].textContent,
  }));
}

export function toggle(input, checked) {
  input.checked = checked;
  input.dispatchEvent(new Event("change"));
}

