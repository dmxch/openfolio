"""Static industry average fundamentals for relative comparison.

Source: FINVIZ/Macrotrends sector medians (approximate, updated annually).
Used as fallback when dynamic peer data is unavailable.

Keys match yfinance ticker.info["industry"] values.
Values: de_ratio (decimal, not %), gross_margin (decimal), net_margin (decimal),
        pe (trailing P/E), roe (decimal).
"""

INDUSTRY_AVERAGES = {
    # Industrials
    "Waste Management": {"de_ratio": 2.50, "gross_margin": 0.38, "net_margin": 0.12, "pe": 28, "roe": 0.25},
    "Aerospace & Defense": {"de_ratio": 0.80, "gross_margin": 0.28, "net_margin": 0.08, "pe": 22, "roe": 0.20},
    "Industrial Distribution": {"de_ratio": 0.60, "gross_margin": 0.30, "net_margin": 0.06, "pe": 20, "roe": 0.22},
    "Specialty Industrial Machinery": {"de_ratio": 0.50, "gross_margin": 0.35, "net_margin": 0.12, "pe": 25, "roe": 0.18},
    "Railroads": {"de_ratio": 1.50, "gross_margin": 0.40, "net_margin": 0.25, "pe": 22, "roe": 0.40},
    "Airlines": {"de_ratio": 2.00, "gross_margin": 0.30, "net_margin": 0.05, "pe": 8, "roe": 0.25},
    "Trucking": {"de_ratio": 1.00, "gross_margin": 0.25, "net_margin": 0.08, "pe": 18, "roe": 0.20},
    "Engineering & Construction": {"de_ratio": 0.60, "gross_margin": 0.15, "net_margin": 0.04, "pe": 18, "roe": 0.15},
    "Conglomerates": {"de_ratio": 1.00, "gross_margin": 0.35, "net_margin": 0.10, "pe": 20, "roe": 0.15},

    # Healthcare
    "Drug Manufacturers - General": {"de_ratio": 0.80, "gross_margin": 0.65, "net_margin": 0.20, "pe": 18, "roe": 0.30},
    "Drug Manufacturers - Specialty & Generic": {"de_ratio": 0.70, "gross_margin": 0.55, "net_margin": 0.12, "pe": 15, "roe": 0.15},
    "Medical Devices": {"de_ratio": 0.50, "gross_margin": 0.60, "net_margin": 0.18, "pe": 30, "roe": 0.15},
    "Medical Instruments & Supplies": {"de_ratio": 0.40, "gross_margin": 0.55, "net_margin": 0.15, "pe": 28, "roe": 0.12},
    "Biotechnology": {"de_ratio": 0.50, "gross_margin": 0.80, "net_margin": 0.25, "pe": 20, "roe": 0.20},
    "Health Information Services": {"de_ratio": 0.60, "gross_margin": 0.45, "net_margin": 0.10, "pe": 25, "roe": 0.15},
    "Diagnostics & Research": {"de_ratio": 0.70, "gross_margin": 0.50, "net_margin": 0.15, "pe": 25, "roe": 0.18},
    "Healthcare Plans": {"de_ratio": 0.60, "gross_margin": 0.20, "net_margin": 0.04, "pe": 18, "roe": 0.20},

    # Consumer Defensive
    "Beverages - Non-Alcoholic": {"de_ratio": 1.50, "gross_margin": 0.55, "net_margin": 0.12, "pe": 25, "roe": 0.40},
    "Beverages - Brewers": {"de_ratio": 1.20, "gross_margin": 0.50, "net_margin": 0.10, "pe": 20, "roe": 0.15},
    "Beverages - Wineries & Distilleries": {"de_ratio": 1.00, "gross_margin": 0.50, "net_margin": 0.15, "pe": 18, "roe": 0.12},
    "Tobacco": {"de_ratio": -5.00, "gross_margin": 0.65, "net_margin": 0.25, "pe": 15, "roe": 0.80},
    "Household & Personal Products": {"de_ratio": 1.20, "gross_margin": 0.50, "net_margin": 0.12, "pe": 25, "roe": 0.30},
    "Packaged Foods": {"de_ratio": 1.00, "gross_margin": 0.35, "net_margin": 0.08, "pe": 20, "roe": 0.15},
    "Farm Products": {"de_ratio": 0.50, "gross_margin": 0.15, "net_margin": 0.04, "pe": 15, "roe": 0.12},
    "Discount Stores": {"de_ratio": 0.80, "gross_margin": 0.30, "net_margin": 0.06, "pe": 22, "roe": 0.30},
    "Grocery Stores": {"de_ratio": 1.50, "gross_margin": 0.28, "net_margin": 0.03, "pe": 15, "roe": 0.25},

    # Technology
    "Software - Application": {"de_ratio": 0.50, "gross_margin": 0.72, "net_margin": 0.20, "pe": 35, "roe": 0.20},
    "Software - Infrastructure": {"de_ratio": 0.60, "gross_margin": 0.70, "net_margin": 0.25, "pe": 40, "roe": 0.25},
    "Semiconductors": {"de_ratio": 0.30, "gross_margin": 0.55, "net_margin": 0.25, "pe": 25, "roe": 0.25},
    "Semiconductor Equipment & Materials": {"de_ratio": 0.30, "gross_margin": 0.45, "net_margin": 0.20, "pe": 22, "roe": 0.22},
    "Information Technology Services": {"de_ratio": 0.40, "gross_margin": 0.35, "net_margin": 0.12, "pe": 22, "roe": 0.20},
    "Internet Content & Information": {"de_ratio": 0.30, "gross_margin": 0.60, "net_margin": 0.25, "pe": 30, "roe": 0.20},
    "Electronic Components": {"de_ratio": 0.40, "gross_margin": 0.30, "net_margin": 0.08, "pe": 18, "roe": 0.12},
    "Consumer Electronics": {"de_ratio": 0.30, "gross_margin": 0.40, "net_margin": 0.20, "pe": 28, "roe": 0.50},
    "Communication Equipment": {"de_ratio": 0.50, "gross_margin": 0.60, "net_margin": 0.20, "pe": 20, "roe": 0.25},

    # Financial Services
    "Banks - Diversified": {"de_ratio": 1.50, "gross_margin": 0.60, "net_margin": 0.25, "pe": 12, "roe": 0.12},
    "Banks - Regional": {"de_ratio": 1.20, "gross_margin": 0.55, "net_margin": 0.25, "pe": 10, "roe": 0.10},
    "Insurance - Diversified": {"de_ratio": 0.40, "gross_margin": 0.30, "net_margin": 0.10, "pe": 12, "roe": 0.12},
    "Insurance - Property & Casualty": {"de_ratio": 0.30, "gross_margin": 0.25, "net_margin": 0.10, "pe": 12, "roe": 0.10},
    "Asset Management": {"de_ratio": 0.50, "gross_margin": 0.50, "net_margin": 0.25, "pe": 15, "roe": 0.15},
    "Capital Markets": {"de_ratio": 2.00, "gross_margin": 0.60, "net_margin": 0.20, "pe": 18, "roe": 0.15},
    "Financial Data & Stock Exchanges": {"de_ratio": 0.80, "gross_margin": 0.55, "net_margin": 0.30, "pe": 30, "roe": 0.20},
    "Credit Services": {"de_ratio": 3.00, "gross_margin": 0.55, "net_margin": 0.25, "pe": 18, "roe": 0.30},

    # Energy
    "Oil & Gas Integrated": {"de_ratio": 0.40, "gross_margin": 0.30, "net_margin": 0.10, "pe": 12, "roe": 0.15},
    "Oil & Gas E&P": {"de_ratio": 0.40, "gross_margin": 0.50, "net_margin": 0.20, "pe": 10, "roe": 0.15},
    "Oil & Gas Midstream": {"de_ratio": 1.50, "gross_margin": 0.35, "net_margin": 0.12, "pe": 12, "roe": 0.10},
    "Oil & Gas Refining & Marketing": {"de_ratio": 0.60, "gross_margin": 0.08, "net_margin": 0.03, "pe": 8, "roe": 0.15},
    "Oil & Gas Equipment & Services": {"de_ratio": 0.50, "gross_margin": 0.20, "net_margin": 0.05, "pe": 15, "roe": 0.08},
    "Uranium": {"de_ratio": 0.20, "gross_margin": 0.40, "net_margin": 0.10, "pe": 30, "roe": 0.05},

    # Basic Materials
    "Gold": {"de_ratio": 0.30, "gross_margin": 0.35, "net_margin": 0.15, "pe": 20, "roe": 0.08},
    "Silver": {"de_ratio": 0.25, "gross_margin": 0.30, "net_margin": 0.10, "pe": 18, "roe": 0.06},
    "Copper": {"de_ratio": 0.40, "gross_margin": 0.30, "net_margin": 0.12, "pe": 15, "roe": 0.10},
    "Steel": {"de_ratio": 0.40, "gross_margin": 0.20, "net_margin": 0.08, "pe": 8, "roe": 0.12},
    "Chemicals": {"de_ratio": 0.60, "gross_margin": 0.30, "net_margin": 0.10, "pe": 18, "roe": 0.15},
    "Specialty Chemicals": {"de_ratio": 0.50, "gross_margin": 0.40, "net_margin": 0.12, "pe": 22, "roe": 0.15},
    "Agricultural Inputs": {"de_ratio": 0.40, "gross_margin": 0.35, "net_margin": 0.10, "pe": 15, "roe": 0.15},
    "Building Materials": {"de_ratio": 0.60, "gross_margin": 0.30, "net_margin": 0.10, "pe": 18, "roe": 0.18},
    "Lumber & Wood Production": {"de_ratio": 0.30, "gross_margin": 0.20, "net_margin": 0.08, "pe": 12, "roe": 0.12},

    # Real Estate
    "REIT - Diversified": {"de_ratio": 1.00, "gross_margin": 0.60, "net_margin": 0.25, "pe": 35, "roe": 0.08},
    "REIT - Industrial": {"de_ratio": 0.80, "gross_margin": 0.70, "net_margin": 0.30, "pe": 40, "roe": 0.05},
    "REIT - Residential": {"de_ratio": 0.90, "gross_margin": 0.65, "net_margin": 0.20, "pe": 35, "roe": 0.06},
    "REIT - Retail": {"de_ratio": 1.00, "gross_margin": 0.65, "net_margin": 0.25, "pe": 30, "roe": 0.05},

    # Communication Services
    "Telecom Services": {"de_ratio": 1.50, "gross_margin": 0.55, "net_margin": 0.10, "pe": 15, "roe": 0.15},
    "Entertainment": {"de_ratio": 0.80, "gross_margin": 0.40, "net_margin": 0.10, "pe": 25, "roe": 0.10},
    "Electronic Gaming & Multimedia": {"de_ratio": 0.30, "gross_margin": 0.65, "net_margin": 0.20, "pe": 25, "roe": 0.15},
    "Advertising Agencies": {"de_ratio": 0.80, "gross_margin": 0.35, "net_margin": 0.08, "pe": 18, "roe": 0.15},
    "Publishing": {"de_ratio": 0.60, "gross_margin": 0.50, "net_margin": 0.10, "pe": 15, "roe": 0.12},

    # Consumer Cyclical
    "Auto Manufacturers": {"de_ratio": 1.20, "gross_margin": 0.18, "net_margin": 0.06, "pe": 10, "roe": 0.12},
    "Auto Parts": {"de_ratio": 0.80, "gross_margin": 0.25, "net_margin": 0.06, "pe": 12, "roe": 0.12},
    "Restaurants": {"de_ratio": 2.00, "gross_margin": 0.35, "net_margin": 0.12, "pe": 25, "roe": 0.40},
    "Apparel Retail": {"de_ratio": 0.60, "gross_margin": 0.50, "net_margin": 0.08, "pe": 15, "roe": 0.20},
    "Home Improvement Retail": {"de_ratio": 2.50, "gross_margin": 0.33, "net_margin": 0.10, "pe": 22, "roe": 0.50},
    "Specialty Retail": {"de_ratio": 0.50, "gross_margin": 0.40, "net_margin": 0.08, "pe": 18, "roe": 0.20},
    "Internet Retail": {"de_ratio": 0.60, "gross_margin": 0.42, "net_margin": 0.05, "pe": 50, "roe": 0.15},
    "Luxury Goods": {"de_ratio": 0.50, "gross_margin": 0.65, "net_margin": 0.20, "pe": 25, "roe": 0.25},
    "Gambling": {"de_ratio": 3.00, "gross_margin": 0.55, "net_margin": 0.10, "pe": 20, "roe": 0.15},
    "Lodging": {"de_ratio": 2.00, "gross_margin": 0.55, "net_margin": 0.12, "pe": 22, "roe": 0.20},
    "Resorts & Casinos": {"de_ratio": 3.00, "gross_margin": 0.55, "net_margin": 0.08, "pe": 20, "roe": 0.15},
    "Travel Services": {"de_ratio": 1.50, "gross_margin": 0.60, "net_margin": 0.15, "pe": 22, "roe": 0.30},
    "Residential Construction": {"de_ratio": 0.50, "gross_margin": 0.25, "net_margin": 0.12, "pe": 10, "roe": 0.18},
    "Furnishings, Fixtures & Appliances": {"de_ratio": 0.50, "gross_margin": 0.35, "net_margin": 0.08, "pe": 15, "roe": 0.15},
    "Textile Manufacturing": {"de_ratio": 0.50, "gross_margin": 0.45, "net_margin": 0.10, "pe": 18, "roe": 0.15},
    "Footwear & Accessories": {"de_ratio": 0.50, "gross_margin": 0.45, "net_margin": 0.10, "pe": 22, "roe": 0.25},
    "Packaging & Containers": {"de_ratio": 1.20, "gross_margin": 0.25, "net_margin": 0.06, "pe": 15, "roe": 0.15},

    # Utilities
    "Utilities - Regulated Electric": {"de_ratio": 1.50, "gross_margin": 0.40, "net_margin": 0.12, "pe": 18, "roe": 0.10},
    "Utilities - Renewable": {"de_ratio": 1.80, "gross_margin": 0.50, "net_margin": 0.08, "pe": 25, "roe": 0.05},
    "Utilities - Diversified": {"de_ratio": 1.50, "gross_margin": 0.35, "net_margin": 0.10, "pe": 18, "roe": 0.10},
}


# Sector-level fallbacks (when industry not found)
SECTOR_AVERAGES = {
    "Technology": {"de_ratio": 0.45, "gross_margin": 0.55, "net_margin": 0.20, "pe": 28, "roe": 0.22},
    "Healthcare": {"de_ratio": 0.60, "gross_margin": 0.55, "net_margin": 0.15, "pe": 22, "roe": 0.18},
    "Financial Services": {"de_ratio": 1.50, "gross_margin": 0.50, "net_margin": 0.20, "pe": 14, "roe": 0.12},
    "Consumer Defensive": {"de_ratio": 1.00, "gross_margin": 0.40, "net_margin": 0.10, "pe": 22, "roe": 0.25},
    "Consumer Cyclical": {"de_ratio": 1.00, "gross_margin": 0.35, "net_margin": 0.08, "pe": 18, "roe": 0.18},
    "Industrials": {"de_ratio": 0.80, "gross_margin": 0.30, "net_margin": 0.08, "pe": 20, "roe": 0.18},
    "Energy": {"de_ratio": 0.50, "gross_margin": 0.30, "net_margin": 0.10, "pe": 10, "roe": 0.12},
    "Basic Materials": {"de_ratio": 0.45, "gross_margin": 0.30, "net_margin": 0.10, "pe": 15, "roe": 0.12},
    "Real Estate": {"de_ratio": 1.00, "gross_margin": 0.65, "net_margin": 0.25, "pe": 35, "roe": 0.06},
    "Utilities": {"de_ratio": 1.50, "gross_margin": 0.40, "net_margin": 0.10, "pe": 18, "roe": 0.10},
    "Communication Services": {"de_ratio": 0.80, "gross_margin": 0.50, "net_margin": 0.12, "pe": 20, "roe": 0.15},
}


def get_industry_averages(industry: str | None, sector: str | None) -> dict | None:
    """Look up industry averages, falling back to sector if industry not found."""
    if industry and industry in INDUSTRY_AVERAGES:
        return INDUSTRY_AVERAGES[industry]
    if sector and sector in SECTOR_AVERAGES:
        return SECTOR_AVERAGES[sector]
    return None
