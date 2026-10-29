"""SQLite storage + merchant resolution + FTS5 index. One file DB, no services - right for the slice; production choice is in the design doc."""
from __future__ import annotations

import csv
import difflib
import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from .schema import Offer

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "zave.db"
REF = ROOT / "data" / "reference"

SCHEMA = """
CREATE TABLE IF NOT EXISTS merchants(
  merchant_id INTEGER PRIMARY KEY, canonical TEXT UNIQUE, norm_key TEXT, category TEXT, aliases TEXT);
CREATE TABLE IF NOT EXISTS card_products(
  product_id TEXT PRIMARY KEY, issuer TEXT, product_name TEXT, network TEXT, tier TEXT, card_type TEXT, verified INT, source_note TEXT);
CREATE TABLE IF NOT EXISTS offers(
  offer_id TEXT PRIMARY KEY, source TEXT, source_url TEXT, merchant_id INT, outlet TEXT, category TEXT, title TEXT,
  benefit_type TEXT, value REAL, cap_aed REAL, min_spend_aed REAL, valid_to TEXT, channel TEXT, promo_code TEXT,
  eligible_issuer TEXT, eligible_products TEXT, eligible_networks TEXT, card_types TEXT, eligibility_verified INT,
  exclusions TEXT, days_times TEXT, flags TEXT, confidence REAL, extraction_method TEXT,
  content_hash TEXT, first_seen TEXT, last_verified TEXT, status TEXT DEFAULT 'active', missed_runs INT DEFAULT 0, body TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS offers_fts USING fts5(offer_id UNINDEXED, merchant, aliases, title, category, outlet, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS review_queue(
  id INTEGER PRIMARY KEY, source TEXT, source_url TEXT, title TEXT, reason TEXT, raw_text TEXT, created TEXT, resolved INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS source_runs(
  id INTEGER PRIMARY KEY, source TEXT, ts TEXT, blocks INT, normalised INT, review INT);
CREATE TABLE IF NOT EXISTS app_metadata(
  key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

STOP = {"hypermarket", "restaurant", "restaurants", "llc", "the", "dubai", "uae", "hotel", "and", "at", "cafe", "store", "stores"}


def norm_key(name: str) -> str:
    t = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    toks = [w for w in t.split() if w not in STOP]
    return " ".join(toks) or t.strip()


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    seed_reference(c)
    return c


def seed_reference(c: sqlite3.Connection) -> None:
    if c.execute("SELECT COUNT(*) FROM card_products").fetchone()[0] == 0:
        with open(REF / "card_products.csv", newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                c.execute("INSERT OR IGNORE INTO card_products VALUES(?,?,?,?,?,?,?,?)",
                          (r["product_id"], r["issuer"], r["product_name"], r["network"], r["tier"], r["card_type"], int(r["verified"]), r["source_note"]))
    if c.execute("SELECT COUNT(*) FROM merchants").fetchone()[0] == 0:
        with open(REF / "merchants_seed.csv", newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                c.execute("INSERT OR IGNORE INTO merchants(canonical,norm_key,category,aliases) VALUES(?,?,?,?)",
                          (r["canonical"], norm_key(r["canonical"]), r["category"], r["aliases"]))
    c.commit()


def resolve_merchant(c: sqlite3.Connection, name: str, category: str) -> int:
    """alias/exact -> fuzzy(>=0.9) -> new. Fuzzy hits are logged by the caller via flags, not silently merged below 0.9."""
    key = norm_key(name)
    rows = c.execute("SELECT merchant_id, canonical, norm_key, aliases FROM merchants").fetchall()
    for r in rows:
        alias_keys = {norm_key(a) for a in (r["aliases"] or "").split("|") if a}
        if key == r["norm_key"] or key in alias_keys:
            return r["merchant_id"]
    best, best_r = 0.0, None
    for r in rows:
        s = difflib.SequenceMatcher(None, key, r["norm_key"]).ratio()
        if s > best:
            best, best_r = s, r
    if best_r is not None and best >= 0.9:
        return best_r["merchant_id"]
    cur = c.execute("INSERT INTO merchants(canonical,norm_key,category,aliases) VALUES(?,?,?,?)", (name.strip(), key, category, ""))
    return cur.lastrowid


def offer_id(o: Offer) -> str:
    return hashlib.sha1(f"{o.source}|{o.source_url}|{o.title}".encode()).hexdigest()[:16]


def upsert_offers(c: sqlite3.Connection, offers: list[Offer]) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stats = {"new": 0, "changed": 0, "unchanged": 0}
    seen_by_source: dict[str, set[str]] = {}
    for o in offers:
        oid = offer_id(o)
        seen_by_source.setdefault(o.source, set()).add(oid)
        mid = resolve_merchant(c, o.merchant_raw, o.category)
        prev = c.execute("SELECT content_hash, first_seen FROM offers WHERE offer_id=?", (oid,)).fetchone()
        if prev is None:
            stats["new"] += 1
        elif prev["content_hash"] != o.content_hash:
            stats["changed"] += 1
        else:
            stats["unchanged"] += 1
        row = (oid, o.source, o.source_url, mid, o.outlet, o.category, o.title, o.benefit_type.value, o.value, o.cap_aed, o.min_spend_aed,
               o.valid_to.isoformat() if o.valid_to else None, o.channel.value, o.promo_code, o.eligible_issuer,
               json.dumps(o.eligible_products), json.dumps(o.eligible_networks), json.dumps(o.card_types), int(o.eligibility_verified),
               json.dumps(o.exclusions), o.days_times, json.dumps(o.flags), o.confidence, o.extraction_method, o.content_hash,
               prev["first_seen"] if prev else now, now, "active", 0, o.raw_text)
        c.execute("INSERT OR REPLACE INTO offers VALUES(" + ",".join("?" * len(row)) + ")", row)
        m = c.execute("SELECT canonical, aliases FROM merchants WHERE merchant_id=?", (mid,)).fetchone()
        c.execute("DELETE FROM offers_fts WHERE offer_id=?", (oid,))
        c.execute("INSERT INTO offers_fts(offer_id,merchant,aliases,title,category,outlet) VALUES(?,?,?,?,?,?)",
                  (oid, m["canonical"], (m["aliases"] or "").replace("|", " "), o.title, o.category.replace("_", " "), o.outlet or ""))
    # offers that vanished from the page: count misses; withdraw after 2 consecutive misses (page-disappearance expiry)
    for src, ids in seen_by_source.items():
        for r in c.execute("SELECT offer_id, missed_runs FROM offers WHERE source=? AND status='active'", (src,)).fetchall():
            if r["offer_id"] not in ids:
                mr = r["missed_runs"] + 1
                c.execute("UPDATE offers SET missed_runs=?, status=? WHERE offer_id=?", (mr, "withdrawn" if mr >= 2 else "active", r["offer_id"]))
    c.commit()
    return stats


def log_review(c: sqlite3.Connection, raw, reason: str) -> None:
    c.execute("INSERT INTO review_queue(source,source_url,title,reason,raw_text,created) VALUES(?,?,?,?,?,?)",
              (raw.source, raw.source_url, raw.title, reason, raw.text[:4000], datetime.now(timezone.utc).isoformat(timespec="seconds")))
    c.commit()
