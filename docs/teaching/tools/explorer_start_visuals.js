/* Adapted from Platform's marketing graphics and yoke-film beats 06–10.
 * Source paths and adaptation notes: getting-started-visuals.md. */
function startVisual(page) {
  const figure = text('figure', '', 'start-visual');
  function caption(value) { figure.append(text('figcaption', value)); }
  function cards(entries, className = '') {
    const grid = text('div', '', 'start-visual-grid ' + className);
    for (const [label, title, detail] of entries) {
      const card = text('div', '', 'start-visual-card');
      card.append(text('small', label), text('strong', title));
      if (detail) card.append(text('p', detail));
      grid.append(card);
    }
    figure.append(grid);
  }
  function track(entries) {
    const list = text('ol', '', 'start-visual-track');
    for (const [name, detail] of entries) {
      const step = text('li', '');
      step.append(text('strong', name), text('span', detail)); list.append(step);
    }
    figure.append(list);
  }
  if (page === 'setup') {
    figure.append(text('div', 'Your agent', 'start-visual-bar'));
    figure.append(text('p', 'install upyoke.com', 'start-chat-prompt'));
    figure.append(text('p', 'Installation → Setup choices → Project onboarding', 'start-chat-response'));
    caption('One request starts the guided setup.');
  } else if (page === 'understand') {
    const options = [
      ['Local', 'Your computer', '<rect x="4" y="3" width="16" height="12" rx="1.5"/><path d="M4 15 1 19h22l-3-4M9 19h6"/>'],
      ['Self-hosted', 'Your server', '<rect x="8" y="3" width="8" height="18" rx="2"/><path d="M12 7v.01M12 12v5"/>'],
      ['Hosted', 'upyoke.com', '<path d="M6 18a4 4 0 0 1-.5-8A6.5 6.5 0 0 1 18 8a5 5 0 0 1 0 10Z"/>']
    ];
    const grid = text('div', '', 'start-visual-grid');
    for (const [name, place, shape] of options) {
      const card = text('div', '', 'start-visual-card start-hosting');
      const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      icon.setAttribute('viewBox', '0 0 24 24'); icon.setAttribute('aria-hidden', 'true');
      icon.innerHTML = shape;
      card.append(icon, text('strong', name), text('p', place)); grid.append(card);
    }
    figure.append(grid);
    const universe = text('div', '', 'start-universe');
    universe.append(text('strong', 'Your universe'));
    const projects = text('div', '', 'start-projects');
    ['Website project', 'API project', 'Mobile app project'].forEach(p => projects.append(text('span', p)));
    universe.append(projects); figure.append(universe);
    caption('Choose a home for your universe; keep your projects together inside it.');
  } else if (page === 'strategy') {
    figure.append(text('div', 'Strategy · Example storefront project', 'start-visual-bar'));
    cards([
      ['MISSION', 'Help independent merchants sell online', 'Why this project exists'],
      ['VISION', 'One place for storefronts, customers and orders', 'The future to build'],
      ['LANDSCAPE', 'Understand checkout and inventory needs', 'Research and outside context'],
      ['MASTER-PLAN', 'Reliable checkout, then simpler order management', 'The evolving strategy']
    ], 'start-standing');
    const plan = text('div', '', 'start-plan');
    plan.append(text('small', 'CURRENT-PLAN · STEERED'), text('strong', 'Make the first purchase effortless'));
    figure.append(plan);
    caption('Standing strategy informs focused plans; steering turns plans into work.');
  } else if (page === 'work') {
    figure.append(text('div', 'One item · First-time checkout', 'start-visual-bar'));
    track([['Plan', 'Define the outcome'], ['Implement', 'Make the change'], ['Review', 'Check the result']]);
    cards([['CLAIMED BY', 'One agent session', 'Owns this item’s work'], ['WORKTREE', 'Isolated checkout', 'Keeps changes separate']]);
    caption('Illustrative workflow: the project defines the stages and checks.');
  } else if (page === 'sessions') {
    figure.append(text('div', 'Sessions · Example team', 'start-visual-bar'));
    const plan = text('div', '', 'start-plan');
    plan.append(text('small', 'STEERING SESSION'), text('strong', 'CURRENT-PLAN'), text('p', 'Coordinates work toward an easier first purchase'));
    figure.append(plan);
    cards([
      ['CLAUDE CODE · ACTIVE', 'Improve checkout', 'Claimed item · Worktree A'],
      ['CODEX · ACTIVE', 'Show delivery estimates', 'Claimed item · Worktree B'],
      ['CURSOR · ACTIVE', 'Guide product listing', 'Claimed item · Worktree C']
    ]);
    caption('Sessions hold distinct work while steering keeps the plan connected.');
  } else if (page === 'qa') {
    figure.append(text('div', 'Evidence follows the change', 'start-visual-bar'));
    track([['Tests', 'Recorded results'], ['Browser check', 'Screenshots'], ['Review', 'Recorded decision'], ['Approval', 'Human decision']]);
    caption('Example checks from the film: each step contributes evidence where required.');
  } else if (page === 'delivery') {
    figure.append(text('div', 'Deployment · Example production run', 'start-visual-bar'));
    track([['✓ Merged', 'Complete'], ['✓ Item QA', 'Passed'], ['Approval', 'Waiting on you'], ['Release', 'Next']]);
    cards([['CHANGE', 'A better first purchase', 'Checkout and delivery estimates'], ['EVIDENCE', 'Checks and review attached', 'Inspect before deciding']]);
    caption('A run shows completed stages, the current decision and what comes next.');
  } else if (page === 'operations') {
    figure.append(text('div', 'Ouroboros · Learning from the work', 'start-visual-bar'));
    track([['Field notes', 'Capture rough edges'], ['Curation', 'Find patterns and file work'], ['Steering', 'Staff the improvements']]);
    figure.append(text('p', '↻ Results and new observations feed the next cycle', 'start-cycle'));
    caption('The homepage’s learning loop, expanded into its three steps.');
  } else return null;
  return figure;
}
