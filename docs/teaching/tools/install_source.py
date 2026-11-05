"""Read installation wording from its public documentation owner."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
INSTALL_DOC = 'docs/public/start/install.md'


def read_install(model):
    """Return the public install recipe, including its declared setup mode."""
    try:
        text = (REPO / INSTALL_DOC).read_text(encoding='utf-8')
        recipe = re.search(r'^```(?:bash|sh)\n(.+?)\n```', text, re.M | re.S)
        if recipe is None:
            raise ValueError('no shell installation recipe')
        command = recipe[1].splitlines()[0]
        explanation = text[recipe.end():].strip().split('\n\n', 1)[0]
        if not command.strip() or not explanation:
            raise ValueError('installation command or explanation is empty')
        return command, explanation
    except (OSError, UnicodeError, ValueError) as error:
        model.problem(
            'GUIDE_SOURCE_UNREADABLE', INSTALL_DOC,
            f'{error}; restore the public shell recipe and its explanation, then rebuild',
        )
        return '', ''
