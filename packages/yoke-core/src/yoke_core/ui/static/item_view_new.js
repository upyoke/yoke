import { callFunction, el, renderError } from "./universe_view_support.js";
import { itemIntakeField, loadVerificationCatalog, webWorkflowSteer } from "./item_intake_controls.js";
import { renderNewItemForm } from "./item_new_form.js";

export function renderNewItemView(context, main, initialProjectId) {
  const documentNode = context.document;
  const query = String(documentNode.defaultView?.location?.hash || "").split("?", 2)[1] || "";
  const draft = { workflowId: new URLSearchParams(query).get("workflow") };
  const selector = el(documentNode, "select", "item-form-control item-project-select");
  selector.required = true;
  let projectId = "";
  let sequence = 0;
  let instructionSequence = 0;
  let instructions = [];
  let renderForm = null;
  const valid = (result) => result.status === 200 && result.envelope.success;
  const showFailure = (result) => {
    main.replaceChildren(itemIntakeField(documentNode, "Project", selector));
    renderError(main, result);
    main.appendChild(el(documentNode, "p", "item-form-help", "Choose another project or reload to retry. Your draft is preserved."));
  };
  const loadInstructions = async (workflowId) => {
    const token = ++instructionSequence;
    const result = await callFunction(context.client, "workflow.execution_instruction.resolve", {
      workflow: workflowId, project: projectId, detail: "full",
    });
    if (token !== instructionSequence || !context.isMounted()) return;
    if (!valid(result)) { showFailure(result); return; }
    instructions = result.envelope.result?.execution_instructions || [];
    draft.instructionsLoading = false;
    renderForm?.();
  };
  const loadProject = async () => {
    const token = ++sequence;
    ++instructionSequence;
    draft.title = draft.titleControl?.value ?? draft.title;
    draft.instruction = draft.instructionControl?.value ?? draft.instruction;
    selector.value = projectId;
    main.replaceChildren(itemIntakeField(documentNode, "Project", selector), el(documentNode, "p", "empty", "Loading project settings…"));
    const project = context.projects().find((row) => String(row.id) === projectId);
    try {
      const [result, catalog] = await Promise.all([
        callFunction(context.client, "workflows.definition.get", { project: projectId }),
        loadVerificationCatalog(context.client, project),
      ]);
      if (token !== sequence || !context.isMounted()) return;
      if (!valid(result) || catalog.failed) { showFailure(catalog.failed || result); return; }
      const definition = result.envelope.result || {};
      const workflow = webWorkflowSteer(definition.workflows || []).web.find((row) => row.id === draft.workflowId)
        || webWorkflowSteer(definition.workflows || []).web[0];
      if (!workflow) {
        main.appendChild(el(documentNode, "p", "empty", "No current workflow version allows the web form entry surface."));
        return;
      }
      const priorWorkflow = draft.workflowId;
      draft.workflowId = workflow.id;
      const notice = draft.title !== undefined
        ? "Project settings refreshed. Review this project's settings before creating." + (priorWorkflow && priorWorkflow !== workflow.id ? ` ${priorWorkflow} is unavailable; ${workflow.name || workflow.id} is selected.` : "")
        : "";
      draft.posture = null;
      renderForm = () => renderNewItemForm(context, main, projectId, {
        definition, catalog, draft, projectControl: selector, instructions, notice,
        onWorkflowChange: (id) => {
          draft.instructionsLoading = true;
          draft.title = draft.titleControl.value;
          draft.instruction = draft.instructionControl.value;
          loadInstructions(id).catch((error) => showFailure({ status: 0, envelope: { error: { message: String(error) } } }));
        },
      });
      await loadInstructions(workflow.id);
    } catch (error) {
      if (token === sequence && context.isMounted()) showFailure({ status: 0, envelope: { error: { message: String(error) } } });
    }
  };
  selector.addEventListener("change", () => { projectId = selector.value; loadProject(); });
  main.replaceChildren(el(documentNode, "p", "empty", "Loading projects…"));
  callFunction(context.client, "projects.list", { fields: ["id", "slug", "name", "emoji"], for_item_creation: true })
    .then((result) => {
      if (!context.isMounted()) return;
      if (!valid(result)) { showFailure(result); return; }
      if (!result.envelope.result?.creation_scoped) {
        main.textContent = "Item creation project permissions are unavailable. Update the server and reload to retry.";
        return;
      }
      const projects = result.envelope.result.rows || [];
      const placeholder = el(documentNode, "option", null, "Choose a project");
      placeholder.value = "";
      placeholder.disabled = true;
      selector.appendChild(placeholder);
      for (const project of projects) {
        const option = el(documentNode, "option", null, `${project.emoji || ""} ${project.name || project.slug}`.trim());
        option.value = String(project.id);
        selector.appendChild(option);
      }
      if (!projects.length) {
        main.textContent = "You cannot create items in any project. Ask a project owner for access.";
        return;
      }
      projectId = projects.some((row) => String(row.id) === String(initialProjectId)) ? String(initialProjectId)
        : projects.length === 1 ? String(projects[0].id) : "";
      selector.value = projectId;
      if (projectId) loadProject();
      else main.replaceChildren(itemIntakeField(documentNode, "Project", selector), el(documentNode, "p", "item-form-help", "Choose the project this item belongs to."));
    }).catch((error) => { if (context.isMounted()) showFailure({ status: 0, envelope: { error: { message: String(error) } } }); });
}
