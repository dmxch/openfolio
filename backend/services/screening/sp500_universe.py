"""Statisches S&P-500-Universum (Symbol -> Firmenname + GICS-Sektor) fuer den EPS-Scanner.

Eigenstaendiger Resolver — NICHT an `resolve_equity_universe()` gekoppelt.

Generiert aus Wikipedia "List of S&P 500 companies" am 2026-06-23.
Symbol-Normalisierung: Punkt -> Bindestrich (BRK.B -> BRK-B) fuer yfinance/Finnhub.

Listenpflege (Maintainer-TODO, Doc OF-4): bei Indexanpassungen (~4x/Jahr)
neu generieren — Generator-Snippet siehe scripts/ bzw. Commit-Historie.
"""
from __future__ import annotations

SP500_META: dict[str, dict[str, str]] = {
    "A": {
        "name": "Agilent Technologies",
        "sector": "Health Care"
    },
    "AAPL": {
        "name": "Apple Inc.",
        "sector": "Information Technology"
    },
    "ABBV": {
        "name": "AbbVie",
        "sector": "Health Care"
    },
    "ABNB": {
        "name": "Airbnb",
        "sector": "Consumer Discretionary"
    },
    "ABT": {
        "name": "Abbott Laboratories",
        "sector": "Health Care"
    },
    "ACGL": {
        "name": "Arch Capital Group",
        "sector": "Financials"
    },
    "ACN": {
        "name": "Accenture",
        "sector": "Information Technology"
    },
    "ADBE": {
        "name": "Adobe Inc.",
        "sector": "Information Technology"
    },
    "ADI": {
        "name": "Analog Devices",
        "sector": "Information Technology"
    },
    "ADM": {
        "name": "Archer Daniels Midland",
        "sector": "Consumer Staples"
    },
    "ADP": {
        "name": "Automatic Data Processing",
        "sector": "Industrials"
    },
    "ADSK": {
        "name": "Autodesk",
        "sector": "Information Technology"
    },
    "AEE": {
        "name": "Ameren",
        "sector": "Utilities"
    },
    "AEP": {
        "name": "American Electric Power",
        "sector": "Utilities"
    },
    "AES": {
        "name": "AES Corporation",
        "sector": "Utilities"
    },
    "AFL": {
        "name": "Aflac",
        "sector": "Financials"
    },
    "AIG": {
        "name": "American International Group",
        "sector": "Financials"
    },
    "AIZ": {
        "name": "Assurant",
        "sector": "Financials"
    },
    "AJG": {
        "name": "Arthur J. Gallagher & Co.",
        "sector": "Financials"
    },
    "AKAM": {
        "name": "Akamai Technologies",
        "sector": "Information Technology"
    },
    "ALB": {
        "name": "Albemarle Corporation",
        "sector": "Materials"
    },
    "ALGN": {
        "name": "Align Technology",
        "sector": "Health Care"
    },
    "ALL": {
        "name": "Allstate",
        "sector": "Financials"
    },
    "ALLE": {
        "name": "Allegion",
        "sector": "Industrials"
    },
    "AMAT": {
        "name": "Applied Materials",
        "sector": "Information Technology"
    },
    "AMCR": {
        "name": "Amcor",
        "sector": "Materials"
    },
    "AMD": {
        "name": "Advanced Micro Devices",
        "sector": "Information Technology"
    },
    "AME": {
        "name": "Ametek",
        "sector": "Industrials"
    },
    "AMGN": {
        "name": "Amgen",
        "sector": "Health Care"
    },
    "AMP": {
        "name": "Ameriprise Financial",
        "sector": "Financials"
    },
    "AMT": {
        "name": "American Tower",
        "sector": "Real Estate"
    },
    "AMZN": {
        "name": "Amazon",
        "sector": "Consumer Discretionary"
    },
    "ANET": {
        "name": "Arista Networks",
        "sector": "Information Technology"
    },
    "AON": {
        "name": "Aon plc",
        "sector": "Financials"
    },
    "AOS": {
        "name": "A. O. Smith",
        "sector": "Industrials"
    },
    "APA": {
        "name": "APA Corporation",
        "sector": "Energy"
    },
    "APD": {
        "name": "Air Products",
        "sector": "Materials"
    },
    "APH": {
        "name": "Amphenol",
        "sector": "Information Technology"
    },
    "APO": {
        "name": "Apollo Global Management",
        "sector": "Financials"
    },
    "APP": {
        "name": "AppLovin",
        "sector": "Information Technology"
    },
    "APTV": {
        "name": "Aptiv",
        "sector": "Consumer Discretionary"
    },
    "ARE": {
        "name": "Alexandria Real Estate Equities",
        "sector": "Real Estate"
    },
    "ARES": {
        "name": "Ares Management",
        "sector": "Financials"
    },
    "ATO": {
        "name": "Atmos Energy",
        "sector": "Utilities"
    },
    "AVB": {
        "name": "AvalonBay Communities",
        "sector": "Real Estate"
    },
    "AVGO": {
        "name": "Broadcom",
        "sector": "Information Technology"
    },
    "AVY": {
        "name": "Avery Dennison",
        "sector": "Materials"
    },
    "AWK": {
        "name": "American Water Works",
        "sector": "Utilities"
    },
    "AXON": {
        "name": "Axon Enterprise",
        "sector": "Industrials"
    },
    "AXP": {
        "name": "American Express",
        "sector": "Financials"
    },
    "AZO": {
        "name": "AutoZone",
        "sector": "Consumer Discretionary"
    },
    "BA": {
        "name": "Boeing",
        "sector": "Industrials"
    },
    "BAC": {
        "name": "Bank of America",
        "sector": "Financials"
    },
    "BALL": {
        "name": "Ball Corporation",
        "sector": "Materials"
    },
    "BAX": {
        "name": "Baxter International",
        "sector": "Health Care"
    },
    "BBY": {
        "name": "Best Buy",
        "sector": "Consumer Discretionary"
    },
    "BDX": {
        "name": "Becton Dickinson",
        "sector": "Health Care"
    },
    "BEN": {
        "name": "Franklin Resources",
        "sector": "Financials"
    },
    "BF-B": {
        "name": "Brown–Forman",
        "sector": "Consumer Staples"
    },
    "BG": {
        "name": "Bunge Global",
        "sector": "Consumer Staples"
    },
    "BIIB": {
        "name": "Biogen",
        "sector": "Health Care"
    },
    "BKNG": {
        "name": "Booking Holdings",
        "sector": "Consumer Discretionary"
    },
    "BKR": {
        "name": "Baker Hughes",
        "sector": "Energy"
    },
    "BLDR": {
        "name": "Builders FirstSource",
        "sector": "Industrials"
    },
    "BLK": {
        "name": "BlackRock",
        "sector": "Financials"
    },
    "BMY": {
        "name": "Bristol Myers Squibb",
        "sector": "Health Care"
    },
    "BNY": {
        "name": "BNY Mellon",
        "sector": "Financials"
    },
    "BR": {
        "name": "Broadridge Financial Solutions",
        "sector": "Industrials"
    },
    "BRK-B": {
        "name": "Berkshire Hathaway",
        "sector": "Financials"
    },
    "BRO": {
        "name": "Brown & Brown",
        "sector": "Financials"
    },
    "BSX": {
        "name": "Boston Scientific",
        "sector": "Health Care"
    },
    "BX": {
        "name": "Blackstone Inc.",
        "sector": "Financials"
    },
    "BXP": {
        "name": "BXP, Inc.",
        "sector": "Real Estate"
    },
    "C": {
        "name": "Citigroup",
        "sector": "Financials"
    },
    "CAG": {
        "name": "Conagra Brands",
        "sector": "Consumer Staples"
    },
    "CAH": {
        "name": "Cardinal Health",
        "sector": "Health Care"
    },
    "CARR": {
        "name": "Carrier Global",
        "sector": "Industrials"
    },
    "CASY": {
        "name": "Casey's",
        "sector": "Consumer Staples"
    },
    "CAT": {
        "name": "Caterpillar Inc.",
        "sector": "Industrials"
    },
    "CB": {
        "name": "Chubb Limited",
        "sector": "Financials"
    },
    "CBOE": {
        "name": "Cboe Global Markets",
        "sector": "Financials"
    },
    "CBRE": {
        "name": "CBRE Group",
        "sector": "Real Estate"
    },
    "CCI": {
        "name": "Crown Castle",
        "sector": "Real Estate"
    },
    "CCL": {
        "name": "Carnival Corporation",
        "sector": "Consumer Discretionary"
    },
    "CDNS": {
        "name": "Cadence Design Systems",
        "sector": "Information Technology"
    },
    "CDW": {
        "name": "CDW Corporation",
        "sector": "Information Technology"
    },
    "CEG": {
        "name": "Constellation Energy",
        "sector": "Utilities"
    },
    "CF": {
        "name": "CF Industries",
        "sector": "Materials"
    },
    "CFG": {
        "name": "Citizens Financial Group",
        "sector": "Financials"
    },
    "CHD": {
        "name": "Church & Dwight",
        "sector": "Consumer Staples"
    },
    "CHRW": {
        "name": "C.H. Robinson",
        "sector": "Industrials"
    },
    "CHTR": {
        "name": "Charter Communications",
        "sector": "Communication Services"
    },
    "CI": {
        "name": "Cigna",
        "sector": "Health Care"
    },
    "CIEN": {
        "name": "Ciena",
        "sector": "Information Technology"
    },
    "CINF": {
        "name": "Cincinnati Financial",
        "sector": "Financials"
    },
    "CL": {
        "name": "Colgate-Palmolive",
        "sector": "Consumer Staples"
    },
    "CLX": {
        "name": "Clorox",
        "sector": "Consumer Staples"
    },
    "CMCSA": {
        "name": "Comcast",
        "sector": "Communication Services"
    },
    "CME": {
        "name": "CME Group",
        "sector": "Financials"
    },
    "CMG": {
        "name": "Chipotle Mexican Grill",
        "sector": "Consumer Discretionary"
    },
    "CMI": {
        "name": "Cummins",
        "sector": "Industrials"
    },
    "CMS": {
        "name": "CMS Energy",
        "sector": "Utilities"
    },
    "CNC": {
        "name": "Centene Corporation",
        "sector": "Health Care"
    },
    "CNP": {
        "name": "CenterPoint Energy",
        "sector": "Utilities"
    },
    "COF": {
        "name": "Capital One",
        "sector": "Financials"
    },
    "COHR": {
        "name": "Coherent Corp.",
        "sector": "Information Technology"
    },
    "COIN": {
        "name": "Coinbase",
        "sector": "Financials"
    },
    "COO": {
        "name": "Cooper Companies (The)",
        "sector": "Health Care"
    },
    "COP": {
        "name": "ConocoPhillips",
        "sector": "Energy"
    },
    "COR": {
        "name": "Cencora",
        "sector": "Health Care"
    },
    "COST": {
        "name": "Costco",
        "sector": "Consumer Staples"
    },
    "CPAY": {
        "name": "Corpay",
        "sector": "Financials"
    },
    "CPRT": {
        "name": "Copart",
        "sector": "Industrials"
    },
    "CPT": {
        "name": "Camden Property Trust",
        "sector": "Real Estate"
    },
    "CRH": {
        "name": "CRH plc",
        "sector": "Materials"
    },
    "CRL": {
        "name": "Charles River Laboratories",
        "sector": "Health Care"
    },
    "CRM": {
        "name": "Salesforce",
        "sector": "Information Technology"
    },
    "CRWD": {
        "name": "CrowdStrike",
        "sector": "Information Technology"
    },
    "CSCO": {
        "name": "Cisco",
        "sector": "Information Technology"
    },
    "CSGP": {
        "name": "CoStar Group",
        "sector": "Real Estate"
    },
    "CSX": {
        "name": "CSX Corporation",
        "sector": "Industrials"
    },
    "CTAS": {
        "name": "Cintas",
        "sector": "Industrials"
    },
    "CTSH": {
        "name": "Cognizant",
        "sector": "Information Technology"
    },
    "CTVA": {
        "name": "Corteva",
        "sector": "Materials"
    },
    "CVNA": {
        "name": "Carvana",
        "sector": "Consumer Discretionary"
    },
    "CVS": {
        "name": "CVS Health",
        "sector": "Health Care"
    },
    "CVX": {
        "name": "Chevron Corporation",
        "sector": "Energy"
    },
    "D": {
        "name": "Dominion Energy",
        "sector": "Utilities"
    },
    "DAL": {
        "name": "Delta Air Lines",
        "sector": "Industrials"
    },
    "DASH": {
        "name": "DoorDash",
        "sector": "Consumer Discretionary"
    },
    "DD": {
        "name": "DuPont",
        "sector": "Materials"
    },
    "DDOG": {
        "name": "Datadog",
        "sector": "Information Technology"
    },
    "DE": {
        "name": "Deere & Company",
        "sector": "Industrials"
    },
    "DECK": {
        "name": "Deckers Brands",
        "sector": "Consumer Discretionary"
    },
    "DELL": {
        "name": "Dell Technologies",
        "sector": "Information Technology"
    },
    "DG": {
        "name": "Dollar General",
        "sector": "Consumer Staples"
    },
    "DGX": {
        "name": "Quest Diagnostics",
        "sector": "Health Care"
    },
    "DHI": {
        "name": "D. R. Horton",
        "sector": "Consumer Discretionary"
    },
    "DHR": {
        "name": "Danaher Corporation",
        "sector": "Health Care"
    },
    "DIS": {
        "name": "Walt Disney Company (The)",
        "sector": "Communication Services"
    },
    "DLR": {
        "name": "Digital Realty",
        "sector": "Real Estate"
    },
    "DLTR": {
        "name": "Dollar Tree",
        "sector": "Consumer Staples"
    },
    "DOC": {
        "name": "Healthpeak Properties",
        "sector": "Real Estate"
    },
    "DOV": {
        "name": "Dover Corporation",
        "sector": "Industrials"
    },
    "DOW": {
        "name": "Dow Inc.",
        "sector": "Materials"
    },
    "DPZ": {
        "name": "Domino's",
        "sector": "Consumer Discretionary"
    },
    "DRI": {
        "name": "Darden Restaurants",
        "sector": "Consumer Discretionary"
    },
    "DTE": {
        "name": "DTE Energy",
        "sector": "Utilities"
    },
    "DUK": {
        "name": "Duke Energy",
        "sector": "Utilities"
    },
    "DVA": {
        "name": "DaVita",
        "sector": "Health Care"
    },
    "DVN": {
        "name": "Devon Energy",
        "sector": "Energy"
    },
    "DXCM": {
        "name": "Dexcom",
        "sector": "Health Care"
    },
    "EA": {
        "name": "Electronic Arts",
        "sector": "Communication Services"
    },
    "EBAY": {
        "name": "eBay Inc.",
        "sector": "Consumer Discretionary"
    },
    "ECL": {
        "name": "Ecolab",
        "sector": "Materials"
    },
    "ED": {
        "name": "Consolidated Edison",
        "sector": "Utilities"
    },
    "EFX": {
        "name": "Equifax",
        "sector": "Industrials"
    },
    "EG": {
        "name": "Everest Group",
        "sector": "Financials"
    },
    "EIX": {
        "name": "Edison International",
        "sector": "Utilities"
    },
    "EL": {
        "name": "Estée Lauder Companies (The)",
        "sector": "Consumer Staples"
    },
    "ELV": {
        "name": "Elevance Health",
        "sector": "Health Care"
    },
    "EME": {
        "name": "Emcor",
        "sector": "Industrials"
    },
    "EMR": {
        "name": "Emerson Electric",
        "sector": "Industrials"
    },
    "EOG": {
        "name": "EOG Resources",
        "sector": "Energy"
    },
    "EQIX": {
        "name": "Equinix",
        "sector": "Real Estate"
    },
    "EQR": {
        "name": "Equity Residential",
        "sector": "Real Estate"
    },
    "EQT": {
        "name": "EQT Corporation",
        "sector": "Energy"
    },
    "ERIE": {
        "name": "Erie Indemnity",
        "sector": "Financials"
    },
    "ES": {
        "name": "Eversource Energy",
        "sector": "Utilities"
    },
    "ESS": {
        "name": "Essex Property Trust",
        "sector": "Real Estate"
    },
    "ETN": {
        "name": "Eaton Corporation",
        "sector": "Industrials"
    },
    "ETR": {
        "name": "Entergy",
        "sector": "Utilities"
    },
    "EVRG": {
        "name": "Evergy",
        "sector": "Utilities"
    },
    "EW": {
        "name": "Edwards Lifesciences",
        "sector": "Health Care"
    },
    "EXC": {
        "name": "Exelon",
        "sector": "Utilities"
    },
    "EXE": {
        "name": "Expand Energy",
        "sector": "Energy"
    },
    "EXPD": {
        "name": "Expeditors International",
        "sector": "Industrials"
    },
    "EXPE": {
        "name": "Expedia Group",
        "sector": "Consumer Discretionary"
    },
    "EXR": {
        "name": "Extra Space Storage",
        "sector": "Real Estate"
    },
    "F": {
        "name": "Ford Motor Company",
        "sector": "Consumer Discretionary"
    },
    "FANG": {
        "name": "Diamondback Energy",
        "sector": "Energy"
    },
    "FAST": {
        "name": "Fastenal",
        "sector": "Industrials"
    },
    "FCX": {
        "name": "Freeport-McMoRan",
        "sector": "Materials"
    },
    "FDS": {
        "name": "FactSet",
        "sector": "Financials"
    },
    "FDX": {
        "name": "FedEx",
        "sector": "Industrials"
    },
    "FDXF": {
        "name": "FedEx Freight",
        "sector": "Industrials"
    },
    "FE": {
        "name": "FirstEnergy",
        "sector": "Utilities"
    },
    "FFIV": {
        "name": "F5, Inc.",
        "sector": "Information Technology"
    },
    "FICO": {
        "name": "Fair Isaac",
        "sector": "Information Technology"
    },
    "FIS": {
        "name": "Fidelity National Information Services",
        "sector": "Financials"
    },
    "FISV": {
        "name": "Fiserv",
        "sector": "Financials"
    },
    "FITB": {
        "name": "Fifth Third Bancorp",
        "sector": "Financials"
    },
    "FIX": {
        "name": "Comfort Systems USA",
        "sector": "Industrials"
    },
    "FLEX": {
        "name": "Flex Ltd.",
        "sector": "Information Technology"
    },
    "FOX": {
        "name": "Fox Corporation (Class B)",
        "sector": "Communication Services"
    },
    "FOXA": {
        "name": "Fox Corporation (Class A)",
        "sector": "Communication Services"
    },
    "FRT": {
        "name": "Federal Realty Investment Trust",
        "sector": "Real Estate"
    },
    "FSLR": {
        "name": "First Solar",
        "sector": "Information Technology"
    },
    "FTNT": {
        "name": "Fortinet",
        "sector": "Information Technology"
    },
    "FTV": {
        "name": "Fortive",
        "sector": "Industrials"
    },
    "GD": {
        "name": "General Dynamics",
        "sector": "Industrials"
    },
    "GDDY": {
        "name": "GoDaddy",
        "sector": "Information Technology"
    },
    "GE": {
        "name": "GE Aerospace",
        "sector": "Industrials"
    },
    "GEHC": {
        "name": "GE HealthCare",
        "sector": "Health Care"
    },
    "GEN": {
        "name": "Gen Digital",
        "sector": "Information Technology"
    },
    "GEV": {
        "name": "GE Vernova",
        "sector": "Industrials"
    },
    "GILD": {
        "name": "Gilead Sciences",
        "sector": "Health Care"
    },
    "GIS": {
        "name": "General Mills",
        "sector": "Consumer Staples"
    },
    "GL": {
        "name": "Globe Life",
        "sector": "Financials"
    },
    "GLW": {
        "name": "Corning Inc.",
        "sector": "Information Technology"
    },
    "GM": {
        "name": "General Motors",
        "sector": "Consumer Discretionary"
    },
    "GNRC": {
        "name": "Generac",
        "sector": "Industrials"
    },
    "GOOG": {
        "name": "Alphabet Inc. (Class C)",
        "sector": "Communication Services"
    },
    "GOOGL": {
        "name": "Alphabet Inc. (Class A)",
        "sector": "Communication Services"
    },
    "GPC": {
        "name": "Genuine Parts Company",
        "sector": "Consumer Discretionary"
    },
    "GPN": {
        "name": "Global Payments",
        "sector": "Financials"
    },
    "GRMN": {
        "name": "Garmin",
        "sector": "Consumer Discretionary"
    },
    "GS": {
        "name": "Goldman Sachs",
        "sector": "Financials"
    },
    "GWW": {
        "name": "W. W. Grainger",
        "sector": "Industrials"
    },
    "HAL": {
        "name": "Halliburton",
        "sector": "Energy"
    },
    "HAS": {
        "name": "Hasbro",
        "sector": "Consumer Discretionary"
    },
    "HBAN": {
        "name": "Huntington Bancshares",
        "sector": "Financials"
    },
    "HCA": {
        "name": "HCA Healthcare",
        "sector": "Health Care"
    },
    "HD": {
        "name": "Home Depot (The)",
        "sector": "Consumer Discretionary"
    },
    "HIG": {
        "name": "Hartford (The)",
        "sector": "Financials"
    },
    "HII": {
        "name": "Huntington Ingalls Industries",
        "sector": "Industrials"
    },
    "HLT": {
        "name": "Hilton Worldwide",
        "sector": "Consumer Discretionary"
    },
    "HON": {
        "name": "Honeywell",
        "sector": "Industrials"
    },
    "HOOD": {
        "name": "Robinhood Markets",
        "sector": "Financials"
    },
    "HPE": {
        "name": "Hewlett Packard Enterprise",
        "sector": "Information Technology"
    },
    "HPQ": {
        "name": "HP Inc.",
        "sector": "Information Technology"
    },
    "HRL": {
        "name": "Hormel Foods",
        "sector": "Consumer Staples"
    },
    "HSIC": {
        "name": "Henry Schein",
        "sector": "Health Care"
    },
    "HST": {
        "name": "Host Hotels & Resorts",
        "sector": "Real Estate"
    },
    "HSY": {
        "name": "Hershey Company (The)",
        "sector": "Consumer Staples"
    },
    "HUBB": {
        "name": "Hubbell Incorporated",
        "sector": "Industrials"
    },
    "HUM": {
        "name": "Humana",
        "sector": "Health Care"
    },
    "HWM": {
        "name": "Howmet Aerospace",
        "sector": "Industrials"
    },
    "IBKR": {
        "name": "Interactive Brokers",
        "sector": "Financials"
    },
    "IBM": {
        "name": "IBM",
        "sector": "Information Technology"
    },
    "ICE": {
        "name": "Intercontinental Exchange",
        "sector": "Financials"
    },
    "IDXX": {
        "name": "Idexx Laboratories",
        "sector": "Health Care"
    },
    "IEX": {
        "name": "IDEX Corporation",
        "sector": "Industrials"
    },
    "IFF": {
        "name": "International Flavors & Fragrances",
        "sector": "Materials"
    },
    "INCY": {
        "name": "Incyte",
        "sector": "Health Care"
    },
    "INTC": {
        "name": "Intel",
        "sector": "Information Technology"
    },
    "INTU": {
        "name": "Intuit",
        "sector": "Information Technology"
    },
    "INVH": {
        "name": "Invitation Homes",
        "sector": "Real Estate"
    },
    "IP": {
        "name": "International Paper",
        "sector": "Materials"
    },
    "IQV": {
        "name": "IQVIA",
        "sector": "Health Care"
    },
    "IR": {
        "name": "Ingersoll Rand",
        "sector": "Industrials"
    },
    "IRM": {
        "name": "Iron Mountain",
        "sector": "Real Estate"
    },
    "ISRG": {
        "name": "Intuitive Surgical",
        "sector": "Health Care"
    },
    "IT": {
        "name": "Gartner",
        "sector": "Information Technology"
    },
    "ITW": {
        "name": "Illinois Tool Works",
        "sector": "Industrials"
    },
    "IVZ": {
        "name": "Invesco",
        "sector": "Financials"
    },
    "J": {
        "name": "Jacobs Solutions",
        "sector": "Industrials"
    },
    "JBHT": {
        "name": "J.B. Hunt",
        "sector": "Industrials"
    },
    "JBL": {
        "name": "Jabil",
        "sector": "Information Technology"
    },
    "JCI": {
        "name": "Johnson Controls",
        "sector": "Industrials"
    },
    "JKHY": {
        "name": "Jack Henry & Associates",
        "sector": "Financials"
    },
    "JNJ": {
        "name": "Johnson & Johnson",
        "sector": "Health Care"
    },
    "JPM": {
        "name": "JPMorgan Chase",
        "sector": "Financials"
    },
    "KDP": {
        "name": "Keurig Dr Pepper",
        "sector": "Consumer Staples"
    },
    "KEY": {
        "name": "KeyCorp",
        "sector": "Financials"
    },
    "KEYS": {
        "name": "Keysight Technologies",
        "sector": "Information Technology"
    },
    "KHC": {
        "name": "Kraft Heinz",
        "sector": "Consumer Staples"
    },
    "KIM": {
        "name": "Kimco Realty",
        "sector": "Real Estate"
    },
    "KKR": {
        "name": "KKR & Co.",
        "sector": "Financials"
    },
    "KLAC": {
        "name": "KLA Corporation",
        "sector": "Information Technology"
    },
    "KMB": {
        "name": "Kimberly-Clark",
        "sector": "Consumer Staples"
    },
    "KMI": {
        "name": "Kinder Morgan",
        "sector": "Energy"
    },
    "KO": {
        "name": "Coca-Cola Company (The)",
        "sector": "Consumer Staples"
    },
    "KR": {
        "name": "Kroger",
        "sector": "Consumer Staples"
    },
    "KVUE": {
        "name": "Kenvue",
        "sector": "Consumer Staples"
    },
    "L": {
        "name": "Loews Corporation",
        "sector": "Financials"
    },
    "LDOS": {
        "name": "Leidos",
        "sector": "Industrials"
    },
    "LEN": {
        "name": "Lennar",
        "sector": "Consumer Discretionary"
    },
    "LH": {
        "name": "Labcorp",
        "sector": "Health Care"
    },
    "LHX": {
        "name": "L3Harris",
        "sector": "Industrials"
    },
    "LII": {
        "name": "Lennox International",
        "sector": "Industrials"
    },
    "LIN": {
        "name": "Linde plc",
        "sector": "Materials"
    },
    "LITE": {
        "name": "Lumentum",
        "sector": "Information Technology"
    },
    "LLY": {
        "name": "Lilly (Eli)",
        "sector": "Health Care"
    },
    "LMT": {
        "name": "Lockheed Martin",
        "sector": "Industrials"
    },
    "LNT": {
        "name": "Alliant Energy",
        "sector": "Utilities"
    },
    "LOW": {
        "name": "Lowe's",
        "sector": "Consumer Discretionary"
    },
    "LRCX": {
        "name": "Lam Research",
        "sector": "Information Technology"
    },
    "LULU": {
        "name": "Lululemon Athletica",
        "sector": "Consumer Discretionary"
    },
    "LUV": {
        "name": "Southwest Airlines",
        "sector": "Industrials"
    },
    "LVS": {
        "name": "Las Vegas Sands",
        "sector": "Consumer Discretionary"
    },
    "LYB": {
        "name": "LyondellBasell",
        "sector": "Materials"
    },
    "LYV": {
        "name": "Live Nation Entertainment",
        "sector": "Communication Services"
    },
    "MA": {
        "name": "Mastercard",
        "sector": "Financials"
    },
    "MAA": {
        "name": "Mid-America Apartment Communities",
        "sector": "Real Estate"
    },
    "MAR": {
        "name": "Marriott International",
        "sector": "Consumer Discretionary"
    },
    "MAS": {
        "name": "Masco",
        "sector": "Industrials"
    },
    "MCD": {
        "name": "McDonald's",
        "sector": "Consumer Discretionary"
    },
    "MCHP": {
        "name": "Microchip Technology",
        "sector": "Information Technology"
    },
    "MCK": {
        "name": "McKesson Corporation",
        "sector": "Health Care"
    },
    "MCO": {
        "name": "Moody's Corporation",
        "sector": "Financials"
    },
    "MDLZ": {
        "name": "Mondelez International",
        "sector": "Consumer Staples"
    },
    "MDT": {
        "name": "Medtronic",
        "sector": "Health Care"
    },
    "MET": {
        "name": "MetLife",
        "sector": "Financials"
    },
    "META": {
        "name": "Meta Platforms",
        "sector": "Communication Services"
    },
    "MGM": {
        "name": "MGM Resorts",
        "sector": "Consumer Discretionary"
    },
    "MKC": {
        "name": "McCormick & Company",
        "sector": "Consumer Staples"
    },
    "MLM": {
        "name": "Martin Marietta Materials",
        "sector": "Materials"
    },
    "MMM": {
        "name": "3M",
        "sector": "Industrials"
    },
    "MNST": {
        "name": "Monster Beverage",
        "sector": "Consumer Staples"
    },
    "MO": {
        "name": "Altria",
        "sector": "Consumer Staples"
    },
    "MOS": {
        "name": "Mosaic Company (The)",
        "sector": "Materials"
    },
    "MPC": {
        "name": "Marathon Petroleum",
        "sector": "Energy"
    },
    "MPWR": {
        "name": "Monolithic Power Systems",
        "sector": "Information Technology"
    },
    "MRK": {
        "name": "Merck & Co.",
        "sector": "Health Care"
    },
    "MRNA": {
        "name": "Moderna",
        "sector": "Health Care"
    },
    "MRSH": {
        "name": "Marsh McLennan",
        "sector": "Financials"
    },
    "MRVL": {
        "name": "Marvell Technology",
        "sector": "Information Technology"
    },
    "MS": {
        "name": "Morgan Stanley",
        "sector": "Financials"
    },
    "MSCI": {
        "name": "MSCI Inc.",
        "sector": "Financials"
    },
    "MSFT": {
        "name": "Microsoft",
        "sector": "Information Technology"
    },
    "MSI": {
        "name": "Motorola Solutions",
        "sector": "Information Technology"
    },
    "MTB": {
        "name": "M&T Bank",
        "sector": "Financials"
    },
    "MTD": {
        "name": "Mettler Toledo",
        "sector": "Health Care"
    },
    "MU": {
        "name": "Micron Technology",
        "sector": "Information Technology"
    },
    "NCLH": {
        "name": "Norwegian Cruise Line Holdings",
        "sector": "Consumer Discretionary"
    },
    "NDAQ": {
        "name": "Nasdaq, Inc.",
        "sector": "Financials"
    },
    "NDSN": {
        "name": "Nordson Corporation",
        "sector": "Industrials"
    },
    "NEE": {
        "name": "NextEra Energy",
        "sector": "Utilities"
    },
    "NEM": {
        "name": "Newmont",
        "sector": "Materials"
    },
    "NFLX": {
        "name": "Netflix",
        "sector": "Communication Services"
    },
    "NI": {
        "name": "NiSource",
        "sector": "Utilities"
    },
    "NKE": {
        "name": "Nike, Inc.",
        "sector": "Consumer Discretionary"
    },
    "NOC": {
        "name": "Northrop Grumman",
        "sector": "Industrials"
    },
    "NOW": {
        "name": "ServiceNow",
        "sector": "Information Technology"
    },
    "NRG": {
        "name": "NRG Energy",
        "sector": "Utilities"
    },
    "NSC": {
        "name": "Norfolk Southern",
        "sector": "Industrials"
    },
    "NTAP": {
        "name": "NetApp",
        "sector": "Information Technology"
    },
    "NTRS": {
        "name": "Northern Trust",
        "sector": "Financials"
    },
    "NUE": {
        "name": "Nucor",
        "sector": "Materials"
    },
    "NVDA": {
        "name": "Nvidia",
        "sector": "Information Technology"
    },
    "NVR": {
        "name": "NVR, Inc.",
        "sector": "Consumer Discretionary"
    },
    "NWS": {
        "name": "News Corp (Class B)",
        "sector": "Communication Services"
    },
    "NWSA": {
        "name": "News Corp (Class A)",
        "sector": "Communication Services"
    },
    "NXPI": {
        "name": "NXP Semiconductors",
        "sector": "Information Technology"
    },
    "O": {
        "name": "Realty Income",
        "sector": "Real Estate"
    },
    "ODFL": {
        "name": "Old Dominion",
        "sector": "Industrials"
    },
    "OKE": {
        "name": "Oneok",
        "sector": "Energy"
    },
    "OMC": {
        "name": "Omnicom Group",
        "sector": "Communication Services"
    },
    "ON": {
        "name": "ON Semiconductor",
        "sector": "Information Technology"
    },
    "ORCL": {
        "name": "Oracle Corporation",
        "sector": "Information Technology"
    },
    "ORLY": {
        "name": "O’Reilly Automotive",
        "sector": "Consumer Discretionary"
    },
    "OTIS": {
        "name": "Otis Worldwide",
        "sector": "Industrials"
    },
    "OXY": {
        "name": "Occidental Petroleum",
        "sector": "Energy"
    },
    "PANW": {
        "name": "Palo Alto Networks",
        "sector": "Information Technology"
    },
    "PAYX": {
        "name": "Paychex",
        "sector": "Industrials"
    },
    "PCAR": {
        "name": "Paccar",
        "sector": "Industrials"
    },
    "PCG": {
        "name": "PG&E Corporation",
        "sector": "Utilities"
    },
    "PEG": {
        "name": "Public Service Enterprise Group",
        "sector": "Utilities"
    },
    "PEP": {
        "name": "PepsiCo",
        "sector": "Consumer Staples"
    },
    "PFE": {
        "name": "Pfizer",
        "sector": "Health Care"
    },
    "PFG": {
        "name": "Principal Financial Group",
        "sector": "Financials"
    },
    "PG": {
        "name": "Procter & Gamble",
        "sector": "Consumer Staples"
    },
    "PGR": {
        "name": "Progressive Corporation",
        "sector": "Financials"
    },
    "PH": {
        "name": "Parker Hannifin",
        "sector": "Industrials"
    },
    "PHM": {
        "name": "PulteGroup",
        "sector": "Consumer Discretionary"
    },
    "PKG": {
        "name": "Packaging Corporation of America",
        "sector": "Materials"
    },
    "PLD": {
        "name": "Prologis",
        "sector": "Real Estate"
    },
    "PLTR": {
        "name": "Palantir Technologies",
        "sector": "Information Technology"
    },
    "PM": {
        "name": "Philip Morris International",
        "sector": "Consumer Staples"
    },
    "PNC": {
        "name": "PNC Financial Services",
        "sector": "Financials"
    },
    "PNR": {
        "name": "Pentair",
        "sector": "Industrials"
    },
    "PNW": {
        "name": "Pinnacle West Capital",
        "sector": "Utilities"
    },
    "PODD": {
        "name": "Insulet Corporation",
        "sector": "Health Care"
    },
    "PPG": {
        "name": "PPG Industries",
        "sector": "Materials"
    },
    "PPL": {
        "name": "PPL Corporation",
        "sector": "Utilities"
    },
    "PRU": {
        "name": "Prudential Financial",
        "sector": "Financials"
    },
    "PSA": {
        "name": "Public Storage",
        "sector": "Real Estate"
    },
    "PSKY": {
        "name": "Paramount Skydance Corporation",
        "sector": "Communication Services"
    },
    "PSX": {
        "name": "Phillips 66",
        "sector": "Energy"
    },
    "PTC": {
        "name": "PTC Inc.",
        "sector": "Information Technology"
    },
    "PWR": {
        "name": "Quanta Services",
        "sector": "Industrials"
    },
    "PYPL": {
        "name": "PayPal",
        "sector": "Financials"
    },
    "Q": {
        "name": "Qnity Electronics",
        "sector": "Information Technology"
    },
    "QCOM": {
        "name": "Qualcomm",
        "sector": "Information Technology"
    },
    "RCL": {
        "name": "Royal Caribbean Group",
        "sector": "Consumer Discretionary"
    },
    "REG": {
        "name": "Regency Centers",
        "sector": "Real Estate"
    },
    "REGN": {
        "name": "Regeneron Pharmaceuticals",
        "sector": "Health Care"
    },
    "RF": {
        "name": "Regions Financial Corporation",
        "sector": "Financials"
    },
    "RJF": {
        "name": "Raymond James Financial",
        "sector": "Financials"
    },
    "RL": {
        "name": "Ralph Lauren Corporation",
        "sector": "Consumer Discretionary"
    },
    "RMD": {
        "name": "ResMed",
        "sector": "Health Care"
    },
    "ROK": {
        "name": "Rockwell Automation",
        "sector": "Industrials"
    },
    "ROL": {
        "name": "Rollins, Inc.",
        "sector": "Industrials"
    },
    "ROP": {
        "name": "Roper Technologies",
        "sector": "Information Technology"
    },
    "ROST": {
        "name": "Ross Stores",
        "sector": "Consumer Discretionary"
    },
    "RSG": {
        "name": "Republic Services",
        "sector": "Industrials"
    },
    "RTX": {
        "name": "RTX Corporation",
        "sector": "Industrials"
    },
    "RVTY": {
        "name": "Revvity",
        "sector": "Health Care"
    },
    "SATS": {
        "name": "EchoStar",
        "sector": "Communication Services"
    },
    "SBAC": {
        "name": "SBA Communications",
        "sector": "Real Estate"
    },
    "SBUX": {
        "name": "Starbucks",
        "sector": "Consumer Discretionary"
    },
    "SCHW": {
        "name": "Charles Schwab Corporation",
        "sector": "Financials"
    },
    "SHW": {
        "name": "Sherwin-Williams",
        "sector": "Materials"
    },
    "SJM": {
        "name": "J.M. Smucker Company (The)",
        "sector": "Consumer Staples"
    },
    "SLB": {
        "name": "Schlumberger",
        "sector": "Energy"
    },
    "SMCI": {
        "name": "Supermicro",
        "sector": "Information Technology"
    },
    "SNA": {
        "name": "Snap-on",
        "sector": "Industrials"
    },
    "SNDK": {
        "name": "Sandisk",
        "sector": "Information Technology"
    },
    "SNPS": {
        "name": "Synopsys",
        "sector": "Information Technology"
    },
    "SO": {
        "name": "Southern Company",
        "sector": "Utilities"
    },
    "SOLV": {
        "name": "Solventum",
        "sector": "Health Care"
    },
    "SPG": {
        "name": "Simon Property Group",
        "sector": "Real Estate"
    },
    "SPGI": {
        "name": "S&P Global",
        "sector": "Financials"
    },
    "SRE": {
        "name": "Sempra",
        "sector": "Utilities"
    },
    "STE": {
        "name": "Steris",
        "sector": "Health Care"
    },
    "STLD": {
        "name": "Steel Dynamics",
        "sector": "Materials"
    },
    "STT": {
        "name": "State Street Corporation",
        "sector": "Financials"
    },
    "STX": {
        "name": "Seagate Technology",
        "sector": "Information Technology"
    },
    "STZ": {
        "name": "Constellation Brands",
        "sector": "Consumer Staples"
    },
    "SW": {
        "name": "Smurfit Westrock",
        "sector": "Materials"
    },
    "SWK": {
        "name": "Stanley Black & Decker",
        "sector": "Industrials"
    },
    "SWKS": {
        "name": "Skyworks Solutions",
        "sector": "Information Technology"
    },
    "SYF": {
        "name": "Synchrony Financial",
        "sector": "Financials"
    },
    "SYK": {
        "name": "Stryker Corporation",
        "sector": "Health Care"
    },
    "SYY": {
        "name": "Sysco",
        "sector": "Consumer Staples"
    },
    "T": {
        "name": "AT&T",
        "sector": "Communication Services"
    },
    "TAP": {
        "name": "Molson Coors Beverage Company",
        "sector": "Consumer Staples"
    },
    "TDG": {
        "name": "TransDigm Group",
        "sector": "Industrials"
    },
    "TDY": {
        "name": "Teledyne Technologies",
        "sector": "Information Technology"
    },
    "TECH": {
        "name": "Bio-Techne",
        "sector": "Health Care"
    },
    "TEL": {
        "name": "TE Connectivity",
        "sector": "Information Technology"
    },
    "TER": {
        "name": "Teradyne",
        "sector": "Information Technology"
    },
    "TFC": {
        "name": "Truist Financial",
        "sector": "Financials"
    },
    "TGT": {
        "name": "Target Corporation",
        "sector": "Consumer Staples"
    },
    "TJX": {
        "name": "TJX Companies",
        "sector": "Consumer Discretionary"
    },
    "TKO": {
        "name": "TKO Group Holdings",
        "sector": "Communication Services"
    },
    "TMO": {
        "name": "Thermo Fisher Scientific",
        "sector": "Health Care"
    },
    "TMUS": {
        "name": "T-Mobile US",
        "sector": "Communication Services"
    },
    "TPL": {
        "name": "Texas Pacific Land Corporation",
        "sector": "Energy"
    },
    "TPR": {
        "name": "Tapestry, Inc.",
        "sector": "Consumer Discretionary"
    },
    "TRGP": {
        "name": "Targa Resources",
        "sector": "Energy"
    },
    "TRMB": {
        "name": "Trimble Inc.",
        "sector": "Information Technology"
    },
    "TROW": {
        "name": "T. Rowe Price",
        "sector": "Financials"
    },
    "TRV": {
        "name": "Travelers Companies (The)",
        "sector": "Financials"
    },
    "TSCO": {
        "name": "Tractor Supply",
        "sector": "Consumer Discretionary"
    },
    "TSLA": {
        "name": "Tesla, Inc.",
        "sector": "Consumer Discretionary"
    },
    "TSN": {
        "name": "Tyson Foods",
        "sector": "Consumer Staples"
    },
    "TT": {
        "name": "Trane Technologies",
        "sector": "Industrials"
    },
    "TTD": {
        "name": "Trade Desk (The)",
        "sector": "Communication Services"
    },
    "TTWO": {
        "name": "Take-Two Interactive",
        "sector": "Communication Services"
    },
    "TXN": {
        "name": "Texas Instruments",
        "sector": "Information Technology"
    },
    "TXT": {
        "name": "Textron",
        "sector": "Industrials"
    },
    "TYL": {
        "name": "Tyler Technologies",
        "sector": "Information Technology"
    },
    "UAL": {
        "name": "United Airlines Holdings",
        "sector": "Industrials"
    },
    "UBER": {
        "name": "Uber",
        "sector": "Industrials"
    },
    "UDR": {
        "name": "UDR, Inc.",
        "sector": "Real Estate"
    },
    "UHS": {
        "name": "Universal Health Services",
        "sector": "Health Care"
    },
    "ULTA": {
        "name": "Ulta Beauty",
        "sector": "Consumer Discretionary"
    },
    "UNH": {
        "name": "UnitedHealth Group",
        "sector": "Health Care"
    },
    "UNP": {
        "name": "Union Pacific Corporation",
        "sector": "Industrials"
    },
    "UPS": {
        "name": "United Parcel Service",
        "sector": "Industrials"
    },
    "URI": {
        "name": "United Rentals",
        "sector": "Industrials"
    },
    "USB": {
        "name": "U.S. Bancorp",
        "sector": "Financials"
    },
    "V": {
        "name": "Visa Inc.",
        "sector": "Financials"
    },
    "VEEV": {
        "name": "Veeva Systems",
        "sector": "Health Care"
    },
    "VICI": {
        "name": "Vici Properties",
        "sector": "Real Estate"
    },
    "VLO": {
        "name": "Valero Energy",
        "sector": "Energy"
    },
    "VLTO": {
        "name": "Veralto",
        "sector": "Industrials"
    },
    "VMC": {
        "name": "Vulcan Materials Company",
        "sector": "Materials"
    },
    "VRSK": {
        "name": "Verisk Analytics",
        "sector": "Industrials"
    },
    "VRSN": {
        "name": "Verisign",
        "sector": "Information Technology"
    },
    "VRT": {
        "name": "Vertiv",
        "sector": "Industrials"
    },
    "VRTX": {
        "name": "Vertex Pharmaceuticals",
        "sector": "Health Care"
    },
    "VST": {
        "name": "Vistra Corp.",
        "sector": "Utilities"
    },
    "VTR": {
        "name": "Ventas",
        "sector": "Real Estate"
    },
    "VTRS": {
        "name": "Viatris",
        "sector": "Health Care"
    },
    "VZ": {
        "name": "Verizon",
        "sector": "Communication Services"
    },
    "WAB": {
        "name": "Wabtec",
        "sector": "Industrials"
    },
    "WAT": {
        "name": "Waters Corporation",
        "sector": "Health Care"
    },
    "WBD": {
        "name": "Warner Bros. Discovery",
        "sector": "Communication Services"
    },
    "WDAY": {
        "name": "Workday, Inc.",
        "sector": "Information Technology"
    },
    "WDC": {
        "name": "Western Digital",
        "sector": "Information Technology"
    },
    "WEC": {
        "name": "WEC Energy Group",
        "sector": "Utilities"
    },
    "WELL": {
        "name": "Welltower",
        "sector": "Real Estate"
    },
    "WFC": {
        "name": "Wells Fargo",
        "sector": "Financials"
    },
    "WM": {
        "name": "Waste Management",
        "sector": "Industrials"
    },
    "WMB": {
        "name": "Williams Companies",
        "sector": "Energy"
    },
    "WMT": {
        "name": "Walmart",
        "sector": "Consumer Staples"
    },
    "WRB": {
        "name": "W. R. Berkley Corporation",
        "sector": "Financials"
    },
    "WSM": {
        "name": "Williams-Sonoma, Inc.",
        "sector": "Consumer Discretionary"
    },
    "WST": {
        "name": "West Pharmaceutical Services",
        "sector": "Health Care"
    },
    "WTW": {
        "name": "Willis Towers Watson",
        "sector": "Financials"
    },
    "WY": {
        "name": "Weyerhaeuser",
        "sector": "Real Estate"
    },
    "WYNN": {
        "name": "Wynn Resorts",
        "sector": "Consumer Discretionary"
    },
    "XEL": {
        "name": "Xcel Energy",
        "sector": "Utilities"
    },
    "XOM": {
        "name": "ExxonMobil",
        "sector": "Energy"
    },
    "XYL": {
        "name": "Xylem Inc.",
        "sector": "Industrials"
    },
    "XYZ": {
        "name": "Block, Inc.",
        "sector": "Financials"
    },
    "YUM": {
        "name": "Yum! Brands",
        "sector": "Consumer Discretionary"
    },
    "ZBH": {
        "name": "Zimmer Biomet",
        "sector": "Health Care"
    },
    "ZBRA": {
        "name": "Zebra Technologies",
        "sector": "Information Technology"
    },
    "ZTS": {
        "name": "Zoetis",
        "sector": "Health Care"
    }
}


SP500_TICKERS: list[str] = sorted(SP500_META)


def resolve_sp500_universe() -> list[str]:
    """Liefert die statische S&P-500-Symbolliste (sortiert). Keine Netzabfrage."""
    return sorted(SP500_META)


def company_name(ticker: str) -> str | None:
    """Firmenname zum Ticker, oder None wenn nicht im S&P-500-Universum."""
    m = SP500_META.get((ticker or "").strip().upper())
    return m["name"] if m else None


def gics_sector(ticker: str) -> str | None:
    """GICS-Sektor zum Ticker, oder None wenn nicht im S&P-500-Universum."""
    m = SP500_META.get((ticker or "").strip().upper())
    return m["sector"] if m else None
