import re
import difflib
from dataclasses import dataclass
from typing import Any
from django.db.models import Q
from core.models import Product

# 25 authoritative catalogue vehicle fitments with common aliases and typo variants
KNOWN_VEHICLES = {
    "Bajaj Dominar 400": ["bajaj dominar 400", "dominar 400", "dominar400", "dominar"],
    "Bajaj Pulsar 150": ["bajaj pulsar 150", "pulsar 150", "pulsar150", "p150", "pulsar-150"],
    "Bajaj Pulsar NS200": ["bajaj pulsar ns200", "pulsar ns200", "pulsarns200", "pulsar ns 200", "ns200", "ns 200", "pulsar-ns200"],
    "Hero Splendor Plus": ["hero splendor plus", "splendor plus", "splendor+", "splendour plus", "splendour+", "splendor", "splendour"],
    "Hero Xtreme 160R": ["hero xtreme 160r", "xtreme 160r", "xtreme 160", "xtreme160r", "xtreme"],
    "Honda Hornet 2.0": ["honda hornet 2.0", "hornet 2.0", "hornet 2", "hornet2.0", "hornet"],
    "Honda Shine 125": ["honda shine 125", "shine 125", "cb shine", "shine125", "shine"],
    "Hyundai Creta": ["hyundai creta", "creta"],
    "Hyundai i20": ["hyundai i20", "i20"],
    "KTM Duke 200": ["ktm duke 200", "duke 200", "duke200"],
    "KTM Duke 390": ["ktm duke 390", "duke 390", "duke390"],
    "Mahindra Thar": ["mahindra thar", "thar"],
    "Maruti Baleno": ["maruti baleno", "baleno"],
    "Maruti Swift": ["maruti swift", "swift"],
    "Royal Enfield Classic 350": ["royal enfield classic 350", "classic 350", "classic350", "bullet 350", "re classic 350", "classic"],
    "Royal Enfield Himalayan 450": ["royal enfield himalayan 450", "himalayan 450", "himalayan450", "re himalayan", "himalayan"],
    "Royal Enfield Hunter 350": ["royal enfield hunter 350", "hunter 350", "hunter350", "re hunter", "hunter"],
    "Suzuki Gixxer SF": ["suzuki gixxer sf", "gixxer sf", "gixxersf", "gixxer"],
    "TVS Apache RTR 160": ["tvs apache rtr 160", "apache rtr 160", "apache 160", "rtr 160", "rtr160"],
    "TVS Apache RTR 200": ["tvs apache rtr 200", "apache rtr 200", "apache 200", "rtr 200", "rtr200"],
    "Tata Nexon": ["tata nexon", "nexon"],
    "Universal": ["universal", "all bikes", "universal fit", "all motorcycles"],
    "Yamaha FZ-S": ["yamaha fz-s", "yamaha fzs", "yamaha fz", "fz-s", "fzs", "fz"],
    "Yamaha MT-15": ["yamaha mt-15", "yamaha mt 15", "mt-15", "mt 15", "mt15"],
    "Yamaha R15 V4": ["yamaha r15 v4", "yamaha r15", "r15 v4", "r15v4", "r15"],
}

# Vehicle families where query specifies umbrella model without exact displacement
VEHICLE_FAMILIES = {
    "pulsar": ["Bajaj Pulsar 150", "Bajaj Pulsar NS200"],
    "duke": ["KTM Duke 200", "KTM Duke 390"],
    "apache": ["TVS Apache RTR 160", "TVS Apache RTR 200"],
    "enfield": ["Royal Enfield Classic 350", "Royal Enfield Himalayan 450", "Royal Enfield Hunter 350"],
    "splendor": ["Hero Splendor Plus"],
    "shine": ["Honda Shine 125"],
    "hornet": ["Honda Hornet 2.0"],
    "xtreme": ["Hero Xtreme 160R"],
    "gixxer": ["Suzuki Gixxer SF"],
    "r15": ["Yamaha R15 V4"],
    "mt15": ["Yamaha MT-15"],
    "fz": ["Yamaha FZ-S"],
}

# Vehicles explicitly NOT in catalogue — used for unambiguous rejection & zero-hallucination
NON_CATALOGUE_VEHICLES = [
    "activa", "honda activa", "activa 6g", "activa 125",
    "jupiter", "tvs jupiter",
    "access", "access 125", "suzuki access",
    "dio", "honda dio",
    "passion", "hero passion",
    "platina", "bajaj platina",
    "glamour", "hero glamour",
    "chetak", "bajaj chetak",
    "scooter",
    "interceptor", "continental gt", "bullet 500",
    "swift", "maruti swift", "car", "cars",
]

# 40 authoritative catalogue brands
CATALOGUE_BRANDS = [
    "3M", "Amaron", "Apollo", "Bosch", "Brembo", "CEAT", "Castrol", "DID",
    "Denso", "Domino", "Endurance", "Exide", "Galfer", "Godrej", "Hella",
    "K&N", "Liqui Moly", "Lumax", "MRF", "Mahle", "Michelin", "Moto Torque",
    "Motul", "NGK", "Portronics", "Progrip", "Purolator", "RK", "Rammount",
    "Rolon", "Rynox", "Shell", "Solace", "Steelbird", "Studds", "TVS Girling",
    "Tukzer", "Uno Minda", "Vega", "Zana"
]

# 11 authoritative catalogue categories
CATALOGUE_CATEGORIES = [
    "Body & Styling", "Brakes", "Car Care", "Controls & Grips", "Drivetrain",
    "Engine & Oils", "Filters", "Lighting & Electrical", "Rider Gear",
    "Tyres & Tubes", "Universal Accessories"
]

# 32 base part types in the catalogue with extensive synonym, typo, and plural mappings
PART_TYPES = {
    "Tubeless Tyre": [
        "tubeless tyre", "tubeless tire", "tubeless tyres", "tubeless tires",
        "tubeless", "tubless", "tubeles", "tubles", "tubelesss",
        "tyre", "tyres", "tire", "tires"
    ],
    "Brake Pad Set": [
        "brake pad set", "brake pad", "brake pads", "brake pad sets",
        "break pad", "break pads", "brak pad", "brak pads", "disc pad", "disc pads",
        "pad set", "pads", "pad"
    ],
    "Brake Disc Rotor": [
        "brake disc rotor", "brake disc", "brake rotor", "disc rotor",
        "brake disk", "brake disks", "disc rotors", "rotor", "rotors"
    ],
    "Brake Shoe Set": [
        "brake shoe set", "brake shoe", "brake shoes", "shoe set", "drum brake", "drum shoes"
    ],
    "Brake Lever": [
        "brake lever", "brake levers", "clutch lever", "clutch levers", "lever set", "lever", "levers"
    ],
    "Brake Fluid DOT4 500ml": [
        "brake fluid dot4", "brake fluid", "dot4", "dot 4", "brake oil"
    ],
    "Chain Sprocket Kit": [
        "chain sprocket kit", "chain sprocket", "sprocket kit", "sprocket", "sprockets",
        "chain kit", "sproket", "sprokets"
    ],
    "Drive Chain": [
        "drive chain", "chain drive", "drive chains", "motorcycle chain", "chain", "chains"
    ],
    "Chain Lube 400ml": [
        "chain lube 400ml", "chain lube", "chain lubricant", "lube spray", "chain lubrication"
    ],
    "Chain Cleaner Spray 500ml": [
        "chain cleaner spray", "chain cleaner", "cleaner spray"
    ],
    "Clutch Plate Set": [
        "clutch plate set", "clutch plate", "clutch plates", "clutch kit", "clutch friction plate"
    ],
    "Air Filter": [
        "air filter", "air filters", "airfilter", "air cleaner"
    ],
    "Oil Filter": [
        "oil filter", "oil filters", "oilfilter"
    ],
    "Spark Plug": [
        "spark plug", "spark plugs", "sparkplug", "sparkplugs", "plug", "plugs"
    ],
    "Engine Oil": [
        "engine oil", "motor oil", "mobil", "lubricant", "4t oil", "10w30", "10w-30", "20w40", "20w-40"
    ],
    "Coolant 1L": [
        "coolant 1l", "coolant", "radiator coolant", "antifreeze"
    ],
    "LED Headlight": [
        "led headlight", "headlight", "headlights", "head light", "head lights",
        "headlamp", "headlamps", "front headlight"
    ],
    "LED Indicator Set": [
        "led indicator set", "led indicator", "led indicators", "indicator set",
        "indicator", "indicators", "turn indicator", "turn indicators", "blinker", "blinkers"
    ],
    "Battery": [
        "battery", "batteries", "bike battery", "12v battery", "car battery"
    ],
    "Side Mirror Set": [
        "side mirror set", "side mirror", "side mirrors", "rear view mirror",
        "rearview mirror", "rearview", "rear view", "mirror", "mirrors"
    ],
    "Crash Guard": [
        "crash guard", "crash guards", "leg guard", "leg guards", "engine guard"
    ],
    "Tank Pad": [
        "tank pad", "tank pads", "tankpad", "tankpads", "tank protector", "tank sticker"
    ],
    "Handle Grip Set": [
        "handle grip set", "handle grip", "handle grips", "hand grip", "hand grips",
        "grip set", "grips", "grip", "handlebar grips"
    ],
    "Foot Peg Set": [
        "foot peg set", "foot peg", "foot pegs", "footpeg", "footpegs", "foot rest", "footrest"
    ],
    "Full Face Helmet": [
        "full face helmet", "helmet", "helmets", "headgear"
    ],
    "Riding Gloves": [
        "riding gloves", "riding glove", "biker gloves", "gloves", "glove"
    ],
    "Riding Jacket": [
        "riding jacket", "biker jacket", "jacket", "jackets"
    ],
    "Bike Body Cover": [
        "bike body cover", "body cover", "bike cover", "covers", "dust cover"
    ],
    "Mobile Holder": [
        "mobile holder", "phone holder", "mobile mount", "phone mount"
    ],
    "Wiper Blade Set": [
        "wiper blade set", "wiper blade", "wiper blades", "wiper", "wipers"
    ],
    "Car Floor Mat Set": [
        "car floor mat set", "floor mat set", "floor mat", "floor mats", "car mat", "car mats"
    ],
}

# Automotive parts and non-automotive domains that do NOT exist in the product catalogue
UNSUPPORTED_DOMAINS_AND_PARTS = [
    "shocker", "shock absorber", "shock absorbers", "monoshock", "suspension",
    "carburetor", "carburettor", "fuel injector", "silencer", "exhaust",
    "piston", "cylinder", "chassis", "frame", "cable", "cables", "clutch cable",
    "accelerator cable", "speedometer cable",
    "helicopter", "airplane", "aeroplane", "boat", "laptop", "phone screen",
    "drone", "rocket"
]

# Word-level typo and synonym normalization dictionary
WORD_SYNONYMS = {
    "tubless": "tubeless",
    "tubeles": "tubeless",
    "tubles": "tubeless",
    "tubelesss": "tubeless",
    "tire": "tyre",
    "tires": "tyre",
    "break": "brake",
    "breaks": "brake",
    "brak": "brake",
    "braks": "brake",
    "shocker": "shock absorber",
    "shockers": "shock absorber",
    "shox": "shock absorber",
    "airfilter": "air filter",
    "oilfilter": "oil filter",
    "sparkplug": "spark plug",
    "sparkplugs": "spark plug",
    "sproket": "sprocket",
    "sprokets": "sprocket",
    "headlamp": "headlight",
    "headlamps": "headlight",
    "taillamp": "tail light",
    "taillamps": "tail light",
    "blinker": "indicator",
    "blinkers": "indicator",
    "rearview": "mirror",
    "footpeg": "foot peg",
    "footpegs": "foot peg",
    "tankpad": "tank pad",
    "tankpads": "tank pad",
    "mobil": "engine oil",
    "lubricant": "engine oil",
}


@dataclass
class ParsedQuery:
    raw_query: str
    cleaned_query: str
    detected_sku: str | None
    target_vehicle: str | None
    target_family: str | None
    is_non_catalogue_vehicle: bool
    non_catalogue_vehicle_name: str | None
    target_part_type: str | None
    target_category: str | None
    target_brand: str | None
    is_unsupported_part: bool
    unsupported_part_name: str | None
    tokens: list[str]


def normalize_query_text(text: str) -> str:
    """Performs safe, case-folded, punctuation-stripped normalization."""
    if not text:
        return ""
    s = text.lower()
    # Strip common punctuation except hyphens in SKUs/models
    s = re.sub(r"[^\w\s\-]", " ", s)
    # Remove conversational filler words
    filler_patterns = [
        r"\b(do you have|do you stock|do you carry|can i get|can you give me)\b",
        r"\b(i want|i need|looking for|search for|find me|show me|tell me about)\b",
        r"\b(what is the price of|price of|cost of|how much is)\b",
        r"\b(check stock for|check availability of|is there any)\b",
        r"\b(please|kindly|available|stock|parts?|spares?|items?|products?)\b",
        r"\b(hello|hi|hey|thanks|thank you)\b",
    ]
    for pattern in filler_patterns:
        s = re.sub(pattern, " ", s)
    return " ".join(s.split())


def parse_query(query: str = "", vehicle_hint: str = None, category_hint: str = None) -> ParsedQuery:
    """Extracts entities, vehicle fitment, part type, and brand from query."""
    raw = query or ""
    q_lower = raw.lower()

    # 1. Detect explicit SKU (e.g. BRK-1044, TYR-1003)
    sku_match = re.search(r"\b([A-Z]{3}-[A-Za-z0-9\-]+)\b", raw)
    detected_sku = sku_match.group(1).upper() if sku_match else None

    # 2. Check for unsupported parts or domains
    is_unsupported_part = False
    unsupported_part_name = None
    for up in UNSUPPORTED_DOMAINS_AND_PARTS:
        if re.search(rf"\b{re.escape(up)}\b", q_lower):
            is_unsupported_part = True
            unsupported_part_name = up
            break

    # 3. Check for explicitly non-catalogue vehicles (e.g. Activa, Jupiter)
    is_non_cat_veh = False
    non_cat_veh_name = None
    for ncv in NON_CATALOGUE_VEHICLES:
        if re.search(rf"\b{re.escape(ncv)}\b", q_lower):
            is_non_cat_veh = True
            non_cat_veh_name = ncv.title()
            break

    # 4. Detect catalogue vehicle or vehicle family
    detected_vehicle = None
    detected_family = None

    # Check vehicle hint first
    if vehicle_hint:
        vh_clean = vehicle_hint.strip().lower()
        for vname, aliases in KNOWN_VEHICLES.items():
            if vh_clean == vname.lower() or any(vh_clean == a for a in aliases):
                detected_vehicle = vname
                break
        if not detected_vehicle:
            for fam, members in VEHICLE_FAMILIES.items():
                if fam in vh_clean:
                    detected_family = fam
                    break

    # Check in query text if not resolved by hint
    if not detected_vehicle and not detected_family:
        # Match longest vehicle alias first
        all_aliases = []
        for vname, aliases in KNOWN_VEHICLES.items():
            for a in aliases:
                all_aliases.append((a, vname))
        all_aliases.sort(key=lambda x: len(x[0]), reverse=True)

        for a, vname in all_aliases:
            if re.search(rf"\b{re.escape(a)}\b", q_lower):
                detected_vehicle = vname
                break

    if not detected_vehicle and not detected_family:
        for fam, members in VEHICLE_FAMILIES.items():
            if re.search(rf"\b{re.escape(fam)}\b", q_lower):
                detected_family = fam
                break

    # 5. Detect Part Type
    detected_part_type = None
    all_part_keywords = []
    for pt, kws in PART_TYPES.items():
        for kw in kws:
            all_part_keywords.append((kw, pt))
    all_part_keywords.sort(key=lambda x: len(x[0]), reverse=True)

    for kw, pt in all_part_keywords:
        if re.search(rf"\b{re.escape(kw)}\b", q_lower):
            detected_part_type = pt
            break

    # 6. Detect Category
    detected_category = None
    if category_hint:
        for cat in CATALOGUE_CATEGORIES:
            if category_hint.strip().lower() == cat.lower():
                detected_category = cat
                break
    if not detected_category:
        for cat in CATALOGUE_CATEGORIES:
            if re.search(rf"\b{re.escape(cat.lower())}\b", q_lower):
                detected_category = cat
                break

    # 7. Detect Brand
    detected_brand = None
    for b in sorted(CATALOGUE_BRANDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(b.lower())}\b", q_lower):
            detected_brand = b
            break

    # 8. Clean tokens
    cleaned = normalize_query_text(raw)
    tokens = [w for w in cleaned.split() if len(w) > 2]

    return ParsedQuery(
        raw_query=raw,
        cleaned_query=cleaned,
        detected_sku=detected_sku,
        target_vehicle=detected_vehicle,
        target_family=detected_family,
        is_non_catalogue_vehicle=is_non_cat_veh,
        non_catalogue_vehicle_name=non_cat_veh_name,
        target_part_type=detected_part_type,
        target_category=detected_category,
        target_brand=detected_brand,
        is_unsupported_part=is_unsupported_part,
        unsupported_part_name=unsupported_part_name,
        tokens=tokens,
    )


def hybrid_search_parts(
    query: str = "",
    vehicle: str = None,
    category: str = None,
    limit: int = 5
) -> list[dict]:
    """Retrieves and ranks relevant catalogue products from PostgreSQL using multi-signal hybrid scoring.
    
    Signals combined:
    1. Exact SKU match (highest priority, score 1.0)
    2. Vehicle fitment alignment (confirmed vs universal vs incompatible)
    3. Part type & category matching with synonym/typo expansion
    4. Brand alignment
    5. PostgreSQL Trigram similarity / lexical token matching
    
    Guarantees:
    - 100% grounded in PostgreSQL live data.
    - Zero hallucinations: returns [] for unsupported parts or vehicles.
    - Returns fitment status: 'confirmed', 'universal', 'possible', 'incompatible', or 'unspecified'.
    """
    parsed = parse_query(query=query, vehicle_hint=vehicle, category_hint=category)

    # 1. If an explicitly non-catalogue vehicle was requested (e.g. Activa, Jupiter),
    # return empty to prevent claiming false compatibility.
    if parsed.is_non_catalogue_vehicle:
        return []

    # 2. If an unsupported part or domain was requested (e.g. shocker, carburetor, helicopter),
    # return empty to prevent returning unrelated parts.
    if parsed.is_unsupported_part:
        return []

    # 3. Direct SKU lookup
    if parsed.detected_sku:
        qs = Product.objects.filter(sku__iexact=parsed.detected_sku).select_related("inventory")
        if qs.exists():
            p = qs.first()
            return [{
                "sku": p.sku,
                "name": p.name,
                "category": p.category,
                "brand": p.brand,
                "vehicle_fitment": p.vehicle_fitment,
                "price": f"{p.price:.2f}",
                "stock": p.stock,
                "description": p.description,
                "confidence_score": 1.0,
                "is_compatible": True,
                "fitment_status": "confirmed",
            }]
        # If user explicitly asked for a SKU that does not exist in the DB, return empty
        return []

    # 4. Build Candidate QuerySet in PostgreSQL
    qs = Product.objects.select_related("inventory").all()

    # Part Type or Category constraint
    if parsed.target_part_type:
        if parsed.target_part_type == "Engine Oil":
            qs = qs.filter(name__icontains="Engine Oil")
        else:
            qs = qs.filter(name__icontains=parsed.target_part_type)
    elif parsed.target_category:
        qs = qs.filter(category__iexact=parsed.target_category)

    # Brand constraint / filter
    if parsed.target_brand:
        brand_qs = qs.filter(brand__iexact=parsed.target_brand)
        if brand_qs.exists():
            qs = brand_qs

    # Vehicle constraint
    target_vehicles = []
    if parsed.target_vehicle:
        target_vehicles = [parsed.target_vehicle]
    elif parsed.target_family:
        target_vehicles = VEHICLE_FAMILIES.get(parsed.target_family, [])

    if target_vehicles:
        veh_qs = qs.filter(Q(vehicle_fitment__in=target_vehicles) | Q(vehicle_fitment__iexact="Universal"))
        if veh_qs.exists():
            qs = veh_qs
        else:
            # We don't have parts matching this vehicle; keep original qs to verify fitment during scoring
            pass

    # Fallback to token filtering if neither part_type nor vehicle was identified
    if not parsed.target_part_type and not target_vehicles and parsed.tokens:
        word_q = Q()
        for w in parsed.tokens:
            stem = WORD_SYNONYMS.get(w, w)
            if stem.endswith("s") and len(stem) > 3:
                stem = stem[:-1]
            word_q |= Q(name__icontains=stem) | Q(brand__icontains=stem) | Q(category__icontains=stem) | Q(sku__icontains=stem)
        qs = qs.filter(word_q)

    # If query had terms but no candidates matched at all, return []
    if not qs.exists():
        return []

    # 5. Native PostgreSQL Trigram Similarity (if available)
    use_trigram = False
    try:
        from django.contrib.postgres.search import TrigramSimilarity
        if parsed.cleaned_query:
            qs = qs.annotate(trigram_sim=TrigramSimilarity("name", parsed.cleaned_query))
            use_trigram = True
    except Exception:
        use_trigram = False

    candidates = list(qs[:40])

    # 6. Composite Hybrid Scoring
    scored = []
    for p in candidates:
        score = 0.0
        p_name_lower = p.name.lower()
        p_fitment = p.vehicle_fitment

        # Signal A: Vehicle Fitment Alignment
        fitment_status = "unspecified"
        is_compatible = True

        if parsed.target_vehicle:
            if p_fitment.lower() == parsed.target_vehicle.lower():
                score += 0.40
                fitment_status = "confirmed"
            elif p_fitment.lower() == "universal":
                score += 0.25
                fitment_status = "universal"
            else:
                score -= 0.40
                fitment_status = "incompatible"
                is_compatible = False
        elif parsed.target_family:
            family_members = [m.lower() for m in VEHICLE_FAMILIES.get(parsed.target_family, [])]
            if p_fitment.lower() in family_members:
                score += 0.35
                fitment_status = "confirmed"
            elif p_fitment.lower() == "universal":
                score += 0.25
                fitment_status = "universal"
            else:
                score -= 0.35
                fitment_status = "incompatible"
                is_compatible = False
        else:
            if p_fitment.lower() == "universal":
                score += 0.20
                fitment_status = "universal"
            else:
                score += 0.15
                fitment_status = "unspecified"

        # If user explicitly requested a specific vehicle and this part is incompatible, drop candidate
        if (parsed.target_vehicle or parsed.target_family) and not is_compatible:
            continue

        # Signal B: Part Type / Category Alignment
        if parsed.target_part_type:
            target_pt = parsed.target_part_type.lower()
            if target_pt in p_name_lower or (target_pt == "engine oil" and "engine oil" in p_name_lower):
                score += 0.45
            else:
                score -= 0.20
        elif parsed.target_category:
            if p.category.lower() == parsed.target_category.lower():
                score += 0.30

        # Signal C: Brand Alignment
        if parsed.target_brand:
            if p.brand.lower() == parsed.target_brand.lower():
                score += 0.20

        # Signal D: Lexical & Trigram Similarity
        if use_trigram and hasattr(p, "trigram_sim") and p.trigram_sim is not None:
            score += float(p.trigram_sim) * 0.25
        else:
            # Python sequence similarity fallback
            matcher = difflib.SequenceMatcher(None, parsed.cleaned_query, p_name_lower)
            sim = matcher.ratio()
            score += sim * 0.20

        # Token overlap bonus
        for t in parsed.tokens:
            mapped_t = WORD_SYNONYMS.get(t, t)
            if mapped_t in p_name_lower or mapped_t in p.brand.lower():
                score += 0.10

        # Enforce minimum threshold (0.25)
        if score >= 0.25:
            scored.append({
                "product": p,
                "score": round(min(score, 1.0), 2),
                "is_compatible": is_compatible,
                "fitment_status": fitment_status,
            })

    # Sort candidates by (confidence_score descending, available stock descending)
    scored.sort(key=lambda x: (x["score"], x["product"].stock), reverse=True)

    results = []
    for item in scored[:limit]:
        p = item["product"]
        results.append({
            "sku": p.sku,
            "name": p.name,
            "category": p.category,
            "brand": p.brand,
            "vehicle_fitment": p.vehicle_fitment,
            "price": f"{p.price:.2f}",
            "stock": p.stock,
            "description": p.description,
            "confidence_score": item["score"],
            "is_compatible": item["is_compatible"],
            "fitment_status": item["fitment_status"],
        })
    return results

