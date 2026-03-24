"""IT Act & Companies Act 2013 Depreciation Rules — pure Python, no LLM, no I/O.

IT Act: WDV block method (Section 32).
Companies Act: SLM per Schedule II (useful life approach).
"""

# ---------------------------------------------------------------------------
# IT Act — WDV Block Rates (Section 32, Schedule II of IT Act)
# ---------------------------------------------------------------------------
IT_ACT_BLOCK_RATES = {
    "buildings_rcc": 0.10,
    "buildings_other": 0.05,
    "furniture_fittings": 0.10,
    "plant_machinery_general": 0.15,
    "computers_software": 0.40,
    "vehicles_motor_cars": 0.15,
    "vehicles_heavy": 0.30,
    "aircraft": 0.40,
    "ships": 0.20,
    "intangibles": 0.25,
}

# ---------------------------------------------------------------------------
# Companies Act 2013 — Useful Life (Schedule II, SLM)
# ---------------------------------------------------------------------------
COMPANIES_ACT_USEFUL_LIFE = {
    "buildings_rcc": 60,
    "buildings_other": 30,
    "furniture_fittings": 10,
    "plant_machinery_general": 15,
    "computers_software": 3,
    "computers_laptop": 3,
    "computers_server": 6,
    "vehicles_motor_cars": 8,
    "vehicles_heavy": 12,
    "aircraft": 20,
    "ships": 25,
    "intangibles": 10,
}

# ---------------------------------------------------------------------------
# Asset classification — keyword matching (specific before general)
# ---------------------------------------------------------------------------
ASSET_KEYWORDS = {
    "computers_software": [
        "SOFTWARE", "LICENSE", "ERP", "SAP", "TALLY", "ORACLE",
    ],
    "computers_laptop": [
        "LAPTOP", "NOTEBOOK",
    ],
    "computers_server": [
        "SERVER", "DATA CENTER", "DATACENTER",
    ],
    "aircraft": [
        "AIRCRAFT", "AEROPLANE", "AIRPLANE", "HELICOPTER",
    ],
    "ships": [
        "SHIP", "VESSEL", "BOAT", "BARGE",
    ],
    "vehicles_heavy": [
        "TRUCK", "LORRY", "BUS", "HEAVY VEHICLE", "COMMERCIAL VEHICLE",
        "TRAILER", "TANKER", "TIPPER",
    ],
    "vehicles_motor_cars": [
        "CAR", "MOTOR CAR", "VEHICLE", "MOTORCYCLE", "SCOOTER",
        "AUTO", "AUTOMOBILE", "SUV", "SEDAN", "HATCHBACK",
    ],
    "intangibles": [
        "INTANGIBLE", "PATENT", "TRADEMARK", "COPYRIGHT", "GOODWILL",
        "KNOW-HOW", "FRANCHISE", "BRAND",
    ],
    "furniture_fittings": [
        "FURNITURE", "FITTING", "FIXTURE", "ELECTRICAL FITTING",
        "PARTITION", "CABIN", "CUPBOARD", "TABLE", "CHAIR", "DESK",
        "AIR CONDITIONER", "AC UNIT",
    ],
    "buildings_rcc": [
        "RCC", "REINFORCED", "CONCRETE BUILDING", "PERMANENT BUILDING",
    ],
    "buildings_other": [
        "BUILDING", "OFFICE", "WAREHOUSE", "FACTORY", "SHED",
        "GODOWN", "PREMISES", "CONSTRUCTION",
    ],
    "plant_machinery_general": [
        "PLANT", "MACHINERY", "MACHINE", "EQUIPMENT", "GENERATOR",
        "COMPRESSOR", "PUMP", "MOTOR", "TOOL", "DIE", "MOULD",
        "COMPUTER", "PRINTER", "UPS", "INVERTER",
    ],
}


def classify_asset_block(description: str) -> str:
    """Classify an asset description into an IT Act block key.

    Priority: specific keywords first (laptop before computer, RCC before building).
    Fallback: plant_machinery_general.
    """
    upper = (description or "").upper()

    for block_key, keywords in ASSET_KEYWORDS.items():
        for kw in keywords:
            if kw in upper:
                return block_key

    return "plant_machinery_general"


def get_it_block_rate(block_key: str) -> float:
    """Get IT Act WDV depreciation rate for a block key."""
    # Map sub-categories to their parent rate
    if block_key in ("computers_laptop", "computers_server"):
        return IT_ACT_BLOCK_RATES["computers_software"]
    return IT_ACT_BLOCK_RATES.get(block_key, IT_ACT_BLOCK_RATES["plant_machinery_general"])


def get_ca_useful_life(block_key: str) -> int:
    """Get Companies Act useful life in years for a block key."""
    return COMPANIES_ACT_USEFUL_LIFE.get(block_key, 15)
