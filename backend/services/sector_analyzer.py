import logging

from sqlalchemy.ext.asyncio import AsyncSession
from yf_patch import yf_download

from services import cache

logger = logging.getLogger(__name__)

SECTOR_ETFS = {
    "XLK": "Technology",
    "XLV": "Health Care",
    "XLF": "Financials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLU": "Utilities",
    "XLC": "Communication Services",
}

# Top 30 holdings per SPDR Sector ETF (source: stockanalysis.com, Mar 2026)
SECTOR_ETF_HOLDINGS = {
    "XLK": [
        ("NVDA", "NVIDIA", 15.03), ("AAPL", "Apple", 12.98), ("MSFT", "Microsoft", 10.30),
        ("AVGO", "Broadcom", 5.30), ("MU", "Micron Technology", 3.92), ("PLTR", "Palantir Technologies", 3.07),
        ("AMD", "Advanced Micro Devices", 2.86), ("CSCO", "Cisco Systems", 2.78), ("AMAT", "Applied Materials", 2.43),
        ("LRCX", "Lam Research", 2.37), ("ORCL", "Oracle", 2.29), ("IBM", "IBM", 2.11),
        ("INTC", "Intel", 1.81), ("CRM", "Salesforce", 1.69), ("KLAC", "KLA Corp", 1.65),
        ("MRVL", "Marvell Technology", 1.52), ("ADBE", "Adobe", 1.48), ("SNPS", "Synopsys", 1.40),
        ("CDNS", "Cadence Design", 1.35), ("QCOM", "Qualcomm", 1.30), ("NOW", "ServiceNow", 1.25),
        ("INTU", "Intuit", 1.18), ("ADI", "Analog Devices", 1.12), ("NXPI", "NXP Semiconductors", 1.05),
        ("MCHP", "Microchip Technology", 0.98), ("ON", "ON Semiconductor", 0.95), ("FTNT", "Fortinet", 0.90),
        ("TXN", "Texas Instruments", 0.87), ("PANW", "Palo Alto Networks", 0.82), ("HPE", "Hewlett Packard Ent.", 0.78),
    ],
    "XLF": [
        ("BRK-B", "Berkshire Hathaway", 12.51), ("JPM", "JPMorgan Chase", 10.90), ("V", "Visa", 7.36),
        ("MA", "Mastercard", 5.87), ("BAC", "Bank of America", 4.54), ("WFC", "Wells Fargo", 3.51),
        ("GS", "Goldman Sachs", 3.42), ("MS", "Morgan Stanley", 2.68), ("C", "Citigroup", 2.66),
        ("AXP", "American Express", 2.25), ("SCHW", "Charles Schwab", 2.17), ("BLK", "BlackRock", 2.03),
        ("SPGI", "S&P Global", 1.91), ("COF", "Capital One", 1.68), ("PGR", "Progressive", 1.68),
        ("CB", "Chubb", 1.55), ("ICE", "Intercontinental Exchange", 1.48), ("MMC", "Marsh & McLennan", 1.42),
        ("CME", "CME Group", 1.35), ("AON", "Aon", 1.28), ("MCO", "Moody's", 1.22),
        ("USB", "US Bancorp", 1.15), ("TFC", "Truist Financial", 1.08), ("AIG", "American Intl Group", 1.02),
        ("MET", "MetLife", 0.96), ("MSCI", "MSCI", 0.90), ("ALL", "Allstate", 0.85),
        ("PNC", "PNC Financial", 0.80), ("AJG", "Arthur J. Gallagher", 0.75), ("AFL", "Aflac", 0.72),
    ],
    "XLE": [
        ("XOM", "Exxon Mobil", 23.55), ("CVX", "Chevron", 17.39), ("COP", "ConocoPhillips", 6.98),
        ("WMB", "Williams Companies", 4.51), ("EOG", "EOG Resources", 4.02), ("SLB", "Schlumberger", 4.00),
        ("VLO", "Valero Energy", 3.93), ("PSX", "Phillips 66", 3.79), ("KMI", "Kinder Morgan", 3.69),
        ("MPC", "Marathon Petroleum", 3.69), ("BKR", "Baker Hughes", 3.36), ("OKE", "ONEOK", 3.04),
        ("TRGP", "Targa Resources", 2.90), ("EQT", "EQT Corp", 2.18), ("OXY", "Occidental Petroleum", 2.16),
        ("DVN", "Devon Energy", 1.85), ("HAL", "Halliburton", 1.72), ("FANG", "Diamondback Energy", 1.60),
        ("HES", "Hess Corp", 1.48), ("CTRA", "Coterra Energy", 1.35), ("MRO", "Marathon Oil", 1.22),
        ("APA", "APA Corp", 0.95), ("PXD", "Pioneer Natural Res.", 0.88), ("TPL", "Texas Pacific Land", 0.82),
        ("AM", "Antero Midstream", 0.75), ("AR", "Antero Resources", 0.70), ("RRC", "Range Resources", 0.65),
        ("MTDR", "Matador Resources", 0.60), ("CHK", "Chesapeake Energy", 0.55), ("PR", "Permian Resources", 0.50),
    ],
    "XLV": [
        ("LLY", "Eli Lilly", 14.01), ("JNJ", "Johnson & Johnson", 10.36), ("ABBV", "AbbVie", 7.37),
        ("MRK", "Merck", 5.17), ("UNH", "UnitedHealth", 4.69), ("AMGN", "Amgen", 3.55),
        ("TMO", "Thermo Fisher", 3.50), ("ABT", "Abbott Labs", 3.46), ("GILD", "Gilead Sciences", 3.23),
        ("ISRG", "Intuitive Surgical", 3.16), ("PFE", "Pfizer", 2.71), ("SYK", "Stryker", 2.29),
        ("DHR", "Danaher", 2.28), ("BMY", "Bristol-Myers Squibb", 2.22), ("MDT", "Medtronic", 2.14),
        ("BSX", "Boston Scientific", 1.95), ("VRTX", "Vertex Pharma", 1.85), ("CI", "Cigna Group", 1.72),
        ("ELV", "Elevance Health", 1.60), ("ZTS", "Zoetis", 1.48), ("REGN", "Regeneron", 1.38),
        ("HCA", "HCA Healthcare", 1.28), ("A", "Agilent Technologies", 1.15), ("EW", "Edwards Lifesciences", 1.08),
        ("IQV", "IQVIA Holdings", 1.02), ("IDXX", "IDEXX Laboratories", 0.95), ("BDX", "Becton Dickinson", 0.90),
        ("RMD", "ResMed", 0.85), ("MTD", "Mettler-Toledo", 0.80), ("BAX", "Baxter Intl", 0.72),
    ],
    "XLI": [
        ("GE", "GE Aerospace", 6.54), ("CAT", "Caterpillar", 6.26), ("RTX", "RTX Corp", 5.18),
        ("GEV", "GE Vernova", 4.19), ("BA", "Boeing", 3.29), ("UBER", "Uber Technologies", 2.97),
        ("UNP", "Union Pacific", 2.92), ("HON", "Honeywell", 2.87), ("DE", "Deere & Co", 2.81),
        ("ETN", "Eaton Corp", 2.61), ("LMT", "Lockheed Martin", 2.53), ("PH", "Parker-Hannifin", 2.31),
        ("HWM", "Howmet Aerospace", 1.92), ("NOC", "Northrop Grumman", 1.88), ("TT", "Trane Technologies", 1.83),
        ("WM", "Waste Management", 1.72), ("GD", "General Dynamics", 1.65), ("CSX", "CSX Corp", 1.55),
        ("NSC", "Norfolk Southern", 1.45), ("EMR", "Emerson Electric", 1.38), ("FDX", "FedEx", 1.30),
        ("JCI", "Johnson Controls", 1.22), ("CARR", "Carrier Global", 1.15), ("AXON", "Axon Enterprise", 1.08),
        ("ROK", "Rockwell Automation", 1.00), ("FAST", "Fastenal", 0.95), ("ODFL", "Old Dominion Freight", 0.90),
        ("AME", "AMETEK", 0.85), ("VRSK", "Verisk Analytics", 0.80), ("CPRT", "Copart", 0.75),
    ],
    "XLP": [
        ("WMT", "Walmart", 11.54), ("COST", "Costco", 9.30), ("PG", "Procter & Gamble", 7.68),
        ("KO", "Coca-Cola", 6.37), ("PM", "Philip Morris", 5.64), ("CL", "Colgate-Palmolive", 4.69),
        ("MO", "Altria", 4.68), ("PEP", "PepsiCo", 4.65), ("MDLZ", "Mondelez", 4.43),
        ("MNST", "Monster Beverage", 3.44), ("TGT", "Target", 3.43), ("KR", "Kroger", 2.74),
        ("SYY", "Sysco", 2.58), ("KDP", "Keurig Dr Pepper", 2.39), ("KVUE", "Kenvue", 2.20),
        ("GIS", "General Mills", 2.05), ("HSY", "Hershey", 1.85), ("STZ", "Constellation Brands", 1.72),
        ("ADM", "Archer-Daniels-Midland", 1.58), ("K", "Kellanova", 1.45), ("CAG", "Conagra Brands", 1.30),
        ("SJM", "J.M. Smucker", 1.18), ("CHD", "Church & Dwight", 1.10), ("CLX", "Clorox", 1.02),
        ("BG", "Bunge Global", 0.95), ("TSN", "Tyson Foods", 0.88), ("HRL", "Hormel Foods", 0.80),
        ("CPB", "Campbell's", 0.72), ("MKC", "McCormick", 0.68), ("LW", "Lamb Weston", 0.62),
    ],
    "XLY": [
        ("AMZN", "Amazon", 22.12), ("TSLA", "Tesla", 19.22), ("HD", "Home Depot", 6.19),
        ("MCD", "McDonald's", 4.94), ("TJX", "TJX Companies", 4.24), ("LOW", "Lowe's", 3.42),
        ("BKNG", "Booking Holdings", 3.23), ("SBUX", "Starbucks", 2.60), ("ORLY", "O'Reilly Automotive", 1.88),
        ("MAR", "Marriott", 1.76), ("GM", "General Motors", 1.73), ("RCL", "Royal Caribbean", 1.72),
        ("HLT", "Hilton", 1.67), ("NKE", "Nike", 1.64), ("ROST", "Ross Stores", 1.64),
        ("AZO", "AutoZone", 1.50), ("CMG", "Chipotle", 1.38), ("DHI", "D.R. Horton", 1.28),
        ("LEN", "Lennar", 1.18), ("ABNB", "Airbnb", 1.10), ("F", "Ford Motor", 1.02),
        ("YUM", "Yum! Brands", 0.95), ("EXPE", "Expedia", 0.88), ("DPZ", "Domino's Pizza", 0.82),
        ("GPC", "Genuine Parts", 0.75), ("POOL", "Pool Corp", 0.70), ("BBY", "Best Buy", 0.65),
        ("EBAY", "eBay", 0.60), ("PHM", "PulteGroup", 0.55), ("GRMN", "Garmin", 0.52),
    ],
    "XLB": [
        ("LIN", "Linde", 14.18), ("NEM", "Newmont", 7.85), ("FCX", "Freeport-McMoRan", 5.58),
        ("SHW", "Sherwin-Williams", 4.79), ("CRH", "CRH", 4.60), ("CTVA", "Corteva", 4.60),
        ("APD", "Air Products", 4.56), ("ECL", "Ecolab", 4.53), ("NUE", "Nucor", 4.09),
        ("MLM", "Martin Marietta", 3.97), ("VMC", "Vulcan Materials", 3.78), ("STLD", "Steel Dynamics", 3.31),
        ("PPG", "PPG Industries", 3.19), ("DOW", "Dow", 3.05), ("SW", "Smurfit Westrock", 2.96),
        ("IFF", "Intl Flavors & Frag.", 2.65), ("DD", "DuPont", 2.45), ("CF", "CF Industries", 2.20),
        ("EMN", "Eastman Chemical", 1.95), ("ALB", "Albemarle", 1.78), ("CE", "Celanese", 1.60),
        ("IP", "International Paper", 1.42), ("BALL", "Ball Corp", 1.30), ("PKG", "Packaging Corp", 1.18),
        ("MOS", "Mosaic", 1.05), ("RPM", "RPM Intl", 0.95), ("FMC", "FMC Corp", 0.85),
        ("AVY", "Avery Dennison", 0.78), ("SEE", "Sealed Air", 0.68), ("WRK", "WestRock", 0.62),
    ],
    "XLU": [
        ("NEE", "NextEra Energy", 13.12), ("SO", "Southern Company", 7.40), ("CEG", "Constellation Energy", 7.17),
        ("DUK", "Duke Energy", 7.08), ("AEP", "American Electric Power", 4.89), ("SRE", "Sempra", 4.24),
        ("D", "Dominion Energy", 3.72), ("VST", "Vistra", 3.69), ("EXC", "Exelon", 3.41),
        ("XEL", "Xcel Energy", 3.37), ("ETR", "Entergy", 3.26), ("PEG", "PSEG", 2.90),
        ("ED", "Consolidated Edison", 2.76), ("PCG", "PG&E", 2.75), ("WEC", "WEC Energy", 2.61),
        ("ES", "Eversource Energy", 2.40), ("AWK", "American Water Works", 2.20), ("EIX", "Edison Intl", 2.02),
        ("FE", "FirstEnergy", 1.85), ("DTE", "DTE Energy", 1.72), ("PPL", "PPL Corp", 1.58),
        ("CMS", "CMS Energy", 1.45), ("AES", "AES Corp", 1.32), ("CNP", "CenterPoint Energy", 1.20),
        ("ATO", "Atmos Energy", 1.08), ("NI", "NiSource", 0.98), ("EVRG", "Evergy", 0.88),
        ("LNT", "Alliant Energy", 0.80), ("PNW", "Pinnacle West Capital", 0.72), ("NRG", "NRG Energy", 0.65),
    ],
    "XLRE": [
        ("WELL", "Welltower", 10.32), ("PLD", "Prologis", 9.39), ("EQIX", "Equinix", 6.86),
        ("AMT", "American Tower", 6.44), ("SPG", "Simon Property", 4.81), ("PSA", "Public Storage", 4.80),
        ("O", "Realty Income", 4.79), ("DLR", "Digital Realty", 4.72), ("VTR", "Ventas", 4.08),
        ("CCI", "Crown Castle", 4.01), ("CBRE", "CBRE Group", 3.77), ("VICI", "VICI Properties", 3.24),
        ("IRM", "Iron Mountain", 3.24), ("EXR", "Extra Space Storage", 3.20), ("AVB", "AvalonBay", 2.59),
        ("ARE", "Alexandria Real Estate", 2.35), ("EQR", "Equity Residential", 2.15), ("MAA", "Mid-America Apartment", 1.95),
        ("INVH", "Invitation Homes", 1.78), ("UDR", "UDR Inc", 1.60), ("SUI", "Sun Communities", 1.45),
        ("ESS", "Essex Property", 1.32), ("KIM", "Kimco Realty", 1.20), ("REG", "Regency Centers", 1.08),
        ("CPT", "Camden Property", 0.98), ("HST", "Host Hotels", 0.90), ("BXP", "BXP Inc", 0.82),
        ("DOC", "Healthpeak Properties", 0.75), ("PEAK", "Healthpeak Properties", 0.68), ("LAMR", "Lamar Advertising", 0.62),
    ],
    "XLC": [
        ("META", "Meta Platforms", 19.70), ("GOOGL", "Alphabet A", 10.19), ("GOOG", "Alphabet C", 8.15),
        ("NFLX", "Netflix", 5.76), ("VZ", "Verizon", 5.68), ("T", "AT&T", 5.26),
        ("CMCSA", "Comcast", 5.08), ("TMUS", "T-Mobile US", 5.00), ("EA", "Electronic Arts", 4.37),
        ("WBD", "Warner Bros Discovery", 4.20), ("DIS", "Walt Disney", 4.17), ("TTWO", "Take-Two Interactive", 3.83),
        ("OMC", "Omnicom", 3.46), ("LYV", "Live Nation", 3.23), ("CHTR", "Charter Communications", 2.59),
        ("IPG", "Interpublic Group", 1.95), ("PARA", "Paramount Global", 1.72), ("MTCH", "Match Group", 1.50),
        ("FOXA", "Fox Corp A", 1.35), ("FOX", "Fox Corp B", 1.20), ("NWSA", "News Corp A", 1.08),
        ("NWS", "News Corp B", 0.95), ("PINS", "Pinterest", 0.88), ("RBLX", "Roblox", 0.82),
        ("SNAP", "Snap", 0.72), ("ZG", "Zillow Group", 0.65), ("ROKU", "Roku", 0.58),
        ("SONO", "Sonos", 0.48), ("LUMN", "Lumen Technologies", 0.42), ("DISH", "DISH Network", 0.38),
    ],
}


def get_sector_rotation() -> list[dict]:
    cached = cache.get("sector_rotation")
    if cached is not None:
        return cached

    tickers = list(SECTOR_ETFS.keys())
    ticker_str = " ".join(tickers)

    try:
        data = yf_download(ticker_str, period="3mo", progress=False)
    except Exception as e:
        logger.error(f"Sector rotation download failed: {e}")
        return []

    if data.empty:
        logger.warning(f"Sector rotation download returned empty data")
        return []

    logger.info(f"Sector rotation: {data.shape[0]} rows, {data.shape[1]} cols")

    results = []
    failed_tickers = []
    for etf, sector_name in SECTOR_ETFS.items():
        try:
            close = data["Close"][etf].dropna()
            if len(close) < 2:
                raise ValueError("not enough data")

            n1w, n1m, n3m = 5, 21, 63

            perf_1d = ((close.iloc[-1] / close.iloc[-2]) - 1) * 100
            close_1w = close.iloc[-n1w:] if len(close) >= n1w else close
            close_1m = close.iloc[-n1m:] if len(close) >= n1m else close
            close_3m = close.iloc[-n3m:] if len(close) >= n3m else close

            perf_1w = ((close_1w.iloc[-1] / close_1w.iloc[0]) - 1) * 100
            perf_1m = ((close_1m.iloc[-1] / close_1m.iloc[0]) - 1) * 100
            perf_3m = ((close_3m.iloc[-1] / close_3m.iloc[0]) - 1) * 100

            results.append({
                "etf": etf,
                "sector": sector_name,
                "perf_1d": round(float(perf_1d), 2),
                "perf_1w": round(float(perf_1w), 2),
                "perf_1m": round(float(perf_1m), 2),
                "perf_3m": round(float(perf_3m), 2),
                "trend": "up" if perf_1m > 0 and perf_3m > 0 else "down" if perf_1m < 0 and perf_3m < 0 else "mixed",
            })
        except Exception as e:
            logger.warning(f"Sector {etf} missing from batch download, will retry individually: {e}")
            failed_tickers.append((etf, sector_name))

    # Retry failed tickers individually
    for etf, sector_name in failed_tickers:
        try:
            retry_data = yf_download(etf, period="3mo", progress=False)
            if retry_data.empty:
                raise ValueError("empty data")
            close = retry_data["Close"].dropna()
            if len(close) < 2:
                raise ValueError("not enough data")

            n1w, n1m, n3m = 5, 21, 63
            perf_1d = ((close.iloc[-1] / close.iloc[-2]) - 1) * 100
            close_1w = close.iloc[-n1w:] if len(close) >= n1w else close
            close_1m = close.iloc[-n1m:] if len(close) >= n1m else close
            close_3m = close.iloc[-n3m:] if len(close) >= n3m else close

            perf_1w = ((close_1w.iloc[-1] / close_1w.iloc[0]) - 1) * 100
            perf_1m = ((close_1m.iloc[-1] / close_1m.iloc[0]) - 1) * 100
            perf_3m = ((close_3m.iloc[-1] / close_3m.iloc[0]) - 1) * 100

            results.append({
                "etf": etf,
                "sector": sector_name,
                "perf_1d": round(float(perf_1d), 2),
                "perf_1w": round(float(perf_1w), 2),
                "perf_1m": round(float(perf_1m), 2),
                "perf_3m": round(float(perf_3m), 2),
                "trend": "up" if perf_1m > 0 and perf_3m > 0 else "down" if perf_1m < 0 and perf_3m < 0 else "mixed",
            })
            logger.info(f"Sector {etf} retry succeeded")
        except Exception as e:
            logger.error(f"Sector {etf} retry also failed: {e}")
            results.append({
                "etf": etf,
                "sector": sector_name,
                "perf_1d": 0, "perf_1w": 0, "perf_1m": 0, "perf_3m": 0,
                "trend": "unknown",
            })

    results.sort(key=lambda x: x["perf_1m"], reverse=True)

    # Only cache if all sectors have real data (non-zero performance)
    valid_count = sum(1 for r in results if r["perf_1m"] != 0 or r["perf_1w"] != 0)
    if valid_count >= 11:
        cache.set("sector_rotation", results)
    else:
        logger.warning(f"Sector rotation: only {valid_count}/11 sectors have data — not caching")

    return results


def _compute_perf(close_6m, spy_6m) -> dict:
    """Compute 1D/1W/1M/3M/6M performance, vs SPY, and trend from a 6M close series."""
    if close_6m is None or len(close_6m) < 2:
        return {"perf_1d": 0, "perf_1w": 0, "perf_1m": 0, "perf_3m": 0, "perf_6m": 0, "relative_to_spy": 0, "trend": "unknown"}

    n1w, n1m, n3m = 5, 21, 63
    close_1w = close_6m.iloc[-n1w:] if len(close_6m) >= n1w else close_6m
    close_1m = close_6m.iloc[-n1m:] if len(close_6m) >= n1m else close_6m
    close_3m = close_6m.iloc[-n3m:] if len(close_6m) >= n3m else close_6m

    perf_1d = ((close_6m.iloc[-1] / close_6m.iloc[-2]) - 1) * 100
    perf_1w = ((close_1w.iloc[-1] / close_1w.iloc[0]) - 1) * 100
    perf_1m = ((close_1m.iloc[-1] / close_1m.iloc[0]) - 1) * 100
    perf_3m = ((close_3m.iloc[-1] / close_3m.iloc[0]) - 1) * 100
    perf_6m = ((close_6m.iloc[-1] / close_6m.iloc[0]) - 1) * 100

    spy_perf = 0
    if spy_6m is not None and len(spy_6m) > 1:
        spy_1m = spy_6m.iloc[-n1m:] if len(spy_6m) >= n1m else spy_6m
        spy_perf = ((spy_1m.iloc[-1] / spy_1m.iloc[0]) - 1) * 100

    return {
        "perf_1d": round(float(perf_1d), 2),
        "perf_1w": round(float(perf_1w), 2),
        "perf_1m": round(float(perf_1m), 2),
        "perf_3m": round(float(perf_3m), 2),
        "perf_6m": round(float(perf_6m), 2),
        "relative_to_spy": round(float(perf_1m - spy_perf), 2),
        "trend": "up" if perf_1m > 0 and perf_3m > 0 else "down" if perf_1m < 0 and perf_3m < 0 else "mixed",
    }


async def get_sector_holdings(etf_ticker: str, db: AsyncSession) -> dict | None:
    """Get top 30 holdings for a sector ETF with prices, performance, and portfolio/watchlist status."""
    import asyncio
    from sqlalchemy import select
    from models.position import Position
    from models.watchlist import WatchlistItem

    holdings_data = SECTOR_ETF_HOLDINGS.get(etf_ticker)
    if not holdings_data:
        return None

    sector_name = SECTOR_ETFS.get(etf_ticker, etf_ticker)
    cache_key = f"sector_holdings:{etf_ticker}"
    cached = cache.get(cache_key)

    # Get portfolio tickers and watchlist tickers
    pos_result = await db.execute(select(Position.ticker, Position.yfinance_ticker).where(Position.is_active == True))  # noqa: E712
    portfolio_tickers = set()
    for ticker, yf_ticker in pos_result:
        portfolio_tickers.add(ticker)
        if yf_ticker:
            portfolio_tickers.add(yf_ticker)

    wl_result = await db.execute(select(WatchlistItem.ticker).where(WatchlistItem.is_active == True))  # noqa: E712
    watchlist_tickers = {row[0] for row in wl_result}

    # Use cached performance data or fetch fresh
    if cached:
        perf_map = cached
    else:
        holding_tickers = [t for t, _, _ in holdings_data]
        all_tickers = holding_tickers + ["SPY"]

        def _download():
            data = yf_download(" ".join(all_tickers), period="6mo", progress=False, group_by="ticker")
            if data.empty:
                return {}
            spy_close = None
            try:
                spy_close = data["SPY"]["Close"].dropna()
            except (KeyError, IndexError) as e:
                logger.debug(f"Could not extract SPY close data: {e}")
            result = {}
            for t in holding_tickers:
                try:
                    close = data[t]["Close"].dropna()
                    perf = _compute_perf(close, spy_close)
                    perf["price"] = round(float(close.iloc[-1]), 2)
                    prev = float(close.iloc[-2]) if len(close) > 1 else perf["price"]
                    perf["change_pct"] = round(((perf["price"] / prev) - 1) * 100, 2) if prev else 0
                    result[t] = perf
                except (KeyError, IndexError) as e:
                    logger.debug(f"Could not extract holding {t} data: {e}")
                    result[t] = None
            return result

        perf_map = await asyncio.to_thread(_download)
        cache.set(cache_key, perf_map)

    holdings = []
    for ticker, name, weight in holdings_data:
        perf = perf_map.get(ticker)
        holdings.append({
            "ticker": ticker,
            "name": name,
            "weight": weight,
            "price": perf["price"] if perf else None,
            "currency": "USD",
            "change_pct": perf["change_pct"] if perf else None,
            "perf_1d": perf.get("perf_1d", 0) if perf else 0,
            "perf_1w": perf["perf_1w"] if perf else 0,
            "perf_1m": perf["perf_1m"] if perf else 0,
            "perf_3m": perf["perf_3m"] if perf else 0,
            "perf_6m": perf["perf_6m"] if perf else 0,
            "relative_to_spy": perf["relative_to_spy"] if perf else 0,
            "trend": perf["trend"] if perf else "unknown",
            "in_portfolio": ticker in portfolio_tickers,
            "in_watchlist": ticker in watchlist_tickers,
        })

    return {
        "etf": etf_ticker,
        "sector": sector_name,
        "holdings": holdings,
    }
