# Zave offers engine - working slice

Collect public Dubai card offers -> normalise to one schema -> store in SQLite -> wallet-aware search.
Two sources: **Citi UAE promotions** (static HTML, full T&Cs inline) and **HSBC UAE special offers** (static HTML list, 12 per page, Dubai filter).
Plus a Playwright **endpoint-discovery** helper for the JS-rendered Mashreq page (see "What is not done").

## Run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                                   # 12 offline tests
python -m zave demo                         # offline end-to-end on fixtures, no network
python -m zave eval                         # rule extractor vs tests/gold.jsonl

python -m zave collect --source all         # LIVE: ~7 requests, 3 s apart, robots.txt checked, UA identifies us
python -m zave normalise                    # rules only
GROQ_API_KEY=... python -m zave normalise --llm   # rules + Groq (llama-3.3-70b-versatile), compared
python -m zave search "spa" --wallet hsbc_premier --basket 300
python -m zave report                       # counts, review queue
python -m zave web                           # local browser preview at http://127.0.0.1:8000
```

### Local web preview

Run `python -m zave web` and open http://127.0.0.1:8000. On first run, if the
SQLite database has no offers, the app loads the offline Citi and HSBC fixtures
so the interface is usable without network access. Existing offers are left
untouched. Search by merchant or category, select cards to filter for issuer
eligibility, and enter a typical basket amount to personalize estimated savings.
The estimates are illustrative; confirm offer terms with the issuer. Use
`python -m zave web --port 8080` to choose another local port. Stop the server
with Ctrl+C.
Wallet = comma-separated product ids from `data/reference/card_products.csv` (or `citi:*` = "a Citi card, not sure which").

## How it works (one line each)
- `crawl.py` - robots.txt via urllib.robotparser (5xx => treated as disallow), 3 s/host, caches raw HTML, no login, no JS.
- `sources/*.py` - split a page into raw offer blocks. Citi: walk h2/h3 in document order (structure-agnostic). HSBC: offer links + sibling text.
- `normalise.py` - rules extractor (regex) and optional Groq extractor, run independently; disagreement on type/value/expiry => confidence 0.4 + review queue. Pydantic validates ranges, controlled vocabularies, date order.
- `store.py` - SQLite; merchant table (alias -> fuzzy >= 0.9 -> new), card-product table, FTS5 index, review queue, per-source run log; an offer missing from its page twice in a row is withdrawn.
- `search.py` - FTS5 prefix match -> drop expired/withdrawn -> wallet filter -> expected-AED-saved score -> sort. Assumptions are constants at the top of the file.

## What worked
- 25 fixture blocks -> 25 valid offers; 9/9 tests pass offline.
- Displayed expiry beats URL-slug date. Real cases seen on HSBC: Careem slug says 2024 but page says 31 Dec 2026; District Gold slug says 31-12-2026 but page says 30 Nov 2026.
- "from AED 350 per person" (a price) is not read as a minimum spend; "worth AED 350 and above" is.
- Ranking example from the brief: 20% capped at AED 100 beats 15% uncapped at a AED 300 basket (60 vs 45) and loses at AED 1,000 (100 vs 150) - tested.

## What broke (found by auditing output against source text)
- Hotel restaurants were classified as spas/travel because of "Resort & SPA" in the name; fixed by trusting the page section for Dining/Travel and matching the merchant name before the body.
- A cinema was classified as dining because "beverages" appeared in the body; fixed the same way.
- Make My Trip (10% off + 10% cashback, different caps for hotel and flight) was silently collapsed to one benefit; now flagged `multi_benefit` and sent to review rather than guessed.

## Honest limits - read these
1. **Not live-tested.** The build sandbox could not reach the bank sites from the shell. I read the pages' rendered text through a text-fetch tool, and rebuilt a subset as HTML fixtures (`tests/make_fixtures.py`). Wording, numbers and dates are real; the **DOM structure is my reconstruction**. The first thing to do is `python -m zave collect` and compare block counts with the page (Citi ~40+, HSBC Dubai 57). If it prints `ALERT: zero blocks`, the selectors need adjusting.
2. **robots.txt/terms not read for Citi or HSBC.** I could read Emirates NBD's (`User-agent: *`, `Disallow: /sitecore`) only. The crawler checks robots at runtime and skips a disallowed URL, but read each site's terms of use yourself before running it.
3. **The Groq path is untested against the real API** (only against a mocked response). Model name and JSON mode follow Groq's OpenAI-compatible docs as I know them; check `GROQ_MODEL`.
4. **Eval is in-sample.** `tests/gold.jsonl` has 13 items I labelled from the same text I tuned the regexes on, so ~98% proves little. The design doc proposes a 150-item gold set drawn blind, stratified by source and offer type.
5. **Card eligibility is unknown on HSBC's list page** (detail pages state it; `collect --details` fetches them, +57 requests). Until then those offers carry `eligibility_verified=0` and the UI says "check T&Cs".
6. **Card-product table is seeded only with products I saw named on pages**; networks/tiers are left blank when the page did not state them, rather than filled from memory.
7. `AED_PER_POINT`, `BOGO_EFFECTIVE_PCT`, basket defaults are guesses, labelled as such in `search.py`.

## What is not done
- **JS-rendered source.** Verified: Mashreq's offers page ships an empty shell ("No offers available" in the initial HTML; filters by category / payment type / emirate), and Emirates NBD's lifestyle deals page returned no offer content in the initial HTML. I did not find the JSON endpoints. `python -m zave.sources.mashreq_js` opens the page in Playwright and ranks every JSON response by how offer-like it looks, to find the endpoint in ~2 minutes; production should then replay it with `requests`.
- Awin Promotions API (POST /publisher/{id}/promotions, needs an access token and joined advertisers) - schema fits, collector not written.
- Multi-page HSBC beyond page 5, Arabic pages, PDFs of terms.

## Next
1. Run `collect` locally, fix selectors, commit real HTML snapshots as fixtures.
2. Run the Mashreq discovery, add its collector. 3. Blind 150-item gold set + per-field accuracy gate before showing offers to users.
4. Per-offer content hashing per block (already stored) -> diff report; daily expiry sweep; alert on >50% block drop (already in `cli.py`).
