export function createHostedFrameWorkflowClient(workflows, gates) {
  const ok = (result) => ({
    status: 200,
    envelope: { success: true, result },
  });
  return {
    async call(request) {
      if (request.function === "projects.list") {
        return ok({
          rows: [{
            id: 1, slug: "yoke", name: "Yoke", emoji: "🐄",
            public_item_prefix: "YOK",
          }],
        });
      }
      if (request.function === "workflows.definition.get") {
        return ok({
          family: "work-items",
          workflows: structuredClone(workflows),
          gate_catalog: Object.entries(gates).map(([id, value]) => ({
            id,
            availability: "live",
            ...value,
          })),
          flows: [],
        });
      }
      if (request.function === "workflow.execution_instruction.list") {
        return ok({ instructions: [] });
      }
      if (request.function === "workflows.version.get") {
        const current = workflows.find(
          (row) => row.id === request.payload.workflow_id,
        );
        const version = current?.versions.find(
          (row) => Number(row.version) === Number(request.payload.version),
        );
        if (current && version) {
          return ok({
            workflow_id: current.id,
            ...structuredClone(version),
            current:
              Number(current.current_version) === Number(version.version),
            definition: structuredClone(version.definition),
          });
        }
      }
      if (request.function === "workflows.policy_defaults.publish") {
        const current = workflows.find(
          (row) => row.id === request.payload.workflow_id,
        );
        if (current) {
          const version =
            Math.max(...current.versions.map((row) => Number(row.version))) + 1;
          const publishedAt = new Date().toISOString();
          const definition = structuredClone(current.definition);
          const defaultKey = [
            "file_budget_default",
            "path_claims_default",
            "path_survey_default",
          ].find((key) => request.payload[key] !== undefined);
          const policyKey = defaultKey.replace("_default", "");
          definition.policies[policyKey] =
            request.payload[defaultKey] ? "required" : "optional";
          current.current_version = version;
          current.published_at = publishedAt;
          current.definition = definition;
          current.versions.push({
            version,
            definition_digest: `${current.id}-v${version}-fixture`,
            published_at: publishedAt,
            published_by_actor_id: 1,
            definition: structuredClone(definition),
          });
          return ok({
            workflow_id: current.id,
            version,
            version_id: version,
            definition_digest: `${current.id}-v${version}-fixture`,
            [defaultKey]: request.payload[defaultKey],
          });
        }
      }
      if (request.function === "workflows.current.set") {
        const current = workflows.find(
          (row) => row.id === request.payload.workflow_id,
        );
        if (current) {
          const version = current.versions.find(
            (row) => Number(row.version) === Number(request.payload.version),
          );
          if (!version) {
            return {
              status: 404,
              envelope: {
                success: false,
                error: { message: "Workflow version not found." },
              },
            };
          }
          current.current_version = Number(version.version);
          current.published_at = version.published_at;
          current.definition = structuredClone(version.definition);
          return ok({
            workflow_id: current.id,
            version: current.current_version,
            version_id: current.current_version,
          });
        }
      }
      return {
        status: 404,
        envelope: {
          success: false,
          error: { message: `No fixture for ${request.function}` },
        },
      };
    },
  };
}
