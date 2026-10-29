"""Polite fetcher: identifies itself, honours robots.txt, rate-limits, caches raw HTML, never logs in."""
from __future__ import annotations

import hashlib
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import requests

UA = "ZaveOffersBot-Assignment/0.1 (+mailto:bhavanam.23.becs@acharya.ac.in; research prototype, low-rate)"
MIN_DELAY_S = 3.0
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


class RobotsBlocked(Exception):
    pass


class PoliteFetcher:
    def __init__(self, delay: float = MIN_DELAY_S, cache: bool = True):
        self.delay = delay
        self.cache = cache
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last: dict[str, float] = {}
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})

    def _allowed(self, url: str) -> bool:
        host = urlparse(url)
        base = f"{host.scheme}://{host.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.s.get(base + "/robots.txt", timeout=15)
                # 4xx => no robots file => allowed per RFC 9309; 5xx => treat as disallow (be safe)
                if r.status_code >= 500:
                    rp.parse(["User-agent: *", "Disallow: /"])
                elif r.status_code >= 400:
                    rp.parse([])
                else:
                    rp.parse(r.text.splitlines())
            except requests.RequestException:
                rp.parse(["User-agent: *", "Disallow: /"])
            self._robots[base] = rp
        return self._robots[base].can_fetch(UA, url)

    def get(self, url: str) -> str:
        if not self._allowed(url):
            raise RobotsBlocked(url)
        host = urlparse(url).netloc
        wait = self.delay - (time.time() - self._last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        r = self.s.get(url, timeout=30)
        self._last[host] = time.time()
        r.raise_for_status()
        if self.cache:
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            name = hashlib.sha1(url.encode()).hexdigest()[:12] + ".html"
            (RAW_DIR / name).write_text(r.text, encoding="utf-8")
        return r.text
