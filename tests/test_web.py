from zave import store
from zave.web import ensure_demo_data, meta_payload, offers_payload


def _db(tmp_path):
    c = store.connect(tmp_path / "web.db")
    assert ensure_demo_data(c)
    return c


def test_first_web_start_seeds_fixture_preview_only_when_empty(tmp_path):
    c = store.connect(tmp_path / "web.db")
    assert ensure_demo_data(c)
    count = c.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
    assert count > 0
    assert ensure_demo_data(c)
    assert c.execute("SELECT COUNT(*) FROM offers").fetchone()[0] == count


def test_offer_browse_search_and_wallet_filters(tmp_path):
    c = _db(tmp_path)
    all_offers = offers_payload(c, {})
    assert all_offers["total"] > 0

    searched = offers_payload(c, {"q": ["cinema"]})
    assert searched["total"] > 0
    assert all("cinema" in offer["merchant"].lower() or "cinema" in offer["title"].lower() for offer in searched["offers"])

    wallet = offers_payload(c, {"q": ["play"], "wallet": ["citi_other_credit"]})
    assert all(offer["eligible_issuer"] == "citi" for offer in wallet["offers"])


def test_web_filters_validate_inputs_and_meta_includes_wallet(tmp_path):
    c = _db(tmp_path)
    try:
        offers_payload(c, {"basket": ["-1"]})
        assert False, "Invalid basket amount should be rejected"
    except ValueError as exc:
        assert "between AED" in str(exc)
    meta = meta_payload(c, sample_data=True)
    assert meta["sample_data"] is True
    assert any(card["product_id"] == "hsbc_premier" for card in meta["cards"])
