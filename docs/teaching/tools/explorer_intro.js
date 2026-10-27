/* Opening illustration uses the film's original brand geometry. */
function renderIntro(article) {
  article.append(text('p', 'Yoke is a control plane for agentic engineering that gives humans and coding agents one shared source of truth for strategy, planning, implementation, testing, and deployment. You set the direction, and Yoke handles getting it done quickly and correctly.'));
  const viewport = text('div', '', 'intro-visual');
  const image = document.createElement('img');
  image.src = data.intro_visual;
  image.alt = 'Your codebase connected through Yoke to Claude Code, Codex and Cursor.';
  viewport.append(image); article.append(viewport);
}
