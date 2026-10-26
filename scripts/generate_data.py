"""Generate the synthetic store catalog and order history in data/.

The output is checked into the repo, so this script only needs to be re-run
if you change it. Everything is deterministic: a fixed random seed for the
filler orders, and hand-written orders for the cases the evals depend on
(final sale, outside the return window, not yet delivered, and so on).

All names, emails and products are invented. Emails use example.com.

Dates are relative to STORE_TODAY (2026-10-15), the frozen "today" the app
uses by default so that return-window math on this data never drifts.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STORE_TODAY = date(2026, 10, 15)
SEED = 42

# (sku, name, category, price, final_sale, attributes, description)
PRODUCTS = [
    ("SKU-1001", "Trailhead Rain Shell", "outerwear", 129.00, False,
     {"sizes": "XS-XXL", "color": "slate", "waterproof": "yes"},
     "Lightweight waterproof shell with taped seams and a packable hood."),
    ("SKU-1002", "Harbor Wool Peacoat", "outerwear", 219.00, False,
     {"sizes": "XS-XL", "color": "navy", "material": "80% wool"},
     "Double-breasted wool coat with a quilted lining for cold commutes."),
    ("SKU-1003", "Ridge Fleece Pullover", "outerwear", 69.00, False,
     {"sizes": "S-XXL", "color": "moss", "material": "recycled polyester"},
     "Midweight fleece with a half zip, good for layering."),
    ("SKU-1004", "Everyday Cotton Tee", "tops", 22.00, False,
     {"sizes": "XS-XXL", "color": "white", "material": "organic cotton"},
     "Soft crew-neck tee in organic cotton. Preshrunk."),
    ("SKU-1005", "Linen Camp Shirt", "tops", 58.00, False,
     {"sizes": "S-XL", "color": "sand", "material": "linen"},
     "Breathable short-sleeve linen shirt with a relaxed fit."),
    ("SKU-1006", "Merino Crew Sweater", "tops", 98.00, False,
     {"sizes": "XS-XL", "color": "charcoal", "material": "merino wool"},
     "Fine-gauge merino sweater that resists odor and itch."),
    ("SKU-1007", "Stretch Chino Pant", "bottoms", 64.00, False,
     {"waist": "28-40", "color": "khaki", "fit": "slim"},
     "Chinos with a little stretch for all-day comfort."),
    ("SKU-1008", "Selvedge Denim Jean", "bottoms", 110.00, False,
     {"waist": "28-38", "color": "indigo", "fit": "straight"},
     "Raw selvedge denim that fades with wear."),
    ("SKU-1009", "Trail Running Short", "bottoms", 38.00, False,
     {"sizes": "S-XL", "color": "black", "inseam": "5 inch"},
     "Quick-dry running short with a zip pocket."),
    ("SKU-1010", "Canvas Low Sneaker", "footwear", 75.00, False,
     {"sizes": "5-13", "color": "off-white"},
     "Classic canvas sneaker with a vulcanized rubber sole."),
    ("SKU-1011", "Waterproof Hiking Boot", "footwear", 165.00, False,
     {"sizes": "6-14", "color": "brown", "waterproof": "yes"},
     "Mid-height hiking boot with a waterproof membrane and lugged sole."),
    ("SKU-1012", "Sample Sale Loafer", "footwear", 49.00, True,
     {"sizes": "7-12", "color": "tan"},
     "Leather penny loafer from a past season. Final sale."),
    ("SKU-1013", "Cast Iron Skillet 10in", "kitchen", 42.00, False,
     {"diameter": "10 inch", "preseasoned": "yes"},
     "Preseasoned cast iron skillet for stovetop and oven."),
    ("SKU-1014", "Pour-Over Coffee Set", "kitchen", 36.00, False,
     {"capacity": "600 ml", "material": "borosilicate glass"},
     "Glass dripper, carafe and 40 paper filters."),
    ("SKU-1015", "Chef Knife 8in", "kitchen", 89.00, False,
     {"blade": "8 inch", "steel": "German stainless"},
     "Full-tang chef knife with a forged stainless blade."),
    ("SKU-1016", "Stoneware Dinner Plates (set of 4)", "kitchen", 54.00, False,
     {"pieces": "4", "dishwasher_safe": "yes"},
     "Reactive-glaze stoneware plates, microwave and dishwasher safe."),
    ("SKU-1017", "Linen Duvet Cover Queen", "home", 149.00, False,
     {"size": "queen", "material": "stonewashed linen"},
     "Stonewashed linen duvet cover with a button closure."),
    ("SKU-1018", "Wool Throw Blanket", "home", 79.00, False,
     {"dimensions": "50x60 inch", "material": "lambswool"},
     "Woven lambswool throw with fringed edges."),
    ("SKU-1019", "Clearance Ceramic Vase", "home", 18.00, True,
     {"height": "9 inch", "color": "speckled white"},
     "Hand-thrown ceramic vase. Clearance item, final sale."),
    ("SKU-1020", "Soy Candle Cedar", "home", 24.00, True,
     {"burn_time": "45 hours", "scent": "cedar and sage"},
     "Hand-poured soy candle. For hygiene reasons candles are final sale."),
    ("SKU-1021", "Insulated Water Bottle 32oz", "outdoor", 34.00, False,
     {"capacity": "32 oz", "keeps_cold": "24 hours"},
     "Double-wall stainless bottle that keeps drinks cold for 24 hours."),
    ("SKU-1022", "Two-Person Backpacking Tent", "outdoor", 289.00, False,
     {"capacity": "2 person", "weight": "3.4 lb", "season": "3-season"},
     "Freestanding three-season tent with two doors and vestibules."),
    ("SKU-1023", "Down Sleeping Bag 20F", "outdoor", 239.00, False,
     {"rating": "20F", "fill": "650 fill down"},
     "Mummy-shape down bag rated to 20 degrees Fahrenheit."),
    ("SKU-1024", "Leather Card Wallet", "accessories", 45.00, False,
     {"slots": "4", "material": "full-grain leather"},
     "Slim card wallet in full-grain leather."),
    ("SKU-1025", "Gift Card $50", "accessories", 50.00, True,
     {"delivery": "email"},
     "Digital gift card delivered by email. Gift cards are non-returnable."),
]

FIRST = ["Avery", "Jordan", "Riley", "Casey", "Morgan", "Quinn", "Rowan", "Sage",
         "Emerson", "Hayden", "Parker", "Reese", "Skyler", "Dakota", "Finley"]
LAST = ["Okafor", "Lindqvist", "Moreau", "Tanaka", "Castillo", "Novak", "Haddad",
        "Brennan", "Kowalski", "Iyer", "Ferreira", "Nakamura", "Osei", "Varga", "Duarte"]


def product_by_sku() -> dict[str, tuple]:
    return {p[0]: p for p in PRODUCTS}


def make_item(sku: str, quantity: int = 1) -> dict:
    p = product_by_sku()[sku]
    return {"sku": sku, "name": p[1], "quantity": quantity, "unit_price": p[3],
            "final_sale": p[4]}


def make_order(order_id: str, email: str, skus: list[str], ordered_days_ago: int,
               delivered_days_ago: int | None, status: str) -> dict:
    ordered = STORE_TODAY - timedelta(days=ordered_days_ago)
    delivered = (STORE_TODAY - timedelta(days=delivered_days_ago)
                 if delivered_days_ago is not None else None)
    tracking = None if status in ("processing", "cancelled") else f"TRK{order_id[-5:]}US"
    return {
        "order_id": order_id,
        "email": email,
        "status": status,
        "order_date": ordered.isoformat(),
        "delivered_date": delivered.isoformat() if delivered else None,
        "tracking_number": tracking,
        "items": [make_item(s) for s in skus],
    }


def hand_written_orders() -> list[dict]:
    """Orders that tests and eval scenarios refer to by id. Do not renumber."""
    return [
        # delivered 10 days ago: eligible for return
        make_order("ORD-10001", "avery.okafor@example.com", ["SKU-1001", "SKU-1004"], 16, 10,
                   "delivered"),
        # delivered 45 days ago: outside the 30-day window
        make_order("ORD-10002", "jordan.lindqvist@example.com", ["SKU-1011"], 50, 45, "delivered"),
        # delivered 5 days ago but contains a final-sale item and a normal one
        make_order("ORD-10003", "riley.moreau@example.com", ["SKU-1012", "SKU-1007"], 9, 5,
                   "delivered"),
        # shipped, not delivered yet
        make_order("ORD-10004", "casey.tanaka@example.com", ["SKU-1022"], 3, None, "shipped"),
        # still processing
        make_order("ORD-10005", "morgan.castillo@example.com", ["SKU-1015", "SKU-1014"], 1, None,
                   "processing"),
        # delivered exactly 30 days ago: last eligible day
        make_order("ORD-10006", "quinn.novak@example.com", ["SKU-1006"], 34, 30, "delivered"),
        # delivered exactly 31 days ago: first ineligible day
        make_order("ORD-10007", "rowan.haddad@example.com", ["SKU-1018"], 35, 31, "delivered"),
        # cancelled before shipping
        make_order("ORD-10008", "sage.brennan@example.com", ["SKU-1023"], 12, None, "cancelled"),
    ]


def filler_orders(rng: random.Random, start: int, count: int) -> list[dict]:
    orders = []
    skus = [p[0] for p in PRODUCTS]
    for i in range(count):
        order_id = f"ORD-{start + i}"
        first, last = rng.choice(FIRST), rng.choice(LAST)
        email = f"{first.lower()}.{last.lower()}{rng.randint(1, 99)}@example.com"
        items = rng.sample(skus, k=rng.randint(1, 3))
        ordered_days_ago = rng.randint(2, 90)
        roll = rng.random()
        if roll < 0.7 and ordered_days_ago > 4:
            delivered = ordered_days_ago - rng.randint(2, 4)
            status = "delivered"
        elif roll < 0.9:
            # orders still in transit are recent
            ordered_days_ago = min(ordered_days_ago, rng.randint(2, 6))
            delivered, status = None, "shipped"
        else:
            ordered_days_ago = 1
            delivered, status = None, "processing"
        orders.append(make_order(order_id, email, items, ordered_days_ago, delivered, status))
    return orders


def main() -> None:
    rng = random.Random(SEED)
    products = [
        {"sku": s, "name": n, "category": c, "price": pr, "final_sale": fs,
         "attributes": attrs, "description": d}
        for (s, n, c, pr, fs, attrs, d) in PRODUCTS
    ]
    orders = hand_written_orders() + filler_orders(rng, start=10009, count=22)
    (DATA_DIR / "products.json").write_text(json.dumps(products, indent=2) + "\n")
    (DATA_DIR / "orders.json").write_text(json.dumps(orders, indent=2) + "\n")
    print(f"wrote {len(products)} products and {len(orders)} orders to {DATA_DIR}")


if __name__ == "__main__":
    main()
