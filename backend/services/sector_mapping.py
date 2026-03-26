"""FINVIZ Industry → Sector taxonomy with custom categories."""

INDUSTRY_TO_SECTOR = {
    # ══════════════════════════════════════
    # FINVIZ Standard-Sektoren (11 GICS)
    # ══════════════════════════════════════

    # Basic Materials
    "Agricultural Inputs": "Basic Materials",
    "Aluminum": "Basic Materials",
    "Building Materials": "Basic Materials",
    "Chemicals": "Basic Materials",
    "Coking Coal": "Basic Materials",
    "Copper": "Basic Materials",
    "Gold": "Basic Materials",
    "Lumber & Wood Production": "Basic Materials",
    "Other Industrial Metals & Mining": "Basic Materials",
    "Other Precious Metals & Mining": "Basic Materials",
    "Paper & Paper Products": "Basic Materials",
    "Silver": "Basic Materials",
    "Specialty Chemicals": "Basic Materials",
    "Steel": "Basic Materials",

    # Communication Services
    "Advertising Agencies": "Communication Services",
    "Broadcasting": "Communication Services",
    "Electronic Gaming & Multimedia": "Communication Services",
    "Entertainment": "Communication Services",
    "Internet Content & Information": "Communication Services",
    "Publishing": "Communication Services",
    "Telecom Services": "Communication Services",

    # Consumer Cyclical
    "Apparel Manufacturing": "Consumer Cyclical",
    "Apparel Retail": "Consumer Cyclical",
    "Auto & Truck Dealerships": "Consumer Cyclical",
    "Auto Manufacturers": "Consumer Cyclical",
    "Auto Parts": "Consumer Cyclical",
    "Department Stores": "Consumer Cyclical",
    "Footwear & Accessories": "Consumer Cyclical",
    "Furnishings, Fixtures & Appliances": "Consumer Cyclical",
    "Gambling": "Consumer Cyclical",
    "Home Improvement Retail": "Consumer Cyclical",
    "Internet Retail": "Consumer Cyclical",
    "Leisure": "Consumer Cyclical",
    "Lodging": "Consumer Cyclical",
    "Luxury Goods": "Consumer Cyclical",
    "Packaging & Containers": "Consumer Cyclical",
    "Personal Services": "Consumer Cyclical",
    "Recreational Vehicles": "Consumer Cyclical",
    "Residential Construction": "Consumer Cyclical",
    "Resorts & Casinos": "Consumer Cyclical",
    "Restaurants": "Consumer Cyclical",
    "Specialty Retail": "Consumer Cyclical",
    "Textile Manufacturing": "Consumer Cyclical",
    "Travel Services": "Consumer Cyclical",

    # Consumer Defensive
    "Beverages - Brewers": "Consumer Defensive",
    "Beverages - Non-Alcoholic": "Consumer Defensive",
    "Beverages - Wineries & Distilleries": "Consumer Defensive",
    "Confectioners": "Consumer Defensive",
    "Discount Stores": "Consumer Defensive",
    "Education & Training Services": "Consumer Defensive",
    "Farm Products": "Consumer Defensive",
    "Food Distribution": "Consumer Defensive",
    "Grocery Stores": "Consumer Defensive",
    "Household & Personal Products": "Consumer Defensive",
    "Packaged Foods": "Consumer Defensive",
    "Tobacco": "Consumer Defensive",

    # Energy
    "Oil & Gas Drilling": "Energy",
    "Oil & Gas E&P": "Energy",
    "Oil & Gas Equipment & Services": "Energy",
    "Oil & Gas Integrated": "Energy",
    "Oil & Gas Midstream": "Energy",
    "Oil & Gas Refining & Marketing": "Energy",
    "Thermal Coal": "Energy",
    "Uranium": "Energy",

    # Financials
    "Asset Management": "Financials",
    "Banks - Diversified": "Financials",
    "Banks - Regional": "Financials",
    "Capital Markets": "Financials",
    "Credit Services": "Financials",
    "Financial Conglomerates": "Financials",
    "Financial Data & Stock Exchanges": "Financials",
    "Insurance - Diversified": "Financials",
    "Insurance - Life": "Financials",
    "Insurance - Property & Casualty": "Financials",
    "Insurance - Reinsurance": "Financials",
    "Insurance - Specialty": "Financials",
    "Insurance Brokers": "Financials",
    "Mortgage Finance": "Financials",
    "Shell Companies": "Financials",

    # Healthcare
    "Biotechnology": "Healthcare",
    "Diagnostics & Research": "Healthcare",
    "Drug Manufacturers - General": "Healthcare",
    "Drug Manufacturers - Specialty & Generic": "Healthcare",
    "Health Information Services": "Healthcare",
    "Healthcare Plans": "Healthcare",
    "Medical Care Facilities": "Healthcare",
    "Medical Devices": "Healthcare",
    "Medical Distribution": "Healthcare",
    "Medical Instruments & Supplies": "Healthcare",
    "Pharmaceutical Retailers": "Healthcare",

    # Industrials
    "Aerospace & Defense": "Industrials",
    "Airlines": "Industrials",
    "Building Products & Equipment": "Industrials",
    "Business Equipment & Supplies": "Industrials",
    "Conglomerates": "Industrials",
    "Consulting Services": "Industrials",
    "Electrical Equipment & Parts": "Industrials",
    "Engineering & Construction": "Industrials",
    "Farm & Heavy Construction Machinery": "Industrials",
    "Industrial Distribution": "Industrials",
    "Infrastructure Operations": "Industrials",
    "Integrated Freight & Logistics": "Industrials",
    "Marine Shipping": "Industrials",
    "Metal Fabrication": "Industrials",
    "Pollution & Treatment Controls": "Industrials",
    "Railroads": "Industrials",
    "Rental & Leasing Services": "Industrials",
    "Security & Protection Services": "Industrials",
    "Specialty Business Services": "Industrials",
    "Specialty Industrial Machinery": "Industrials",
    "Staffing & Employment Services": "Industrials",
    "Tools & Accessories": "Industrials",
    "Trucking": "Industrials",
    "Waste Management": "Industrials",

    # Real Estate
    "Real Estate - Development": "Real Estate",
    "Real Estate - Diversified": "Real Estate",
    "Real Estate Services": "Real Estate",
    "REIT - Diversified": "Real Estate",
    "REIT - Healthcare Facilities": "Real Estate",
    "REIT - Hotel & Motel": "Real Estate",
    "REIT - Industrial": "Real Estate",
    "REIT - Mortgage": "Real Estate",
    "REIT - Office": "Real Estate",
    "REIT - Residential": "Real Estate",
    "REIT - Retail": "Real Estate",
    "REIT - Specialty": "Real Estate",

    # Technology
    "Communication Equipment": "Technology",
    "Computer Hardware": "Technology",
    "Consumer Electronics": "Technology",
    "Electronic Components": "Technology",
    "Electronics & Computer Distribution": "Technology",
    "Information Technology Services": "Technology",
    "Scientific & Technical Instruments": "Technology",
    "Semiconductor Equipment & Materials": "Technology",
    "Semiconductors": "Technology",
    "Software - Application": "Technology",
    "Software - Infrastructure": "Technology",
    "Solar": "Technology",

    # Utilities
    "Utilities - Diversified": "Utilities",
    "Utilities - Independent Power Producers": "Utilities",
    "Utilities - Regulated Electric": "Utilities",
    "Utilities - Regulated Gas": "Utilities",
    "Utilities - Regulated Water": "Utilities",
    "Utilities - Renewable": "Utilities",

    # ══════════════════════════════════════
    # Custom-Kategorien (nicht FINVIZ)
    # ══════════════════════════════════════

    # Commodities
    "Gold (Physical)": "Commodities",
    "Silver (Physical)": "Commodities",
    "Other Commodities": "Commodities",

    # Crypto
    "Bitcoin": "Crypto",
    "Ethereum": "Crypto",
    "Other Crypto": "Crypto",

    # Cash
    "Bank Account": "Cash",
    "Broker Cash": "Cash",

    # Pension
    "Pillar 3a": "Pension",
    "Pillar 2": "Pension",
    "Other Pension": "Pension",

    # Multi-Sector (ETFs)
    "Broad Market ETF": "Multi-Sector",
    "Sector ETF": "Multi-Sector",
    "Thematic ETF": "Multi-Sector",
}

# Fixed sector display order (FINVIZ first, then custom)
SECTOR_ORDER = [
    "Technology",
    "Healthcare",
    "Financials",
    "Consumer Cyclical",
    "Consumer Defensive",
    "Communication Services",
    "Industrials",
    "Energy",
    "Basic Materials",
    "Real Estate",
    "Utilities",
    "Commodities",
    "Crypto",
    "Cash",
    "Pension",
    "Multi-Sector",
]

# The 11 FINVIZ sectors (used for ETF weight validation)
FINVIZ_SECTORS = SECTOR_ORDER[:11]

# All sectors including custom
ALL_SECTORS = list(SECTOR_ORDER)

# Multi-Sector industries (trigger ETF sector weight UI)
MULTI_SECTOR_INDUSTRIES = ["Broad Market ETF", "Sector ETF", "Thematic ETF"]

# Broad market ETFs where below-200-DMA = BUY signal (inverted Schwur 1)
# Base tickers only — matching strips exchange suffix (VWRL.SW → VWRL)
ETF_200DMA_WHITELIST: set[str] = {
    # US Broad Market
    "VOO", "VTI", "SPY", "QQQ", "OEF", "IVV", "VT", "DIA",
    # International / World (US-listed)
    "ACWI", "URTH", "VEA", "VWO", "EEM", "IEMG",
    # European / London-listed
    "VWRL", "VWRD", "SWDA", "IWDA", "CSPX", "VUSA", "WOSC", "EIMI",
    # CHF-hedged / Switzerland
    "SP5HCH", "WRDHDCH", "SPMCHA", "CHSPI", "CSSMI",
}


def is_broad_etf(ticker: str) -> bool:
    """Check if ticker is on the broad ETF whitelist (matches base ticker)."""
    base = ticker.split(".")[0].upper()
    return base in ETF_200DMA_WHITELIST

# Reverse mapping: sector → sorted list of industries
SECTORS_WITH_INDUSTRIES = {}
for _industry, _sector in INDUSTRY_TO_SECTOR.items():
    SECTORS_WITH_INDUSTRIES.setdefault(_sector, []).append(_industry)
for _sector in SECTORS_WITH_INDUSTRIES:
    SECTORS_WITH_INDUSTRIES[_sector].sort()
