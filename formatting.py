"""Helpers de formato compartidos entre bot.py y scheduler.py."""
import re

_BOLD_MD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def markdown_to_html(text: str) -> str:
    """Convierte Markdown bold (**texto**) a HTML (<b>texto</b>).

    Defensa por si Claude se le escapa el formato Markdown a pesar del system prompt.
    """
    return _BOLD_MD_RE.sub(r"<b>\1</b>", text)
