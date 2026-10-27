/* Homepage hosting cards, adapted without card calls to action.
 * Source: Platform webapp/src/components/marketing-hosting.tsx. */
function renderHostingCards(section) {
  const modes = [
    ['local', 'Local', 'Start on your own machine.',
      'Your core and data stay on your laptop, with no signup. Move to a server or Yoke Cloud whenever your team is ready.',
      '<rect x="4" y="3" width="16" height="12" rx="1.5"/><path d="M4 15 1 19h22l-3-4M9 19h6"/>'],
    ['selfhost', 'Self-hosted', 'Run it on your infrastructure.',
      'Host the Yoke core and its database on your own server. Connect your team and the machines you control.',
      '<rect x="3" y="3" width="18" height="8" rx="2"/><rect x="3" y="13" width="18" height="8" rx="2"/><path d="M7 7h.01M7 17h.01M12 7h5M12 17h5"/>'],
    ['hosted', 'Hosted', 'Let us host the control plane.',
      'A shared home for your team’s strategy and work. Invite teammates, connect your own machines and model credentials.',
      '<path d="M6 18a4 4 0 0 1-.5-8A6.5 6.5 0 0 1 18 8a5 5 0 0 1 0 10Z"/>']
  ];
  const grid = text('div', '', 'intro-hosting-grid');
  for (const [mode, title, lead, body, shape] of modes) {
    const card = text('article', '', 'intro-hosting-card ' + mode);
    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    icon.setAttribute('viewBox', '0 0 24 24'); icon.setAttribute('aria-hidden', 'true');
    icon.innerHTML = shape;
    const heading = text('div', '', 'intro-hosting-title');
    heading.append(text('h3', title));
    if (mode === 'hosted') heading.append(text('span', 'Private beta'));
    card.append(icon, heading, text('strong', lead), text('p', body));
    grid.append(card);
  }
  section.append(grid);
}
