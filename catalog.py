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
    # Grains / staples
    "cheeni": "sugar", "shakkar": "sugar", "chini": "sugar",
    "doodh": "milk", "dudh": "milk",
    "chawal": "rice", "chaval": "rice", "chaawal": "rice",
    "tel": "oil", "sarso": "mustard oil", "sarson": "mustard oil",
    "namak": "salt", "lon": "salt",
    "chai": "tea", "chaay": "tea", "chay": "tea",
    "anda": "egg", "ande": "egg", "anda packet": "egg",
    "atta": "atta flour", "aata": "atta flour", "gehu": "atta flour",
    "maida": "maida flour",
    "besan": "gram flour besan",
    "dal": "dal lentil", "daal": "dal lentil",
    # Vegetables / fruits
    "pyaaz": "onion", "kanda": "onion",
    "aalu": "potato", "aloo": "potato",
    "tamatar": "tomato",
    "sabzi": "vegetable", "sabji": "vegetable",
    "phal": "fruit", "fal": "fruit",
    # Dairy
    "dahi": "curd", "dahii": "curd",
    "makhan": "butter", "makkhan": "butter",
    "ghee": "ghee", "desi ghee": "ghee",
    "paneer": "paneer", "pneer": "paneer",
    "cream": "cream",
    # Spices
    "haldi": "turmeric", "haldy": "turmeric",
    "mirch": "chilli", "mirchi": "chilli",
    "jeera": "cumin", "zeera": "cumin",
    "dhaniya": "coriander",
    "hing": "asafoetida",
    "elaichi": "cardamom",
    # Snacks / sweets
    "namkeen": "namkeen", "namkin": "namkeen",
    "biscuit": "biscuit", "biskut": "biscuit", "biskit": "biscuit",
    "chocolate": "chocolate", "choco": "chocolate",
    "ice cream": "ice cream icecream", "icecream": "ice cream",
    # Cleaning / personal care
    "sasta": "cheap",
    "wips": "wipes", "wipes": "wipes",
    "saban": "soap", "sabun": "soap", "saabun": "soap",
    "tooth paste": "toothpaste", "toothpest": "toothpaste",
    "manjan": "toothpaste",
    "diaper": "diaper", "nappy": "diaper",
    "coffee": "coffee", "coffe": "coffee",
    "shampoo": "shampoo", "shampu": "shampoo", "shampo": "shampoo",
    "conditioner": "conditioner",
    # Noodles
    "maggi": "maggi noodle", "magi": "maggi noodle", "magii": "maggi noodle",
    # Cleaning
    "phenyl": "phenyl", "fenil": "phenyl",
    "jhadoo": "broom", "jhadu": "broom",
    "pochha": "mop", "pocha": "mop",
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
    "butter": "BUTTER", "makhan": "BUTTER", "makkhan": "BUTTER",
    "amul butter": "BUTTER",
    "ghee": "GHEE", "desi ghee": "GHEE", "pure ghee": "GHEE", "gai ghee": "GHEE",
    "cheese": "CHEESE", "cube cheese": "CHEESE", "cheese slice": "CHEESE",
    "paneer": "DAIRY_OTHER", "cottage cheese": "DAIRY_OTHER",
    "dahi": "DAIRY_OTHER", "curd": "DAIRY_OTHER", "yogurt": "DAIRY_OTHER", "yoghurt": "DAIRY_OTHER",
    "cream": "DAIRY_OTHER", "fresh cream": "DAIRY_OTHER",
    "doodh": "DAIRY_OTHER", "milk": "DAIRY_OTHER", "dairy": "DAIRY_OTHER",
    "amul fresh": "DAIRY_OTHER", "milkmaid": "DAIRY_OTHER",
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
    "biscuit": "BISCUIT", "biscuits": "BISCUIT", "biskut": "BISCUIT", "biskit": "BISCUIT",
    "cookie": "BISCUIT", "cookies": "BISCUIT", "rusk": "BISCUIT", "marie": "BISCUIT",
    "parle g": "BISCUIT", "parle": "BISCUIT", "good day": "BISCUIT", "tiger": "BISCUIT",
    "bourbon": "BISCUIT", "hide and seek": "BISCUIT", "britannia": "BISCUIT",
    "milano": "BISCUIT", "jim jam": "BISCUIT", "dark fantasy": "BISCUIT",
    "glucose biscuit": "BISCUIT", "salty biscuit": "BISCUIT",
    "namkeen": "NAMKEEN_CHIPS", "namkin": "NAMKEEN_CHIPS",
    "chips": "NAMKEEN_CHIPS", "wafers": "NAMKEEN_CHIPS", "wafer": "NAMKEEN_CHIPS",
    "snack": "NAMKEEN_CHIPS", "snacks": "NAMKEEN_CHIPS",
    "kurkure": "NAMKEEN_CHIPS", "bhujia": "NAMKEEN_CHIPS", "sev": "NAMKEEN_CHIPS",
    "lays": "NAMKEEN_CHIPS", "bingo": "NAMKEEN_CHIPS", "doritos": "NAMKEEN_CHIPS",
    "mixture": "NAMKEEN_CHIPS", "gathiya": "NAMKEEN_CHIPS", "papad": "NAMKEEN_CHIPS",
    "haldiram": "NAMKEEN_CHIPS", "bikano": "NAMKEEN_CHIPS",
    "makhana": "NAMKEEN_CHIPS_MAKHANA", "foxnut": "NAMKEEN_CHIPS_MAKHANA",
    "maggi": "NOODLES", "noodles": "NOODLES", "noodle": "NOODLES", "pasta": "NOODLES",
    "macaroni": "NOODLES", "vermicelli": "NOODLES", "sevaiyan": "NOODLES",
    "yippee": "NOODLES", "top ramen": "NOODLES", "chings": "NOODLES",
    "cup noodles": "NOODLES", "instant noodles": "NOODLES", "sooji": "NOODLES",
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
    "kinley": "WATER",
    "mineral water": "WATER", "packaged water": "WATER", "drinking water": "WATER",
    "bottled water": "WATER", "bottle water": "WATER",
    "tea": "TEA_COFFEE", "chai": "TEA_COFFEE", "chaay": "TEA_COFFEE", "chayy": "TEA_COFFEE",
    "coffee": "TEA_COFFEE", "kaapi": "TEA_COFFEE", "bru": "TEA_COFFEE", "nescafe": "TEA_COFFEE",
    "tata tea": "TEA_COFFEE", "taj mahal": "TEA_COFFEE", "tetley": "TEA_COFFEE",
    "green tea": "TEA_COFFEE", "lipton": "TEA_COFFEE", "instant coffee": "TEA_COFFEE",
    "spice": "SPICE", "masala": "SPICE", "haldi": "SPICE", "mirch": "SPICE",
    "jeera": "SPICE", "dhaniya": "SPICE", "hing": "SPICE", "saunf": "SPICE",
    "elaichi": "SPICE", "kalimirch": "SPICE", "ajwain": "SPICE", "methi": "SPICE",
    "garam masala": "SPICE", "chaat masala": "SPICE", "amchur": "SPICE",
    "salt": "SALT", "namak": "SALT", "tata salt": "SALT", "kala namak": "SALT",
    "black salt": "SALT", "rock salt": "SALT", "sendha namak": "SALT", "sendha": "SALT",
    "white salt": "SALT", "iodized salt": "SALT",
    "sugar": "SUGAR", "cheeni": "SUGAR", "shakkar": "SUGAR", "shakar": "SUGAR",
    "white sugar": "SUGAR", "brown sugar": "SUGAR", "mishri": "SUGAR", "misri": "SUGAR",
    "honey": "SUGAR", "shahad": "SUGAR", "madhu": "SUGAR",
    "jaggery": "SUGAR", "gur": "SUGAR", "gud": "SUGAR",
    "oil": "OIL", "oils": "OIL", "tel": "OIL", "refined": "OIL", "refined oil": "OIL",
    "mustard": "OIL", "mustard oil": "OIL", "sarso": "OIL", "sarso ka tel": "OIL",
    "sunflower": "OIL", "sunflower oil": "OIL", "groundnut oil": "OIL",
    "soyabean oil": "OIL", "soybean oil": "OIL", "kachi ghani": "OIL",
    "rice bran oil": "OIL", "olive oil": "OIL", "palm oil": "OIL",
    "fortune": "OIL", "saffola": "OIL", "dhara": "OIL",
    "atta": "ATTA", "aata": "ATTA", "flour": "ATTA", "wheat flour": "ATTA",
    "gehu": "ATTA", "gehun": "ATTA", "chakki atta": "ATTA",
    "maida": "ATTA", "all purpose flour": "ATTA", "fine flour": "ATTA",
    "besan": "ATTA", "gram flour": "ATTA", "chickpea flour": "ATTA",
    "aashirvaad": "ATTA", "fortune atta": "ATTA", "pillsbury": "ATTA",
    "rice": "RICE", "chawal": "RICE", "chaval": "RICE", "basmati": "RICE",
    "basmati rice": "RICE", "long grain": "RICE", "kolam": "RICE",
    "sona masuri": "RICE", "ponni": "RICE", "polish": "RICE",
    "india gate": "RICE", "daawat": "RICE", "kohinoor": "RICE",
    "dal": "DAL", "daal": "DAL", "pulse": "DAL", "pulses": "DAL", "lentils": "DAL",
    "moong": "DAL", "moong dal": "DAL", "chana": "DAL", "chana dal": "DAL",
    "kabuli chana": "DAL", "kala chana": "DAL", "white chana": "DAL",
    "rajma": "DAL", "kidney beans": "DAL",
    "urad": "DAL", "urad dal": "DAL", "masoor": "DAL", "masoor dal": "DAL",
    "tuvar": "DAL", "toor": "DAL", "arhar": "DAL", "arhar dal": "DAL",
    "lobia": "DAL", "matar": "DAL", "green peas": "DAL",
    "soap": "SOAP", "soaps": "SOAP", "saban": "SOAP", "saabun": "SOAP", "sabun": "SOAP",
    "bathing soap": "SOAP", "nahane wala saban": "SOAP",
    "dettol": "SOAP", "lifebuoy": "SOAP", "lux": "SOAP", "dove": "SOAP", "pears": "SOAP",
    "medimix": "SOAP", "cinthol": "SOAP", "margo": "SOAP",
    "handwash": "SOAP", "hand wash": "SOAP", "bodywash": "SOAP", "body wash": "SOAP",
    "shampoo": "HAIR_CARE", "conditioner": "HAIR_CARE", "hair": "HAIR_CARE",
    "face wash": "COSMETIC", "facewash": "COSMETIC", "lotion": "COSMETIC",
    "moisturiser": "COSMETIC", "moisturizer": "COSMETIC", "cream face": "COSMETIC",
    "dish wash": "CLEANING", "dishwash": "CLEANING", "vim": "CLEANING",
    "toothpaste": "ORAL_CARE", "manjan": "ORAL_CARE", "tooth": "ORAL_CARE",
    "brush": "ORAL_CARE", "toothbrush": "ORAL_CARE", "tongue cleaner": "ORAL_CARE",
    "paint brush": "STATIONERY_BRUSH", "art brush": "STATIONERY_BRUSH",
    "toilet brush": "CLEANING_BRUSH",
    "detergent": "DETERGENT", "surf": "DETERGENT", "tide": "DETERGENT", "ariel": "DETERGENT",
    "ghadi": "DETERGENT", "rin": "DETERGENT", "wheel": "DETERGENT", "nirma": "DETERGENT",
    "henko": "DETERGENT", "washing powder": "DETERGENT", "washing soap": "DETERGENT",
    "kapde dhone": "DETERGENT", "kapda dhone": "DETERGENT", "washing bar": "DETERGENT",
    "liquid detergent": "DETERGENT", "matic": "DETERGENT",
    "harpic": "CLEANING", "lizol": "CLEANING", "phenyl": "CLEANING",
    "floor cleaner": "CLEANING", "toilet cleaner": "CLEANING", "bathroom cleaner": "CLEANING",
    "kitchen cleaner": "CLEANING", "dish soap": "CLEANING",
    "dish wash bar": "CLEANING", "dishwashing": "CLEANING", "scrub": "CLEANING",
    "freshener": "CLEANING", "room freshener": "CLEANING", "ambi pur": "CLEANING",
    "pad": "HYGIENE", "pads": "HYGIENE", "wipes": "HYGIENE", "wet wipes": "HYGIENE",
    "whisper": "HYGIENE", "stayfree": "HYGIENE", "sofy": "HYGIENE", "carefree": "HYGIENE",
    "sanitary": "HYGIENE", "sanitary pad": "HYGIENE", "sanitary napkin": "HYGIENE",
    "tampon": "HYGIENE", "ladies pad": "HYGIENE", "feminine": "HYGIENE",
    "face wipes": "HYGIENE", "baby wipes": "HYGIENE",
    "diaper": "BABY", "diapers": "BABY", "pampers": "BABY", "huggies": "BABY",
    "mamy poko": "BABY", "mamypoko": "BABY", "baby": "BABY",
    "baby food": "BABY", "cerelac": "BABY", "pediasure": "BABY", "lactogen": "BABY",
    "baby oil": "BABY", "johnson baby": "BABY", "baby powder": "BABY",
    "toy": "TOY", "toys": "TOY",
    "pen": "STATIONERY", "pencil": "STATIONERY", "copy": "STATIONERY", "notebook": "STATIONERY",
    "eraser": "STATIONERY", "rubber": "STATIONERY", "sharpener": "STATIONERY",
    "scale": "STATIONERY", "marker": "STATIONERY", "highlighter": "STATIONERY",
    "stapler": "STATIONERY", "glue": "STATIONERY", "tape": "STATIONERY",
    "doms": "STATIONERY", "register": "STATIONERY",
    "agarbatti": "POOJA", "incense": "POOJA", "incense stick": "POOJA",
    "diya": "POOJA", "deepak": "POOJA", "kapoor": "POOJA", "camphor": "POOJA",
    "dhoop": "POOJA", "lobaan": "POOJA", "puja samagri": "POOJA", "pooja": "POOJA",
    "matchbox": "POOJA", "match box": "POOJA", "match stick": "POOJA",
    "ganga jal": "POOJA", "havan": "POOJA",
    "bread": "BREAD", "breads": "BREAD", "bun": "BREAD", "burger bun": "BREAD",
    "white bread": "BREAD", "brown bread": "BREAD", "kulcha": "BREAD",
    "breakfast bread": "BREAD", "slice bread": "BREAD", "cake": "BREAD",
    "english oven": "BREAD", "harvest gold": "BREAD",
    "egg": "EGG", "eggs": "EGG", "anda": "EGG", "ande": "EGG",
    "white egg": "EGG", "brown egg": "EGG",
}


# Phrases that LOOK like category keywords but mean something else.
# Returning None pushes the query to AI, which sees the actual catalog matches
# and answers correctly (e.g. 'butter paper' → parchment, not butter).
# Common brand misspellings → canonical brand name
BRAND_TYPO_FIX = {
    # Dairy brands
    "amool": "amul", "amol": "amul", "amul ka": "amul", "ammul": "amul",
    "motherdairy": "mother dairy", "mother dary": "mother dairy",
    # Chocolate / biscuit brands
    "kadbury": "cadbury", "kadberry": "cadbury", "cad bury": "cadbury", "cadbry": "cadbury",
    "dair milk": "dairy milk", "dary milk": "dairy milk", "dairy milc": "dairy milk",
    "good-day": "good day", "goodday": "good day", "gud day": "good day",
    "parle-g": "parle g", "parleg": "parle g", "parle ji": "parle g",
    "dark fantsy": "dark fantasy", "dark fantacy": "dark fantasy",
    "jim-jam": "jim jam", "jimjam": "jim jam",
    "hide n seek": "hide and seek", "hide & seek": "hide and seek",
    # Atta / grain brands
    "ashirvad": "aashirvaad", "ascurvad": "aashirvaad", "ashirwad": "aashirvaad",
    "ashirvaad": "aashirvaad", "aashirvad": "aashirvaad",
    "pilsbury": "pillsbury", "pillsburi": "pillsbury",
    # Snack brands
    "magic": "maggi", "magii": "maggi", "magi": "maggi", "meggi": "maggi",
    "lays chip": "lays", "leys": "lays", "layz": "lays",
    "kurkur": "kurkure", "kurkur e": "kurkure", "kurkurey": "kurkure",
    "haldirams": "haldiram", "haldiram's": "haldiram",
    "bikaner": "bikano", "bikaneri": "bikano",
    # Cleaning brands
    "harpik": "harpic", "harpick": "harpic",
    "viim": "vim", "vimm": "vim",
    "lizal": "lizol", "lysol": "lizol",
    "ghadi detergent": "ghadi",
    # Personal care brands
    "lifebouy": "lifebuoy", "life buoy": "lifebuoy", "lifboy": "lifebuoy",
    "kollgate": "colgate", "colgate ka": "colgate", "colgat": "colgate",
    "pepsident": "pepsodent", "pepsodint": "pepsodent",
    "doove": "dove", "dov": "dove",
    "head n shoulders": "head and shoulders", "h&s": "head and shoulders",
    "clinic plus": "clinic", "clinik": "clinic",
    # Other brands
    "britania": "britannia", "britnia": "britannia", "britaniya": "britannia",
    "nestley": "nestle", "nesle": "nestle", "nestl": "nestle",
    "kit kat": "kitkat", "kit-kat": "kitkat",
    "fortuna": "fortune", "fortune oil": "fortune",
    "saafola": "saffola", "saffolla": "saffola",
    "addilal": "vadilal", "vidilal": "vadilal", "vadilaal": "vadilal",
    "biscut": "biscuit", "biskut": "biscuit", "biskit": "biscuit",
    "shampu": "shampoo", "shampo": "shampoo",
    # Drink brands
    "thums-up": "thums up", "thumsup": "thums up", "thumps up": "thums up",
    "cocacola": "coca cola", "coca-cola": "coca cola",
    "pepsy": "pepsi", "pepsey": "pepsi",
    "fruti": "frooti", "frotii": "frooti",
    "maza": "maaza", "mazaa": "maaza",
    # Tea / coffee
    "tata chai": "tata tea", "taata tea": "tata tea",
    "nescaffe": "nescafe", "nescafey": "nescafe",
}


# Hindi number words → digit
HINDI_NUMBERS = {
    "ek": "1", "do": "2", "teen": "3", "char": "4", "chaar": "4",
    "paanch": "5", "panch": "5", "che": "6", "chh": "6",
    "saat": "7", "saath": "7", "aath": "8", "nau": "9", "naw": "9",
    "das": "10", "dus": "10", "gyaarah": "11", "barah": "12", "bara": "12",
    "ek dum": "1", "ek packet": "1 packet",
    "do packet": "2 packets", "do kg": "2 kg",
    "ek kg": "1 kg", "aadha kg": "0.5 kg", "aadha": "0.5",
    "paav kg": "0.25 kg", "paav": "0.25",
    "dher saara": "10",
}


def normalize_query(text: str) -> str:
    """Apply brand-typo fixes + Hindi number translation BEFORE any matching."""
    if not text:
        return text
    t = text.lower()
    # Brand typos (longest first to avoid partial matches)
    for typo, fix in sorted(BRAND_TYPO_FIX.items(), key=lambda x: -len(x[0])):
        t = t.replace(typo, fix)
    # Hindi numbers (whole-word match)
    import re as _re
    for word, digit in sorted(HINDI_NUMBERS.items(), key=lambda x: -len(x[0])):
        t = _re.sub(r'\b' + _re.escape(word) + r'\b', digit, t)
    return t


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


def search_catalog_raw(query: str, limit: int = 30):
    """Original search (no normalization). Used internally.

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
    """Short price tag: our price first (bold), then MRP struck if discounted."""
    mrp = item.get("mrp", 0) or 0
    price = item.get("price", 0) or 0
    if mrp <= 0 or abs(mrp - price) < 1:
        return f"*₹{price:.0f}*"
    discount = round((mrp - price) / mrp * 100)
    if discount >= 50:
        return f"*₹{price:.0f}* ~₹{mrp:.0f}~ 🔥{discount}%OFF"
    elif discount > 0:
        return f"*₹{price:.0f}* ~₹{mrp:.0f}~ {discount}%OFF"
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


def search_catalog(query: str, limit: int = 30):
    """Public search — normalizes query (brand typos + Hindi numbers) first."""
    return search_catalog_raw(normalize_query(query), limit=limit)


# Catalog stats for runtime sanity
def _stats():
    n = len(CATALOG)
    in_stock = sum(1 for i in CATALOG if i["stock"] > 0)
    return f"Catalog loaded: {n} items, {in_stock} in stock"


print(_stats())
