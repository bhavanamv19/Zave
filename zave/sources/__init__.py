from dataclasses import dataclass, field


@dataclass
class RawOffer:
    """One offer block exactly as published, before normalisation."""
    source: str
    source_url: str
    issuer: str
    title: str                      # merchant / headline as shown
    text: str                       # all visible text for the block incl. T&Cs
    section: str = ""               # page category heading if any
    extra: dict = field(default_factory=dict)
