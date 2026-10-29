"""Mashreq offers - JavaScript-rendered. NOT VERIFIED / NOT PART OF THE TESTED SLICE.

What I verified (28 Oct 2026, text fetch of the page): the initial HTML is a shell - filter chips (category, payment type,
emirate), a search box, two hero cards (Salary transfer, Early bird cashback) and the literal text 'No offers available'.
The offer cards are therefore injected by script after load.

What I could NOT verify from the build sandbox (no outbound access from the shell): the JSON endpoint behind it.
`discover` below opens the page in Playwright, records every JSON response, and prints the ones that look like offer lists, so the
real endpoint can be found in ~2 minutes locally. Once known, production should replay that endpoint with `requests`
(cheap, stable) rather than run a browser each crawl.

Run:  python -m zave.sources.mashreq_js        (needs: pip install playwright && playwright install chromium)
"""
from __future__ import annotations

import json
import sys

URL = "https://www.mashreq.com/en/uae/neo/offers/"


def discover(url: str = URL) -> None:
    from playwright.sync_api import sync_playwright

    from ..crawl import UA, PoliteFetcher

    if not PoliteFetcher()._allowed(url):
        sys.exit("robots.txt disallows this URL for our UA; stopping.")
    hits = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(user_agent=UA)

        def on_resp(r):
            if "json" in (r.headers.get("content-type") or ""):
                try:
                    body = r.json()
                except Exception:
                    return
                s = json.dumps(body)[:20000].lower()
                score = sum(k in s for k in ("offer", "merchant", "discount", "valid", "expiry", "title"))
                hits.append((score, r.url, len(s)))

        pg.on("response", on_resp)
        pg.goto(url, wait_until="networkidle")
        b.close()
    for score, u, n in sorted(hits, reverse=True)[:10]:
        print(f"score={score} bytes~{n}  {u}")


if __name__ == "__main__":
    discover()
