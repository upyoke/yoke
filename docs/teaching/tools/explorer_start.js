/* Reader-facing copy for the proposed public introduction. */
function renderGettingStarted() {
  const article = text('article', '', 'getting-started-preview');
  article.append(text('p', 'Draft page · Links open the planned detailed sections.', 'source-size'));
  article.append(text('h1', 'Getting started'));
  article.append(text('p', 'Yoke helps you and your coding agents take software from an idea to a working release. It keeps the project’s direction, work, checks and deployments connected, so you can see what is happening and what needs your attention.', 'summary'));
  const sections = [
    ['Install Yoke', 'setup', [
      'Open your coding agent and say:',
      '>install upyoke.com',
      'Your agent handles installation and guides you through setup. It asks for the choices and browser steps that need you.',
      'Onboarding brings your existing project and work into Yoke, establishes what you want to accomplish, and prepares what is needed to begin.'
    ], 'Installation and onboarding'],
    ['Universes, projects and where Yoke runs', 'understand', [
      'A universe is the home for your Yoke projects, work records and configuration. Each project brings together its software, goals and work. You can keep several projects in one universe.',
      'Choose where your universe lives during setup: local runs privately on your computer; self-hosted runs on a server you manage; hosted runs at upyoke.com. Self-hosted and hosted let you connect from multiple computers and work with a team.',
      'You can move a universe between these options using export and import.',
      'Use your agent to work with Yoke and the dashboard to see what is going on. You remain responsible for direction and the decisions that need your judgment.'
    ], 'How Yoke fits together'],
    ['Set direction with strategy documents', 'strategy', [
      'Work with your agent to write and refine your project’s strategy documents. They explain why the project exists, where it is going and what to work on next.',
      'MISSION states the purpose. LANDSCAPE collects research and outside context. VISION describes the future you want. MASTER-PLAN holds the evolving strategy. CURRENT-PLAN sets the near-term focus. You can also add focused plans for particular areas.',
      'Link work items to the strategy documents they serve, so individual changes stay connected to the larger goal.',
      'The frontier shows which work is ready, which is blocked and which is already underway. Steering uses that picture to keep work moving toward your goals.'
    ], 'Direction and priorities'],
    ['Track work from idea to completion', 'work', [
      'An item is a piece of work with a defined outcome. Its workflow sets the steps it must pass through, such as planning, implementation and review.',
      'Different changes need different amounts of planning. Your agent helps choose the workflow, records progress and brings decisions back to you. Dependencies and work claims help agents avoid conflicting work.'
    ], 'Items and workflows'],
    ['Work with agents', 'sessions', [
      'A harness session is a conversation in an agent app such as Claude Code, Codex or Cursor. Yoke records which sessions are active and what work they own.',
      'Steering coordinates that work. Execution levels describe the model and effort used for agent work, so different jobs can use different amounts of capability and cost.'
    ], 'Sessions, steering and levels'],
    ['Give agents the guidance they need', 'guidance', [
      'Project instructions, documentation and skills tell agents how to work in your project. Yoke also supplies relevant guidance as they work, through context packets and command responses.',
      'You can inspect that guidance when you want to understand or change how work happens.'
    ], 'Agent guidance'],
    ['Connect the tools your project uses', 'configuration', [
      'Capabilities are resources your project can use, such as a service integration or a test machine. Packs provide reusable setup and guidance for a particular technology or capability.',
      'Your agent helps configure what the work needs, including settings and access to services. You can add more as your project grows.'
    ], 'Project configuration'],
    ['Know whether the work is good', 'qa', [
      'QA makes the checks for your work explicit. A method defines how to check something; a case defines a particular check; a plan collects the cases.',
      'A requirement says what must be satisfied. A run records an attempt and its evidence. This lets you see what was checked, what passed and what still needs attention.'
    ], 'QA methods, plans, cases and runs'],
    ['Get changes into use', 'delivery', [
      'Merging code and deploying it are separate steps. A deployment flow defines the stages for putting a change into an environment, such as staging or production. A deployment run is one attempt to follow that flow.',
      'Runs record progress, checks and approvals. You can see where a release is going, what has happened and whether it is waiting for you.'
    ], 'Deployment flows and runs'],
    ['Handle database changes', 'databases', [
      'Database changes need their own care because they affect stored data as well as code. Yoke tracks migrations and their checks as part of delivery, including rehearsals where the project requires them.'
    ], 'Databases and migrations'],
    ['Understand problems and recover', 'operations', [
      'When work stops, start with the reason it is blocked and the next action your agent reports. Health checks help diagnose problems with setup and operation.',
      'Recorded failures and lessons help improve the project’s instructions and workflows.'
    ], 'Operations and recovery'],
    ['Control access and decisions', 'access', [
      'Access controls determine who can use project resources and perform actions. Approval steps identify decisions that must come back to a person before work proceeds.',
      'Your agent can guide you through access setup and explain a pending approval; you make the decisions assigned to you.'
    ], 'Access and approvals']
  ];
  for (const [title, page, paragraphs, linkLabel] of sections) {
    const section = text('section', '');
    section.append(text('h2', title));
    for (const paragraph of paragraphs) {
      section.append(text(paragraph.startsWith('>') ? 'blockquote' : 'p',
        paragraph.startsWith('>') ? paragraph.slice(1) : paragraph));
    }
    section.append(nodeLink(byId.get('page:' + page), linkLabel + ' →'));
    article.append(section);
  }
  world.append(article);
  notice.textContent = 'Getting started · Draft public page';
}
