// Stable workbench destinations and their project-scope contracts.

export const SCOPE_MULTI = "multi", SCOPE_SINGLE = "single";
export const SCOPE_NONE = "none";

export const NAV = [
  {
    id: "overview", icon: "⊞", label: "Overview", scope: SCOPE_MULTI,
    summary: "Your Yoke universe at a glance",
  },
  {
    id: "inbox", icon: "✉", label: "Inbox", scope: SCOPE_MULTI,
    summary: "Decisions waiting on you, and what happened while you were away.",
  },
  {
    id: "strategy", icon: "❖", label: "Strategy", scope: SCOPE_MULTI,
    summary:
      "The authoritative planning corpus — authored through a harness, reviewable and traceable here.",
  },
  {
    id: "frontier", icon: "⚡", label: "Frontier", scope: SCOPE_MULTI,
    summary: "What can run now, and why. You steer here; the harness runs it.",
  },
  { id: "items", icon: "≣", label: "Items", scope: SCOPE_MULTI },
  {
    id: "sessions", icon: "◈", label: "Sessions", scope: SCOPE_MULTI,
    summary:
      "Every harness session running against this universe, and what each one holds.",
  },
  {
    id: "delivery", icon: "⬈", label: "Delivery", scope: SCOPE_MULTI,
    summary: "Environments, flows and runs, with databases and infrastructure.",
    tabs: [
      {
        id: "runs", label: "Runs",
        summary: "Each run of a flow against a target environment.",
      },
      {
        id: "environments", label: "Environments",
        summary: "The deploy targets runs ship to.",
      },
      {
        id: "flows", label: "Flows",
        summary: "The pipeline definitions runs execute.",
      },
      {
        id: "databases", label: "Databases",
        summary:
          "Declared database models, their posture, and the apply records.",
      },
      {
        id: "infrastructure", label: "Infrastructure",
        summary:
          "What backs an environment and its latest operational state.",
      },
    ],
  },
  {
    id: "qa", icon: "◉", label: "QA", scope: SCOPE_MULTI,
    summary:
      "Test plans prove the work; methods say how; capabilities make it possible.",
    tabs: [
      {
        id: "methods", label: "Methods",
        summary: "The registered contracts each case uses to prove its claim.",
      },
      {
        id: "plans", label: "Plans",
        summary: "Project-scoped ordered cases and where they are attached.",
      },
      {
        id: "activity", label: "Activity",
        summary: "Readable case outcomes folded from requirements, runs and evidence.",
      },
    ],
  },
  {
    id: "workflows", icon: "⚗", label: "Workflows", scope: SCOPE_NONE,
    summary:
      "The versioned definitions every work item follows — lifecycle, posture, gates, testing and delivery.",
  },
  {
    id: "capabilities", icon: "⚿", label: "Capabilities", scope: SCOPE_MULTI,
    summary:
      "The configured providers, declared models, and test resources Yoke can use on your behalf.",
    pageAction: { label: "Add capability", view: "project" },
  },
  { id: "events", icon: "≋", label: "Events", scope: SCOPE_MULTI },
  {
    id: "doctor", icon: "♥", label: "Doctor", scope: SCOPE_MULTI,
    summary: "The health checks and what they found.",
  },
  { id: "ouroboros", icon: "∞", label: "Ouroboros", scope: SCOPE_MULTI },
  { id: "projects", icon: "▤", label: "Projects", scope: SCOPE_NONE },
  {
    id: "access", icon: "⚇", label: "Access", scope: SCOPE_NONE,
    summary: "Who and what may act here, at the universe and per project.",
  },
  {
    id: "packs", icon: "◫", label: "Packs", scope: SCOPE_NONE,
    summary:
      "Reusable capabilities whose installed code belongs to the project.",
  },
  {
    id: "github", icon: "⎇", label: "GitHub", scope: SCOPE_SINGLE,
    summary: "How this project binds to its repository, and how they sync.",
  },
  {
    id: "project", icon: "⚙", label: "Project settings", scope: SCOPE_SINGLE,
    summary: "Settings for one project.",
  },
  {
    id: "organization", icon: "⛭", label: "Universe settings", scope: SCOPE_NONE,
    summary: "This organization and its universe, including export and import.",
  },
  {
    id: "members", icon: "⚉", label: "Members", scope: SCOPE_NONE,
    summary: "The people in your organization, managed by the hosting platform.",
    hostFed: true,
  },
  {
    id: "billing", icon: "▧", label: "Billing", scope: SCOPE_NONE,
    summary: "Your plan and payments, managed by the hosting platform.",
    hostFed: true,
  },
];
