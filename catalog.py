"""4U Grocery product catalog — loads from catalog_data.json (Marg export).

Only items with verified barcodes (12-14 digit) are included.
Update catalog_data.json + redeploy to refresh inventory.

Fields per item:
  name    — exact item name from Marg
  stock   — current qty (0 = out of stock; still searchable but flagged)
  mrp     — Maximum Retail Price (strikethrough in customer messages)
  price   — 4U sale price (what customer pays)
  barcode — EAN/UPC barcode
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_PATH = os.path.join(_HERE, "catalog_data.json")

with open(_DATA_PATH) as f:
    CATALOG = json.load(f)


# Hindi/Hinglish synonyms — appended to query during matching
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
    "atta": "atta flour",
    "maida": "maida flour",
    "haldi": "turmeric",
    "mirch": "chilli",
    "namkeen": "namkeen",
    "biscuit": "biscuit",
    "sabzi": "vegetable",
    "phal": "fruit",
    "sasta": "cheap",
    "wips": "wipes",
    "saban": "soap",
    "tooth paste": "toothpaste",
    "manjan": "toothpaste",
    "diaper": "diaper",
    "coffee": "coffee",
    "ghee": "ghee",
    "paneer": "paneer",
    "cream": "cream",
    "chocolate": "chocolate",
    "ice cream": "ice cream icecream",
    "shampoo": "shampoo",
    "conditioner": "conditioner",
}


def _expand_query(s: str) -> str:
    """Apply Hinglish synonyms to the QUERY only (not item names)."""
    s = (s or "").lower()
    for syn, eng in SYNONYMS.items():
        if syn in s:
            s += " " + eng
    return s


def _normalize_name(s: str) -> str:
    """Plain lowercase for item names. NO synonym contamination."""
    return (s or "").lower()


def search_catalog(query: str, limit: int = 30):
    """Return matching items for a customer query.

    Scoring per query token:
      +3 if token is a complete word in the item name (highest signal)
      +1 if token only appears as substring (e.g. "atta" inside "khatta") — low signal
      +0.5 in-stock bonus
    Also dedupes the query token list so synonym-expanded duplicates don't double-count.
    """
    q = _expand_query(query)
    if not q.strip():
        return []

    # Dedupe + filter tokens
    seen = set()
    tokens = []
    for t in q.split():
        if len(t) >= 2 and t not in seen:
            seen.add(t)
            tokens.append(t)
    if not tokens:
        return []

    scored = []
    for item in CATALOG:
        name_norm = _normalize_name(item["name"])
        name_words = set(name_norm.split())
        score = 0
        for t in tokens:
            if t in name_words:
                score += 3
            elif t in name_norm:
                score += 1
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


def top_offers(limit: int = 3, min_discount: int = 25):
    """Top in-stock items by discount % — for upsell push.
    Higher min_discount now (25%+) since catalog has thousands of items."""
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


# Catalog stats for runtime sanity
def _stats():
    n = len(CATALOG)
    in_stock = sum(1 for i in CATALOG if i["stock"] > 0)
    return f"Catalog loaded: {n} items, {in_stock} in stock"


print(_stats())
