"""Wallet-aware search + 'best for you' ranking.

Pipeline: query -> FTS5 candidates (merchant, alias, title, category) -> hard filters (active, not expired, wallet-eligible)
          -> expected-AED-saved score for a basket -> sort -> explain.
All assumptions are constants at the top so they can be argued with, not buried.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

# ---- assumptions (guesses, labelled as such in the design doc) ----
BOGO_EFFECTIVE_PCT = 25.0       # half the time you'd buy a pair; a free second item then saves ~50% -> ~25% of basket
INSTALMENT_CONVENIENCE_PCT = 0.5  # 0% plan is cash-flow value, not savings; scored as a token 0.5% so it never outranks real money off
CASHBACK_RELIABILITY = 0.9      # cashback is later and can fail to credit
AED_PER_POINT = 0.01            # placeholder; Smiles/SHARE/Skywards values must be set per programme
UPSELL_FACTOR = 0.5             # offer needing more spend than the basket: count half of the saving at the required spend
UPSELL_MAX_RATIO = 2.0          # ... but only if min spend <= 2x basket; beyond that it is parked at the bottom
DEFAULT_BASKETS = {"groceries": 250, "dining": 200, "fashion": 400, "attractions": 300, "kids": 300, "entertainment": 120,
                   "travel_hotels": 1200, "beauty_wellness": 250, "online_shopping": 200, "jewellery": 2000, "other": 200}


@dataclass
class Result:
    offer_id: str
    merchant: str
    title: str
    category: str
    expected_saving: float
    score: float
    valid_to: str | None
    days_left: int | None
    why: str
    caveats: list[str] = field(default_factory=list)
    source_url: str = ""
    eligibility: str = ""


def expected_saving(o: sqlite3.Row, basket: float) -> tuple[float, list[str]]:
    """Dirhams saved for a basket (AED), plus caveats. Pure function of offer + basket."""
    bt, v, cap, mn = o["benefit_type"], o["value"], o["cap_aed"], o["min_spend_aed"]
    notes: list[str] = []
    spend, factor = basket, 1.0
    if mn and basket < mn:
        if mn <= UPSELL_MAX_RATIO * basket:
            spend, factor = mn, UPSELL_FACTOR
            notes.append(f"needs AED {mn:,.0f} spend (you usually spend ~{basket:,.0f})")
        else:
            notes.append(f"min spend AED {mn:,.0f} is far above a typical basket")
            return 0.0, notes
    if bt == "percent":
        s = spend * (v or 0) / 100
    elif bt == "cashback":
        s = spend * (v or 0) / 100 * CASHBACK_RELIABILITY
        notes.append("cashback is credited later")
    elif bt == "fixed":
        s = v or 0
    elif bt == "bogo":
        s = spend * BOGO_EFFECTIVE_PCT / 100
        notes.append("value assumes you'd buy a pair")
    elif bt == "instalment":
        s = spend * INSTALMENT_CONVENIENCE_PCT / 100
        notes.append("0% plan: no discount, spreads payment")
    elif bt == "points":
        s = spend * (v or 0) * AED_PER_POINT
    else:  # perk
        s = 0.0
        notes.append("non-cash perk")
    if cap is not None and bt in ("percent", "cashback") and s > cap:
        s = cap * (CASHBACK_RELIABILITY if bt == "cashback" else 1.0)
        notes.append(f"capped at AED {cap:,.0f}")
    return s * factor, notes


def _fts_query(q: str) -> str:
    toks = [t for t in re.findall(r"[a-z0-9]+", q.lower()) if len(t) > 1]
    return " OR ".join(f'"{t}"*' for t in toks)


def wallet_issuers(c: sqlite3.Connection, wallet: list[str]) -> dict[str, set[str]]:
    """wallet = product_ids (citi_ultima) or 'issuer:*' for 'a card from this bank, don't know which'."""
    out: dict[str, set[str]] = {}
    for w in wallet:
        if w.endswith(":*"):
            out.setdefault(w[:-2], set()).add("*")
            continue
        r = c.execute("SELECT issuer FROM card_products WHERE product_id=?", (w,)).fetchone()
        if r:
            out.setdefault(r["issuer"], set()).add(w)
    return out


def eligible(o: sqlite3.Row, wl: dict[str, set[str]]) -> tuple[bool, str]:
    if not wl:
        return True, "no wallet set"
    prods = wl.get(o["eligible_issuer"])
    if not prods:
        return False, ""
    needed = json.loads(o["eligible_products"] or "[]")
    if needed and "*" not in prods and not (set(needed) & prods):
        return False, ""
    if needed and "*" in prods and not (set(needed) & prods):
        return True, "check your card: offer is limited to " + ", ".join(needed)
    return True, ("matches your card" if o["eligibility_verified"] else "bank page doesn't state which cards - check T&Cs")


def search(c: sqlite3.Connection, query: str, wallet: list[str] | None = None, basket: float | None = None,
           today: date | None = None, limit: int = 10) -> list[Result]:
    today = today or date.today()
    q = _fts_query(query)
    if q:
        rows = c.execute(
            "SELECT o.*, m.canonical AS merchant, bm25(offers_fts, 0, 5.0, 3.0, 2.0, 1.0, 0.5) AS rank "
            "FROM offers_fts f JOIN offers o ON o.offer_id=f.offer_id JOIN merchants m ON m.merchant_id=o.merchant_id "
            "WHERE offers_fts MATCH ? AND o.status='active' ORDER BY rank LIMIT 200", (q,)).fetchall()
    else:
        rows = c.execute(
            "SELECT o.*, m.canonical AS merchant, 0 AS rank "
            "FROM offers o JOIN merchants m ON m.merchant_id=o.merchant_id "
            "WHERE o.status='active' ORDER BY o.last_verified DESC LIMIT 200").fetchall()
    wl = wallet_issuers(c, wallet or [])
    out: list[Result] = []
    for o in rows:
        if o["valid_to"] and date.fromisoformat(o["valid_to"]) < today:
            continue                                  # hard expiry
        ok, elig = eligible(o, wl)
        if not ok:
            continue
        b = basket or DEFAULT_BASKETS.get(o["category"], 200)
        saving, notes = expected_saving(o, b)
        days_left = (date.fromisoformat(o["valid_to"]) - today).days if o["valid_to"] else None
        if days_left is None:
            notes.append("no expiry published")
        elif days_left <= 7:
            notes.append(f"ends in {days_left} day{'s' if days_left != 1 else ''}")
        # freshness + extraction confidence discount: stale or doubtful data must not win on paper savings
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(o["last_verified"])).days
        fresh = 1.0 if age <= 2 else 0.9 if age <= 7 else 0.7
        score = saving * fresh * min(1.0, 0.5 + o["confidence"] / 2)
        if o["channel"] == "online":
            notes.append("online only")
        elif o["channel"] == "in_store":
            notes.append("in-store only")
        out.append(Result(o["offer_id"], o["merchant"], o["title"], o["category"], round(saving, 1), round(score, 2),
                          o["valid_to"], days_left, f"~AED {saving:,.0f} saved on a AED {b:,.0f} basket", notes, o["source_url"], elig))
    # ties (and zero-saving perks): sooner-ending first - urgency is the tie-breaker, not a score boost
    out.sort(key=lambda r: (-r.score, r.days_left if r.days_left is not None else 9999))
    return out[:limit]
