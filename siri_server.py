"""Servidor aiohttp con endpoint /ingest para que Siri pueda hablar al bot."""
import re

_TAG_RE = re.compile(r"<[^>]+>")


def html_to_plain(text: str) -> str:
    """Quita tags HTML simples y desescapa entidades básicas. Para que Siri pueda leer la respuesta."""
    plain = _TAG_RE.sub("", text)
    plain = plain.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return plain
