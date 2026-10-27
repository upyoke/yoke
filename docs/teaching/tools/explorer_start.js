/* Read-only view of the public-owned Getting started page. */
function renderGettingStarted() {
  const article = text('article', '', 'public-docs-intro');
  article.innerHTML = data.public_intro;
  for (const link of article.querySelectorAll('[data-public-page]')) {
    link.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      const page = byId.get('page:' + link.dataset.publicPage);
      if (!page) return;
      event.preventDefault(); choose(page);
    });
  }
  for (const button of article.querySelectorAll('[data-copy]')) {
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.copy);
        button.textContent = 'Copied';
      } catch {
        button.textContent = 'Select text to copy';
        const code = button.parentElement.querySelector('code');
        if (code) {
          const range = document.createRange(); range.selectNodeContents(code);
          const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
        }
      }
    });
  }
  world.append(article);
  notice.textContent = 'Getting started · Public docs';
}
