"""Run: pytest -q   (offline; uses fixtures reconstructed from captured page text - see make_fixtures.py)"""
from datetime import date
from pathlib import Path

from zave import normalise as N
from zave import store
from zave.search import expected_saving, search
from zave.sources import citi, hsbc

FIX = Path(__file__).parent / "fixtures"


def _db(tmp_path):
    c = store.connect(tmp_path / "t.db")
    raws = citi.parse((FIX / "citi_promotions.html").read_text()) + hsbc.parse_list((FIX / "hsbc_special_offers_p1.html").read_text())
    offers = [o for r in raws if (o := N.normalise(r)[0])]
    store.upsert_offers(c, offers)
    return c, raws


def test_block_counts():
    assert len(citi.parse((FIX / "citi_promotions.html").read_text())) == 14       # nav/footer h3s are ignored
    assert len(hsbc.parse_list((FIX / "hsbc_special_offers_p1.html").read_text())) == 11


def test_displayed_expiry_beats_url_slug(tmp_path):
    c, raws = _db(tmp_path)
    careem = next(r for r in raws if r.title == "Careem")
    assert N.rules_extract(careem)["valid_to"] == date(2026, 12, 31)         # slug said 2024
    dg = next(r for r in raws if r.title == "District Gold")
    assert N.rules_extract(dg)["valid_to"] == date(2026, 11, 30)             # slug said 31-12-2026


def test_amount_not_confused_with_price():
    raw = next(r for r in citi.parse((FIX / "citi_promotions.html").read_text()) if r.title.startswith("dnata"))
    d = N.rules_extract(raw)
    assert d["min_spend_aed"] is None and d["promo_code"] == "CITIBANK"        # 'from AED 350 per person' is a price


def test_wallet_filters_issuer_and_product(tmp_path):
    c, _ = _db(tmp_path)
    today = date(2026, 10, 28)
    ids = lambda w, q: {r.merchant for r in search(c, q, w, today=today)}
    assert "Play DXB" not in ids(["citi_other_credit"], "play")                   # Ultima/Prestige-only
    assert "Play DXB" in ids(["citi_ultima"], "play")
    assert "Anantara Spa" not in ids(["citi_ultima"], "spa")                      # wrong issuer
    assert "Anantara Spa" in ids(["hsbc_premier"], "spa")


def test_expired_offers_are_hidden(tmp_path):
    c, _ = _db(tmp_path)
    assert not any(r.merchant == "Anantara Spa" for r in search(c, "anantara", [], today=date(2026, 11, 15)))


def test_ranking_cap_vs_uncapped():
    def row(**k):
        base = dict(benefit_type="percent", value=0, cap_aed=None, min_spend_aed=None)
        base.update(k)
        return base
    # the brief's example: 20% capped AED 100 vs 15% uncapped, at two basket sizes
    a, b = row(value=20, cap_aed=100), row(value=15)
    assert expected_saving(a, 300)[0] == 60 and expected_saving(b, 300)[0] == 45     # small basket: capped 20% wins
    assert expected_saving(a, 1000)[0] == 100 and expected_saving(b, 1000)[0] == 150 # big basket: uncapped 15% wins
    assert expected_saving(row(value=30, min_spend_aed=5000), 200)[0] == 0           # unreachable min spend


def test_removed_offer_withdrawn_after_two_misses(tmp_path):
    c, raws = _db(tmp_path)
    keep = [o for r in raws if (o := N.normalise(r)[0]) and r.title != "Careem"]
    store.upsert_offers(c, keep)
    assert c.execute("SELECT status FROM offers WHERE title LIKE 'Careem%'").fetchone()[0] == "active"
    store.upsert_offers(c, keep)
    assert c.execute("SELECT status FROM offers WHERE title LIKE 'Careem%'").fetchone()[0] == "withdrawn"


def test_llm_disagreement_goes_to_review(monkeypatch):
    raw = next(r for r in citi.parse((FIX / "citi_promotions.html").read_text()) if r.title == "NRTC Fresh")
    monkeypatch.setattr(N, "llm_extract", lambda r: {
        "merchant_raw": "NRTC Fresh", "category": "groceries", "benefit_type": "percent", "value": 12.0,   # wrong on purpose
        "min_spend_aed": 80, "valid_to": "2027-03-31", "confidence": 0.9, "uncertain_fields": []})
    o, why = N.normalise(raw, use_llm=True)
    assert why and "value" in why and o.confidence <= 0.4


def test_llm_agreement_raises_confidence(monkeypatch):
    raw = next(r for r in citi.parse((FIX / "citi_promotions.html").read_text()) if r.title == "NRTC Fresh")
    monkeypatch.setattr(N, "llm_extract", lambda r: {
        "merchant_raw": "NRTC Fresh", "category": "groceries", "benefit_type": "percent", "value": 10.0,
        "min_spend_aed": 80, "valid_to": "2027-03-31", "confidence": 0.8, "uncertain_fields": []})
    o, why = N.normalise(raw, use_llm=True)
    assert why is None and o.extraction_method == "rules+llm" and o.confidence >= 0.9
