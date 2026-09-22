"""Full abstracts from the NeurIPS and ICLR proceedings pages.

Scholar's ``AB`` is a search snippet, never the abstract: fragments joined by
ellipses, around the query terms. The proceedings abstract page for the same
record states the real one, and 1,220 of the 1,391 records that reach
Covidence carry a URL that names that page, or the PDF beside it.

Both hosts serve the same template:

    <meta name="citation_title" content="...">
    <h2 class="section-label">Abstract</h2>
    <p class="paper-abstract"><p>...</p>
    </p>

The cached payload is the extracted title and abstract, not the page. The
title is kept so that a claim is made only when the page is demonstrably the
record's own paper.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse

from ..cache import Cache
from ..models import Claim
from .semanticscholar import titles_match

HOSTS = frozenset({"proceedings.neurips.cc", "papers.nips.cc", "proceedings.iclr.cc"})

_PATH = re.compile(
    r"^(?P<prefix>/paper_files/paper/\d{4}/)(?:hash|file)/"
    r"(?P<sha>[0-9a-f]+)-(?:Abstract|Paper)-(?P<track>[A-Za-z_]+)\.(?:html|pdf)$"
)
_TITLE = re.compile(r'<meta\s+name="citation_title"\s+content="([^"]*)"', re.IGNORECASE)
_ABSTRACT = re.compile(r'<p class="paper-abstract">(.*?)</section>', re.IGNORECASE | re.DOTALL)
# Block boundaries become a space; inline tags (<i>, <sub>) vanish, so that
# "<i>k</i>-means" stays "k-means" rather than becoming "k -means".
_BLOCK = re.compile(r"</?(?:p|br|div|li|ul|ol)\b[^>]*>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_MATH = re.compile(r"\$[^$]*\$")
# Some pages escape twice ("caption &amp;amp; instruction"), so one unescape
# leaves "&amp;" behind: 6 of 1,220 pages. Only a complete, named-or-numeric
# entity is decoded again; a bare "&" in "R&D" is not an entity and survives.
_LEFTOVER_ENTITY = re.compile(r"&(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")


def abstract_page(url: str) -> str | None:
    """The abstract page a proceedings URL belongs to, or ``None``.

    A record may carry only the PDF. Its sibling ``hash/...-Abstract-...html``
    is the same paper by construction: the two differ in nothing but the
    directory, the word, and the extension.
    """
    parsed = urlparse(url)
    if parsed.netloc.lower() not in HOSTS:
        return None
    match = _PATH.match(parsed.path)
    if match is None:
        return None
    return (f"https://{parsed.netloc.lower()}{match['prefix']}hash/"
            f"{match['sha']}-Abstract-{match['track']}.html")


def one_line(text: str) -> str:
    """Whitespace collapsed to single spaces.

    RIS has no continuation lines that Covidence and venuetriage agree on, and
    the projection's safety argument rests on one value occupying one line.
    """
    return " ".join(text.split())


def extract(page: str) -> dict:
    """``{"title", "abstract"}`` from a proceedings page; either may be empty."""
    title = _TITLE.search(page)
    body = _ABSTRACT.search(page)
    return {
        "title": html.unescape(title.group(1)).strip() if title else "",
        "abstract": one_line(html.unescape(_TAG.sub("", _BLOCK.sub(" ", body.group(1))))) if body else "",
    }


def page_key(url: str) -> str:
    return f"proceedings:abstract:{url}"


class ProceedingsPageResolver:
    def __init__(self, cache: Cache) -> None:
        self.cache = cache

    def resolve(self, title: str, urls: list[str]) -> list[Claim]:
        """An abstract claim from the first page that is this record's paper."""
        pages = list(dict.fromkeys(p for p in map(abstract_page, urls) if p))
        for page in pages:

            def loader(page: str = page) -> dict:
                from ..http import get_text

                return extract(get_text(page))

            payload = self.cache.fetch(page_key(page), loader)
            abstract = _LEFTOVER_ENTITY.sub(lambda m: html.unescape(m.group(0)),
                                            payload.get("abstract") or "")
            if abstract and _same_paper(title, payload.get("title") or ""):
                return [Claim(field="abstract", value=abstract, source="proceedings_page",
                              tier=2, confidence=0.99, evidence=page)]
        return []


def _same_paper(record_title: str, page_title: str) -> bool:
    """``titles_match``, tolerating the TeX that Scholar drops from titles.

    The page says "$R^2$-Guard: ..."; Scholar's record says "-Guard: ...".
    The comparison is a prefix, so a formula at the start shifts every
    character after it -- measured on the first 125 pages, the only mismatch.
    """
    return titles_match(record_title, page_title) or titles_match(
        record_title, _MATH.sub("", page_title))
