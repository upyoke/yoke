/* Opening illustration uses the film's original brand geometry. */
function renderIntro(article) {
  article.append(text('p', 'Yoke is a control plane for agentic engineering that gives humans and coding agents one shared source of truth for strategy, planning, implementation, testing, and deployment. You set the direction, and Yoke handles getting it done quickly and correctly.'));
  const viewport = text('div', '', 'intro-visual');
  const image = document.createElement('img');
  image.src = data.intro_visual;
  image.alt = 'Your codebase connected through Yoke to Claude Code, Codex and Cursor.';
  viewport.append(image); article.append(viewport);
}
function renderInstallIntro(article) {
  const section = text('section', '');
  section.append(text('h2', 'Install Yoke'));
  section.append(text('p', 'Open Claude Code, Codex, or Cursor and say:'));
  const prompt = text('div', '', 'intro-install-command');
  const command = text('code', 'install upyoke.com');
  const copy = text('button', 'Copy');
  copy.type = 'button'; copy.setAttribute('aria-label', 'Copy install upyoke.com');
  const status = text('p', '', 'source-size');
  status.setAttribute('role', 'status');
  copy.onclick = async () => {
    try {
      await navigator.clipboard.writeText(command.textContent);
      copy.textContent = 'Copied ✓'; status.textContent = 'Copied to clipboard.';
    } catch {
      copy.textContent = 'Select text';
      status.textContent = 'Clipboard unavailable. Select the command to copy it.';
      const range = document.createRange(); range.selectNodeContents(command);
      const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    }
  };
  prompt.append(command, copy); section.append(prompt, status);
  section.append(text('p', 'Your agent handles installation and guides you through setup, helping you make the right configuration choices.'));
  const onboarding = text('p', 'Once installation and setup are complete, your agent will launch the ');
  onboarding.append(text('code', '/yoke onboard'), document.createTextNode(' skill. During onboarding, your agent reviews your project and existing work, helps you write your strategy and choose what to tackle first, and configures what that work needs.'));
  const steering = text('p', 'It then begins an interactive ');
  const label = text('span', '', 'intro-steering');
  const icon = document.createElement('img');
  icon.src = data.steering_icon; icon.alt = '';
  label.append(icon, document.createTextNode('STEERING'));
  steering.append(label, document.createTextNode(' session that files work items in Yoke, launches CLI sessions in the background to staff them, orchestrates delivery, and tees up key decisions for you to make along the way.'));
  section.append(onboarding, steering, nodeLink(byId.get('page:setup'), 'More about installation and onboarding →'));
  article.append(section);
}
