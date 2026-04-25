"""4U Grocery product catalog.

Initial 30-item sample from Marg export. Swap to Google Sheet fetcher
when full 5000-item sheet is available — keep the search_catalog()
signature stable so handle_grocery doesn't need to change.

Fields per item:
  name  — exact item name as it appears in Marg
  stock — current stock qty (0 = out of stock)
  mrp   — Maximum Retail Price (shown to customer with strikethrough)
  price — 4U sale price (what customer actually pays)
"""

CATALOG = [
    {"name": "AMERICANA FLICK COCONUT 50G",        "stock": 20, "mrp": 10.00,  "price": 9.00},
    {"name": "AMERICANA FLICK STRAWBERRY 50G",     "stock": 83, "mrp":  9.00,  "price": 8.00},
    {"name": "AMERICANA FLICK VANILA 50G",         "stock": 98, "mrp": 10.00,  "price": 9.00},
    {"name": "AMERICANA T-8",                       "stock":  8, "mrp": 240.00, "price": 140.00},
    {"name": "AMMY BABY WIPS 80P",                  "stock":  5, "mrp": 185.00, "price":  92.50},
    {"name": "AMMY MAXI THICK 40P",                 "stock":  0, "mrp": 399.00, "price": 220.00},
    {"name": "AMMY MAXI XL 16P",                    "stock":  0, "mrp": 100.00, "price":  65.00},
    {"name": "AMMY MAXI XL 36P",                    "stock":  0, "mrp": 180.00, "price": 125.00},
    {"name": "AMMY MAXI XXL 15P",                   "stock":  0, "mrp": 100.00, "price":  65.00},
    {"name": "AMMY MAXI XXL 24P",                   "stock":  0, "mrp": 150.00, "price": 110.00},
    {"name": "AMMY ULTRA THIN XXL 30P",             "stock":  8, "mrp": 300.00, "price": 170.00},
    {"name": "AMONIA POWDER 100G",                  "stock":  8, "mrp":  50.00, "price":  22.00},
    {"name": "AMPI PUR CAR JASMINE REFIIL 1N",      "stock":  4, "mrp": 249.00, "price": 190.00},
    {"name": "AMUL BADAM SHAKES CAN 200ML",         "stock":  0, "mrp":  40.00, "price":  36.80},
    {"name": "AMUL BELIGIAN CHOCOLATE 35G",         "stock":  0, "mrp":  50.00, "price":  45.00},
    {"name": "AMUL BUTTER 100G",                    "stock": 10, "mrp":  58.00, "price":  53.36},
    {"name": "AMUL BUTTER 200G",                    "stock":  1, "mrp": 118.00, "price": 108.56},
    {"name": "AMUL BUTTER 500G",                    "stock":  5, "mrp": 285.00, "price": 262.20},
    {"name": "AMUL CHEESE CUBE 200G",               "stock":  8, "mrp": 130.00, "price": 119.60},
    {"name": "AMUL CHEESE SLICE 200G",              "stock":  5, "mrp": 140.00, "price": 128.80},
    {"name": "AMUL CHOCOMINIS 250G",                "stock": 10, "mrp": 130.00, "price": 119.60},
    {"name": "AMUL DAHI 15KG",                      "stock":  0, "mrp": 975.00, "price": 920.00},
    {"name": "AMUL DARK CHOCLATE 35G",              "stock":  0, "mrp":  45.00, "price":  40.00},
    {"name": "AMUL DICED CHEESE 200G",              "stock":  9, "mrp": 120.00, "price": 110.40},
    {"name": "AMUL F&N DARK CHOCOLATE 40G",         "stock":  5, "mrp":  45.00, "price":  40.00},
    {"name": "AMUL FRESH CREAM 250ML",              "stock":  6, "mrp":  70.00, "price":  64.40},
    {"name": "AMUL KOOL CAFE COFFEE 200ML",         "stock": 30, "mrp":  60.00, "price":  50.00},
    {"name": "AMUL KOOL ELAICHI 180ML",             "stock": 22, "mrp":  30.00, "price":  27.00},
    {"name": "AMUL KOOL GOLD KESAR 180ML",          "stock":  1, "mrp":  30.00, "price":  27.00},
    {"name": "AMUL PURE GHEE 1L",                   "stock":  0, "mrp": 610.00, "price": 560.00},
]

# Hindi/Hinglish synonyms → English keywords for fuzzy matching
SYNONYMS = {
    "cheeni": "sugar", "shakkar": "sugar",
    "doodh": "milk",
    "chawal": "rice",
    "tel": "oil",
    "namak": "salt",
    "chai": "tea",
    "anda": "egg",
    "pyaaz": "onion", "kanda": "onion",
    "aalu": "potato",
    "tamatar": "tomato",
    "dahi": "curd",
    "makhan": "butter",
    "ghee": "ghee",
    "atta": "flour atta",
    "maida": "flour maida",
    "haldi": "turmeric",
    "mirch": "chilli",
    "namkeen": "snack namkeen",
    "biscuit": "biscuit",
    "sabzi": "vegetable",
    "phal": "fruit",
    "wips": "wipes",
}


def _normalize(s: str) -> str:
    """Lowercase + apply synonyms for matching."""
    s = (s or "").lower()
    for syn, eng in SYNONYMS.items():
        if syn in s:
            s += " " + eng
    return s


def search_catalog(query: str, limit: int = 20):
    """Return top matching items for a customer query.

    Simple substring scoring: each token in the query that appears
    in the item name scores +1. In-stock items get a +0.5 bonus to
    bubble up over out-of-stock variants of the same product.
    """
    q = _normalize(query)
    if not q.strip():
        return []

    tokens = [t for t in q.split() if len(t) >= 2]
    scored = []
    for item in CATALOG:
        name_norm = _normalize(item["name"])
        score = sum(1 for t in tokens if t in name_norm)
        if score == 0:
            continue
        if item["stock"] > 0:
            score += 0.5
        scored.append((score, item))

    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:limit]]


def format_item_for_ai(item: dict) -> str:
    """Compact one-line representation passed to the AI."""
    discount = round((item["mrp"] - item["price"]) / item["mrp"] * 100) if item["mrp"] > 0 else 0
    stock_label = "in stock" if item["stock"] > 0 else "OUT OF STOCK"
    return (
        f"- {item['name']} | MRP ₹{item['mrp']:.0f} | 4U ₹{item['price']:.0f} "
        f"({discount}% off) | {stock_label} ({item['stock']})"
    )


def top_offers(limit: int = 3, min_discount: int = 15):
    """Return the top in-stock items by discount % — for upsell push."""
    scored = []
    for item in CATALOG:
        if item["stock"] <= 0 or item["mrp"] <= 0:
            continue
        discount = (item["mrp"] - item["price"]) / item["mrp"] * 100
        if discount < min_discount:
            continue
        scored.append((discount, item))
    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:limit]]
