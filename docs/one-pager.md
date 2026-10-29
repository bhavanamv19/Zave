# Zave
## Better value from the cards you already have

**A wallet-aware guide to Dubai card offers**

### The problem

Bank-card promotions are scattered across issuer sites and written in different formats. People have to search multiple pages, interpret fine print, check card eligibility, and work out whether a discount is worthwhile.

### The solution

Zave brings card offers into one searchable experience. Choose your card, search a merchant or category, enter a typical basket, and see eligible offers ranked by estimated AED value—with expiry, caveats, and a link back to the issuer.

### How it works

**Collect** public issuer pages → **Normalize** offer terms into one schema → **Validate** and queue ambiguous records → **Filter** by expiry and wallet → **Rank** by estimated value → **Verify** on the issuer page.

### What's working today

- Functional local browser prototype and CLI.
- Citi UAE and HSBC UAE parser paths with offline fixture data.
- SQLite offer store, FTS5 search, card filtering, expiry handling, and estimated-savings ranking.
- Explicit review flags for uncertain extraction and incomplete eligibility.
- **12 offline tests passing.**

### What it is not

This is a working slice, not a live or production offers service. The fixtures reconstruct rendered issuer text; live DOM parsing has not been verified. HSBC card eligibility may require checking offer details. Value estimates use explicit assumptions and are illustrative. Users must confirm current terms with the issuer.

### Demo and submission links

- **Prototype:** `http://127.0.0.1:8000` (local only; run `python -m zave web`)
- **GitHub repository:** pending; no remote is configured yet.
- **60-second recording:** `prototype-demo.webm` (local file, recorded from the prototype).
- **Design document:** `design-document.pdf`
- **Product spec:** `product-spec.pdf`

### Next milestone

Validate a permitted live fetch, build a blind 150-offer quality set, gate accuracy before labeling data verified, then decide deployment and monitoring requirements.
