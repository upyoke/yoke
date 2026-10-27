/* Three alternatives for review; all use the film's original brand geometry. */
function renderIntroVariants(article) {
  const variants = [
    ['Shared coordination',
      'Yoke is a control plane for agentic engineering. It gives you and your coding agents one shared place to organize work, coordinate changes, check results and manage releases. You set the direction; Yoke keeps the work connected across agents and sessions.',
      'Your codebase and three supported agent apps connected through Yoke.'],
    ['From direction to delivery',
      'Yoke is a control plane for agentic engineering. It connects your project’s strategy to the work agents carry out, the checks that prove it works and the deployments that put it into use. You can follow progress and make decisions throughout.',
      'Yoke connects your agents and codebase across strategy, work, checks and deployment.'],
    ['People and agents working together',
      'Yoke is a control plane for agentic engineering. It coordinates people and coding agents around shared goals, plans and project rules. Agents can work across sessions and machines while you see who owns each change, what is ready and where your input is needed.',
      'People, a codebase and three supported agent apps share a connection through Yoke.']
  ];
  article.append(text('p', 'Three alternatives for this opening section.', 'source-size'));
  variants.forEach(([title, paragraph, alt], i) => {
    const option = text('section', '', 'intro-variant');
    option.append(text('h3', `Option ${i + 1} · ${title}`), text('p', paragraph));
    const viewport = text('div', '', 'intro-visual');
    const image = document.createElement('img');
    image.src = data.intro_visuals[i]; image.alt = alt;
    viewport.append(image); option.append(viewport); article.append(option);
  });
}
