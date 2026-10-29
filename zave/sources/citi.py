"""Citi UAE card promotions - static, server-rendered HTML (observed 28 Oct 2026 via a text fetch).

Observed shape: <h2>Card Offers on Dining</h2> then repeated <h3>Merchant</h3> + headline + 'Expires On' + T&C bullets.
I could not inspect the live DOM from the build sandbox, so the splitter is deliberately structure-agnostic:
it walks headings in document order and gathers all text until the next h2/h3. If Citi changes class names, nothing breaks;
if they change heading levels, the 'zero blocks' alarm in cli.py fires.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag

from . import RawOffer

URL = "https://www.citibank.ae/credit-cards/promotions"
SOURCE = "citi_ae"
SECTION_RE = re.compile(r"^Card Offers on (.+)$", re.I)


def _text_until_next_heading(h: Tag) -> str:
    parts: list[str] = []
    for el in h.next_elements:
        if isinstance(el, Tag) and el.name in ("h2", "h3") and el is not h:
            break
        if isinstance(el, NavigableString) and el.strip():
            if el.parent and el.parent.name in ("script", "style"):
                continue
            if h in el.parents:          # the heading's own text is the title, not body
                continue
            parts.append(el.strip())
    return "\n".join(parts)


def parse(html: str, url: str = URL) -> list[RawOffer]:
    soup = BeautifulSoup(html, "lxml")
    out: list[RawOffer] = []
    section = ""
    for h in soup.find_all(["h2", "h3"]):
        t = h.get_text(" ", strip=True)
        if h.name == "h2":
            m = SECTION_RE.match(t)
            section = m.group(1) if m else ""
            continue
        if not section:      # h3s outside offer sections (footer, nav)
            continue
        body = _text_until_next_heading(h)
        if "Expires On" not in body and "valid until" not in body.lower():
            continue         # not an offer block
        out.append(RawOffer(SOURCE, url, "citi", t, f"{t}\n{body}", section))
    return out


def collect(fetcher) -> list[RawOffer]:
    return parse(fetcher.get(URL))
