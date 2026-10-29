"""Canonical offer schema (see design doc section 2). Everything downstream speaks this."""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class BenefitType(str, Enum):
    PERCENT = "percent"          # instant discount, e.g. 20% off bill
    FIXED = "fixed"              # AED off
    BOGO = "bogo"                # buy one get one / 2-for-1
    CASHBACK = "cashback"        # money back later
    INSTALMENT = "instalment"    # 0% plan
    POINTS = "points"            # loyalty points / miles
    PERK = "perk"                # free membership, lounge, valet... not convertible to AED cleanly


class Channel(str, Enum):
    IN_STORE = "in_store"
    ONLINE = "online"
    BOTH = "both"
    UNKNOWN = "unknown"


# Controlled vocabularies: validation rejects anything outside these.
CATEGORIES = {
    "dining", "groceries", "fashion", "electronics", "beauty_wellness", "travel_hotels",
    "entertainment", "attractions", "kids", "health", "automotive", "jewellery",
    "online_shopping", "services", "other",
}
NETWORKS = {"visa", "mastercard", "amex", "unionpay"}
TIERS = {"classic", "gold", "platinum", "signature", "infinite", "world", "world_elite", "premier", "private"}


class Offer(BaseModel):
    # identity / provenance
    source: str                       # e.g. "citi_ae"
    source_url: str
    title: str
    merchant_raw: str
    outlet: Optional[str] = None      # branch / hotel / mall text as published
    city: str = "Dubai"
    category: str = "other"

    # benefit
    benefit_type: BenefitType
    value: Optional[float] = None     # percent for percent/cashback, AED for fixed, points rate for points
    cap_aed: Optional[float] = None
    min_spend_aed: Optional[float] = None
    instalment_months: list[int] = Field(default_factory=list)

    # when / where / how
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    days_times: Optional[str] = None
    channel: Channel = Channel.UNKNOWN
    promo_code: Optional[str] = None
    exclusions: list[str] = Field(default_factory=list)

    # who
    eligible_issuer: str              # canonical bank id: citi, hsbc, fab ...
    eligible_networks: list[str] = Field(default_factory=list)
    eligible_products: list[str] = Field(default_factory=list)  # card_products.product_id; empty = any product of the issuer
    eligible_tiers: list[str] = Field(default_factory=list)   # fallback when only a tier is stated
    eligible_programmes: list[str] = Field(default_factory=list)
    card_types: list[str] = Field(default_factory=lambda: ["credit", "debit"])
    eligibility_verified: bool = False  # False when the page does not state card eligibility

    # bookkeeping
    raw_text: str = ""
    content_hash: str = ""
    last_verified: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = 1.0
    extraction_method: str = "rules"
    flags: list[str] = Field(default_factory=list)

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        if v not in CATEGORIES:
            raise ValueError(f"category {v!r} not in controlled list")
        return v

    @field_validator("eligible_networks")
    @classmethod
    def _net(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in NETWORKS]
        if bad:
            raise ValueError(f"unknown networks {bad}")
        return v

    @field_validator("eligible_tiers")
    @classmethod
    def _tier(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in TIERS]
        if bad:
            raise ValueError(f"unknown tiers {bad}")
        return v

    @model_validator(mode="after")
    def _sanity(self) -> "Offer":
        if self.benefit_type in (BenefitType.PERCENT, BenefitType.CASHBACK):
            if self.value is None or not (0 < self.value <= 100):
                raise ValueError(f"percent value out of range: {self.value}")
        if self.benefit_type == BenefitType.FIXED and (self.value is None or self.value <= 0):
            raise ValueError("fixed offer needs positive AED value")
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("valid_from after valid_to")
        for n in ("cap_aed", "min_spend_aed"):
            x = getattr(self, n)
            if x is not None and x < 0:
                raise ValueError(f"{n} negative")
        return self
