"""One-time script: tag every catalog item with a single category.

Run this whenever you re-export from Marg. It rewrites catalog_data.json
in place, adding a "category" field to each item.

Order matters — first matching rule wins. Most specific rules go first.
"""
import json
import re
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "catalog_data.json")


# ── Rules ──
# Each rule: (category_name, predicate(name_upper) -> bool)
# Specific rules first; broad ones last.

def _has_word(name: str, *words) -> bool:
    """Match if any of the words appears as a whole token (or hyphen-separated)."""
    parts = re.split(r"[\s\-/.,]+", name)
    return any(w in parts for w in words)


def _has_substring(name: str, *fragments) -> bool:
    return any(f in name for f in fragments)


RULES = [
    # POPCORN — must come before BUTTER (contains "BUTTER")
    ("POPCORN", lambda n: (
        n.startswith(("ACT II ", "ACT-II ", "ACTII ", "AMERICANA FLICK ", "4700BC "))
        or _has_word(n, "POPCORN", "POPS")
    )),

    # ICE CREAM — before CHOCOLATE, before CREAM
    ("ICE_CREAM", lambda n: _has_substring(n, "ICE CREAM", "ICECREAM", "KULFI") or n.startswith("VADILAL ")),

    # BISCUIT / COOKIE — must come before BUTTER (Butter Bite/Sticks/Jeera are biscuits, not dairy)
    ("BISCUIT", lambda n: _has_word(n, "BISCUIT", "BISCUITS", "BIKIS", "COOKIE", "COOKIES",
                                      "KRACK", "MARIE", "RUSK")
        or n.startswith(("MCVITIES ", "PRIYAGOLD ", "BRITANNIA ", "PARLE ", "BRITANIA "))
        or _has_substring(n, "GOOD DAY", "PARLE G", "PARLE-G", "BOURBON", "TIGER GLUCOSE", "MILANO",
                          "JIM JAM", "HIDE & SEEK", "TREAT JIM", "BR ", "AMERICANA BISCUIT",
                          "AMERICANA BOON", "BUTTER STICKS", "BUTTER BITE", "BUTTER JEERA",
                          "BUTTER COOKIE", "BUTTER COOKIES", "KARTAR BUTTER")),

    # MAKHANA (foxnut snacks) — NOT butter
    ("NAMKEEN_CHIPS_MAKHANA", lambda n: _has_word(n, "MAKHANA", "MAKHAANE", "FOXNUT", "FOX NUT")),

    # CHOCOLATE — before DAIRY (DAIRY MILK is chocolate)
    ("CHOCOLATE", lambda n: _has_word(n, "CHOCOLATE", "CHOCO", "CHOCS", "CHOCOMINIS", "KITKAT", "ECLAIRS", "CADBURY",
                                       "DAIRYMILK", "PERK", "FIVESTAR", "MUNCH", "GEMS", "TOBLERONE",
                                       "FERRERO", "NUTELLA", "BOURNVITA", "MILKYBAR")
        or _has_substring(n, "DAIRY MILK", "5 STAR", "FIVE STAR", "DARK CHOCLATE", "DARK CHOCOLATE", "CHOCOMINIS",
                          "F&N DARK", "BELIGIAN CHOC", "BELGIAN CHOC")),

    # NAMKEEN / CHIPS / SNACKS
    ("NAMKEEN_CHIPS", lambda n: _has_word(n, "NAMKEEN", "CHIPS", "KURKURE", "PUFF", "PUFFS", "MIXTURE",
                                          "BHUJIA", "MOONG", "SEV", "WAFER", "WAFERS", "PAPAD", "MATHRI",
                                          "FUNYUNS", "DORITOS", "LAYS", "BINGO")
        or _has_substring(n, "KHATTA M", "KHATTA-M", "KHATTA METHA", "KURE KURE", "ALOO BHUJIA")),

    # MAGGI / NOODLES
    ("NOODLES", lambda n: _has_word(n, "MAGGI", "NOODLES", "PASTA", "MACARONI", "VERMICELLI", "SOOJI")),

    # JUICE / SOFT DRINK / COLD
    ("DRINK_COLD", lambda n: _has_word(n, "JUICE", "COKE", "PEPSI", "SPRITE", "FANTA", "MAAZA", "MIRINDA",
                                        "THUMS", "LIMCA", "LASSI", "SHAKE", "SHAKES", "KOOL", "FROOTI",
                                        "REAL", "TROPICANA", "B-FAST", "SODA")
        or _has_substring(n, "ICED TEA", "COLD COFFEE")),

    # WATER — strictly bottled drinking water. Excludes face washes/melons/etc.
    ("WATER", lambda n: (
        _has_word(n, "BISLERI", "AQUAFINA", "KINLEY", "BAILLEY", "OXYRICH", "HIMALAYAN")
        or _has_substring(n, "MINERAL WATER", "DRINKING WATER", "PACKAGED WATER")
    ) and not _has_word(n, "MELON", "GEL", "FACE", "WASH", "BODY", "HAIR")),

    # DRINK_PANI — flavored drink mixes (Nimbu pani, Jal jeera) + pani-puri ingredients
    ("DRINK_PANI", lambda n: _has_substring(
        n, "NIMBU PANI", "JAL JEERA", "JALJEERA", "PANI PURI", "GOL GAPPA",
        "SHIKANJI", "GLUCAN", "GLUCO", "ELECTORAL", "ELECTRAL", "ENERZAL", "GLUCON")),

    # ORAL_CARE — toothbrushes only when paired with dental keywords. Random "BRUSH" items don't qualify.
    ("ORAL_CARE", lambda n: _has_word(n, "TOOTHPASTE", "MANJAN", "COLGATE",
                                          "PEPSODENT", "CLOSEUP", "SENSODYNE", "DABUR RED",
                                          "LISTERINE", "MOUTHWASH")
        or _has_substring(n, "TOOTH BRUSH", "TOOTHBRUSH", "TONGUE CLEAN", "ORAL-B", "ORAL B",
                          "DENTAL", "MOUTH WASH")),

    # ART/PAINT BRUSHES → STATIONERY
    ("STATIONERY_BRUSH", lambda n: _has_word(n, "BRUSH") and _has_word(
        n, "PEN", "PAINT", "ART", "DRAWING", "DOMS", "OPERA",
        "WATERCOLOR", "BRW", "FLAIR", "MICKEY", "CREATIVE", "COLOUR", "COLOR")),

    # TOILET / SHOE / OTHER CLEANING BRUSHES
    ("CLEANING_BRUSH", lambda n: _has_word(n, "BRUSH") and _has_word(
        n, "TOILET", "BOSS", "SHOE", "BOOTS", "SHAVE")),

    # TEA / COFFEE
    ("TEA_COFFEE", lambda n: _has_word(n, "TEA", "COFFEE", "BRU", "NESCAFE", "TAJ", "TAAZA",
                                        "TATA", "CHAI", "GREEN")
        and not _has_word(n, "BISCUIT", "JUICE", "ICED")),

    # SOAP / SHAMPOO / COSMETIC / CLEANING — all BEFORE DAIRY (would otherwise leak)

    ("SOAP", lambda n: _has_word(n, "SOAP", "SAABUN", "SABUN")),

    ("HAIR_CARE", lambda n: _has_word(n, "SHAMPOO", "CONDITIONER")
        or _has_substring(n, "HEAD & SHOULDER", "HEAD AND SHOULDER", "SUNSILK", "PANTENE",
                          "TRESEMME", "CLINIC PLUS", "DABUR AMLA", "PARACHUTE", "HAIR OIL")),

    ("COSMETIC", lambda n: _has_word(n, "LAKME", "FACEWASH", "LOTION", "MOTRISER", "MOISTURISER",
                                       "MOISTURIZER", "FAIRNESS", "POND", "PONDS", "GARNIER",
                                       "FACE", "BODY")
        or _has_substring(n, "FAIR & LOVELY", "GLOW & ", "FACE WASH", "BODY LOTION", "PEACH MILK",
                          "BODY POLISH", "BODY MILK", "SILKY SOFT")),

    ("CLEANING", lambda n: _has_word(n, "HARPIC", "LIZOL", "VIM", "PRIL", "EXO", "GENTEEL",
                                       "PHENYL", "FRESHENER", "REFILL")
        or _has_substring(n, "AMBI PUR", "AMBIPUR", "DISH WASH", "TOILET CLEAN", "FLOOR CLEAN",
                          "ROOM FRESH", "CAR FRESH")),

    # GHEE
    ("GHEE", lambda n: _has_word(n, "GHEE")),

    # BUTTER — pure dairy butter only. Biscuits and makhanas filtered out above.
    ("BUTTER", lambda n: _has_word(n, "BUTTER", "MAKHAN")
        and not _has_word(n, "BADAM", "PEANUT")
        and not _has_substring(n, "STICKS", "BITE", "COOKIE", "JEERA")  # biscuit shapes
        ),

    ("CHEESE", lambda n: _has_word(n, "CHEESE")),

    # DAIRY_OTHER — strict: only explicit dairy words
    ("DAIRY_OTHER", lambda n: _has_word(n, "PANEER", "DAHI", "CURD", "DOODH", "LASSI", "MILKMAID")
        or _has_substring(n, "AMUL FRESH CREAM", "AMUL DAHI", "MOTHER DAIRY", "AMUL TAAZA",
                          "AMUL GOLD", "AMUL KOOL", "TONED MILK", "FULL CREAM MILK")),

    # SPICES
    ("SPICE", lambda n: _has_word(n, "HALDI", "MIRCH", "JEERA", "DHANIYA", "MASALA", "GARAM", "HING",
                                    "ELAICHI", "LAUNG", "DALCHINI", "KESAR", "SAUNF", "AJWAIN",
                                    "METHI", "SARSON", "AMCHUR", "KALIMIRCH", "KALONJI", "SABAT")
        or _has_substring(n, "PAV BHAJI", "CHAT MASALA", "CHAAT MASALA")),

    # SALT
    ("SALT", lambda n: _has_word(n, "SALT", "NAMAK", "TATA")),

    # SUGAR / SWEETENER
    ("SUGAR", lambda n: _has_word(n, "SUGAR", "CHEENI", "SHAKKAR", "JAGGERY", "GUR", "HONEY", "SHAHAD")),

    # OIL
    ("OIL", lambda n: _has_word(n, "OIL", "REFINED", "MUSTARD", "SUNFLOWER", "GROUNDNUT", "SOYABEAN", "TEL")
        and not _has_word(n, "HAIR", "MASSAGE", "BABY")),  # exclude hair oil

    # ATTA / FLOUR
    ("ATTA", lambda n: _has_word(n, "ATTA", "FLOUR", "MAIDA", "BESAN", "RAVA")),

    # RICE
    ("RICE", lambda n: _has_word(n, "RICE", "BASMATI", "CHAWAL", "POHA", "MURMURA")),

    # DAL / PULSE
    ("DAL", lambda n: _has_word(n, "DAL", "MOONG", "CHANA", "RAJMA", "URAD", "MASOOR", "LOBIA", "MATAR", "TUVAR", "TOOR")),

    # SOAP
    ("SOAP", lambda n: _has_word(n, "SOAP", "SAABUN", "DETTOL", "LIFEBUOY", "DOVE", "LUX", "PEARS",
                                   "MEDIMIX", "CINTHOL", "MARGO", "GODREJ NO")
        and not _has_word(n, "DETERGENT", "WASH", "DISH", "POWDER")),

    # SHAMPOO / CONDITIONER / HAIR
    ("HAIR_CARE", lambda n: _has_word(n, "SHAMPOO", "CONDITIONER", "HAIR")
        or _has_substring(n, "HEAD & SHOULDER", "HEAD AND SHOULDER", "SUNSILK", "PANTENE",
                          "TRESEMME", "CLINIC PLUS", "DABUR AMLA", "PARACHUTE")),

    # (ORAL_CARE rule already declared earlier — removed duplicate that was
    #  miscategorising any item containing "BRUSH")

    # DETERGENT
    ("DETERGENT", lambda n: _has_word(n, "DETERGENT", "WASH", "SURF", "TIDE", "ARIEL", "GHADI", "WHEEL",
                                        "RIN", "NIRMA", "HENKO")
        or _has_substring(n, "WASHING POWDER", "WASHING LIQUID")),

    # CLEANING / DISHWASH
    ("CLEANING", lambda n: _has_word(n, "HARPIC", "LIZOL", "VIM", "PRIL", "EXO", "GENTEEL", "SCRUB")
        or _has_substring(n, "DISH WASH", "TOILET CLEAN", "FLOOR CLEAN")),

    # SANITARY / HYGIENE
    ("HYGIENE", lambda n: _has_word(n, "WIPE", "WIPES", "PAD", "PADS", "WHISPER", "STAYFREE",
                                      "SOFY", "TAMPON", "MAXI", "ULTRA")),

    # DIAPER / BABY
    ("BABY", lambda n: _has_word(n, "DIAPER", "DIAPERS", "PAMPERS", "HUGGIES", "MAMYPOKO", "BABY")),

    # TOY
    ("TOY", lambda n: _has_word(n, "TOY", "TOYS")
        or n.startswith(("ANAND ", "ANAM "))
        or _has_substring(n, "TRACTOR", "BUS 3+", "THAR 3+")),

    # STATIONERY
    ("STATIONERY", lambda n: _has_word(n, "PEN", "PENCIL", "ERASER", "RUBBER", "COPY", "REGISTER",
                                         "NOTEBOOK", "STAPLER", "GLUE", "TAPE", "MARKER", "HIGHLIGHTER",
                                         "SHARPENER", "SCALE")
        or n.startswith(("DOMS ", "CLASSMATE ", "CAMLIN "))),

    # COSMETIC / FACE
    ("COSMETIC", lambda n: _has_word(n, "CREAM", "FACE", "LOTION", "SCRUB", "FAIR", "POND")
        or _has_substring(n, "FAIR & LOVELY", "GARNIER", "LAKME")),

    # AGARBATTI / POOJA
    ("POOJA", lambda n: _has_word(n, "AGARBATTI", "INCENSE", "DHOOP", "DIYA", "CAMPHOR", "KAPOOR")),

    # BREAD / BAKERY
    ("BREAD", lambda n: _has_word(n, "BREAD", "BUN", "CAKE", "MUFFIN", "PIZZA", "BURGER")),

    # EGG
    ("EGG", lambda n: _has_word(n, "EGG", "EGGS", "ANDA")),
]


def categorize(name: str) -> str:
    n = name.upper()
    for cat, pred in RULES:
        try:
            if pred(n):
                return cat
        except Exception:
            continue
    return "OTHER"


def main():
    with open(DATA) as f:
        items = json.load(f)

    counts = {}
    for item in items:
        c = categorize(item["name"])
        item["category"] = c
        counts[c] = counts.get(c, 0) + 1

    with open(DATA, "w") as f:
        json.dump(items, f, ensure_ascii=False)

    print(f"✅ Categorized {len(items)} items")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:20} {v:4}")


if __name__ == "__main__":
    main()
