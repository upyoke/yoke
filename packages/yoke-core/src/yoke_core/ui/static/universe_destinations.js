// Stable workbench destinations, their groups, and their project-scope
// contracts.
//
// Three groups, and the second and third exist to say something honest about
// the first. FOCUS is what an operator opens. SETTINGS is configuration that
// persists. DIAGNOSTICS is everything else — and it is a drawer on purpose,
// not a filing failure: those destinations are unproven, several of them
// window onto things an agent authors in the CLI rather than anything a person
// builds here, and one flat list of twenty claimed they were all equally worth
// going to. A destination leaves the drawer when it earns a reason to be
// looked at.
//
// Settings sits above Diagnostics because it is the group you open on purpose;
// the drawer is where you end up, not where you head.

export const SCOPE_MULTI = "multi", SCOPE_SINGLE = "single";
export const SCOPE_NONE = "none";

export const GROUP_FOCUS = "focus";
export const GROUP_SETTINGS = "settings";
export const GROUP_DIAGNOSTICS = "diagnostics";

// Render order, and the label each group carries in the sidebar. Focus is
// unlabelled: it is the top of the list and needs no heading to say so.
export const NAV_GROUPS = [
  { id: GROUP_FOCUS, label: "" },
  { id: GROUP_SETTINGS, label: "Settings" },
  { id: GROUP_DIAGNOSTICS, label: "Diagnostics" },
];

export const NAV = [
  {
    id: "overview", icon: "⊞", label: "Overview", scope: SCOPE_MULTI,
    group: GROUP_FOCUS,
    summary: "Your Yoke universe at a glance",
  },
  {
    id: "sessions", icon: "◈", label: "Sessions", scope: SCOPE_MULTI,
    group: GROUP_FOCUS,
    summary:
      "What can run on each machine, and every harness session running against "
      + "this universe.",
  },
  {
    id: "inbox", icon: "✉", label: "Inbox", scope: SCOPE_MULTI,
    group: GROUP_FOCUS,
    summary: "The gates waiting on your decision, and the messages sent to you.",
  },

  // A workflow definition is configuration: it is authored once and every item
  // then follows the version pinned to it. What you govern with is not what
  // you watch.
  {
    id: "organization", icon: "⛭", label: "Universe", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
    summary: "This organization and its universe, including export and import.",
  },
  {
    id: "workflows", icon: "⚗", label: "Workflows", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
    summary:
      "The versioned definitions every work item follows — lifecycle, posture, gates, testing and delivery.",
  },
  {
    id: "projects", icon: "▤", label: "Projects", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
    summary: "Every project in this universe. Open one for its settings.",
  },
  {
    id: "github", icon: "⎇", label: "GitHub", scope: SCOPE_SINGLE,
    group: GROUP_SETTINGS,
    summary: "How this project binds to its repository, and how they sync.",
  },
  {
    id: "access", icon: "⚇", label: "Access", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
    summary: "Who and what may act here, at the universe and per project.",
  },
  {
    id: "members", icon: "⚉", label: "Members", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
    summary: "The people in your organization, managed by the hosting platform.",
    hostFed: true,
  },
  {
    id: "billing", icon: "▧", label: "Billing", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
    summary: "Your plan and payments, managed by the hosting platform.",
    hostFed: true,
  },

  // Ordered by subject, in the order the subjects follow each other: what the
  // work is, how it ships, how it is proved, what the project is made of, and
  // the record of what happened. Alphabetical would have been an order too,
  // and a worse one — it puts Architecture beside Capabilities because both
  // start with a letter.
  {
    id: "strategy", icon: "❖", label: "Strategy", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
    summary:
      "The authoritative planning corpus — authored through a harness, reviewable and traceable here.",
  },
  {
    id: "items", icon: "≣", label: "Items", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "deployments", icon: "⬈", label: "Deployments", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
    summary: "Each run of a flow against a target environment.",
  },
  {
    id: "environments", icon: "◇", label: "Environments", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
    summary: "The deploy targets runs ship to.",
  },
  {
    id: "flows", icon: "⇉", label: "Flows", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
    summary: "The pipeline definitions runs execute.",
  },
  {
    id: "databases", icon: "▤", label: "Databases", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
    summary: "Declared database models, their posture, and the apply records.",
  },
  {
    id: "qa-methods", icon: "◉", label: "QA methods", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
    summary: "The registered contracts each case uses to prove its claim.",
  },
  {
    id: "qa-plans", icon: "◎", label: "QA plans", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
    summary: "Project-scoped ordered cases and where they are attached.",
  },
  {
    id: "qa-activity", icon: "◍", label: "QA activity", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
    summary: "Readable case outcomes folded from requirements, runs and evidence.",
  },
  {
    id: "capabilities", icon: "⚿", label: "Capabilities", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
    summary:
      "The configured providers, declared models, and test resources Yoke can use on your behalf.",
    pageAction: { label: "Add capability", view: "projects" },
  },
  {
    id: "packs", icon: "◫", label: "Packs", scope: SCOPE_NONE,
    group: GROUP_DIAGNOSTICS,
    summary:
      "Reusable capabilities whose installed code belongs to the project.",
  },
  {
    id: "architecture", icon: "▦", label: "Architecture", scope: SCOPE_SINGLE,
    group: GROUP_DIAGNOSTICS,
    summary:
      "The project's declared map — layers, areas, gateways — and how "
      + "much of the tree honors it.",
  },
  // Fleet-wide traffic, which is not the Inbox: the Inbox is yours.
  {
    id: "messages", icon: "✦", label: "Messages", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
    summary: "Compose confirmed deliveries and inspect per-recipient receipts.",
  },
  {
    id: "events", icon: "≋", label: "Events", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "doctor", icon: "♥", label: "Doctor", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
    summary: "The health checks and what they found.",
  },
  {
    id: "ouroboros", icon: "∞", label: "Ouroboros", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  // Registration and proved identity per registered machine, absorbing the
  // launch and relay records. Capacity and health are a different question and
  // live on Sessions, which is where they are read: before staffing, not after.
  {
    id: "machines", icon: "▣", label: "Machines", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
    summary:
      "Connected machines, the native surfaces they serve, and the launches "
      + "they have run.",
  },
];
