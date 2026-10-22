"""The former overview opens the single teaching guide."""
from render_redirects import redirect


def index_page(views, intro):
    views['index.html'] = redirect('index.html', '')
