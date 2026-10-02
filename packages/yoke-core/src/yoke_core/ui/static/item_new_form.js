import { selectionParam } from "./universe_project_selection.js";
import { buildUniverseRoute } from "./universe_navigation.js";
import { itemDrillInHref } from "./universe_item_routes.js";
import {
  itemIntakeField,
  itemPostureToggle,
  verificationChoiceSelect,
  webWorkflowSteer,
} from "./item_intake_controls.js";
import { callFunction, el, renderError } from "./universe_view_support.js";
import {
  button, sortedWorkflows, workflowPanel,
} from "./workflow_view_primitives.js";

export function renderNewItemForm(context, main, projectId, options) {
  const documentNode = context.document;
  const { definition, catalog, draft, projectControl, instructions } = options;
  const requestedWorkflowId = draft.workflowId;
  const project = context.projects().find((row) => String(row.id) === String(projectId));
    const workflows = sortedWorkflows(
      definition.workflows || [],
    );
    const steer = webWorkflowSteer(workflows);
    let selected = steer.web.find(
      (workflow) => workflow.id === requestedWorkflowId,
    ) || steer.web[0];
    if (!selected) {
      main.textContent =
        "No current workflow version allows the web form entry surface.";
      return;
    }
    const verificationStageId = "reviewing-implementation";
    const state = draft.posture || {
      verification: false,
      file_budget: false,
      path_claims: false,
      path_survey: false,
      approval_on_done: false,
      deployment: false,
      verification_target: "",
    };
    const pathSurveyPolicyFor = (workflow) => (
      workflow.definition?.policies?.path_survey ||
      (["dash", "blitz"].includes(workflow.id) ? "required" : null)
    );
    draft.posture = state;
    state.path_survey = pathSurveyPolicyFor(selected) === "required";
    const verificationAvailable = Boolean(
      catalog.plans.length || catalog.methods.length,
    );
    draft.workflowId = selected.id;
    const titleLimit = definition.title_max_length;
    if (!titleLimit) {
      main.textContent =
        "workflows.definition.get served no title_max_length, so this form " +
        "cannot cap the title. Update the server to a build that serves it.";
      return;
    }
    const title = el(documentNode, "input", "item-form-control");
    title.type = "text";
    // The server decides the limit for the selected project and stays
    // authoritative; this only stops the field accepting what it will refuse.
    title.maxLength = titleLimit;
    title.required = true;
    title.value = draft.title || "";
    draft.titleControl = title;
    const instruction = el(documentNode, "textarea", "item-form-control");
    instruction.required = true;
    instruction.rows = 3;
    instruction.value = draft.instruction || "";
    draft.instructionControl = instruction;
    for (const control of [title, instruction]) control.addEventListener("input", () => draft.save?.());
    const render = () => {
      const directWorkflow = ["dash", "blitz"].includes(selected.id);
      const pathSurveyPolicy = pathSurveyPolicyFor(selected);
      const allow = new Set(
        selected.definition?.policies?.item_posture_allowlist || [],
      );
      for (const key of ["verification", "file_budget", "path_claims", "deployment", "approval_on_done"]) {
        const allowed = allow.has(key) || (key === "approval_on_done" && allow.has("approval"));
        state[key] = allowed && state[key] === true;
      }
      if (!verificationAvailable) state.verification = false;
      const stored = draft.save?.();
      const host = el(documentNode, "div", "item-new");
      const head = el(
        documentNode, "div", "page-head item-new-heading",
      );
      const copy = el(documentNode, "div", "h");
      copy.appendChild(el(
        documentNode,
        "h1",
        "title",
        `New ${selected.name || selected.id}`,
      ));
      copy.appendChild(el(
        documentNode, "p", "subtitle", steer.copy,
      ));
      head.appendChild(copy);
      const cancel = el(documentNode, "a", "item-button", "Discard draft");
       cancel.addEventListener("click", () => draft.discard?.());
      cancel.href = buildUniverseRoute("items", context.screenPreferences ? selectionParam(context.screenPreferences.selectionFor("items")) : String(projectId));
      const actions = el(documentNode, "div", "head-actions");
      actions.appendChild(cancel);
      head.appendChild(actions);
      host.appendChild(head);

      const form = el(documentNode, "form", "item-form");
      form.addEventListener("change", () => draft.save?.());
      if (steer.web.length > 1) {
        const choices = workflowPanel(documentNode, "Choose a workflow");
        choices.body.className += " item-workflow-options";
        for (const workflow of steer.web) {
          const choice = button(
            documentNode,
            workflow.name || workflow.id,
            `item-button${workflow.id === selected.id ? " primary" : ""}`,
          );
          choice.setAttribute("aria-pressed", String(workflow.id === selected.id));
          choice.addEventListener("click", () => {
            if (draft.creating) return;
            selected = workflow;
            draft.workflowId = workflow.id;
            options.onWorkflowChange(workflow.id);
            state.path_survey = pathSurveyPolicyFor(selected) === "required";
            render();
          });
          choices.body.appendChild(choice);
        }
        form.appendChild(choices.panel);
      }
      form.appendChild(itemIntakeField(documentNode, "Title", title));
      const instructionHelp = el(
        documentNode,
        "span",
        "item-form-help",
        selected.id === "task"
          ? "This is the complete laneless, merge-free instruction. Choose " +
            "Dash when work needs a git lane, verification, or approval."
          : "This is the whole spec. The agent completes the full instruction " +
            "in this item, including larger-than-expected work.",
      );
      form.appendChild(itemIntakeField(
        documentNode, "Instruction", instruction, instructionHelp,
      ));
      form.appendChild(itemIntakeField(documentNode, "Project", projectControl));
      if (stored) form.appendChild(el(documentNode, "p", "item-form-help", "Draft saved in this browser tab. You can leave and return."));
      if (options.notice) form.appendChild(el(documentNode, "p", "item-form-help", options.notice));
      if (instructions.length) {
        const details = el(documentNode, "details", "item-execution-instructions");
        details.appendChild(el(documentNode, "summary", null, "Execution instructions"));
        for (const entry of instructions) {
          details.appendChild(el(documentNode, "pre", null, entry.content));
        }
        form.appendChild(details);
      }
      const settings = workflowPanel(documentNode, "Settings");
      settings.body.className += " item-stack";
      const rows = [
        [
          "verification", "✓", "Verification",
          state.verification
            ? `choose a plan or ad hoc case — runs at ${verificationStageId}`
            : verificationAvailable
              ? `when off, we rely on agent self-check at ${verificationStageId}`
              : "no plans or ad hoc methods are available for this project",
        ],
        [
          "file_budget", "▤", "File Budget",
          `plans the files this ${selected.name || selected.id} touches ` +
          "for sizing and conflict evidence before implementation",
        ],
        [
          "path_claims", "⛉", "Path claims",
          `reserves the files this ${selected.name || selected.id} touches, ` +
          "so overlapping work serializes instead of colliding at merge",
        ],
        [
          "path_survey", "⌁", "Path survey",
          `checks the files this ${selected.name || selected.id} expects to ` +
          "touch and re-checks the declared set immediately before merge",
        ],
        [
          "approval_on_done", "☑", "Approval on done",
          "someone has to approve before it can finish — a project owner, " +
          "or a named person",
        ],
        [
          "deployment", "⬈", "Deploy after merge",
          "once the work merges, ship it through the project's delivery flow",
        ],
      ];
      let settingCount = 0;
      for (const [key, icon, label, note] of rows) {
        const directSurvey = key === "path_survey" && directWorkflow;
        if (!allow.has(key) && !(key === "approval_on_done" && allow.has("approval")) && !directSurvey) {
          continue;
        }
        settings.body.appendChild(itemPostureToggle(
          documentNode,
          icon,
          label,
          note,
          state,
          key,
          render,
          key === "verification" && state.verification
            ? verificationChoiceSelect(documentNode, catalog, state)
            : null,
          key !== "verification" || verificationAvailable,
          key === "path_survey" && pathSurveyPolicy === "required",
        ));
        settingCount += 1;
      }
      if (settingCount) form.appendChild(settings.panel);
      const footer = el(documentNode, "div", "item-form-actions");
      const submit = button(
        documentNode,
        `Create ${selected.name || selected.id}`,
        "item-button primary",
      );
      submit.type = "submit";
      submit.disabled = Boolean(draft.instructionsLoading || draft.creating);
      footer.appendChild(submit);
      form.appendChild(footer);
      const outcome = el(documentNode, "p", "item-form-outcome");
      form.appendChild(outcome);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const cleanTitle = title.value.trim();
        const cleanInstruction = instruction.value.trim();
        if (submit.disabled || draft.creating) return;
        if (!cleanTitle || !cleanInstruction) {
          outcome.className = "item-form-outcome error";
          outcome.textContent = "Title and instruction are required.";
          return;
        }
        if (cleanTitle.length > titleLimit) {
          outcome.className = "item-form-outcome error";
          outcome.textContent = `Title exceeds this project's ${titleLimit}-character limit. Shorten it and retry.`;
          return;
        }
        if (state.verification && !state.verification_target) {
          outcome.className = "item-form-outcome error";
          outcome.textContent =
            "Choose a verification plan or ad hoc method.";
          return;
        }
        const posture = {};
        if (state.verification) {
          const [kind, id] = state.verification_target.split(":", 2);
          posture.verification = kind === "plan"
            ? { kind: "plan", plan_id: Number(id) }
            : { kind: "ad_hoc", method_id: id };
        }
        for (const key of [
          "file_budget", "path_claims", "path_survey", "deployment",
        ]) {
          if (key === "path_survey" && pathSurveyPolicy === "required") {
            continue;
          }
          if (state[key]) posture[key] = true;
        }
        if (state.approval_on_done) {
          posture[allow.has("approval_on_done")
            ? "approval_on_done" : "approval"] = true;
        }
        draft.creating = true;
        submit.disabled = true;
        projectControl.disabled = true;
        outcome.className = "item-form-outcome";
        outcome.textContent = "Creating…";
        let result;
        try {
          result = await callFunction(context.client, "items.create", {
            title: cleanTitle,
            instruction: cleanInstruction,
            project: String(project?.slug || project?.id || projectId),
            workflow: selected.id,
            entry_surface: "web_form",
            workflow_posture: posture,
          });
        } catch (error) {
          result = {
            status: 0,
            envelope: {
              success: false,
              error: { message: String(error) },
            },
          };
        }
        if (result.status === 200 && result.envelope.success) {
          draft.discard?.();
          const itemRef = result.envelope.result?.public_ref;
          outcome.textContent = `Created ${itemRef}.`;
          const href = itemDrillInHref({
            projectId,
            publicRef: itemRef,
          });
          if (context.navigate && href) {
            context.navigate(href);
          }
          return;
        }
        draft.creating = false;
        submit.disabled = false;
        projectControl.disabled = false;
        outcome.className = "item-form-outcome error";
        outcome.textContent =
          result.envelope?.error?.message || "Item creation failed.";
      });
      host.appendChild(form);
      main.replaceChildren(host);
    };
    render();
}
