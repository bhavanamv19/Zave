"""HSBC UAE credit/debit card special offers - server-rendered list, 12 per page, Dubai filter (57 offers seen on 28 Oct 2026).

List pages: /credit-cards/special-offers/ then /credit-cards/special-offers.dubai.all-categories.page-N/
Each card links to a detail page whose slug encodes merchant, benefit and expiry; the list shows merchant, headline, 'Expires <date>'.
Detail pages (T&Cs, card eligibility) are fetched only with details=True because that is +57 requests.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import RawOffer

BASE = "https://www.hsbc.ae"
LIST_URL = BASE + "/credit-cards/special-offers/"
PAGE_URL = BASE + "/credit-cards/special-offers.dubai.all-categories.page-{n}/"
SOURCE = "hsbc_ae"
OFFER_LINK = re.compile(r"/credit-cards/special-offers/[a-z0-9\-]+/?$", re.I)
CARD_TEXT = re.compile(r"Offer\s+\d+\s+of\s+\d+\s+(.*)", re.S)


def parse_list(html: str, url: str = LIST_URL) -> list[RawOffer]:
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not OFFER_LINK.search(href) or href.rstrip("/").endswith("special-offers"):
            continue
        full = urljoin(BASE, href)
        if full in seen:
            continue
        seen.add(full)
        # the visible card text may sit inside the anchor or in its parent card; take the larger of the two
        txt = a.get_text("\n", strip=True)
        parent = a.find_parent(["li", "article", "div"])
        ptxt = parent.get_text("\n", strip=True) if parent else ""
        text = ptxt if len(ptxt) > len(txt) and len(ptxt) < 600 else txt
        text = CARD_TEXT.sub(r"\1", text, count=1)
        lines = [l for l in text.split("\n") if l.strip()]
        if len(lines) < 2:
            continue
        out.append(RawOffer(SOURCE, full, "hsbc", lines[0], "\n".join(lines), "all", {"slug": full.rstrip("/").split("/")[-1]}))
    return out


def parse_detail(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main") or soup
    for t in main(["script", "style", "nav", "header", "footer"]):
        t.decompose()
    return "\n".join(s for s in main.stripped_strings)


def collect(fetcher, pages: int = 5, details: bool = False) -> list[RawOffer]:
    offers = parse_list(fetcher.get(LIST_URL))
    for n in range(2, pages + 1):
        offers += parse_list(fetcher.get(PAGE_URL.format(n=n)), PAGE_URL.format(n=n))
    # de-dup by url (page 1 can repeat)
    uniq = {o.source_url: o for o in offers}
    offers = list(uniq.values())
    if details:
        for o in offers:
            o.text += "\n--- detail ---\n" + parse_detail(fetcher.get(o.source_url))
    return offers
