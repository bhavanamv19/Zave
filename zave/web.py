"""Local web interface for browsing and searching offers."""
from __future__ import annotations

import json
import logging
import mimetypes
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import normalise, store
from .schema import CATEGORIES
from .search import search
from .sources import citi, hsbc

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
WEB_ROOT = Path(__file__).resolve().parent / "static"
LOGGER = logging.getLogger("zave.web")

CATEGORY_LABELS = {
    "attractions": "Attractions",
    "automotive": "Automotive",
    "beauty_wellness": "Beauty & wellness",
    "dining": "Dining",
    "electronics": "Electronics",
    "entertainment": "Entertainment",
    "fashion": "Fashion",
    "groceries": "Groceries",
    "health": "Health",
    "jewellery": "Jewellery",
    "kids": "Kids & family",
    "online_shopping": "Online shopping",
    "other": "Other",
    "services": "Services",
    "travel_hotels": "Travel & hotels",
}


def ensure_demo_data(c) -> bool:
    """Load fixture offers for first-run preview only; never mix them into an existing database."""
    if c.execute("SELECT COUNT(*) FROM offers").fetchone()[0]:
        marker = c.execute("SELECT value FROM app_metadata WHERE key='fixture_preview'").fetchone()
        return bool(marker and marker["value"] == "1")
    raws = citi.parse((FIXTURES / "citi_promotions.html").read_text(encoding="utf-8"))
    raws += hsbc.parse_list((FIXTURES / "hsbc_special_offers_p1.html").read_text(encoding="utf-8"))
    offers = []
    for raw in raws:
        offer, reason = normalise.normalise(raw)
        if offer is not None:
            offers.append(offer)
        if reason:
            store.log_review(c, raw, reason)
    store.upsert_offers(c, offers)
    c.execute("INSERT OR REPLACE INTO app_metadata(key, value) VALUES('fixture_preview', '1')")
    c.commit()
    return bool(offers)


def offers_payload(c, params: dict[str, list[str]]) -> dict:
    query = params.get("q", [""])[0].strip()[:120]
    category = params.get("category", [""])[0]
    if category and category not in CATEGORIES:
        raise ValueError("Unknown offer category")

    wallet = [item for value in params.get("wallet", []) for item in value.split(",") if item]
    basket_values = params.get("basket", [])
    basket = None
    if basket_values and basket_values[0]:
        try:
            basket = float(basket_values[0])
        except ValueError as exc:
            raise ValueError("Basket amount must be a number") from exc
        if not 10 <= basket <= 50000:
            raise ValueError("Basket amount must be between AED 10 and AED 50,000")

    results = search(c, query, wallet, basket, limit=200)
    if category:
        results = [result for result in results if result.category == category]
    if len(results) > 60:
        results = results[:60]
    ids = [result.offer_id for result in results]
    extra_by_id = {}
    if ids:
        placeholders = ",".join("?" for _ in ids)
        rows = c.execute(
            f"SELECT offer_id, benefit_type, value, cap_aed, channel, eligible_issuer, promo_code "
            f"FROM offers WHERE offer_id IN ({placeholders})", ids,
        ).fetchall()
        extra_by_id = {row["offer_id"]: dict(row) for row in rows}

    offers = []
    for result in results:
        item = result.__dict__.copy()
        item.update(extra_by_id[result.offer_id])
        item["category_label"] = CATEGORY_LABELS.get(result.category, "Other")
        offers.append(item)
    return {"offers": offers, "total": len(offers)}


def meta_payload(c, sample_data: bool) -> dict:
    cards = [
        dict(row)
        for row in c.execute(
            "SELECT product_id, issuer, product_name, card_type FROM card_products ORDER BY issuer, product_name"
        )
    ]
    active = c.execute(
        "SELECT COUNT(*) FROM offers WHERE status='active' AND (valid_to IS NULL OR valid_to >= ?)",
        (date.today().isoformat(),),
    ).fetchone()[0]
    issuers = c.execute(
        "SELECT COUNT(DISTINCT eligible_issuer) FROM offers WHERE status='active'"
    ).fetchone()[0]
    return {
        "cards": cards,
        "active_offers": active,
        "issuers": issuers,
        "open_reviews": c.execute("SELECT COUNT(*) FROM review_queue WHERE resolved=0").fetchone()[0],
        "sample_data": sample_data,
    }


class RequestHandler(BaseHTTPRequestHandler):
    db_path = store.DB_PATH
    sample_data = False

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict, status: int = 200) -> None:
        self._send(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            c = store.connect(self.db_path)
            try:
                params = parse_qs(parsed.query)
                if parsed.path == "/api/meta":
                    self._json(meta_payload(c, self.sample_data))
                elif parsed.path == "/api/offers":
                    self._json(offers_payload(c, params))
                else:
                    self._json({"error": "API route not found"}, 404)
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
            except Exception:
                LOGGER.exception("Request failed for %s", parsed.path)
                self._json({"error": "The request could not be completed"}, 500)
            finally:
                c.close()
            return

        if parsed.path not in ("/", "/index.html"):
            self._send(b"Not found", "text/plain; charset=utf-8", 404)
            return
        page = (WEB_ROOT / "index.html").read_bytes()
        self._send(page, mimetypes.guess_type("index.html")[0] + "; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:
        LOGGER.info("%s - %s", self.address_string(), fmt % args)


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    c = store.connect()
    try:
        sample_data = ensure_demo_data(c)
    finally:
        c.close()
    handler = type("ZaveRequestHandler", (RequestHandler,), {"sample_data": sample_data})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Zave is ready at http://{host}:{port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Zave.")
    finally:
        server.server_close()
