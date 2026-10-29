"""Builds tests/fixtures/*.html.

IMPORTANT - what these are: the build sandbox had no outbound access from the shell, so I could not save the live HTML.
I read the rendered text of the real pages on 28 Oct 2026 through a text-fetch tool and rebuilt a *subset* here as minimal HTML.
Offer wording/numbers/dates are copied from that capture (T&Cs shortened). The DOM structure is MY reconstruction, not Citi's/HSBC's.
So: these prove the parsing + normalising + ranking logic works; they do NOT prove the selectors match the live DOM. First thing to do
on a laptop: `python -m zave.cli collect` and look at the block counts.
"""
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"
FIX.mkdir(exist_ok=True)

COMMON = ["Offer is valid upon payment on a Citi Credit or Debit Card.", "Discount is not valid in conjunction with any promotion."]
CITI = {
    "Dining": [
        ("Shabestan, Radisson Blu Hotel, Dubai Deira Creek", "<strong>25%</strong> discount on total bill.", "12/30/2026",
         COMMON + ["Offer is not valid on public holidays, special promotions, festive seasons, or blackout dates.", "Advance booking is required."]),
        ("Saffar, InterContinental Ras Al Khaimah Mina Al Arab Resort & SPA", "<strong>10%</strong> discount on total bill.", "12/28/2026",
         COMMON + ["Offer is valid up to 4 people including cardholder.", "Prior reservation is required."]),
        ("Vintage, At Wafi Pyramids", "<strong>20%</strong> discount on total bill on dine-in.", "01/13/2027", COMMON + ["Discount is valid during public holidays."]),
    ],
    "Travel": [
        ("Dukes the Palm Hotel", "<strong>30%</strong> Discount on Best Available Rate.", "12/23/2026",
         ["Offer is valid upon payment on a Citi Credit or Debit Card.", "Offer is not valid in conjunction with any on-going promotion and not valid for online booking."]),
        ("Make My Trip", "<strong>Hotel Bookings</strong> <strong>10%</strong> off on minimum transactions of <strong>AED 300</strong> plus <strong>10%</strong> cashback on select hotel bookings. "
         "<strong>Flight Bookings</strong> 10% off plus 10% cashback up to <strong>AED 50.</strong>", "06/30/2027",
         ["Offer is valid upon payment with a Citi Credit or Debit Card.", "Instant discount of 10% up to AED 200 plus 10% cashback in MMT Wallet up to AED 200 on select hotel bookings.",
          "Minimum transaction value: AED 300."]),
        ("dnata Travel", "Your Next Escape Starts from <strong>AED 350</strong> per Person* Get Smarter with dnata Travel and Enjoy <strong>5%</strong> Off on Selected Destinations.", "12/15/2026",
         ["Offer is valid upon payment using a Citi Credit or Debit Card.", "An additional flat 5% discount is applicable on select destinations using the promo code CITIBANK.",
          "Maldives: Book 3 nights at a 5-star resort, from AED 4,070 per person."]),
    ],
    "Entertainment": [
        ("Koala Kids, Dubai Mall, and Al Qouz", "Up to <strong>20%</strong> discount.", "12/31/2026",
         ["Payment on Citibank Credit cards and Debit Cards only.", "Discount is not valid in conjunction with any promotion and not valid during public holidays or special occasions."]),
        ("Play DXB", "<strong>20%</strong> discount on All standard worth <strong>AED 350</strong> and above.", "12/31/2027",
         ["Offer is valid upon payment by eligible CITI Credit Card (Citi Ultima & Citi Prestige).", "Offer is valid on attraction ticketing counter only.", "Offer is not valid for online booking.", "Offer is not valid during public holidays."]),
        ("Reel Cinemas", "Buy 1 Get 1 movie ticket and <strong>20%</strong> discount on food & beverages on minimum purchase of <strong>AED 20</strong>.", "12/31/2027",
         ["Offer is valid upon payment by eligible CITI Credit Card (Citi Ultima & Citi Prestige).", "For BOGO offer, guests need to choose minimum of two tickets to avail the offer.",
          "Offer is valid for tickets purchased online or via Reel Cinemas mobile app."]),
        ("IMG Theme Park", "<strong>30%</strong> discount on General Admission Tickets calculated at the rack rate (1+4 Family Members).", "01/10/2027",
         ["Offer is valid upon payment on a Citi Credit or Debit Card at the cashier's counter.", "Offer is not valid for any online purchases."]),
    ],
    "Shopping": [
        ("NRTC Fresh", "<strong>10%</strong> discount, minimum order value of <strong>AED 80.</strong>", "03/31/2027",
         ["Offer is valid upon payment of a Citi Credit or Debit Card.", "Offer is valid on minimum purchase of AED 80.", "There is no cap on the discount amount.", "Offer is valid for all online purchases via NRTC's app or website."]),
        ("fnp.ae", "<strong>15%</strong> discount on all products across fnp.ae. Use code <strong>CITI15</strong>.", "03/31/2027",
         ["Offer is valid upon payment of a Citibank Credit or Debit Card.", "Customer has to use the code CITI15 while checking out on www.fnp.ae."]),
        ("Styli", "<strong>20%</strong> discount on full price, <strong>10%</strong> discount on sale items and <strong>5%</strong> discount on home & beauty items.", "12/31/2026",
         ["Privileges are valid upon payment on Citi Credit or Debit Card.", "Offer is valid on UAE website only, www.styli.ae."]),
    ],
    "Lifestyle": [
        ("InterContinental Ras Al Khaimah Mina Al Arab Resort & SPA", "10% off on Spa treatments.", "12/28/2026",
         ["Offer is valid upon payment on a Citi Credit or Debit Card.", "Discount is not valid in conjunction with any promotion."]),
    ],
}


def citi_html() -> str:
    h = ["<html><body><nav><h3>Bank with us</h3></nav><main><h1>Cards Offers</h1>"]
    for sec, items in CITI.items():
        h.append(f"<section><h2>Card Offers on {sec}</h2>")
        for title, head, exp, tcs in items:
            lis = "".join(f"<li>{t}</li>" for t in tcs)
            h.append(f"<div class='card'><img alt=''><h3>{title}</h3><p>{head}<br><strong>Expires On: {exp}</strong></p>"
                     f"<a>Learn more</a><div class='modal'><strong>Terms and Conditions:</strong><ul>{lis}</ul></div></div>")
        h.append("</section>")
    h.append("<h2>Discover More Benefits with Citibank Credit Cards</h2><h3>Golf</h3><a>Golf</a></main></body></html>")
    return "\n".join(h)


HSBC = [
    ("airalo-get-a-sim-card-with-2gb-free-data-roaming-31-12-2026", "Airalo", "Get a SIM card with 2GB free data roaming!", "31 December 2026"),
    ("airalo-global-data-roaming-save-with-a-15-discount-on-roaming-data-with-airalo-10-06-2027", "Airalo Global Data Roaming", "Save with a 15% discount on roaming data with Airalo", "10 June 2027"),
    ("anantara-spa-anantara-the-palm-dubai-resort-30-discount-on-all-treatments-14-11-2026", "Anantara Spa - Anantara The Palm Dubai Resort", "30% Discount on all treatments", "14 November 2026"),
    ("beautiful-bundles-10-discount-on-total-bill-14-11-2026", "Beautiful Bundles", "10% Discount on total bill", "14 November 2026"),
    ("bhima-jewellers-flexi-instalment-plans-on-purchases-starting-at-aed-1-000-31-12-2029", "Bhima Jewellers", "Flexi Instalment Plans on purchases starting at AED 1,000", "31 December 2029"),
    ("blu20-health-club-and-spa-radisson-blu-hotel-dubai-deira-creek-20-discount-on-gym-membership-30-11-2026", "Blu20 Health Club and Spa - Radisson Blu Hotel, Dubai Deira Creek", "20% Discount on Gym Membership", "30 November 2026"),
    ("blu20-health-club-and-spa-radisson-blu-hotel-dubai-deira-creek-20-discount-on-spa-treatments-30-11-2026", "Blu20 Health Club and Spa - Radisson Blu Hotel, Dubai Deira Creek", "20% Discount on Spa Treatments", "30 November 2026"),
    # slug says 2024 but the page shows 31 Dec 2026 -> displayed date must win
    ("careem-get-a-complimentary-12-month-careem-plus-subscription-with-hsbc-simply-add-and-use-your-hsbc-credit-card-on-the-careem-app-15-11-2024", "Careem", "Get a complimentary 12-month Careem Plus subscription with HSBC. Simply add and use your HSBC credit card on the Careem app", "31 December 2026"),
    ("cocoona-centre-for-aesthetic-transformation-flexi-instalment-plans-on-purchases-starting-at-aed-1-000-31-05-2027", "Cocoona Centre for Aesthetic Transformation", "Flexi Instalment Plans on purchases starting at AED 1,000", "31 May 2027"),
    ("damas-flexi-instalment-plans-on-purchases-starting-at-aed-2-000-28-02-2027", "Damas", "Flexi Instalment Plans on purchases starting at AED 2,000", "28 February 2027"),
    # slug says 31-12-2026 but page shows 30 November 2026
    ("district-gold-get-a-complimentary-12-month-district-gold-membership-31-12-2026", "District Gold", "Get a complimentary 12-month District Gold membership", "30 November 2026"),
]


def hsbc_html() -> str:
    h = ["<html><body><main><h1>Credit and debit card special offers</h1><ul>"]
    for i, (slug, name, head, exp) in enumerate(HSBC, 1):
        h.append(f"<li><a href='/credit-cards/special-offers/{slug}/'>Offer {i} of 57 {name}</a><p>{head}</p><p>Expires {exp}</p></li>")
    h.append("</ul><nav><a href='/credit-cards/special-offers.dubai.all-categories.page-2/'>Page 2</a></nav></main></body></html>")
    return "\n".join(h)


if __name__ == "__main__":
    (FIX / "citi_promotions.html").write_text(citi_html(), encoding="utf-8")
    (FIX / "hsbc_special_offers_p1.html").write_text(hsbc_html(), encoding="utf-8")
    print("fixtures written")
