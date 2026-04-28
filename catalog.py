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

# Trial mode: treat ALL items as in-stock regardless of Marg numbers.
# Flip to False once user confirms real stock data is reliable.
UNLIMITED_STOCK_TRIAL = True

# Data sanity pass — protect against Marg-export errors
for _it in CATALOG:
    if _it.get("stock", 0) < 0:
        _it["stock"] = 0
    if _it.get("price", 0) > _it.get("mrp", 0) > 0:
        _it["price"] = _it["mrp"]
    if _it.get("mrp", 0) <= 0 and _it.get("price", 0) > 0:
        _it["mrp"] = _it["price"]
    if UNLIMITED_STOCK_TRIAL and _it.get("price", 0) > 0:
        _it["stock"] = max(_it.get("stock", 0), 99)


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


# Map customer query words → category code (for category-filtered search)
QUERY_TO_CATEGORY = {
    "butter": "BUTTER", "makhan": "BUTTER",
    "ghee": "GHEE",
    "cheese": "CHEESE",
    "paneer": "DAIRY_OTHER", "dahi": "DAIRY_OTHER", "curd": "DAIRY_OTHER", "cream": "DAIRY_OTHER",
    "doodh": "DAIRY_OTHER", "milk": "DAIRY_OTHER",
    "popcorn": "POPCORN", "pops": "POPCORN",
    "pani": "WATER", "water": "WATER", "bisleri": "WATER", "aquafina": "WATER",
    "nimbu pani": "DRINK_PANI", "jal jeera": "DRINK_PANI", "jaljeera": "DRINK_PANI",
    "panipuri": "NAMKEEN_CHIPS", "pani puri": "NAMKEEN_CHIPS", "gol gappa": "NAMKEEN_CHIPS",
    "glucan": "DRINK_PANI", "electoral": "DRINK_PANI", "electral": "DRINK_PANI",
    "shikanji": "DRINK_PANI",
    "chocolate": "CHOCOLATE", "choco": "CHOCOLATE", "cadbury": "CHOCOLATE",
    "kitkat": "CHOCOLATE", "dairy milk": "CHOCOLATE", "perk": "CHOCOLATE",
    "five star": "CHOCOLATE", "munch": "CHOCOLATE", "gems": "CHOCOLATE",
    "eclairs": "CHOCOLATE", "milky bar": "CHOCOLATE",
    "ice cream": "ICE_CREAM", "ice-cream": "ICE_CREAM", "icecream": "ICE_CREAM",
    "ice": "ICE_CREAM", "kulfi": "ICE_CREAM", "cone": "ICE_CREAM", "softy": "ICE_CREAM",
    "sundae": "ICE_CREAM", "candy": "ICE_CREAM", "chocobar": "ICE_CREAM",
    "biscuit": "BISCUIT", "cookie": "BISCUIT", "rusk": "BISCUIT",
    "parle g": "BISCUIT", "good day": "BISCUIT", "marie": "BISCUIT",
    "bourbon": "BISCUIT", "hide and seek": "BISCUIT", "tiger": "BISCUIT",
    "namkeen": "NAMKEEN_CHIPS", "chips": "NAMKEEN_CHIPS", "snack": "NAMKEEN_CHIPS",
    "kurkure": "NAMKEEN_CHIPS", "bhujia": "NAMKEEN_CHIPS",
    "maggi": "NOODLES", "noodles": "NOODLES", "pasta": "NOODLES",
    "drinks": "DRINK_COLD", "drink": "DRINK_COLD", "cold drink": "DRINK_COLD",
    "cold drinks": "DRINK_COLD", "soft drink": "DRINK_COLD", "soft drinks": "DRINK_COLD",
    "thanda": "DRINK_COLD", "refreshment": "DRINK_COLD", "beverage": "DRINK_COLD",
    "beverages": "DRINK_COLD",
    "juice": "DRINK_COLD", "cold": "DRINK_COLD", "soda": "DRINK_COLD",
    "coke": "DRINK_COLD", "pepsi": "DRINK_COLD", "kool": "DRINK_COLD", "shake": "DRINK_COLD",
    "shakes": "DRINK_COLD", "lassi": "DRINK_COLD", "frooti": "DRINK_COLD",
    "maaza": "DRINK_COLD", "thums up": "DRINK_COLD",
    "sprite": "DRINK_COLD", "fanta": "DRINK_COLD", "mirinda": "DRINK_COLD",
    "real": "DRINK_COLD", "tropicana": "DRINK_COLD",
    "water": "WATER", "bisleri": "WATER",
    "tea": "TEA_COFFEE", "chai": "TEA_COFFEE", "coffee": "TEA_COFFEE", "bru": "TEA_COFFEE",
    "spice": "SPICE", "masala": "SPICE", "haldi": "SPICE", "mirch": "SPICE",
    "jeera": "SPICE", "dhaniya": "SPICE", "hing": "SPICE", "saunf": "SPICE",
    "elaichi": "SPICE", "kalimirch": "SPICE", "ajwain": "SPICE", "methi": "SPICE",
    "garam masala": "SPICE", "chaat masala": "SPICE", "amchur": "SPICE",
    "salt": "SALT", "namak": "SALT",
    "sugar": "SUGAR", "cheeni": "SUGAR", "shakkar": "SUGAR", "honey": "SUGAR", "shahad": "SUGAR",
    "oil": "OIL", "tel": "OIL", "refined": "OIL", "mustard": "OIL",
    "atta": "ATTA", "flour": "ATTA", "maida": "ATTA", "besan": "ATTA",
    "rice": "RICE", "chawal": "RICE", "basmati": "RICE",
    "dal": "DAL", "moong": "DAL", "chana": "DAL", "rajma": "DAL",
    "urad": "DAL", "masoor": "DAL", "tuvar": "DAL", "toor": "DAL",
    "lobia": "DAL", "matar": "DAL",
    "soap": "SOAP", "saban": "SOAP", "saabun": "SOAP",
    "shampoo": "HAIR_CARE", "conditioner": "HAIR_CARE", "hair": "HAIR_CARE",
    "face wash": "COSMETIC", "facewash": "COSMETIC", "lotion": "COSMETIC",
    "moisturiser": "COSMETIC", "moisturizer": "COSMETIC", "cream face": "COSMETIC",
    "dish wash": "CLEANING", "dishwash": "CLEANING", "vim": "CLEANING",
    "toothpaste": "ORAL_CARE", "manjan": "ORAL_CARE", "tooth": "ORAL_CARE",
    "brush": "ORAL_CARE", "toothbrush": "ORAL_CARE", "tongue cleaner": "ORAL_CARE",
    "paint brush": "STATIONERY_BRUSH", "art brush": "STATIONERY_BRUSH",
    "toilet brush": "CLEANING_BRUSH",
    "detergent": "DETERGENT", "surf": "DETERGENT", "tide": "DETERGENT", "ariel": "DETERGENT",
    "harpic": "CLEANING", "lizol": "CLEANING", "vim": "CLEANING",
    "pad": "HYGIENE", "wipes": "HYGIENE", "whisper": "HYGIENE", "sanitary": "HYGIENE",
    "diaper": "BABY", "pampers": "BABY", "baby": "BABY",
    "toy": "TOY", "toys": "TOY",
    "pen": "STATIONERY", "pencil": "STATIONERY", "copy": "STATIONERY", "notebook": "STATIONERY",
    "eraser": "STATIONERY", "rubber": "STATIONERY", "sharpener": "STATIONERY",
    "scale": "STATIONERY", "marker": "STATIONERY", "highlighter": "STATIONERY",
    "stapler": "STATIONERY", "glue": "STATIONERY", "tape": "STATIONERY",
    "doms": "STATIONERY", "register": "STATIONERY",
    "agarbatti": "POOJA", "incense": "POOJA", "diya": "POOJA",
    "bread": "BREAD", "bun": "BREAD", "cake": "BREAD",
    "egg": "EGG", "anda": "EGG",
}


# Phrases that LOOK like category keywords but mean something else.
# Returning None pushes the query to AI, which sees the actual catalog matches
# and answers correctly (e.g. 'butter paper' → parchment, not butter).
SHADOW_PHRASES = {
    "butter paper", "foil paper", "silver paper", "wax paper",
    "tissue paper", "kitchen paper", "cling film", "cling wrap",
    "ice tray", "ice box",            # don't map to ice cream
    "milk powder",                    # special category if needed
    "egg tray", "egg shell",
}


def _detect_category(query: str) -> str | None:
    """If query mentions a known category keyword, return its category code.
    Uses longest-match-first so multi-word keys like 'ice cream' beat 'cream'.
    Returns None for shadow phrases so they bypass category routing → AI handles."""
    q = (query or "").lower().strip()
    if any(p in q for p in SHADOW_PHRASES):
        return None
    for word, cat in sorted(QUERY_TO_CATEGORY.items(), key=lambda x: -len(x[0])):
        if f" {word} " in f" {q} " or q == word or q.startswith(word + " ") or q.endswith(" " + word):
            return cat
    return None


def search_catalog(query: str, limit: int = 30):
    """Return matching items for a customer query.

    Two-stage:
      1. If query mentions a known category keyword (butter/popcorn/chocolate/etc.),
         restrict the search universe to items in that category only.
         This is what stops "butter" from matching popcorn-with-butter-flavor.
      2. Within the (possibly restricted) universe, score by:
           +3 per exact word match in name
           +1 per substring token match
           +0.5 in-stock bonus
    """
    q = _expand_query(query)
    if not q.strip():
        return []

    seen = set()
    tokens = []
    for t in q.split():
        if len(t) >= 2 and t not in seen:
            seen.add(t)
            tokens.append(t)
    if not tokens:
        return []

    # Category-filter step
    cat = _detect_category(query)
    universe = [i for i in CATALOG if i.get("category") == cat] if cat else CATALOG

    scored = []
    for item in universe:
        name_norm = _normalize_name(item["name"])
        name_words = set(name_norm.split())
        score = 0
        for t in tokens:
            if t in name_words:
                score += 3
            elif t in name_norm:
                score += 1
        # When category-filtered, give small base score so ALL items in the
        # category surface even if name doesn't contain the query word
        if cat and score == 0:
            score = 0.1
        if score == 0:
            continue
        if item["stock"] > 0:
            score += 0.5
        scored.append((score, item))

    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:limit]]


def format_price_label(item: dict) -> str:
    """Format price professionally: no-discount = direct MRP only, else strikethrough.
    Highlights >=50% discounts with 🔥 BIG DEAL tag."""
    mrp = item.get("mrp", 0) or 0
    price = item.get("price", 0) or 0
    if mrp <= 0 or abs(mrp - price) < 1:
        return f"*₹{price:.0f}*"
    discount = round((mrp - price) / mrp * 100)
    if discount >= 50:
        return f"~₹{mrp:.0f}~ *₹{price:.0f}* 🔥 *{discount}% OFF*"
    elif discount > 0:
        return f"~₹{mrp:.0f}~ *₹{price:.0f}* ({discount}% OFF)"
    return f"*₹{price:.0f}*"


def format_item_for_ai(item: dict) -> str:
    """Compact one-line representation passed to the AI."""
    discount = round((item["mrp"] - item["price"]) / item["mrp"] * 100) if item["mrp"] > 0 else 0
    stock_label = "in stock" if item["stock"] > 0 else "OUT OF STOCK"
    no_disc_note = " | NO DISCOUNT" if discount <= 0 or abs(item["mrp"] - item["price"]) < 1 else ""
    big_deal = " 🔥" if discount >= 50 else ""
    return (
        f"- {item['name']} | MRP ₹{item['mrp']:.0f} | 4U ₹{item['price']:.0f} "
        f"({discount}% off){no_disc_note}{big_deal} | {stock_label} ({item['stock']})"
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
