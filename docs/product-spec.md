# Zave: Product specification

**MVP working slice · Dubai, UAE · 29 October 2026**

## Product intent

Help Dubai cardholders find issuer offers they can plausibly use, understand the conditions, and compare estimated value without browsing multiple bank sites.

## Target user

A Dubai resident or visitor who holds one or more bank cards, shops or dines locally, and wants to find a relevant offer without manually checking every issuer's promotions page.

### User need

> When I am choosing where to shop or eat, show me current offers that fit the card I have, explain the likely value and conditions, and let me verify the offer with the issuer.

## MVP scope

### Included in the working slice

- Citi UAE and HSBC UAE offer-list parsing.
- Shared offer model with benefit, eligibility, validity, channel, source, and confidence fields.
- SQLite persistence, merchant aliases, FTS5 search, review queue, and withdrawal after repeated source misses.
- Search by text; filter by category and card product/issuer.
- Typical-basket input and estimated AED-value ranking.
- Offer source links, expiry cues, and caveats.
- Offline fixture mode so the browser prototype can be demonstrated without a live bank site.
- CLI for collect, normalize, search, report, evaluation, and demo operations.

### Explicitly not included

- A verified real-time feed, broad bank coverage, or production hosting.
- User accounts, card-number collection, payments, or personal financial advice.
- Confirmed eligibility for every HSBC list-page offer without detail-page collection.
- Arabic-language offers, PDF terms extraction, or full pagination.
- Automated LLM extraction by default; the optional Groq path requires an API key.
- Affiliate attribution, redemption, or bank integrations.

## Main flow

1. User opens the offers page.
2. User searches for a merchant or chooses a category.
3. User optionally selects one or more card products.
4. User optionally enters a typical basket amount in AED.
5. Zave filters ineligible/expired records and ranks the remainder by an illustrative value score.
6. User reviews expiry and caveats, then opens the issuer page to confirm terms.

## Functional requirements and acceptance criteria

| ID | Requirement | Acceptance |
|---|---|---|
| FR-1 | Parse issuer pages into a shared offer model | Citi and HSBC fixture blocks normalize into validated records; invalid fields do not silently become trusted offers. |
| FR-2 | Search offers | A text query returns matching active offers; blank search can browse available active offers. |
| FR-3 | Respect wallet selection | With a selected card, results exclude offers belonging to a different issuer or incompatible product where eligibility is known. Uncertain eligibility is disclosed. |
| FR-4 | Apply expiry and lifecycle | Expired/withdrawn offers do not appear; an offer missing twice is withdrawn. |
| FR-5 | Estimate value | Basket-based estimate reflects percent/fixed/cashback/cap/minimum spend and the documented heuristic assumptions. |
| FR-6 | Communicate uncertainty | UI surfaces issuer, source link, expiry, missing eligibility, and caveats; user is told to confirm terms. |
| FR-7 | Work offline for a demo | An empty local database loads fixture offers, but existing records are not overwritten. |
| FR-8 | Reject invalid basket values | API accepts AED 10–50,000 only and returns a clear validation error outside that range. |

## Product principles

- **Source-first:** every offer points back to its issuer page.
- **No false precision:** values are estimates, and uncertain extraction/eligibility remains visible.
- **Wallet filtering, not card storage:** the prototype needs only product IDs for filtering, never a card number.
- **Graceful offline demo:** use clearly labeled fixtures rather than failing or claiming live coverage.
- **Quality before breadth:** add sources only when policy, freshness, and extraction quality can be checked.

## Success measures for a next validation phase

These are proposed targets, not measured outcomes:

- At least 95% exact accuracy on benefit type and expiry, and 90% on value/cap/minimum spend, on a blind source-stratified set before labeling offers verified.
- At least 90% of a small usability-test cohort can find a relevant offer and identify its eligibility in under one minute.
- No expired or withdrawn offer appears in the active result set under tested boundary conditions.
- Every surfaced offer has a source URL; uncertain terms are visibly marked.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Issuer page layout changes or blocks collection | Check block counts, alert on sharp drops, retain snapshots, and review before trusting new data. |
| Offer terms are stale or parsed incorrectly | Display last-verified context where available, expiry, confidence/review state, and issuer source. Build blind evaluation before production. |
| Card eligibility is ambiguous | Preserve unknown status; avoid claiming a match and direct user to the T&Cs. |
| Value estimates create false expectations | Label estimates illustrative; keep assumptions explicit and link to source terms. |
| Source policies restrict automated collection | Review robots and terms before live operation; use conservative request pacing and no login. |
| Public demo exposes an unfinished service | Keep the current app local until deployment, privacy, security, and monitoring requirements are defined. |

## Current status

The functional slice is implemented and its offline test suite passes (**12 tests**). It is not live-validated; the fixtures reconstruct rendered text and do not prove the production DOM. The app is available at `http://127.0.0.1:8000` only on the developer's machine. A public deployment and public repository link remain to be configured.
