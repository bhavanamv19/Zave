"""Raw offer text -> canonical Offer.

Two extractors that are run independently and compared:
  1. rules  - regexes tuned on the two sources; fast, free, deterministic; the baseline.
  2. llm    - Groq (OpenAI-compatible endpoint, JSON mode). Optional; needs GROQ_API_KEY.
When both run and disagree on benefit type, value, or expiry, confidence drops and the offer goes to the review queue.
When neither can produce a valid Offer, the raw block goes to the review queue untouched (nothing is silently dropped).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import date, datetime

import requests
from pydantic import ValidationError

from .schema import CATEGORIES, TIERS, BenefitType, Channel, Offer
from .sources import RawOffer

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}

# ---------- helpers ----------

def _flat(t: str) -> str:
    return re.sub(r"\s+", " ", t.replace("–", "-").replace("’", "'")).strip()


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_date(text: str) -> date | None:
    """Prefer the explicit 'Expires' statement; the URL slug date is NOT trusted (see HSBC District Gold / Careem)."""
    t = _flat(text)
    m = re.search(r"Expires On:?\s*(\d{1,2})/(\d{1,2})/(\d{4})", t, re.I)       # Citi: MM/DD/YYYY
    if m:
        mo, d, y = map(int, m.groups())
        return date(y, mo, d)
    m = re.search(r"Expires\s+(?:on\s+)?(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", t, re.I)  # HSBC: 31 December 2026
    if m and m.group(2).lower() in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(r"(?:valid|offer valid)\s+until\s+([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", t, re.I)
    if m and m.group(1).lower() in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    m = re.search(r"valid\s+until\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})", t, re.I)
    if m and m.group(2).lower() in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    return None


CATEGORY_RULES = [
    ("dining", r"\b(restaurant|bar\b|cafe|café|lounge|dining|bbq|noodle|pastr|beverages|taste|grill|kitchen|pizza|bistro|brasserie)"),
    ("beauty_wellness", r"\b(spa|salon|gym|health club|fitness|treatments|massage|wellness|beauty|aesthetic|clinic)"),
    ("jewellery", r"\b(jewel|gold|diamond|damas)"),
    ("groceries", r"\b(hypermarket|supermarket|grocery|groceries|fresh)\b"),
    ("fashion", r"\b(fashion|apparel|styli|clothing|shoes)\b"),
    ("kids", r"\b(kids|kidzania|nursery|koala|orange wheels|orange hub|birthday part)"),
    ("attractions", r"\b(park|aquarium|burj|ice rink|ticket|coaster|the view|adventure|img |play dxb|yacht)"),
    ("entertainment", r"\b(cinema|movie|entertainment|immersiv|theatre|concert|membership)"),
    ("travel_hotels", r"\b(hotel|resort|flight|travel|stay|booking|roaming|sim card|airline|dnata|air arabia)"),
    ("online_shopping", r"\b(fnp|noon|amazon|online)\b"),
    ("automotive", r"\b(automotive|car wash|valet|tyre)"),
    ("services", r"\b(careem|ride|traffic fines|insurance)"),
]
SECTION_MAP = {"dining": "dining", "travel": "travel_hotels", "entertainment": "entertainment", "shopping": "online_shopping",
               "lifestyle": "beauty_wellness"}


def categorise(title: str, text: str, section: str) -> tuple[str, list[str]]:
    """Order matters: (1) merchant name keywords, (2) page section when it is unambiguous (Dining/Travel), (3) body keywords, (4) section, (5) other.
    Body-first was wrong: 'Resort & SPA' in a hotel restaurant's name made it a spa; 'beverages' made a cinema a restaurant."""
    t = title.lower()
    for cat, rx in CATEGORY_RULES:
        if re.search(rx, t):
            if section.lower() == "dining" and cat in ("beauty_wellness", "travel_hotels"):
                break                    # a restaurant inside a hotel/resort is dining
            return cat, []
    sec = SECTION_MAP.get(section.lower())
    if sec in ("dining", "travel_hotels"):
        return sec, ["cat_from_section"]
    body = text[:300].lower()
    for cat, rx in CATEGORY_RULES:
        if re.search(rx, body):
            return cat, ["cat_from_body"]
    if sec:
        return sec, ["cat_from_section"]
    return "other", ["cat_default"]


def split_merchant(title: str) -> tuple[str, str | None]:
    t = _flat(title)
    parts = re.split(r",\s*| - | – ", t, maxsplit=1)
    merchant = parts[0].strip()
    outlet = parts[1].strip() if len(parts) > 1 else None
    return merchant, outlet


# ---------- rules extractor ----------

def rules_extract(raw: RawOffer) -> dict:
    text = _flat(raw.text)
    low = text.lower()
    flags: list[str] = []
    d: dict = {}

    merchant, outlet = split_merchant(raw.title)
    d["merchant_raw"], d["outlet"] = merchant, outlet
    body = _flat(raw.text)[len(_flat(raw.title)):].strip()
    headline = re.split(r"Expires|Terms and Conditions|--- detail", body)[0].strip(" .:-")[:110]
    d["title"] = _flat(raw.title) + (f": {headline}" if headline else "")

    # benefit type, in priority order
    bt, val = None, None
    if re.search(r"buy\s*(1|one)\s*get\s*(1|one)|\b2\s*for\s*1\b|bogo", low):
        bt = BenefitType.BOGO
    elif re.search(r"instal?ment|installment|\bepp\b|0%\s*plan", low) and not re.search(r"\d+\s*%\s*(discount|off)", low):
        bt = BenefitType.INSTALMENT
    elif re.search(r"\d+(\.\d+)?\s*%\s*(off|discount)|discount of \d+(\.\d+)?\s*%|(off|discount)[^.]{0,20}\d+\s*%", low):
        bt = BenefitType.PERCENT                # instant money off beats cashback when both are present
    elif "cashback" in low:
        bt = BenefitType.CASHBACK
    elif re.search(r"\d+(\.\d+)?\s*%", low):
        bt = BenefitType.PERCENT
    elif re.search(r"aed\s*[\d,]+\s*(off|discount)|discount of aed\s*[\d,]+", low):
        bt = BenefitType.FIXED
    elif re.search(r"complimentary|free\b", low):
        bt = BenefitType.PERK
    if bt in (BenefitType.PERCENT, BenefitType.CASHBACK):
        m = re.search(r"(up to\s*)?(\d+(?:\.\d+)?)\s*%", low)
        if m:
            val = float(m.group(2))
            if m.group(1):
                flags.append("up_to")
        n_pct = len(set(re.findall(r"\d+(?:\.\d+)?\s*%", low)))
        if n_pct > 1:
            flags.append("multi_benefit")      # e.g. Make My Trip: 10% off + 10% cashback; Styli: 20/10/5% by item type
    elif bt == BenefitType.FIXED:
        m = re.search(r"aed\s*([\d,]+)\s*(?:off|discount)|discount of aed\s*([\d,]+)", low)
        val = _num(m.group(1) or m.group(2)) if m else None
    if bt == BenefitType.PERCENT and "cashback" in low and re.search(r"\d+\s*%\s*(off|discount)", low):
        flags.append("multi_benefit")          # e.g. Make My Trip: instant 10% off + 10% cashback
    if bt == BenefitType.BOGO and re.search(r"\d+\s*%", low):
        flags.append("multi_benefit")          # e.g. Reel Cinemas: BOGO tickets + 20% off F&B
    if bt is None:
        flags.append("no_benefit_found")
    d["benefit_type"], d["value"] = bt, val

    # instalment months
    d["instalment_months"] = sorted({int(x) for x in re.findall(r"(\d{1,2})\s*(?:,|and|&)?\s*(?:months?)", low)}) if bt == BenefitType.INSTALMENT else []

    # cap: 'up to AED 200', 'capped at', 'maximum ... AED'
    cap = None
    m = re.search(r"(?:up to|capped at|cap of|maximum(?: discount)?(?: of)?)\s*aed\s*([\d,]+)", low)
    if m and bt in (BenefitType.PERCENT, BenefitType.CASHBACK):
        cap = _num(m.group(1))
    d["cap_aed"] = cap

    # min spend: only explicit minimum-style phrases (NOT 'from AED 350 per person', which is a price)
    ms = None
    m = (re.search(r"(?:minimum|min\.?)\s+(?:transaction value|transactions?|purchase|order value|order|spend|bill)(?: value)?(?: of| is)?[^.]{0,25}?aed\s*([\d,]+)", low)
         or re.search(r"purchases?\s+starting\s+at\s+aed\s*([\d,]+)", low)
         or re.search(r"worth\s+aed\s*([\d,]+)\s+and above", low))
    if m:
        ms = _num(m.group(1))
    d["min_spend_aed"] = ms

    # dates
    d["valid_to"] = parse_date(raw.text)
    if d["valid_to"] is None:
        flags.append("no_expiry")

    # channel
    if re.search(r"not valid (?:for|on) online|counter only|cashier'?s counter|physical ticket", low):
        ch = Channel.IN_STORE
    elif re.search(r"online purchases|via [a-z' ]*(?:app|website)|promo code|use code|website only|not valid for any online", low):
        ch = Channel.ONLINE if "not valid for any online" not in low else Channel.IN_STORE
    else:
        ch = Channel.UNKNOWN
    d["channel"] = ch

    # promo code
    m = re.search(r"(?:promo code|use code|code)[:\s]+\"?“?([A-Z][A-Z0-9]{3,14})\b", _flat(raw.text))
    d["promo_code"] = m.group(1) if m else None

    # days
    m = re.search(r"every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", low)
    d["days_times"] = f"every {m.group(1)}" if m else None

    # exclusions: keep short 'not valid ...' sentences
    ex = []
    for s in re.split(r"(?<=[.])\s+|\s+-\s+|\n", raw.text):
        s = _flat(s)
        if re.search(r"not valid|not applicable|excluding|cannot be combined", s, re.I) and len(s) < 160:
            ex.append(s.rstrip("."))
    d["exclusions"] = ex[:6]

    # eligibility
    issuer = raw.issuer
    d["eligible_issuer"] = issuer
    nets = [n for n in ("visa", "mastercard") if n in low]
    d["eligible_networks"] = nets
    products: list[str] = []
    verified = False
    if issuer == "citi":
        if re.search(r"citi ultima|citi prestige", low):
            if re.search(r"citi ultima", low):
                products.append("citi_ultima")
            if re.search(r"citi prestige", low):
                products.append("citi_prestige")
            verified = True
        elif re.search(r"citi(?:bank)? credit (?:or|and) debit|citi credit card|citi(?:bank)? credit cards? and debit", low):
            verified = True
        elif "eligible citi credit card" in low:
            flags.append("eligible_card_unspecified")
    d["eligible_products"] = products
    d["eligibility_verified"] = verified
    if not verified and issuer != "citi":
        flags.append("eligibility_unstated_on_list")
    ct = []
    if "credit" in low:
        ct.append("credit")
    if "debit" in low:
        ct.append("debit")
    d["card_types"] = ct or ["credit", "debit"]
    d["eligible_tiers"] = []

    cat, cflags = categorise(raw.title, raw.text, raw.section)
    d["category"] = cat
    flags += cflags
    d["flags"] = flags
    return d


# ---------- LLM extractor (Groq) ----------

LLM_SYSTEM = """You extract structured data from a UAE bank card-offer text. Return ONLY a JSON object with keys:
merchant_raw, outlet, category (one of %s), benefit_type (percent|fixed|bogo|cashback|instalment|points|perk),
value (number or null; percent for percent/cashback, AED for fixed), cap_aed, min_spend_aed, instalment_months (list of ints),
valid_to (YYYY-MM-DD or null), days_times, channel (in_store|online|both|unknown), promo_code, exclusions (list of short strings),
eligible_networks (subset of visa|mastercard|amex|unionpay), eligible_tiers (subset of %s), eligible_products (list of strings, product names as written),
confidence (0-1), uncertain_fields (list of field names you guessed).
Rules: never invent numbers; if a field is not stated use null; dates in the text are authoritative; 'up to X%%' -> value X;
if several benefits are listed choose the headline one and put 'multi_benefit' in uncertain_fields.""" % (sorted(CATEGORIES), sorted(TIERS))


def llm_extract(raw: RawOffer, model: str | None = None, retries: int = 2) -> dict | None:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None
    model = model or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    body = {
        "model": model, "temperature": 0, "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": LLM_SYSTEM},
                     {"role": "user", "content": f"Issuer: {raw.issuer}\nPage section: {raw.section}\nTEXT:\n{raw.text[:6000]}"}],
    }
    for attempt in range(retries + 1):
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions", json=body, timeout=60,
                              headers={"Authorization": f"Bearer {key}"})
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return json.loads(r.json()["choices"][0]["message"]["content"])
        except (requests.RequestException, KeyError, json.JSONDecodeError):
            time.sleep(2)
    return None


# ---------- combine ----------

def _to_offer(raw: RawOffer, d: dict, method: str, confidence: float, extra_flags: list[str]) -> Offer:
    vt = d.get("valid_to")
    if isinstance(vt, str):
        vt = date.fromisoformat(vt)
    flags = list(dict.fromkeys((d.get("flags") or []) + extra_flags))
    return Offer(
        source=raw.source, source_url=raw.source_url, title=d.get("title") or _flat(raw.title),
        merchant_raw=d["merchant_raw"], outlet=d.get("outlet"), category=d.get("category", "other"),
        benefit_type=d["benefit_type"], value=d.get("value"), cap_aed=d.get("cap_aed"), min_spend_aed=d.get("min_spend_aed"),
        instalment_months=d.get("instalment_months") or [], valid_to=vt, days_times=d.get("days_times"),
        channel=d.get("channel") or Channel.UNKNOWN, promo_code=d.get("promo_code"), exclusions=d.get("exclusions") or [],
        eligible_issuer=raw.issuer, eligible_networks=d.get("eligible_networks") or [],
        eligible_products=d.get("eligible_products") if isinstance(d.get("eligible_products"), list) and all(
            re.fullmatch(r"[a-z0-9_]+", p or "") for p in d.get("eligible_products", [])) else [],
        eligible_tiers=d.get("eligible_tiers") or [], card_types=d.get("card_types") or ["credit", "debit"],
        eligibility_verified=bool(d.get("eligibility_verified", False)),
        raw_text=raw.text, content_hash=hashlib.sha1(raw.text.encode()).hexdigest(),
        confidence=confidence, extraction_method=method, flags=flags,
    )


def normalise(raw: RawOffer, use_llm: bool = False) -> tuple[Offer | None, str | None]:
    """Returns (offer, review_reason). Offer may be set AND a review reason given (low confidence)."""
    rd = rules_extract(raw)
    rule_offer, rule_err = None, None
    try:
        if rd["benefit_type"] is None:
            raise ValueError("no benefit found")
        rule_offer = _to_offer(raw, rd, "rules", 0.8, [])
    except (ValidationError, ValueError, KeyError) as e:
        rule_err = str(e).splitlines()[0][:120]

    if not use_llm:
        if rule_offer is None:
            return None, f"rules_failed: {rule_err}"
        reason = None
        if {"multi_benefit", "no_expiry", "no_benefit_found"} & set(rule_offer.flags):
            rule_offer.confidence = 0.55
            reason = "rules_low_confidence: " + ",".join(sorted({"multi_benefit", "no_expiry", "no_benefit_found"} & set(rule_offer.flags)))
        return rule_offer, reason

    ld = llm_extract(raw)
    if ld is None:
        if rule_offer is None:
            return None, f"rules_failed_and_llm_unavailable: {rule_err}"
        rule_offer.flags.append("llm_unavailable")
        return rule_offer, None
    try:
        ld.setdefault("title", _flat(raw.title))
        ld["benefit_type"] = BenefitType(ld["benefit_type"])
        ld["channel"] = Channel(ld.get("channel") or "unknown")
        # eligibility from the page text is rule-derived (product ids are ours, not the model's)
        ld["eligible_products"] = rd["eligible_products"]
        ld["eligibility_verified"] = rd["eligibility_verified"]
        ld["card_types"] = rd["card_types"]
        llm_offer = _to_offer(raw, ld, "llm", float(ld.get("confidence") or 0.7), ["llm_uncertain:" + f for f in ld.get("uncertain_fields", [])])
    except (ValidationError, ValueError, KeyError) as e:
        if rule_offer:
            rule_offer.flags.append("llm_invalid")
            return rule_offer, f"llm_invalid: {str(e).splitlines()[0][:100]}"
        return None, "both_extractors_failed"
    if rule_offer is None:
        return llm_offer, "llm_only"
    disagree = []
    if rule_offer.benefit_type != llm_offer.benefit_type:
        disagree.append("benefit_type")
    if (rule_offer.value or 0) != (llm_offer.value or 0):
        disagree.append("value")
    if rule_offer.valid_to != llm_offer.valid_to:
        disagree.append("valid_to")
    if disagree:
        llm_offer.confidence = 0.4
        llm_offer.flags.append("rule_llm_disagree:" + "+".join(disagree))
        return llm_offer, "rule_llm_disagree:" + "+".join(disagree)
    llm_offer.confidence = max(llm_offer.confidence, 0.9)
    llm_offer.extraction_method = "rules+llm"
    return llm_offer, None
